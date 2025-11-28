"""
Metrics Collector Service

Monitors all MySQL instances and collects performance metrics:
- Latency (connection + query time)
- Replication lag (timestamp difference from master)
- Uptime (time since last failure)
- Crash count (historical failures)

These metrics are used by Cabinet and SEER services for decision making.
"""

import os
import time
import asyncio
import threading
from typing import Dict, List
from datetime import datetime
import mysql.connector
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "rootpass")
MYSQL_MASTER_HOST = os.getenv("MYSQL_MASTER_HOST", "mysql-instance-1")

# Three replica configuration
MYSQL_REPLICAS = [
    {"id": "instance-2", "host": os.getenv("MYSQL_REPLICA_2_HOST", "mysql-instance-2")},
    {"id": "instance-3", "host": os.getenv("MYSQL_REPLICA_3_HOST", "mysql-instance-3")},
    {"id": "instance-4", "host": os.getenv("MYSQL_REPLICA_4_HOST", "mysql-instance-4")},
]


# Global metrics storage
metrics_lock = threading.Lock()
replica_metrics: Dict[str, dict] = {}


class ReplicaMetrics(BaseModel):
    """Metrics for a single replica"""
    replica_id: str
    latency_ms: float
    replication_lag: int  # Timestamp difference from master
    uptime_seconds: float
    crash_count: int
    last_updated: str
    is_healthy: bool


class MetricsResponse(BaseModel):
    """Response containing all replica metrics"""
    replicas: List[ReplicaMetrics]
    master_timestamp: int


def get_mysql_connection(host: str):
    """
    Create a MySQL connection to the specified host.
    
    Args:
        host: MySQL host address
        
    Returns:
        MySQL connection object or None if connection fails
    """
    try:
        conn = mysql.connector.connect(
            host=host,
            port=3306,
            user="root",
            password=MYSQL_PASSWORD,
            database="testdb",
            connect_timeout=5
        )
        return conn
    except Exception as e:
        print(f"Failed to connect to {host}: {e}")
        return None


def measure_latency(host: str) -> float:
    """
    Measure latency to a MySQL instance (connection + simple query).
    
    Args:
        host: MySQL host address
        
    Returns:
        Latency in milliseconds
    """
    start_time = time.time()
    conn = get_mysql_connection(host)
    
    if not conn:
        return 9999.0  # High latency for failed connections
    
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchall()
        cursor.close()
        conn.close()
        
        end_time = time.time()
        return (end_time - start_time) * 1000  # Convert to milliseconds
    except Exception as e:
        print(f"Error measuring latency for {host}: {e}")
        return 9999.0


def get_last_applied_timestamp(host: str) -> int:
    """
    Get the last applied timestamp from a MySQL instance.
    
    Args:
        host: MySQL host address
        
    Returns:
        Last applied timestamp or 0 if unavailable
    """
    conn = get_mysql_connection(host)
    if not conn:
        return 0
    
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT last_applied_timestamp FROM _metadata LIMIT 1")
        result = cursor.fetchone()
        cursor.close()
        conn.close()
        
        return result[0] if result else 0
    except Exception as e:
        print(f"Error getting timestamp from {host}: {e}")
        return 0


def get_replication_status(host: str) -> dict:
    """
    Get binlog replication status from a replica.
    
    Args:
        host: MySQL host address
        
    Returns:
        Dictionary with replication status or empty dict if unavailable
    """
    conn = get_mysql_connection(host)
    if not conn:
        return {}
    
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SHOW SLAVE STATUS")
        result = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if result:
            return {
                "slave_io_running": result.get("Slave_IO_Running", "No"),
                "slave_sql_running": result.get("Slave_SQL_Running", "No"),
                "seconds_behind_master": result.get("Seconds_Behind_Master", None),
                "master_host": result.get("Master_Host", ""),
                "read_master_log_pos": result.get("Read_Master_Log_Pos", 0),
                "exec_master_log_pos": result.get("Exec_Master_Log_Pos", 0),
            }
        return {}
    except Exception as e:
        print(f"Error getting replication status from {host}: {e}")
        return {}


def collect_metrics():
    """
    Background task to collect metrics from all replicas.
    Runs every 5 seconds.
    """
    global replica_metrics
    
    # Initialize metrics for each replica
    for replica in MYSQL_REPLICAS:
        replica_id = replica["id"]
        if replica_id not in replica_metrics:
            replica_metrics[replica_id] = {
                "latency_ms": 0.0,
                "replication_lag": 0,
                "uptime_seconds": 0.0,
                "crash_count": 0,
                "start_time": time.time(),
                "last_crash_time": None,
                "is_healthy": True
            }
    
    while True:
        try:
            # Get master's current timestamp
            master_timestamp = get_last_applied_timestamp(MYSQL_MASTER_HOST)
            
            # Collect metrics for each replica
            for replica in MYSQL_REPLICAS:
                replica_id = replica["id"]
                host = replica["host"]
                
                # Measure latency
                latency = measure_latency(host)
                
                # Get replica's last applied timestamp
                replica_timestamp = get_last_applied_timestamp(host)
                
                # Calculate replication lag
                lag = max(0, master_timestamp - replica_timestamp)
                
                with metrics_lock:
                    metrics = replica_metrics[replica_id]
                    
                    # Check if replica is healthy
                    was_healthy = metrics["is_healthy"]
                    is_healthy = latency < 5000  # Consider unhealthy if latency > 5s
                    
                    # Track crashes (transitions from healthy to unhealthy)
                    if was_healthy and not is_healthy:
                        metrics["crash_count"] += 1
                        metrics["last_crash_time"] = time.time()
                        metrics["start_time"] = time.time()  # Reset uptime
                    
                    # Update metrics
                    metrics["latency_ms"] = latency
                    metrics["replication_lag"] = lag
                    metrics["is_healthy"] = is_healthy
                    
                    # Calculate uptime
                    if is_healthy:
                        metrics["uptime_seconds"] = time.time() - metrics["start_time"]
                    else:
                        metrics["uptime_seconds"] = 0.0
            
            # Sleep for 5 seconds before next collection
            time.sleep(5)
            
        except Exception as e:
            print(f"Error in metrics collection: {e}")
            time.sleep(5)


@app.on_event("startup")
async def startup_event():
    """Start the background metrics collection task"""
    thread = threading.Thread(target=collect_metrics, daemon=True)
    thread.start()


@app.get("/metrics", response_model=MetricsResponse)
async def get_all_metrics():
    """
    Get metrics for all replicas.
    
    Returns:
        MetricsResponse: Contains metrics for all replicas and master timestamp
    """
    with metrics_lock:
        replicas = []
        for replica_id, metrics in replica_metrics.items():
            replicas.append(ReplicaMetrics(
                replica_id=replica_id,
                latency_ms=metrics["latency_ms"],
                replication_lag=metrics["replication_lag"],
                uptime_seconds=metrics["uptime_seconds"],
                crash_count=metrics["crash_count"],
                last_updated=datetime.now().isoformat(),
                is_healthy=metrics["is_healthy"]
            ))
        
        master_timestamp = get_last_applied_timestamp(MYSQL_MASTER_HOST)
        
        return MetricsResponse(replicas=replicas, master_timestamp=master_timestamp)


@app.get("/metrics/{replica_id}", response_model=ReplicaMetrics)
async def get_replica_metrics(replica_id: str):
    """
    Get metrics for a specific replica.
    
    Args:
        replica_id: ID of the replica (e.g., "replica-1")
        
    Returns:
        ReplicaMetrics: Metrics for the specified replica
    """
    with metrics_lock:
        if replica_id not in replica_metrics:
            return {"error": "Replica not found"}
        
        metrics = replica_metrics[replica_id]
        return ReplicaMetrics(
            replica_id=replica_id,
            latency_ms=metrics["latency_ms"],
            replication_lag=metrics["replication_lag"],
            uptime_seconds=metrics["uptime_seconds"],
            crash_count=metrics["crash_count"],
            last_updated=datetime.now().isoformat(),
            is_healthy=metrics["is_healthy"]
        )


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "replicas_tracked": len(replica_metrics)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
