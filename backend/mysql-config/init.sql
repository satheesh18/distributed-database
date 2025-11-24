-- Initialize test database
USE testdb;

-- Create metadata table for tracking timestamps and replication
CREATE TABLE IF NOT EXISTS _metadata (
    id INT AUTO_INCREMENT PRIMARY KEY,
    last_applied_timestamp BIGINT DEFAULT 0,
    last_update TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- Insert initial metadata row
INSERT INTO _metadata (last_applied_timestamp) VALUES (0);

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
