"""
Cabinet Service - Dynamically Weighted Consensus

Implements the Cabinet algorithm for adaptive quorum selection.
Instead of waiting for all replicas, we select a quorum based on performance:
- Weight replicas by latency and replication lag
- Select the fastest, most up-to-date replicas for the quorum
- Ensures strong consistency while minimizing write latency

This provides better performance than fixed quorums while maintaining safety.
"""

import os
import httpx
from typing import List
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import math

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


class QuorumRequest(BaseModel):
    """Request model for quorum selection"""
    operation: str = "write"  # Future: could support different quorum sizes for reads


class QuorumResponse(BaseModel):
    """Response model containing selected quorum"""
    quorum: List[str]  # List of replica IDs
    quorum_size: int
    total_replicas: int


class ReplicaWeight(BaseModel):
    """Internal model for replica weighting"""
    replica_id: str
    weight: float
    latency_ms: float
    replication_lag: int
    is_healthy: bool


def calculate_replica_weight(latency_ms: float, replication_lag: int, is_healthy: bool) -> float:
    """
    Calculate weight for a replica based on its performance metrics.
    
    Higher weight = better performance
    
    Args:
        latency_ms: Network latency in milliseconds
        replication_lag: Number of timestamps behind master
        is_healthy: Whether the replica is currently healthy
        
    Returns:
        Weight score (higher is better)
    """
    if not is_healthy:
        return 0.0  # Unhealthy replicas get zero weight
    
    # Weight formula: inverse of (latency + lag)
    # Add 1 to avoid division by zero
    weight = 1.0 / (latency_ms + replication_lag + 1.0)
    
    return weight


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
            response = await client.get(f"{METRICS_COLLECTOR_URL}/metrics", timeout=5.0)
            response.raise_for_status()
            return response.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Failed to fetch metrics: {str(e)}")


@app.post("/select-quorum", response_model=QuorumResponse)
async def select_quorum(request: QuorumRequest):
    """
    Select optimal quorum for a write operation using the Cabinet algorithm.
    
    Algorithm:
    1. Fetch metrics for all replicas
    2. Calculate weight for each replica (based on latency + lag)
    3. Sort replicas by weight (descending)
    4. Select top N replicas where N = ⌈(total_replicas + 1) / 2⌉ (majority)
    
    Args:
        request: QuorumRequest containing operation type
        
    Returns:
        QuorumResponse: List of replica IDs in the selected quorum
    """
    # Fetch current metrics
    metrics_data = await fetch_metrics()
    replicas = metrics_data.get("replicas", [])
    
    if not replicas:
        raise HTTPException(status_code=503, detail="No replicas available")
    
    # Calculate weights for all replicas
    weighted_replicas = []
    for replica in replicas:
        weight = calculate_replica_weight(
            latency_ms=replica["latency_ms"],
            replication_lag=replica["replication_lag"],
            is_healthy=replica["is_healthy"]
        )
        
        weighted_replicas.append(ReplicaWeight(
            replica_id=replica["replica_id"],
            weight=weight,
            latency_ms=replica["latency_ms"],
            replication_lag=replica["replication_lag"],
            is_healthy=replica["is_healthy"]
        ))
    
    # Sort by weight (descending - highest weight first)
    weighted_replicas.sort(key=lambda x: x.weight, reverse=True)
    
    # Calculate quorum size (majority)
    total_replicas = len(replicas)
    quorum_size = math.ceil((total_replicas + 1) / 2)
    
    # Select top N replicas for quorum
    quorum = [r.replica_id for r in weighted_replicas[:quorum_size]]
    
    # Ensure we have at least one healthy replica in quorum
    healthy_in_quorum = sum(1 for r in weighted_replicas[:quorum_size] if r.is_healthy)
    if healthy_in_quorum == 0:
        raise HTTPException(
            status_code=503,
            detail="No healthy replicas available for quorum"
        )
    
    return QuorumResponse(
        quorum=quorum,
        quorum_size=quorum_size,
        total_replicas=total_replicas
    )


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "cabinet"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
