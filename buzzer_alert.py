"""
buzzer_alert.py — Runs on Raspberry Pi 5
=========================================
Connects to the AyuScan WebSocket and triggers a buzzer on GPIO 18.

Rules:
  - Alert fires after 3 consecutive low readings (debounce)
  - Buzzer beeps continuously at 10Hz while alert is active
  - Alert clears only after 3 consecutive GOOD readings (hysteresis)
  - Also triggers immediately on AI spo2_warning message

Hardware:
  Buzzer +  → GPIO 18
  Buzzer -  → GND

Install on RPi 5:
  pip install websockets gpiozero lgpio

Run:
  python buzzer_alert.py --host <PC_IP>   # IP running ble_server.py or mock_server.py
  python buzzer_alert.py                  # if both on same RPi
"""

import asyncio
import json
import argparse
import time
import threading
from gpiozero import Buzzer

# ── Configuration ──────────────────────────────────────────────
BUZZER_PIN         = 18
SPO2_ALERT         = 90   # below this → bad reading
SPO2_RECOVER       = 93   # above this → good reading
HR_ALERT           = 120  # BPM above this → bad reading (optional)
BEEP_HZ            = 10   # beeps per second when alert is active
BAD_READINGS_NEEDED  = 3  # consecutive bad  readings before alert ON
GOOD_READINGS_NEEDED = 3  # consecutive good readings before alert OFF
# ───────────────────────────────────────────────────────────────

bz = Buzzer(BUZZER_PIN)

# Shared state (protected by GIL - simple flag is safe in Python)
alert_active      = False
consecutive_bad   = 0
consecutive_good  = 0


def continuous_beep_loop():
    """Background thread: beeps at BEEP_HZ while alert_active is True."""
    interval = 1.0 / BEEP_HZ
    while True:
        if alert_active:
            bz.on()
            time.sleep(interval * 0.5)
            bz.off()
            time.sleep(interval * 0.5)
        else:
            bz.off()
            time.sleep(0.05)  # check 20x/sec when idle


def beep_once(times=1, on_ms=200, off_ms=100):
    """Blocking confirmation beep — only called at startup."""
    for i in range(times):
        bz.on()
        time.sleep(on_ms / 1000)
        bz.off()
        if i < times - 1:
            time.sleep(off_ms / 1000)


def activate_alert(reason: str):
    global alert_active, consecutive_bad, consecutive_good
    if not alert_active:
        print(f"[BUZZER] 🔔 ALERT ON  — {reason}")
    alert_active     = True
    consecutive_good = 0


def clear_alert():
    global alert_active, consecutive_bad, consecutive_good
    if alert_active:
        print(f"[BUZZER] ✅ ALERT OFF — vitals recovered")
    alert_active    = False
    consecutive_bad = 0


def evaluate_reading(spo2: int, bpm: int):
    """
    Debounced evaluation:
    - Needs BAD_READINGS_NEEDED consecutive bad values  to turn alert ON
    - Needs GOOD_READINGS_NEEDED consecutive good values to turn alert OFF
    """
    global consecutive_bad, consecutive_good

    is_bad = (spo2 > 0 and spo2 < SPO2_ALERT) or (bpm > 0 and bpm >= HR_ALERT)
    is_good = (spo2 >= SPO2_RECOVER or spo2 == 0)

    if is_bad:
        consecutive_bad  += 1
        consecutive_good  = 0
        if consecutive_bad >= BAD_READINGS_NEEDED:
            activate_alert(f"SpO2={spo2}% BPM={bpm}")
    elif is_good and not is_bad:
        consecutive_good += 1
        consecutive_bad   = 0
        if consecutive_good >= GOOD_READINGS_NEEDED:
            clear_alert()

    print(f"[Vitals] spo2={spo2}%  bpm={bpm}  bad_streak={consecutive_bad}  good_streak={consecutive_good}  alert={alert_active}")


async def listen(host: str, port: int = 8080):
    uri = f"ws://{host}:{port}"
    print(f"[Buzzer] Connecting to {uri} …")
    print(f"[Buzzer] Alert fires after {BAD_READINGS_NEEDED} consecutive readings below SpO2={SPO2_ALERT}%")

    import websockets

    # Start beep loop in dedicated background thread
    t = threading.Thread(target=continuous_beep_loop, daemon=True)
    t.start()

    async for ws in websockets.connect(uri, ping_interval=20):
        try:
            print("[Buzzer] Connected. Monitoring vitals…")
            beep_once(1, 300)  # startup confirmation beep

            async for raw in ws:
                try:
                    data     = json.loads(raw)
                    msg_type = data.get("type", "")

                    # ── AI warning → immediate trigger (no debounce needed) ─
                    if msg_type == "spo2_warning":
                        condition = data.get("condition", "")
                        if condition in ("Rapid Decline", "Critical"):
                            activate_alert(f"AI: {condition}")
                        continue

                    # ── Live ppg vitals → debounced evaluation ─────────────
                    if msg_type == "ppg":
                        spo2 = int(data.get("spo2", 0) or 0)
                        bpm  = int(data.get("bpm",  0) or 0)
                        evaluate_reading(spo2, bpm)

                except (json.JSONDecodeError, KeyError, ValueError, TypeError):
                    pass

        except websockets.ConnectionClosed:
            clear_alert()
            print("[Buzzer] Connection lost — retrying in 5s…")
            await asyncio.sleep(5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AyuScan Buzzer Alert — Raspberry Pi 5")
    parser.add_argument("--host", default="localhost",
                        help="IP of machine running ble_server.py or mock_server.py")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    try:
        asyncio.run(listen(args.host, args.port))
    except KeyboardInterrupt:
        clear_alert()
        bz.off()
        print("\n[Buzzer] Stopped.")
