# Backend - Distributed Database System

Backend services for a distributed MySQL database implementing adaptive quorums (Cabinet) and performance-aware leader election (SEER).

> **Note**: For architecture overview and algorithm explanations, see the main [README.md](../README.md) in the project root.

## Prerequisites

- Docker
- Docker Compose

## Quick Start

```bash
# Start all services (10 containers)
docker-compose up -d

# Check service health
docker-compose ps

# View coordinator logs
docker-compose logs -f coordinator
```

## Service Endpoints

| Service | Port | Endpoints |
|---------|------|-----------|
| Coordinator | 9000 | `/query`, `/status`, `/health`, `/admin/*` |
| Timestamp 1 | 9001 | `/timestamp`, `/health` |
| Timestamp 2 | 9002 | `/timestamp`, `/health` |
| Metrics Collector | 9003 | `/metrics`, `/metrics/{id}`, `/health` |
| Cabinet | 9004 | `/select-quorum`, `/health` |
| SEER | 9005 | `/elect-leader`, `/health` |

## API Examples

### 1. Basic Operations

#### Check System Status

```bash
curl http://localhost:9000/status
```

Response:
```json
{
  "current_master": {
    "id": "instance-1",
    "host": "mysql-instance-1",
    "container": "mysql-instance-1"
  },
  "current_replicas": [
    {"id": "instance-2", "host": "mysql-instance-2", "container": "mysql-instance-2"},
    {"id": "instance-3", "host": "mysql-instance-3", "container": "mysql-instance-3"},
    {"id": "instance-4", "host": "mysql-instance-4", "container": "mysql-instance-4"}
  ],
  "total_replicas": 3,
  "replication_mode": "binlog"
}
```

#### Execute a Write Query (EVENTUAL - Fast)

```bash
curl -X POST http://localhost:9000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "INSERT INTO users (name, email) VALUES (\"Alice\", \"alice@example.com\")", "consistency": "EVENTUAL"}'
```

#### Execute a Write Query (STRONG - Waits for Quorum)

```bash
curl -X POST http://localhost:9000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "INSERT INTO users (name, email) VALUES (\"Bob\", \"bob@example.com\")", "consistency": "STRONG"}'
```

Response:
```json
{
  "success": true,
  "message": "Write successful (consistency: STRONG, timestamp: 5, Cabinet replicas: instance-2, instance-3)",
  "timestamp": 5,
  "rows_affected": 1,
  "executed_on": "mysql-instance-1",
  "consistency_level": "STRONG",
  "latency_ms": 45.23,
  "quorum_achieved": true
}
```

#### Execute a Read Query

```bash
curl -X POST http://localhost:9000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "SELECT * FROM users"}'
```

### 2. Monitoring & Metrics

#### Get Replica Health Metrics

```bash
curl http://localhost:9003/metrics
```

Response:
```json
{
  "replicas": [
    {
      "replica_id": "instance-2",
      "latency_ms": 14.1,
      "replication_lag": 0,
      "is_healthy": true
    }
  ],
  "master_timestamp": 113
}
```

#### Get Table Timestamps (Replication Lag)

```bash
curl http://localhost:9000/table-timestamps
```

Response:
```json
{
  "master": {
    "id": "instance-1",
    "global_timestamp": 113,
    "table_timestamps": {"users": 113, "products": 0}
  },
  "replicas": [
    {
      "id": "instance-2",
      "global_timestamp": 113,
      "global_lag": 0,
      "table_timestamps": {"users": 113, "products": 0},
      "table_lag": {"users": 0, "products": 0}
    }
  ]
}
```

#### Get Consistency Metrics (EVENTUAL vs STRONG)

```bash
curl http://localhost:9000/consistency-metrics
```

Response:
```json
{
  "EVENTUAL": {
    "write_count": 50,
    "avg_write_latency_ms": 1508.34,
    "failures": 0,
    "success_rate": 100.0
  },
  "STRONG": {
    "write_count": 50,
    "avg_write_latency_ms": 4567.01,
    "failures": 0,
    "quorum_not_achieved": 0,
    "success_rate": 100.0
  }
}
```

### 3. Distributed Algorithms

#### Get Quorum Selection (Cabinet)

```bash
curl -X POST http://localhost:9004/select-quorum \
  -H "Content-Type: application/json" \
  -d '{}'
```

Response:
```json
{
  "quorum": ["instance-3", "instance-2", "instance-4"],
  "quorum_size": 3,
  "total_replicas": 4
}
```

#### Trigger Leader Election (SEER)

```bash
curl -X POST http://localhost:9005/elect-leader \
  -H "Content-Type: application/json" \
  -d '{}'
```

## Testing Failover

```bash
# 1. Stop the master container
docker stop mysql-instance-1

# 2. Try a write (triggers automatic failover)
curl -X POST http://localhost:9000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "INSERT INTO users (name, email) VALUES (\"Test\", \"test@example.com\")"}'

# 3. Check new master
curl http://localhost:9000/status

# 4. Restart old master (becomes replica)
docker start mysql-instance-1
curl -X POST http://localhost:9000/admin/restart-old-master
```

## Stress Testing

### Using the Python Script

```bash
# Install dependencies first
pip install aiohttp

# Run all scenarios
python stress_test.py --scenario all

# Run specific scenarios
python stress_test.py --scenario concurrent --writes 200
python stress_test.py --scenario lag
python stress_test.py --scenario failover
python stress_test.py --scenario performance
```

**Scenarios:**
| Scenario | Description |
|----------|-------------|
| `concurrent` | High concurrent write load - tests timestamp ordering and quorum replication |
| `lag` | Monitor replica lag and Cabinet quorum adaptation |
| `failover` | Simulate master failure and SEER election |
| `performance` | Benchmark writes and measure throughput |
| `all` | Run all scenarios sequentially |

### Using the API Endpoints

```bash
# Clear all test data and reset timestamps
curl -X POST http://localhost:9000/admin/clear-data

# Check current data count
curl http://localhost:9000/admin/stress-test/data-count
```

**Concurrent Writes Test** - Tests timestamp ordering under load:
```bash
curl -X POST http://localhost:9000/admin/stress-test/concurrent-writes \
  -H "Content-Type: application/json" \
  -d '{"num_operations": 50, "consistency": "STRONG"}'
```

**Read/Write Mix Test** - 70% reads, 30% writes (realistic workload):
```bash
curl -X POST http://localhost:9000/admin/stress-test/read-write-mix \
  -H "Content-Type: application/json" \
  -d '{"num_operations": 100, "consistency": "EVENTUAL"}'
```

**Consistency Comparison** - Compare EVENTUAL vs STRONG performance:
```bash
curl -X POST "http://localhost:9000/admin/stress-test/consistency-comparison?num_operations=30"
```

### Consistency Levels

| Level | Writes | Reads | Trade-off |
|-------|--------|-------|-----------|
| `EVENTUAL` | Master only, return immediately | Any replica | Fast, may read stale data |
| `STRONG` | Master + wait for Cabinet quorum | Master only | Slower, guaranteed fresh data |

## Project Structure

```
backend/
├── docker-compose.yml          # Orchestrates all 10 containers
├── coordinator/                # Main API gateway
│   ├── main.py                # Query routing, replication, failover
│   └── query_parser.py        # SQL query parser
├── timestamp-service/          # Distributed timestamps (odd/even)
├── metrics-collector/          # Performance monitoring
├── cabinet-service/            # Adaptive quorum selection
├── seer-service/               # Leader election
├── mysql-config/               # MySQL configuration files
├── stress_test.py              # Stress testing script
└── setup.py                    # Setup/reset utility
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
- Check MySQL instances are ready: `docker-compose logs mysql-instance-1`
- Verify network: `docker network inspect backend_db-network`

### Quorum failures

- Check replica health: `curl http://localhost:9003/metrics`
- Ensure at least 2 replicas are healthy for quorum

## Stopping the System

```bash
# Stop all services
docker-compose down

# Stop and remove volumes (clears all data)
docker-compose down -v
```
