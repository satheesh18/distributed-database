"""
SEER Service - Performance-Aware Leader Election

Implements the SEER algorithm for intelligent leader election.
When the master fails, we elect a new leader based on:
- Latency (network performance)
- Stability (uptime and crash history)
- Replication lag (how up-to-date the replica is)

This ensures the most capable replica becomes the new master.
"""

import os
import httpx
from typing import List, Optional
from fastapi import FastAPI, HTTPException
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
METRICS_COLLECTOR_URL = os.getenv("METRICS_COLLECTOR_URL", "http://metrics-collector:8000")


class LeaderElectionRequest(BaseModel):
    """Request model for leader election"""
    exclude_replicas: Optional[List[str]] = []  # Replicas to exclude from election


class LeaderElectionResponse(BaseModel):
    """Response model containing elected leader"""
    leader_id: str
    score: float
    latency_ms: float
    uptime_seconds: float
    replication_lag: int
    crash_count: int


class ReplicaScore(BaseModel):
    """Internal model for replica scoring"""
    replica_id: str
    total_score: float
    latency_score: float
    stability_score: float
    lag_score: float
    latency_ms: float
    uptime_seconds: float
    replication_lag: int
    crash_count: int
    is_healthy: bool


def calculate_replica_score(
    latency_ms: float,
    uptime_seconds: float,
    crash_count: int,
    replication_lag: int,
    is_healthy: bool
) -> dict:
    """
    Calculate leadership score for a replica.
    
    Score components:
    - Latency score (40%): Lower latency is better
    - Stability score (40%): Higher uptime and fewer crashes is better
    - Lag score (20%): Lower replication lag is better
    
    Args:
        latency_ms: Network latency in milliseconds
        uptime_seconds: Time since last failure
        crash_count: Number of historical failures
        replication_lag: Number of timestamps behind master
        is_healthy: Whether the replica is currently healthy
        
    Returns:
        Dictionary with score components and total score
    """
    if not is_healthy:
        return {
            "latency_score": 0.0,
            "stability_score": 0.0,
            "lag_score": 0.0,
            "total_score": 0.0
        }
    
    # Latency score: inverse of latency (lower latency = higher score)
    latency_score = 1.0 / (latency_ms + 1.0)
    
    # Stability score: uptime weighted against crash history
    # More crashes reduce the score significantly
    stability_penalty = crash_count * 100  # Each crash counts as 100 seconds of downtime
    stability_score = uptime_seconds / (uptime_seconds + stability_penalty + 1.0)
    
    # Lag score: inverse of replication lag (lower lag = higher score)
    lag_score = 1.0 / (replication_lag + 1.0)
    
    # Weighted total score
    total_score = (
        latency_score * 0.4 +
        stability_score * 0.4 +
        lag_score * 0.2
    )
    
    return {
        "latency_score": latency_score,
        "stability_score": stability_score,
        "lag_score": lag_score,
        "total_score": total_score
    }


async def fetch_metrics():
    """
    Fetch current metrics from the metrics collector.
    
    Returns:
        Metrics response from the collector
        
    Raises:
        HTTPException: If metrics cannot be fetched
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{METRICS_COLLECTOR_URL}/metrics", timeout=10.0)
            response.raise_for_status()
            return response.json()
    except httpx.ConnectError as e:
        raise HTTPException(
            status_code=503, 
            detail=f"Cannot connect to metrics collector at {METRICS_COLLECTOR_URL}. Is the service running? Error: {str(e)}"
        )
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=503, 
            detail=f"Timeout connecting to metrics collector at {METRICS_COLLECTOR_URL}"
        )
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=503, 
            detail=f"Metrics collector returned error {e.response.status_code}: {e.response.text}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=503, 
            detail=f"Failed to fetch metrics from {METRICS_COLLECTOR_URL}: {str(e)}"
        )

@app.post("/elect-leader", response_model=LeaderElectionResponse)
async def elect_leader(request: LeaderElectionRequest):
    """
    Elect a new leader using the SEER algorithm.
    
    For 2-instance setup: Simply select the healthy replica (instance-2).
    
    Algorithm:
    1. Fetch metrics for replica
    2. Verify replica is healthy
    3. Return replica as new leader
    
    Args:
        request: LeaderElectionRequest with optional exclusions
        
    Returns:
        LeaderElectionResponse: Information about the elected leader
    """
    # Fetch current metrics
    metrics_data = await fetch_metrics()
    replicas = metrics_data.get("replicas", [])
    
    if not replicas:
        raise HTTPException(status_code=503, detail="No replicas available")
    
    # For 2-instance setup, we only have one replica (instance-2)
    # Filter out excluded replicas
    exclude_set = set(request.exclude_replicas or [])
    replicas = [r for r in replicas if r["replica_id"] not in exclude_set]
    
    if not replicas:
        raise HTTPException(status_code=503, detail="No eligible replicas for election")
    
    # Calculate scores for all replicas
    scored_replicas = []
    for replica in replicas:
        scores = calculate_replica_score(
            latency_ms=replica["latency_ms"],
            uptime_seconds=replica["uptime_seconds"],
            crash_count=replica["crash_count"],
            replication_lag=replica["replication_lag"],
            is_healthy=replica["is_healthy"]
        )
        
        scored_replicas.append(ReplicaScore(
            replica_id=replica["replica_id"],
            total_score=scores["total_score"],
            latency_score=scores["latency_score"],
            stability_score=scores["stability_score"],
            lag_score=scores["lag_score"],
            latency_ms=replica["latency_ms"],
            uptime_seconds=replica["uptime_seconds"],
            replication_lag=replica["replication_lag"],
            crash_count=replica["crash_count"],
            is_healthy=replica["is_healthy"]
        ))
    
    # Sort by total score (descending - highest score first)
    scored_replicas.sort(key=lambda x: x.total_score, reverse=True)
    
    # Select the highest scoring replica as leader
    leader = scored_replicas[0]
    
    if leader.total_score == 0.0:
        raise HTTPException(
            status_code=503,
            detail="No healthy replicas available for leader election"
        )
    
    return LeaderElectionResponse(
        leader_id=leader.replica_id,
        score=leader.total_score,
        latency_ms=leader.latency_ms,
        uptime_seconds=leader.uptime_seconds,
        replication_lag=leader.replication_lag,
        crash_count=leader.crash_count
    )


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "seer"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
