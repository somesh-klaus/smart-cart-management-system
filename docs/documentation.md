# Smart Cart Management System – Documentation

## Table of Contents
1. [Architecture Overview](#architecture-overview)
2. [Hardware Components](#hardware-components)
3. [Circuit Wiring Guide](#circuit-wiring-guide)
4. [Firmware Setup (ESP32)](#firmware-setup-esp32)
5. [Backend Setup (Flask)](#backend-setup-flask)
6. [Frontend (Web Dashboard)](#frontend-web-dashboard)
7. [API Documentation](#api-documentation)
8. [Fraud Detection Logic](#fraud-detection-logic)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     Physical Cart                               │
│                                                                 │
│  ┌──────────┐   SPI    ┌─────────┐                             │
│  │  RC522   │─────────▶│         │                             │
│  │  RFID    │          │  ESP32  │──── Wi-Fi ────▶  Flask API  │
│  └──────────┘          │  DevKit │                    │        │
│  ┌──────────┐   GPIO   │         │◀─── JSON ─────     │        │
│  │  HX711   │─────────▶│         │                    │        │
│  │ Load Cell│          └────┬────┘             SQLite DB        │
│  └──────────┘               │                    │             │
│  ┌──────────┐   I2C         │                    │             │
│  │ SSD1306  │◀──────────────┘               WebSocket          │
│  │   OLED   │                                    │             │
│  └──────────┘                            Web Dashboard         │
│  ┌──────────┐   GPIO                    (HTML/CSS/JS)          │
│  │  Buzzer  │◀──────────────────────────────────────────────── │
│  └──────────┘                                                   │
└─────────────────────────────────────────────────────────────────┘
```

### Data Flow
1. Customer places item on scale and scans RFID tag.
2. ESP32 reads UID via RC522 and weight via HX711.
3. ESP32 sends `POST /api/scan` with `{cart_id, rfid_uid, actual_weight}`.
4. Flask looks up the product, runs fraud detection, saves to SQLite.
5. Response returned to ESP32: product info + fraud status.
6. OLED shows cart total; buzzer fires on fraud.
7. Flask broadcasts `cart_update` event via Socket.IO to all dashboard clients.
8. Dashboard updates in real time.

---

## Hardware Components

| Component | Model / Spec | Qty |
|-----------|-------------|-----|
| Microcontroller | ESP32 DevKit V1 (30-pin) | 1 |
| RFID Reader | MFRC522 RC522 (13.56 MHz) | 1 |
| Load Cell Amplifier | HX711 24-bit ADC | 1 |
| Load Cell | 5 kg single-point load cell | 1 |
| OLED Display | SSD1306 128×64 I2C | 1 |
| Active Buzzer | 5V, 85 dB | 1 |
| Power Supply | 5V / 2A USB or LiPo + regulator | 1 |
| Jumper Wires | Male-to-female, assorted | ~30 |
| Breadboard or PCB | Full-size breadboard | 1 |

---

## Circuit Wiring Guide

### RC522 RFID Reader (SPI)

| RC522 Pin | ESP32 Pin | Description |
|-----------|-----------|-------------|
| VCC | 3.3V | Power (3.3 V only!) |
| GND | GND | Ground |
| RST | GPIO 22 | Reset |
| SDA (SS) | GPIO 5 | SPI Chip Select |
| SCK | GPIO 18 | SPI Clock |
| MOSI | GPIO 23 | SPI MOSI |
| MISO | GPIO 19 | SPI MISO |
| IRQ | Not connected | |

> **Warning:** RC522 operates at 3.3 V. Do not connect VCC to 5V.

### HX711 Load Cell Amplifier

| HX711 Pin | ESP32 Pin | Description |
|-----------|-----------|-------------|
| VCC | 5V | Power |
| GND | GND | Ground |
| DT (DOUT) | GPIO 16 | Serial Data |
| SCK | GPIO 17 | Serial Clock |

**Load Cell Wiring to HX711:**
- Red wire → E+ (Excitation+)
- Black wire → E- (Excitation−)
- White wire → A+ (Signal+)
- Green wire → A- (Signal−)

> Wiring colours may vary. Refer to your load cell's datasheet.

### SSD1306 OLED Display (I2C)

| OLED Pin | ESP32 Pin | Description |
|----------|-----------|-------------|
| VCC | 3.3V | Power |
| GND | GND | Ground |
| SDA | GPIO 21 | I2C Data |
| SCL | GPIO 22 | I2C Clock (shared with RC522 RST line — use different GPIO if conflict occurs) |

> Default I2C address: `0x3C`. Some modules use `0x3D`.

### Buzzer

| Buzzer Pin | ESP32 Pin |
|-----------|-----------|
| + (VCC) | GPIO 4 |
| − (GND) | GND |

> A 100Ω resistor in series is recommended to limit current.

### Full Pin Summary

```
ESP32 GPIO  │ Connected to
────────────┼──────────────────────────
4           │ Buzzer (+)
5           │ RC522 SDA/SS
16          │ HX711 DOUT
17          │ HX711 SCK
18          │ RC522 SCK  (SPI CLK)
19          │ RC522 MISO (SPI MISO)
21          │ OLED SDA   (I2C)
22          │ OLED SCL + RC522 RST
23          │ RC522 MOSI (SPI MOSI)
3.3V        │ RC522 VCC, OLED VCC
5V          │ HX711 VCC
GND         │ All GND
```

---

## Firmware Setup (ESP32)

### Prerequisites
- [Arduino IDE](https://www.arduino.cc/en/software) ≥ 2.0, or PlatformIO
- ESP32 board package installed (add `https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json` to Board Manager URLs)

### Required Libraries (install via Library Manager)
| Library | Author |
|---------|--------|
| MFRC522 | GithubCommunity |
| HX711 Arduino Library | bogde |
| Adafruit SSD1306 | Adafruit |
| Adafruit GFX Library | Adafruit |
| ArduinoJson | Benoit Blanchon |

### Configuration (`firmware/smart_cart.ino`)
Edit the top section:
```cpp
#define WIFI_SSID      "YOUR_WIFI_SSID"
#define WIFI_PASSWORD  "YOUR_WIFI_PASSWORD"
#define SERVER_URL     "http://192.168.1.100:5000"  // Flask server IP
#define CART_ID        "CART_001"
```

### Load Cell Calibration
1. Flash firmware with a known weight (e.g., 500 g) on the scale.
2. Read raw value via Serial Monitor.
3. Adjust `CALIBRATION_FACTOR` until `scale.get_units()` matches the known weight.

### Flashing
1. Connect ESP32 via USB.
2. Select **Board:** `ESP32 Dev Module`, **Port:** your COM/ttyUSB.
3. Click **Upload**.

---

## Backend Setup (Flask)

### Requirements
- Python 3.10+
- pip

### Installation
```bash
cd backend
pip install -r requirements.txt
```

### Running the Server
```bash
python app.py
```

The server starts on `http://0.0.0.0:5000`.

### Environment Variables
| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | `smart-cart-secret-key` | Flask session secret |

### Database
SQLite file created automatically at `backend/smart_cart.db`. Demo products are seeded on first run.

---

## Frontend (Web Dashboard)

### Serving
The Flask backend automatically serves `frontend/index.html` at `http://<server>:5000/`.

Alternatively, open `frontend/index.html` directly in a browser (real-time WebSocket features require the Flask server to be running and reachable).

### Pages
| Page | Description |
|------|-------------|
| **Dashboard** | Live stats, cart monitor, activity feed |
| **Product Catalog** | CRUD for products mapped to RFID UIDs |
| **Cart Sessions** | All sessions with checkout action |
| **Fraud Logs** | All fraud events with deviation % |
| **Admin** | Simulate RFID scans, quick cart actions |

---

## API Documentation

Base URL: `http://<server>:5000`

### POST /api/scan
Receive RFID scan + weight from ESP32.

**Request Body (JSON):**
```json
{
  "cart_id":       "CART_001",
  "rfid_uid":      "A1:B2:C3:D4",
  "actual_weight": 180.5
}
```

**Response 200:**
```json
{
  "found":           true,
  "cart_id":         "CART_001",
  "rfid_uid":        "A1:B2:C3:D4",
  "product_name":    "Apple",
  "price":           1.50,
  "expected_weight": 182.0,
  "actual_weight":   180.5,
  "deviation_pct":   0.82,
  "fraud_detected":  false,
  "alert_message":   "",
  "cart_total":      1.50,
  "item_count":      1
}
```

**Response 404** (product not in catalog):
```json
{ "found": false, "message": "Product not found in catalog" }
```

---

### GET /api/products
List all products.

**Response 200:** Array of product objects.

---

### POST /api/products
Create a new product.

**Request Body:**
```json
{
  "rfid_uid":        "XX:XX:XX:XX",
  "name":            "Crisps 100g",
  "price":           0.99,
  "expected_weight": 100.0,
  "category":        "Snacks"
}
```
**Response 201:** Created product object.

---

### GET /api/products/{id}
Get a single product by ID.

---

### PUT /api/products/{id}
Update product fields (rfid_uid is immutable).

---

### DELETE /api/products/{id}
Delete a product.

---

### GET /api/carts
List all cart sessions.

---

### GET /api/carts/{cart_id}
Get active session + item list for a cart.

**Response 200:**
```json
{
  "session":    { ... },
  "items":      [ ... ],
  "item_count": 3,
  "total":      5.20
}
```

---

### POST /api/carts/{cart_id}/checkout
Complete checkout for the active session.

**Response 200:**
```json
{
  "cart_id":    "CART_001",
  "total":      5.20,
  "item_count": 3,
  "message":    "Checkout complete"
}
```

---

### POST /api/carts/{cart_id}/clear
Reset (clear) the active session without billing.

---

### GET /api/fraud-logs
Get last 200 fraud events ordered by most recent.

---

### GET /api/stats
Dashboard statistics.

**Response 200:**
```json
{
  "active_carts":   2,
  "total_products": 10,
  "fraud_today":    1,
  "revenue_today":  42.50
}
```

---

### WebSocket Events (Socket.IO)

| Event (Server → Client) | Payload | Description |
|--------------------------|---------|-------------|
| `connected` | `{message}` | Fired on connect |
| `cart_update` | `{cart_id, product_name, price, fraud_detected, alert_message, cart_total, item_count, scanned_at}` | Fired after every scan |
| `checkout` | `{cart_id, total}` | Fired after checkout |

| Event (Client → Server) | Payload | Description |
|--------------------------|---------|-------------|
| `subscribe_cart` | `{cart_id}` | Subscribe to a specific cart's updates |

---

## Fraud Detection Logic

Weight fraud is detected when the actual weight of an item deviates more than **10%** from the expected weight registered in the product catalog.

```
deviation_pct = |actual_weight - expected_weight| / expected_weight × 100

if deviation_pct > 10.0:
    fraud = True
    → Log to fraud_logs table
    → Include fraud_detected=True in API response
    → Broadcast alert via WebSocket
    → ESP32 triggers buzzer + OLED alert
```

Common fraud scenarios detected:
- Item swapping (cheaper item placed in heavier product's packaging)
- Scale tampering (additional weight placed on scale)
- Missing items (scanning tag but not placing item on scale)
