-- Initialize test database for REPLICA instances
-- This file creates the schema but does NOT insert into _metadata
-- The _metadata row will be replicated from master
USE testdb;

-- Create replication user for binlog replication
-- This will be used by replicas to connect to master
CREATE USER IF NOT EXISTS 'replicator'@'%' IDENTIFIED BY 'replicator_password';
GRANT REPLICATION SLAVE ON *.* TO 'replicator'@'%';
GRANT SELECT ON testdb.* TO 'replicator'@'%';
FLUSH PRIVILEGES;

-- Create metadata table for tracking timestamps and replication
-- Note: We do NOT insert the initial row here - it will come from master via replication
CREATE TABLE IF NOT EXISTS _metadata (
    id INT AUTO_INCREMENT PRIMARY KEY,
    last_applied_timestamp BIGINT DEFAULT 0,
    last_update TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_timestamp (last_applied_timestamp)
);

-- Create sample users table for testing
CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    timestamp BIGINT,
    INDEX idx_timestamp (timestamp)
);

-- Create sample products table for testing
CREATE TABLE IF NOT EXISTS products (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    price DECIMAL(10, 2) NOT NULL,
    stock INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    timestamp BIGINT,
    INDEX idx_timestamp (timestamp)
);
