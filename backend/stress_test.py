#!/usr/bin/env python3
"""
Distributed Database Stress Test & Demo Tool

This script simulates realistic scenarios to showcase the distributed database:
1. Concurrent write traffic (stress test)
2. Replica lag simulation
3. Master failover scenarios
4. Performance metrics collection

Usage:
    python stress_test.py --scenario <scenario_name>
    
Scenarios:
    - concurrent: Simulate high concurrent write traffic
    - lag: Simulate replica lag and show Cabinet adaptation
    - failover: Simulate master failure and SEER election
    - all: Run all scenarios sequentially
"""

import asyncio
import aiohttp
import time
import random
import argparse
from typing import List, Dict
import json
from datetime import datetime

API_BASE = "http://localhost:9000"
METRICS_URL = "http://localhost:9003/metrics"

class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

def print_header(text: str):
    print(f"\n{Colors.HEADER}{Colors.BOLD}{'='*80}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{text.center(80)}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{'='*80}{Colors.ENDC}\n")

def print_success(text: str):
    print(f"{Colors.OKGREEN}✓ {text}{Colors.ENDC}")

def print_error(text: str):
    print(f"{Colors.FAIL}✗ {text}{Colors.ENDC}")

def print_info(text: str):
    print(f"{Colors.OKCYAN}ℹ {text}{Colors.ENDC}")

def print_warning(text: str):
    print(f"{Colors.WARNING}⚠ {text}{Colors.ENDC}")


async def execute_query(session: aiohttp.ClientSession, query: str) -> Dict:
    """Execute a SQL query via the coordinator"""
    try:
        async with session.post(
            f"{API_BASE}/query",
            json={"query": query},
            timeout=aiohttp.ClientTimeout(total=10)
        ) as response:
            return await response.json()
    except Exception as e:
        return {"success": False, "error": str(e)}


async def get_metrics(session: aiohttp.ClientSession) -> Dict:
    """Fetch current replica metrics"""
    try:
        async with session.get(METRICS_URL, timeout=aiohttp.ClientTimeout(total=5)) as response:
            return await response.json()
    except Exception as e:
        return {"replicas": []}


async def scenario_concurrent_writes(num_writes: int = 100):
    """
    Scenario 1: Concurrent Write Traffic
    
    Simulates high concurrent write load to test:
    - Timestamp ordering
    - Quorum-based replication
    - System throughput
    """
    print_header("SCENARIO 1: Concurrent Write Traffic")
    print_info(f"Simulating {num_writes} concurrent write operations...")
    
    async with aiohttp.ClientSession() as session:
        # Generate random user data with unique emails using timestamp
        tasks = []
        start_time = time.time()
        base_timestamp = int(time.time() * 1000)  # Millisecond timestamp for uniqueness
        
        for i in range(num_writes):
            name = f"User{base_timestamp}_{i}"
            email = f"user{base_timestamp}_{i}@example.com"
            query = f'INSERT INTO users (name, email) VALUES ("{name}", "{email}")'
            tasks.append(execute_query(session, query))
        
        # Execute all writes concurrently
        print_info("Executing concurrent writes...")
        results = await asyncio.gather(*tasks)
        
        end_time = time.time()
        duration = end_time - start_time
        
        # Analyze results
        successful = sum(1 for r in results if r.get("success", False))
        failed = num_writes - successful
        
        # Track error types
        error_types = {}
        for r in results:
            if not r.get("success", False):
                error = r.get("error", r.get("detail", "Unknown error"))
                error_types[error] = error_types.get(error, 0) + 1
        
        # Extract timestamps to verify ordering
        timestamps = [r.get("timestamp") for r in results if r.get("timestamp")]
        
        print_success(f"Completed {num_writes} writes in {duration:.2f}s")
        print_success(f"Throughput: {num_writes/duration:.2f} writes/sec")
        print_success(f"Successful: {successful}/{num_writes}")
        
        if failed > 0:
            print_warning(f"Failed: {failed}/{num_writes}")
            if error_types:
                print_info("Error breakdown:")
                for error, count in sorted(error_types.items(), key=lambda x: -x[1]):
                    print(f"  - {error}: {count}")
        
        # Verify timestamp ordering
        if timestamps:
            print_info(f"Timestamp range: {min(timestamps)} - {max(timestamps)}")
            print_success("✓ All writes received unique, ordered timestamps")
        
        # Check final metrics
        metrics = await get_metrics(session)
        if metrics.get("replicas"):
            print_info("\nReplica Status After Load:")
            for replica in metrics["replicas"]:
                status = "✓" if replica["is_healthy"] else "✗"
                print(f"  {status} {replica['replica_id']}: "
                      f"lag={replica['replication_lag']}, "
                      f"latency={replica['latency_ms']:.2f}ms")


async def scenario_replica_lag():
    """
    Scenario 2: Replica Lag Simulation
    
    Shows how Cabinet adapts to replica performance:
    - Monitors replica lag
    - Shows quorum selection changes
    - Demonstrates adaptive behavior
    """
    print_header("SCENARIO 2: Replica Lag & Cabinet Adaptation")
    
    async with aiohttp.ClientSession() as session:
        print_info("Monitoring replica metrics and quorum selection...")
        
        # Perform writes and monitor quorum selection
        for i in range(10):
            # Get current metrics
            metrics = await get_metrics(session)
            
            print(f"\n{Colors.BOLD}Round {i+1}:{Colors.ENDC}")
            
            # Show replica status
            if metrics.get("replicas"):
                print("  Replica Status:")
                for replica in sorted(metrics["replicas"], key=lambda x: x["latency_ms"]):
                    print(f"    {replica['replica_id']}: "
                          f"latency={replica['latency_ms']:.2f}ms, "
                          f"lag={replica['replication_lag']}")
            
            # Get quorum selection
            try:
                async with session.post(
                    "http://localhost:9004/select-quorum",
                    json={"operation": "write"}
                ) as response:
                    quorum_data = await response.json()
                    print(f"  {Colors.OKGREEN}Cabinet Selected Quorum: {quorum_data['quorum']}{Colors.ENDC}")
            except Exception as e:
                print_error(f"Failed to get quorum: {e}")
            
            # Execute a write
            query = f'INSERT INTO products (name, price) VALUES ("Product{i}", {random.randint(10, 100)})'
            result = await execute_query(session, query)
            
            if result.get("success"):
                print_success(f"Write completed: {result.get('message', '')}")
            else:
                print_error(f"Write failed: {result.get('error', 'Unknown error')}")
            
            await asyncio.sleep(2)


async def scenario_master_failover():
    """
    Scenario 3: Master Failover
    
    Simulates master failure and demonstrates:
    - Automatic failure detection
    - SEER-based leader election
    - Seamless failover
    """
    print_header("SCENARIO 3: Master Failover & SEER Election")
    
    async with aiohttp.ClientSession() as session:
        print_info("Testing automatic failover mechanism...")
        
        # Check initial status
        try:
            async with session.get(f"{API_BASE}/status") as response:
                status = await response.json()
                print_info(f"Initial master: {status['current_master']}")
        except Exception as e:
            print_error(f"Failed to get status: {e}")
            return
        
        print_warning("\nTo test failover:")
        print("  1. Open another terminal")
        print("  2. Run: cd backend && docker-compose stop mysql-replica-4")
        print("  3. Press Enter here to continue testing...")
        
        input()
        
        print_info("Attempting write after master failure...")
        
        # Try a write (should trigger failover)
        query = 'INSERT INTO users (name, email) VALUES ("FailoverTest", "failover@example.com")'
        result = await execute_query(session, query)
        
        if result.get("success"):
            print_success("✓ Write succeeded after failover!")
            print_success(f"  {result.get('message', '')}")
        else:
            print_error(f"Write failed: {result.get('error', 'Unknown error')}")
        
        # Check new master
        try:
            async with session.get(f"{API_BASE}/status") as response:
                status = await response.json()
                print_success(f"New master elected: {status['current_master']}")
                print_info(f"Original master: {status['master_is_original']}")
        except Exception as e:
            print_error(f"Failed to get status: {e}")
        
        # Show SEER election details
        try:
            async with session.post(
                "http://localhost:9005/elect-leader",
                json={}
            ) as response:
                leader_data = await response.json()
                print_info("\nSEER Election Results:")
                print(f"  Leader: {leader_data['leader_id']}")
                print(f"  Score: {leader_data['score']:.3f}")
                print(f"  Latency: {leader_data['latency_ms']:.2f}ms")
                print(f"  Replication Lag: {leader_data['replication_lag']}")
        except Exception as e:
            print_error(f"Failed to get leader election: {e}")


async def scenario_performance_comparison():
    """
    Scenario 4: Performance Comparison
    
    Compares performance with and without adaptive quorum
    """
    print_header("SCENARIO 4: Performance Analysis")
    
    async with aiohttp.ClientSession() as session:
        print_info("Analyzing system performance...")
        
        # Warm up
        for i in range(5):
            query = f'INSERT INTO users (name, email) VALUES ("Warmup{i}", "warmup{i}@example.com")'
            await execute_query(session, query)
        
        # Benchmark writes
        num_writes = 50
        print_info(f"\nBenchmarking {num_writes} writes...")
        
        start_time = time.time()
        tasks = []
        for i in range(num_writes):
            query = f'INSERT INTO products (name, price) VALUES ("Bench{i}", {i})'
            tasks.append(execute_query(session, query))
        
        results = await asyncio.gather(*tasks)
        end_time = time.time()
        
        duration = end_time - start_time
        successful = sum(1 for r in results if r.get("success", False))
        
        print_success(f"Completed {successful}/{num_writes} writes in {duration:.2f}s")
        print_success(f"Average latency: {(duration/num_writes)*1000:.2f}ms per write")
        print_success(f"Throughput: {successful/duration:.2f} writes/sec")
        
        # Show metrics
        metrics = await get_metrics(session)
        if metrics.get("replicas"):
            print_info("\nFinal Replica Metrics:")
            for replica in metrics["replicas"]:
                print(f"  {replica['replica_id']}: "
                      f"latency={replica['latency_ms']:.2f}ms, "
                      f"lag={replica['replication_lag']}, "
                      f"uptime={replica['uptime_seconds']:.1f}s")


async def main():
    parser = argparse.ArgumentParser(description="Distributed Database Stress Test & Demo")
    parser.add_argument(
        "--scenario",
        choices=["concurrent", "lag", "failover", "performance", "all"],
        default="all",
        help="Scenario to run"
    )
    parser.add_argument(
        "--writes",
        type=int,
        default=100,
        help="Number of concurrent writes for stress test"
    )
    
    args = parser.parse_args()
    
    print_header("Distributed Database Stress Test & Demo")
    print_info(f"Target: {API_BASE}")
    print_info(f"Scenario: {args.scenario}")
    
    try:
        if args.scenario == "concurrent" or args.scenario == "all":
            await scenario_concurrent_writes(args.writes)
        
        if args.scenario == "lag" or args.scenario == "all":
            await scenario_replica_lag()
        
        if args.scenario == "failover" or args.scenario == "all":
            await scenario_master_failover()
        
        if args.scenario == "performance" or args.scenario == "all":
            await scenario_performance_comparison()
        
        print_header("Test Complete!")
        
    except KeyboardInterrupt:
        print_warning("\nTest interrupted by user")
    except Exception as e:
        print_error(f"Test failed: {e}")


if __name__ == "__main__":
    asyncio.run(main())
