-- =============================================================
-- TICKETY DATABASE SCHEMA
-- Created for Aiven MySQL
-- This script creates all tables needed for web and mobile apps
-- =============================================================

-- Drop existing tables (optional, for fresh setup)
-- DROP TABLE IF EXISTS qr_codes;
-- DROP TABLE IF EXISTS tickets;
-- DROP TABLE IF EXISTS services;
-- DROP TABLE IF EXISTS resets;
-- DROP TABLE IF EXISTS users;

-- =============================================================
-- USERS TABLE
-- Stores user accounts with authentication and roles
-- =============================================================
CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(120) UNIQUE NOT NULL,
    password LONGBLOB NOT NULL,
    role VARCHAR(20) NOT NULL DEFAULT 'client',
    verified BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_username (username),
    INDEX idx_email (email),
    INDEX idx_role (role)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =============================================================
-- RESETS TABLE
-- Stores password reset tokens with expiration
-- =============================================================
CREATE TABLE IF NOT EXISTS resets (
    id INT AUTO_INCREMENT PRIMARY KEY,
    email VARCHAR(120) UNIQUE NOT NULL,
    code VARCHAR(6) NOT NULL,
    expire_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_email (email),
    INDEX idx_expire (expire_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =============================================================
-- SERVICES TABLE
-- Service points with QR codes for the mobile app
-- Each service represents a desk/counter that users can submit tickets to
-- =============================================================
CREATE TABLE IF NOT EXISTS services (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    description TEXT DEFAULT '',
    category VARCHAR(50) NOT NULL DEFAULT 'General',
    is_active BOOLEAN DEFAULT TRUE,
    service_token VARCHAR(36) UNIQUE NOT NULL,
    created_by INT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (created_by) REFERENCES users(id),
    INDEX idx_service_token (service_token),
    INDEX idx_is_active (is_active),
    INDEX idx_category (category),
    INDEX idx_created_by (created_by)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =============================================================
-- QR_CODES TABLE
-- Stores generated QR code images for each service
-- One QR code per service - scanned by mobile app
-- =============================================================
CREATE TABLE IF NOT EXISTS qr_codes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    service_id INT UNIQUE NOT NULL,
    encoded_url VARCHAR(500) NOT NULL,
    image_url LONGTEXT,
    generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (service_id) REFERENCES services(id) ON DELETE CASCADE,
    INDEX idx_service_id (service_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =============================================================
-- TICKETS TABLE
-- Support tickets created by users via web or mobile app
-- =============================================================
CREATE TABLE IF NOT EXISTS tickets (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    service_id INT,
    title VARCHAR(200) NOT NULL,
    description TEXT NOT NULL,
    notes TEXT DEFAULT '',
    priority VARCHAR(20) NOT NULL DEFAULT 'medium',
    service VARCHAR(100) NOT NULL,
    service_code VARCHAR(500) DEFAULT '',
    status VARCHAR(20) NOT NULL DEFAULT 'open',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (service_id) REFERENCES services(id),
    INDEX idx_user_id (user_id),
    INDEX idx_service_id (service_id),
    INDEX idx_status (status),
    INDEX idx_priority (priority),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =============================================================
-- SAMPLE DATA (Optional - for testing)
-- Uncomment to add test data
-- =============================================================
-- INSERT INTO users (username, email, password, role, verified) VALUES
-- ('admin', 'admin@tickety.app', '<hashed_password>', 'admin', TRUE),
-- ('testuser', 'test@example.com', '<hashed_password>', 'client', TRUE);
