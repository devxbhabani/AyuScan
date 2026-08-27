"""
mock_server.py — Demo simulation for AyuScan
=============================================
Replaces ble_server.py for demo/presentation purposes.
Sends realistic fake vitals to the dashboard over WebSocket
WITHOUT needing the physical ESP32 device.

Scenario (auto-plays):
  0–30s  : Normal resting      (SpO2 98%, HR 72, Temp 36.5, BP 118/76)
  30–60s : Mild exertion       (SpO2 97%, HR 88, Temp 36.9, BP 125/80)
  60–90s : Elevated stress     (SpO2 95%, HR 102, Temp 37.2, BP 132/85)
  90–120s: SpO2 drop warning   (SpO2 88%, HR 110, Temp 37.5, BP 138/90)
  120s+  : Recovery            (SpO2 97%, HR 78, Temp 36.8, BP 120/78)

Run:
  python mock_server.py

Dashboard connects to ws://localhost:8080  (same as real server)
buzzer_alert.py also connects to the same port.
"""

import asyncio
import json
import time
import random
import websockets

WS_PORT = 8080
DEVICE_ID = "patient_01"
clients = set()


async def register(websocket):
    clients.add(websocket)
    try:
        await websocket.wait_closed()
    finally:
        clients.discard(websocket)


async def broadcast(message):
    if clients:
        await asyncio.gather(
            *(client.send(message) for client in clients),
            return_exceptions=True
        )


def jitter(val, amount=0.5):
    """Add tiny random noise to make data feel live."""
    return round(val + random.uniform(-amount, amount), 1)


def get_scenario(elapsed):
    """Return target vitals based on elapsed seconds. Shortened for fast demo."""
    if elapsed < 10:
        return {"spo2": 98, "hr": 72, "temp": 36.5, "sbp": 118, "dbp": 76,
                "label": "Normal Resting"}
    elif elapsed < 20:
        return {"spo2": 97, "hr": 88, "temp": 36.9, "sbp": 125, "dbp": 80,
                "label": "Mild Exertion"}
    elif elapsed < 30:
        return {"spo2": 95, "hr": 102, "temp": 37.2, "sbp": 132, "dbp": 85,
                "label": "Elevated Stress"}
    elif elapsed < 45:
        # SpO2 drops to 82% — well below 90 threshold, buzzer will fire after 3 readings
        return {"spo2": 82, "hr": 115, "temp": 37.5, "sbp": 138, "dbp": 90,
                "label": "⚠ SpO2 CRITICAL DROP"}
    elif elapsed < 55:
        # Partial recovery — still below recover threshold (93%)
        return {"spo2": 87, "hr": 108, "temp": 37.3, "sbp": 133, "dbp": 87,
                "label": "Slow Recovery"}
    else:
        return {"spo2": 97, "hr": 78, "temp": 36.8, "sbp": 120, "dbp": 78,
                "label": "Full Recovery"}


async def stream_fake_data():
    """Continuously broadcast fake vitals every second."""
    start = time.time()
    sent_bp = False
    sent_ecg_label = False

    while True:
        elapsed = time.time() - start
        s = get_scenario(elapsed)

        # ── PPG vitals (bpm + spo2) ───────────────────────────────────
        spo2 = max(70, min(100, int(s["spo2"] + random.uniform(-1, 1))))
        bpm  = int(s["hr"] + random.uniform(-3, 3))

        ppg_msg = json.dumps({
            "device": DEVICE_ID,
            "type": "ppg",
            "bpm": bpm,
            "spo2": spo2,
            "hrv_sdnn": round(random.uniform(28, 55), 1),
            "hrv_rmssd": round(random.uniform(20, 45), 1)
        })
        await broadcast(ppg_msg)

        # ── Temperature (every 3s) ────────────────────────────────────
        if int(elapsed) % 3 == 0:
            temp_msg = json.dumps({
                "device": DEVICE_ID,
                "type": "temp",
                "val": jitter(s["temp"], 0.1)
            })
            await broadcast(temp_msg)

        # ── Blood Pressure (every 10s) ────────────────────────────────
        if int(elapsed) % 10 == 0 and int(elapsed) > 0:
            bp_msg = json.dumps({
                "device": DEVICE_ID,
                "type": "bp",
                "sbp": int(s["sbp"] + random.uniform(-3, 3)),
                "dbp": int(s["dbp"] + random.uniform(-2, 2)),
                "status": "Normal" if s["sbp"] < 130 else "Elevated"
            })
            await broadcast(bp_msg)
            print(f"[Mock] BP sent: {s['sbp']}/{s['dbp']}")

        # ── SpO2 AI Warning (trigger once at scenario change) ─────────
        if 30 <= elapsed <= 31:
            warn_msg = json.dumps({
                "device": DEVICE_ID,
                "type": "spo2_warning",
                "condition": "Rapid Decline"
            })
            await broadcast(warn_msg)
            print("[Mock] SpO2 warning sent: Rapid Decline")

        # ── ECG AI label ──────────────────────────────────────────────
        if 20 <= elapsed <= 21:
            ai_msg = json.dumps({
                "device": DEVICE_ID,
                "type": "ai_prediction",
                "condition": "Tachycardia"
            })
            await broadcast(ai_msg)
            print("[Mock] AI ECG: Tachycardia")

        print(f"[Mock] t={int(elapsed)}s | {s['label']} | HR={bpm} SpO2={spo2}%")
        await asyncio.sleep(1)


async def main():
    print(f"[Mock] AyuScan demo server starting on ws://0.0.0.0:{WS_PORT}")
    print("[Mock] Connect your dashboard and buzzer_alert.py now.")
    print("[Mock] Scenario: Normal → Exertion → Stress → SpO2 Alert → Recovery\n")

    async with websockets.serve(register, "0.0.0.0", WS_PORT):
        await stream_fake_data()


if __name__ == "__main__":
    asyncio.run(main())
