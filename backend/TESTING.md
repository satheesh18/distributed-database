# Stress Testing & Demo Guide

This guide shows how to properly showcase the distributed database system under realistic conditions.

## Quick Start

### 1. Reset the System

```bash
# Clear all data and reset timestamps
python3 setup.py
```

### 2. Run Stress Tests

```bash
# Run all scenarios
python3 stress_test.py --scenario all

# Or run individual scenarios:
python3 stress_test.py --scenario concurrent --writes 100
python3 stress_test.py --scenario lag
python3 stress_test.py --scenario failover
python3 stress_test.py --scenario performance
```

## Test Scenarios

### Scenario 1: Concurrent Write Traffic

**Purpose**: Stress test the system with high concurrent load

**What it tests**:
- Timestamp ordering under load
- Quorum-based replication at scale
- System throughput
- Consistency guarantees

**Example**:
```bash
python3 stress_test.py --scenario concurrent --writes 200
```

**Expected Output**:
```
✓ Completed 200 writes in 4.23s
✓ Throughput: 47.28 writes/sec
✓ Successful: 200/200
✓ All writes received unique, ordered timestamps
```

### Scenario 2: Replica Lag & Cabinet Adaptation

**Purpose**: Show how Cabinet adapts to replica performance

**What it demonstrates**:
- Real-time replica monitoring
- Dynamic quorum selection
- Adaptation to changing conditions

**Example**:
```bash
python3 stress_test.py --scenario lag
```

**What you'll see**:
- Replica metrics (latency, lag) updated in real-time
- Cabinet selecting different quorums based on performance
- System adapting to slow replicas

### Scenario 3: Master Failover

**Purpose**: Demonstrate automatic failover and SEER election

**What it tests**:
- Failure detection
- SEER-based leader election
- Seamless recovery

**Steps**:
1. Run the test: `python3 stress_test.py --scenario failover`
2. When prompted, open another terminal
3. Stop the master: `docker-compose stop mysql-replica-4`
4. Press Enter to continue
5. Watch automatic failover happen!

**What you'll see**:
- Write fails on old master
- SEER elects new leader based on score
- Write succeeds on new master
- System continues operating

### Scenario 4: Performance Analysis

**Purpose**: Benchmark system performance

**What it measures**:
- Write latency
- Throughput
- Replica health after load

**Example**:
```bash
python3 stress_test.py --scenario performance
```

## Manual Testing

### Test Concurrent Writes

```bash
# Terminal 1
for i in {1..10}; do
  curl -X POST http://localhost:8000/query \
    -H "Content-Type: application/json" \
    -d "{\"query\": \"INSERT INTO users (name, email) VALUES ('User$i', 'user$i@example.com')\"}" &
done
wait
```

### Monitor Metrics

```bash
# Watch metrics in real-time
watch -n 1 'curl -s http://localhost:8003/metrics | jq'
```

### Test Quorum Selection

```bash
# See which replicas Cabinet selects
curl -X POST http://localhost:8004/select-quorum \
  -H "Content-Type: application/json" \
  -d '{"operation": "write"}' | jq
```

### Test Leader Election

```bash
# See which replica SEER would elect
curl -X POST http://localhost:8005/elect-leader \
  -H "Content-Type: application/json" \
  -d '{}' | jq
```

## Simulating Specific Conditions

### Simulate Slow Replica

```bash
# Add network delay to a replica
docker-compose exec mysql-replica-1 tc qdisc add dev eth0 root netem delay 100ms

# Remove delay
docker-compose exec mysql-replica-1 tc qdisc del dev eth0 root
```

### Simulate Replica Crash

```bash
# Stop a replica
docker-compose stop mysql-replica-2

# Start it again
docker-compose start mysql-replica-2
```

### Simulate Master Failure

```bash
# Stop master (triggers failover)
docker-compose stop mysql-replica-4

# Restore original master
docker-compose start mysql-replica-4
```

## Expected Results

### Concurrent Writes
- ✅ All writes get unique, ordered timestamps
- ✅ Quorum achieved for all writes (2/2)
- ✅ All replicas updated (3/3)
- ✅ High throughput (40-60 writes/sec)

### Replica Lag
- ✅ Cabinet selects fastest replicas for quorum
- ✅ Slow replicas excluded from quorum
- ✅ System adapts in real-time

### Master Failover
- ✅ Failure detected automatically
- ✅ SEER elects best replica as new leader
- ✅ Writes continue without manual intervention
- ✅ System remains available

## Troubleshooting

### All writes failing

**Cause**: Master might be down or system needs reset

**Solution**:
```bash
# Check system status
curl http://localhost:8000/status

# If master is down, restart it
  docker-compose restart mysql-replica-4

# Or reset the system
python3 setup.py
```

### Duplicate key errors

**Cause**: Data from previous tests still exists

**Solution**:
```bash
# Clear all data
python3 setup.py
```

### Connection errors

**Cause**: Services not running

**Solution**:
```bash
# Restart all services
docker-compose restart

# Or rebuild if needed
docker-compose down
docker-compose up -d
```

## Demo Tips

1. **Start Clean**: Always run `python3 setup.py` before demos
2. **Show Metrics**: Keep the frontend open to visualize in real-time
3. **Explain as You Go**: Narrate what's happening during each scenario
4. **Compare**: Show performance with/without Cabinet
5. **Interactive**: Let audience trigger failover themselves

## Advanced Testing

### Custom Workload

Create your own test script:

```python
import asyncio
import aiohttp

async def custom_workload():
    async with aiohttp.ClientSession() as session:
        # Your custom test logic here
        for i in range(100):
            query = f'INSERT INTO products (name, price) VALUES ("Item{i}", {i})'
            async with session.post(
                "http://localhost:8000/query",
                json={"query": query}
            ) as response:
                result = await response.json()
                print(f"Write {i}: {result.get('message')}")

asyncio.run(custom_workload())
```

### Continuous Load

```bash
# Generate continuous load for 60 seconds
timeout 60 bash -c 'while true; do
  curl -X POST http://localhost:8000/query \
    -H "Content-Type: application/json" \
    -d "{\"query\": \"INSERT INTO users (name, email) VALUES ('LoadTest', 'load@test.com')\"}"
  sleep 0.1
done'
```
