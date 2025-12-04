# Distributed Database Dashboard

A Vue.js frontend dashboard to visualize and interact with the distributed database system.

## Features

- **Service Status Monitoring**: Real-time health checks for all 10 services
- **Cluster Topology**: Visual master-replica layout with live metrics
- **Failover Testing**: Stop master and trigger SEER-based leader election
- **Stress Testing**: Run concurrent operations with configurable consistency levels

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

### Cluster Topology
Visual display of master and replicas with real-time metrics:
- Latency (ms) - network round-trip time
- Replication lag (transactions behind master)
- Uptime (time since last restart)
- Health status

### Failover Testing
Test automatic leader election:
- **Stop Master and Failover**: Stops current master, triggers SEER election, promotes best replica
- Shows step-by-step progress of failover process
- Old master automatically restarts as replica

### Stress Testing
Run concurrent database operations:
- Configure number of operations (10, 25, 50, 100)
- Choose consistency level:
  - **EVENTUAL**: Fast writes, master only
  - **STRONG**: Wait for Cabinet-selected replica quorum
- Live progress with success/failure counts and latency metrics

## API Endpoints Used

- `http://localhost:9000/status` - Get system status
- `http://localhost:9000/admin/stop-master-only` - Stop master container
- `http://localhost:9000/admin/promote-leader` - Promote replica to master
- `http://localhost:9000/admin/start-instance` - Start/restart instance
- `http://localhost:9000/admin/stress-test/*` - Stress test endpoints
- `http://localhost:9003/metrics` - Get replica metrics
- `http://localhost:9005/elect-leader` - Trigger SEER election

## Development

The dashboard auto-refreshes every 5 seconds to show latest metrics and service status.

All PrimeVue components use the Aura theme in light mode for a clean, modern interface.
