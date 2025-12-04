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
    "EVENTUAL": {
        "read_count": 0,
        "write_count": 0,
        "read_latency": 0.0,
        "write_latency": 0.0,
        "failures": 0
    },
    "STRONG": {
        "read_count": 0,
        "write_count": 0,
        "read_latency": 0.0,
        "write_latency": 0.0,
        "failures": 0,
        "quorum_not_achieved": 0
    }
}
metrics_lock = threading.Lock()


class ConsistencyLevel(str, Enum):
    """Consistency levels for read and write operations"""
    EVENTUAL = "EVENTUAL"  # Fast writes/reads, master only write, replica reads
    STRONG = "STRONG"      # Wait for Cabinet-selected quorum on writes, master reads


class QueryRequest(BaseModel):
    """Request model for SQL queries"""
    query: str
    consistency: ConsistencyLevel = ConsistencyLevel.STRONG  # Default to QUORUM


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
    
    Load balances between the two timestamp services with automatic failover.
    If the primary service fails, falls back to the other service.
    
    Returns:
        Timestamp value
        
    Raises:
        HTTPException: If timestamp cannot be obtained from any service
    """
    # Shuffle services for load balancing
    services = TIMESTAMP_SERVICES.copy()
    random.shuffle(services)
    
    last_error = None
    for service_url in services:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{service_url}/timestamp", timeout=2.0)
                response.raise_for_status()
                data = response.json()
                print(f"Got timestamp {data['timestamp']} from {service_url}")
                return data["timestamp"]
        except Exception as e:
            print(f"Timestamp service {service_url} failed: {e}, trying fallback...")
            last_error = e
            continue
    
    raise HTTPException(status_code=503, detail=f"All timestamp services failed: {str(last_error)}")


def execute_query_on_host(host: str, query: str, timestamp: Optional[int] = None, table_name: Optional[str] = None) -> Dict:
    """
    Execute a SQL query on a specific MySQL host.
    
    For write queries, also updates the metadata table with the timestamp
    and tracks per-table timestamps for fine-grained replication lag monitoring.
    
    Args:
        host: MySQL host address
        query: SQL query to execute
        timestamp: Optional timestamp for write operations
        table_name: Optional table name for per-table timestamp tracking
        
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
            # Update global timestamp (only if higher - handles concurrent writes)
            cursor.execute(
                "UPDATE _metadata SET last_applied_timestamp = GREATEST(last_applied_timestamp, %s) WHERE id = 1",
                (timestamp,)
            )
            
            # Update per-table timestamp if table name is provided (only if higher)
            if table_name:
                cursor.execute(
                    """INSERT INTO _table_timestamps (table_name, last_timestamp) 
                       VALUES (%s, %s) 
                       ON DUPLICATE KEY UPDATE last_timestamp = GREATEST(last_timestamp, %s)""",
                    (table_name, timestamp, timestamp)
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


def get_table_timestamps(host: str) -> Dict[str, int]:
    """
    Get per-table timestamps from a MySQL instance.
    
    This allows fine-grained tracking of replication lag per table,
    so you can know exactly which tables are behind on each replica.
    
    Args:
        host: MySQL host address
        
    Returns:
        Dictionary mapping table names to their last applied timestamps
    """
    try:
        conn = get_mysql_connection(host)
        cursor = conn.cursor()
        cursor.execute("SELECT table_name, last_timestamp FROM _table_timestamps")
        results = cursor.fetchall()
        cursor.close()
        conn.close()
        
        return {row[0]: row[1] for row in results} if results else {}
    except Exception as e:
        print(f"Error getting table timestamps from {host}: {e}")
        return {}


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

async def get_cabinet_quorum() -> List[str]:
    """
    Get optimal quorum from Cabinet service based on replica performance.
    
    Returns:
        List of replica IDs selected by Cabinet algorithm
        
    Raises:
        HTTPException: If Cabinet service fails
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{CABINET_SERVICE_URL}/select-quorum",
                json={"operation": "write"},
                timeout=5.0
            )
            response.raise_for_status()
            data = response.json()
            return data["quorum"]
    except Exception as e:
        raise HTTPException(
            status_code=503, 
            detail=f"Failed to get Cabinet quorum: {str(e)}"
        )

def check_replica_timestamp_sync(replica_host: str, timestamp: int) -> bool:
    """
    Check if a replica has caught up to the given timestamp.
    This is a synchronous helper for parallel execution.
    """
    try:
        replica_timestamp = get_last_applied_timestamp(replica_host)
        return replica_timestamp >= timestamp
    except Exception as e:
        print(f"Error checking replica timestamp: {e}")
        return False


async def wait_for_quorum_catchup(
    timestamp: int, 
    quorum_replicas: List[str], 
    timeout_seconds: float = 5.0
) -> dict:
    """
    Post-write verification: Wait for Cabinet-selected quorum replicas to catch up.
    Uses parallel checking for better performance.
    
    Args:
        timestamp: Target timestamp to wait for
        quorum_replicas: List of replica IDs selected by Cabinet (e.g., ["instance-2", "instance-3"])
        timeout_seconds: Maximum time to wait
        
    Returns:
        Dictionary with caught_up count and list of caught up replicas
    """
    start_time = time.time()
    
    with state_lock:
        replica_map = {r["id"]: r["host"] for r in current_replicas}
    
    # Only monitor the Cabinet-selected replicas
    target_replicas = [(rid, replica_map[rid]) for rid in quorum_replicas if rid in replica_map]
    
    if not target_replicas:
        return {
            "quorum_achieved": False,
            "caught_up_count": 0,
            "caught_up_replicas": []
        }
    
    loop = asyncio.get_event_loop()
    
    while (time.time() - start_time) < timeout_seconds:
        # Check all replicas in parallel using thread pool
        check_tasks = [
            loop.run_in_executor(
                None,
                check_replica_timestamp_sync,
                replica_host,
                timestamp
            )
            for replica_id, replica_host in target_replicas
        ]
        
        # Wait for all checks to complete in parallel
        results = await asyncio.gather(*check_tasks, return_exceptions=True)
        
        # Collect caught up replicas
        caught_up_replicas = [
            target_replicas[i][0]  # replica_id
            for i, result in enumerate(results)
            if result is True
        ]
        
        # Check if all Cabinet-selected replicas caught up
        if len(caught_up_replicas) >= len(target_replicas):
            return {
                "quorum_achieved": True,
                "caught_up_count": len(caught_up_replicas),
                "caught_up_replicas": caught_up_replicas
            }
        
        await asyncio.sleep(0.05)  # Shorter sleep for faster response
    
    # Final check after timeout
    check_tasks = [
        loop.run_in_executor(
            None,
            check_replica_timestamp_sync,
            replica_host,
            timestamp
        )
        for replica_id, replica_host in target_replicas
    ]
    results = await asyncio.gather(*check_tasks, return_exceptions=True)
    caught_up_replicas = [
        target_replicas[i][0]
        for i, result in enumerate(results)
        if result is True
    ]
    
    return {
        "quorum_achieved": len(caught_up_replicas) >= len(target_replicas),
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
        # NOTE: We do NOT use RESET MASTER as it clears GTID history
        # which breaks replication for other replicas
        promote_sql = """
            STOP SLAVE;
            RESET SLAVE ALL;
            SET GLOBAL read_only = OFF;
            SET GLOBAL super_read_only = OFF;
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
        
        # Ensure replicator user exists with correct permissions on new master
        # This is needed so other replicas can connect
        ensure_replicator_sql = """
            CREATE USER IF NOT EXISTS 'replicator'@'%' IDENTIFIED WITH mysql_native_password BY 'replicator_password';
            GRANT REPLICATION SLAVE ON *.* TO 'replicator'@'%';
            GRANT SELECT ON testdb.* TO 'replicator'@'%';
            FLUSH PRIVILEGES;
        """
        result = subprocess.run(
            ["docker", "exec", replica_container, "mysql", "-u", "root", "-prootpass", "-e", ensure_replicator_sql],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode != 0:
            print(f"Warning: Could not ensure replicator user: {result.stderr}")
        else:
            print(f"Replicator user verified on {replica_container}")
        
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
    Handle a write query with Cabinet-integrated replication.
    
    Consistency Levels:
    - EVENTUAL: Write to master only, return immediately (fast)
    - STRONG: Write to master, wait for Cabinet-selected quorum to catch up
    """
    global current_master, current_replicas
    
    start_time = time.time()
    
    # Step 0: Parse query to extract table name for per-table timestamp tracking
    query_type, tables = parse_query(query)
    table_name = tables[0] if tables else None
    
    # Step 1: Get timestamp
    timestamp = await get_timestamp()
    
    # Step 2: For STRONG consistency, get Cabinet quorum (no pre-flight check)
    cabinet_quorum = None
    if consistency == ConsistencyLevel.STRONG:
        cabinet_quorum = await get_cabinet_quorum()
    
    # Step 3: Execute on master (with per-table timestamp tracking)
    with state_lock:
        master_host = current_master["host"]
        master_container = current_master["container"]
    
    result = execute_query_on_host(master_host, query, timestamp, table_name)
    
    # Check if master execution failed
    if not result["success"]:
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
        
        # Find and promote elected replica
        with state_lock:
            elected_replica = next((r for r in current_replicas if r["id"] == new_leader_id), None)
        
        if not elected_replica:
            with metrics_lock:
                consistency_metrics[consistency.value]["failures"] += 1
            raise HTTPException(status_code=503, detail=f"Elected leader {new_leader_id} not found")
        
        promotion_success = await promote_replica_to_master(elected_replica["container"])
        
        if not promotion_success:
            with metrics_lock:
                consistency_metrics[consistency.value]["failures"] += 1
            raise HTTPException(status_code=503, detail="Failover failed: could not promote replica")
        
        # Update global state
        with state_lock:
            old_master = current_master
            current_master = elected_replica
            current_replicas = [r for r in current_replicas if r["id"] != new_leader_id]
            current_replicas.append(old_master)
        
        print(f"Failover complete: new master is {current_master['id']}")
        
        # Retry on new master (with per-table timestamp tracking)
        result = execute_query_on_host(current_master["host"], query, timestamp, table_name)
        
        if not result["success"]:
            with metrics_lock:
                consistency_metrics[consistency.value]["failures"] += 1
            raise HTTPException(status_code=500, detail=f"Query failed on new master: {result.get('error')}")
    
    latency_ms = (time.time() - start_time) * 1000
    
    # Consistency-specific logic
    if consistency == ConsistencyLevel.EVENTUAL:
        # EVENTUAL: Return immediately after master confirms
        with metrics_lock:
            consistency_metrics["EVENTUAL"]["write_count"] += 1
            consistency_metrics["EVENTUAL"]["write_latency"] += latency_ms
        
        return QueryResponse(
            success=True,
            message=f"Write successful (consistency: EVENTUAL, timestamp: {timestamp})",
            timestamp=timestamp,
            rows_affected=result["rows_affected"],
            executed_on=master_host,
            consistency_level="EVENTUAL",
            latency_ms=round(latency_ms, 2),
            quorum_achieved=None,
            replica_caught_up=None
        )
    
    else:  # ConsistencyLevel.STRONG
        # STRONG: Wait for Cabinet-selected replicas to catch up
        catchup_result = await wait_for_quorum_catchup(
            timestamp, 
            quorum_replicas=cabinet_quorum,
            timeout_seconds=5.0
        )
        
        latency_ms = (time.time() - start_time) * 1000
        
        if not catchup_result["quorum_achieved"]:
            # Write succeeded on master but Cabinet quorum didn't catch up
            with metrics_lock:
                consistency_metrics["STRONG"]["write_count"] += 1
                consistency_metrics["STRONG"]["write_latency"] += latency_ms
                consistency_metrics["STRONG"]["quorum_not_achieved"] += 1
            
            return QueryResponse(
                success=True,
                message=f"Write successful on master (timestamp: {timestamp}), but only {catchup_result['caught_up_count']}/{len(cabinet_quorum)} Cabinet replicas caught up. Data will eventually propagate.",
                timestamp=timestamp,
                rows_affected=result["rows_affected"],
                executed_on=master_host,
                consistency_level="STRONG",
                latency_ms=round(latency_ms, 2),
                quorum_achieved=False,
                replica_caught_up=False
            )
        
        # Cabinet quorum achieved
        with metrics_lock:
            consistency_metrics["STRONG"]["write_count"] += 1
            consistency_metrics["STRONG"]["write_latency"] += latency_ms
        
        return QueryResponse(
            success=True,
            message=f"Write successful (consistency: STRONG, timestamp: {timestamp}, Cabinet replicas: {', '.join(catchup_result['caught_up_replicas'])})",
            timestamp=timestamp,
            rows_affected=result["rows_affected"],
            executed_on=master_host,
            consistency_level="STRONG",
            latency_ms=round(latency_ms, 2),
            quorum_achieved=True,
            replica_caught_up=True
        )

async def handle_read_query(query: str, consistency: ConsistencyLevel) -> QueryResponse:
    """
    Handle a read query with tunable consistency.
    
    - EVENTUAL: Read from replica (fast, may be stale)
    - STRONG: Read from master (guaranteed fresh)
    """
    start_time = time.time()
    
    if consistency == ConsistencyLevel.EVENTUAL:
        # EVENTUAL: Route to lowest-latency healthy replica based on metrics
        with state_lock:
            master_host = current_master["host"]
            replicas = current_replicas.copy()
        
        # Fetch metrics to select best replica
        best_replica = None
        if replicas:
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(f"{METRICS_COLLECTOR_URL}/metrics", timeout=2.0)
                    if response.status_code == 200:
                        metrics_data = response.json()
                        replica_metrics_list = metrics_data.get("replicas", [])
                        
                        # Build lookup: replica_id -> metrics
                        metrics_lookup = {m["replica_id"]: m for m in replica_metrics_list}
                        
                        # Filter healthy replicas and sort by latency
                        healthy_replicas = []
                        for r in replicas:
                            metrics = metrics_lookup.get(r["id"])
                            if metrics and metrics.get("is_healthy", False):
                                healthy_replicas.append({
                                    "replica": r,
                                    "latency_ms": metrics.get("latency_ms", 9999)
                                })
                        
                        # Sort by latency (lowest first)
                        healthy_replicas.sort(key=lambda x: x["latency_ms"])
                        
                        if healthy_replicas:
                            best_replica = healthy_replicas[0]["replica"]
                            print(f"Read routing: selected {best_replica['id']} (latency: {healthy_replicas[0]['latency_ms']:.2f}ms)")
            except Exception as e:
                print(f"Failed to fetch metrics for read routing: {e}, falling back to random")
        
        # Fallback to random if metrics unavailable
        if not best_replica and replicas:
            best_replica = random.choice(replicas)
            print(f"Read routing: random fallback to {best_replica['id']}")
        
        # Execute read on selected replica or master
        if best_replica:
            replica_host = best_replica["host"]
            result = execute_query_on_host(replica_host, query)
            
            # Fallback to master if replica fails
            if not result["success"]:
                print(f"Replica read failed, using master: {result.get('error')}")
                result = execute_query_on_host(master_host, query)
                read_host = master_host
            else:
                read_host = replica_host
        else:
            # No replicas available, use master
            result = execute_query_on_host(master_host, query)
            read_host = master_host
        
        if not result["success"]:
            with metrics_lock:
                consistency_metrics["EVENTUAL"]["failures"] += 1
            raise HTTPException(
                status_code=500, 
                detail=f"Read failed: {result.get('error')}"
            )
        
        latency_ms = (time.time() - start_time) * 1000
        
        with metrics_lock:
            consistency_metrics["EVENTUAL"]["read_count"] += 1
            consistency_metrics["EVENTUAL"]["read_latency"] += latency_ms
        
        return QueryResponse(
            success=True,
            message="Read successful (eventual consistency - data may be stale)",
            data=result["data"],
            rows_affected=len(result["data"]) if result["data"] else 0,
            executed_on=read_host,
            consistency_level="EVENTUAL",
            latency_ms=round(latency_ms, 2)
        )
    
    else:  # ConsistencyLevel.STRONG
        # STRONG: Read from master for guaranteed fresh data
        with state_lock:
            master_host = current_master["host"]
        
        result = execute_query_on_host(master_host, query)
        
        if not result["success"]:
            with metrics_lock:
                consistency_metrics["STRONG"]["failures"] += 1
            raise HTTPException(
                status_code=500,
                detail=f"Read failed: {result.get('error')}"
            )
        
        latency_ms = (time.time() - start_time) * 1000
        
        with metrics_lock:
            consistency_metrics["STRONG"]["read_count"] += 1
            consistency_metrics["STRONG"]["read_latency"] += latency_ms
        
        return QueryResponse(
            success=True,
            message="Read successful (strong consistency - latest data)",
            data=result["data"],
            rows_affected=len(result["data"]) if result["data"] else 0,
            executed_on=master_host,
            consistency_level="STRONG",
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


@app.get("/table-timestamps")
async def get_table_timestamps_endpoint():
    """
    Get per-table timestamps for all MySQL instances.
    
    This shows the replication lag per table on each instance,
    allowing fine-grained visibility into which tables are behind.
    
    Returns:
        Dictionary with table timestamps for master and each replica
    """
    with state_lock:
        master_host = current_master["host"]
        master_id = current_master["id"]
        replicas = list(current_replicas)
    
    result = {
        "master": {
            "id": master_id,
            "host": master_host,
            "global_timestamp": get_last_applied_timestamp(master_host),
            "table_timestamps": get_table_timestamps(master_host)
        },
        "replicas": []
    }
    
    for replica in replicas:
        replica_timestamps = get_table_timestamps(replica["host"])
        global_timestamp = get_last_applied_timestamp(replica["host"])
        
        # Calculate per-table lag compared to master
        master_table_ts = result["master"]["table_timestamps"]
        table_lag = {}
        for table, ts in master_table_ts.items():
            replica_ts = replica_timestamps.get(table, 0)
            table_lag[table] = ts - replica_ts
        
        result["replicas"].append({
            "id": replica["id"],
            "host": replica["host"],
            "global_timestamp": global_timestamp,
            "global_lag": result["master"]["global_timestamp"] - global_timestamp,
            "table_timestamps": replica_timestamps,
            "table_lag": table_lag
        })
    
    return result


@app.get("/consistency-metrics")
async def get_consistency_metrics():
    """Get consistency level performance metrics with separate read/write latencies"""
    with metrics_lock:
        metrics_summary = {}
        for level, data in consistency_metrics.items():
            # Calculate average read latency
            avg_read_latency = (
                data["read_latency"] / data["read_count"] 
                if data["read_count"] > 0 
                else 0
            )
            
            # Calculate average write latency
            avg_write_latency = (
                data["write_latency"] / data["write_count"] 
                if data["write_count"] > 0 
                else 0
            )
            
            # Calculate overall average
            total_count = data["read_count"] + data["write_count"]
            total_latency = data["read_latency"] + data["write_latency"]
            avg_latency = (
                total_latency / total_count
                if total_count > 0
                else 0
            )
            
            metrics_summary[level] = {
                "read_count": data["read_count"],
                "write_count": data["write_count"],
                "total_count": total_count,
                "avg_read_latency_ms": round(avg_read_latency, 2),
                "avg_write_latency_ms": round(avg_write_latency, 2),
                "avg_latency_ms": round(avg_latency, 2),
                "failures": data["failures"],
                "quorum_not_achieved": data.get("quorum_not_achieved", 0),
                "success_rate": (
                    round((total_count / (total_count + data["failures"]) * 100), 2)
                    if (total_count + data["failures"]) > 0
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
        
        # Step 1: Stop the master container (don't impose a short Python-side timeout)
        print(f"Stopping {master_container} container...")
        result = subprocess.run(
            ["docker", "stop", master_container],
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            print(f"Failed to stop master: {result.stderr}")
            return {
                "success": False,
                "message": "Failed to stop master",
                "error": result.stderr
            }

        print("docker stop returned; waiting for container to be observed as stopped")

        # Step 2: Wait for the container to actually be stopped (poll until stopped)
        stopped = await wait_for_container_stop(master_container, poll_interval=1.0, max_wait_seconds=120)
        if not stopped:
            return {
                "success": False,
                "message": "Master stop did not complete in time",
                "error": "Timed out waiting for container to stop"
            }
        
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


async def wait_for_container_stop(container: str, poll_interval: float = 1.0, max_wait_seconds: Optional[int] = None) -> bool:
    """
    Wait for a Docker container to stop by polling its running state.

    This avoids relying on fixed sleep durations and Python-side timeouts
    when attempting to stop a container for failover. If `max_wait_seconds`
    is None, this will wait indefinitely (polling) until the container is
    observed as not running. Returns True when the container is stopped,
    False if we exceeded `max_wait_seconds`.
    """
    start = time.time()
    while True:
        try:
            inspect = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Running}}", container],
                capture_output=True,
                text=True
            )
            running = inspect.returncode == 0 and "true" in inspect.stdout.lower()
            if not running:
                print(f"Container {container} is not running")
                return True
        except Exception as e:
            print(f"Error inspecting container {container}: {e}")

        if max_wait_seconds is not None and (time.time() - start) > max_wait_seconds:
            print(f"Timed out waiting for container {container} to stop after {max_wait_seconds}s")
            return False

        await asyncio.sleep(poll_interval)


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
        
        # NOTE: We do NOT use RESET MASTER here as it clears GTID history
        # which can cause issues with replication in a GTID-based setup
        
        # Step 2: Set read-only mode
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
        
        # Step 3: Configure replication (using CHANGE REPLICATION SOURCE for MySQL 8.0.23+)
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
        
        # Stop the master container (don't impose a short Python-side timeout)
        print(f"Stopping {master_container} container...")
        result = subprocess.run(
            ["docker", "stop", master_container],
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            print(f"Failed to stop master: {result.stderr}")
            return {
                "success": False,
                "message": "Failed to stop master",
                "error": result.stderr
            }

        print(f"docker stop returned for {master_container}; waiting to observe container stopped")

        stopped = await wait_for_container_stop(master_container, poll_interval=1.0, max_wait_seconds=120)
        if not stopped:
            return {
                "success": False,
                "message": "Master stop did not complete in time",
                "error": "Timed out waiting for container to stop"
            }

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


@app.post("/admin/promote-leader")
async def promote_leader(request: dict):
    """
    Promote a specific replica to master and reconfigure all other replicas.
    Called after SEER election when the old master has been stopped.
    
    This endpoint:
    1. Promotes the elected replica to master
    2. Reconfigures all other replicas to point to the new master
    3. Updates the coordinator's global state
    """
    global current_master, current_replicas
    
    new_leader_id = request.get("new_leader")
    if not new_leader_id:
        return {
            "success": False,
            "message": "new_leader is required",
            "error": "Missing new_leader parameter"
        }
    
    try:
        with state_lock:
            # Find the replica to promote
            target_replica = next((r for r in current_replicas if r["id"] == new_leader_id), None)
            if not target_replica:
                return {
                    "success": False,
                    "message": f"Replica {new_leader_id} not found in current replicas",
                    "error": "Replica not found"
                }
            
            old_master_id = current_master["id"]
            new_master_container = target_replica["container"]
            new_master_host = target_replica["host"]
            # Get list of other replicas that need to be reconfigured
            other_replicas = [r for r in current_replicas if r["id"] != new_leader_id]
        
        print(f"Promoting {new_leader_id} to master...")
        
        # Step 1: Promote the elected replica to master
        promotion_success = await promote_replica_to_master(new_master_container)
        if not promotion_success:
            return {
                "success": False,
                "message": "Failed to promote replica to master",
                "error": "Promotion failed"
            }
        
        # Give the new master a moment to be fully ready
        await asyncio.sleep(2)
        
        # Step 2: Reconfigure ALL other replicas to point to new master
        # This is critical for replication to work after failover
        for replica in other_replicas:
            print(f"Reconfiguring {replica['id']} to replicate from new master {new_master_host}...")
            try:
                # First, stop replication and clear old master info
                # RESET SLAVE ALL is needed to clear the old master connection info
                # but does NOT affect GTID_EXECUTED, so GTID replication will still work
                stop_sql = "STOP SLAVE; RESET SLAVE ALL;"
                result = subprocess.run(
                    ["docker", "exec", replica["container"], "mysql", "-u", "root", "-prootpass", "-e", stop_sql],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                if result.returncode != 0:
                    print(f"Warning: Failed to stop slave on {replica['id']}: {result.stderr}")
                
                # Now configure to replicate from new master
                # MASTER_AUTO_POSITION=1 uses GTID to automatically find the right position
                change_master_sql = f"""
                    CHANGE MASTER TO
                        MASTER_HOST='{new_master_host}',
                        MASTER_USER='replicator',
                        MASTER_PASSWORD='replicator_password',
                        MASTER_AUTO_POSITION=1,
                        GET_MASTER_PUBLIC_KEY=1;
                """
                result = subprocess.run(
                    ["docker", "exec", replica["container"], "mysql", "-u", "root", "-prootpass", "-e", change_master_sql],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                if result.returncode != 0:
                    print(f"Warning: Failed to change master on {replica['id']}: {result.stderr}")
                
                # Start replication
                result = subprocess.run(
                    ["docker", "exec", replica["container"], "mysql", "-u", "root", "-prootpass", "-e", "START SLAVE;"],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                if result.returncode != 0:
                    print(f"Warning: Failed to start slave on {replica['id']}: {result.stderr}")
                else:
                    print(f"Successfully reconfigured {replica['id']}")
                    
                # Check replication status
                check_result = subprocess.run(
                    ["docker", "exec", replica["container"], "mysql", "-u", "root", "-prootpass", "-e", "SHOW SLAVE STATUS\\G"],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                if check_result.returncode == 0:
                    output = check_result.stdout
                    if "Slave_IO_Running: Yes" in output and "Slave_SQL_Running: Yes" in output:
                        print(f"✓ {replica['id']} replication is running")
                    else:
                        # Extract error info
                        for line in output.split('\n'):
                            if 'Last_IO_Error:' in line or 'Last_SQL_Error:' in line:
                                error_text = line.split(':', 1)[1].strip() if ':' in line else ''
                                if error_text:
                                    print(f"  {replica['id']} Error: {error_text}")
                        
            except Exception as e:
                print(f"Warning: Error reconfiguring {replica['id']}: {e}")
        
        # Step 3: Update global state
        with state_lock:
            current_master = target_replica.copy()
            # Remove new master from replicas list (old master is already stopped, don't add it back yet)
            current_replicas = [r.copy() for r in current_replicas if r["id"] != new_leader_id]
        
        print(f"Failover complete: new master is {new_leader_id}")
        
        return {
            "success": True,
            "message": f"Successfully promoted {new_leader_id} to master",
            "old_master": old_master_id,
            "new_master": new_leader_id,
            "new_leader_id": new_leader_id,
            "reconfigured_replicas": [r["id"] for r in other_replicas]
        }
    
    except Exception as e:
        return {
            "success": False,
            "message": "Promotion failed",
            "error": str(e)
        }


# ==================== STRESS TEST ENDPOINTS ====================

class StressTestRequest(BaseModel):
    """Request model for stress tests"""
    num_operations: int = 50
    consistency: ConsistencyLevel = ConsistencyLevel.STRONG


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
    Keeps the schema intact. Also resets timestamp services.
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
            consistency_metrics["EVENTUAL"] = {
                "read_count": 0,
                "write_count": 0,
                "read_latency": 0.0,
                "write_latency": 0.0,
                "failures": 0
            }
            consistency_metrics["STRONG"] = {
                "read_count": 0,
                "write_count": 0,
                "read_latency": 0.0,
                "write_latency": 0.0,
                "failures": 0,
                "quorum_not_achieved": 0
            }
        
        # Reset timestamp services to start from the beginning
        timestamp_reset_success = True
        async with httpx.AsyncClient() as client:
            for service_url in TIMESTAMP_SERVICES:
                try:
                    response = await client.post(f"{service_url}/reset", timeout=5.0)
                    if response.status_code != 200:
                        print(f"Warning: Failed to reset timestamp service {service_url}")
                        timestamp_reset_success = False
                except Exception as e:
                    print(f"Warning: Could not reset timestamp service {service_url}: {e}")
                    timestamp_reset_success = False
        
        return {
            "success": True,
            "message": f"Cleared {users_deleted} users and {products_deleted} products",
            "users_deleted": users_deleted,
            "products_deleted": products_deleted,
            "timestamp_reset": timestamp_reset_success
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
    
    for level in [ConsistencyLevel.EVENTUAL, ConsistencyLevel.STRONG]:
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


@app.get("/admin/current-quorum")
async def get_current_quorum():
    """
    Get the current Cabinet quorum selection based on live metrics.
    
    Returns:
        Current quorum selection with replica weights and metrics
    """
    try:
        # Fetch current metrics
        async with httpx.AsyncClient() as client:
            metrics_response = await client.get(f"{METRICS_COLLECTOR_URL}/metrics", timeout=5.0)
            metrics_data = metrics_response.json()
            
            # Call Cabinet to get quorum
            cabinet_response = await client.post(
                f"{CABINET_SERVICE_URL}/select-quorum",
                json={"replicas": metrics_data["replicas"]},
                timeout=5.0
            )
            cabinet_data = cabinet_response.json()
        
        # Filter to show only actual replicas (not master)
        with state_lock:
            master_id = current_master["id"]
            replica_ids = [r["id"] for r in current_replicas]
        
        cabinet_quorum = cabinet_data.get("quorum", [])
        filtered_quorum = [rid for rid in cabinet_quorum if rid in replica_ids]
        
        return {
            "master": master_id,
            "cabinet_selected": cabinet_quorum,
            "actual_replicas_to_wait": filtered_quorum,
            "quorum_size": cabinet_data.get("quorum_size"),
            "total_instances": cabinet_data.get("total_replicas"),
            "metrics": {
                m["replica_id"]: {
                    "latency_ms": round(m["latency_ms"], 2),
                    "replication_lag": m["replication_lag"],
                    "is_healthy": m["is_healthy"]
                }
                for m in metrics_data["replicas"]
            }
        }
    except Exception as e:
        return {"error": str(e)}


@app.post("/admin/stress-test/read-after-write")
async def stress_test_read_after_write(num_trials: int = 20):
    """
    Read-After-Write Consistency Test.
    
    Compares STRONG vs EVENTUAL consistency for read-after-write scenarios.
    
    For each trial:
    1. Write a unique record
    2. Immediately read it back
    3. Check if data is found (consistent) or not found (stale)
    
    Args:
        num_trials: Number of trials per consistency level (default: 20)
        
    Returns:
        RAWTestResult with success rates and detailed logs
    """
    base_ts = int(time.time() * 1000)
    trial_logs = []
    
    # Test STRONG consistency
    strong_success = 0
    strong_latencies = []
    strong_logs = []
    
    for i in range(num_trials):
        trial_start = time.time()
        unique_name = f"RAW_Strong_{base_ts}_{i}"
        unique_email = f"raw_strong_{base_ts}_{i}@test.com"
        
        # Write with STRONG
        write_query = f'INSERT INTO users (name, email) VALUES ("{unique_name}", "{unique_email}")'
        try:
            write_result = await handle_write_query(write_query, ConsistencyLevel.STRONG)
            write_success = write_result.success
        except Exception as e:
            write_success = False
        
        # Immediately read with STRONG
        read_query = f'SELECT * FROM users WHERE name="{unique_name}"'
        try:
            read_result = await handle_read_query(read_query, ConsistencyLevel.STRONG)
            data_found = read_result.data is not None and len(read_result.data) > 0
        except Exception as e:
            data_found = False
        
        trial_latency = (time.time() - trial_start) * 1000
        strong_latencies.append(trial_latency)
        
        if data_found:
            strong_success += 1
            
        strong_logs.append({
            "trial": i + 1,
            "write_success": write_success,
            "data_found": data_found,
            "latency_ms": round(trial_latency, 2)
        })
    
    # Test EVENTUAL consistency
    eventual_success = 0
    eventual_latencies = []
    eventual_logs = []
    
    for i in range(num_trials):
        trial_start = time.time()
        unique_name = f"RAW_Eventual_{base_ts}_{i}"
        unique_email = f"raw_eventual_{base_ts}_{i}@test.com"
        
        # Write with EVENTUAL
        write_query = f'INSERT INTO users (name, email) VALUES ("{unique_name}", "{unique_email}")'
        try:
            write_result = await handle_write_query(write_query, ConsistencyLevel.EVENTUAL)
            write_success = write_result.success
        except Exception as e:
            write_success = False
        
        # Immediately read with EVENTUAL
        read_query = f'SELECT * FROM users WHERE name="{unique_name}"'
        try:
            read_result = await handle_read_query(read_query, ConsistencyLevel.EVENTUAL)
            data_found = read_result.data is not None and len(read_result.data) > 0
        except Exception as e:
            data_found = False
        
        trial_latency = (time.time() - trial_start) * 1000
        eventual_latencies.append(trial_latency)
        
        if data_found:
            eventual_success += 1
            
        eventual_logs.append({
            "trial": i + 1,
            "write_success": write_success,
            "data_found": data_found,
            "latency_ms": round(trial_latency, 2)
        })
    
    # Combine logs
    trial_logs = [
        {"consistency": "STRONG", "trials": strong_logs},
        {"consistency": "EVENTUAL", "trials": eventual_logs}
    ]
    
    # Calculate results
    strong_results = {
        "success_count": strong_success,
        "total_trials": num_trials,
        "success_rate": round(strong_success / num_trials * 100, 1),
        "stale_reads": num_trials - strong_success,
        "avg_latency_ms": round(sum(strong_latencies) / len(strong_latencies), 2),
        "min_latency_ms": round(min(strong_latencies), 2),
        "max_latency_ms": round(max(strong_latencies), 2)
    }
    
    eventual_results = {
        "success_count": eventual_success,
        "total_trials": num_trials,
        "success_rate": round(eventual_success / num_trials * 100, 1),
        "stale_reads": num_trials - eventual_success,
        "avg_latency_ms": round(sum(eventual_latencies) / len(eventual_latencies), 2),
        "min_latency_ms": round(min(eventual_latencies), 2),
        "max_latency_ms": round(max(eventual_latencies), 2)
    }
    
    return {
        "test_name": "Read-After-Write Consistency Comparison",
        "num_trials": num_trials,
        "strong_results": strong_results,
        "eventual_results": eventual_results,
        "summary": {
            "strong_success_rate": f"{strong_results['success_rate']}%",
            "eventual_success_rate": f"{eventual_results['success_rate']}%",
            "strong_guarantees_raw": strong_results['success_rate'] == 100.0,
            "eventual_stale_read_rate": f"{round((num_trials - eventual_success) / num_trials * 100, 1)}%",
            "conclusion": "STRONG guarantees read-after-write consistency" if strong_results['success_rate'] == 100.0 else "Unexpected: STRONG had stale reads"
        },
        "trial_logs": trial_logs
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
