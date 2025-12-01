"""
Main Coordinator Service - Binlog-Based Replication

This is the central component that handles all client requests.
It coordinates between all other services to provide:
- Distributed timestamp assignment
- Binlog-based replication with eventual quorum consistency
- Performance-aware leader election on failure with binlog rewiring

Flow:
1. Client sends SQL query
2. Coordinator parses query
3. For writes: 
   - Check replica health (pre-flight check)
   - Get timestamp → Execute on master
   - Wait for replica to catch up to timestamp (post-write verification)
   - Return success/failure based on quorum achievement
4. For reads: Route to up-to-date replica or master
5. On master failure: Elect new leader via SEER and rewire binlog replication
"""

import asyncio
import os
import random
import threading
import time
import mysql.connector
import httpx
from typing import Dict, List, Optional
from enum import Enum
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import subprocess
from query_parser import parse_query, is_write_query, is_read_query

app = FastAPI()

# Add CORS middleware to allow frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "rootpass")
MYSQL_MASTER_HOST = os.getenv("MYSQL_MASTER_HOST", "mysql-instance-1")

# Instance configuration (master + 3 replicas)
MYSQL_INSTANCES = [
    {"id": "instance-1", "host": MYSQL_MASTER_HOST, "container": "mysql-instance-1"},
    {"id": "instance-2", "host": os.getenv("MYSQL_REPLICA_2_HOST", "mysql-instance-2"), "container": "mysql-instance-2"},
    {"id": "instance-3", "host": os.getenv("MYSQL_REPLICA_3_HOST", "mysql-instance-3"), "container": "mysql-instance-3"},
    {"id": "instance-4", "host": os.getenv("MYSQL_REPLICA_4_HOST", "mysql-instance-4"), "container": "mysql-instance-4"},
]

TIMESTAMP_SERVICES = [
    os.getenv("TIMESTAMP_SERVICE_1_URL", "http://timestamp-service-1:8000"),
    os.getenv("TIMESTAMP_SERVICE_2_URL", "http://timestamp-service-2:8000"),
]

CABINET_SERVICE_URL = os.getenv("CABINET_SERVICE_URL", "http://cabinet-service:8000")
SEER_SERVICE_URL = os.getenv("SEER_SERVICE_URL", "http://seer-service:8000")
METRICS_COLLECTOR_URL = os.getenv("METRICS_COLLECTOR_URL", "http://metrics-collector:8000")

# Global state
state_lock = threading.Lock()
current_master = {"id": "instance-1", "host": MYSQL_MASTER_HOST, "container": "mysql-instance-1"}
# List of current replicas (will change during failover)
current_replicas = [
    {"id": "instance-2", "host": os.getenv("MYSQL_REPLICA_2_HOST", "mysql-instance-2"), "container": "mysql-instance-2"},
    {"id": "instance-3", "host": os.getenv("MYSQL_REPLICA_3_HOST", "mysql-instance-3"), "container": "mysql-instance-3"},
    {"id": "instance-4", "host": os.getenv("MYSQL_REPLICA_4_HOST", "mysql-instance-4"), "container": "mysql-instance-4"},
]

# Consistency metrics tracking
consistency_metrics = {
    "ONE": {"count": 0, "total_latency": 0.0, "failures": 0},
    "QUORUM": {"count": 0, "total_latency": 0.0, "failures": 0, "quorum_not_achieved": 0},
    "ALL": {"count": 0, "total_latency": 0.0, "failures": 0}
}
metrics_lock = threading.Lock()


class ConsistencyLevel(str, Enum):
    """Consistency levels for read and write operations"""
    ONE = "ONE"
    QUORUM = "QUORUM"
    ALL = "ALL"


class QueryRequest(BaseModel):
    """Request model for SQL queries"""
    query: str
    consistency: ConsistencyLevel = ConsistencyLevel.QUORUM  # Default to QUORUM


class QueryResponse(BaseModel):
    """Response model for query execution"""
    success: bool
    message: str
    timestamp: Optional[int] = None
    rows_affected: Optional[int] = None
    data: Optional[List[Dict]] = None
    executed_on: Optional[str] = None
    consistency_level: Optional[str] = None
    latency_ms: Optional[float] = None
    quorum_achieved: Optional[bool] = None
    replica_caught_up: Optional[bool] = None


def get_mysql_connection(host: str):
    """
    Create a MySQL connection to the specified host.
    
    Args:
        host: MySQL host address
        
    Returns:
        MySQL connection object
        
    Raises:
        Exception: If connection fails
    """
    return mysql.connector.connect(
        host=host,
        port=3306,
        user="root",
        password=MYSQL_PASSWORD,
        database="testdb",
        autocommit=True
    )


async def get_timestamp() -> int:
    """
    Get a globally ordered timestamp from one of the timestamp services.
    
    Load balances between the two timestamp services.
    
    Returns:
        Timestamp value
        
    Raises:
        HTTPException: If timestamp cannot be obtained
    """
    # Randomly select a timestamp service for load balancing
    service_url = random.choice(TIMESTAMP_SERVICES)
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{service_url}/timestamp", timeout=5.0)
            response.raise_for_status()
            data = response.json()
            return data["timestamp"]
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Failed to get timestamp: {str(e)}")


def execute_query_on_host(host: str, query: str, timestamp: Optional[int] = None) -> Dict:
    """
    Execute a SQL query on a specific MySQL host.
    
    For write queries, also updates the metadata table with the timestamp.
    
    Args:
        host: MySQL host address
        query: SQL query to execute
        timestamp: Optional timestamp for write operations
        
    Returns:
        Dictionary with execution results
    """
    try:
        conn = get_mysql_connection(host)
        cursor = conn.cursor(dictionary=True)
        
        # Execute the main query
        cursor.execute(query)
        
        # For write queries, update metadata with timestamp
        if timestamp is not None:
            cursor.execute(
                "UPDATE _metadata SET last_applied_timestamp = %s WHERE id = 1",
                (timestamp,)
            )
        
        # Get results
        rows_affected = cursor.rowcount
        data = None
        
        # For SELECT queries, fetch results
        if query.strip().upper().startswith("SELECT"):
            data = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        return {
            "success": True,
            "rows_affected": rows_affected,
            "data": data
        }
    
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def get_last_applied_timestamp(host: str) -> int:
    """
    Get the last applied timestamp from a MySQL instance.
    
    Args:
        host: MySQL host address
        
    Returns:
        Last applied timestamp or 0 if unavailable
    """
    try:
        conn = get_mysql_connection(host)
        cursor = conn.cursor()
        cursor.execute("SELECT last_applied_timestamp FROM _metadata LIMIT 1")
        result = cursor.fetchone()
        cursor.close()
        conn.close()
        
        return result[0] if result else 0
    except Exception as e:
        print(f"Error getting timestamp from {host}: {e}")
        return 0


async def check_replicas_health() -> dict:
    """
    Pre-flight check: Verify replicas are healthy and caught up.
    
    Returns:
        Dictionary with healthy replica count and list of healthy replicas
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{METRICS_COLLECTOR_URL}/metrics", timeout=5.0)
            response.raise_for_status()
            data = response.json()
            replicas = data.get("replicas", [])
            
            if not replicas:
                return {"healthy_count": 0, "healthy_replicas": []}
            
            # Consider healthy if latency < 5s and lag < 10 timestamps
            healthy_replicas = [
                r for r in replicas 
                if r["is_healthy"] and r["replication_lag"] < 10
            ]
            
            return {
                "healthy_count": len(healthy_replicas),
                "healthy_replicas": healthy_replicas,
                "total_replicas": len(replicas)
            }
    except Exception as e:
        print(f"Error checking replica health: {e}")
        return {"healthy_count": 0, "healthy_replicas": []}


async def wait_for_quorum_catchup(timestamp: int, quorum_size: int = 2, timeout_seconds: float = 5.0) -> dict:
    """
    Post-write verification: Wait for quorum of replicas to catch up to the given timestamp.
    
    Args:
        timestamp: Target timestamp to wait for
        quorum_size: Number of replicas needed for quorum (default 2 out of 3)
        timeout_seconds: Maximum time to wait
        
    Returns:
        Dictionary with caught_up count and list of caught up replicas
    """
    start_time = time.time()
    
    with state_lock:
        replica_hosts = [(r["id"], r["host"]) for r in current_replicas]
    
    caught_up_replicas = []
    
    while (time.time() - start_time) < timeout_seconds:
        caught_up_replicas = []
        
        for replica_id, replica_host in replica_hosts:
            try:
                replica_timestamp = get_last_applied_timestamp(replica_host)
                
                if replica_timestamp >= timestamp:
                    caught_up_replicas.append(replica_id)
            except Exception as e:
                print(f"Error checking replica {replica_id} timestamp: {e}")
        
        # Check if we have quorum
        if len(caught_up_replicas) >= quorum_size:
            return {
                "quorum_achieved": True,
                "caught_up_count": len(caught_up_replicas),
                "caught_up_replicas": caught_up_replicas
            }
        
        # Wait a bit before checking again
        await asyncio.sleep(0.1)
    
    return {
        "quorum_achieved": False,
        "caught_up_count": len(caught_up_replicas),
        "caught_up_replicas": caught_up_replicas
    }


async def promote_replica_to_master(replica_container: str) -> bool:
    """
    Promote a replica to master by stopping replication and disabling read-only.
    
    Args:
        replica_container: Container name of the replica to promote
        
    Returns:
        True if promotion successful, False otherwise
    """
    try:
        print(f"Promoting {replica_container} to master...")
        
        # SQL commands to promote replica to master
        promote_sql = """
            STOP SLAVE;
            RESET SLAVE ALL;
            SET GLOBAL read_only = OFF;
            SET GLOBAL super_read_only = OFF;
            RESET MASTER;
        """
        
        # Execute directly using docker exec
        result = subprocess.run(
            ["docker", "exec", replica_container, "mysql", "-u", "root", "-prootpass", "-e", promote_sql],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode != 0:
            print(f"Failed to promote replica: {result.stderr}")
            return False
        
        print(f"Successfully promoted {replica_container} to master")
        return True
    except Exception as e:
        print(f"Error promoting replica: {e}")
        return False


async def demote_master_to_replica(old_master_container: str, new_master_host: str) -> bool:
    """
    Demote old master to replica by configuring it to replicate from new master.
    
    Args:
        old_master_container: Container name of the old master
        new_master_host: Host name of the new master
        
    Returns:
        True if demotion successful, False otherwise
    """
    try:
        print(f"Demoting {old_master_container} to replica of {new_master_host}...")
        
        # Determine the correct server_id based on container name
        server_id_map = {
            "mysql-instance-1": 1,
            "mysql-instance-2": 2,
            "mysql-instance-3": 3,
            "mysql-instance-4": 4,
        }
        server_id = server_id_map.get(old_master_container, 100)
        
        # SQL commands to demote master to replica (including server_id fix)
        demote_sql = f"""
            SET GLOBAL server_id = {server_id};
            SET GLOBAL read_only = ON;
            SET GLOBAL super_read_only = ON;
            STOP SLAVE;
            RESET SLAVE ALL;
            CHANGE MASTER TO
                MASTER_HOST='{new_master_host}',
                MASTER_USER='replicator',
                MASTER_PASSWORD='replicator_password',
                MASTER_AUTO_POSITION=1,
                GET_MASTER_PUBLIC_KEY=1;
            START SLAVE;
        """
        
        # Execute directly using docker exec
        result = subprocess.run(
            ["docker", "exec", old_master_container, "mysql", "-u", "root", "-prootpass", "-e", demote_sql],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode != 0:
            print(f"Failed to demote master: {result.stderr}")
            return False
        
        print(f"Successfully demoted {old_master_container} to replica")
        return True
    except Exception as e:
        print(f"Error demoting master: {e}")
        return False


async def handle_write_query(query: str, consistency: ConsistencyLevel) -> QueryResponse:
    """
    Handle a write query with binlog-based replication and eventual quorum consistency.
    
    Consistency Levels:
    - ONE: Write to master only, return immediately (eventual consistency)
    - QUORUM: Write to master, wait for 2 out of 3 replicas to catch up (strong consistency)
    - ALL: Write to master, wait for all 3 replicas to catch up (strongest consistency)
    
    Args:
        query: SQL write query
        consistency: Desired consistency level
        
    Returns:
        QueryResponse with execution results and metrics
    """
    global current_master, current_replicas
    
    start_time = time.time()
    
    # Step 1: Get timestamp
    timestamp = await get_timestamp()
    
    # Step 2: Pre-flight check for QUORUM/ALL consistency
    if consistency in [ConsistencyLevel.QUORUM, ConsistencyLevel.ALL]:
        health_status = await check_replicas_health()
        
        required_healthy = 2 if consistency == ConsistencyLevel.QUORUM else 3
        
        if health_status["healthy_count"] < required_healthy:
            with metrics_lock:
                consistency_metrics[consistency.value]["failures"] += 1
            raise HTTPException(
                status_code=503,
                detail=f"Not enough healthy replicas. Need {required_healthy}, have {health_status['healthy_count']}. Cannot achieve {consistency.value} consistency."
            )
    
    # Step 3: Execute on master
    with state_lock:
        master_host = current_master["host"]
        master_container = current_master["container"]
    
    result = execute_query_on_host(master_host, query, timestamp)
    
    # Check if master execution failed
    if not result["success"]:
        # Master might be down - attempt failover
        print(f"Master execution failed: {result.get('error')}")
        
        # Use SEER to elect best replica
        try:
            async with httpx.AsyncClient() as client:
                election_response = await client.post(
                    f"{SEER_SERVICE_URL}/elect-leader",
                    json={},
                    timeout=10.0
                )
                election_response.raise_for_status()
                election_data = election_response.json()
                new_leader_id = election_data["leader_id"]
        except Exception as e:
            with metrics_lock:
                consistency_metrics[consistency.value]["failures"] += 1
            raise HTTPException(status_code=503, detail=f"Leader election failed: {str(e)}")
        
        # Find the elected replica
        with state_lock:
            elected_replica = next((r for r in current_replicas if r["id"] == new_leader_id), None)
        
        if not elected_replica:
            with metrics_lock:
                consistency_metrics[consistency.value]["failures"] += 1
            raise HTTPException(status_code=503, detail=f"Elected leader {new_leader_id} not found")
        
        # Promote elected replica to master
        promotion_success = await promote_replica_to_master(elected_replica["container"])
        
        if not promotion_success:
            with metrics_lock:
                consistency_metrics[consistency.value]["failures"] += 1
            raise HTTPException(status_code=503, detail="Failover failed: could not promote replica")
        
        # Update global state
        with state_lock:
            old_master = current_master
            current_master = elected_replica
            # Remove elected replica from replicas list and add old master
            current_replicas = [r for r in current_replicas if r["id"] != new_leader_id]
            current_replicas.append(old_master)
        
        print(f"Failover complete: new master is {current_master['id']}")
        
        # Retry on new master
        result = execute_query_on_host(current_master["host"], query, timestamp)
        
        if not result["success"]:
            with metrics_lock:
                consistency_metrics[consistency.value]["failures"] += 1
            raise HTTPException(status_code=500, detail=f"Query failed on new master: {result.get('error')}")
    
    latency_ms = (time.time() - start_time) * 1000
    
    # Consistency-specific logic
    if consistency == ConsistencyLevel.ONE:
        # ONE: Return immediately after master confirms (fastest, eventual consistency)
        # Binlog will automatically replicate to replicas
        
        with metrics_lock:
            consistency_metrics["ONE"]["count"] += 1
            consistency_metrics["ONE"]["total_latency"] += latency_ms
        
        return QueryResponse(
            success=True,
            message=f"Write successful (consistency: ONE, timestamp: {timestamp})",
            timestamp=timestamp,
            rows_affected=result["rows_affected"],
            executed_on=master_host,
            consistency_level="ONE",
            latency_ms=round(latency_ms, 2),
            quorum_achieved=None,
            replica_caught_up=None
        )
    
    elif consistency == ConsistencyLevel.QUORUM:
        # QUORUM: Wait for 2 out of 3 replicas to catch up
        catchup_result = await wait_for_quorum_catchup(timestamp, quorum_size=2, timeout_seconds=5.0)
        
        latency_ms = (time.time() - start_time) * 1000
        
        if not catchup_result["quorum_achieved"]:
            # Write succeeded on master but quorum didn't catch up in time
            with metrics_lock:
                consistency_metrics["QUORUM"]["count"] += 1
                consistency_metrics["QUORUM"]["total_latency"] += latency_ms
                consistency_metrics["QUORUM"]["quorum_not_achieved"] += 1
            
            return QueryResponse(
                success=True,
                message=f"Write successful on master (timestamp: {timestamp}), but only {catchup_result['caught_up_count']}/3 replicas caught up. Data will eventually propagate via binlog.",
                timestamp=timestamp,
                rows_affected=result["rows_affected"],
                executed_on=master_host,
                consistency_level="QUORUM",
                latency_ms=round(latency_ms, 2),
                quorum_achieved=False,
                replica_caught_up=False
            )
        
        # Quorum achieved - 2+ replicas caught up
        with metrics_lock:
            consistency_metrics["QUORUM"]["count"] += 1
            consistency_metrics["QUORUM"]["total_latency"] += latency_ms
        
        return QueryResponse(
            success=True,
            message=f"Write successful (consistency: QUORUM, timestamp: {timestamp}, {catchup_result['caught_up_count']}/3 replicas confirmed)",
            timestamp=timestamp,
            rows_affected=result["rows_affected"],
            executed_on=master_host,
            consistency_level="QUORUM",
            latency_ms=round(latency_ms, 2),
            quorum_achieved=True,
            replica_caught_up=True
        )
    
    else:  # ConsistencyLevel.ALL
        # ALL: Wait for all 3 replicas to catch up
        catchup_result = await wait_for_quorum_catchup(timestamp, quorum_size=3, timeout_seconds=5.0)
        
        latency_ms = (time.time() - start_time) * 1000
        
        if not catchup_result["quorum_achieved"]:
            # Write succeeded on master but not all replicas caught up
            with metrics_lock:
                consistency_metrics["ALL"]["count"] += 1
                consistency_metrics["ALL"]["total_latency"] += latency_ms
                consistency_metrics["ALL"]["quorum_not_achieved"] += 1
            
            return QueryResponse(
                success=True,
                message=f"Write successful on master (timestamp: {timestamp}), but only {catchup_result['caught_up_count']}/3 replicas caught up. Data will eventually propagate via binlog.",
                timestamp=timestamp,
                rows_affected=result["rows_affected"],
                executed_on=master_host,
                consistency_level="ALL",
                latency_ms=round(latency_ms, 2),
                quorum_achieved=False,
                replica_caught_up=False
            )
        
        # All replicas caught up
        with metrics_lock:
            consistency_metrics["ALL"]["count"] += 1
            consistency_metrics["ALL"]["total_latency"] += latency_ms
        
        return QueryResponse(
            success=True,
            message=f"Write successful (consistency: ALL, timestamp: {timestamp}, all 3 replicas confirmed)",
            timestamp=timestamp,
            rows_affected=result["rows_affected"],
            executed_on=master_host,
            consistency_level="ALL",
            latency_ms=round(latency_ms, 2),
            quorum_achieved=True,
            replica_caught_up=True
        )


async def handle_read_query(query: str, consistency: ConsistencyLevel) -> QueryResponse:
    """
    Handle a read query with tunable consistency.
    
    Consistency Levels:
    - ONE: Read from replica if healthy, otherwise master
    - QUORUM/ALL: Read from master for strong consistency
    
    Args:
        query: SQL read query
        consistency: Desired consistency level
        
    Returns:
        QueryResponse with query results and metrics
    """
    start_time = time.time()
    
    if consistency == ConsistencyLevel.ONE:
        # Try replica first for load balancing
        health_status = await check_replicas_health()
        
        with state_lock:
            # Pick a healthy replica if available, otherwise use master
            if current_replicas and health_status["healthy_count"] > 0:
                # Pick a random replica for load balancing
                replica = random.choice(current_replicas)
                replica_host = replica["host"]
            else:
                replica_host = None
            master_host = current_master["host"]
        
        if replica_host and health_status["healthy_count"] > 0:
            result = execute_query_on_host(replica_host, query)
            read_host = replica_host
        else:
            result = execute_query_on_host(master_host, query)
            read_host = master_host
        
        if not result["success"]:
            with metrics_lock:
                consistency_metrics["ONE"]["failures"] += 1
            raise HTTPException(status_code=500, detail=f"Query failed: {result.get('error')}")
        
        latency_ms = (time.time() - start_time) * 1000
        
        with metrics_lock:
            consistency_metrics["ONE"]["count"] += 1
            consistency_metrics["ONE"]["total_latency"] += latency_ms
        
        return QueryResponse(
            success=True,
            message="Read successful (consistency: ONE)",
            data=result["data"],
            rows_affected=len(result["data"]) if result["data"] else 0,
            executed_on=read_host,
            consistency_level="ONE",
            latency_ms=round(latency_ms, 2)
        )
    
    else:  # QUORUM or ALL - read from master for strong consistency
        with state_lock:
            master_host = current_master["host"]
        
        result = execute_query_on_host(master_host, query)
        
        if not result["success"]:
            with metrics_lock:
                consistency_metrics[consistency.value]["failures"] += 1
            raise HTTPException(status_code=500, detail=f"Query failed: {result.get('error')}")
        
        latency_ms = (time.time() - start_time) * 1000
        
        with metrics_lock:
            consistency_metrics[consistency.value]["count"] += 1
            consistency_metrics[consistency.value]["total_latency"] += latency_ms
        
        return QueryResponse(
            success=True,
            message=f"Read successful (consistency: {consistency.value})",
            data=result["data"],
            rows_affected=len(result["data"]) if result["data"] else 0,
            executed_on=master_host,
            consistency_level=consistency.value,
            latency_ms=round(latency_ms, 2)
        )


@app.post("/query", response_model=QueryResponse)
async def execute_query(request: QueryRequest):
    """
    Main endpoint for executing SQL queries.
    
    Handles both read and write queries:
    - Writes: Timestamped, replicated via binlog, with quorum verification
    - Reads: Routed to replica (ONE) or master (QUORUM/ALL)
    
    Args:
        request: QueryRequest containing SQL query
        
    Returns:
        QueryResponse with execution results
    """
    query = request.query.strip()
    
    if not query:
        raise HTTPException(status_code=400, detail="Query cannot be empty")
    
    # Parse query
    query_type, tables = parse_query(query)
    
    if query_type == "UNKNOWN":
        raise HTTPException(status_code=400, detail="Unsupported query type")
    
    # Route based on query type with consistency level
    if is_write_query(query_type):
        return await handle_write_query(query, request.consistency)
    elif is_read_query(query_type):
        return await handle_read_query(query, request.consistency)
    else:
        raise HTTPException(status_code=400, detail="Invalid query type")


@app.get("/status")
async def get_status():
    """Get current system status"""
    with state_lock:
        return {
            "current_master": current_master,
            "current_replicas": current_replicas,
            "total_replicas": len(current_replicas),
            "replication_mode": "binlog"
        }


@app.get("/consistency-metrics")
async def get_consistency_metrics():
    """Get consistency level performance metrics"""
    with metrics_lock:
        metrics_summary = {}
        for level, data in consistency_metrics.items():
            avg_latency = (
                data["total_latency"] / data["count"] 
                if data["count"] > 0 
                else 0
            )
            metrics_summary[level] = {
                "count": data["count"],
                "avg_latency_ms": round(avg_latency, 2),
                "failures": data["failures"],
                "quorum_not_achieved": data.get("quorum_not_achieved", 0),
                "success_rate": (
                    round((data["count"] / (data["count"] + data["failures"]) * 100), 2)
                    if (data["count"] + data["failures"]) > 0
                    else 100.0
                )
            }
        return metrics_summary


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "coordinator"}


@app.post("/admin/stop-master")
async def stop_master():
    """
    Stop the current MySQL master container to simulate failure.
    This will trigger automatic failover and binlog rewiring.
    """
    global current_master, current_replicas
    
    try:
        with state_lock:
            master_container = current_master["container"]
            # Pick the first replica as the new master for simplicity in forced failure
            # In a real scenario, we might want to consult SEER even here
            if not current_replicas:
                 return {
                    "success": False,
                    "message": "No replicas available to promote",
                    "error": "No replicas found"
                }
            new_master_info = current_replicas[0]
            replica_container = new_master_info["container"]
            new_master_id = new_master_info["id"]
        
        # Step 1: Stop the master container
        print(f"Stopping {master_container} container...")
        result = subprocess.run(
            ["docker", "stop", master_container],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode != 0:
            print(f"Failed to stop master: {result.stderr}")
            return {
                "success": False,
                "message": "Failed to stop master",
                "error": result.stderr
            }
        
        print("Master stopped successfully")
        
        # Step 2: Wait for container to stop
        await asyncio.sleep(2)
        
        # Step 3: Promote replica to master
        promotion_success = await promote_replica_to_master(replica_container)
        
        if not promotion_success:
            return {
                "success": False,
                "message": "Master stopped but replica promotion failed",
                "error": "Could not promote replica to master"
            }
        
        # Step 4: Update global state
        with state_lock:
            old_master = current_master
            current_master = new_master_info
            # Remove new master from replicas list
            current_replicas = [r for r in current_replicas if r["id"] != new_master_id]
            # We don't add the stopped master back to replicas yet, it needs to be restarted first
            
        return {
            "success": True,
            "message": f"Failover complete. New master: {current_master['id']}",
            "old_master": old_master["id"],
            "new_master": current_master["id"],
            "new_leader_id": current_master["id"]
        }
            
    except Exception as e:
        return {
            "success": False,
            "message": "Failover failed",
            "error": str(e)
        }

class FailoverRequest(BaseModel):
    new_leader: Optional[str] = None


@app.post("/admin/trigger-failover")
async def trigger_failover(request: FailoverRequest):
    """
    Trigger a graceful failover to a specific replica (or elect one).
    This does NOT stop the old master container, but demotes it to a replica.
    """
    global current_master, current_replicas
    
    try:
        target_replica = None
        
        with state_lock:
            # If new_leader provided, find it
            if request.new_leader:
                target_replica = next((r for r in current_replicas if r["id"] == request.new_leader), None)
                if not target_replica:
                     return {
                        "success": False,
                        "message": f"Target replica {request.new_leader} not found",
                        "error": "Replica not found"
                    }
            # Otherwise pick the first one (or we could call SEER here)
            elif current_replicas:
                target_replica = current_replicas[0]
            else:
                return {
                    "success": False,
                    "message": "No replicas available for failover",
                    "error": "No replicas found"
                }
            
            old_master_container = current_master["container"]
            old_master_id = current_master["id"]
            new_master_container = target_replica["container"]
            new_master_host = target_replica["host"]
            new_master_id = target_replica["id"]

        print(f"Triggering graceful failover from {old_master_id} to {new_master_id}...")

        # Step 1: Demote current master to replica of new master
        # Note: We need to promote the new master first so it can accept connections? 
        # Actually, usually we promote new master, then demote old master.
        # But if we promote new master first, we might have split brain for a moment.
        # Safe sequence:
        # 1. Set old master read-only (demote script does this)
        # 2. Promote new master (reset slave, read-write)
        # 3. Configure old master to replicate from new master
        
        # Let's use our scripts. 
        
        # 1. Promote new master
        promotion_success = await promote_replica_to_master(new_master_container)
        if not promotion_success:
             return {
                "success": False,
                "message": "Failed to promote new master",
                "error": "Promotion failed"
            }
            
        # 2. Demote old master
        demotion_success = await demote_master_to_replica(old_master_container, new_master_host)
        if not demotion_success:
             # This is bad, we have two masters or old master is in weird state.
             # But new master is active, so we can proceed with state update.
             print("Warning: Failed to demote old master, but new master is promoted.")
        
        # Step 3: Update global state
        with state_lock:
            old_master_obj = current_master
            current_master = target_replica
            
            # Update replicas list: remove new master, add old master
            current_replicas = [r for r in current_replicas if r["id"] != new_master_id]
            current_replicas.append(old_master_obj)
            
        return {
            "success": True,
            "message": f"Graceful failover complete. New master: {new_master_id}",
            "old_master": old_master_id,
            "new_master": new_master_id,
            "new_leader_id": new_master_id
        }

    except Exception as e:
        return {
            "success": False,
            "message": "Graceful failover failed",
            "error": str(e)
        }


@app.post("/admin/restart-old-master")
async def restart_old_master():
    """
    Restart the old master (mysql-instance-1) and configure it as a replica of the current master.
    This is called after a failover to bring the old master back online.
    """
    global current_master, current_replicas
    
    try:
        # The old master is always mysql-instance-1
        old_master_container = "mysql-instance-1"
        old_master_id = "instance-1"
        
        with state_lock:
            new_master_host = current_master["host"]
            # Check if old master is already in replicas (already recovered)
            already_replica = any(r["id"] == old_master_id for r in current_replicas)
        
        if already_replica:
            return {
                "success": True,
                "message": f"{old_master_id} is already configured as a replica",
                "master": current_master["id"]
            }
        
        # Step 1: Start the old master container
        print(f"Starting {old_master_container} container...")
        result = subprocess.run(
            ["docker", "start", old_master_container],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode != 0:
            return {
                "success": False,
                "message": "Failed to start old master",
                "error": result.stderr
            }
        
        # Step 2: Wait for container to start
        await asyncio.sleep(5)
        
        # Step 3: Demote old master to replica
        demotion_success = await demote_master_to_replica(old_master_container, new_master_host)
        
        if not demotion_success:
            return {
                "success": False,
                "message": "Old master started but demotion to replica failed",
                "error": "Could not configure replication"
            }
        
        # Step 4: Add old master back to replicas list
        with state_lock:
            old_master_info = {
                "id": old_master_id,
                "host": "mysql-instance-1",
                "container": old_master_container
            }
            current_replicas.append(old_master_info)
        
        return {
            "success": True,
            "message": f"Old master ({old_master_id}) restarted and configured as replica of {current_master['id']}",
            "master": current_master["id"],
            "total_replicas": len(current_replicas)
        }
    
    except Exception as e:
        return {
            "success": False,
            "message": "Restart failed",
            "error": str(e)
        }

class StartInstanceRequest(BaseModel):
    """Request model for starting a MySQL instance"""
    instance_id: str  # e.g., "instance-1", "instance-2", etc.


class TopologyResponse(BaseModel):
    """Response model showing current cluster topology"""
    current_master: Dict
    current_replicas: List[Dict]
    total_replicas: int


async def wait_for_mysql_ready(container: str, max_retries: int = 30) -> bool:
    """
    Wait for MySQL to be ready to accept connections.
    
    Args:
        container: Docker container name
        max_retries: Maximum number of retry attempts (default 30 = 30 seconds)
        
    Returns:
        True if MySQL is ready, False otherwise
    """
    for i in range(max_retries):
        try:
            result = subprocess.run(
                ["docker", "exec", container, "mysqladmin", "-u", "root", "-prootpass", "ping"],
                capture_output=True,
                text=True,
                timeout=2
            )
            
            if result.returncode == 0 and "mysqld is alive" in result.stdout:
                print(f"MySQL in {container} is ready")
                return True
        except Exception as e:
            print(f"Waiting for MySQL in {container}... ({i+1}/{max_retries})")
        
        await asyncio.sleep(1)
    
    return False


async def configure_replica(replica_container: str, master_host: str) -> bool:
    """
    Configure a MySQL instance as a replica of the specified master.
    This version is more robust for restarted containers with detailed diagnostics.
    
    Args:
        replica_container: Container name of the replica
        master_host: Host name of the master
        
    Returns:
        True if configuration successful, False otherwise
    """
    try:
        print(f"Configuring {replica_container} as replica of {master_host}...")
        
        # Wait for MySQL to be fully ready
        await asyncio.sleep(3)
        
        # Determine the correct server_id based on container name
        # This is crucial to avoid "same server ID" errors after failover
        server_id_map = {
            "mysql-instance-1": 1,
            "mysql-instance-2": 2,
            "mysql-instance-3": 3,
            "mysql-instance-4": 4,
        }
        server_id = server_id_map.get(replica_container, 100)
        
        # Step 0: Set the correct server ID (crucial for avoiding conflicts)
        print(f"Setting server_id to {server_id} for {replica_container}...")
        server_id_sql = f"SET GLOBAL server_id = {server_id};"
        result = subprocess.run(
            ["docker", "exec", replica_container, "mysql", "-u", "root", "-prootpass", "-e", server_id_sql],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode != 0:
            print(f"Warning: Could not set server_id: {result.stderr}")
        else:
            print(f"Server ID set to {server_id}")
        
        await asyncio.sleep(1)
        
        # Step 1: Verify replicator user exists on master
        print(f"Verifying replicator user on master {master_host}...")
        verify_user_sql = "SELECT User, Host FROM mysql.user WHERE User='replicator';"
        result = subprocess.run(
            ["docker", "exec", replica_container, "mysql", "-h", master_host, "-u", "root", "-prootpass", "-e", verify_user_sql],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode != 0:
            print(f"Cannot connect to master or replicator user missing: {result.stderr}")
            print("Creating replicator user on master...")
            create_user_sql = """
                CREATE USER IF NOT EXISTS 'replicator'@'%' IDENTIFIED WITH mysql_native_password BY 'replicator_password';
                GRANT REPLICATION SLAVE ON *.* TO 'replicator'@'%';
                FLUSH PRIVILEGES;
            """
            # Try to create user on master
            master_container = None
            with state_lock:
                for inst in MYSQL_INSTANCES:
                    if inst["host"] == master_host:
                        master_container = inst["container"]
                        break
            
            if master_container:
                subprocess.run(
                    ["docker", "exec", master_container, "mysql", "-u", "root", "-prootpass", "-e", create_user_sql],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                print("Replicator user created")
        else:
            print(f"Replicator user verified: {result.stdout}")
        
        await asyncio.sleep(1)
        
        # Step 1: Stop any existing replication and reset
        print("Stopping existing replication...")
        stop_sql = "STOP SLAVE; RESET SLAVE ALL;"
        result = subprocess.run(
            ["docker", "exec", replica_container, "mysql", "-u", "root", "-prootpass", "-e", stop_sql],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode != 0:
            print(f"Warning: Could not stop existing replication: {result.stderr}")
        else:
            print("Existing replication stopped")
        
        await asyncio.sleep(1)
        
        # Step 2: Reset binary log (important for clean state)
        print("Resetting binary log...")
        reset_sql = "RESET MASTER;"
        result = subprocess.run(
            ["docker", "exec", replica_container, "mysql", "-u", "root", "-prootpass", "-e", reset_sql],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode != 0:
            print(f"Warning: Could not reset master: {result.stderr}")
        else:
            print("Binary log reset")
        
        await asyncio.sleep(1)
        
        # Step 3: Set read-only mode
        print("Setting read-only mode...")
        readonly_sql = "SET GLOBAL read_only = ON; SET GLOBAL super_read_only = ON;"
        result = subprocess.run(
            ["docker", "exec", replica_container, "mysql", "-u", "root", "-prootpass", "-e", readonly_sql],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode != 0:
            print(f"Failed to set read-only mode: {result.stderr}")
            return False
        
        print("Read-only mode set")
        await asyncio.sleep(1)
        
        # Step 4: Configure replication (using CHANGE REPLICATION SOURCE for MySQL 8.0.23+)
        print("Configuring replication source...")
        change_master_sql = f"""
            CHANGE REPLICATION SOURCE TO
                SOURCE_HOST='{master_host}',
                SOURCE_USER='replicator',
                SOURCE_PASSWORD='replicator_password',
                SOURCE_AUTO_POSITION=1,
                GET_SOURCE_PUBLIC_KEY=1;
        """
        
        result = subprocess.run(
            ["docker", "exec", replica_container, "mysql", "-u", "root", "-prootpass", "-e", change_master_sql],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        # If newer syntax fails, try older CHANGE MASTER TO syntax
        if result.returncode != 0:
            print(f"New syntax failed, trying legacy syntax: {result.stderr}")
            change_master_sql_legacy = f"""
                CHANGE MASTER TO
                    MASTER_HOST='{master_host}',
                    MASTER_USER='replicator',
                    MASTER_PASSWORD='replicator_password',
                    MASTER_AUTO_POSITION=1,
                    GET_MASTER_PUBLIC_KEY=1;
            """
            
            result = subprocess.run(
                ["docker", "exec", replica_container, "mysql", "-u", "root", "-prootpass", "-e", change_master_sql_legacy],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode != 0:
                print(f"Failed to configure replication (both syntaxes): {result.stderr}")
                return False
        
        print("Replication source configured")
        await asyncio.sleep(1)
        
        # Step 5: Start replication (try both syntaxes)
        print("Starting replication...")
        start_sql = "START REPLICA;"
        result = subprocess.run(
            ["docker", "exec", replica_container, "mysql", "-u", "root", "-prootpass", "-e", start_sql],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode != 0:
            print(f"New syntax failed, trying legacy: {result.stderr}")
            start_sql_legacy = "START SLAVE;"
            result = subprocess.run(
                ["docker", "exec", replica_container, "mysql", "-u", "root", "-prootpass", "-e", start_sql_legacy],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode != 0:
                print(f"Failed to start replication: {result.stderr}")
                return False
        
        print("Replication started")
        
        # Step 6: Wait for replication to initialize
        await asyncio.sleep(5)
        
        # Step 7: Verify replication status with retries
        print("Verifying replication status...")
        max_retries = 10
        for attempt in range(max_retries):
            # Try both SHOW REPLICA STATUS and SHOW SLAVE STATUS
            check_sql = "SHOW REPLICA STATUS\\G"
            result = subprocess.run(
                ["docker", "exec", replica_container, "mysql", "-u", "root", "-prootpass", "-e", check_sql],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            # Try legacy syntax if new one fails
            if result.returncode != 0:
                check_sql = "SHOW SLAVE STATUS\\G"
                result = subprocess.run(
                    ["docker", "exec", replica_container, "mysql", "-u", "root", "-prootpass", "-e", check_sql],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
            
            if result.returncode == 0:
                output = result.stdout
                
                # Print full output for debugging
                if attempt == 0:
                    print(f"Replication status:\n{output[:500]}")
                
                # Check both old and new field names
                io_running = ("Slave_IO_Running: Yes" in output or 
                             "Replica_IO_Running: Yes" in output)
                sql_running = ("Slave_SQL_Running: Yes" in output or 
                              "Replica_SQL_Running: Yes" in output)
                
                # Extract errors
                last_io_error = ""
                last_sql_error = ""
                for line in output.split('\n'):
                    if 'Last_IO_Error:' in line or 'Last_IO_Errno:' in line:
                        error_text = line.split(':', 1)[1].strip() if ':' in line else ''
                        if error_text and error_text != '0':
                            last_io_error = error_text
                    if 'Last_SQL_Error:' in line or 'Last_SQL_Errno:' in line:
                        error_text = line.split(':', 1)[1].strip() if ':' in line else ''
                        if error_text and error_text != '0':
                            last_sql_error = error_text
                
                if io_running and sql_running:
                    print(f"✓ Successfully configured {replica_container} as replica (replication active)")
                    return True
                else:
                    print(f"Replication attempt {attempt+1}/{max_retries}: IO={io_running}, SQL={sql_running}")
                    if last_io_error:
                        print(f"  IO Error: {last_io_error}")
                    if last_sql_error:
                        print(f"  SQL Error: {last_sql_error}")
                    
                    # If not the last attempt, wait and retry
                    if attempt < max_retries - 1:
                        await asyncio.sleep(3)
            else:
                print(f"Failed to check replication status: {result.stderr}")
                await asyncio.sleep(2)
        
        print(f"✗ Replication configuration failed after {max_retries} attempts")
        return False
        
    except Exception as e:
        print(f"✗ Error configuring replica: {e}")
        import traceback
        traceback.print_exc()
        return False
    
@app.post("/admin/start-instance", response_model=TopologyResponse)
async def start_instance(request: StartInstanceRequest):
    """
    Start a specific MySQL instance and configure it as a replica of the current master.
    
    This endpoint:
    1. Starts the specified MySQL container
    2. Waits for MySQL to be ready
    3. Configures it as a replica of the current master
    4. Adds it to the current_replicas list
    5. Returns the updated cluster topology
    
    Args:
        request: StartInstanceRequest with instance_id
        
    Returns:
        TopologyResponse with current master and replicas
    """
    global current_master, current_replicas
    
    try:
        instance_id = request.instance_id
        
        # Find the instance in the global MYSQL_INSTANCES list
        instance_info = next((inst for inst in MYSQL_INSTANCES if inst["id"] == instance_id), None)
        
        if not instance_info:
            raise HTTPException(
                status_code=400,
                detail=f"Instance {instance_id} not found in configuration"
            )
        
        instance_container = instance_info["container"]
        instance_host = instance_info["host"]
        
        with state_lock:
            current_master_host = current_master["host"]
            current_master_id = current_master["id"]
            
            # Check if this instance is the current master
            if instance_id == current_master_id:
                return TopologyResponse(
                    current_master=current_master,
                    current_replicas=current_replicas,
                    total_replicas=len(current_replicas)
                )
            
            # Check if instance is already a replica in state
            already_replica = any(r["id"] == instance_id for r in current_replicas)
        
        # Even if it's in the replicas list, we need to check if the container is actually running
        # and properly configured. Check container status first.
        container_running = False
        try:
            check_result = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Running}}", instance_container],
                capture_output=True,
                text=True,
                timeout=5
            )
            container_running = check_result.returncode == 0 and "true" in check_result.stdout.lower()
        except Exception as e:
            print(f"Error checking container status: {e}")
            container_running = False
        
        # If container is running and already in replicas, verify replication is working
        if already_replica and container_running:
            # Verify replication is actually working
            try:
                repl_check = subprocess.run(
                    ["docker", "exec", instance_container, "mysql", "-u", "root", "-prootpass", "-e", 
                     "SHOW SLAVE STATUS\\G"],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                if "Slave_IO_Running: Yes" in repl_check.stdout and "Slave_SQL_Running: Yes" in repl_check.stdout:
                    print(f"{instance_id} is already running and replicating correctly")
                    return TopologyResponse(
                        current_master=current_master,
                        current_replicas=current_replicas,
                        total_replicas=len(current_replicas)
                    )
            except Exception as e:
                print(f"Replication check failed: {e}")
        
        # Need to start/restart the container and configure replication
        print(f"Starting {instance_container} container...")
        result = subprocess.run(
            ["docker", "start", instance_container],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode != 0:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to start {instance_id}: {result.stderr}"
            )
        
        print(f"Container {instance_container} started successfully")
        
        # Step 2: Wait for MySQL to be ready
        mysql_ready = await wait_for_mysql_ready(instance_container, max_retries=30)
        
        if not mysql_ready:
            raise HTTPException(
                status_code=500,
                detail=f"MySQL in {instance_id} did not become ready in time"
            )
        
        # Step 3: Configure as replica of current master
        config_success = await configure_replica(instance_container, current_master_host)
        
        if not config_success:
            raise HTTPException(
                status_code=500,
                detail=f"Instance {instance_id} started but replication configuration failed. Check logs for details."
            )
        
        # Step 4: Add to replicas list (only if not already there)
        with state_lock:
            if not any(r["id"] == instance_id for r in current_replicas):
                current_replicas.append(instance_info)
            
            response = TopologyResponse(
                current_master=current_master.copy(),
                current_replicas=[r.copy() for r in current_replicas],
                total_replicas=len(current_replicas)
            )
        
        print(f"Instance {instance_id} configured as replica of {current_master_id}")
        
        return response
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to start instance: {str(e)}"
        )


@app.get("/admin/topology", response_model=TopologyResponse)
async def get_topology():
    """
    Get the current cluster topology.
    
    Returns:
        TopologyResponse with current master and all replicas
    """
    with state_lock:
        return TopologyResponse(
            current_master=current_master.copy(),
            current_replicas=[r.copy() for r in current_replicas],
            total_replicas=len(current_replicas)
        )

@app.post("/admin/stop-master-only")
async def stop_master_only(request: dict):
    """
    Stop the current MySQL master container ONLY (no election or promotion).
    The frontend will handle calling SEER and promotion separately.
    """
    global current_master, current_replicas
    
    try:
        with state_lock:
            master_container = current_master["container"]
            master_id = current_master["id"]
        
        # Stop the master container
        print(f"Stopping {master_container} container...")
        result = subprocess.run(
            ["docker", "stop", master_container],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode != 0:
            print(f"Failed to stop master: {result.stderr}")
            return {
                "success": False,
                "message": "Failed to stop master",
                "error": result.stderr
            }
        
        print(f"Master {master_container} stopped successfully")
        
        return {
            "success": True,
            "message": f"Master {master_id} stopped successfully",
            "stopped_master": master_id,
            "stopped_container": master_container
        }
            
    except Exception as e:
        return {
            "success": False,
            "message": "Failed to stop master",
            "error": str(e)
        }
# ==================== STRESS TEST ENDPOINTS ====================

class StressTestRequest(BaseModel):
    """Request model for stress tests"""
    num_operations: int = 50
    consistency: ConsistencyLevel = ConsistencyLevel.QUORUM


class StressTestResult(BaseModel):
    """Result model for stress tests"""
    test_name: str
    total_operations: int
    successful: int
    failed: int
    duration_seconds: float
    throughput_ops_per_sec: float
    avg_latency_ms: float
    min_latency_ms: float
    max_latency_ms: float
    consistency_level: str
    timestamp_range: Optional[Dict] = None
    errors: Optional[Dict] = None


@app.post("/admin/clear-data")
async def clear_test_data():
    """
    Clear all test data from the database (users and products tables).
    Keeps the schema intact.
    """
    try:
        with state_lock:
            master_host = current_master["host"]
        
        conn = get_mysql_connection(master_host)
        cursor = conn.cursor()
        
        # Clear test tables
        cursor.execute("DELETE FROM users")
        users_deleted = cursor.rowcount
        
        cursor.execute("DELETE FROM products")
        products_deleted = cursor.rowcount
        
        # Reset metadata timestamp
        cursor.execute("UPDATE _metadata SET last_applied_timestamp = 0")
        
        cursor.close()
        conn.close()
        
        # Reset consistency metrics
        with metrics_lock:
            for level in consistency_metrics:
                consistency_metrics[level] = {
                    "count": 0, 
                    "total_latency": 0.0, 
                    "failures": 0,
                    "quorum_not_achieved": 0
                }
        
        return {
            "success": True,
            "message": f"Cleared {users_deleted} users and {products_deleted} products",
            "users_deleted": users_deleted,
            "products_deleted": products_deleted
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Failed to clear data: {str(e)}",
            "error": str(e)
        }


@app.post("/admin/stress-test/concurrent-writes", response_model=StressTestResult)
async def stress_test_concurrent_writes(request: StressTestRequest):
    """
    Stress test: Concurrent write operations.
    
    Tests:
    - Timestamp ordering under load
    - Quorum-based replication performance
    - System throughput at different consistency levels
    """
    num_ops = request.num_operations
    consistency = request.consistency
    
    results = []
    latencies = []
    errors = {}
    timestamps = []
    
    # Generate unique test data
    base_ts = int(time.time() * 1000)
    
    async def single_write(i: int):
        start = time.time()
        name = f"StressUser_{base_ts}_{i}"
        email = f"stress_{base_ts}_{i}@test.com"
        query = f'INSERT INTO users (name, email) VALUES ("{name}", "{email}")'
        
        try:
            result = await handle_write_query(query, consistency)
            latency = (time.time() - start) * 1000
            return {
                "success": result.success,
                "latency_ms": latency,
                "timestamp": result.timestamp,
                "error": None
            }
        except HTTPException as e:
            latency = (time.time() - start) * 1000
            return {
                "success": False,
                "latency_ms": latency,
                "timestamp": None,
                "error": e.detail
            }
        except Exception as e:
            latency = (time.time() - start) * 1000
            return {
                "success": False,
                "latency_ms": latency,
                "timestamp": None,
                "error": str(e)
            }
    
    # Execute concurrent writes
    start_time = time.time()
    tasks = [single_write(i) for i in range(num_ops)]
    results = await asyncio.gather(*tasks)
    duration = time.time() - start_time
    
    # Analyze results
    successful = 0
    for r in results:
        latencies.append(r["latency_ms"])
        if r["success"]:
            successful += 1
            if r["timestamp"]:
                timestamps.append(r["timestamp"])
        else:
            error = r["error"] or "Unknown error"
            errors[error] = errors.get(error, 0) + 1
    
    failed = num_ops - successful
    
    return StressTestResult(
        test_name="Concurrent Writes",
        total_operations=num_ops,
        successful=successful,
        failed=failed,
        duration_seconds=round(duration, 3),
        throughput_ops_per_sec=round(num_ops / duration, 2),
        avg_latency_ms=round(sum(latencies) / len(latencies), 2) if latencies else 0,
        min_latency_ms=round(min(latencies), 2) if latencies else 0,
        max_latency_ms=round(max(latencies), 2) if latencies else 0,
        consistency_level=consistency.value,
        timestamp_range={"min": min(timestamps), "max": max(timestamps)} if timestamps else None,
        errors=errors if errors else None
    )


@app.post("/admin/stress-test/read-write-mix", response_model=StressTestResult)
async def stress_test_read_write_mix(request: StressTestRequest):
    """
    Stress test: Mixed read/write workload (70% reads, 30% writes).
    
    Tests:
    - Real-world mixed workload performance
    - Read scaling across replicas
    - Write consistency under mixed load
    """
    num_ops = request.num_operations
    consistency = request.consistency
    
    latencies = []
    errors = {}
    successful = 0
    
    base_ts = int(time.time() * 1000)
    
    async def single_operation(i: int):
        start = time.time()
        is_write = random.random() < 0.3  # 30% writes
        
        try:
            if is_write:
                name = f"MixUser_{base_ts}_{i}"
                email = f"mix_{base_ts}_{i}@test.com"
                query = f'INSERT INTO users (name, email) VALUES ("{name}", "{email}")'
                result = await handle_write_query(query, consistency)
            else:
                query = "SELECT * FROM users ORDER BY id DESC LIMIT 10"
                result = await handle_read_query(query, consistency)
            
            latency = (time.time() - start) * 1000
            return {"success": result.success, "latency_ms": latency, "error": None}
        except HTTPException as e:
            latency = (time.time() - start) * 1000
            return {"success": False, "latency_ms": latency, "error": e.detail}
        except Exception as e:
            latency = (time.time() - start) * 1000
            return {"success": False, "latency_ms": latency, "error": str(e)}
    
    start_time = time.time()
    tasks = [single_operation(i) for i in range(num_ops)]
    results = await asyncio.gather(*tasks)
    duration = time.time() - start_time
    
    for r in results:
        latencies.append(r["latency_ms"])
        if r["success"]:
            successful += 1
        else:
            error = r["error"] or "Unknown error"
            errors[error] = errors.get(error, 0) + 1
    
    return StressTestResult(
        test_name="Read/Write Mix (70/30)",
        total_operations=num_ops,
        successful=successful,
        failed=num_ops - successful,
        duration_seconds=round(duration, 3),
        throughput_ops_per_sec=round(num_ops / duration, 2),
        avg_latency_ms=round(sum(latencies) / len(latencies), 2) if latencies else 0,
        min_latency_ms=round(min(latencies), 2) if latencies else 0,
        max_latency_ms=round(max(latencies), 2) if latencies else 0,
        consistency_level=consistency.value,
        errors=errors if errors else None
    )


@app.post("/admin/stress-test/consistency-comparison")
async def stress_test_consistency_comparison(num_operations: int = 30):
    """
    Compare performance across all consistency levels.
    
    Tests:
    - ONE vs QUORUM vs ALL latency
    - Throughput differences
    - Trade-offs visualization
    """
    results = {}
    base_ts = int(time.time() * 1000)
    
    for level in [ConsistencyLevel.ONE, ConsistencyLevel.QUORUM, ConsistencyLevel.ALL]:
        latencies = []
        successful = 0
        errors = {}
        
        async def single_write(i: int, lvl: ConsistencyLevel):
            start = time.time()
            name = f"Comp_{lvl.value}_{base_ts}_{i}"
            email = f"comp_{lvl.value}_{base_ts}_{i}@test.com"
            query = f'INSERT INTO users (name, email) VALUES ("{name}", "{email}")'
            
            try:
                result = await handle_write_query(query, lvl)
                latency = (time.time() - start) * 1000
                return {"success": result.success, "latency_ms": latency, "error": None}
            except HTTPException as e:
                latency = (time.time() - start) * 1000
                return {"success": False, "latency_ms": latency, "error": e.detail}
            except Exception as e:
                latency = (time.time() - start) * 1000
                return {"success": False, "latency_ms": latency, "error": str(e)}
        
        start_time = time.time()
        tasks = [single_write(i, level) for i in range(num_operations)]
        test_results = await asyncio.gather(*tasks)
        duration = time.time() - start_time
        
        for r in test_results:
            latencies.append(r["latency_ms"])
            if r["success"]:
                successful += 1
            elif r["error"]:
                errors[r["error"]] = errors.get(r["error"], 0) + 1
        
        results[level.value] = {
            "total": num_operations,
            "successful": successful,
            "failed": num_operations - successful,
            "duration_seconds": round(duration, 3),
            "throughput_ops_per_sec": round(num_operations / duration, 2),
            "avg_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else 0,
            "min_latency_ms": round(min(latencies), 2) if latencies else 0,
            "max_latency_ms": round(max(latencies), 2) if latencies else 0,
            "errors": errors if errors else None
        }
    
    return {
        "test_name": "Consistency Level Comparison",
        "operations_per_level": num_operations,
        "results": results,
        "summary": {
            "fastest": min(results.keys(), key=lambda k: results[k]["avg_latency_ms"]),
            "most_reliable": max(results.keys(), key=lambda k: results[k]["successful"]),
            "highest_throughput": max(results.keys(), key=lambda k: results[k]["throughput_ops_per_sec"])
        }
    }


@app.get("/admin/stress-test/data-count")
async def get_data_count():
    """Get current count of test data in database"""
    try:
        with state_lock:
            master_host = current_master["host"]
        
        conn = get_mysql_connection(master_host)
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM users")
        users_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM products")
        products_count = cursor.fetchone()[0]
        
        cursor.close()
        conn.close()
        
        return {
            "users": users_count,
            "products": products_count,
            "total": users_count + products_count
        }
    except Exception as e:
        return {"error": str(e), "users": 0, "products": 0, "total": 0}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
