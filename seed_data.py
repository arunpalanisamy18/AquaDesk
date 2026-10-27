import sqlite3
import os
from database import init_db, get_db, create_user, calculate_water_tariff
from werkzeug.security import generate_password_hash

def seed():
    print("Initializing Database schema...")
    init_db()

    conn = get_db()
    cur = conn.cursor()

    # Check if already seeded
    cur.execute("SELECT COUNT(*) FROM users")
    if cur.fetchone()[0] > 0:
        print("Database already contains data. Skipping re-seed.")
        conn.close()
        return

    print("Seeding initial administrative and supply data...")

    # 1. Admin User
    admin_hash = generate_password_hash("admin123")
    cur.execute("""
        INSERT INTO users (username, password, role, full_name, email, phone)
        VALUES ('admin', ?, 'admin', 'Municipal Water Superintendent', 'admin@waterboard.gov.in', '+91 98765 00001')
    """, (admin_hash,))

    # 2. Supply Zones
    zones = [
        ("North Zone - Green Valley", "Ward 12 (North)", "Green Valley Elevated Reservoir", 86.5, 48.2, 7.3, 165, "ACTIVE", "06:00 AM - 09:00 AM", "06:00 PM - 08:30 PM"),
        ("South Zone - Hilltop", "Ward 07 (South)", "Hilltop Main Storage Tank", 68.0, 42.5, 7.1, 190, "SCHEDULED", "05:30 AM - 08:30 AM", "05:30 PM - 08:00 PM"),
        ("East Commercial District", "Ward 03 (East)", "East District Booster Reservoir", 92.0, 54.0, 7.4, 150, "ACTIVE", "07:00 AM - 11:00 AM", "06:00 PM - 09:30 PM"),
        ("West Industrial Park", "Ward 19 (West)", "Riverview Industrial Tank", 45.0, 36.8, 6.9, 210, "MAINTENANCE", "08:00 AM - 12:00 PM", "04:00 PM - 07:00 PM")
    ]

    cur.executemany("""
        INSERT INTO supply_zones (
            zone_name, ward_area, reservoir_name, reservoir_level_pct,
            water_pressure_psi, purity_ph, tds_ppm, supply_status, morning_slot, evening_slot
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, zones)

    # 3. Consumer Users & Profiles
    consumers_data = [
        {
            "username": "rahul_sharma",
            "password": generate_password_hash("password123"),
            "full_name": "Rahul Sharma",
            "email": "rahul.sharma@example.com",
            "phone": "+91 98111 22334",
            "zone_id": 1,
            "account_number": "WTR-1001",
            "connection_type": "Residential",
            "meter_number": "MTR-7821",
            "address": "Flat 402, Royal Residency, North Lake Road",
            "last_reading": 142.5
        },
        {
            "username": "priya_patel",
            "password": generate_password_hash("password123"),
            "full_name": "Priya Patel",
            "email": "priya.patel@example.com",
            "phone": "+91 98222 33445",
            "zone_id": 2,
            "account_number": "WTR-1002",
            "connection_type": "Residential",
            "meter_number": "MTR-8302",
            "address": "Bungalow 14, Rosewood Gardens, South Heights",
            "last_reading": 98.0
        },
        {
            "username": "apex_hospital",
            "password": generate_password_hash("password123"),
            "full_name": "Apex Multispecialty Hospital",
            "email": "billing@apexhospital.org",
            "phone": "+91 98333 44556",
            "zone_id": 3,
            "account_number": "WTR-2001",
            "connection_type": "Commercial",
            "meter_number": "MTR-9411",
            "address": "Plot 88, Commercial Express Highway",
            "last_reading": 340.0
        },
        {
            "username": "sun_textiles",
            "password": generate_password_hash("password123"),
            "full_name": "Sun Textiles & Garments Ltd",
            "email": "operations@suntextiles.com",
            "phone": "+91 98444 55667",
            "zone_id": 4,
            "account_number": "WTR-3001",
            "connection_type": "Industrial",
            "meter_number": "MTR-5120",
            "address": "Shed 12B, West Phase-2 Industrial Zone",
            "last_reading": 820.0
        }
    ]

    consumer_ids = []
    for c in consumers_data:
        cur.execute("""
            INSERT INTO users (username, password, role, full_name, email, phone)
            VALUES (?, ?, 'consumer', ?, ?, ?)
        """, (c["username"], c["password"], c["full_name"], c["email"], c["phone"]))
        u_id = cur.lastrowid

        cur.execute("""
            INSERT INTO consumers (
                user_id, account_number, zone_id, connection_type,
                meter_number, installation_date, address, last_meter_reading, status
            ) VALUES (?, ?, ?, ?, ?, '2025-01-15', ?, ?, 'Active')
        """, (u_id, c["account_number"], c["zone_id"], c["connection_type"], c["meter_number"], c["address"], c["last_reading"]))
        consumer_ids.append(cur.lastrowid)

    # 4. Historical and Current Bills
    # Consumer 1 (Rahul Sharma):
    # - Aug 2026: 18 kL (Paid)
    # - Sep 2026: 22 kL (Paid)
    # - Oct 2026: 24 kL (UNPAID - ready for demo payment)
    bills_seed = [
        # Rahul (ID: 1)
        (1, "BILL-202608-0001", "August 2026", "2026-08-01", "2026-08-20", 78.0, 96.0, 18.0, "PAID"),
        (1, "BILL-202609-0002", "September 2026", "2026-09-01", "2026-09-20", 96.0, 118.0, 22.0, "PAID"),
        (1, "BILL-202610-0003", "October 2026", "2026-10-01", "2026-11-05", 118.0, 142.5, 24.5, "UNPAID"),

        # Priya (ID: 2)
        (2, "BILL-202609-0004", "September 2026", "2026-09-05", "2026-09-25", 65.0, 80.0, 15.0, "PAID"),
        (2, "BILL-202610-0005", "October 2026", "2026-10-05", "2026-11-08", 80.0, 98.0, 18.0, "UNPAID"),

        # Apex Hospital (ID: 3, Commercial)
        (3, "BILL-202609-0006", "September 2026", "2026-09-01", "2026-09-20", 250.0, 295.0, 45.0, "PAID"),
        (3, "BILL-202610-0007", "October 2026", "2026-10-01", "2026-11-05", 295.0, 340.0, 45.0, "PAID"),

        # Sun Textiles (ID: 4, Industrial)
        (4, "BILL-202610-0008", "October 2026", "2026-10-02", "2026-11-10", 720.0, 820.0, 100.0, "UNPAID")
    ]

    # Map consumer ID to connection type
    c_types = {1: "Residential", 2: "Residential", 3: "Commercial", 4: "Industrial"}

    for b in bills_seed:
        cid, bnum, bmonth, bdate, ddate, prev_r, curr_r, units, status = b
        tariff = calculate_water_tariff(c_types[cid], units)
        
        cur.execute("""
            INSERT INTO bills (
                bill_number, consumer_id, billing_month, billing_date, due_date,
                prev_reading, curr_reading, units_consumed,
                base_charge, consumption_charge, tax_surcharge, total_amount,
                status, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Regular monthly utility meter reading')
        """, (
            bnum, cid, bmonth, bdate, ddate, prev_r, curr_r, units,
            tariff["base_charge"], tariff["consumption_charge"], tariff["tax_surcharge"], tariff["total_amount"],
            status
        ))
        bill_id = cur.lastrowid

        # Insert payment record for PAID bills
        if status == "PAID":
            rcpt = f"RCPT-{bill_id:04d}-542"
            tx = f"TXN-2026-CONF-{bill_id:04d}"
            cur.execute("""
                INSERT INTO payments (bill_id, consumer_id, receipt_number, transaction_ref, amount_paid, payment_method, payment_date)
                VALUES (?, ?, ?, ?, ?, 'UPI', DATETIME(? || ' 11:30:00'))
            """, (bill_id, cid, rcpt, tx, tariff["total_amount"], bdate))

    # 5. Supply Alerts
    alerts = [
        (1, "Scheduled Maintenance Pipeline Flush", "North Zone main booster line will undergo chlorination flush on Thursday between 1:00 PM and 3:30 PM. No morning/evening disruption.", "Info", 1),
        (4, "Low Pressure Advisory - West Phase-2", "Valve replacement underway at Riverview feeder pipeline. Expect lower pressure during evening supply slot.", "Warning", 1),
        (None, "Monsoon Reservoir Safety Update", "All city reservoirs are at optimal capacity (>75%). Safe potable drinking water is fully assured across all municipal wards.", "Info", 1)
    ]

    cur.executemany("""
        INSERT INTO supply_alerts (zone_id, title, message, severity, is_active)
        VALUES (?, ?, ?, ?, ?)
    """, alerts)

    # 6. Sample Complaints
    complaints = [
        (1, "Low Pressure", "Water pressure in morning supply slot (7:00 AM) has been lower than usual on top floor.", "In Progress", "Municipal field team dispatched to inspect feeder valve."),
        (2, "Meter Fault", "Display glass on the external water meter is blurred due to condensation.", "Pending", None)
    ]

    cur.executemany("""
        INSERT INTO complaints (consumer_id, category, description, status, admin_response)
        VALUES (?, ?, ?, ?, ?)
    """, complaints)

    conn.commit()
    conn.close()
    print("Database seeded successfully with realistic test records!")

if __name__ == "__main__":
    seed()
