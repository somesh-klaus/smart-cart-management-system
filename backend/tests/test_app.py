"""
Tests for Smart Cart Management System backend.
Run with: pytest backend/tests/test_app.py -v
"""
import json
import os
import sys
import tempfile
import pytest

# Make the backend importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# Use a temporary database for tests
TEST_DB = tempfile.mktemp(suffix=".db")
os.environ["TESTING"] = "1"

import backend.app as app_module
app_module.DB_PATH = TEST_DB

from backend.app import app, init_db, check_fraud


@pytest.fixture(autouse=True)
def setup_db():
    """Re-create a fresh database before every test."""
    # Apply the test DB path before each test
    app_module.DB_PATH = TEST_DB
    init_db()
    yield
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# ─────────────────────────────────────────────
# Fraud Detection Logic
# ─────────────────────────────────────────────

class TestFraudDetection:
    def test_no_fraud_within_tolerance(self):
        fraud, pct, msg = check_fraud(100.0, 105.0)
        assert fraud is False
        assert pct == pytest.approx(5.0, abs=0.01)
        assert msg == ""

    def test_fraud_above_threshold(self):
        fraud, pct, msg = check_fraud(100.0, 115.0)
        assert fraud is True
        assert pct == pytest.approx(15.0, abs=0.01)
        assert "mismatch" in msg.lower()

    def test_fraud_below_threshold(self):
        fraud, pct, msg = check_fraud(100.0, 85.0)
        assert fraud is True
        assert pct == pytest.approx(15.0, abs=0.01)

    def test_exact_boundary_no_fraud(self):
        fraud, pct, msg = check_fraud(100.0, 110.0)
        assert fraud is False   # exactly 10 % -> not over threshold

    def test_zero_expected_weight(self):
        fraud, pct, msg = check_fraud(0.0, 50.0)
        assert fraud is False

    def test_exact_match(self):
        fraud, pct, msg = check_fraud(182.0, 182.0)
        assert fraud is False
        assert pct == 0.0


# ─────────────────────────────────────────────
# Products CRUD
# ─────────────────────────────────────────────

class TestProducts:
    def test_list_products_returns_seeded_data(self, client):
        resp = client.get("/api/products")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)
        assert len(data) >= 5  # seeded demo products

    def test_create_product(self, client):
        payload = {
            "rfid_uid":        "AA:BB:CC:DD",
            "name":            "Test Biscuits",
            "price":           0.99,
            "expected_weight": 250.0,
            "category":        "Snacks",
        }
        resp = client.post("/api/products", json=payload)
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["rfid_uid"] == "AA:BB:CC:DD"
        assert data["name"]     == "Test Biscuits"

    def test_create_product_duplicate_uid(self, client):
        payload = {
            "rfid_uid": "A1:B2:C3:D4",   # already seeded
            "name":     "Duplicate",
            "price":    1.0,
            "expected_weight": 100.0,
        }
        resp = client.post("/api/products", json=payload)
        assert resp.status_code == 409

    def test_create_product_missing_fields(self, client):
        resp = client.post("/api/products", json={"name": "Incomplete"})
        assert resp.status_code == 400

    def test_get_product(self, client):
        payload = {
            "rfid_uid": "FF:FF:FF:01", "name": "Chips",
            "price": 1.50, "expected_weight": 100.0,
        }
        created = client.post("/api/products", json=payload).get_json()
        resp = client.get(f"/api/products/{created['id']}")
        assert resp.status_code == 200
        assert resp.get_json()["name"] == "Chips"

    def test_get_product_not_found(self, client):
        resp = client.get("/api/products/99999")
        assert resp.status_code == 404

    def test_update_product(self, client):
        payload = {
            "rfid_uid": "FF:FF:FF:02", "name": "Old Name",
            "price": 1.0, "expected_weight": 100.0,
        }
        created = client.post("/api/products", json=payload).get_json()
        resp = client.put(f"/api/products/{created['id']}", json={"name": "New Name", "price": 2.0})
        assert resp.status_code == 200
        assert resp.get_json()["name"] == "New Name"
        assert resp.get_json()["price"] == 2.0

    def test_delete_product(self, client):
        payload = {
            "rfid_uid": "FF:FF:FF:03", "name": "Delete Me",
            "price": 0.5, "expected_weight": 50.0,
        }
        created = client.post("/api/products", json=payload).get_json()
        resp = client.delete(f"/api/products/{created['id']}")
        assert resp.status_code == 200
        assert client.get(f"/api/products/{created['id']}").status_code == 404


# ─────────────────────────────────────────────
# Scan Endpoint
# ─────────────────────────────────────────────

class TestScan:
    def test_scan_known_product_no_fraud(self, client):
        resp = client.post("/api/scan", json={
            "cart_id":       "CART_TEST_1",
            "rfid_uid":      "A1:B2:C3:D4",   # Apple, expected 182g
            "actual_weight": 180.0,             # within 10 %
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["found"]          is True
        assert data["product_name"]   == "Apple"
        assert data["fraud_detected"] is False
        assert data["cart_total"]     == pytest.approx(1.50, abs=0.01)
        assert data["item_count"]     == 1

    def test_scan_known_product_fraud_detected(self, client):
        resp = client.post("/api/scan", json={
            "cart_id":       "CART_TEST_2",
            "rfid_uid":      "A1:B2:C3:D4",   # Apple, expected 182g
            "actual_weight": 50.0,              # way off
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["fraud_detected"]  is True
        assert "mismatch" in data["alert_message"].lower()

    def test_scan_unknown_product(self, client):
        resp = client.post("/api/scan", json={
            "cart_id":       "CART_TEST_3",
            "rfid_uid":      "ZZ:ZZ:ZZ:ZZ",
            "actual_weight": 100.0,
        })
        assert resp.status_code == 404
        assert resp.get_json()["found"] is False

    def test_scan_missing_rfid(self, client):
        resp = client.post("/api/scan", json={"cart_id": "CART_TEST_4"})
        assert resp.status_code == 400

    def test_scan_invalid_json(self, client):
        resp = client.post("/api/scan", data="not json",
                           content_type="text/plain")
        assert resp.status_code == 400

    def test_multiple_scans_accumulate_total(self, client):
        client.post("/api/scan", json={
            "cart_id": "CART_ACCUM", "rfid_uid": "A1:B2:C3:D4",
            "actual_weight": 180.0,
        })
        resp = client.post("/api/scan", json={
            "cart_id": "CART_ACCUM", "rfid_uid": "E5:F6:07:H8",
            "actual_weight": 1020.0,
        })
        data = resp.get_json()
        # Apple 1.50 + Milk 2.20 = 3.70
        assert data["cart_total"] == pytest.approx(3.70, abs=0.01)
        assert data["item_count"] == 2


# ─────────────────────────────────────────────
# Cart Session Endpoints
# ─────────────────────────────────────────────

class TestCartSession:
    def _scan(self, client, cart_id):
        client.post("/api/scan", json={
            "cart_id": cart_id, "rfid_uid": "A1:B2:C3:D4",
            "actual_weight": 180.0,
        })

    def test_get_cart(self, client):
        self._scan(client, "CART_GET")
        resp = client.get("/api/carts/CART_GET")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["item_count"] == 1
        assert len(data["items"]) == 1

    def test_checkout(self, client):
        self._scan(client, "CART_CHECKOUT")
        resp = client.post("/api/carts/CART_CHECKOUT/checkout")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["total"] == pytest.approx(1.50, abs=0.01)
        resp2 = client.post("/api/carts/CART_CHECKOUT/checkout")
        assert resp2.status_code == 404

    def test_clear_cart(self, client):
        self._scan(client, "CART_CLEAR")
        resp = client.post("/api/carts/CART_CLEAR/clear")
        assert resp.status_code == 200
        assert client.get("/api/carts/CART_CLEAR").status_code == 404

    def test_list_carts(self, client):
        self._scan(client, "CART_LIST_A")
        self._scan(client, "CART_LIST_B")
        resp = client.get("/api/carts")
        assert resp.status_code == 200
        cart_ids = {c["cart_id"] for c in resp.get_json()}
        assert "CART_LIST_A" in cart_ids
        assert "CART_LIST_B" in cart_ids


# ─────────────────────────────────────────────
# Fraud Logs
# ─────────────────────────────────────────────

class TestFraudLogs:
    def test_fraud_log_created_on_fraud(self, client):
        client.post("/api/scan", json={
            "cart_id":       "CART_FRAUD",
            "rfid_uid":      "A1:B2:C3:D4",
            "actual_weight": 10.0,   # fraud
        })
        resp = client.get("/api/fraud-logs")
        assert resp.status_code == 200
        logs = resp.get_json()
        assert any(l["cart_id"] == "CART_FRAUD" for l in logs)

    def test_no_fraud_log_on_valid_scan(self, client):
        client.post("/api/scan", json={
            "cart_id":       "CART_VALID",
            "rfid_uid":      "A1:B2:C3:D4",
            "actual_weight": 182.0,
        })
        resp = client.get("/api/fraud-logs")
        logs = resp.get_json()
        assert not any(l["cart_id"] == "CART_VALID" for l in logs)


# ─────────────────────────────────────────────
# Stats
# ─────────────────────────────────────────────

class TestStats:
    def test_stats_endpoint(self, client):
        resp = client.get("/api/stats")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "active_carts"   in data
        assert "total_products" in data
        assert "fraud_today"    in data
        assert "revenue_today"  in data

    def test_stats_product_count(self, client):
        resp = client.get("/api/stats")
        data = resp.get_json()
        assert data["total_products"] >= 5   # seeded products
