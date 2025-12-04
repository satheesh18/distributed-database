-- Replica initialization - SCHEMA ONLY
-- Data will come from master via replication
-- This ensures no duplicate key conflicts

USE testdb;

-- Create replication user (needed if this replica becomes master)
CREATE USER IF NOT EXISTS 'replicator'@'%' IDENTIFIED BY 'replicator_password';
GRANT REPLICATION SLAVE ON *.* TO 'replicator'@'%';
GRANT SELECT ON testdb.* TO 'replicator'@'%';
FLUSH PRIVILEGES;

CREATE TABLE IF NOT EXISTS _metadata (
    id INT AUTO_INCREMENT PRIMARY KEY,
    last_applied_timestamp BIGINT DEFAULT 0,
    last_update TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_timestamp (last_applied_timestamp)
);

CREATE TABLE IF NOT EXISTS _table_timestamps (
    table_name VARCHAR(255) PRIMARY KEY,
    last_timestamp BIGINT DEFAULT 0,
    last_update TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_timestamp (last_timestamp)
);

CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    timestamp BIGINT,
    INDEX idx_timestamp (timestamp)
);

CREATE TABLE IF NOT EXISTS products (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    price DECIMAL(10, 2) NOT NULL,
    stock INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    timestamp BIGINT,
    INDEX idx_timestamp (timestamp)
);
