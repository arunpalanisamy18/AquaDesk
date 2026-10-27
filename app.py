from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from functools import wraps
import database
import os

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or os.urandom(32)

# ----------------- AUTH DECORATORS -----------------
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            flash("Please sign in to access this page.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session or session.get("role") != "admin":
            flash("Access denied. Administrator privileges required.", "danger")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function

def consumer_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session or session.get("role") != "consumer":
            flash("Access denied. Consumer account required.", "danger")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function

# Context processor for navigation
@app.context_processor
def inject_user():
    return {
        "current_user": session.get("username"),
        "current_role": session.get("role"),
        "current_full_name": session.get("full_name")
    }

# ----------------- AUTHENTICATION ROUTES -----------------
@app.route("/")
def index():
    if "user_id" in session:
        if session.get("role") == "admin":
            return redirect(url_for("admin_dashboard"))
        return redirect(url_for("consumer_dashboard"))
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        user = database.get_user_by_username(username)
        from werkzeug.security import check_password_hash
        if user and check_password_hash(user["password"], password):
            session["user_id"] = user["user_id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            session["full_name"] = user["full_name"]

            flash(f"Welcome back, {user['full_name']}!", "success")
            if user["role"] == "admin":
                return redirect(url_for("admin_dashboard"))
            else:
                return redirect(url_for("consumer_dashboard"))
        else:
            flash("Invalid username or password. Please try again.", "danger")

    # Get sample demo users for quick presentation switcher
    demo_consumers = database.get_all_consumers()[:3]
    return render_template("login.html", demo_consumers=demo_consumers)

@app.route("/quick_switch/<role>/<username>")
def quick_switch(role, username):
    """Convenient 1-click login for demonstration to teachers/examiners"""
    user = database.get_user_by_username(username)
    if user:
        session["user_id"] = user["user_id"]
        session["username"] = user["username"]
        session["role"] = user["role"]
        session["full_name"] = user["full_name"]
        flash(f"Switched session to {user['full_name']} ({role.upper()})", "info")
        if role == "admin":
            return redirect(url_for("admin_dashboard"))
        return redirect(url_for("consumer_dashboard"))
    flash("Demo user not found.", "danger")
    return redirect(url_for("login"))

@app.route("/register", methods=["GET", "POST"])
def register():
    zones = database.get_all_zones()
    if request.method == "POST":
        full_name = request.form.get("full_name")
        username = request.form.get("username")
        email = request.form.get("email")
        phone = request.form.get("phone")
        password = request.form.get("password")
        zone_id = request.form.get("zone_id")
        connection_type = request.form.get("connection_type")
        address = request.form.get("address")
        initial_reading = float(request.form.get("initial_reading") or 0.0)

        # Check existing username
        if database.get_user_by_username(username):
            flash("Username already exists. Please choose a different one.", "danger")
            return render_template("register.html", zones=zones)

        try:
            user_id = database.create_user(username, password, "consumer", full_name, email, phone)
            database.create_consumer_profile(user_id, zone_id, connection_type, address, initial_reading=initial_reading)
            flash("Registration successful! You can now log in with your credentials.", "success")
            return redirect(url_for("login"))
        except Exception as e:
            flash(f"Error during registration: {str(e)}", "danger")

    return render_template("register.html", zones=zones)

@app.route("/logout")
def logout():
    session.clear()
    flash("You have been signed out successfully.", "info")
    return redirect(url_for("login"))

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
        billing_month = request.form.get("billing_month")
        prev_reading = float(request.form.get("prev_reading"))
        curr_reading = float(request.form.get("curr_reading"))
        due_days = int(request.form.get("due_days") or 15)
        notes = request.form.get("notes")

        try:
            bill_id = database.add_bill(consumer_id, billing_month, curr_reading, prev_reading, due_days, notes)
            consumer = database.get_consumer_by_id(consumer_id)
            flash(f"Bill successfully generated for {consumer['full_name']} ({consumer['account_number']})! It is now instantly visible on the consumer's dashboard.", "success")
            return redirect(url_for("admin_billing"))
        except Exception as e:
            flash(f"Error adding bill: {str(e)}", "danger")

    filter_status = request.args.get("status", "ALL")
    bills = database.get_all_bills(filter_status)
    consumers = database.get_all_consumers()
    return render_template("admin/billing.html", bills=bills, consumers=consumers, current_filter=filter_status)

@app.route("/admin/consumers", methods=["GET", "POST"])
@admin_required
def admin_consumers():
    zones = database.get_all_zones()
    if request.method == "POST":
        full_name = request.form.get("full_name")
        username = request.form.get("username")
        email = request.form.get("email")
        phone = request.form.get("phone")
        password = request.form.get("password") or "password123"
        zone_id = request.form.get("zone_id")
        connection_type = request.form.get("connection_type")
        meter_number = request.form.get("meter_number")
        address = request.form.get("address")
        initial_reading = float(request.form.get("initial_reading") or 0.0)

        try:
            user_id = database.create_user(username, password, "consumer", full_name, email, phone)
            database.create_consumer_profile(user_id, zone_id, connection_type, address, meter_number, initial_reading)
            flash(f"Consumer account for {full_name} created successfully!", "success")
            return redirect(url_for("admin_consumers"))
        except Exception as e:
            flash(f"Failed to create consumer: {str(e)}", "danger")

    consumers = database.get_all_consumers()
    return render_template("admin/consumers.html", consumers=consumers, zones=zones)

@app.route("/admin/supply", methods=["GET", "POST"])
@admin_required
def admin_supply():
    if request.method == "POST":
        action = request.form.get("action")
        if action == "update_zone":
            zone_id = int(request.form.get("zone_id"))
            status = request.form.get("status")
            reservoir_level = float(request.form.get("reservoir_level"))
            water_pressure = float(request.form.get("water_pressure"))
            morning_slot = request.form.get("morning_slot")
            evening_slot = request.form.get("evening_slot")
            purity_ph = float(request.form.get("purity_ph")) if request.form.get("purity_ph") else None
            tds_ppm = int(request.form.get("tds_ppm")) if request.form.get("tds_ppm") else None

            database.update_zone_details(zone_id, status, reservoir_level, water_pressure, morning_slot, evening_slot, purity_ph, tds_ppm)
            flash("Zone water supply parameters updated successfully!", "success")

        elif action == "add_alert":
            zone_id = request.form.get("zone_id")
            title = request.form.get("title")
            message = request.form.get("message")
            severity = request.form.get("severity")
            database.add_supply_alert(zone_id, title, message, severity)
            flash("Supply alert / notice published to consumer dashboards!", "success")

        return redirect(url_for("admin_supply"))

    zones = database.get_all_zones()
    alerts = database.get_active_alerts()
    return render_template("admin/supply.html", zones=zones, alerts=alerts)

@app.route("/admin/alert/toggle/<int:alert_id>/<int:status>")
@admin_required
def admin_toggle_alert(alert_id, status):
    database.toggle_alert_status(alert_id, bool(status))
    flash("Alert status updated.", "info")
    return redirect(url_for("admin_supply"))

@app.route("/admin/complaints", methods=["GET", "POST"])
@admin_required
def admin_complaints():
    if request.method == "POST":
        complaint_id = int(request.form.get("complaint_id"))
        status = request.form.get("status")
        admin_response = request.form.get("admin_response")
        database.update_complaint_status(complaint_id, status, admin_response)
        flash("Grievance ticket updated successfully.", "success")
        return redirect(url_for("admin_complaints"))

    complaints = database.get_all_complaints()
    return render_template("admin/complaints.html", complaints=complaints)

# ----------------- CONSUMER DASHBOARD & ACTIONS -----------------
@app.route("/consumer/dashboard")
@consumer_required
def consumer_dashboard():
    consumer = database.get_consumer_by_user_id(session["user_id"])
    if not consumer:
        flash("Consumer record not found. Please contact municipal administrator.", "danger")
        return redirect(url_for("logout"))

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
    bills = database.get_bills_for_consumer(consumer["consumer_id"])
    return render_template("consumer/bills.html", consumer=consumer, bills=bills)

@app.route("/consumer/pay/<int:bill_id>", methods=["POST"])
@consumer_required
def consumer_pay_bill(bill_id):
    consumer = database.get_consumer_by_user_id(session["user_id"])
    bill = database.get_bill_by_id(bill_id)

    if not bill or bill["consumer_id"] != consumer["consumer_id"]:
        flash("Unauthorized bill payment request.", "danger")
        return redirect(url_for("consumer_bills"))

    payment_method = request.form.get("payment_method", "UPI")
    try:
        receipt = database.record_bill_payment(bill_id, payment_method)
        flash(f"Payment successful! Receipt #{receipt['receipt_number']} generated. Amount paid: ₹{receipt['amount']}", "success")
    except Exception as e:
        flash(f"Payment failed: {str(e)}", "danger")

    return redirect(url_for("consumer_bills"))

@app.route("/bill/<int:bill_id>/invoice")
@login_required
def view_bill_invoice(bill_id):
    bill = database.get_bill_by_id(bill_id)
    if not bill:
        flash("Bill not found.", "danger")
        return redirect(url_for("index"))

    # If consumer, verify ownership
    if session.get("role") == "consumer":
        consumer = database.get_consumer_by_user_id(session["user_id"])
        if bill["consumer_id"] != consumer["consumer_id"]:
            flash("Unauthorized access to invoice.", "danger")
            return redirect(url_for("consumer_dashboard"))

    return render_template("bill_invoice.html", bill=bill)

@app.route("/consumer/complaints", methods=["GET", "POST"])
@consumer_required
def consumer_complaints():
    consumer = database.get_consumer_by_user_id(session["user_id"])
    if request.method == "POST":
        category = request.form.get("category")
        description = request.form.get("description")
        database.add_complaint(consumer["consumer_id"], category, description)
        flash("Your grievance has been registered. Field maintenance will inspect shortly.", "success")
        return redirect(url_for("consumer_complaints"))

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
    units = float(request.args.get("units", 0.0))
    tariff = database.calculate_water_tariff(connection_type, units)
    return jsonify(tariff)

if __name__ == "__main__":
    database.init_db()
    # Check if seed is needed
    conn = database.get_db()
    user_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    conn.close()
    if user_count == 0:
        import seed_data
        seed_data.seed()
    print("Starting Water Supply Monitoring and Consumer Billing System on http://127.0.0.1:5000 ...")
    app.run(debug=True, port=5000)
