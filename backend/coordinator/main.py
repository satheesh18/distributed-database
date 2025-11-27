"""
Main Coordinator Service

This is the central component that handles all client requests.
It coordinates between all other services to provide:
- Distributed timestamp assignment
- Quorum-based replication (strong consistency)
- Performance-aware leader election on failure

Flow:
1. Client sends SQL query
2. Coordinator parses query
3. For writes: Get timestamp → Execute on master → Replicate to quorum
4. For reads: Route to up-to-date replica or master
5. On master failure: Elect new leader via SEER
"""

import asyncio
import os
import random
import threading
import mysql.connector
import httpx
from typing import Dict, List, Optional
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
MYSQL_MASTER_HOST = os.getenv("MYSQL_MASTER_HOST", "mysql-replica-4")
MYSQL_REPLICAS = [
    {"id": "replica-1", "host": os.getenv("MYSQL_REPLICA_1_HOST", "mysql-replica-1")},
    {"id": "replica-2", "host": os.getenv("MYSQL_REPLICA_2_HOST", "mysql-replica-2")},
    {"id": "replica-3", "host": os.getenv("MYSQL_REPLICA_3_HOST", "mysql-replica-3")},
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
current_master = MYSQL_MASTER_HOST
master_is_original = True


class QueryRequest(BaseModel):
    """Request model for SQL queries"""
    query: str


class QueryResponse(BaseModel):
    """Response model for query execution"""
    success: bool
    message: str
    timestamp: Optional[int] = None
    rows_affected: Optional[int] = None
    data: Optional[List[Dict]] = None
    executed_on: Optional[str] = None


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


async def get_quorum() -> List[str]:
    """
    Get the optimal quorum for write replication from Cabinet service.
    
    Returns:
        List of replica IDs in the quorum
        
    Raises:
        HTTPException: If quorum cannot be determined
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
        raise HTTPException(status_code=503, detail=f"Failed to get quorum: {str(e)}")


async def elect_new_leader() -> str:
    """
    Elect a new leader using SEER service when master fails.
    
    Returns:
        Replica ID of the new leader
        
    Raises:
        HTTPException: If leader election fails
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{SEER_SERVICE_URL}/elect-leader",
                json={},
                timeout=5.0
            )
            response.raise_for_status()
            data = response.json()
            return data["leader_id"]
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Failed to elect leader: {str(e)}")


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


async def handle_write_query(query: str) -> QueryResponse:
    """
    Handle a write query (INSERT, UPDATE, DELETE).
    
    Flow:
    1. Get timestamp from timestamp service
    2. Execute on master
    3. Get quorum from Cabinet
    4. Replicate to quorum members
    5. Return success when quorum confirms
    
    Args:
        query: SQL write query
        
    Returns:
        QueryResponse with execution results
    """
    global current_master, master_is_original
    
    # Step 1: Get timestamp
    timestamp = await get_timestamp()
    
    # Step 2: Execute on master
    with state_lock:
        master_host = current_master
    
    result = execute_query_on_host(master_host, query, timestamp)
    
    # Check if master execution failed
    if not result["success"]:
        # Master might be down - attempt failover
        print(f"Master execution failed: {result.get('error')}")
        
        # Elect new leader
        new_leader_id = await elect_new_leader()
        new_master_host = next(
            (r["host"] for r in MYSQL_REPLICAS if r["id"] == new_leader_id),
            None
        )
        
        if not new_master_host:
            raise HTTPException(status_code=503, detail="Failover failed: no suitable replica")
        
        # Update master
        with state_lock:
            current_master = new_master_host
            master_is_original = False
        
        print(f"Failover complete: new master is {new_leader_id}")
        
        # Retry on new master
        result = execute_query_on_host(new_master_host, query, timestamp)
        
        if not result["success"]:
            raise HTTPException(status_code=500, detail=f"Query failed on new master: {result.get('error')}")
    
    # Step 3: Get quorum (determines which replicas we wait for)
    quorum = await get_quorum()
    
    # Step 4: Replicate to ALL replicas (not just quorum)
    # IMPORTANT: Exclude the current master from replication (it already has the write)
    # This handles the case where a replica has been promoted to master
    with state_lock:
        current_master_host = current_master
    
    # Filter out the current master from the replica list
    actual_replicas = [
        r for r in MYSQL_REPLICAS 
        if r["host"] != current_master_host
    ]
    
    # We send to all replicas to keep them in sync, but only wait for quorum confirmation
    successful_replications = 0
    failed_replicas = []
    quorum_confirmations = 0
    
    for replica in actual_replicas:
        replica_id = replica["id"]
        replica_host = replica["host"]
        
        replica_result = execute_query_on_host(replica_host, query, timestamp)
        
        if replica_result["success"]:
            successful_replications += 1
            # Check if this replica is in the quorum
            if replica_id in quorum:
                quorum_confirmations += 1
        else:
            failed_replicas.append(replica_id)
            print(f"Replication to {replica_id} failed: {replica_result.get('error')}")
    
    # Step 5: Check if quorum was achieved
    # We need majority of quorum members to confirm (not just any replicas)
    quorum_size = len(quorum)
    required_confirmations = (quorum_size // 2 + 1)
    
    if quorum_confirmations < required_confirmations:
        raise HTTPException(
            status_code=500,
            detail=f"Quorum not achieved: {quorum_confirmations}/{quorum_size} quorum replicas confirmed (total: {successful_replications}/{len(actual_replicas)})"
        )
    
    return QueryResponse(
        success=True,
        message=f"Write successful (timestamp: {timestamp}, quorum: {quorum_confirmations}/{quorum_size}, total: {successful_replications}/{len(actual_replicas)})",
        timestamp=timestamp,
        rows_affected=result["rows_affected"],
        executed_on=master_host
    )


async def get_best_replica_for_read() -> str:
    """
    Select the best replica for read operations based on metrics.
    
    Selects replica with:
    - Low latency
    - Low or zero replication lag
    - Healthy status
    
    Falls back to master if no suitable replica found.
    
    Returns:
        Host address of best replica or master
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{METRICS_COLLECTOR_URL}/metrics", timeout=5.0)
            response.raise_for_status()
            data = response.json()
            replicas = data.get("replicas", [])
        
        if not replicas:
            # No replicas available, use master
            with state_lock:
                return current_master
        
        # Filter healthy replicas with acceptable lag (< 5 timestamps behind)
        suitable_replicas = [
            r for r in replicas 
            if r["is_healthy"] and r["replication_lag"] < 5
        ]
        
        if not suitable_replicas:
            # No suitable replicas, use master
            with state_lock:
                return current_master
        
        # Sort by latency (ascending - lowest latency first)
        suitable_replicas.sort(key=lambda x: x["latency_ms"])
        
        # Select the best replica (lowest latency)
        best_replica_id = suitable_replicas[0]["replica_id"]
        
        # Get host for this replica
        best_replica_host = next(
            (r["host"] for r in MYSQL_REPLICAS if r["id"] == best_replica_id),
            None
        )
        
        if best_replica_host:
            return best_replica_host
        else:
            # Fallback to master
            with state_lock:
                return current_master
    
    except Exception as e:
        print(f"Error selecting best replica: {e}")
        # Fallback to master on error
        with state_lock:
            return current_master


async def handle_read_query(query: str) -> QueryResponse:
    """
    Handle a read query (SELECT).
    
    Routes to the best available replica based on:
    - Latency (lower is better)
    - Replication lag (lower is better)
    - Health status (must be healthy)
    
    Falls back to master if no suitable replica is available.
    
    Args:
        query: SQL read query
        
    Returns:
        QueryResponse with query results
    """
    # Select best replica for read
    read_host = await get_best_replica_for_read()
    
    # Execute on selected host
    result = execute_query_on_host(read_host, query)
    
    if not result["success"]:
        # If read fails on replica, try master as fallback
        print(f"Read failed on {read_host}, trying master")
        with state_lock:
            master_host = current_master
        
        result = execute_query_on_host(master_host, query)
        read_host = master_host
        
        if not result["success"]:
            raise HTTPException(status_code=500, detail=f"Query failed: {result.get('error')}")
    
    return QueryResponse(
        success=True,
        message="Read successful",
        data=result["data"],
        rows_affected=len(result["data"]) if result["data"] else 0,
        executed_on=read_host
    )


@app.post("/query", response_model=QueryResponse)
async def execute_query(request: QueryRequest):
    """
    Main endpoint for executing SQL queries.
    
    Handles both read and write queries:
    - Writes: Timestamped, replicated to quorum
    - Reads: Routed to master for strong consistency
    
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
    
    # Route based on query type
    if is_write_query(query_type):
        return await handle_write_query(query)
    elif is_read_query(query_type):
        return await handle_read_query(query)
    else:
        raise HTTPException(status_code=400, detail="Invalid query type")


@app.get("/status")
async def get_status():
    """Get current system status"""
    with state_lock:
        return {
            "current_master": current_master,
            "master_is_original": master_is_original,
            "replicas": [r["id"] for r in MYSQL_REPLICAS]
        }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "coordinator"}

@app.post("/admin/stop-master")
async def stop_master():
    """
    Stop the MySQL master container to simulate failure.
    This will IMMEDIATELY trigger leader election via SEER.
    """
    global current_master, master_is_original
    
    try:
        # Step 1: Stop the master container
        print("Stopping mysql-replica-4 container...")
        result = subprocess.run(
            ["docker", "stop", "mysql-replica-4"],
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
        
        # Step 2: Wait a moment for the container to fully stop
        await asyncio.sleep(2)
        
        # Step 4: Immediately elect new leader using SEER (with retries)
        print("Triggering leader election via SEER...")
        
        max_election_retries = 5
        election_data = None
        last_error = None
        
        for attempt in range(max_election_retries):
            try:
                async with httpx.AsyncClient() as client:
                    # Call SEER with empty exclude list (SEER will filter unhealthy replicas)
                    election_response = await client.post(
                        f"{SEER_SERVICE_URL}/elect-leader",
                        json={"exclude_replicas": []},  # Empty - SEER filters by health
                        timeout=20.0  # Increased timeout
                    )
                    election_response.raise_for_status()
                    election_data = election_response.json()
                    print(f"Election successful on attempt {attempt + 1}")
                    break
            except httpx.HTTPStatusError as e:
                error_detail = e.response.text if hasattr(e.response, 'text') else str(e)
                print(f"Election attempt {attempt + 1} failed (HTTP {e.response.status_code}): {error_detail}")
                last_error = error_detail
                if attempt < max_election_retries - 1:
                    await asyncio.sleep(3)  # Longer wait between retries
            except Exception as e:
                print(f"Election attempt {attempt + 1} failed: {str(e)}")
                last_error = str(e)
                if attempt < max_election_retries - 1:
                    await asyncio.sleep(3)
        
        if not election_data:
            return {
                "success": False,
                "message": "Master stopped but leader election failed after retries",
                "error": last_error or "Unknown error during election",
                "hint": "Check if metrics-collector and SEER services are running. Master is stopped but system needs manual intervention."
            }
        
        new_leader_id = election_data.get("leader_id")
        print(f"SEER elected: {new_leader_id}")
        
        if not new_leader_id:
            print("No leader ID in response")
            return {
                "success": False,
                "message": "Master stopped but SEER did not return a leader",
                "error": "Empty leader_id in response"
            }
        
        # Step 5: Map leader ID to host
        new_master_host = next(
            (r["host"] for r in MYSQL_REPLICAS if r["id"] == new_leader_id),
            None
        )
        
        if not new_master_host:
            print(f"Could not find host for {new_leader_id}")
            return {
                "success": False,
                "message": "Master stopped but no suitable replica found for failover",
                "error": f"No host mapping for {new_leader_id}"
            }
        
        # Step 6: Update global master state
        old_master = current_master
        with state_lock:
            current_master = new_master_host
            master_is_original = False
        
        print(f"Failover complete: {old_master} -> {new_master_host} ({new_leader_id})")
        
        return {
            "success": True,
            "message": "Master stopped and failover complete",
            "old_master": old_master,
            "new_master": new_master_host,
            "new_leader_id": new_leader_id,
            "election_details": {
                "leader_id": election_data.get("leader_id"),
                "score": election_data.get("score"),
                "latency_ms": election_data.get("latency_ms"),
                "uptime_seconds": election_data.get("uptime_seconds"),
                "replication_lag": election_data.get("replication_lag"),
                "crash_count": election_data.get("crash_count")
            }
        }
    
    except subprocess.TimeoutExpired:
        print("Docker command timed out")
        raise HTTPException(status_code=500, detail="Command timed out")
    except Exception as e:
        print(f"Unexpected error: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error stopping master: {str(e)}")


@app.post("/admin/start-master")
async def start_master():
    """
    Start the MySQL master container after failure recovery.
    """
    global current_master, master_is_original
    
    try:
        result = subprocess.run(
            ["docker", "start", "mysql-replica-4"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0:
            # Wait for MySQL to be ready
            print("Waiting for MySQL master to be ready...")
            await asyncio.sleep(5)
            
            # Reset master to original
            old_master = current_master
            with state_lock:
                current_master = MYSQL_MASTER_HOST
                master_is_original = True
            
            print(f"Master restored: {old_master} -> {MYSQL_MASTER_HOST}")
            
            return {
                "success": True,
                "message": "Master container started and restored as primary.",
                "old_master": old_master,
                "new_master": MYSQL_MASTER_HOST,
                "output": result.stdout
            }
        else:
            return {
                "success": False,
                "message": "Failed to start master",
                "error": result.stderr
            }
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="Command timed out")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error starting master: {str(e)}")


@app.post("/admin/trigger-failover")
async def trigger_failover():
    """
    Manually trigger failover by electing a new leader.
    Useful for testing SEER algorithm without actually stopping master.
    """
    try:
        # Elect new leader
        new_leader_id = await elect_new_leader()
        new_master_host = next(
            (r["host"] for r in MYSQL_REPLICAS if r["id"] == new_leader_id),
            None
        )
        
        if not new_master_host:
            raise HTTPException(status_code=503, detail="No suitable replica found")
        
        # Update master
        global current_master, master_is_original
        old_master = current_master
        
        with state_lock:
            current_master = new_master_host
            master_is_original = False
        
        return {
            "success": True,
            "message": f"Failover complete: {old_master} -> {new_master_host}",
            "old_master": old_master,
            "new_master": new_master_host,
            "new_leader_id": new_leader_id
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failover failed: {str(e)}")


@app.get("/admin/leader-info")
async def get_leader_info():
    """
    Get detailed information about current leader and election metrics.
    """
    try:
        # Get metrics for all replicas
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{METRICS_COLLECTOR_URL}/metrics", timeout=5.0)
            response.raise_for_status()
            metrics_data = response.json()
        
        with state_lock:
            current_leader = current_master
            is_original = master_is_original
        
        return {
            "current_master": current_leader,
            "master_is_original": is_original,
            "replica_metrics": metrics_data.get("replicas", []),
            "timestamp": metrics_data.get("timestamp")
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get leader info: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
