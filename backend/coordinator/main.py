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

import os
import random
import threading
import mysql.connector
import httpx
from typing import Dict, List, Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from query_parser import parse_query, is_write_query, is_read_query

app = FastAPI()

# Configuration
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "rootpass")
MYSQL_MASTER_HOST = os.getenv("MYSQL_MASTER_HOST", "mysql-master")
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
    
    # Step 3: Get quorum
    quorum = await get_quorum()
    
    # Step 4: Replicate to quorum
    successful_replications = 0
    failed_replicas = []
    
    for replica_id in quorum:
        replica_host = next((r["host"] for r in MYSQL_REPLICAS if r["id"] == replica_id), None)
        if not replica_host:
            continue
        
        replica_result = execute_query_on_host(replica_host, query, timestamp)
        
        if replica_result["success"]:
            successful_replications += 1
        else:
            failed_replicas.append(replica_id)
            print(f"Replication to {replica_id} failed: {replica_result.get('error')}")
    
    # Step 5: Check if quorum was achieved
    quorum_size = len(quorum)
    if successful_replications < (quorum_size // 2 + 1):
        raise HTTPException(
            status_code=500,
            detail=f"Quorum not achieved: {successful_replications}/{quorum_size} replicas confirmed"
        )
    
    return QueryResponse(
        success=True,
        message=f"Write successful (timestamp: {timestamp}, quorum: {successful_replications}/{quorum_size})",
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
