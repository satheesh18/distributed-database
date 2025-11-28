#!/bin/bash
# Promote a replica to master during failover
# Usage: ./promote-to-master.sh <container_name>

set -e

CONTAINER_NAME=${1:-mysql-instance-2}

echo "Promoting $CONTAINER_NAME to master..."

docker exec $CONTAINER_NAME mysql -u root -prootpass <<-EOSQL
    -- Stop replication
    STOP SLAVE;
    
    -- Reset slave configuration
    RESET SLAVE ALL;
    
    -- Disable read-only mode
    SET GLOBAL read_only = OFF;
    SET GLOBAL super_read_only = OFF;
    
    -- Reset master to start fresh binlog
    RESET MASTER;
EOSQL

echo "$CONTAINER_NAME promoted to master successfully!"
echo "Checking new master status..."
docker exec $CONTAINER_NAME mysql -u root -prootpass -e "SHOW MASTER STATUS\G"
