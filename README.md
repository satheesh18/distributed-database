# Distributed Database System - Complete Project

## Project Structure

```
distributed-database/
├── backend/                    # Distributed database backend
│   ├── docker-compose.yml     # Orchestrates 10 containers
│   ├── coordinator/           # Main API (FastAPI)
│   ├── timestamp-service/     # Odd/even timestamps
│   ├── metrics-collector/     # Performance monitoring
│   ├── cabinet-service/       # Adaptive quorum
│   ├── seer-service/          # Leader election
│   ├── mysql-config/          # MySQL setup
│   └── README.md              # Backend documentation
│
└── frontend/                   # Vue.js dashboard
    ├── src/
    │   ├── views/
    │   │   └── HomeView.vue   # Main dashboard
    │   ├── main.ts            # App setup with PrimeVue
    │   └── assets/main.css    # Custom styles
    ├── package.json
    └── README.md              # Frontend documentation
```

## Quick Start

### 1. Start Backend

```bash
cd backend
docker-compose up -d
```

This starts all 10 containers:
- MySQL Master + 3 Replicas
- 2 Timestamp Services
- Metrics Collector
- Cabinet Service (Quorum Selection)
- SEER Service (Leader Election)
- Coordinator (API Gateway)

### 2. Start Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 in your browser.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Client / Frontend                         │
└────────────────────────┬────────────────────────────────────┘
                         │ HTTP Requests
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              Coordinator (FastAPI - Port 9000)              │
│  • Query parsing & routing                                  │
│  • Timestamp coordination                                   │
│  • Quorum-based replication verification                    │
│  • Failover orchestration                                   │
└──┬────┬────┬────┬────┬────┬────┬────┬────┬────────────────┘
   │    │    │    │    │    │    │    │    │
   ▼    ▼    ▼    ▼    ▼    ▼    ▼    ▼    ▼
┌─────┐┌─────┐┌─────┐┌─────┐┌─────┐┌─────┐┌─────┐┌─────┐┌─────┐
│MySQL││MySQL││MySQL││MySQL││TS-1 ││TS-2 ││Metr.││Cab. ││SEER │
│Mstr ││Rep2 ││Rep3 ││Rep4 ││Odd  ││Even ││Coll.││     ││     │
│:3306││:3307││:3308││:3309││:9001││:9002││:9003││:9004││:9005│
└─────┘└─────┘└─────┘└─────┘└─────┘└─────┘└─────┘└─────┘└─────┘
   │       │       │       │
   └───────┴───────┴───────┘
   MySQL Binlog Replication
```

**Components:**
- **MySQL Instances**: 1 master + 3 replicas with binlog replication
- **Timestamp Services**: Odd/even assignment for global ordering
- **Metrics Collector**: Monitors latency, lag, uptime, crashes
- **Cabinet Service**: Adaptive quorum selection based on performance
- **SEER Service**: Performance-aware leader election
- **Coordinator**: Main API gateway orchestrating all operations

## Features

### Backend
- ✅ **Distributed Timestamps**: Odd/even assignment for global ordering
- ✅ **Adaptive Quorum Replication**: Cabinet algorithm selects best replicas
- ✅ **Performance-Aware Leader Election**: SEER algorithm for intelligent failover
- ✅ **Strong Consistency**: Quorum-based writes (majority confirmation)
- ✅ **Intelligent Read Routing**: Routes to best replica based on latency/lag
- ✅ **Binlog-Based Replication**: MySQL native binary log replication with GTID

### Frontend Dashboard
- ✅ **Service Status Monitoring**: Real-time health checks for all 10 services
- ✅ **Cluster Topology**: Visual master-replica layout with live metrics
- ✅ **Replica Metrics**: Live display of latency, lag, uptime per replica
- ✅ **Failover Testing**: Stop master and trigger SEER election with progress visualization
- ✅ **Stress Testing**: Run concurrent operations with configurable consistency levels

## Usage Examples

### Monitor Cluster Status

1. Open the dashboard at http://localhost:5173
2. View **Service Status** section for health of all 10 services
3. View **Cluster Topology** to see master and replica metrics:
   - Latency (network round-trip time)
   - Replication lag (transactions behind master)
   - Uptime and health status

### Test Master Failover

1. In the **Failover Testing** section, click "Stop Master and Failover"
2. Watch the failover progress:
   - Current master is stopped
   - SEER algorithm scores all replicas
   - Best replica is elected as new master
   - Other replicas reconfigure to follow new master
   - Old master restarts as a replica

### Run Stress Test

1. Go to the **Stress Testing** section
2. Configure the test:
   - Select number of concurrent operations (10, 25, 50, or 100)
   - Choose consistency level (EVENTUAL or STRONG)
3. Click "Run Stress Test"
4. Watch live progress showing:
   - Operations completed
   - Success/failure counts
   - Average latency
   - Timestamp ordering verification

## API Endpoints

| Service | Port | Endpoints |
|---------|------|-----------|
| Coordinator | 9000 | `/query`, `/status`, `/health` |
| Timestamp 1 | 9001 | `/timestamp`, `/health` |
| Timestamp 2 | 9002 | `/timestamp`, `/health` |
| Metrics | 9003 | `/metrics`, `/metrics/{id}`, `/health` |
| Cabinet | 9004 | `/select-quorum`, `/health` |
| SEER | 9005 | `/elect-leader`, `/health` |

## Technology Stack

### Backend
- **Python 3.11** with FastAPI
- **MySQL 8.0** (1 master + 3 replicas)
- **Docker & Docker Compose**
- **httpx** for inter-service communication

### Frontend
- **Vue.js 3** with TypeScript
- **PrimeVue v4** with Aura theme (light mode)
- **Pinia** for state management
- **Vite** for build tooling

## Key Algorithms

### 1. Timestamp as a Service
- Server 1: Assigns odd numbers (1, 3, 5, ...)
- Server 2: Assigns even numbers (2, 4, 6, ...)
- Provides total ordering without coordination

### 2. Cabinet (Adaptive Quorum)
```python
weight = 1 / (latency + lag + 1)
quorum = top_N_replicas(sorted_by_weight)
```
- Selects fastest, most up-to-date replicas
- Ensures strong consistency via majority

### 3. SEER (Leader Election)
```python
score = latency_score * 0.4 + stability_score * 0.4 + lag_score * 0.2
leader = replica_with_highest_score
```
- Considers performance, stability, and freshness
- Minimizes disruption during failover

## Stopping the System

```bash
# Stop backend
cd backend
docker-compose down

# Stop frontend (Ctrl+C in terminal)
```

## Documentation

- **Backend README**: `backend/README.md` - API examples, testing, troubleshooting
- **Frontend README**: `frontend/README.md` - Dashboard features and setup

## References

- **Timestamp as a Service**: [PVLDB 2023](https://www.vldb.org/pvldb/vol17/p994-li.pdf)
- **Cabinet**: [arXiv 2025](https://arxiv.org/abs/2503.08914)
- **SEER**: [arXiv 2021](https://arxiv.org/abs/2104.01355)
