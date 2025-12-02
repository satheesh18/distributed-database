"""
Timestamp Service - Distributed Timestamp Generation

This service provides globally ordered timestamps using an odd/even assignment strategy:
- Server 1: Assigns odd numbers (1, 3, 5, 7, ...)
- Server 2: Assigns even numbers (2, 4, 6, 8, ...)

This ensures total ordering of writes across the distributed system.
"""

import os
import threading
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

# Configuration from environment variables
SERVER_ID = int(os.getenv("SERVER_ID", "1"))  # 1 or 2
START_VALUE = int(os.getenv("START_VALUE", "1"))  # 1 for odd, 2 for even

# Thread-safe counter
counter_lock = threading.Lock()
current_counter = START_VALUE


class TimestampResponse(BaseModel):
    """Response model for timestamp requests"""
    timestamp: int
    server_id: int


@app.get("/timestamp", response_model=TimestampResponse)
async def get_timestamp():
    """
    Generate and return a globally ordered timestamp.
    
    Returns:
        TimestampResponse: Contains the timestamp and server ID
        
    Example:
        Server 1 returns: {"timestamp": 1, "server_id": 1}
        Next call to Server 1: {"timestamp": 3, "server_id": 1}
        Server 2 returns: {"timestamp": 2, "server_id": 2}
        Next call to Server 2: {"timestamp": 4, "server_id": 2}
    """
    global current_counter
    
    with counter_lock:
        # Get current timestamp
        timestamp = current_counter
        # Increment by 2 to maintain odd/even pattern
        current_counter += 2
    
    return TimestampResponse(timestamp=timestamp, server_id=SERVER_ID)


@app.post("/reset")
async def reset_counter():
    """
    Reset the timestamp counter to its initial value.
    Called when clearing data to ensure timestamps start fresh.
    
    Returns:
        Dictionary with reset confirmation and new counter value
    """
    global current_counter
    
    with counter_lock:
        current_counter = START_VALUE
    
    return {
        "status": "reset",
        "server_id": SERVER_ID,
        "current_counter": current_counter
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "server_id": SERVER_ID,
        "current_counter": current_counter
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
