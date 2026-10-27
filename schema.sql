-- ====================================================================
-- WATER SUPPLY MONITORING AND CONSUMER BILLING SYSTEM
-- Database Management System (DBMS) Project Schema
-- RDBMS: Standard SQL / SQLite / PostgreSQL / MySQL Compatible
-- ====================================================================

-- 1. USERS TABLE (Authentication & Role Management)
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY AUTOINCREMENT,
    username VARCHAR(50) UNIQUE NOT NULL,
    password VARCHAR(255) NOT NULL,
    role VARCHAR(20) NOT NULL CHECK(role IN ('admin', 'consumer')),
    full_name VARCHAR(100) NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    phone VARCHAR(20),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. SUPPLY ZONES TABLE (Water Grid & Reservoir Monitoring)
CREATE TABLE IF NOT EXISTS supply_zones (
    zone_id INTEGER PRIMARY KEY AUTOINCREMENT,
    zone_name VARCHAR(100) UNIQUE NOT NULL,
    ward_area VARCHAR(100) NOT NULL,
    reservoir_name VARCHAR(100) NOT NULL,
    reservoir_level_pct DECIMAL(5,2) DEFAULT 75.0,  -- Water storage percentage
    water_pressure_psi DECIMAL(5,2) DEFAULT 45.0,   -- Pipeline pressure
    purity_ph DECIMAL(3,1) DEFAULT 7.2,             -- Water quality pH
    tds_ppm INTEGER DEFAULT 180,                    -- Total Dissolved Solids (ppm)
    supply_status VARCHAR(20) DEFAULT 'ACTIVE' CHECK(supply_status IN ('ACTIVE', 'SCHEDULED', 'MAINTENANCE', 'OUTAGE')),
    morning_slot VARCHAR(50) DEFAULT '06:00 AM - 09:00 AM',
    evening_slot VARCHAR(50) DEFAULT '06:00 PM - 08:30 PM',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 3. CONSUMERS TABLE (Connection & Meter Profiles)
CREATE TABLE IF NOT EXISTS consumers (
    consumer_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER UNIQUE NOT NULL,
    account_number VARCHAR(30) UNIQUE NOT NULL,
    zone_id INTEGER NOT NULL,
    connection_type VARCHAR(20) DEFAULT 'Residential' CHECK(connection_type IN ('Residential', 'Commercial', 'Industrial')),
    meter_number VARCHAR(50) UNIQUE NOT NULL,
    installation_date DATE,
    address TEXT NOT NULL,
    last_meter_reading DECIMAL(10,2) DEFAULT 0.0,
    status VARCHAR(20) DEFAULT 'Active' CHECK(status IN ('Active', 'Suspended', 'Disconnected')),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (zone_id) REFERENCES supply_zones(zone_id) ON DELETE RESTRICT
);

-- 4. BILLS TABLE (Water Billing & Slabs)
CREATE TABLE IF NOT EXISTS bills (
    bill_id INTEGER PRIMARY KEY AUTOINCREMENT,
    bill_number VARCHAR(30) UNIQUE NOT NULL,
    consumer_id INTEGER NOT NULL,
    billing_month VARCHAR(30) NOT NULL,   -- e.g. "October 2026"
    billing_date DATE NOT NULL,
    due_date DATE NOT NULL,
    prev_reading DECIMAL(10,2) NOT NULL,
    curr_reading DECIMAL(10,2) NOT NULL,
    units_consumed DECIMAL(10,2) NOT NULL, -- Kiloliters (kL)
    base_charge DECIMAL(10,2) NOT NULL,   -- Fixed meter connection fee
    consumption_charge DECIMAL(10,2) NOT NULL,
    tax_surcharge DECIMAL(10,2) NOT NULL, -- Environmental / Sewerage levy
    total_amount DECIMAL(10,2) NOT NULL,
    status VARCHAR(20) DEFAULT 'UNPAID' CHECK(status IN ('UNPAID', 'PAID', 'OVERDUE')),
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (consumer_id) REFERENCES consumers(consumer_id) ON DELETE CASCADE
);

-- 5. PAYMENTS TABLE (Transaction Auditing & Receipts)
CREATE TABLE IF NOT EXISTS payments (
    payment_id INTEGER PRIMARY KEY AUTOINCREMENT,
    bill_id INTEGER NOT NULL,
    consumer_id INTEGER NOT NULL,
    receipt_number VARCHAR(40) UNIQUE NOT NULL,
    transaction_ref VARCHAR(60) UNIQUE NOT NULL,
    amount_paid DECIMAL(10,2) NOT NULL,
    payment_method VARCHAR(30) NOT NULL CHECK(payment_method IN ('UPI', 'Credit/Debit Card', 'Net Banking', 'Cash', 'Counter')),
    payment_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (bill_id) REFERENCES bills(bill_id) ON DELETE CASCADE,
    FOREIGN KEY (consumer_id) REFERENCES consumers(consumer_id) ON DELETE CASCADE
);

-- 6. SUPPLY ALERTS TABLE (Outage Notices & Grid Announcements)
CREATE TABLE IF NOT EXISTS supply_alerts (
    alert_id INTEGER PRIMARY KEY AUTOINCREMENT,
    zone_id INTEGER, -- NULL implies all zones (City-wide announcement)
    title VARCHAR(150) NOT NULL,
    message TEXT NOT NULL,
    severity VARCHAR(20) DEFAULT 'Warning' CHECK(severity IN ('Info', 'Warning', 'Emergency')),
    is_active BOOLEAN DEFAULT 1,
    posted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (zone_id) REFERENCES supply_zones(zone_id) ON DELETE SET NULL
);

-- 7. COMPLAINTS & GRIEVANCES TABLE
CREATE TABLE IF NOT EXISTS complaints (
    complaint_id INTEGER PRIMARY KEY AUTOINCREMENT,
    consumer_id INTEGER NOT NULL,
    category VARCHAR(50) NOT NULL CHECK(category IN ('Low Pressure', 'No Water', 'Contaminated / Murky Water', 'Pipeline Leakage', 'Billing Discrepancy', 'Meter Fault')),
    description TEXT NOT NULL,
    status VARCHAR(20) DEFAULT 'Pending' CHECK(status IN ('Pending', 'In Progress', 'Resolved')),
    admin_response TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMP,
    FOREIGN KEY (consumer_id) REFERENCES consumers(consumer_id) ON DELETE CASCADE
);

-- ====================================================================
-- DBMS VIEWS (Virtual Tables for Optimized Reporting)
-- ====================================================================

-- View 1: Complete Bill Details with Consumer & Zone Info
CREATE VIEW IF NOT EXISTS vw_bills_detailed AS
SELECT 
    b.bill_id,
    b.bill_number,
    b.billing_month,
    b.billing_date,
    b.due_date,
    b.prev_reading,
    b.curr_reading,
    b.units_consumed,
    b.base_charge,
    b.consumption_charge,
    b.tax_surcharge,
    b.total_amount,
    b.status AS bill_status,
    c.consumer_id,
    c.account_number,
    c.meter_number,
    c.connection_type,
    c.address,
    u.full_name AS consumer_name,
    u.email,
    u.phone,
    z.zone_id,
    z.zone_name,
    z.ward_area
FROM bills b
JOIN consumers c ON b.consumer_id = c.consumer_id
JOIN users u ON c.user_id = u.user_id
JOIN supply_zones z ON c.zone_id = z.zone_id;

-- View 2: Consumer Financial Summary (Outstanding Balance)
CREATE VIEW IF NOT EXISTS vw_consumer_balances AS
SELECT 
    c.consumer_id,
    c.account_number,
    u.full_name,
    COUNT(b.bill_id) AS total_bills,
    COALESCE(SUM(CASE WHEN b.status = 'UNPAID' OR b.status = 'OVERDUE' THEN b.total_amount ELSE 0 END), 0) AS total_pending_amount,
    COALESCE(SUM(CASE WHEN b.status = 'PAID' THEN b.total_amount ELSE 0 END), 0) AS total_paid_amount
FROM consumers c
JOIN users u ON c.user_id = u.user_id
LEFT JOIN bills b ON c.consumer_id = b.consumer_id
GROUP BY c.consumer_id, c.account_number, u.full_name;

-- View 3: Zone Water Supply & Monitoring Summary
CREATE VIEW IF NOT EXISTS vw_zone_monitoring AS
SELECT 
    z.zone_id,
    z.zone_name,
    z.ward_area,
    z.reservoir_name,
    z.reservoir_level_pct,
    z.water_pressure_psi,
    z.purity_ph,
    z.supply_status,
    z.morning_slot,
    z.evening_slot,
    COUNT(c.consumer_id) AS total_connected_consumers
FROM supply_zones z
LEFT JOIN consumers c ON z.zone_id = c.zone_id
GROUP BY z.zone_id;

-- ====================================================================
-- DBMS TRIGGERS (Automated Business Logic at Database Level)
-- ====================================================================

-- Trigger 1: Automatically update consumer's last meter reading when new bill is added
CREATE TRIGGER IF NOT EXISTS trg_update_consumer_meter_reading
AFTER INSERT ON bills
BEGIN
    UPDATE consumers
    SET last_meter_reading = NEW.curr_reading
    WHERE consumer_id = NEW.consumer_id;
END;

-- Trigger 2: Automatically mark bill as PAID when a payment is inserted
CREATE TRIGGER IF NOT EXISTS trg_mark_bill_paid
AFTER INSERT ON payments
BEGIN
    UPDATE bills
    SET status = 'PAID'
    WHERE bill_id = NEW.bill_id;
END;
