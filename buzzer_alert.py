"""
buzzer_alert.py — Runs on Raspberry Pi 5
=========================================
Connects to the AyuScan WebSocket server and triggers a buzzer
on GPIO 18 based on live vitals (SpO2 drop, high heart rate).

Hardware:
  Buzzer +  → GPIO 18 (PWM-capable)
  Buzzer -  → GND

Dependencies (install on RPi 5):
  pip install websockets gpiozero

Usage:
  python buzzer_alert.py --host 192.168.x.x   (IP of the machine running ble_server.py)
  python buzzer_alert.py                       (defaults to localhost if on same RPi)
"""

import asyncio
import json
import argparse
import time
from gpiozero import Buzzer

# ── Configuration ──────────────────────────────────────────────
BUZZER_PIN = 18

# SpO2 thresholds
SPO2_WARN   = 94   # moderate decline  → 3 short beeps
SPO2_ALERT  = 90   # severe decline    → rapid continuous beeps

# Heart rate thresholds
HR_WARN     = 100  # elevated          → 2 beeps
HR_ALERT    = 120  # very high         → 4 fast beeps

# Minimum seconds between same-level alerts (prevents alarm fatigue)
COOLDOWN_SEC = 15
# ───────────────────────────────────────────────────────────────


bz = Buzzer(BUZZER_PIN)

last_alert_time = {
    "spo2_warn": 0,
    "spo2_alert": 0,
    "hr_warn": 0,
    "hr_alert": 0,
}


def beep(times: int, on_ms: int = 150, off_ms: int = 100):
    """Blocking beep pattern — runs in a thread via asyncio.to_thread."""
    for i in range(times):
        bz.on()
        time.sleep(on_ms / 1000)
        bz.off()
        if i < times - 1:
            time.sleep(off_ms / 1000)


def rapid_beep(duration_sec: float = 3.0, hz: int = 4):
    """Continuous rapid beeps for `duration_sec` seconds at `hz` Hz."""
    interval = 1.0 / hz
    end = time.time() + duration_sec
    while time.time() < end:
        bz.on()
        time.sleep(interval * 0.5)
        bz.off()
        time.sleep(interval * 0.5)


def can_alert(key: str) -> bool:
    now = time.time()
    if now - last_alert_time[key] >= COOLDOWN_SEC:
        last_alert_time[key] = now
        return True
    return False


async def handle_vitals(spo2: int, bpm: int):
    """Trigger buzzer only when SpO2 drops below 90%."""
    if spo2 > 0 and spo2 < 90:
        if can_alert("spo2_alert"):
            print(f"[BUZZER] SpO2 critically low: {spo2}% — beeping!")
            await asyncio.to_thread(rapid_beep, 4.0, 5)


async def listen(host: str, port: int = 8080):
    uri = f"ws://{host}:{port}"
    print(f"[Buzzer] Connecting to AyuScan WebSocket at {uri} …")

    import websockets
    async for ws in websockets.connect(uri, ping_interval=20):
        try:
            print("[Buzzer] Connected. Monitoring vitals…")
            # Start-up confirmation: 1 short beep
            await asyncio.to_thread(beep, 1, 300)

            async for raw in ws:
                try:
                    data = json.loads(raw)
                    spo2 = int(data.get("spo2", 0))
                    bpm  = int(data.get("bpm",  0))
                    print(f"[Vitals] bpm={bpm}  spo2={spo2}%")
                    await handle_vitals(spo2, bpm)
                except (json.JSONDecodeError, KeyError, ValueError):
                    pass  # ignore malformed packets

        except websockets.ConnectionClosed:
            print("[Buzzer] Connection lost — retrying in 5s…")
            await asyncio.sleep(5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AyuScan Buzzer Alert for Raspberry Pi 5")
    parser.add_argument("--host", default="localhost",
                        help="IP address of the machine running ble_server.py")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    try:
        asyncio.run(listen(args.host, args.port))
    except KeyboardInterrupt:
        bz.off()
        print("\n[Buzzer] Stopped.")
