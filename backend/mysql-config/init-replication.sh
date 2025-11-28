#!/bin/bash
# Initialize replication on replica instance
# This script runs when the replica container starts

set -e

echo "Waiting for master to be ready..."
until mysql -h mysql-instance-1 -u root -prootpass -e "SELECT 1" &> /dev/null; do
    echo "Master not ready yet, waiting..."
    sleep 2
done

echo "Master is ready. Configuring replication..."

# Get master binlog position
MASTER_STATUS=$(mysql -h mysql-instance-1 -u root -prootpass -e "SHOW MASTER STATUS\G")
echo "Master status: $MASTER_STATUS"

# Configure replication using GTID (simpler than binlog position)
mysql -u root -prootpass <<-EOSQL
    STOP SLAVE;
    CHANGE MASTER TO
        MASTER_HOST='mysql-instance-1',
        MASTER_USER='replicator',
        MASTER_PASSWORD='replicator_password',
        MASTER_AUTO_POSITION=1,
        GET_MASTER_PUBLIC_KEY=1;
    START SLAVE;
    SET GLOBAL read_only=ON;
    SET GLOBAL super_read_only=ON;
EOSQL

echo "Replication configured. Checking status..."
mysql -u root -prootpass -e "SHOW SLAVE STATUS\G"

echo "Replication setup complete!"
