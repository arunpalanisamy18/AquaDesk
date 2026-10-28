from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, abort, g
from functools import wraps
import database
import os
import secrets
import logging
import time

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or "aquaflow-secure-session-key-2026-ia3"
app.config["TEMPLATES_AUTO_RELOAD"] = True

# Academic Demo Mode Flag
DEMO_MODE_ENABLED = os.environ.get("AQUAFLOW_DEMO_MODE", "true").lower() in ("true", "1", "yes")

ALLOWED_DEMO_USERS = {
    "admin": "admin",
    "rahul_sharma": "consumer",
    "priya_patel": "consumer",
    "apex_hospital": "consumer",
    "sun_textiles": "consumer"
}

# ----------------- OPERATIONAL LOGGING CONFIGURATION -----------------
class RequestIdFormatter(logging.Formatter):
    def format(self, record):
        if not hasattr(record, "request_id"):
            try:
                record.request_id = getattr(g, "request_id", "SYS")
            except RuntimeError:
                record.request_id = "SYS"
        return super().format(record)

log_level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
log_level = getattr(logging, log_level_name, logging.INFO)

_handler = logging.StreamHandler()
_handler.setFormatter(RequestIdFormatter("%(asctime)s [%(levelname)s] [Req:%(request_id)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))

_root_logger = logging.getLogger()
_root_logger.setLevel(log_level)
_root_logger.handlers = [_handler]

logger = logging.getLogger("aquaflow")

# ----------------- CSRF & SECURITY HOOKS -----------------
@app.before_request
def security_and_csrf_check():
    # Assign short request correlation ID
    g.request_id = secrets.token_hex(4)
    g.start_time = time.time()

    # Ensure a unique CSRF token exists for the session
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(24)

    # Protect state-changing HTTP methods from CSRF
    if request.method in ("POST", "PUT", "DELETE", "PATCH"):
        # Allow bypassing CSRF during automated unit testing if configured
        if app.config.get("TESTING") or app.config.get("WTF_CSRF_ENABLED") is False:
            return

        submitted_token = request.form.get("csrf_token") or request.headers.get("X-CSRFToken")
        session_token = session.get("csrf_token")

        if not submitted_token or submitted_token != session_token:
            logger.warning(f"CSRF validation failed for {request.path}")
            flash("Security check failed: Invalid or missing CSRF session token. Please reload and try again.", "danger")
            if request.is_json or request.path.startswith("/api/"):
                return jsonify({"error": "CSRF validation failed"}), 400
            return render_template("base.html"), 400

@app.after_request
def log_request_metrics(response):
    if hasattr(g, "start_time") and not request.path.startswith("/static"):
        duration = round((time.time() - g.start_time) * 1000, 1)
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"{request.method} {request.path} -> {response.status_code} ({duration}ms)")
    return response

# ----------------- JINJA2 TEMPLATE FILTERS -----------------
@app.template_filter("utc_to_ist")
def jinja_utc_to_ist(val, fmt="%d %b %Y, %I:%M %p"):
    """Converts a stored UTC timestamp to Asia/Kolkata (IST) display format."""
    return database.utc_to_ist_str(val, fmt)

@app.template_filter("format_date")
def jinja_format_date(val, fmt="%d %b %Y"):
    """Formats a calendar date string (YYYY-MM-DD) nicely for display."""
    return database.format_calendar_date(val, fmt)

# ----------------- AUTH DECORATORS -----------------
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            flash("Please sign in or select a demo role to access this portal.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            flash("Please sign in or select Administrator demo role.", "warning")
            return redirect(url_for("login"))
        if session.get("role") != "admin":
            flash("Access denied. Administrator privileges required.", "danger")
            return redirect(url_for("consumer_dashboard"))
        return f(*args, **kwargs)
    return decorated_function

def consumer_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            flash("Please sign in or select a Consumer profile.", "warning")
            return redirect(url_for("login"))
        if session.get("role") != "consumer":
            flash("Access denied. Consumer account required.", "danger")
            return redirect(url_for("admin_dashboard"))
        return f(*args, **kwargs)
    return decorated_function

# Context processor for templates
@app.context_processor
def inject_user():
    return {
        "current_user": session.get("username"),
        "current_role": session.get("role"),
        "current_full_name": session.get("full_name"),
        "csrf_token": session.get("csrf_token"),
        "demo_mode_enabled": DEMO_MODE_ENABLED
    }

# ----------------- HEALTH CHECK ROUTE -----------------
@app.route("/health")
@app.route("/api/health")
def health_check():
    """
    Read-only health diagnostic endpoint.
    Verifies SQLite database file presence, active connectivity, PRAGMA checks, and table row counts.
    """
    try:
        health_report = database.check_database_health()
        return jsonify(health_report), 200
    except Exception as e:
        return jsonify({
            "status": "unhealthy",
            "error": str(e)
        }), 503

# ----------------- ROLE SELECTION & AUTHENTICATION -----------------
def clear_auth_session():
    """
    Clears authenticated user identity and role from session
    while strictly preserving Flask flash notifications and CSRF tokens.
    """
    for key in ("user_id", "username", "role", "full_name", "consumer_id"):
        session.pop(key, None)

@app.route("/")
def index():
    """
    Main landing route.
    Presents the clean role selection page with Administrator and Consumer options.
    Clears previous identity so switching back to landing resets privileges safely.
    """
    clear_auth_session()
    return render_template("role_selection.html")

@app.route("/select_role")
def select_role():
    """Displays the role selection page allowing clean portal switching."""
    clear_auth_session()
    return render_template("role_selection.html")

@app.route("/select_role/admin", methods=["GET", "POST"])
def select_role_admin():
    """
    Demonstration entry into the Administrator portal.
    Retrieves the administrator account and initializes the server-side session.
    """
    clear_auth_session()
    admin = database.get_user_by_username("admin")
    if not admin:
        conn = database.get_db()
        admin = conn.execute("SELECT * FROM users WHERE role = 'admin' LIMIT 1").fetchone()
        conn.close()

    if admin:
        session["user_id"] = admin["user_id"]
        session["username"] = admin["username"]
        session["role"] = "admin"
        session["full_name"] = admin["full_name"]
        logger.info("Admin demo session initiated via /select_role/admin")
        flash("Accessed Municipal Administrator Portal.", "info")
        return redirect(url_for("admin_dashboard"))

    flash("Administrator account not found in database.", "danger")
    return redirect(url_for("select_role"))

@app.route("/select_consumer")
def select_consumer():
    """
    Consumer selection screen listing actual consumers retrieved from SQLite.
    Allows opening any consumer's portal with isolated data loading.
    Clears prior user session keys so consumer selection starts with a clean slate,
    while strictly preserving flash notifications.
    """
    clear_auth_session()
    try:
        consumers = database.get_all_consumers()
    except Exception as e:
        logger.error(f"Error loading consumers from database: {str(e)}")
        flash(f"Error loading consumers from database: {str(e)}", "danger")
        consumers = []

    return render_template("select_consumer.html", consumers=consumers)

@app.route("/select_consumer/<int:consumer_id>", methods=["GET", "POST"])
def select_consumer_account(consumer_id):
    """
    Initializes a server-side session for the chosen consumer and redirects to their dashboard.
    """
    consumer = database.get_consumer_by_id(consumer_id)
    if not consumer:
        logger.warning(f"Attempted selection of non-existent consumer ID: {consumer_id}")
        flash("Consumer account not found.", "danger")
        return redirect(url_for("select_consumer"))

    clear_auth_session()
    session["user_id"] = consumer["user_id"]
    session["username"] = consumer["username"]
    session["role"] = "consumer"
    session["full_name"] = consumer["full_name"]
    logger.info(f"Consumer session bound: {consumer['full_name']} (Account: {consumer['account_number']}, ID: {consumer_id})")
    flash(f"Accessed Consumer Portal for {consumer['full_name']} ({consumer['account_number']}).", "info")
    return redirect(url_for("consumer_dashboard"))

@app.route("/login", methods=["GET", "POST"])
def login():
    """
    Login endpoint.
    GET: Presents the clean role selection screen.
    POST: Preserves credential-based authentication for test suite compatibility.
    """
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        if not username or not password:
            logger.warning("Login rejected: Empty username or password submitted")
            flash("Please provide both username and password.", "danger")
            return render_template("role_selection.html"), 400

        user = database.get_user_by_username(username)
        from werkzeug.security import check_password_hash
        if user and check_password_hash(user["password"], password):
            session["user_id"] = user["user_id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            session["full_name"] = user["full_name"]

            logger.info(f"User '{username}' logged in successfully with role '{user['role']}'")
            flash(f"Welcome back, {user['full_name']}!", "success")
            if user["role"] == "admin":
                return redirect(url_for("admin_dashboard"))
            else:
                return redirect(url_for("consumer_dashboard"))
        else:
            logger.warning(f"Failed login attempt for username '{username}'")
            flash("Invalid username or password. Please try again.", "danger")
            return render_template("role_selection.html"), 400

    return render_template("role_selection.html")

@app.route("/quick_switch/<role>/<username>")
def quick_switch(role, username):
    """
    Demonstration role switch shortcut for examiners.
    Restricted to approved demo accounts and active when demo mode is enabled.
    """
    if not DEMO_MODE_ENABLED:
        flash("Demo switcher is disabled in this environment.", "danger")
        return ("Demo role switching is disabled in production.", 403)

    if username not in ALLOWED_DEMO_USERS or ALLOWED_DEMO_USERS[username] != role:
        flash("Unauthorized demo account.", "danger")
        return ("Unauthorized demo account requested.", 403)

    user = database.get_user_by_username(username)
    if user and user["role"] == role:
        session["user_id"] = user["user_id"]
        session["username"] = user["username"]
        session["role"] = user["role"]
        session["full_name"] = user["full_name"]
        flash(f"Switched session to {user['full_name']} ({role.upper()})", "info")
        if role == "admin":
            return redirect(url_for("admin_dashboard"))
        return redirect(url_for("consumer_dashboard"))

    flash("Demo user not found.", "danger")
    return redirect(url_for("select_role"))

@app.route("/register", methods=["GET", "POST"])
def register():
    """
    Consumer connection registration route.
    Creates user and consumer profile atomically.
    """
    zones = database.get_all_zones()
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "").strip() or "password123"
        zone_id = request.form.get("zone_id")
        connection_type = request.form.get("connection_type", "Residential")
        address = request.form.get("address", "").strip()
        initial_reading_raw = request.form.get("initial_reading", "0.0")

        if not all([full_name, username, email, zone_id, address]):
            flash("All mandatory fields must be completed.", "danger")
            return render_template("register.html", zones=zones), 400

        try:
            initial_reading = float(initial_reading_raw or 0.0)
            if initial_reading < 0:
                raise ValueError("Initial meter reading cannot be negative.")
        except ValueError as ve:
            flash(f"Invalid initial meter reading: {str(ve)}", "danger")
            return render_template("register.html", zones=zones), 400

        try:
            # Atomic registration: creates user and consumer profile in a single transaction
            database.register_consumer_account(
                username=username,
                password=password,
                full_name=full_name,
                email=email,
                phone=phone,
                zone_id=int(zone_id),
                connection_type=connection_type,
                address=address,
                initial_reading=initial_reading
            )
            logger.info(f"Consumer registration successful: username '{username}', zone #{zone_id}")
            flash("Registration successful! Your water utility connection has been registered.", "success")
            return redirect(url_for("select_consumer"))
        except ValueError as ve:
            logger.warning(f"Registration validation failure for '{username}': {str(ve)}")
            flash(str(ve), "danger")
        except Exception as e:
            logger.error(f"Registration error for '{username}': {str(e)}")
            flash(f"Registration failed: {str(e)}", "danger")

    return render_template("register.html", zones=zones)

@app.route("/logout")
def logout():
    clear_auth_session()
    flash("Session ended. Please choose a portal to continue.", "info")
    return redirect(url_for("select_role"))

# ----------------- ADMIN DASHBOARD & CONTROLS -----------------
@app.route("/admin/dashboard")
@admin_required
def admin_dashboard():
    metrics = database.get_admin_dashboard_metrics()
    zones = database.get_all_zones()
    alerts = database.get_active_alerts()
    return render_template("admin/dashboard.html", metrics=metrics, zones=zones, alerts=alerts)

@app.route("/admin/billing", methods=["GET", "POST"])
@admin_required
def admin_billing():
    if request.method == "POST":
        consumer_id = request.form.get("consumer_id")
        billing_month = request.form.get("billing_month", "").strip()
        prev_reading_raw = request.form.get("prev_reading")
        curr_reading_raw = request.form.get("curr_reading")
        due_days_raw = request.form.get("due_days", "15")
        notes = request.form.get("notes")

        if not consumer_id or not billing_month or curr_reading_raw is None:
            flash("Consumer, billing month, and current meter reading are required.", "danger")
            return redirect(url_for("admin_billing"))

        try:
            curr_reading = float(curr_reading_raw)
            prev_reading = float(prev_reading_raw) if prev_reading_raw and prev_reading_raw.strip() else None
            due_days = int(due_days_raw or 15)

            bill_id = database.add_bill(
                consumer_id=int(consumer_id),
                billing_month=billing_month,
                curr_reading=curr_reading,
                prev_reading=prev_reading,
                due_days=due_days,
                notes=notes
            )
            consumer = database.get_consumer_by_id(int(consumer_id))
            logger.info(f"Generated bill #{bill_id} for consumer #{consumer_id} ({billing_month}, units: {curr_reading - (prev_reading or 0):.2f} kL)")
            flash(f"Bill #{bill_id} generated for {consumer['full_name']} ({consumer['account_number']}).", "success")
            return redirect(url_for("admin_billing"))
        except ValueError as ve:
            logger.warning(f"Bill generation rejected for consumer #{consumer_id}: {str(ve)}")
            flash(f"Billing Error: {str(ve)}", "danger")
        except Exception as e:
            logger.error(f"Unexpected error generating bill for consumer #{consumer_id}: {str(e)}")
            flash(f"Unexpected error generating bill: {str(e)}", "danger")

    filter_status = request.args.get("status", "ALL")
    bills = database.get_all_bills(filter_status)
    consumers = database.get_all_consumers()
    return render_template("admin/billing.html", bills=bills, consumers=consumers, current_filter=filter_status)

@app.route("/admin/consumers", methods=["GET", "POST"])
@admin_required
def admin_consumers():
    zones = database.get_all_zones()
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "").strip() or "password123"
        zone_id = request.form.get("zone_id")
        connection_type = request.form.get("connection_type", "Residential")
        meter_number = request.form.get("meter_number", "").strip() or None
        address = request.form.get("address", "").strip()
        initial_reading_raw = request.form.get("initial_reading", "0.0")

        if not all([full_name, username, email, zone_id, address]):
            flash("All mandatory fields must be completed.", "danger")
            return redirect(url_for("admin_consumers"))

        try:
            initial_reading = float(initial_reading_raw or 0.0)
            database.register_consumer_account(
                username=username,
                password=password,
                full_name=full_name,
                email=email,
                phone=phone,
                zone_id=int(zone_id),
                connection_type=connection_type,
                address=address,
                initial_reading=initial_reading,
                meter_number=meter_number
            )
            flash(f"Consumer account for {full_name} created successfully.", "success")
            return redirect(url_for("admin_consumers"))
        except ValueError as ve:
            flash(f"Failed to create consumer: {str(ve)}", "danger")
        except Exception as e:
            flash(f"Unexpected error: {str(e)}", "danger")

    consumers = database.get_all_consumers()
    return render_template("admin/consumers.html", consumers=consumers, zones=zones)

@app.route("/admin/supply", methods=["GET", "POST"])
@admin_required
def admin_supply():
    if request.method == "POST":
        action = request.form.get("action")
        if action == "update_zone":
            try:
                zone_id = int(request.form.get("zone_id"))
                status = request.form.get("status")
                reservoir_level = float(request.form.get("reservoir_level"))
                water_pressure = float(request.form.get("water_pressure"))
                morning_slot = request.form.get("morning_slot", "").strip()
                evening_slot = request.form.get("evening_slot", "").strip()
                purity_ph_raw = request.form.get("purity_ph")
                tds_ppm_raw = request.form.get("tds_ppm")

                purity_ph = float(purity_ph_raw) if purity_ph_raw and purity_ph_raw.strip() else None
                tds_ppm = int(tds_ppm_raw) if tds_ppm_raw and tds_ppm_raw.strip() else None

                database.update_zone_details(
                    zone_id=zone_id,
                    status=status,
                    reservoir_level=reservoir_level,
                    water_pressure=water_pressure,
                    morning_slot=morning_slot,
                    evening_slot=evening_slot,
                    purity_ph=purity_ph,
                    tds_ppm=tds_ppm
                )
                flash("Zone water supply parameters updated successfully.", "success")
            except ValueError as ve:
                flash(f"Zone update failed: {str(ve)}", "danger")
            except Exception as e:
                flash(f"Error updating zone: {str(e)}", "danger")

        elif action == "add_alert":
            try:
                zone_id = request.form.get("zone_id")
                title = request.form.get("title", "").strip()
                message = request.form.get("message", "").strip()
                severity = request.form.get("severity", "Warning")

                database.add_supply_alert(zone_id, title, message, severity)
                flash("Supply alert published successfully.", "success")
            except ValueError as ve:
                flash(f"Alert creation failed: {str(ve)}", "danger")
            except Exception as e:
                flash(f"Error publishing alert: {str(e)}", "danger")

        return redirect(url_for("admin_supply"))

    zones = database.get_all_zones()
    alerts = database.get_active_alerts()
    return render_template("admin/supply.html", zones=zones, alerts=alerts)

@app.route("/admin/alert/toggle/<int:alert_id>", methods=["GET", "POST"])
@app.route("/admin/alert/toggle/<int:alert_id>/<int:status>", methods=["GET", "POST"])
@admin_required
def admin_toggle_alert(alert_id, status=None):
    if status is None:
        # Toggle current status
        conn = database.get_db()
        current = conn.execute("SELECT is_active FROM supply_alerts WHERE alert_id = ?", (alert_id,)).fetchone()
        conn.close()
        new_status = not bool(current["is_active"]) if current else False
    else:
        new_status = bool(status)

    database.toggle_alert_status(alert_id, new_status)
    flash("Alert status updated.", "info")
    return redirect(url_for("admin_supply"))

@app.route("/admin/complaints", methods=["GET", "POST"])
@admin_required
def admin_complaints():
    if request.method == "POST":
        try:
            complaint_id = int(request.form.get("complaint_id"))
            status = request.form.get("status")
            admin_response = request.form.get("admin_response")
            database.update_complaint_status(complaint_id, status, admin_response)
            flash("Grievance ticket updated successfully.", "success")
        except ValueError as ve:
            flash(f"Update failed: {str(ve)}", "danger")
        except Exception as e:
            flash(f"Error updating grievance: {str(e)}", "danger")
        return redirect(url_for("admin_complaints"))

    complaints = database.get_all_complaints()
    return render_template("admin/complaints.html", complaints=complaints)

# ----------------- CONSUMER DASHBOARD & ACTIONS -----------------
@app.route("/consumer/dashboard")
@consumer_required
def consumer_dashboard():
    consumer = database.get_consumer_by_user_id(session["user_id"])
    if not consumer:
        flash("Consumer record not found. Please select an active consumer account.", "danger")
        return redirect(url_for("select_consumer"))

    metrics = database.get_consumer_dashboard_metrics(consumer["consumer_id"])
    bills = database.get_bills_for_consumer(consumer["consumer_id"])
    alerts = database.get_active_alerts(consumer["zone_id"])
    recent_complaints = database.get_complaints_by_consumer(consumer["consumer_id"])[:3]

    return render_template(
        "consumer/dashboard.html",
        consumer=consumer,
        metrics=metrics,
        bills=bills,
        alerts=alerts,
        recent_complaints=recent_complaints
    )

@app.route("/consumer/bills")
@consumer_required
def consumer_bills():
    consumer = database.get_consumer_by_user_id(session["user_id"])
    if not consumer:
        flash("Consumer account not found.", "danger")
        return redirect(url_for("select_consumer"))

    bills = database.get_bills_for_consumer(consumer["consumer_id"])
    return render_template("consumer/bills.html", consumer=consumer, bills=bills)

@app.route("/consumer/pay/<int:bill_id>", methods=["POST"])
@consumer_required
def consumer_pay_bill(bill_id):
    consumer = database.get_consumer_by_user_id(session["user_id"])
    if not consumer:
        flash("Consumer profile missing.", "danger")
        return redirect(url_for("select_consumer"))

    bill = database.get_bill_by_id(bill_id)
    if not bill or bill["consumer_id"] != consumer["consumer_id"]:
        logger.warning(f"Unauthorized payment attempt: Consumer #{consumer['consumer_id']} tried to pay bill #{bill_id}")
        flash("Unauthorized payment request. You can only pay your own utility bills.", "danger")
        return redirect(url_for("consumer_bills"))

    payment_method = request.form.get("payment_method", "UPI")
    amount_paid_raw = request.form.get("amount_paid")
    amount_paid = float(amount_paid_raw) if amount_paid_raw and amount_paid_raw.strip() else None

    try:
        receipt = database.record_bill_payment(
            bill_id=bill_id,
            payment_method=payment_method,
            amount_paid=amount_paid,
            consumer_id=consumer["consumer_id"]
        )
        logger.info(f"Payment successful: Bill #{bill_id}, Receipt #{receipt['receipt_number']}, Ref {receipt['transaction_ref']}, Amount ₹{receipt['amount']:.2f} via {payment_method}")
        flash(f"Payment successful! Receipt #{receipt['receipt_number']} generated. Amount: ₹{receipt['amount']:.2f}", "success")
    except ValueError as ve:
        logger.warning(f"Payment rejected for bill #{bill_id}: {str(ve)}")
        flash(f"Payment rejected: {str(ve)}", "danger")
    except Exception as e:
        logger.error(f"Payment transaction failed for bill #{bill_id}: {str(e)}")
        flash(f"Payment transaction failed: {str(e)}", "danger")

    return redirect(url_for("consumer_bills"))

@app.route("/bill/<int:bill_id>/invoice")
@login_required
def view_bill_invoice(bill_id):
    bill = database.get_bill_by_id(bill_id)
    if not bill:
        flash("Bill not found.", "danger")
        return redirect(url_for("index"))

    # Enforce strict data isolation for consumers
    if session.get("role") == "consumer":
        consumer = database.get_consumer_by_user_id(session["user_id"])
        if not consumer or bill["consumer_id"] != consumer["consumer_id"]:
            flash("Unauthorized access: You cannot inspect invoices belonging to other consumers.", "danger")
            return redirect(url_for("consumer_dashboard"))

    return render_template("bill_invoice.html", bill=bill)

@app.route("/consumer/complaints", methods=["GET", "POST"])
@consumer_required
def consumer_complaints():
    consumer = database.get_consumer_by_user_id(session["user_id"])
    if not consumer:
        flash("Consumer profile missing.", "danger")
        return redirect(url_for("select_consumer"))

    if request.method == "POST":
        category = request.form.get("category")
        description = request.form.get("description", "").strip()

        try:
            database.add_complaint(consumer["consumer_id"], category, description)
            flash("Grievance registered successfully. Municipal field team will inspect.", "success")
            return redirect(url_for("consumer_complaints"))
        except ValueError as ve:
            flash(f"Could not submit grievance: {str(ve)}", "danger")
        except Exception as e:
            flash(f"Submission error: {str(e)}", "danger")

    complaints = database.get_complaints_by_consumer(consumer["consumer_id"])
    return render_template("consumer/complaints.html", consumer=consumer, complaints=complaints)

# ----------------- API HELPER ENDPOINTS -----------------
@app.route("/api/consumer/<int:consumer_id>/details")
@admin_required
def api_consumer_details(consumer_id):
    consumer = database.get_consumer_by_id(consumer_id)
    if not consumer:
        return jsonify({"error": "Consumer not found"}), 404
    return jsonify({
        "consumer_id": consumer["consumer_id"],
        "account_number": consumer["account_number"],
        "meter_number": consumer["meter_number"],
        "connection_type": consumer["connection_type"],
        "zone_name": consumer["zone_name"],
        "last_meter_reading": consumer["last_meter_reading"]
    })

@app.route("/api/calculate_tariff")
def api_calculate_tariff():
    connection_type = request.args.get("connection_type", "Residential")
    units_raw = request.args.get("units", "0.0")
    try:
        tariff = database.calculate_water_tariff(connection_type, units_raw)
        return jsonify(tariff), 200
    except ValueError as ve:
        return jsonify({"error": str(ve)}), 400

# ----------------- STATIC ASSETS & ERROR HANDLERS -----------------
@app.route("/favicon.ico")
def favicon():
    return app.response_class(status=204)

@app.errorhandler(403)
def forbidden(e):
    return render_template("error.html", error_code=403, error_title="Access Forbidden", error_message="You do not have administrative privileges to access this protected municipal resource."), 403

@app.errorhandler(404)
def not_found(e):
    return render_template("error.html", error_code=404, error_title="Resource Not Found", error_message="The requested utility page or endpoint does not exist on this server."), 404

@app.errorhandler(500)
def internal_server_error(e):
    return render_template("error.html", error_code=500, error_title="Internal Server Error", error_message="An unexpected system error occurred while processing your request. Please try again later."), 500

if __name__ == "__main__":
    database.init_db()
    conn = database.get_db()
    user_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    conn.close()
    if user_count == 0:
        import seed_data
        seed_data.seed()

    is_debug = os.environ.get("FLASK_DEBUG", "0").lower() in ("1", "true")
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"Starting AquaFlow Water Utility System on http://127.0.0.1:{port} (Debug={is_debug}, LogLevel={log_level_name}, DB={database.get_db_path()})")
    app.run(debug=is_debug, host="127.0.0.1", port=port)
