#!/usr/bin/env python3
"""
Setup and Reset Script for Distributed Database

Clears all data and prepares the system for testing.
"""

import requests
import time

API_BASE = "http://localhost:9000"

def clear_data():
    """Clear all data from tables"""
    print("🧹 Clearing existing data...")
    
    queries = [
        "DELETE FROM users",
        "DELETE FROM products",
        "UPDATE _metadata SET last_applied_timestamp = 0 WHERE id = 1"
    ]
    
    for query in queries:
        try:
            response = requests.post(
                f"{API_BASE}/query",
                json={"query": query},
                timeout=10
            )
            result = response.json()
            if result.get("success"):
                print(f"  ✓ {query}")
            else:
                print(f"  ✗ Failed: {query}")
        except Exception as e:
            print(f"  ✗ Error: {e}")
    
    print("✅ Data cleared!\n")


def verify_system():
    """Verify system is ready"""
    print("🔍 Verifying system status...")
    
    try:
        # Check coordinator
        response = requests.get(f"{API_BASE}/health", timeout=5)
        if response.ok:
            print("  ✓ Coordinator is healthy")
        
        # Check status
        response = requests.get(f"{API_BASE}/status", timeout=5)
        status = response.json()
        print(f"  ✓ Master: {status['current_master']}")
        print(f"  ✓ Replicas: {', '.join(status['replicas'])}")
        
        # Check metrics
        response = requests.get("http://localhost:9003/metrics", timeout=5)
        metrics = response.json()
        print(f"  ✓ Tracking {len(metrics['replicas'])} replicas")
        
        print("✅ System is ready!\n")
        return True
        
    except Exception as e:
        print(f"  ✗ System check failed: {e}")
        return False


def main():
    print("=" * 60)
    print("  Distributed Database - Setup & Reset")
    print("=" * 60)
    print()
    
    if not verify_system():
        print("\n⚠️  System not ready. Please start the backend:")
        print("    cd backend && docker-compose up -d")
        return
    
    clear_data()
    
    print("🎯 System is ready for testing!")
    print("\nRun stress tests with:")
    print("  python stress_test.py --scenario all")
    print("  python stress_test.py --scenario concurrent --writes 200")
    print("  python stress_test.py --scenario lag")
    print("  python stress_test.py --scenario failover")


if __name__ == "__main__":
    main()
