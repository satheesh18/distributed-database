# Distributed Database System - Complete Project

## Project Structure

```
final_project/
├── backend/                    # Distributed database backend
│   ├── docker-compose.yml     # Orchestrates 10 containers
│   ├── coordinator/           # Main API (FastAPI)
│   ├── timestamp-service/     # Odd/even timestamps
│   ├── metrics-collector/     # Performance monitoring
│   ├── cabinet-service/       # Adaptive quorum
│   ├── seer-service/          # Leader election
│   ├── mysql-config/          # MySQL setup
│   ├── README.md             # Backend documentation
│   └── WALKTHROUGH.md        # Implementation walkthrough
│
└── frontend/                  # Vue.js dashboard
    ├── src/
    │   ├── views/
    │   │   └── HomeView.vue  # Main dashboard
    │   ├── main.ts           # App setup with PrimeVue
    │   └── assets/main.css   # Custom styles
    ├── package.json
    └── README.md             # Frontend documentation
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

## Features

### Backend
- ✅ **Distributed Timestamps**: Odd/even assignment for global ordering
- ✅ **Adaptive Quorum Replication**: Cabinet algorithm selects best replicas
- ✅ **Performance-Aware Leader Election**: SEER algorithm for intelligent failover
- ✅ **Strong Consistency**: Quorum-based writes (majority confirmation)
- ✅ **Intelligent Read Routing**: Routes to best replica based on latency/lag
- ✅ **Custom Replication**: Manual replication logic (no binlog)

### Frontend Dashboard
- ✅ **Service Status Monitoring**: Real-time health checks for all services
- ✅ **Replica Metrics**: Live table showing latency, lag, uptime, crashes
- ✅ **Query Execution**: Execute SQL queries with visual feedback
- ✅ **Execution Flow**: Step-by-step visualization of query processing
- ✅ **Quorum Selection**: Visualize Cabinet algorithm in action
- ✅ **Leader Election**: Trigger and visualize SEER algorithm
- ✅ **Master Failover Testing**: Stop/start master to test automatic failover

## Usage Examples

### Execute a Write Query

1. Open the dashboard at http://localhost:5173
2. In the "Query Execution" section, enter:
   ```sql
   INSERT INTO users (name, email) VALUES ("Alice", "alice@example.com")
   ```
3. Click "Execute Query"
4. Watch the execution flow:
   - Query parsing
   - Timestamp assignment (e.g., timestamp: 5)
   - Execution on master
   - Quorum achievement (2/2 replicas)

### Test Quorum Selection

1. Click "Get Quorum" button
2. See Cabinet algorithm select best replicas
3. Execution flow shows:
   - Selected quorum (e.g., replica-3, replica-2)
   - Quorum size (2 out of 3)

### Test Leader Election

1. Click "Elect Leader" button
2. See SEER algorithm score all replicas
3. Execution flow shows:
   - Elected leader (e.g., replica-3)
   - Leader score (based on latency, stability, lag)

### Test Master Failover

1. In "Danger Zone", click "Stop Master"
2. Execute a write query
3. Watch automatic failover:
   - Master failure detected
   - SEER elects new leader
   - Query retried on new master
   - System continues operating

## API Endpoints

| Service | Port | Endpoints |
|---------|------|-----------|
| Coordinator | 8000 | `/query`, `/status`, `/health` |
| Timestamp 1 | 8001 | `/timestamp`, `/health` |
| Timestamp 2 | 8002 | `/timestamp`, `/health` |
| Metrics | 8003 | `/metrics`, `/metrics/{id}`, `/health` |
| Cabinet | 8004 | `/select-quorum`, `/health` |
| SEER | 8005 | `/elect-leader`, `/health` |

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

- **Backend README**: `backend/README.md`
- **Backend Walkthrough**: `backend/WALKTHROUGH.md`
- **Frontend README**: `frontend/README.md`
- **Project Description**: `desc.md`

## References

- **Timestamp as a Service**: [PVLDB 2023](https://www.vldb.org/pvldb/vol17/p994-li.pdf)
- **Cabinet**: [arXiv 2025](https://arxiv.org/abs/2503.08914)
- **SEER**: [arXiv 2021](https://arxiv.org/abs/2104.01355)
