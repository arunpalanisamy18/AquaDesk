# AquaFlow — Water Supply Monitoring & Consumer Billing System
### Database Management System (DBMS) Academic Capstone Project

AquaFlow is a full-stack Water Grid Telemetry and Consumer Billing System designed with a **Dual Dashboard Architecture** (Administrator Portal & Consumer Portal).

---

## 🌟 Key Features

### 1. Dual Dashboard Architecture
* **Admin Dashboard (`/admin/dashboard`)**:
  * Real-time grid monitoring of 4 municipal water distribution zones.
  * Live reservoir capacity (%) progress bars with threshold color coding.
  * Pipeline pressure telemetry (PSI), water quality index (pH & TDS ppm).
  * Morning and evening domestic water supply schedule controls.
  * Citizen advisory & outage notice broadcasting system.
  * **Bill Generator Engine**: Select any consumer, input current meter readings, and auto-compute progressive slab tariffs. When generated, the bill **instantly updates in the consumer's dashboard**.
  * Grievance redressal desk for inspecting and resolving consumer complaints.

* **Consumer Dashboard (`/consumer/dashboard`)**:
  * Personalized profile showing Account Number, Meter Serial, and Assigned Distribution Zone.
  * **Live Supply Telemetry**: Real-time status for their specific ward (Water Flowing Now / Scheduled / Maintenance Shutoff).
  * Today's scheduled supply timings (Morning slot & Evening slot).
  * **Prominent Bill Notification Banner**: Displays newly generated utility bills added by the Admin with amount, consumed units, and due date.
  * **Instant Online Bill Payment**: Simulated payment gateway (UPI QR / Debit Card / Net Banking) with instantaneous receipt generation and automatic database status update to `PAID`.
  * Visual water consumption trend chart (Chart.js) across past billing cycles.
  * Printable official Municipal Water Utility Tax Invoices (`/bill/<id>/invoice`).
  * Citizen grievance reporting module (low pressure, murky water, pipe leakages).

---

## 🗄️ Database Management System (DBMS) Architecture

### Entity-Relationship Structure
1. **`users`**: Authentication credentials, hashed passwords, roles (`admin`, `consumer`), and contact details.
2. **`supply_zones`**: Water distribution wards, reservoirs, storage levels, pressure, supply status, and time slots.
3. **`consumers`**: Consumer account numbers (`WTR-xxxx`), meter numbers (`MTR-xxxx`), connection type (`Residential`, `Commercial`, `Industrial`), and assigned zone (Foreign Key).
4. **`bills`**: Billing cycles, previous reading, current reading, units consumed (kL), base fee, slab-calculated consumption charge, surcharge, due date, and payment status (`UNPAID`, `PAID`).
5. **`payments`**: Transaction records, unique receipt numbers (`RCPT-xxxx`), payment methods, and timestamps.
6. **`supply_alerts`**: Zone-targeted or city-wide outage notices and chlorination advisories.
7. **`complaints`**: Citizen grievances, categories, and administrative resolution notes.

### Advanced DBMS Features Implemented
* **Referential Integrity**: Cascading deletes on dependent child records and restricted deletes on parent zones.
* **Database Triggers**:
  * `trg_update_consumer_meter_reading`: Automatically synchronizes `last_meter_reading` in the `consumers` table whenever a new bill is posted.
  * `trg_mark_bill_paid`: Automatically updates the bill status to `'PAID'` upon inserting a valid transaction into the `payments` table.
* **Database Views**:
  * `vw_bills_detailed`: Multi-table JOIN combining bills, consumers, users, and supply zones.
  * `vw_consumer_balances`: Aggregated financial summary of total paid vs pending dues.
  * `vw_zone_monitoring`: Real-time status combining zone telemetry with connected consumer counts.

---

## 🚀 Quick Start Guide

### Prerequisites
* Python 3.10+ (Installed on system)
* Flask, Werkzeug (Pre-installed)

### 1. Launch the Application
In your terminal, navigate to the project directory and run:
```powershell
python app.py
```
The application generates a temporary session key when `SECRET_KEY` is not set. For a stable key across restarts, set a private key in PowerShell before launching:
```powershell
$env:SECRET_KEY = python -c "import secrets; print(secrets.token_hex(32))"
python app.py
```
Keep this key private and do not commit it.

The server will start at:
```
http://127.0.0.1:5000
```

### 2. Ready-to-Use Demo Credentials
| Role | Username | Password | Purpose / Features |
| :--- | :--- | :--- | :--- |
| **Admin** | `admin` | `admin123` | Add bills, adjust zone telemetry, post outage notices |
| **Consumer 1** | `rahul_sharma` | `password123` | Residential consumer (North Zone) with active unpaid bill |
| **Consumer 2** | `priya_patel` | `password123` | Residential consumer (South Zone) |
| **Consumer 3** | `apex_hospital` | `password123` | Commercial consumer (East Commercial Sector) |
| **Consumer 4** | `sun_textiles` | `password123` | Industrial consumer (West Industrial Park) |

> 💡 **Presentation Tip**: Use the **"Demo Switcher"** button in the top-right navigation bar to switch between Admin and Consumers in 1 click during professor viva/examinations without retyping passwords!

---

## 🧪 Step-by-Step Viva Demonstration Workflow

To demonstrate the core requirement (*"If admin adds the bills to the consumer it should add it in consumers dashboard"*):

1. **Sign in as Admin** (or click "Instant Admin Demo"):
   * Go to **"Add & Manage Bills"** (`/admin/billing`).
   * In the **Bill Generator**, select **Rahul Sharma (WTR-1001)**.
   * Notice how the previous meter reading auto-populates (`142.50 kL`).
   * Enter a current reading (e.g. `165.00 kL`).
   * Watch the **Live Tariff Engine** instantly calculate consumed units (22.50 kL), slab charges, tax surcharge, and total amount.
   * Click **"Generate & Post Bill to Consumer Dashboard"**.

2. **Switch to Consumer Dashboard**:
   * Click the **"Switch Role"** dropdown in the top navbar and pick **Rahul (Residential - North)**.
   * **Result**: A prominent amber notification banner immediately alerts:
     > *"New Utility Bill Added by Admin — Water Bill for November 2026"*
   * The new bill number, consumption, and amount due are highlighted with an active **"Pay Now"** button.

3. **Complete Payment Simulation**:
   * Click **"Pay Now"**.
   * Select **UPI / QR Code** and click **"Confirm & Pay"**.
   * **Result**: The database trigger fires, changes status to **PAID**, and generates an official Municipal Receipt.
   * Click **"Receipt"** to view and print the official **Tax Invoice**.

4. **Verify on Admin Portal**:
   * Switch back to **Admin**.
   * Notice total collected revenue increased, and the bill status is marked **PAID** in the master ledger!
