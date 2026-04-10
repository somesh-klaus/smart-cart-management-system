# Smart Cart Management System – Backend
# Flask REST API with SQLite database, WebSocket support, and fraud detection

import os
import time
import json
import logging
from datetime import datetime, timezone

from flask import Flask, request, jsonify, render_template_string
from flask_socketio import SocketIO, emit
import sqlite3

# ─────────────────────────────────────────────
# App Configuration
# ─────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, "smart_cart.db")

FRAUD_THRESHOLD_PCT = 10.0   # flag if weight deviates > 10 %

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

FRONTEND_DIR = os.path.join(BASE_DIR, "..", "frontend")

app = Flask(
    __name__,
    template_folder=FRONTEND_DIR,
    static_folder=FRONTEND_DIR,
    static_url_path="",
)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "smart-cart-secret-key")

socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# ─────────────────────────────────────────────
# Database Helpers
# ─────────────────────────────────────────────

def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    """Create tables and seed demo products if empty."""
    conn = get_db()
    cur  = conn.cursor()

    cur.executescript("""
        CREATE TABLE IF NOT EXISTS products (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            rfid_uid        TEXT    UNIQUE NOT NULL,
            name            TEXT    NOT NULL,
            price           REAL    NOT NULL,
            expected_weight REAL    NOT NULL,
            category        TEXT    DEFAULT 'General',
            created_at      TEXT    DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS cart_sessions (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            cart_id    TEXT NOT NULL,
            started_at TEXT DEFAULT (datetime('now')),
            ended_at   TEXT,
            total      REAL DEFAULT 0.0,
            status     TEXT DEFAULT 'active'
        );

        CREATE TABLE IF NOT EXISTS cart_items (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id    INTEGER NOT NULL REFERENCES cart_sessions(id),
            cart_id       TEXT    NOT NULL,
            rfid_uid      TEXT    NOT NULL,
            product_name  TEXT    NOT NULL,
            price         REAL    NOT NULL,
            expected_weight REAL  NOT NULL,
            actual_weight   REAL  NOT NULL,
            fraud_detected  INTEGER DEFAULT 0,
            scanned_at      TEXT  DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS fraud_logs (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            cart_id        TEXT NOT NULL,
            rfid_uid       TEXT NOT NULL,
            product_name   TEXT NOT NULL,
            expected_weight REAL NOT NULL,
            actual_weight   REAL NOT NULL,
            deviation_pct   REAL NOT NULL,
            flagged_at      TEXT DEFAULT (datetime('now'))
        );
    """)

    # Seed demo products
    demo = [
        ("A1:B2:C3:D4", "Apple",        1.50,  182.0, "Fruit"),
        ("E5:F6:07:H8", "Milk 1L",      2.20, 1030.0, "Dairy"),
        ("I9:J0:K1:L2", "Bread Loaf",   1.80,  400.0, "Bakery"),
        ("M3:N4:O5:P6", "Orange Juice", 2.50,  950.0, "Beverages"),
        ("Q7:R8:S9:T0", "Yoghurt 500g", 1.20,  500.0, "Dairy"),
    ]
    cur.executemany(
        """INSERT OR IGNORE INTO products (rfid_uid, name, price, expected_weight, category)
           VALUES (?, ?, ?, ?, ?)""",
        demo,
    )
    conn.commit()
    conn.close()
    log.info("Database initialised at %s", DB_PATH)


# ─────────────────────────────────────────────
# Cart Session Helpers
# ─────────────────────────────────────────────

def get_or_create_session(cart_id: str, conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT id FROM cart_sessions WHERE cart_id=? AND status='active'",
        (cart_id,),
    ).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO cart_sessions (cart_id) VALUES (?)", (cart_id,)
    )
    conn.commit()
    return cur.lastrowid


def session_total(session_id: int, conn: sqlite3.Connection) -> float:
    row = conn.execute(
        "SELECT SUM(price) AS total FROM cart_items WHERE session_id=? AND fraud_detected=0",
        (session_id,),
    ).fetchone()
    return round(row["total"] or 0.0, 2)


def session_item_count(session_id: int, conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS cnt FROM cart_items WHERE session_id=?",
        (session_id,),
    ).fetchone()
    return row["cnt"]


# ─────────────────────────────────────────────
# Fraud Detection
# ─────────────────────────────────────────────

def check_fraud(expected: float, actual: float) -> tuple[bool, float, str]:
    """Determine whether an item's measured weight indicates fraud.

    Args:
        expected: The expected weight (in grams) from the product catalog.
        actual:   The actual weight (in grams) measured by the load cell.

    Returns:
        A 3-tuple of:
          - bool:  True if the deviation exceeds FRAUD_THRESHOLD_PCT.
          - float: The deviation percentage (always non-negative).
          - str:   A human-readable alert message, or "" when no fraud.
    """
    if expected == 0:
        return False, 0.0, ""
    deviation_pct = abs(actual - expected) / expected * 100.0
    if deviation_pct > FRAUD_THRESHOLD_PCT:
        msg = (
            f"Weight mismatch! Expected {expected:.0f}g, "
            f"got {actual:.0f}g ({deviation_pct:.1f}% off)"
        )
        return True, round(deviation_pct, 2), msg
    return False, round(deviation_pct, 2), ""


# ─────────────────────────────────────────────
# REST API – Scan Endpoint
# ─────────────────────────────────────────────

@app.route("/api/scan", methods=["POST"])
def scan():
    """Receive RFID scan + weight from ESP32, return product info and fraud status."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    cart_id       = data.get("cart_id", "UNKNOWN")
    rfid_uid      = data.get("rfid_uid", "").upper().strip()
    actual_weight = float(data.get("actual_weight", 0.0))

    if not rfid_uid:
        return jsonify({"error": "rfid_uid required"}), 400

    conn = get_db()
    try:
        product = conn.execute(
            "SELECT * FROM products WHERE rfid_uid=?", (rfid_uid,)
        ).fetchone()

        if not product:
            conn.close()
            return jsonify({
                "found":        False,
                "rfid_uid":     rfid_uid,
                "cart_id":      cart_id,
                "message":      "Product not found in catalog",
                "fraud_detected": False,
            }), 404

        session_id = get_or_create_session(cart_id, conn)

        fraud_detected, deviation_pct, alert_msg = check_fraud(
            product["expected_weight"], actual_weight
        )

        # Insert cart item
        conn.execute(
            """INSERT INTO cart_items
               (session_id, cart_id, rfid_uid, product_name, price,
                expected_weight, actual_weight, fraud_detected)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                cart_id,
                rfid_uid,
                product["name"],
                product["price"],
                product["expected_weight"],
                actual_weight,
                1 if fraud_detected else 0,
            ),
        )

        # Log fraud
        if fraud_detected:
            conn.execute(
                """INSERT INTO fraud_logs
                   (cart_id, rfid_uid, product_name, expected_weight,
                    actual_weight, deviation_pct)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    cart_id,
                    rfid_uid,
                    product["name"],
                    product["expected_weight"],
                    actual_weight,
                    deviation_pct,
                ),
            )

        # Update session total
        total      = session_total(session_id, conn)
        item_count = session_item_count(session_id, conn)
        conn.execute(
            "UPDATE cart_sessions SET total=? WHERE id=?", (total, session_id)
        )
        conn.commit()

        response_payload = {
            "found":           True,
            "cart_id":         cart_id,
            "rfid_uid":        rfid_uid,
            "product_name":    product["name"],
            "price":           product["price"],
            "expected_weight": product["expected_weight"],
            "actual_weight":   actual_weight,
            "deviation_pct":   deviation_pct,
            "fraud_detected":  fraud_detected,
            "alert_message":   alert_msg,
            "cart_total":      total,
            "item_count":      item_count,
        }

        # Broadcast update to dashboard via WebSocket
        socketio.emit(
            "cart_update",
            {
                "cart_id":        cart_id,
                "product_name":   product["name"],
                "price":          product["price"],
                "fraud_detected": fraud_detected,
                "alert_message":  alert_msg,
                "cart_total":     total,
                "item_count":     item_count,
                "scanned_at":     datetime.now(timezone.utc).isoformat(),
            },
        )

        log.info(
            "Scanned %s on %s | weight=%.1fg | fraud=%s",
            product["name"], cart_id, actual_weight, fraud_detected,
        )
        return jsonify(response_payload), 200

    finally:
        conn.close()


# ─────────────────────────────────────────────
# REST API – Products (CRUD)
# ─────────────────────────────────────────────

@app.route("/api/products", methods=["GET"])
def list_products():
    conn = get_db()
    rows = conn.execute("SELECT * FROM products ORDER BY name").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows]), 200


@app.route("/api/products", methods=["POST"])
def create_product():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400
    required = ["rfid_uid", "name", "price", "expected_weight"]
    missing  = [f for f in required if f not in data]
    if missing:
        return jsonify({"error": f"Missing fields: {missing}"}), 400
    conn = get_db()
    try:
        cur = conn.execute(
            """INSERT INTO products (rfid_uid, name, price, expected_weight, category)
               VALUES (?, ?, ?, ?, ?)""",
            (
                data["rfid_uid"].upper().strip(),
                data["name"],
                float(data["price"]),
                float(data["expected_weight"]),
                data.get("category", "General"),
            ),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM products WHERE id=?", (cur.lastrowid,)).fetchone()
        return jsonify(dict(row)), 201
    except sqlite3.IntegrityError:
        return jsonify({"error": "rfid_uid already exists"}), 409
    finally:
        conn.close()


@app.route("/api/products/<int:product_id>", methods=["GET"])
def get_product(product_id):
    conn = get_db()
    row  = conn.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "Not found"}), 404
    return jsonify(dict(row)), 200


@app.route("/api/products/<int:product_id>", methods=["PUT"])
def update_product(product_id):
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400
    conn = get_db()
    row  = conn.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Not found"}), 404
    conn.execute(
        """UPDATE products SET name=?, price=?, expected_weight=?, category=?
           WHERE id=?""",
        (
            data.get("name",            row["name"]),
            float(data.get("price",     row["price"])),
            float(data.get("expected_weight", row["expected_weight"])),
            data.get("category",        row["category"]),
            product_id,
        ),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
    conn.close()
    return jsonify(dict(row)), 200


@app.route("/api/products/<int:product_id>", methods=["DELETE"])
def delete_product(product_id):
    conn = get_db()
    row  = conn.execute("SELECT id FROM products WHERE id=?", (product_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Not found"}), 404
    conn.execute("DELETE FROM products WHERE id=?", (product_id,))
    conn.commit()
    conn.close()
    return jsonify({"message": "Deleted"}), 200


# ─────────────────────────────────────────────
# REST API – Cart Sessions
# ─────────────────────────────────────────────

@app.route("/api/carts", methods=["GET"])
def list_carts():
    conn  = get_db()
    rows  = conn.execute(
        "SELECT * FROM cart_sessions ORDER BY started_at DESC"
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows]), 200


@app.route("/api/carts/<cart_id>", methods=["GET"])
def get_cart(cart_id):
    conn    = get_db()
    session = conn.execute(
        "SELECT * FROM cart_sessions WHERE cart_id=? AND status='active'",
        (cart_id,),
    ).fetchone()
    if not session:
        conn.close()
        return jsonify({"error": "No active session"}), 404
    items = conn.execute(
        "SELECT * FROM cart_items WHERE session_id=? ORDER BY scanned_at",
        (session["id"],),
    ).fetchall()
    conn.close()
    return jsonify({
        "session":    dict(session),
        "items":      [dict(i) for i in items],
        "item_count": len(items),
        "total":      session["total"],
    }), 200


@app.route("/api/carts/<cart_id>/checkout", methods=["POST"])
def checkout(cart_id):
    conn = get_db()
    session = conn.execute(
        "SELECT * FROM cart_sessions WHERE cart_id=? AND status='active'",
        (cart_id,),
    ).fetchone()
    if not session:
        conn.close()
        return jsonify({"error": "No active session"}), 404
    items = conn.execute(
        "SELECT * FROM cart_items WHERE session_id=?",
        (session["id"],),
    ).fetchall()
    total = session_total(session["id"], conn)
    conn.execute(
        "UPDATE cart_sessions SET status='completed', ended_at=datetime('now'), total=? WHERE id=?",
        (total, session["id"]),
    )
    conn.commit()
    conn.close()

    socketio.emit("checkout", {"cart_id": cart_id, "total": total})
    log.info("Checkout cart=%s total=%.2f", cart_id, total)
    return jsonify({
        "cart_id":    cart_id,
        "total":      total,
        "item_count": len(items),
        "message":    "Checkout complete",
    }), 200


@app.route("/api/carts/<cart_id>/clear", methods=["POST"])
def clear_cart(cart_id):
    """End the active session without checking out (admin reset)."""
    conn = get_db()
    conn.execute(
        "UPDATE cart_sessions SET status='cleared', ended_at=datetime('now') WHERE cart_id=? AND status='active'",
        (cart_id,),
    )
    conn.commit()
    conn.close()
    return jsonify({"message": f"Cart {cart_id} cleared"}), 200


# ─────────────────────────────────────────────
# REST API – Fraud Logs
# ─────────────────────────────────────────────

@app.route("/api/fraud-logs", methods=["GET"])
def fraud_logs():
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM fraud_logs ORDER BY flagged_at DESC LIMIT 200"
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows]), 200


# ─────────────────────────────────────────────
# REST API – Dashboard Stats
# ─────────────────────────────────────────────

@app.route("/api/stats", methods=["GET"])
def stats():
    conn = get_db()
    active_carts  = conn.execute(
        "SELECT COUNT(*) AS c FROM cart_sessions WHERE status='active'"
    ).fetchone()["c"]
    total_products = conn.execute("SELECT COUNT(*) AS c FROM products").fetchone()["c"]
    fraud_today   = conn.execute(
        "SELECT COUNT(*) AS c FROM fraud_logs WHERE DATE(flagged_at)=DATE('now')"
    ).fetchone()["c"]
    revenue_today = conn.execute(
        """SELECT COALESCE(SUM(ci.price),0) AS rev
           FROM cart_items ci
           JOIN cart_sessions cs ON cs.id=ci.session_id
           WHERE DATE(ci.scanned_at)=DATE('now') AND ci.fraud_detected=0"""
    ).fetchone()["rev"]
    conn.close()
    return jsonify({
        "active_carts":   active_carts,
        "total_products": total_products,
        "fraud_today":    fraud_today,
        "revenue_today":  round(revenue_today, 2),
    }), 200


# ─────────────────────────────────────────────
# WebSocket Events
# ─────────────────────────────────────────────

@socketio.on("connect")
def handle_connect():
    log.info("Dashboard client connected: %s", request.sid)
    emit("connected", {"message": "Connected to Smart Cart server"})


@socketio.on("disconnect")
def handle_disconnect():
    log.info("Dashboard client disconnected: %s", request.sid)


@socketio.on("subscribe_cart")
def subscribe_cart(data):
    cart_id = data.get("cart_id", "")
    log.info("Client subscribed to cart: %s", cart_id)
    emit("subscribed", {"cart_id": cart_id})


# ─────────────────────────────────────────────
# Frontend Serve (optional fallback)
# ─────────────────────────────────────────────

@app.route("/")
def index():
    index_path = os.path.join(BASE_DIR, "..", "frontend", "index.html")
    if os.path.exists(index_path):
        with open(index_path) as f:
            return f.read()
    return "<h1>Smart Cart Management System</h1><p>Frontend not found.</p>"


# ─────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    log.info("Starting Smart Cart server on port 5000")
    socketio.run(app, host="0.0.0.0", port=5000, debug=False)
