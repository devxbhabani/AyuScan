# AyuScan

A real-time wearable health monitoring system using Seeed XIAO ESP32-C6, BioAmp EXG Pill, MAX30102, and MLX90614. Streams live biosignals over BLE to a Raspberry Pi 5, runs AI inference, and displays results on a React dashboard.

---

## Hardware

| Component | Purpose |
|---|---|
| Seeed XIAO ESP32-C6 | BLE data acquisition |
| BioAmp EXG Pill | ECG signal |
| MAX30102 | PPG / SpO2 / Heart Rate |
| MLX90614 (GY-906) | Skin & Ambient Temperature |
| Raspberry Pi 5 | BLE host, AI inference, WebSocket server |
| Buzzer on GPIO 18 | Alert on SpO2 drop |

### Wiring (Direct I2C — No Mux)

```
MAX30102  SDA ──┐
MLX90614  SDA ──┴── D4 (GPIO22)   XIAO ESP32-C6
MAX30102  SCL ──┐
MLX90614  SCL ──┴── D5 (GPIO23)   XIAO ESP32-C6
BioAmp   OUT  ───── A0 (GPIO0)    XIAO ESP32-C6

Buzzer    +   ───── GPIO 18       Raspberry Pi 5
Buzzer    -   ───── GND           Raspberry Pi 5
```

> **Note:** Both MAX30102 (`0x57`) and MLX90614 (`0x5A`) share the same I2C bus because they have different addresses. No I2C multiplexer needed.

---

## Firmware

| File | Description |
|---|---|
| `ayuScan_direct/ayuScan_direct.ino` | **Main firmware** — direct I2C, no mux |
| `ayuScan_raw/ayuScan_raw.ino` | Legacy firmware — uses TCA9548A I2C mux |

Flash `ayuScan_direct.ino` to your XIAO ESP32-C6 using Arduino IDE.

**Required Arduino Libraries:**
- SparkFun MAX3010x Pulse and Proximity Sensor Library
- Adafruit MLX90614
- Adafruit SH110X + Adafruit GFX
- BLEDevice (built into ESP32 core)

---

## Features

- Live ECG waveform streaming (250 Hz)
- Heart Rate & SpO2 monitoring (bandpass-filtered, outlier-rejected)
- Body Temperature (MLX90614, every 1s)
- AI-based ECG condition detection (Normal, Bradycardia, Tachycardia, Arrhythmia)
- AI-based SpO2 trend analysis (Stable, Mild Decline, Rapid Decline, Critical)
- Blood Pressure estimation via ECG + PPG (XGBoost model)
- Real-time React dashboard via WebSocket (port 8080)
- Buzzer alert on Raspberry Pi 5 when SpO2 drops below 90%

---

## Running the System (Real Hardware)

Open **3 terminals**:

**Terminal 1 — Dashboard:**
```bash
cd dashboard
npm install       # first time only
npm run dev
```
Open `http://localhost:5173` in your browser.

**Terminal 2 — BLE Server + AI Backend:**
```bash
pip install bleak websockets torch scipy numpy
python ble_server.py
```
Make sure the ESP32 is powered on and advertising as `AyuScan_Node`.

**Terminal 3 — Buzzer Alert (on Raspberry Pi 5):**
```bash
pip install websockets gpiozero lgpio
python buzzer_alert.py --host <IP of machine running ble_server.py>
```
If `ble_server.py` is running on the same RPi, use `--host localhost`.

---

## Running a Demo (Fake Data — No ESP32 Needed)

Use this to present to judges or test the dashboard without the physical device.

**Terminal 1 — Dashboard:**
```bash
cd dashboard
npm run dev
```

**Terminal 2 — Mock Server (fake sensor data):**
```bash
python mock_server.py
```

**Terminal 3 — Buzzer Alert (on Raspberry Pi 5):**
```bash
python buzzer_alert.py --host <IP of machine running mock_server.py>
```

### Demo Scenario (auto 2-minute loop)

| Time | Scenario | HR | SpO2 | Buzzer |
|---|---|---|---|---|
| 0–30s | Normal Resting | 72 bpm | 98% | Silent |
| 30–60s | Mild Exertion | 88 bpm | 97% | Silent |
| 60–90s | Elevated Stress + Tachycardia alert | 102 bpm | 95% | Silent |
| **90–120s** | **SpO2 Critical Drop** | **110 bpm** | **88%** | **🔔 Rapid beeps!** |
| 120s+ | Recovery | 78 bpm | 97% | Silent |

> The buzzer fires automatically at ~90 seconds when SpO2 drops below 90%.

---

## Buzzer Alert Logic

File: `buzzer_alert.py` — runs on Raspberry Pi 5.

| Condition | Action |
|---|---|
| SpO2 < 90% | Rapid continuous beep for 4 seconds |
| 15s cooldown | Prevents alarm fatigue |
| On connect | 1 confirmation beep |

---

## Project Structure

```
AyuScan/
├── ayuScan_direct/         # Main ESP32 firmware (no mux)
│   └── ayuScan_direct.ino
├── ayuScan_raw/            # Legacy firmware (with TCA9548A mux)
│   └── ayuScan_raw.ino
├── backend/
│   ├── ppg_algorithm.py    # Heart Rate & SpO2 signal processing
│   ├── AI-model/           # ECG 1D-CNN model
│   ├── Spo2-Mocdel/        # SpO2 GRU trend model
│   └── Bp-model/           # Blood Pressure XGBoost model
├── dashboard/              # React frontend (Vite)
├── ble_server.py           # Main BLE → WebSocket server
├── mock_server.py          # Demo simulation server (no hardware)
├── buzzer_alert.py         # Raspberry Pi 5 GPIO buzzer alerts
└── README.md
```

---

## Notes

- The SpO2 algorithm uses `std`-based AC extraction with a physiological ratio gate (`0.3 ≤ R ≤ 1.0`) to reject motion artifacts without the distortion caused by bandpass filtering.
- Heart Rate uses `scipy.signal.find_peaks` on a rolling 5-second IR buffer with `width` filtering to reject dicrotic notch double-detection.
- BPM and SpO2 both use EMA smoothing (α = 0.1) for stable display.
