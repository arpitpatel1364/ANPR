-- ANPR System MySQL Database Schema
-- For use with XAMPP MySQL/MariaDB

-- Create database (run this manually if needed)
-- CREATE DATABASE IF NOT EXISTS anpr_system CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
-- USE anpr_system;

-- Table: detections
-- Stores all license plate detections
CREATE TABLE IF NOT EXISTS detections (
    id INT AUTO_INCREMENT PRIMARY KEY,
    timestamp DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    license_plate VARCHAR(20) NOT NULL,
    verification_status ENUM('VERIFIED', 'NOT_VERIFIED') NOT NULL,
    access_granted ENUM('YES', 'NO') NOT NULL,
    detection_confidence DECIMAL(5,3) NOT NULL DEFAULT 0.000,
    processing_time_ms DECIMAL(10,2) NOT NULL DEFAULT 0.00,
    camera_source VARCHAR(255) NOT NULL,
    detection_count INT NOT NULL DEFAULT 1,
    log_reason VARCHAR(255) DEFAULT NULL,
    image_full_annotated VARCHAR(500) DEFAULT NULL,
    bbox_x1 INT DEFAULT NULL,
    bbox_y1 INT DEFAULT NULL,
    bbox_x2 INT DEFAULT NULL,
    bbox_y2 INT DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_license_plate (license_plate),
    INDEX idx_timestamp (timestamp),
    INDEX idx_verification_status (verification_status),
    INDEX idx_camera_source (camera_source),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Table: allowed_plates
-- Stores list of authorized license plates
CREATE TABLE IF NOT EXISTS allowed_plates (
    id INT AUTO_INCREMENT PRIMARY KEY,
    license_plate VARCHAR(20) NOT NULL UNIQUE,
    description VARCHAR(255) DEFAULT NULL,
    added_by VARCHAR(100) DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_license_plate (license_plate)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Table: users
-- Stores admin panel users (if needed for authentication)
CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(100) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    email VARCHAR(255) DEFAULT NULL,
    role ENUM('admin', 'viewer', 'superadmin') DEFAULT 'viewer',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_username (username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Table: cameras
-- Stores camera configuration (optional, can still use JSON)
CREATE TABLE IF NOT EXISTS cameras (
    id INT AUTO_INCREMENT PRIMARY KEY,
    camera_id VARCHAR(50) NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    location VARCHAR(255) DEFAULT NULL,
    rtsp_source VARCHAR(500) NOT NULL,
    enabled BOOLEAN DEFAULT TRUE,
    dedup_window INT DEFAULT 30,
    confidence_threshold DECIMAL(3,2) DEFAULT 0.80,
    api_enabled BOOLEAN DEFAULT FALSE,
    api_settings TEXT DEFAULT NULL,
    roi_polygon TEXT DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_camera_id (camera_id),
    INDEX idx_enabled (enabled)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Table: system_settings
-- Stores application configuration dynamically
CREATE TABLE IF NOT EXISTS system_settings (
    id INT AUTO_INCREMENT PRIMARY KEY,
    setting_key VARCHAR(100) NOT NULL UNIQUE,
    setting_value TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


