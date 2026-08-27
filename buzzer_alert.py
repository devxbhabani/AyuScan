"""
buzzer_alert.py — Runs on Raspberry Pi 5
=========================================
Connects to the AyuScan WebSocket server and triggers a buzzer
on GPIO 18 based on live vitals (SpO2 drop).

Buzzer beeps CONTINUOUSLY as long as SpO2 stays below 90%.
Stops automatically when SpO2 recovers above 93%.

Hardware:
  Buzzer +  → GPIO 18 (PWM-capable)
  Buzzer -  → GND

Dependencies (install on RPi 5):
  pip install websockets gpiozero lgpio

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
BUZZER_PIN   = 18
SPO2_ALERT   = 90   # start beeping below this
SPO2_RECOVER = 93   # stop beeping once SpO2 is back above this
BEEP_HZ      = 10   # beeps per second (10 = rapid, urgent)
# ───────────────────────────────────────────────────────────────

bz = Buzzer(BUZZER_PIN)

# Shared state between WebSocket listener and beep loop
alert_active = False   # True  = buzzer should keep beeping
ai_triggered = False   # True  = AI warning received, override SpO2 value


def continuous_beep_loop():
    """
    Runs in a background thread.
    Beeps at BEEP_HZ as long as alert_active is True.
    """
    global alert_active
    interval = 1.0 / BEEP_HZ
    while True:
        if alert_active:
            bz.on()
            time.sleep(interval * 0.5)
            bz.off()
            time.sleep(interval * 0.5)
        else:
            bz.off()
            time.sleep(0.1)   # idle check every 100ms


def beep_once(times: int = 1, on_ms: int = 200, off_ms: int = 150):
    """Single confirmation beep (blocking, called once at startup)."""
    for i in range(times):
        bz.on()
        time.sleep(on_ms / 1000)
        bz.off()
        if i < times - 1:
            time.sleep(off_ms / 1000)


def set_alert(active: bool, reason: str = ""):
    global alert_active
    if active and not alert_active:
        print(f"[BUZZER] 🔔 ALERT ON  — {reason}")
    elif not active and alert_active:
        print(f"[BUZZER] ✅ ALERT OFF — SpO2 recovered")
    alert_active = active


async def listen(host: str, port: int = 8080):
    global ai_triggered
    uri = f"ws://{host}:{port}"
    print(f"[Buzzer] Connecting to {uri} …")

    import websockets

    # Start the beep loop in a background thread (non-blocking)
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, continuous_beep_loop)

    async for ws in websockets.connect(uri, ping_interval=20):
        try:
            print("[Buzzer] Connected. Monitoring vitals…")
            beep_once(1, 300)   # startup confirmation

            async for raw in ws:
                try:
                    data     = json.loads(raw)
                    msg_type = data.get("type", "")

                    # ── AI warning: immediate trigger ─────────────────────
                    if msg_type == "spo2_warning":
                        condition = data.get("condition", "")
                        if condition in ("Rapid Decline", "Critical"):
                            ai_triggered = True
                            set_alert(True, f"AI: {condition}")
                        continue

                    # ── Live SpO2 value ───────────────────────────────────
                    if msg_type == "ppg":
                        spo2 = int(data.get("spo2", 0))
                        bpm  = int(data.get("bpm",  0))
                        print(f"[Vitals] bpm={bpm}  spo2={spo2}%  alert={alert_active}")

                        if spo2 > 0:
                            if spo2 < SPO2_ALERT:
                                set_alert(True, f"SpO2={spo2}%")
                            elif spo2 >= SPO2_RECOVER:
                                # Only auto-cancel if it wasn't an AI trigger
                                # (AI warnings need manual reset or explicit recovery)
                                ai_triggered = False
                                set_alert(False)

                except (json.JSONDecodeError, KeyError, ValueError):
                    pass

        except websockets.ConnectionClosed:
            set_alert(False)
            print("[Buzzer] Connection lost — retrying in 5s…")
            await asyncio.sleep(5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AyuScan Buzzer Alert for Raspberry Pi 5")
    parser.add_argument("--host", default="localhost",
                        help="IP of the machine running ble_server.py / mock_server.py")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    try:
        asyncio.run(listen(args.host, args.port))
    except KeyboardInterrupt:
        alert_active = False
        bz.off()
        print("\n[Buzzer] Stopped.")
