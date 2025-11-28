# Binlog-Based Replication - Quick Start Guide

## Starting the System

```bash
cd /Users/satheesh/fall25/cs249/final_project/backend

# Stop any existing containers
docker-compose down

# Start the new binlog-based system
docker-compose up -d

# Wait for services to be ready (30 seconds)
sleep 30

# Verify replication is running
docker exec mysql-instance-2 mysql -uroot -prootpass -e "SHOW SLAVE STATUS\G" | grep -E "Slave_IO_Running|Slave_SQL_Running|Seconds_Behind_Master"
```

Expected output:
```
Slave_IO_Running: Yes
Slave_SQL_Running: Yes
Seconds_Behind_Master: 0
```

## Testing Binlog Replication

### 1. Insert Data on Master
```bash
docker exec mysql-instance-1 mysql -uroot -prootpass testdb -e \
  "INSERT INTO users (name, email, timestamp) VALUES ('Alice', 'alice@example.com', 1000)"
```

### 2. Verify on Replica
```bash
docker exec mysql-instance-2 mysql -uroot -prootpass testdb -e \
  "SELECT * FROM users WHERE email='alice@example.com'"
```

### 3. Check Timestamp Table
```bash
# Master
docker exec mysql-instance-1 mysql -uroot -prootpass testdb -e "SELECT * FROM _metadata"

# Replica
docker exec mysql-instance-2 mysql -uroot -prootpass testdb -e "SELECT * FROM _metadata"
```

## Testing via API

### QUORUM Write (with verification)
```bash
curl -X POST http://localhost:9000/query \
  -H "Content-Type: application/json" \
  -d '{
    "query": "INSERT INTO users (name, email) VALUES (\"Bob\", \"bob@example.com\")",
    "consistency": "QUORUM"
  }'
```

Expected response:
```json
{
  "success": true,
  "quorum_achieved": true,
  "replica_caught_up": true,
  "timestamp": 1234,
  "message": "Write successful (consistency: QUORUM, timestamp: 1234, quorum achieved)"
}
```

### ONE Write (eventual consistency)
```bash
curl -X POST http://localhost:9000/query \
  -H "Content-Type: application/json" \
  -d '{
    "query": "INSERT INTO users (name, email) VALUES (\"Charlie\", \"charlie@example.com\")",
    "consistency": "ONE"
  }'
```

## Testing Failover

### 1. Trigger Failover
```bash
curl -X POST http://localhost:9000/admin/stop-master
```

Expected response:
```json
{
  "success": true,
  "message": "Failover complete. New master: instance-2",
  "old_master": "instance-1",
  "new_master": "instance-2"
}
```

### 2. Verify New Master
```bash
curl http://localhost:9000/status
```

Expected:
```json
{
  "current_master": {
    "id": "instance-2",
    "host": "mysql-instance-2",
    "container": "mysql-instance-2"
  },
  "current_replica": {
    "id": "instance-1",
    "host": "mysql-instance-1",
    "container": "mysql-instance-1"
  },
  "replication_mode": "binlog"
}
```

### 3. Test Write on New Master
```bash
curl -X POST http://localhost:9000/query \
  -H "Content-Type: application/json" \
  -d '{
    "query": "INSERT INTO users (name, email) VALUES (\"After Failover\", \"failover@example.com\")",
    "consistency": "ONE"
  }'
```

### 4. Restart Old Master as Replica
```bash
curl -X POST http://localhost:9000/admin/restart-old-master
```

### 5. Verify Binlog Replication Rewired
```bash
# Check that mysql-instance-1 is now replicating from mysql-instance-2
docker exec mysql-instance-1 mysql -uroot -prootpass -e "SHOW SLAVE STATUS\G" | grep Master_Host
```

Expected: `Master_Host: mysql-instance-2`

## Frontend Dashboard

Open http://localhost:5173 (or your frontend port)

You should see:
- **2 MySQL Instances**: mysql-instance-1 and mysql-instance-2
- **Replication Mode**: binlog (MySQL Native)
- **Failover Button**: "Stop Master (Trigger Failover)"
- **Recovery Button**: "Restart Old Master as Replica"

## Monitoring

### Check Metrics
```bash
curl http://localhost:9003/metrics
```

### Check Consistency Metrics
```bash
curl http://localhost:9000/consistency-metrics
```

### Check Binlog Position
```bash
# Master binlog position
docker exec mysql-instance-1 mysql -uroot -prootpass -e "SHOW MASTER STATUS\G"

# Replica binlog position
docker exec mysql-instance-2 mysql -uroot -prootpass -e "SHOW SLAVE STATUS\G"
```

## Troubleshooting

### Replication Not Running
```bash
# Check replica status
docker exec mysql-instance-2 mysql -uroot -prootpass -e "SHOW SLAVE STATUS\G"

# If Slave_IO_Running or Slave_SQL_Running is "No", restart replication
docker exec mysql-instance-2 mysql -uroot -prootpass -e "STOP SLAVE; START SLAVE;"
```

### Reset Everything
```bash
cd /Users/satheesh/fall25/cs249/final_project/backend
docker-compose down -v  # Remove volumes
docker-compose up -d
sleep 30
```

## Key Differences from Old System

1. **No Manual Replication**: Coordinator only writes to master, binlog handles propagation
2. **Eventual Quorum**: Writes succeed on master even if replica lags (but we verify)
3. **No Revert Logic**: MySQL binlog guarantees eventual consistency
4. **2 Instances**: Down from 4 (mysql-instance-1 and mysql-instance-2)
5. **Binlog Rewiring**: Failover automatically reconfigures replication direction
