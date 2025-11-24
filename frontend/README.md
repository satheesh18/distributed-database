# Distributed Database Dashboard

A Vue.js frontend dashboard to visualize and interact with the distributed database system.

## Features

- **Service Status Monitoring**: Real-time health checks for all 10 services
- **Replica Metrics**: Live metrics showing latency, replication lag, uptime, and crash count
- **Query Execution**: Execute SQL queries and see the execution flow step-by-step
- **Execution Flow Visualization**: See how queries are processed (timestamp assignment, quorum selection, replication)
- **Quorum Selection**: Visualize Cabinet algorithm selecting optimal replicas
- **Leader Election**: Trigger SEER algorithm to elect best replica as leader
- **Master Failover Testing**: Stop/start master to test automatic failover

## Tech Stack

- **Vue.js 3** with TypeScript
- **PrimeVue v4** with Aura theme (light mode)
- **Pinia** for state management
- **Vue Router** for navigation

## Setup

```bash
# Install dependencies
npm install

# Start development server
npm run dev

# Build for production
npm run build
```

## Usage

1. Make sure the backend is running:
   ```bash
   cd ../backend
   docker-compose up -d
   ```

2. Start the frontend:
   ```bash
   npm run dev
   ```

3. Open http://localhost:5173 in your browser

## Dashboard Sections

### Service Status
Shows health status of all 10 services:
- Coordinator (API Gateway)
- MySQL Master & 3 Replicas
- 2 Timestamp Services
- Metrics Collector
- Cabinet Service (Quorum Selection)
- SEER Service (Leader Election)

### Replica Metrics
Real-time table showing:
- Latency (ms)
- Replication lag (timestamps behind)
- Uptime (seconds)
- Crash count
- Health status

### Query Execution
- **Execute Query**: Run any SQL query
- **Insert Sample Data**: Quick button to insert random user data
- **Get Quorum**: See which replicas Cabinet selects for writes
- **Elect Leader**: See which replica SEER would elect as new master

### Execution Flow
Step-by-step visualization showing:
1. Query parsing
2. Timestamp assignment (from timestamp service)
3. Query execution (on master or replica)
4. Quorum achievement (for writes)

### Danger Zone
Test failover functionality:
- **Stop Master**: Triggers automatic leader election
- **Start Master**: Restores original master

## API Endpoints Used

- `http://localhost:8000/query` - Execute SQL queries
- `http://localhost:8000/status` - Get system status
- `http://localhost:8003/metrics` - Get replica metrics
- `http://localhost:8004/select-quorum` - Get optimal quorum
- `http://localhost:8005/elect-leader` - Elect new leader

## Development

The dashboard auto-refreshes every 5 seconds to show latest metrics and service status.

All PrimeVue components use the Aura theme in light mode for a clean, modern interface.
