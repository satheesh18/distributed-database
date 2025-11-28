#!/bin/bash
# Demote a master to replica after recovery
# Usage: ./demote-to-replica.sh <container_name> <new_master_host>

set -e

CONTAINER_NAME=${1:-mysql-instance-1}
NEW_MASTER_HOST=${2:-mysql-instance-2}

echo "Demoting $CONTAINER_NAME to replica of $NEW_MASTER_HOST..."

docker exec $CONTAINER_NAME mysql -u root -prootpass <<-EOSQL
    -- Enable read-only mode
    SET GLOBAL read_only = ON;
    SET GLOBAL super_read_only = ON;
    
    -- Stop any existing replication
    STOP SLAVE;
    RESET SLAVE ALL;
    
    -- Configure replication to new master
    CHANGE MASTER TO
        MASTER_HOST='$NEW_MASTER_HOST',
        MASTER_USER='replicator',
        MASTER_PASSWORD='replicator_password',
        MASTER_AUTO_POSITION=1,
        GET_MASTER_PUBLIC_KEY=1;
    
    -- Start replication
    START SLAVE;
EOSQL

echo "$CONTAINER_NAME demoted to replica successfully!"
echo "Checking replication status..."
docker exec $CONTAINER_NAME mysql -u root -prootpass -e "SHOW SLAVE STATUS\G"
