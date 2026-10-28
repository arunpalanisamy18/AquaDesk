import sqlite3
import os
import random
import zoneinfo
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timezone, timedelta

DB_NAME = "water_supply_dbms.db"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

_INITIALIZING = False

UTC_TZ = timezone.utc
try:
    IST_TZ = zoneinfo.ZoneInfo("Asia/Kolkata")
except Exception:
    IST_TZ = timezone(timedelta(hours=5, minutes=30), name="IST")

def get_utc_now():
    """Returns timezone-aware current UTC datetime."""
    return datetime.now(UTC_TZ)

def get_utc_now_str():
    """Returns current UTC timestamp formatted as YYYY-MM-DD HH:MM:SS for database storage."""
    return get_utc_now().strftime("%Y-%m-%d %H:%M:%S")

def get_ist_now():
    """Returns timezone-aware current IST datetime (Asia/Kolkata)."""
    return datetime.now(IST_TZ)

def utc_to_ist_str(utc_val, fmt="%d %b %Y, %I:%M %p"):
    """
    Parses a UTC timestamp (datetime object or string) and converts it to Asia/Kolkata (IST).
    Handles ISO formats, microsecond formats, and SQLite standard YYYY-MM-DD HH:MM:SS.
    Returns 'N/A' if value is empty/None.
    """
    if not utc_val:
        return "N/A"
    if isinstance(utc_val, datetime):
        dt = utc_val
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC_TZ)
        return dt.astimezone(IST_TZ).strftime(fmt)
    
    val_str = str(utc_val).strip()
    if not val_str:
        return "N/A"
    
    # Try parsing string representations
    for p_fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            dt = datetime.strptime(val_str[:19], "%Y-%m-%d %H:%M:%S")
            dt = dt.replace(tzinfo=UTC_TZ)
            return dt.astimezone(IST_TZ).strftime(fmt)
        except ValueError:
            continue
    return val_str

def format_calendar_date(date_val, fmt="%d %b %Y"):
    """
    Formats calendar dates (YYYY-MM-DD) for display without timezone shifting.
    """
    if not date_val:
        return "N/A"
    val_str = str(date_val).strip()
    try:
        dt = datetime.strptime(val_str[:10], "%Y-%m-%d")
        return dt.strftime(fmt)
    except ValueError:
        return val_str

def get_db_path():
    """Returns the absolute path to the intended database file."""
    custom_path = os.environ.get("DATABASE_PATH")
    if custom_path:
        return os.path.abspath(custom_path)
    return os.path.join(BASE_DIR, DB_NAME)

def get_db():
    """
    Returns a configured SQLite database connection.
    Guarantees foreign keys are enabled and rows are accessible by column name.
    """
    db_file = get_db_path()
    if not os.path.exists(db_file) and not _INITIALIZING:
        raise FileNotFoundError(f"Database file not found at: {db_file}")

    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    """
    Initializes or updates schema without destroying existing data.
    Ensures tables, views, and triggers are safely created or refreshed.
    """
    global _INITIALIZING
    _INITIALIZING = True
    try:
        schema_path = os.path.join(BASE_DIR, "schema.sql")
        with open(schema_path, "r", encoding="utf-8") as f:
            schema_sql = f.read()

        db_file = get_db_path()
        conn = sqlite3.connect(db_file)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.executescript(schema_sql)
        # Explicit migration: database-level enforcement that each bill has at most one payment
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_payments_bill_id_unique ON payments(bill_id);")
        conn.commit()
        conn.close()
    finally:
        _INITIALIZING = False

# ----------------- TARIFF CALCULATION ENGINE -----------------
def calculate_water_tariff(connection_type, units_consumed):
    """
    Computes bill breakdown based on progressive slab tariffs and connection type.
    units_consumed in Kiloliters (kL).
    """
    try:
        units = float(units_consumed)
    except (ValueError, TypeError):
        raise ValueError("Units consumed must be a valid numeric value.")

    if units < 0:
        raise ValueError("Units consumed cannot be negative.")

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
    try:
        return conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    finally:
        conn.close()

def get_user_by_id(user_id):
    conn = get_db()
    try:
        return conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    finally:
        conn.close()

def get_all_users():
    """Returns safe projection of all users without sensitive hashes."""
    conn = get_db()
    try:
        return conn.execute("""
            SELECT user_id, username, role, full_name, email, phone, created_at
            FROM users ORDER BY user_id ASC
        """).fetchall()
    finally:
        conn.close()

def create_user(username, password, role, full_name, email, phone=""):
    if not username or not password or not full_name or not email:
        raise ValueError("Username, password, full name, and email are required.")
    if role not in ('admin', 'consumer'):
        raise ValueError("Role must be 'admin' or 'consumer'.")

    conn = get_db()
    try:
        with conn:
            pwd_hash = generate_password_hash(password)
            cur = conn.execute(
                "INSERT INTO users (username, password, role, full_name, email, phone) VALUES (?, ?, ?, ?, ?, ?)",
                (username.strip(), pwd_hash, role, full_name.strip(), email.strip(), (phone or "").strip())
            )
            return cur.lastrowid
    finally:
        conn.close()

# ----------------- CONSUMER PROFILE HELPERS -----------------
def get_consumer_by_user_id(user_id):
    conn = get_db()
    try:
        return conn.execute("""
            SELECT c.*, u.username, u.full_name, u.email, u.phone, z.zone_name, z.ward_area,
                   z.reservoir_name, z.reservoir_level_pct, z.water_pressure_psi, z.supply_status,
                   z.morning_slot, z.evening_slot, z.purity_ph, z.tds_ppm
            FROM consumers c
            JOIN users u ON c.user_id = u.user_id
            JOIN supply_zones z ON c.zone_id = z.zone_id
            WHERE c.user_id = ?
        """, (user_id,)).fetchone()
    finally:
        conn.close()

def get_consumer_by_id(consumer_id):
    conn = get_db()
    try:
        return conn.execute("""
            SELECT c.*, u.username, u.full_name, u.email, u.phone, z.zone_name, z.ward_area
            FROM consumers c
            JOIN users u ON c.user_id = u.user_id
            JOIN supply_zones z ON c.zone_id = z.zone_id
            WHERE c.consumer_id = ?
        """, (consumer_id,)).fetchone()
    finally:
        conn.close()

def get_all_consumers():
    conn = get_db()
    try:
        return conn.execute("""
            SELECT c.*, u.username, u.full_name, u.email, u.phone, z.zone_name,
                   (SELECT COUNT(*) FROM bills WHERE consumer_id = c.consumer_id AND status IN ('UNPAID', 'OVERDUE')) AS unpaid_bills_count,
                   (SELECT COALESCE(SUM(total_amount), 0) FROM bills WHERE consumer_id = c.consumer_id AND status IN ('UNPAID', 'OVERDUE')) AS pending_amount
            FROM consumers c
            JOIN users u ON c.user_id = u.user_id
            JOIN supply_zones z ON c.zone_id = z.zone_id
            ORDER BY c.consumer_id ASC
        """).fetchall()
    finally:
        conn.close()

def create_consumer_profile(user_id, zone_id, connection_type, address, meter_number=None, initial_reading=0.0):
    if not address:
        raise ValueError("Address is required.")
    try:
        reading = float(initial_reading or 0.0)
    except (ValueError, TypeError):
        raise ValueError("Initial meter reading must be a valid number.")
    if reading < 0:
        raise ValueError("Initial meter reading cannot be negative.")

    conn = get_db()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute("SELECT MAX(consumer_id) FROM consumers")
            max_id = cur.fetchone()[0] or 100
            account_number = f"WTR-{max_id + 101}"
            if not meter_number:
                meter_number = f"MTR-{max_id + 501}"

            cur.execute("""
                INSERT INTO consumers (user_id, account_number, zone_id, connection_type, meter_number, installation_date, address, last_meter_reading)
                VALUES (?, ?, ?, ?, ?, DATE('now'), ?, ?)
            """, (user_id, account_number, int(zone_id), connection_type, meter_number, address.strip(), reading))
            return cur.lastrowid
    finally:
        conn.close()

def register_consumer_account(username, password, full_name, email, phone, zone_id, connection_type, address, initial_reading=0.0, meter_number=None):
    """
    Atomic consumer account registration.
    Inserts user and consumer profile in a SINGLE database transaction.
    Guarantees no orphaned user records if profile creation encounters any error.
    """
    if not username or not password or not full_name or not email or not address:
        raise ValueError("All required fields must be filled.")

    try:
        reading = float(initial_reading or 0.0)
    except (ValueError, TypeError):
        raise ValueError("Initial meter reading must be a valid number.")
    if reading < 0:
        raise ValueError("Initial meter reading cannot be negative.")

    conn = get_db()
    try:
        with conn:
            # Check username and email uniqueness
            cur = conn.cursor()
            cur.execute("SELECT user_id FROM users WHERE username = ?", (username.strip(),))
            if cur.fetchone():
                raise ValueError(f"Username '{username}' is already registered.")

            cur.execute("SELECT user_id FROM users WHERE email = ?", (email.strip(),))
            if cur.fetchone():
                raise ValueError(f"Email '{email}' is already registered to another account.")

            # Verify zone exists
            cur.execute("SELECT zone_id FROM supply_zones WHERE zone_id = ?", (int(zone_id),))
            if not cur.fetchone():
                raise ValueError("Selected water supply zone does not exist.")

            # Create User
            pwd_hash = generate_password_hash(password)
            cur.execute(
                "INSERT INTO users (username, password, role, full_name, email, phone) VALUES (?, ?, 'consumer', ?, ?, ?)",
                (username.strip(), pwd_hash, full_name.strip(), email.strip(), (phone or "").strip())
            )
            user_id = cur.lastrowid

            # Generate account and meter numbers
            cur.execute("SELECT MAX(consumer_id) FROM consumers")
            max_id = cur.fetchone()[0] or 100
            account_number = f"WTR-{max_id + 101}"
            if not meter_number:
                meter_number = f"MTR-{max_id + 501}"

            # Create Consumer Profile
            cur.execute("""
                INSERT INTO consumers (user_id, account_number, zone_id, connection_type, meter_number, installation_date, address, last_meter_reading, status)
                VALUES (?, ?, ?, ?, ?, DATE('now'), ?, ?, 'Active')
            """, (user_id, account_number, int(zone_id), connection_type, meter_number, address.strip(), reading))
            consumer_id = cur.lastrowid

            return user_id, consumer_id
    finally:
        conn.close()

# ----------------- SUPPLY ZONES & MONITORING -----------------
def get_all_zones():
    conn = get_db()
    try:
        return conn.execute("""
            SELECT z.*, COUNT(c.consumer_id) as total_consumers
            FROM supply_zones z
            LEFT JOIN consumers c ON z.zone_id = c.zone_id
            GROUP BY z.zone_id
            ORDER BY z.zone_id ASC
        """).fetchall()
    finally:
        conn.close()

def get_zone_by_id(zone_id):
    conn = get_db()
    try:
        return conn.execute("SELECT * FROM supply_zones WHERE zone_id = ?", (zone_id,)).fetchone()
    finally:
        conn.close()

def update_zone_details(zone_id, status, reservoir_level, water_pressure, morning_slot, evening_slot, purity_ph=None, tds_ppm=None):
    if status not in ('ACTIVE', 'SCHEDULED', 'MAINTENANCE', 'OUTAGE'):
        raise ValueError("Invalid supply status.")
    
    try:
        res_lvl = float(reservoir_level)
    except (ValueError, TypeError):
        raise ValueError("Reservoir level must be a numeric value.")
    if not (0.0 <= res_lvl <= 100.0):
        raise ValueError("Reservoir level must be between 0% and 100%.")

    try:
        pressure = float(water_pressure)
    except (ValueError, TypeError):
        raise ValueError("Water pressure must be a numeric value.")
    if pressure < 0.0:
        raise ValueError("Water pressure cannot be negative.")

    ph_val = None
    if purity_ph is not None and str(purity_ph).strip() != "":
        ph_val = float(purity_ph)
        if not (0.0 <= ph_val <= 14.0):
            raise ValueError("Water purity pH must be between 0.0 and 14.0.")

    tds_val = None
    if tds_ppm is not None and str(tds_ppm).strip() != "":
        tds_val = int(tds_ppm)
        if tds_val < 0:
            raise ValueError("TDS ppm cannot be negative.")

    conn = get_db()
    try:
        with conn:
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
            """, (status, res_lvl, pressure, morning_slot, evening_slot, ph_val, tds_val, int(zone_id)))
    finally:
        conn.close()

def get_active_alerts(zone_id=None):
    conn = get_db()
    try:
        if zone_id:
            return conn.execute("""
                SELECT a.*, z.zone_name 
                FROM supply_alerts a
                LEFT JOIN supply_zones z ON a.zone_id = z.zone_id
                WHERE a.is_active = 1 AND (a.zone_id = ? OR a.zone_id IS NULL)
                ORDER BY a.posted_at DESC
            """, (zone_id,)).fetchall()
        else:
            return conn.execute("""
                SELECT a.*, z.zone_name 
                FROM supply_alerts a
                LEFT JOIN supply_zones z ON a.zone_id = z.zone_id
                ORDER BY a.posted_at DESC
            """).fetchall()
    finally:
        conn.close()

def add_supply_alert(zone_id, title, message, severity='Warning'):
    if not title or not message:
        raise ValueError("Alert title and message are required.")
    if severity not in ('Info', 'Warning', 'Emergency'):
        raise ValueError("Severity must be 'Info', 'Warning', or 'Emergency'.")

    zid = int(zone_id) if zone_id and str(zone_id).strip() not in ("", "0", "None") else None
    conn = get_db()
    try:
        with conn:
            conn.execute("""
                INSERT INTO supply_alerts (zone_id, title, message, severity, posted_at)
                VALUES (?, ?, ?, ?, ?)
            """, (zid, title.strip(), message.strip(), severity, get_utc_now_str()))
    finally:
        conn.close()

def toggle_alert_status(alert_id, is_active):
    conn = get_db()
    try:
        with conn:
            conn.execute("UPDATE supply_alerts SET is_active = ? WHERE alert_id = ?", (1 if is_active else 0, int(alert_id)))
    finally:
        conn.close()

# ----------------- BILLING OPERATIONS -----------------
def generate_bill_number():
    date_str = get_ist_now().strftime("%Y%m")
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM bills")
        count = cur.fetchone()[0] + 1
        return f"BILL-{date_str}-{count:04d}"
    finally:
        conn.close()

def add_bill(consumer_id, billing_month, curr_reading, prev_reading=None, due_days=15, notes=None, billing_date=None, due_date=None):
    """
    Creates a new utility bill for a consumer.
    Ensures readings are valid (non-negative, non-decreasing) and prevents duplicate
    bills for the same billing cycle.
    Database trigger automatically updates consumer's last_meter_reading!
    Stores audit timestamp created_at in UTC; records calendar billing_date and due_date.
    """
    if not billing_month or not str(billing_month).strip():
        raise ValueError("Billing month is required.")

    try:
        curr_reading = float(curr_reading)
    except (ValueError, TypeError):
        raise ValueError("Current meter reading must be a valid number.")

    if curr_reading < 0:
        raise ValueError("Current meter reading cannot be negative.")

    conn = get_db()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM consumers WHERE consumer_id = ?", (int(consumer_id),))
            consumer = cur.fetchone()
            if not consumer:
                raise ValueError("Consumer not found.")

            if prev_reading is None or str(prev_reading).strip() == "":
                prev_reading = float(consumer["last_meter_reading"] or 0.0)
            else:
                try:
                    prev_reading = float(prev_reading)
                except (ValueError, TypeError):
                    raise ValueError("Previous meter reading must be a valid number.")

            if prev_reading < 0:
                raise ValueError("Previous meter reading cannot be negative.")

            if curr_reading < prev_reading:
                raise ValueError(f"Current reading ({curr_reading:.2f} kL) cannot be less than previous reading ({prev_reading:.2f} kL).")

            # Check for existing bill for the same consumer and month
            cur.execute("""
                SELECT bill_id, bill_number FROM bills
                WHERE consumer_id = ? AND billing_month = ?
            """, (int(consumer_id), billing_month.strip()))
            existing = cur.fetchone()
            if existing:
                raise ValueError(f"A bill for '{billing_month.strip()}' has already been generated for this consumer ({existing['bill_number']}).")

            units_consumed = round(curr_reading - prev_reading, 2)
            tariff = calculate_water_tariff(consumer["connection_type"], units_consumed)

            bill_number = generate_bill_number()
            today_cal = get_ist_now().strftime("%Y-%m-%d")
            billing_date = str(billing_date).strip() if billing_date else today_cal
            
            if not due_date:
                due_date = (datetime.strptime(billing_date, "%Y-%m-%d") + timedelta(days=int(due_days or 15))).strftime("%Y-%m-%d")
            else:
                due_date = str(due_date).strip()

            if due_date < billing_date:
                raise ValueError(f"Due date ({due_date}) cannot be earlier than bill issue date ({billing_date}).")

            created_at_utc = get_utc_now_str()

            cur.execute("""
                INSERT INTO bills (
                    bill_number, consumer_id, billing_month, billing_date, due_date,
                    prev_reading, curr_reading, units_consumed,
                    base_charge, consumption_charge, tax_surcharge, total_amount,
                    status, notes, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'UNPAID', ?, ?)
            """, (
                bill_number, int(consumer_id), billing_month.strip(), billing_date, due_date,
                prev_reading, curr_reading, units_consumed,
                tariff["base_charge"], tariff["consumption_charge"], tariff["tax_surcharge"], tariff["total_amount"],
                notes or f"Generated for {billing_month.strip()}", created_at_utc
            ))
            return cur.lastrowid
    finally:
        conn.close()

def get_bills_for_consumer(consumer_id):
    conn = get_db()
    try:
        return conn.execute("""
            SELECT b.*, p.payment_date, p.receipt_number, p.transaction_ref, p.payment_method
            FROM bills b
            LEFT JOIN (
                SELECT bill_id, MAX(payment_id) as payment_id, receipt_number, transaction_ref,
                       amount_paid, payment_date, payment_method
                FROM payments
                GROUP BY bill_id
            ) p ON b.bill_id = p.bill_id
            WHERE b.consumer_id = ?
            ORDER BY b.bill_id DESC
        """, (int(consumer_id),)).fetchall()
    finally:
        conn.close()

def get_all_bills(filter_status=None):
    conn = get_db()
    try:
        query = """
            SELECT b.*, c.account_number, c.meter_number, c.connection_type,
                   u.full_name as consumer_name, z.zone_name,
                   p.payment_date, p.receipt_number, p.transaction_ref, p.payment_method
            FROM bills b
            JOIN consumers c ON b.consumer_id = c.consumer_id
            JOIN users u ON c.user_id = u.user_id
            JOIN supply_zones z ON c.zone_id = z.zone_id
            LEFT JOIN (
                SELECT bill_id, MAX(payment_id) as payment_id, receipt_number, transaction_ref,
                       amount_paid, payment_date, payment_method
                FROM payments
                GROUP BY bill_id
            ) p ON b.bill_id = p.bill_id
        """
        params = []
        if filter_status and filter_status != "ALL":
            query += " WHERE b.status = ?"
            params.append(filter_status)
        query += " ORDER BY b.bill_id DESC"

        return conn.execute(query, params).fetchall()
    finally:
        conn.close()

def get_bill_by_id(bill_id):
    conn = get_db()
    try:
        return conn.execute("""
            SELECT b.*, c.account_number, c.meter_number, c.connection_type, c.address,
                   u.full_name as consumer_name, u.email, u.phone,
                   z.zone_name, z.ward_area,
                   p.receipt_number, p.transaction_ref, p.payment_date, p.payment_method
            FROM bills b
            JOIN consumers c ON b.consumer_id = c.consumer_id
            JOIN users u ON c.user_id = u.user_id
            JOIN supply_zones z ON c.zone_id = z.zone_id
            LEFT JOIN (
                SELECT bill_id, MAX(payment_id) as payment_id, receipt_number, transaction_ref,
                       amount_paid, payment_date, payment_method
                FROM payments
                GROUP BY bill_id
            ) p ON b.bill_id = p.bill_id
            WHERE b.bill_id = ?
        """, (int(bill_id),)).fetchone()
    finally:
        conn.close()

# ----------------- PAYMENT SIMULATION -----------------
def record_bill_payment(bill_id, payment_method="UPI", amount_paid=None, consumer_id=None):
    """
    Records a payment for a bill.
    Validates bill existence, consumer authorization, payment method, and amount.
    Enforces exactly one complete payment per bill (no double-paying or underpaying).
    Stores event timestamp payment_date in UTC.
    Fires database trigger 'trg_mark_bill_paid' and updates bill status to PAID.
    """
    valid_methods = {'UPI', 'Credit/Debit Card', 'Net Banking', 'Cash', 'Counter'}
    if payment_method not in valid_methods:
        raise ValueError(f"Invalid payment method '{payment_method}'. Allowed: {', '.join(valid_methods)}")

    conn = get_db()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM bills WHERE bill_id = ?", (int(bill_id),))
            bill = cur.fetchone()
            if not bill:
                raise ValueError("Bill not found.")

            if consumer_id is not None and bill["consumer_id"] != int(consumer_id):
                raise ValueError("Unauthorized: You can only pay your own utility bills.")

            if bill["status"] == "PAID":
                raise ValueError(f"Bill #{bill['bill_number']} has already been marked as PAID in full.")

            # Check if any prior payment exists for this bill
            cur.execute("SELECT payment_id, receipt_number, amount_paid FROM payments WHERE bill_id = ?", (int(bill_id),))
            existing_payment = cur.fetchone()
            if existing_payment:
                raise ValueError(f"Bill #{bill['bill_number']} has already been paid (Receipt: {existing_payment['receipt_number']}).")

            total_due = round(float(bill["total_amount"]), 2)

            if amount_paid is None:
                payment_amount = total_due
            else:
                try:
                    payment_amount = round(float(amount_paid), 2)
                except (ValueError, TypeError):
                    raise ValueError("Payment amount must be a valid number.")

            if payment_amount <= 0:
                raise ValueError("Payment amount must be greater than zero.")

            if payment_amount != total_due:
                raise ValueError(f"Payment amount (₹{payment_amount:.2f}) does not match outstanding bill amount (₹{total_due:.2f}).")

            now_utc = get_utc_now()
            payment_time_utc = now_utc.strftime("%Y-%m-%d %H:%M:%S")
            trans_code = f"TXN-{now_utc.strftime('%Y%m%d%H%M%S')}-{random.randint(1000, 9999)}"
            receipt_no = f"RCPT-{bill['bill_id']:04d}-{random.randint(100, 999)}"

            cur.execute("""
                INSERT INTO payments (bill_id, consumer_id, receipt_number, transaction_ref, amount_paid, payment_method, payment_date)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (int(bill_id), bill["consumer_id"], receipt_no, trans_code, payment_amount, payment_method, payment_time_utc))

            # Atomic status update
            cur.execute("UPDATE bills SET status = 'PAID' WHERE bill_id = ?", (int(bill_id),))

            return {
                "receipt_number": receipt_no,
                "transaction_ref": trans_code,
                "amount": payment_amount,
                "payment_date_utc": payment_time_utc,
                "payment_date_ist": utc_to_ist_str(payment_time_utc)
            }
    finally:
        conn.close()

def get_payments_for_consumer(consumer_id):
    conn = get_db()
    try:
        return conn.execute("""
            SELECT p.*, b.bill_number, b.billing_month, b.units_consumed
            FROM payments p
            JOIN bills b ON p.bill_id = b.bill_id
            WHERE p.consumer_id = ?
            ORDER BY p.payment_id DESC
        """, (int(consumer_id),)).fetchall()
    finally:
        conn.close()

# ----------------- COMPLAINTS / TICKETS -----------------
def add_complaint(consumer_id, category, description):
    valid_categories = {'Low Pressure', 'No Water', 'Contaminated / Murky Water', 'Pipeline Leakage', 'Billing Discrepancy', 'Meter Fault'}
    if category not in valid_categories:
        raise ValueError(f"Invalid category '{category}'.")
    if not description or not description.strip():
        raise ValueError("Complaint description cannot be empty.")

    conn = get_db()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute("SELECT consumer_id FROM consumers WHERE consumer_id = ?", (int(consumer_id),))
            if not cur.fetchone():
                raise ValueError("Consumer not found.")

            cur.execute("""
                INSERT INTO complaints (consumer_id, category, description, status, created_at)
                VALUES (?, ?, ?, 'Pending', ?)
            """, (int(consumer_id), category, description.strip(), get_utc_now_str()))
            return cur.lastrowid
    finally:
        conn.close()

def get_complaints_by_consumer(consumer_id):
    conn = get_db()
    try:
        return conn.execute("""
            SELECT * FROM complaints 
            WHERE consumer_id = ? 
            ORDER BY complaint_id DESC
        """, (int(consumer_id),)).fetchall()
    finally:
        conn.close()

def get_all_complaints():
    conn = get_db()
    try:
        return conn.execute("""
            SELECT cm.*, c.account_number, u.full_name as consumer_name, z.zone_name
            FROM complaints cm
            JOIN consumers c ON cm.consumer_id = c.consumer_id
            JOIN users u ON c.user_id = u.user_id
            JOIN supply_zones z ON c.zone_id = z.zone_id
            ORDER BY CASE cm.status WHEN 'Pending' THEN 1 WHEN 'In Progress' THEN 2 ELSE 3 END, cm.complaint_id DESC
        """).fetchall()
    finally:
        conn.close()

def update_complaint_status(complaint_id, status, admin_response=None):
    if status not in ('Pending', 'In Progress', 'Resolved'):
        raise ValueError("Status must be 'Pending', 'In Progress', or 'Resolved'.")

    conn = get_db()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute("SELECT complaint_id FROM complaints WHERE complaint_id = ?", (int(complaint_id),))
            if not cur.fetchone():
                raise ValueError("Complaint ticket not found.")

            resolved_at = get_utc_now_str() if status == "Resolved" else None
            cur.execute("""
                UPDATE complaints
                SET status = ?, admin_response = ?, resolved_at = COALESCE(?, resolved_at)
                WHERE complaint_id = ?
            """, (status, admin_response.strip() if admin_response else None, resolved_at, int(complaint_id)))
    finally:
        conn.close()

# ----------------- OVERDUE STATUS SYNCHRONIZATION -----------------
def update_overdue_bills():
    """
    Synchronizes status of past-due unpaid bills to 'OVERDUE'.
    Executed safely at database level based on current calendar date in Asia/Kolkata.
    """
    today_ist = get_ist_now().strftime("%Y-%m-%d")
    conn = get_db()
    try:
        with conn:
            conn.execute("""
                UPDATE bills
                SET status = 'OVERDUE'
                WHERE status = 'UNPAID' AND due_date < ?
            """, (today_ist,))
    finally:
        conn.close()

# ----------------- DASHBOARD ANALYTICS -----------------
def get_admin_dashboard_metrics():
    update_overdue_bills()
    conn = get_db()
    try:
        total_consumers = conn.execute("SELECT COUNT(*) FROM consumers").fetchone()[0]
        total_zones = conn.execute("SELECT COUNT(*) FROM supply_zones").fetchone()[0]

        billing_stats = conn.execute("""
            SELECT 
                COALESCE(SUM(CASE WHEN status = 'PAID' THEN total_amount ELSE 0 END), 0) AS total_revenue,
                COALESCE(SUM(CASE WHEN status IN ('UNPAID', 'OVERDUE') THEN total_amount ELSE 0 END), 0) AS pending_revenue,
                COUNT(CASE WHEN status IN ('UNPAID', 'OVERDUE') THEN 1 END) AS unpaid_bills_count,
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
    finally:
        conn.close()

def get_consumer_dashboard_metrics(consumer_id):
    update_overdue_bills()
    conn = get_db()
    try:
        fin = conn.execute("""
            SELECT 
                COALESCE(SUM(CASE WHEN status IN ('UNPAID', 'OVERDUE') THEN total_amount ELSE 0 END), 0) as pending_total,
                COUNT(CASE WHEN status IN ('UNPAID', 'OVERDUE') THEN 1 END) as pending_count,
                COALESCE(SUM(CASE WHEN status = 'PAID' THEN total_amount ELSE 0 END), 0) as paid_total
            FROM bills
            WHERE consumer_id = ?
        """, (int(consumer_id),)).fetchone()

        latest_unpaid = conn.execute("""
            SELECT * FROM bills 
            WHERE consumer_id = ? AND status IN ('UNPAID', 'OVERDUE')
            ORDER BY due_date ASC LIMIT 1
        """, (int(consumer_id),)).fetchone()

        usage_history = [dict(r) for r in conn.execute("""
            SELECT billing_month, units_consumed, total_amount, status
            FROM bills
            WHERE consumer_id = ?
            ORDER BY bill_id ASC LIMIT 6
        """, (int(consumer_id),)).fetchall()]

        consumer_info = conn.execute("""
            SELECT c.*, u.full_name, u.email, u.phone,
                   z.zone_name, z.ward_area, z.reservoir_name, z.reservoir_level_pct,
                   z.water_pressure_psi, z.supply_status, z.morning_slot, z.evening_slot,
                   z.purity_ph, z.tds_ppm
            FROM consumers c
            JOIN users u ON c.user_id = u.user_id
            JOIN supply_zones z ON c.zone_id = z.zone_id
            WHERE c.consumer_id = ?
        """, (int(consumer_id),)).fetchone()

        return {
            "pending_total": round(fin["pending_total"], 2),
            "pending_count": fin["pending_count"],
            "paid_total": round(fin["paid_total"], 2),
            "latest_unpaid": latest_unpaid,
            "usage_history": usage_history,
            "consumer": consumer_info
        }
    finally:
        conn.close()

# ----------------- DATABASE HEALTH CHECK -----------------
def check_database_health():
    """
    Performs a thorough, read-only health diagnostic of the database.
    Verifies file presence, connection usability, foreign keys, integrity, and all 7 tables.
    """
    db_file = get_db_path()
    if not os.path.exists(db_file):
        raise FileNotFoundError(f"Database file is missing at: {db_file}")

    file_size_bytes = os.path.getsize(db_file)
    conn = get_db()
    try:
        # Check foreign keys pragma
        fk_status = conn.execute("PRAGMA foreign_keys;").fetchone()[0]

        # Check integrity
        integrity_res = conn.execute("PRAGMA integrity_check;").fetchall()
        integrity_ok = len(integrity_res) > 0 and integrity_res[0][0] == "ok"

        # Check foreign keys integrity
        fk_violations = conn.execute("PRAGMA foreign_key_check;").fetchall()

        # Check all required tables
        expected_tables = ["users", "supply_zones", "consumers", "bills", "payments", "supply_alerts", "complaints"]
        table_counts = {}
        for tbl in expected_tables:
            count = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
            table_counts[tbl] = count

        return {
            "status": "healthy",
            "database_file": db_file,
            "file_size_bytes": file_size_bytes,
            "foreign_keys_enabled": bool(fk_status),
            "integrity_ok": integrity_ok,
            "fk_violations_count": len(fk_violations),
            "table_counts": table_counts,
            "timestamp": get_utc_now().isoformat(),
            "timezone": "UTC",
            "server_time_ist": get_ist_now().strftime("%Y-%m-%d %H:%M:%S")
        }
    finally:
        conn.close()
