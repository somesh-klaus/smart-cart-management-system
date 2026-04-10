/**
 * Smart Cart Management System - ESP32 Firmware
 *
 * Hardware:
 *   - ESP32 DevKit
 *   - RC522 RFID Reader (SPI)
 *   - HX711 Load Cell Amplifier
 *   - SSD1306 OLED Display (I2C, 128x64)
 *   - Active Buzzer
 *
 * Libraries required (install via Arduino Library Manager):
 *   - MFRC522        by GithubCommunity
 *   - HX711          by bogde
 *   - Adafruit SSD1306
 *   - Adafruit GFX Library
 *   - ArduinoJson    by Benoit Blanchon
 *   - WiFi           (built-in for ESP32)
 *   - HTTPClient     (built-in for ESP32)
 */

#include <SPI.h>
#include <MFRC522.h>
#include <HX711.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

// ──────────────────────────────────────────────
// User Configuration
// ──────────────────────────────────────────────
#define WIFI_SSID       "YOUR_WIFI_SSID"
#define WIFI_PASSWORD   "YOUR_WIFI_PASSWORD"
#define SERVER_URL      "http://192.168.1.100:5000"   // Flask backend IP
#define CART_ID         "CART_001"

// ──────────────────────────────────────────────
// Pin Definitions
// ──────────────────────────────────────────────

// RC522 RFID (SPI)
#define RFID_SS_PIN     5    // SDA/SS
#define RFID_RST_PIN    22

// SPI shared with RC522
// SCK  -> GPIO 18
// MOSI -> GPIO 23
// MISO -> GPIO 19

// HX711 Load Cell
#define HX711_DOUT_PIN  16
#define HX711_SCK_PIN   17

// OLED SSD1306 (I2C)
// SDA  -> GPIO 21
// SCL  -> GPIO 22  (shared RST only when RST on separate line)
#define OLED_WIDTH      128
#define OLED_HEIGHT     64
#define OLED_RESET      -1   // no reset pin; share Arduino reset
#define OLED_ADDRESS    0x3C

// Buzzer
#define BUZZER_PIN      4

// ──────────────────────────────────────────────
// Constants
// ──────────────────────────────────────────────
#define WEIGHT_TOLERANCE_PCT  10.0   // ±10 % tolerance
#define CALIBRATION_FACTOR    2280.0 // Adjust for your load cell
#define WEIGHT_SETTLE_MS      1500   // ms to wait before reading weight
#define SCAN_COOLDOWN_MS      3000   // ms between scans of the same tag

// ──────────────────────────────────────────────
// Global Objects
// ──────────────────────────────────────────────
MFRC522 rfid(RFID_SS_PIN, RFID_RST_PIN);
HX711   scale;
Adafruit_SSD1306 display(OLED_WIDTH, OLED_HEIGHT, &Wire, OLED_RESET);

// Cart state
float   cartTotal      = 0.0;
int     itemCount      = 0;
String  lastTagUID     = "";
unsigned long lastScanTime = 0;

// ──────────────────────────────────────────────
// Setup
// ──────────────────────────────────────────────
void setup() {
    Serial.begin(115200);

    // Buzzer
    pinMode(BUZZER_PIN, OUTPUT);
    digitalWrite(BUZZER_PIN, LOW);

    // OLED
    if (!display.begin(SSD1306_SWITCHCAPVCC, OLED_ADDRESS)) {
        Serial.println(F("SSD1306 init failed"));
        while (true) delay(10);
    }
    displayMessage("Smart Cart", "Initializing...");

    // SPI & RFID
    SPI.begin();
    rfid.PCD_Init();
    Serial.println(F("RFID reader ready"));

    // HX711
    scale.begin(HX711_DOUT_PIN, HX711_SCK_PIN);
    scale.set_scale(CALIBRATION_FACTOR);
    scale.tare();
    Serial.println(F("Scale tared"));

    // Wi-Fi
    connectWiFi();

    // Startup beep
    beep(100);
    displayCartInfo();
}

// ──────────────────────────────────────────────
// Main Loop
// ──────────────────────────────────────────────
void loop() {
    // Wait for a new RFID card
    if (!rfid.PICC_IsNewCardPresent() || !rfid.PICC_ReadCardSerial()) {
        return;
    }

    String uid = getUID();
    Serial.print(F("Tag UID: "));
    Serial.println(uid);

    // Debounce: ignore same tag scanned too quickly
    unsigned long now = millis();
    if (uid == lastTagUID && (now - lastScanTime) < SCAN_COOLDOWN_MS) {
        rfid.PICC_HaltA();
        rfid.PCD_StopCrypto1();
        return;
    }
    lastTagUID  = uid;
    lastScanTime = now;

    // Read weight (settle first)
    displayMessage("Scanning...", uid.c_str());
    delay(WEIGHT_SETTLE_MS);
    float weight = readWeight();
    Serial.printf("Weight: %.2f g\n", weight);

    // Query backend for product info & fraud check
    displayMessage("Checking...", "Please wait");
    processTag(uid, weight);

    rfid.PICC_HaltA();
    rfid.PCD_StopCrypto1();
}

// ──────────────────────────────────────────────
// Wi-Fi
// ──────────────────────────────────────────────
void connectWiFi() {
    Serial.printf("Connecting to %s", WIFI_SSID);
    displayMessage("Wi-Fi", "Connecting...");
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    int attempts = 0;
    while (WiFi.status() != WL_CONNECTED && attempts < 30) {
        delay(500);
        Serial.print('.');
        attempts++;
    }
    if (WiFi.status() == WL_CONNECTED) {
        Serial.println();
        Serial.print(F("IP: "));
        Serial.println(WiFi.localIP());
        displayMessage("Wi-Fi OK", WiFi.localIP().toString().c_str());
    } else {
        Serial.println(F("\nWi-Fi failed – offline mode"));
        displayMessage("Wi-Fi FAILED", "Offline mode");
    }
    delay(1000);
}

// ──────────────────────────────────────────────
// RFID Helpers
// ──────────────────────────────────────────────
String getUID() {
    String uid = "";
    for (byte i = 0; i < rfid.uid.size; i++) {
        if (rfid.uid.uidByte[i] < 0x10) uid += "0";
        uid += String(rfid.uid.uidByte[i], HEX);
        if (i < rfid.uid.size - 1) uid += ":";
    }
    uid.toUpperCase();
    return uid;
}

// ──────────────────────────────────────────────
// Weight
// ──────────────────────────────────────────────
float readWeight() {
    if (!scale.is_ready()) return 0.0;
    // Average of 5 readings for stability
    return scale.get_units(5);
}

// ──────────────────────────────────────────────
// Backend Communication
// ──────────────────────────────────────────────
void processTag(const String &uid, float weight) {
    if (WiFi.status() != WL_CONNECTED) {
        displayMessage("OFFLINE", "No server");
        beep(200);
        return;
    }

    HTTPClient http;
    String url = String(SERVER_URL) + "/api/scan";
    http.begin(url);
    http.addHeader("Content-Type", "application/json");

    // Build JSON payload
    StaticJsonDocument<256> doc;
    doc["cart_id"]       = CART_ID;
    doc["rfid_uid"]      = uid;
    doc["actual_weight"] = weight;

    String payload;
    serializeJson(doc, payload);

    int httpCode = http.POST(payload);
    Serial.printf("HTTP POST %s -> %d\n", url.c_str(), httpCode);

    if (httpCode == 200) {
        String response = http.getString();
        handleScanResponse(response);
    } else {
        Serial.printf("Server error: %d\n", httpCode);
        displayMessage("Server Error", String(httpCode).c_str());
        beep(300);
    }
    http.end();
}

void handleScanResponse(const String &json) {
    StaticJsonDocument<512> doc;
    DeserializationError err = deserializeJson(doc, json);
    if (err) {
        Serial.print(F("JSON parse error: "));
        Serial.println(err.c_str());
        return;
    }

    const char *productName   = doc["product_name"] | "Unknown";
    float       price         = doc["price"]         | 0.0f;
    bool        fraudDetected = doc["fraud_detected"] | false;
    const char *alertMsg      = doc["alert_message"] | "";

    // Update cart totals from server response
    cartTotal = doc["cart_total"]  | cartTotal;
    itemCount = doc["item_count"]  | itemCount;

    Serial.printf("Product: %s | Price: %.2f | Fraud: %s\n",
                  productName, price, fraudDetected ? "YES" : "NO");

    if (fraudDetected) {
        // Alert
        displayAlert(productName, alertMsg);
        alertBeep();
    } else {
        // Show item added
        char line1[24], line2[24];
        snprintf(line1, sizeof(line1), "%.20s", productName);
        snprintf(line2, sizeof(line2), "PKR %.2f added", price);
        displayMessage(line1, line2);
        beep(80);
        delay(1500);
        displayCartInfo();
    }
}

// ──────────────────────────────────────────────
// OLED Display Helpers
// ──────────────────────────────────────────────
void displayMessage(const char *line1, const char *line2) {
    display.clearDisplay();
    display.setTextSize(1);
    display.setTextColor(SSD1306_WHITE);

    display.setCursor(0, 10);
    display.setTextSize(2);
    display.println(line1);

    display.setTextSize(1);
    display.setCursor(0, 40);
    display.println(line2);

    display.display();
}

void displayCartInfo() {
    display.clearDisplay();
    display.setTextColor(SSD1306_WHITE);

    // Header
    display.setTextSize(1);
    display.setCursor(0, 0);
    display.println(F("=== Smart Cart ==="));

    // Cart ID
    display.setCursor(0, 12);
    display.print(F("ID: "));
    display.println(CART_ID);

    // Items
    display.setCursor(0, 24);
    display.print(F("Items: "));
    display.println(itemCount);

    // Total
    display.setCursor(0, 36);
    display.print(F("Total: PKR "));
    display.println(cartTotal, 2);

    // Hint
    display.setCursor(0, 54);
    display.println(F("Scan item to add"));

    display.display();
}

void displayAlert(const char *product, const char *msg) {
    display.clearDisplay();
    display.setTextColor(SSD1306_WHITE);

    display.setTextSize(1);
    display.setCursor(0, 0);
    display.println(F("!! ALERT !!"));

    display.setTextSize(1);
    display.setCursor(0, 14);
    display.println(product);

    display.setCursor(0, 28);
    display.println(msg);

    display.setCursor(0, 50);
    display.println(F("Check weight!"));

    display.display();
    delay(3000);
    displayCartInfo();
}

// ──────────────────────────────────────────────
// Buzzer Helpers
// ──────────────────────────────────────────────
void beep(int durationMs) {
    digitalWrite(BUZZER_PIN, HIGH);
    delay(durationMs);
    digitalWrite(BUZZER_PIN, LOW);
}

void alertBeep() {
    for (int i = 0; i < 3; i++) {
        beep(200);
        delay(150);
    }
}
