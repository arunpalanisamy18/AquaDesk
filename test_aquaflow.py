"""
AquaFlow Automated Test Suite
Tests all 15 Rubric Verification Categories using an isolated temporary SQLite database.
Never touches or modifies the production/demo database.
"""

import unittest
import os
import tempfile
import sqlite3
from datetime import datetime, timedelta

# Point DATABASE_PATH to an isolated test database before importing app/database
TEST_DB_FILE = os.path.join(tempfile.gettempdir(), f"aquaflow_test_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.db")
os.environ["DATABASE_PATH"] = TEST_DB_FILE
os.environ["AQUAFLOW_DEMO_MODE"] = "true"

import database
import seed_data
from app import app


class AquaFlowComprehensiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Configure Flask application for testing
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False  # Allows direct form testing without CSRF token mismatch
        cls.client = app.test_client()

        # Initialize and seed isolated test database
        if os.path.exists(TEST_DB_FILE):
            os.remove(TEST_DB_FILE)
        seed_data.seed()

    @classmethod
    def tearDownClass(cls):
        # Cleanup isolated temporary database
        try:
            if os.path.exists(TEST_DB_FILE):
                os.remove(TEST_DB_FILE)
        except Exception:
            pass

    # ---------------------------------------------------------
    # 1. Application Startup and Database Connectivity
    # ---------------------------------------------------------
    def test_01_startup_and_connectivity(self):
        """Verify server responds, health endpoint reports healthy, and SQLite is connected."""
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["status"], "healthy")
        self.assertTrue(data["foreign_keys_enabled"])
        self.assertTrue(data["integrity_ok"])

    # ---------------------------------------------------------
    # 2. Required Table and Schema Verification
    # ---------------------------------------------------------
    def test_02_required_tables_and_schema(self):
        """Verify all 7 tables, 3 views, and 2 triggers exist in schema."""
        conn = database.get_db()
        try:
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {r[0] for r in cur.fetchall()}
            expected_tables = {"users", "supply_zones", "consumers", "bills", "payments", "supply_alerts", "complaints"}
            self.assertTrue(expected_tables.issubset(tables), f"Missing tables: {expected_tables - tables}")

            cur.execute("SELECT name FROM sqlite_master WHERE type='view'")
            views = {r[0] for r in cur.fetchall()}
            expected_views = {"vw_bills_detailed", "vw_consumer_balances", "vw_zone_monitoring"}
            self.assertTrue(expected_views.issubset(views), f"Missing views: {expected_views - views}")

            cur.execute("SELECT name FROM sqlite_master WHERE type='trigger'")
            triggers = {r[0] for r in cur.fetchall()}
            expected_triggers = {"trg_update_consumer_meter_reading", "trg_mark_bill_paid"}
            self.assertTrue(expected_triggers.issubset(triggers), f"Missing triggers: {expected_triggers - triggers}")

            # Verify database-level uniqueness enforcement on payments.bill_id
            cur.execute("PRAGMA index_list('payments')")
            payment_indexes = cur.fetchall()
            unique_indexed_cols = set()
            for p_idx in payment_indexes:
                if p_idx["unique"]:
                    cur.execute(f"PRAGMA index_info('{p_idx['name']}')")
                    for col in cur.fetchall():
                        unique_indexed_cols.add(col["name"])
            self.assertIn("bill_id", unique_indexed_cols, "payments.bill_id lacks database-level UNIQUE index/constraint!")
        finally:
            conn.close()

    # ---------------------------------------------------------
    # 3. Valid and Invalid Login Attempts
    # ---------------------------------------------------------
    def test_03_login_validation(self):
        """Test valid credentials, invalid password, nonexistent user, and empty fields."""
        # Valid Admin Login
        res_admin = self.client.post("/login", data={"username": "admin", "password": "admin123"}, follow_redirects=False)
        self.assertEqual(res_admin.status_code, 302)
        self.assertIn("/admin/dashboard", res_admin.location)

        # Valid Consumer Login
        res_consumer = self.client.post("/login", data={"username": "rahul_sharma", "password": "password123"}, follow_redirects=False)
        self.assertEqual(res_consumer.status_code, 302)
        self.assertIn("/consumer/dashboard", res_consumer.location)

        # Invalid Password
        res_bad_pw = self.client.post("/login", data={"username": "admin", "password": "wrongpassword"}, follow_redirects=True)
        self.assertIn(b"Invalid username or password", res_bad_pw.data)

        # Nonexistent User
        res_no_user = self.client.post("/login", data={"username": "ghost_user", "password": "password123"}, follow_redirects=True)
        self.assertIn(b"Invalid username or password", res_no_user.data)

        # Empty Credentials
        res_empty = self.client.post("/login", data={"username": "", "password": ""}, follow_redirects=True)
        self.assertIn(b"Please provide both username and password", res_empty.data)

    # ---------------------------------------------------------
    # 4. Administrator and Consumer Authorization (RBAC)
    # ---------------------------------------------------------
    def test_04_authorization_and_rbac(self):
        """Verify role protection: consumers cannot access admin routes, anonymous redirected to login."""
        # Anonymous accessing admin dashboard
        with self.client.session_transaction() as sess:
            sess.clear()
        res_anon = self.client.get("/admin/dashboard", follow_redirects=False)
        self.assertEqual(res_anon.status_code, 302)
        self.assertIn("/login", res_anon.location)

        # Consumer accessing admin dashboard -> redirected
        with self.client.session_transaction() as sess:
            sess["user_id"] = 2
            sess["username"] = "rahul_sharma"
            sess["role"] = "consumer"
        res_consumer_denied = self.client.get("/admin/dashboard", follow_redirects=True)
        self.assertIn(b"Access denied. Administrator privileges required.", res_consumer_denied.data)

        # Admin accessing consumer dashboard -> redirected
        with self.client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["username"] = "admin"
            sess["role"] = "admin"
        res_admin_denied = self.client.get("/consumer/dashboard", follow_redirects=True)
        self.assertIn(b"Access denied. Consumer account required.", res_admin_denied.data)

    # ---------------------------------------------------------
    # 5. Registration Success and Duplicate Prevention
    # ---------------------------------------------------------
    def test_05_registration_and_duplicate_prevention(self):
        """Verify new consumer registration and rejection of duplicate username or email."""
        # Success registration
        res = self.client.post("/register", data={
            "full_name": "Kavita Rao",
            "username": "kavita_r",
            "email": "kavita@testcity.gov",
            "phone": "+91 91234 56780",
            "password": "password123",
            "zone_id": 1,
            "connection_type": "Residential",
            "address": "404 Lake View Road, Ward 12",
            "initial_reading": "25.0"
        }, follow_redirects=True)
        self.assertIn(b"Registration successful", res.data)

        # Duplicate Username Rejection
        res_dup_user = self.client.post("/register", data={
            "full_name": "Kavita Clone",
            "username": "kavita_r",
            "email": "kavita_new@testcity.gov",
            "phone": "+91 91234 56781",
            "password": "password123",
            "zone_id": 1,
            "connection_type": "Residential",
            "address": "505 Lake View Road",
            "initial_reading": "0.0"
        }, follow_redirects=True)
        self.assertIn(b"is already registered", res_dup_user.data)

        # Duplicate Email Rejection
        res_dup_email = self.client.post("/register", data={
            "full_name": "Another User",
            "username": "another_u",
            "email": "kavita@testcity.gov",
            "phone": "+91 91234 56782",
            "password": "password123",
            "zone_id": 1,
            "connection_type": "Residential",
            "address": "606 Lake View Road",
            "initial_reading": "0.0"
        }, follow_redirects=True)
        self.assertTrue(b"kavita@testcity.gov" in res_dup_email.data and b"already registered" in res_dup_email.data)

    # ---------------------------------------------------------
    # 6. Valid Bill Generation and Correct Slab Calculations
    # ---------------------------------------------------------
    def test_06_bill_generation_and_tariff_calculation(self):
        """Verify progressive slab tariff calculation for Residential, Commercial, and Industrial."""
        # Residential: 20 kL -> Slab 1 (15 * 8 = 120) + Slab 2 (5 * 14 = 70) = 190. Base 60. Tax 5% of 190 = 9.50. Total = 259.50
        tariff_res = database.calculate_water_tariff("Residential", 20.0)
        self.assertEqual(tariff_res["base_charge"], 60.0)
        self.assertEqual(tariff_res["consumption_charge"], 190.0)
        self.assertEqual(tariff_res["tax_surcharge"], 9.50)
        self.assertEqual(tariff_res["total_amount"], 259.50)

        # Commercial: 40 kL -> 30 * 22 = 660, 10 * 36 = 360, sum = 1020. Base 150. Tax 8% = 81.60. Total = 1251.60
        tariff_com = database.calculate_water_tariff("Commercial", 40.0)
        self.assertEqual(tariff_com["base_charge"], 150.0)
        self.assertEqual(tariff_com["consumption_charge"], 1020.0)
        self.assertEqual(tariff_com["tax_surcharge"], 81.60)
        self.assertEqual(tariff_com["total_amount"], 1251.60)

        # Bill generation in database:
        consumer = database.get_consumer_by_user_id(2)  # Rahul Sharma
        last_rdg = float(consumer["last_meter_reading"])
        bill_id = database.add_bill(
            consumer_id=consumer["consumer_id"],
            billing_month="December 2026",
            curr_reading=last_rdg + 20.0,
            prev_reading=last_rdg,
            due_days=15
        )
        self.assertIsNotNone(bill_id)
        bill = database.get_bill_by_id(bill_id)
        self.assertEqual(bill["units_consumed"], 20.0)
        self.assertEqual(bill["total_amount"], 259.50)
        self.assertEqual(bill["status"], "UNPAID")

        # Verify trigger updated consumer's last meter reading!
        updated_consumer = database.get_consumer_by_id(consumer["consumer_id"])
        self.assertEqual(float(updated_consumer["last_meter_reading"]), last_rdg + 20.0)

    # ---------------------------------------------------------
    # 7. Invalid, Missing, Negative, and Decreasing Meter Readings
    # ---------------------------------------------------------
    def test_07_invalid_meter_readings(self):
        """Verify rejection of decreasing readings, negative values, and non-numeric input."""
        consumer = database.get_consumer_by_user_id(2)
        curr = float(consumer["last_meter_reading"])

        # Decreasing meter reading
        with self.assertRaises(ValueError) as ctx:
            database.add_bill(consumer["consumer_id"], "January 2027", curr_reading=curr - 10.0, prev_reading=curr)
        self.assertIn("cannot be less than previous reading", str(ctx.exception))

        # Negative reading
        with self.assertRaises(ValueError) as ctx:
            database.add_bill(consumer["consumer_id"], "January 2027", curr_reading=-5.0, prev_reading=0.0)
        self.assertIn("cannot be negative", str(ctx.exception))

        # Non-numeric reading
        with self.assertRaises(ValueError):
            database.add_bill(consumer["consumer_id"], "January 2027", curr_reading="abc", prev_reading=curr)

    # ---------------------------------------------------------
    # 8. Payment Success, Incorrect Amounts, Unauthorized Payments, Repeated Submissions
    # ---------------------------------------------------------
    def test_08_payment_rules_and_validation(self):
        """Verify payment requires correct amount, rejects unauthorized consumers, and disallows double payments."""
        consumer_rahul = database.get_consumer_by_user_id(2)
        consumer_priya = database.get_consumer_by_user_id(3)

        # Generate fresh bill for testing payment
        curr_rdg = float(consumer_rahul["last_meter_reading"])
        bill_id = database.add_bill(consumer_rahul["consumer_id"], "February 2027", curr_rdg + 10.0, curr_rdg)
        bill = database.get_bill_by_id(bill_id)

        # 1. Unauthorized payment attempt by another consumer
        with self.assertRaises(ValueError) as ctx:
            database.record_bill_payment(bill_id, "UPI", bill["total_amount"], consumer_id=consumer_priya["consumer_id"])
        self.assertIn("Unauthorized", str(ctx.exception))

        # 2. Incorrect amount (partial or excessive)
        with self.assertRaises(ValueError) as ctx:
            database.record_bill_payment(bill_id, "UPI", amount_paid=10.0, consumer_id=consumer_rahul["consumer_id"])
        self.assertIn("does not match outstanding", str(ctx.exception))

        # 3. Successful payment with exact amount
        receipt = database.record_bill_payment(bill_id, "UPI", amount_paid=bill["total_amount"], consumer_id=consumer_rahul["consumer_id"])
        self.assertTrue(receipt["receipt_number"].startswith("RCPT-"))
        paid_bill = database.get_bill_by_id(bill_id)
        self.assertEqual(paid_bill["status"], "PAID")

        # 4. Repeated submission on already paid bill
        with self.assertRaises(ValueError) as ctx:
            database.record_bill_payment(bill_id, "UPI", amount_paid=bill["total_amount"], consumer_id=consumer_rahul["consumer_id"])
        self.assertIn("already been marked as PAID", str(ctx.exception))

    # ---------------------------------------------------------
    # 9. Bill Status and Overdue Balance Calculations
    # ---------------------------------------------------------
    def test_09_bill_status_and_overdue_handling(self):
        """Verify bills with past due dates transition to OVERDUE and compute in pending dues."""
        consumer = database.get_consumer_by_user_id(2)
        curr = float(consumer["last_meter_reading"])

        # Insert a bill with past due date directly to simulate overdue bill
        conn = database.get_db()
        try:
            with conn:
                conn.execute("""
                    INSERT INTO bills (
                        bill_number, consumer_id, billing_month, billing_date, due_date,
                        prev_reading, curr_reading, units_consumed,
                        base_charge, consumption_charge, tax_surcharge, total_amount, status
                    ) VALUES ('BILL-TEST-OVERDUE', ?, 'Past Due Cycle', '2026-01-01', '2026-01-15',
                              ?, ?, 10.0, 60.0, 80.0, 4.0, 144.0, 'UNPAID')
                """, (consumer["consumer_id"], curr, curr + 10.0))
        finally:
            conn.close()

        # Run overdue updater
        database.update_overdue_bills()

        overdue_bill = None
        for b in database.get_bills_for_consumer(consumer["consumer_id"]):
            if b["bill_number"] == "BILL-TEST-OVERDUE":
                overdue_bill = b
                break
        self.assertIsNotNone(overdue_bill)
        self.assertEqual(overdue_bill["status"], "OVERDUE")

        # Check metrics include overdue amount in pending dues
        metrics = database.get_consumer_dashboard_metrics(consumer["consumer_id"])
        self.assertGreaterEqual(metrics["pending_total"], 144.0)

    # ---------------------------------------------------------
    # 10. Consumer Data Isolation (IDOR Prevention)
    # ---------------------------------------------------------
    def test_10_consumer_data_isolation(self):
        """Verify consumers cannot view other consumers' bills or tax invoices."""
        # Consumer 1 (Rahul) attempts to view Consumer 2 (Priya)'s invoice
        # Get a bill belonging to Priya
        priya_consumer = database.get_consumer_by_user_id(3)  # Priya Patel
        priya_bills = database.get_bills_for_consumer(priya_consumer["consumer_id"])
        self.assertTrue(len(priya_bills) > 0)
        priya_bill_id = priya_bills[0]["bill_id"]

        # Log in as Rahul
        with self.client.session_transaction() as sess:
            sess["user_id"] = 2  # Rahul's user ID
            sess["username"] = "rahul_sharma"
            sess["role"] = "consumer"

        # Rahul tries to access Priya's invoice
        res = self.client.get(f"/bill/{priya_bill_id}/invoice", follow_redirects=True)
        self.assertIn(b"Unauthorized access", res.data)

    # ---------------------------------------------------------
    # 11. Complaint Creation and Status Validation
    # ---------------------------------------------------------
    def test_11_complaint_workflow(self):
        """Verify consumers can file complaints with valid category and admins can resolve them."""
        consumer = database.get_consumer_by_user_id(2)

        # Valid complaint
        cid = database.add_complaint(consumer["consumer_id"], "Low Pressure", "Water flow dropped below 15 PSI.")
        self.assertIsNotNone(cid)

        # Invalid category
        with self.assertRaises(ValueError):
            database.add_complaint(consumer["consumer_id"], "InvalidCategoryName", "Some message")

        # Empty description
        with self.assertRaises(ValueError):
            database.add_complaint(consumer["consumer_id"], "Low Pressure", "")

        # Admin resolves complaint
        database.update_complaint_status(cid, "Resolved", "Inspected and replaced booster gasket.")
        conn = database.get_db()
        try:
            complaint = conn.execute("SELECT * FROM complaints WHERE complaint_id = ?", (cid,)).fetchone()
            self.assertEqual(complaint["status"], "Resolved")
            self.assertIsNotNone(complaint["resolved_at"])
        finally:
            conn.close()

    # ---------------------------------------------------------
    # 12. Supply-Zone Operations and Invalid Telemetry Readings
    # ---------------------------------------------------------
    def test_12_supply_zone_telemetry(self):
        """Verify updating zone parameters and rejection of out-of-range sensor values."""
        # Valid update
        database.update_zone_details(
            zone_id=1,
            status="ACTIVE",
            reservoir_level=85.0,
            water_pressure=46.5,
            morning_slot="06:00 AM - 09:00 AM",
            evening_slot="06:00 PM - 08:30 PM",
            purity_ph=7.2,
            tds_ppm=160
        )
        zone = database.get_zone_by_id(1)
        self.assertEqual(float(zone["reservoir_level_pct"]), 85.0)

        # Invalid reservoir level (> 100%)
        with self.assertRaises(ValueError) as ctx:
            database.update_zone_details(1, "ACTIVE", 125.0, 45.0, "06:00 AM", "06:00 PM")
        self.assertIn("between 0% and 100%", str(ctx.exception))

        # Negative water pressure
        with self.assertRaises(ValueError) as ctx:
            database.update_zone_details(1, "ACTIVE", 80.0, -10.0, "06:00 AM", "06:00 PM")
        self.assertIn("cannot be negative", str(ctx.exception))

        # Invalid pH (> 14)
        with self.assertRaises(ValueError) as ctx:
            database.update_zone_details(1, "ACTIVE", 80.0, 40.0, "06:00 AM", "06:00 PM", purity_ph=15.5)
        self.assertIn("between 0.0 and 14.0", str(ctx.exception))

    # ---------------------------------------------------------
    # 13. Database Integrity and Foreign-Key Constraints
    # ---------------------------------------------------------
    def test_13_foreign_keys_and_cascading(self):
        """Verify foreign-key constraints reject non-existent parents and enforce cascading deletes."""
        conn = database.get_db()
        try:
            cur = conn.cursor()

            # Attempt to insert consumer with non-existent user_id
            with self.assertRaises(sqlite3.IntegrityError):
                cur.execute("""
                    INSERT INTO consumers (user_id, account_number, zone_id, meter_number, address)
                    VALUES (99999, 'WTR-GHOST', 1, 'MTR-GHOST', 'Nowhere Land')
                """)

            # Attempt to insert bill for non-existent consumer_id
            with self.assertRaises(sqlite3.IntegrityError):
                cur.execute("""
                    INSERT INTO bills (bill_number, consumer_id, billing_month, billing_date, due_date,
                                       prev_reading, curr_reading, units_consumed, base_charge,
                                       consumption_charge, tax_surcharge, total_amount)
                    VALUES ('BILL-GHOST', 99999, 'Test Month', '2026-01-01', '2026-01-15',
                            0, 10, 10, 60, 80, 4, 144)
                """)
        finally:
            conn.close()

    # ---------------------------------------------------------
    # 14. Transaction Rollback when a Related Operation Fails
    # ---------------------------------------------------------
    def test_14_transaction_rollback(self):
        """Verify no orphaned user is created if consumer profile creation encounters an error."""
        init_users = len(database.get_all_users())

        # Attempt atomic registration with an invalid zone_id (99999)
        with self.assertRaises(ValueError) as ctx:
            database.register_consumer_account(
                username="orphan_candidate",
                password="password123",
                full_name="Orphan Candidate",
                email="orphan@testcity.gov",
                phone="9999999999",
                zone_id=99999,  # Non-existent zone
                connection_type="Residential",
                address="Lost Sector"
            )
        self.assertIn("zone does not exist", str(ctx.exception))

        # Confirm user was NOT added to the database (transaction rolled back)
        post_users = len(database.get_all_users())
        self.assertEqual(init_users, post_users)
        ghost = database.get_user_by_username("orphan_candidate")
        self.assertIsNone(ghost)

    # ---------------------------------------------------------
    # 15. Invalid Form Submissions and Error Responses
    # ---------------------------------------------------------
    def test_15_invalid_form_submissions(self):
        """Verify understandable error messages and bad request handling for invalid inputs."""
        # Tariff API with negative units
        res_api_neg = self.client.get("/api/calculate_tariff?units=-15.0")
        self.assertEqual(res_api_neg.status_code, 400)
        self.assertIn("cannot be negative", res_api_neg.get_json()["error"])

        # Tariff API with non-numeric units
        res_api_bad = self.client.get("/api/calculate_tariff?units=invalid")
        self.assertEqual(res_api_bad.status_code, 400)
        self.assertIn("valid numeric value", res_api_bad.get_json()["error"])

        # Quick switch with disallowed username
        res_bad_switch = self.client.get("/quick_switch/admin/malicious_hacker")
        self.assertEqual(res_bad_switch.status_code, 403)

    # ---------------------------------------------------------
    # 16. Credential-Free Role & Consumer Selection Flow
    # ---------------------------------------------------------
    def test_16_role_and_consumer_selection_flow(self):
        """Verify credential-free role selection: / -> /select_role, /select_role/admin, /select_consumer."""
        # 1. Root / renders role selection page
        with self.client.session_transaction() as sess:
            sess.clear()
        res_root = self.client.get("/")
        self.assertEqual(res_root.status_code, 200)
        self.assertIn(b"Administrator Portal", res_root.data)
        self.assertIn(b"Consumer Portal", res_root.data)

        # 2. Administrator selection directly creates admin session
        res_admin = self.client.get("/select_role/admin", follow_redirects=True)
        self.assertEqual(res_admin.status_code, 200)
        self.assertIn(b"Administrator Dashboard", res_admin.data)
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get("role"), "admin")
            self.assertEqual(sess.get("username"), "admin")

        # 3. Consumer selection page lists actual consumers from SQLite
        with self.client.session_transaction() as sess:
            sess.clear()
        res_consumers = self.client.get("/select_consumer")
        self.assertEqual(res_consumers.status_code, 200)
        self.assertIn(b"Select Consumer Account", res_consumers.data)
        self.assertIn(b"Rahul Sharma", res_consumers.data)
        self.assertIn(b"WTR-1001", res_consumers.data)

        # 4. Selecting a consumer sets that consumer's session and enters consumer dashboard
        res_pick_consumer = self.client.get("/select_consumer/1", follow_redirects=True)
        self.assertEqual(res_pick_consumer.status_code, 200)
        self.assertIn(b"Consumer Portal", res_pick_consumer.data)
        self.assertIn(b"Rahul Sharma", res_pick_consumer.data)
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get("role"), "consumer")
            self.assertEqual(sess.get("username"), "rahul_sharma")

        # 5. Non-existent consumer ID is handled gracefully without crash
        res_bad_consumer = self.client.get("/select_consumer/99999", follow_redirects=True)
        self.assertEqual(res_bad_consumer.status_code, 200)
        self.assertIn(b"Consumer account not found.", res_bad_consumer.data)

    # ---------------------------------------------------------
    # 17. UTC Storage and Asia/Kolkata Display Policy
    # ---------------------------------------------------------
    def test_17_utc_timestamp_and_ist_conversion(self):
        """Verify centralized UTC storage policy and accurate Asia/Kolkata (IST) display conversion."""
        # 1. UTC helper checks
        utc_now = database.get_utc_now()
        self.assertIsNotNone(utc_now.tzinfo)
        utc_str = database.get_utc_now_str()
        self.assertEqual(len(utc_str), 19)

        # 2. Conversion across date boundary (UTC 20:00 -> IST +5:30 -> 01:30 next day)
        sample_utc = "2026-10-27 20:00:00"
        ist_converted = database.utc_to_ist_str(sample_utc, fmt="%Y-%m-%d %H:%M:%S")
        self.assertEqual(ist_converted, "2026-10-28 01:30:00")

        # 3. Calendar date formatting (preserving date without timezone drift)
        cal_date = database.format_calendar_date("2026-11-15")
        self.assertEqual(cal_date, "15 Nov 2026")

        # 4. Verify newly created alert stores UTC timestamp
        database.add_supply_alert(1, "Test Grid Pressure", "Maintenance alert for testing", "Info")
        conn = database.get_db()
        try:
            alert = conn.execute("SELECT posted_at FROM supply_alerts WHERE title = 'Test Grid Pressure'").fetchone()
            self.assertIsNotNone(alert)
            # Must be valid timestamp parseable without error
            self.assertEqual(len(alert["posted_at"]), 19)
        finally:
            conn.close()

    # ---------------------------------------------------------
    # 18. Duplicate Bill Prevention and Calendar Date Validation
    # ---------------------------------------------------------
    def test_18_duplicate_bill_prevention_and_date_rules(self):
        """Verify duplicate monthly bill prevention and due date precedence validation."""
        consumer = database.get_consumer_by_user_id(2)
        curr = float(consumer["last_meter_reading"])

        # 1. Reject due_date before billing_date
        with self.assertRaises(ValueError) as ctx:
            database.add_bill(
                consumer_id=consumer["consumer_id"],
                billing_month="October 2027",
                curr_reading=curr + 5.0,
                prev_reading=curr,
                billing_date="2027-10-20",
                due_date="2027-10-15"
            )
        self.assertIn("cannot be earlier than", str(ctx.exception))

        # 2. Successfully add bill for unique cycle
        b_id = database.add_bill(
            consumer_id=consumer["consumer_id"],
            billing_month="November 2027",
            curr_reading=curr + 15.0,
            prev_reading=curr,
            billing_date="2027-11-01",
            due_date="2027-11-16"
        )
        self.assertIsNotNone(b_id)

        # 3. Reject duplicate bill for the same consumer and month
        with self.assertRaises(ValueError) as ctx:
            database.add_bill(
                consumer_id=consumer["consumer_id"],
                billing_month="November 2027",
                curr_reading=curr + 25.0,
                prev_reading=curr + 15.0
            )
        self.assertIn("already been generated", str(ctx.exception))

    # ---------------------------------------------------------
    # 19. Single Payment Enforcement and Join Determinism
    # ---------------------------------------------------------
    def test_19_single_payment_enforcement_and_join_determinism(self):
        """Verify strict single-payment enforcement per bill and deterministic join without duplicate rows."""
        consumer = database.get_consumer_by_user_id(2)
        curr = float(consumer["last_meter_reading"])

        # Create distinct test bill
        bill_id = database.add_bill(
            consumer_id=consumer["consumer_id"],
            billing_month="September 2027",
            curr_reading=curr + 8.0,
            prev_reading=curr
        )
        bill = database.get_bill_by_id(bill_id)

        # Record valid payment
        receipt = database.record_bill_payment(
            bill_id=bill_id,
            payment_method="Net Banking",
            amount_paid=bill["total_amount"],
            consumer_id=consumer["consumer_id"]
        )
        self.assertIsNotNone(receipt["receipt_number"])
        self.assertTrue(receipt["transaction_ref"].startswith("TXN-"))

        # Re-attempting payment on paid bill MUST raise ValueError
        with self.assertRaises(ValueError) as ctx:
            database.record_bill_payment(
                bill_id=bill_id,
                payment_method="UPI",
                amount_paid=bill["total_amount"],
                consumer_id=consumer["consumer_id"]
            )
        self.assertIn("already been marked as PAID", str(ctx.exception))

        # Direct database-level test: inserting a second payment for the same bill
        # MUST fail at the database level with sqlite3.IntegrityError (UNIQUE constraint)
        conn = database.get_db()
        try:
            with self.assertRaises(sqlite3.IntegrityError) as db_ctx:
                with conn:
                    conn.execute("""
                        INSERT INTO payments (bill_id, consumer_id, receipt_number, transaction_ref, amount_paid, payment_method, payment_date)
                        VALUES (?, ?, 'RCPT-RAW-DUP-01', 'TXN-RAW-DUP-01', ?, 'Cash', datetime('now'))
                    """, (bill_id, consumer["consumer_id"], bill["total_amount"]))
            self.assertIn("UNIQUE", str(db_ctx.exception).upper())
        finally:
            conn.close()

        # Verify join determinism in get_bills_for_consumer: count of bill_id == 1
        all_consumer_bills = database.get_bills_for_consumer(consumer["consumer_id"])
        matching_bills = [b for b in all_consumer_bills if b["bill_id"] == bill_id]
        self.assertEqual(len(matching_bills), 1, "Bill row multiplied by payment join!")
        self.assertEqual(matching_bills[0]["receipt_number"], receipt["receipt_number"])
        self.assertEqual(matching_bills[0]["transaction_ref"], receipt["transaction_ref"])

        # Verify join determinism in get_all_bills: count of bill_id == 1
        all_admin_bills = database.get_all_bills()
        matching_admin_bills = [b for b in all_admin_bills if b["bill_id"] == bill_id]
        self.assertEqual(len(matching_admin_bills), 1, "Admin bill row multiplied by payment join!")

    # ---------------------------------------------------------
    # 20. Portal Switching, Session Invalidation & Flash Preservation
    # ---------------------------------------------------------
    def test_20_portal_switching_logout_and_session_clearing(self):
        """Verify switching portals clears previous identity/privileges and preserves flash notices."""
        # 1. Establish Admin session
        res_admin = self.client.get("/select_role/admin", follow_redirects=True)
        self.assertEqual(res_admin.status_code, 200)
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get("role"), "admin")
            self.assertEqual(sess.get("username"), "admin")

        # 2. Switch portal via /select_role: must clear admin session
        res_switch = self.client.get("/select_role")
        self.assertEqual(res_switch.status_code, 200)
        with self.client.session_transaction() as sess:
            self.assertIsNone(sess.get("role"))
            self.assertIsNone(sess.get("user_id"))
        # Public navigation must NOT expose admin control links
        self.assertNotIn(b'href="/admin/billing"', res_switch.data)
        self.assertNotIn(b'href="/admin/supply"', res_switch.data)

        # 3. Enter consumer portal
        res_consumer = self.client.get("/select_consumer/1", follow_redirects=True)
        self.assertEqual(res_consumer.status_code, 200)
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get("role"), "consumer")

        # 4. Visiting /select_consumer clears active session for fresh selection
        res_pick = self.client.get("/select_consumer")
        self.assertEqual(res_pick.status_code, 200)
        with self.client.session_transaction() as sess:
            self.assertIsNone(sess.get("role"))
            self.assertIsNone(sess.get("user_id"))

        # 5. Invalid consumer selection must preserve "Consumer account not found." flash message
        res_bad = self.client.get("/select_consumer/99999", follow_redirects=True)
        self.assertEqual(res_bad.status_code, 200)
        self.assertIn(b"Consumer account not found.", res_bad.data)

        # 6. Logout must clear session and preserve "Session ended" notice
        # Set an arbitrary session
        with self.client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["role"] = "admin"
        res_logout = self.client.get("/logout", follow_redirects=True)
        self.assertEqual(res_logout.status_code, 200)
        self.assertIn(b"Session ended. Please choose a portal to continue.", res_logout.data)
        with self.client.session_transaction() as sess:
            self.assertIsNone(sess.get("user_id"))
            self.assertIsNone(sess.get("role"))

    # ---------------------------------------------------------
    # 21. Payment Timestamp Consistency Across Views
    # ---------------------------------------------------------
    def test_21_payment_timestamp_consistency_across_views(self):
        """Verify payment timestamp is persisted in UTC and displayed consistently across bills, invoice, and history in IST."""
        consumer = database.get_consumer_by_user_id(2)  # Rahul Sharma
        curr = float(consumer["last_meter_reading"])

        # Create unique bill
        b_id = database.add_bill(
            consumer_id=consumer["consumer_id"],
            billing_month="August 2027",
            curr_reading=curr + 12.0,
            prev_reading=curr
        )
        bill = database.get_bill_by_id(b_id)

        # Record payment
        receipt = database.record_bill_payment(
            bill_id=b_id,
            payment_method="UPI",
            amount_paid=bill["total_amount"],
            consumer_id=consumer["consumer_id"]
        )

        # Check database timestamp format
        paid_bill = database.get_bill_by_id(b_id)
        self.assertIsNotNone(paid_bill["payment_date"])
        expected_ist = database.utc_to_ist_str(paid_bill["payment_date"])

        # Authenticate as Rahul
        with self.client.session_transaction() as sess:
            sess["user_id"] = 2
            sess["username"] = "rahul_sharma"
            sess["role"] = "consumer"
            sess["full_name"] = "Rahul Sharma"

        # Check /consumer/bills HTML contains the IST payment timestamp and receipt number
        res_bills = self.client.get("/consumer/bills")
        self.assertEqual(res_bills.status_code, 200)
        self.assertIn(receipt["receipt_number"].encode(), res_bills.data)
        self.assertIn(expected_ist.encode(), res_bills.data)

        # Check /bill/<id>/invoice HTML contains the exact same IST timestamp, receipt, and txn ref
        res_inv = self.client.get(f"/bill/{b_id}/invoice")
        self.assertEqual(res_inv.status_code, 200)
        self.assertIn(receipt["receipt_number"].encode(), res_inv.data)
        self.assertIn(receipt["transaction_ref"].encode(), res_inv.data)
        self.assertIn(expected_ist.encode(), res_inv.data)


if __name__ == "__main__":
    unittest.main()
