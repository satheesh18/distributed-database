# Distributed Database System

A distributed MySQL database system implementing logical timestamps, adaptive quorums (Cabinet), and performance-aware leader election (SEER).

## Overview

This system provides:
- **Distributed Timestamps**: Global ordering of writes using odd/even assignment
- **Adaptive Quorum Replication**: Dynamic replica selection based on performance (Cabinet algorithm)
- **Performance-Aware Failover**: Intelligent leader election on master failure (SEER algorithm)
- **Strong Consistency**: Quorum-based replication ensures data consistency

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                         Client                              │
└────────────────────────┬────────────────────────────────────┘
                         │ SQL Queries
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              Main Coordinator (FastAPI)                     │
│  - Query parsing                                            │
│  - Request routing (writes → master, reads → replicas)      │
│  - Quorum-based replication (strong consistency)            │
└──┬────────┬────────┬────────┬────────┬────────┬────────┬───┘
   │        │        │        │        │        │        │
   ▼        ▼        ▼        ▼        ▼        ▼        ▼
┌──────┐┌──────┐┌──────┐┌──────┐┌──────┐┌──────┐┌──────┐┌──────┐
│MySQL ││MySQL ││MySQL ││MySQL ││Metrics││Cabinet││SEER  ││TS    │
│Master││Rep 1 ││Rep 2 ││Rep 3 ││Coll. ││      ││      ││Svc   │
└──────┘└──────┘└──────┘└──────┘└──────┘└──────┘└──────┘└──────┘
```

### Components

1. **MySQL Instances** (4 containers)
   - 1 Master: Handles all writes
   - 3 Replicas: Receive replicated writes, can serve reads

2. **Coordinator** (FastAPI)
   - Single entry point for all SQL queries
   - Routes writes to master, reads to replicas
   - Coordinates timestamp assignment and replication

3. **Timestamp Service** (2 containers)
   - Server 1: Assigns odd numbers (1, 3, 5, ...)
   - Server 2: Assigns even numbers (2, 4, 6, ...)
   - Provides total ordering for write operations

4. **Metrics Collector**
   - Monitors all MySQL instances
   - Tracks: latency, replication lag, uptime, crash count
   - Provides metrics to Cabinet and SEER services

5. **Cabinet Service**
   - Implements adaptive quorum selection
   - Weights replicas by performance (latency + lag)
   - Selects best replicas for write quorum

6. **SEER Service**
   - Implements performance-aware leader election
   - Scores replicas by latency, stability, and lag
   - Elects best replica as new master on failure

## Prerequisites

- Docker
- Docker Compose

## Quick Start

```bash
# Navigate to backend directory
cd backend

# Start all services
docker-compose up -d

# Check service health
docker-compose ps

# View logs
docker-compose logs -f coordinator
```

## Usage

### Write Query

```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "INSERT INTO users (name, email) VALUES (\"Alice\", \"alice@example.com\")"}'
```

Response:
```json
{
  "success": true,
  "message": "Write successful (timestamp: 5, quorum: 2/2)",
  "timestamp": 5,
  "rows_affected": 1,
  "executed_on": "mysql-master"
}
```

### Read Query

```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "SELECT * FROM users"}'
```

Response:
```json
{
  "success": true,
  "message": "Read successful",
  "data": [
    {
      "id": 1,
      "name": "Alice",
      "email": "alice@example.com",
      "created_at": "2025-11-23T16:30:00",
      "timestamp": 5
    }
  ],
  "rows_affected": 1,
  "executed_on": "mysql-master"
}
```

### Check System Status

```bash
curl http://localhost:8000/status
```

Response:
```json
{
  "current_master": "mysql-master",
  "master_is_original": true,
  "replicas": ["replica-1", "replica-2", "replica-3"]
}
```

## Algorithms

### Timestamp Service

**Purpose**: Provide globally ordered timestamps for write operations

**Implementation**:
- Two timestamp servers with odd/even assignment
- Server 1: Returns 1, 3, 5, 7, ...
- Server 2: Returns 2, 4, 6, 8, ...
- Coordinator load balances between servers
- Ensures total ordering of all writes

### Cabinet (Adaptive Quorum)

**Purpose**: Select optimal replicas for write quorum based on performance

**Algorithm**:
1. Fetch metrics for all replicas
2. Calculate weight: `weight = 1 / (latency + lag + 1)`
3. Sort replicas by weight (descending)
4. Select top N replicas where N = ⌈(3 + 1) / 2⌉ = 2 (majority)

**Benefits**:
- Faster writes by avoiding slow replicas
- Strong consistency via majority quorum
- Adapts to changing network conditions

### SEER (Leader Election)

**Purpose**: Elect best replica as new master when current master fails

**Algorithm**:
1. Fetch metrics for all replicas
2. Calculate scores:
   - Latency score (40%): `1 / (latency + 1)`
   - Stability score (40%): `uptime / (uptime + crashes * 100 + 1)`
   - Lag score (20%): `1 / (lag + 1)`
3. Select replica with highest total score

**Benefits**:
- Fast, reliable new master
- Considers performance and stability
- Minimizes disruption during failover

## Testing

### 1. Basic Write and Read

```bash
# Insert data
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "INSERT INTO users (name, email) VALUES (\"Bob\", \"bob@example.com\")"}'

# Read data
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "SELECT * FROM users"}'
```

### 2. Test Failover

```bash
# Stop the master
docker-compose stop mysql-master

# Wait a few seconds for detection
sleep 5

# Try a write (should trigger failover)
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "INSERT INTO users (name, email) VALUES (\"Charlie\", \"charlie@example.com\")"}'

# Check new master
curl http://localhost:8000/status
```

### 3. Check Metrics

```bash
# View all replica metrics
curl http://localhost:8003/metrics

# View specific replica
curl http://localhost:8003/metrics/replica-1
```

### 4. Test Quorum Selection

```bash
# Get current quorum
curl -X POST http://localhost:8004/select-quorum \
  -H "Content-Type: application/json" \
  -d '{"operation": "write"}'
```

### 5. Test Leader Election

```bash
# Trigger leader election
curl -X POST http://localhost:8005/elect-leader \
  -H "Content-Type: application/json" \
  -d '{}'
```

## Service Endpoints

| Service | Port | Endpoints |
|---------|------|-----------|
| Coordinator | 8000 | `/query`, `/status`, `/health` |
| Timestamp 1 | 8001 | `/timestamp`, `/health` |
| Timestamp 2 | 8002 | `/timestamp`, `/health` |
| Metrics | 8003 | `/metrics`, `/metrics/{id}`, `/health` |
| Cabinet | 8004 | `/select-quorum`, `/health` |
| SEER | 8005 | `/elect-leader`, `/health` |

## Stopping the System

```bash
# Stop all services
docker-compose down

# Stop and remove volumes (clears data)
docker-compose down -v
```

## Troubleshooting

### Services not starting

```bash
# Check logs
docker-compose logs

# Rebuild containers
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

### Connection errors

- Ensure all services are healthy: `docker-compose ps`
- Check network connectivity: `docker network inspect backend_db-network`
- Verify MySQL instances are ready: `docker-compose logs mysql-master`

### Quorum failures

- Check replica health: `curl http://localhost:8003/metrics`
- Verify at least 2 replicas are healthy
- Check Cabinet service: `curl http://localhost:8004/health`

## Project Structure

```
backend/
├── docker-compose.yml          # Orchestrates all containers
├── coordinator/                # Main coordinator service
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py                # Query routing and replication
│   └── query_parser.py        # SQL query parser
├── timestamp-service/          # Distributed timestamp service
│   ├── Dockerfile
│   ├── requirements.txt
│   └── main.py                # Odd/even timestamp assignment
├── metrics-collector/          # Performance monitoring
│   ├── Dockerfile
│   ├── requirements.txt
│   └── main.py                # Metrics collection
├── cabinet-service/            # Adaptive quorum selection
│   ├── Dockerfile
│   ├── requirements.txt
│   └── main.py                # Cabinet algorithm
├── seer-service/               # Leader election
│   ├── Dockerfile
│   ├── requirements.txt
│   └── main.py                # SEER algorithm
└── mysql-config/               # MySQL configuration
    ├── master.cnf             # Master config
    ├── replica.cnf            # Replica config
    └── init.sql               # Database initialization
```

## Implementation Notes

- **Custom Replication**: We implement our own replication logic instead of using MySQL binlog
- **Strong Consistency**: Achieved through quorum-based writes (majority of replicas must confirm)
- **Simplified Algorithms**: Core concepts implemented for educational purposes
- **Minimal Dependencies**: Uses standard Python libraries and FastAPI

## References

- **Timestamp as a Service**: [PVLDB 2023](https://www.vldb.org/pvldb/vol17/p994-li.pdf)
- **Cabinet**: [arXiv 2025](https://arxiv.org/abs/2503.08914)
- **SEER**: [arXiv 2021](https://arxiv.org/abs/2104.01355)
