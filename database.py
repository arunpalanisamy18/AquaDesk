import sqlite3
import os
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

DB_NAME = "water_supply_dbms.db"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, DB_NAME)

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    schema_path = os.path.join(BASE_DIR, "schema.sql")
    with open(schema_path, "r", encoding="utf-8") as f:
        schema_sql = f.read()
    conn = get_db()
    conn.executescript(schema_sql)
    conn.commit()
    conn.close()

# ----------------- TARIFF CALCULATION ENGINE -----------------
def calculate_water_tariff(connection_type, units_consumed):
    """
    Computes bill breakdown based on progressive slab tariffs and connection type.
    units_consumed in Kiloliters (kL).
    """
    units = max(0.0, float(units_consumed))
    ctype = connection_type or "Residential"

    if ctype == "Residential":
        base_charge = 60.0
        tax_pct = 0.05
        # Slab 1: 0 - 15 kL @ 8.00
        # Slab 2: 16 - 30 kL @ 14.00
        # Slab 3: > 30 kL @ 22.00
        if units <= 15:
            cons_charge = units * 8.0
        elif units <= 30:
            cons_charge = (15 * 8.0) + ((units - 15) * 14.0)
        else:
            cons_charge = (15 * 8.0) + (15 * 14.0) + ((units - 30) * 22.0)

    elif ctype == "Commercial":
        base_charge = 150.0
        tax_pct = 0.08
        if units <= 30:
            cons_charge = units * 22.0
        else:
            cons_charge = (30 * 22.0) + ((units - 30) * 36.0)

    else:  # Industrial
        base_charge = 400.0
        tax_pct = 0.10
        cons_charge = units * 48.0

    tax_surcharge = round(cons_charge * tax_pct, 2)
    total_amount = round(base_charge + cons_charge + tax_surcharge, 2)

    return {
        "base_charge": round(base_charge, 2),
        "consumption_charge": round(cons_charge, 2),
        "tax_surcharge": tax_surcharge,
        "total_amount": total_amount
    }

# ----------------- USER & AUTH HELPERS -----------------
def get_user_by_username(username):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    return user

def get_user_by_id(user_id):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    return user

def create_user(username, password, role, full_name, email, phone=""):
    conn = get_db()
    pwd_hash = generate_password_hash(password)
    try:
        cur = conn.execute(
            "INSERT INTO users (username, password, role, full_name, email, phone) VALUES (?, ?, ?, ?, ?, ?)",
            (username, pwd_hash, role, full_name, email, phone)
        )
        conn.commit()
        user_id = cur.lastrowid
        return user_id
    finally:
        conn.close()

# ----------------- CONSUMER PROFILE HELPERS -----------------
def get_consumer_by_user_id(user_id):
    conn = get_db()
    consumer = conn.execute("""
        SELECT c.*, u.username, u.full_name, u.email, u.phone, z.zone_name, z.ward_area,
               z.reservoir_name, z.reservoir_level_pct, z.water_pressure_psi, z.supply_status,
               z.morning_slot, z.evening_slot, z.purity_ph, z.tds_ppm
        FROM consumers c
        JOIN users u ON c.user_id = u.user_id
        JOIN supply_zones z ON c.zone_id = z.zone_id
        WHERE c.user_id = ?
    """, (user_id,)).fetchone()
    conn.close()
    return consumer

def get_consumer_by_id(consumer_id):
    conn = get_db()
    consumer = conn.execute("""
        SELECT c.*, u.username, u.full_name, u.email, u.phone, z.zone_name, z.ward_area
        FROM consumers c
        JOIN users u ON c.user_id = u.user_id
        JOIN supply_zones z ON c.zone_id = z.zone_id
        WHERE c.consumer_id = ?
    """, (consumer_id,)).fetchone()
    conn.close()
    return consumer

def get_all_consumers():
    conn = get_db()
    consumers = conn.execute("""
        SELECT c.*, u.username, u.full_name, u.email, u.phone, z.zone_name,
               (SELECT COUNT(*) FROM bills WHERE consumer_id = c.consumer_id AND status = 'UNPAID') AS unpaid_bills_count,
               (SELECT COALESCE(SUM(total_amount), 0) FROM bills WHERE consumer_id = c.consumer_id AND status = 'UNPAID') AS pending_amount
        FROM consumers c
        JOIN users u ON c.user_id = u.user_id
        JOIN supply_zones z ON c.zone_id = z.zone_id
        ORDER BY c.consumer_id ASC
    """).fetchall()
    conn.close()
    return consumers

def create_consumer_profile(user_id, zone_id, connection_type, address, meter_number=None, initial_reading=0.0):
    conn = get_db()
    cur = conn.cursor()
    # Generate account number e.g. WTR-1025
    cur.execute("SELECT MAX(consumer_id) FROM consumers")
    max_id = cur.fetchone()[0] or 100
    account_number = f"WTR-{max_id + 101}"
    if not meter_number:
        meter_number = f"MTR-{max_id + 501}"
    
    cur.execute("""
        INSERT INTO consumers (user_id, account_number, zone_id, connection_type, meter_number, installation_date, address, last_meter_reading)
        VALUES (?, ?, ?, ?, ?, DATE('now'), ?, ?)
    """, (user_id, account_number, zone_id, connection_type, meter_number, address, initial_reading))
    conn.commit()
    consumer_id = cur.lastrowid
    conn.close()
    return consumer_id

# ----------------- SUPPLY ZONES & MONITORING -----------------
def get_all_zones():
    conn = get_db()
    zones = conn.execute("""
        SELECT z.*, COUNT(c.consumer_id) as total_consumers
        FROM supply_zones z
        LEFT JOIN consumers c ON z.zone_id = c.zone_id
        GROUP BY z.zone_id
        ORDER BY z.zone_id ASC
    """).fetchall()
    conn.close()
    return zones

def get_zone_by_id(zone_id):
    conn = get_db()
    zone = conn.execute("SELECT * FROM supply_zones WHERE zone_id = ?", (zone_id,)).fetchone()
    conn.close()
    return zone

def update_zone_details(zone_id, status, reservoir_level, water_pressure, morning_slot, evening_slot, purity_ph=None, tds_ppm=None):
    conn = get_db()
    conn.execute("""
        UPDATE supply_zones
        SET supply_status = ?,
            reservoir_level_pct = ?,
            water_pressure_psi = ?,
            morning_slot = ?,
            evening_slot = ?,
            purity_ph = COALESCE(?, purity_ph),
            tds_ppm = COALESCE(?, tds_ppm),
            updated_at = CURRENT_TIMESTAMP
        WHERE zone_id = ?
    """, (status, reservoir_level, water_pressure, morning_slot, evening_slot, purity_ph, tds_ppm, zone_id))
    conn.commit()
    conn.close()

def get_active_alerts(zone_id=None):
    conn = get_db()
    if zone_id:
        alerts = conn.execute("""
            SELECT a.*, z.zone_name 
            FROM supply_alerts a
            LEFT JOIN supply_zones z ON a.zone_id = z.zone_id
            WHERE a.is_active = 1 AND (a.zone_id = ? OR a.zone_id IS NULL)
            ORDER BY a.posted_at DESC
        """, (zone_id,)).fetchall()
    else:
        alerts = conn.execute("""
            SELECT a.*, z.zone_name 
            FROM supply_alerts a
            LEFT JOIN supply_zones z ON a.zone_id = z.zone_id
            ORDER BY a.posted_at DESC
        """).fetchall()
    conn.close()
    return alerts

def add_supply_alert(zone_id, title, message, severity='Warning'):
    conn = get_db()
    zid = int(zone_id) if zone_id and zone_id != "" and str(zone_id) != "0" else None
    conn.execute("""
        INSERT INTO supply_alerts (zone_id, title, message, severity)
        VALUES (?, ?, ?, ?)
    """, (zid, title, message, severity))
    conn.commit()
    conn.close()

def toggle_alert_status(alert_id, is_active):
    conn = get_db()
    conn.execute("UPDATE supply_alerts SET is_active = ? WHERE alert_id = ?", (1 if is_active else 0, alert_id))
    conn.commit()
    conn.close()

# ----------------- BILLING OPERATIONS -----------------
def generate_bill_number():
    date_str = datetime.now().strftime("%Y%m")
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM bills")
    count = cur.fetchone()[0] + 1
    conn.close()
    return f"BILL-{date_str}-{count:04d}"

def add_bill(consumer_id, billing_month, curr_reading, prev_reading=None, due_days=15, notes=None):
    """
    Creates a new bill for a consumer.
    Triggers at SQLite level will automatically update consumer's last_meter_reading!
    """
    conn = get_db()
    consumer = conn.execute("SELECT * FROM consumers WHERE consumer_id = ?", (consumer_id,)).fetchone()
    if not consumer:
        conn.close()
        raise ValueError("Consumer not found.")

    curr_reading = float(curr_reading)
    if prev_reading is None:
        prev_reading = float(consumer["last_meter_reading"] or 0.0)
    else:
        prev_reading = float(prev_reading)

    if curr_reading < prev_reading:
        conn.close()
        raise ValueError(f"Current reading ({curr_reading}) cannot be less than previous reading ({prev_reading}).")

    units_consumed = round(curr_reading - prev_reading, 2)
    tariff = calculate_water_tariff(consumer["connection_type"], units_consumed)

    bill_number = generate_bill_number()
    billing_date = datetime.now().strftime("%Y-%m-%d")
    
    # Calculate due date
    from datetime import timedelta
    due_date = (datetime.now() + timedelta(days=int(due_days))).strftime("%Y-%m-%d")

    cur = conn.cursor()
    cur.execute("""
        INSERT INTO bills (
            bill_number, consumer_id, billing_month, billing_date, due_date,
            prev_reading, curr_reading, units_consumed,
            base_charge, consumption_charge, tax_surcharge, total_amount,
            status, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'UNPAID', ?)
    """, (
        bill_number, consumer_id, billing_month, billing_date, due_date,
        prev_reading, curr_reading, units_consumed,
        tariff["base_charge"], tariff["consumption_charge"], tariff["tax_surcharge"], tariff["total_amount"],
        notes or f"Generated for {billing_month}"
    ))
    bill_id = cur.lastrowid
    conn.commit()
    conn.close()
    return bill_id

def get_bills_for_consumer(consumer_id):
    conn = get_db()
    bills = conn.execute("""
        SELECT b.*, p.payment_date, p.receipt_number, p.payment_method
        FROM bills b
        LEFT JOIN payments p ON b.bill_id = p.bill_id
        WHERE b.consumer_id = ?
        ORDER BY b.bill_id DESC
    """, (consumer_id,)).fetchall()
    conn.close()
    return bills

def get_all_bills(filter_status=None):
    conn = get_db()
    query = """
        SELECT b.*, c.account_number, c.meter_number, c.connection_type,
               u.full_name as consumer_name, z.zone_name,
               p.payment_date, p.receipt_number
        FROM bills b
        JOIN consumers c ON b.consumer_id = c.consumer_id
        JOIN users u ON c.user_id = u.user_id
        JOIN supply_zones z ON c.zone_id = z.zone_id
        LEFT JOIN payments p ON b.bill_id = p.bill_id
    """
    params = []
    if filter_status and filter_status != "ALL":
        query += " WHERE b.status = ?"
        params.append(filter_status)
    query += " ORDER BY b.bill_id DESC"

    bills = conn.execute(query, params).fetchall()
    conn.close()
    return bills

def get_bill_by_id(bill_id):
    conn = get_db()
    bill = conn.execute("""
        SELECT b.*, c.account_number, c.meter_number, c.connection_type, c.address,
               u.full_name as consumer_name, u.email, u.phone,
               z.zone_name, z.ward_area,
               p.receipt_number, p.transaction_ref, p.payment_date, p.payment_method
        FROM bills b
        JOIN consumers c ON b.consumer_id = c.consumer_id
        JOIN users u ON c.user_id = u.user_id
        JOIN supply_zones z ON c.zone_id = z.zone_id
        LEFT JOIN payments p ON b.bill_id = p.bill_id
        WHERE b.bill_id = ?
    """, (bill_id,)).fetchone()
    conn.close()
    return bill

# ----------------- PAYMENT SIMULATION -----------------
def record_bill_payment(bill_id, payment_method="UPI"):
    conn = get_db()
    bill = conn.execute("SELECT * FROM bills WHERE bill_id = ?", (bill_id,)).fetchone()
    if not bill:
        conn.close()
        raise ValueError("Bill not found.")
    
    if bill["status"] == "PAID":
        conn.close()
        raise ValueError("Bill is already paid.")

    import random
    trans_code = f"TXN-{datetime.now().strftime('%Y%m%d%H%M')}-{random.randint(1000, 9999)}"
    receipt_no = f"RCPT-{bill['bill_id']:04d}-{random.randint(100, 999)}"
    
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO payments (bill_id, consumer_id, receipt_number, transaction_ref, amount_paid, payment_method)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (bill_id, bill["consumer_id"], receipt_no, trans_code, bill["total_amount"], payment_method))
    
    # Note: Trigger 'trg_mark_bill_paid' defined in schema.sql will also fire to ensure database-level consistency!
    # We execute an explicit update as well to be foolproof in any driver environment:
    cur.execute("UPDATE bills SET status = 'PAID' WHERE bill_id = ?", (bill_id,))
    
    conn.commit()
    conn.close()
    return {"receipt_number": receipt_no, "transaction_ref": trans_code, "amount": bill["total_amount"]}

def get_payments_for_consumer(consumer_id):
    conn = get_db()
    payments = conn.execute("""
        SELECT p.*, b.bill_number, b.billing_month, b.units_consumed
        FROM payments p
        JOIN bills b ON p.bill_id = b.bill_id
        WHERE p.consumer_id = ?
        ORDER BY p.payment_id DESC
    """, (consumer_id,)).fetchall()
    conn.close()
    return payments

# ----------------- COMPLAINTS / TICKETS -----------------
def add_complaint(consumer_id, category, description):
    conn = get_db()
    conn.execute("""
        INSERT INTO complaints (consumer_id, category, description, status)
        VALUES (?, ?, ?, 'Pending')
    """, (consumer_id, category, description))
    conn.commit()
    conn.close()

def get_complaints_by_consumer(consumer_id):
    conn = get_db()
    complaints = conn.execute("""
        SELECT * FROM complaints 
        WHERE consumer_id = ? 
        ORDER BY complaint_id DESC
    """, (consumer_id,)).fetchall()
    conn.close()
    return complaints

def get_all_complaints():
    conn = get_db()
    complaints = conn.execute("""
        SELECT cm.*, c.account_number, u.full_name as consumer_name, z.zone_name
        FROM complaints cm
        JOIN consumers c ON cm.consumer_id = c.consumer_id
        JOIN users u ON c.user_id = u.user_id
        JOIN supply_zones z ON c.zone_id = z.zone_id
        ORDER BY CASE cm.status WHEN 'Pending' THEN 1 WHEN 'In Progress' THEN 2 ELSE 3 END, cm.complaint_id DESC
    """).fetchall()
    conn.close()
    return complaints

def update_complaint_status(complaint_id, status, admin_response=None):
    conn = get_db()
    resolved_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S") if status == "Resolved" else None
    conn.execute("""
        UPDATE complaints
        SET status = ?, admin_response = ?, resolved_at = COALESCE(?, resolved_at)
        WHERE complaint_id = ?
    """, (status, admin_response, resolved_at, complaint_id))
    conn.commit()
    conn.close()

# ----------------- DASHBOARD ANALYTICS -----------------
def get_admin_dashboard_metrics():
    conn = get_db()
    total_consumers = conn.execute("SELECT COUNT(*) FROM consumers").fetchone()[0]
    total_zones = conn.execute("SELECT COUNT(*) FROM supply_zones").fetchone()[0]
    
    billing_stats = conn.execute("""
        SELECT 
            COALESCE(SUM(CASE WHEN status = 'PAID' THEN total_amount ELSE 0 END), 0) AS total_revenue,
            COALESCE(SUM(CASE WHEN status = 'UNPAID' THEN total_amount ELSE 0 END), 0) AS pending_revenue,
            COUNT(CASE WHEN status = 'UNPAID' THEN 1 END) AS unpaid_bills_count,
            COUNT(*) AS total_bills_count
        FROM bills
    """).fetchone()

    pending_complaints = conn.execute("SELECT COUNT(*) FROM complaints WHERE status != 'Resolved'").fetchone()[0]
    
    avg_reservoir = conn.execute("SELECT AVG(reservoir_level_pct) FROM supply_zones").fetchone()[0] or 0.0

    recent_bills = conn.execute("""
        SELECT b.*, u.full_name, c.account_number 
        FROM bills b
        JOIN consumers c ON b.consumer_id = c.consumer_id
        JOIN users u ON c.user_id = u.user_id
        ORDER BY b.bill_id DESC LIMIT 5
    """).fetchall()

    conn.close()
    return {
        "total_consumers": total_consumers,
        "total_zones": total_zones,
        "total_revenue": round(billing_stats["total_revenue"], 2),
        "pending_revenue": round(billing_stats["pending_revenue"], 2),
        "unpaid_bills_count": billing_stats["unpaid_bills_count"],
        "total_bills_count": billing_stats["total_bills_count"],
        "pending_complaints": pending_complaints,
        "avg_reservoir": round(avg_reservoir, 1),
        "recent_bills": recent_bills
    }

def get_consumer_dashboard_metrics(consumer_id):
    conn = get_db()
    
    # Financial summary
    fin = conn.execute("""
        SELECT 
            COALESCE(SUM(CASE WHEN status = 'UNPAID' THEN total_amount ELSE 0 END), 0) as pending_total,
            COUNT(CASE WHEN status = 'UNPAID' THEN 1 END) as pending_count,
            COALESCE(SUM(CASE WHEN status = 'PAID' THEN total_amount ELSE 0 END), 0) as paid_total
        FROM bills
        WHERE consumer_id = ?
    """, (consumer_id,)).fetchone()

    # Latest unpaid bill
    latest_unpaid = conn.execute("""
        SELECT * FROM bills 
        WHERE consumer_id = ? AND status = 'UNPAID'
        ORDER BY due_date ASC LIMIT 1
    """, (consumer_id,)).fetchone()

    # Water usage history (last 6 bills)
    usage_history = [dict(r) for r in conn.execute("""
        SELECT billing_month, units_consumed, total_amount, status
        FROM bills
        WHERE consumer_id = ?
        ORDER BY bill_id ASC LIMIT 6
    """, (consumer_id,)).fetchall()]

    # Consumer details with zone info
    consumer_info = conn.execute("""
        SELECT c.*, u.full_name, u.email, u.phone,
               z.zone_name, z.ward_area, z.reservoir_name, z.reservoir_level_pct,
               z.water_pressure_psi, z.supply_status, z.morning_slot, z.evening_slot,
               z.purity_ph, z.tds_ppm
        FROM consumers c
        JOIN users u ON c.user_id = u.user_id
        JOIN supply_zones z ON c.zone_id = z.zone_id
        WHERE c.consumer_id = ?
    """, (consumer_id,)).fetchone()

    conn.close()
    return {
        "pending_total": round(fin["pending_total"], 2),
        "pending_count": fin["pending_count"],
        "paid_total": round(fin["paid_total"], 2),
        "latest_unpaid": latest_unpaid,
        "usage_history": usage_history,
        "consumer": consumer_info
    }
