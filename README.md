# Smart Cart Management System

An IoT-based Smart Cart Management System using **ESP32**, **RFID (RC522)**, and **HX711 load cell** for automated billing, real-time cart tracking, and fraud detection through weight verification.

---

## Project Structure

```
smart-cart-management-system/
├── firmware/               # ESP32 Arduino firmware
│   └── smart_cart.ino
├── backend/                # Flask REST API + SQLite + WebSocket
│   ├── app.py
│   ├── requirements.txt
│   └── tests/
│       └── test_app.py
├── frontend/               # Web dashboard (HTML/CSS/JS)
│   ├── index.html
│   ├── css/style.css
│   └── js/app.js
├── docs/                   # Circuit diagrams, wiring guide, API docs
│   └── documentation.md
└── README.md
```

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

---

## Hardware Components

| Component | Model |
|-----------|-------|
| Microcontroller | ESP32 DevKit V1 |
| RFID Reader | MFRC522 RC522 (13.56 MHz) |
| Load Cell Amplifier | HX711 24-bit ADC |
| Load Cell | 5 kg single-point |
| OLED Display | SSD1306 128×64 I2C |
| Active Buzzer | 5V |

---

## Wiring (Quick Reference)

| RC522 | ESP32 | HX711 | ESP32 | OLED | ESP32 | Buzzer | ESP32 |
|-------|-------|-------|-------|------|-------|--------|-------|
| VCC → 3.3V | | VCC → 5V | | VCC → 3.3V | | (+) → GPIO 4 |
| GND → GND | | GND → GND | | GND → GND | | (−) → GND |
| RST → GPIO22 | | DT → GPIO16 | | SDA → GPIO21 | | |
| SDA → GPIO5 | | SCK → GPIO17 | | SCL → GPIO22 | | |
| SCK → GPIO18 | | | | | | |
| MOSI → GPIO23 | | | | | | |
| MISO → GPIO19 | | | | | | |

Full wiring guide: [`docs/documentation.md`](docs/documentation.md)

---

## Firmware Setup (ESP32)

1. Install **Arduino IDE** and the **ESP32 board package**.
2. Install libraries via Library Manager:
   - `MFRC522` (GithubCommunity)
   - `HX711 Arduino Library` (bogde)
   - `Adafruit SSD1306`
   - `Adafruit GFX Library`
   - `ArduinoJson`
3. Open `firmware/smart_cart.ino`.
4. Edit configuration at the top:
   ```cpp
   #define WIFI_SSID      "YOUR_WIFI_SSID"
   #define WIFI_PASSWORD  "YOUR_WIFI_PASSWORD"
   #define SERVER_URL     "http://192.168.1.100:5000"
   #define CART_ID        "CART_001"
   ```
5. Calibrate `CALIBRATION_FACTOR` for your load cell.
6. Upload to ESP32.

---

## Backend Setup (Flask)

```bash
cd backend
pip install -r requirements.txt
python app.py
```

Server runs on `http://0.0.0.0:5000`. SQLite database is created automatically with demo products.

### Run Tests

```bash
pytest backend/tests/test_app.py -v
```

---

## Web Dashboard

Open `http://<server-ip>:5000` in a browser.

| Page | Description |
|------|-------------|
| Dashboard | Live stats, cart monitor, activity feed |
| Product Catalog | CRUD for products mapped to RFID UIDs |
| Cart Sessions | All sessions with checkout action |
| Fraud Logs | All fraud events with deviation % |
| Admin | Simulate RFID scans, quick cart actions |

---

## API Documentation

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/scan` | Receive scan from ESP32 |
| GET | `/api/products` | List products |
| POST | `/api/products` | Create product |
| GET | `/api/products/{id}` | Get product |
| PUT | `/api/products/{id}` | Update product |
| DELETE | `/api/products/{id}` | Delete product |
| GET | `/api/carts` | List all sessions |
| GET | `/api/carts/{cart_id}` | Get active cart |
| POST | `/api/carts/{cart_id}/checkout` | Checkout |
| POST | `/api/carts/{cart_id}/clear` | Clear cart |
| GET | `/api/fraud-logs` | Fraud events |
| GET | `/api/stats` | Dashboard stats |

Full API docs: [`docs/documentation.md`](docs/documentation.md)

---

## Fraud Detection

Weight fraud is flagged when actual weight deviates **more than 10%** from the expected weight in the product catalog:

```
deviation = |actual − expected| / expected × 100
if deviation > 10%  →  FRAUD ALERT
```

On fraud detection:
- ESP32 sounds buzzer (3 beeps) and shows OLED alert
- Backend logs event to `fraud_logs` table
- Dashboard receives real-time WebSocket alert

---

## License

[MIT](LICENSE)
