import asyncio
import json
import random
import time
import math
import os
import websockets
from bleak import BleakClient, BleakScanner

WS_PORT = 8080
DEVICE_NAME = "AyuScan_Node"
VITALS_CHAR_UUID = "e3223119-9445-4e96-a4a1-85358ce291d0"

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

def generate_fake_ecg(hr, fs=250):
    interval = int((60.0 / hr) * fs)
    points = []
    baseline = 2000
    for i in range(fs):
        pos = i % interval
        # Scale to match AD8232 on ESP32 (12-bit ADC, baseline ~2000)
        p = 150 * math.exp(-((pos - 20) ** 2) / 20)
        q = -150 * math.exp(-((pos - 35) ** 2) / 10)
        r = 1200 * math.exp(-((pos - 45) ** 2) / 10)
        s = -300 * math.exp(-((pos - 55) ** 2) / 10)
        t = 200 * math.exp(-((pos - 90) ** 2) / 50)
        noise = random.uniform(-15, 15)
        points.append(int(baseline + p + q + r + s + t + noise))
    return points

async def connect_and_stream(device):
    mac = device.address
    try:
        async with BleakClient(device) as client:
            print(f"Connected to {mac}!")
            
            # State for this specific device
            # We assign different baseline vitals randomly so the two devices look distinct
            device_state = {
                "id": f"unknown_{mac[-5:]}", # Will be updated when we read the first BLE packet
                "temp": 36.6,
                "base_hr": random.choice([72, 85]),
                "base_spo2": random.choice([98, 95]),
                "base_sbp": random.choice([118, 130]),
                "base_dbp": random.choice([76, 85])
            }
            
            async def handle_ble_notification(sender, data):
                try:
                    decoded = data.decode('utf-8').strip()
                    payload = json.loads(decoded)
                    
                    # Extract the true device ID (patient_01 or patient_02)
                    if "device" in payload:
                        device_state["id"] = payload["device"]
                        
                    # Extract the real temp
                    if payload.get("type") == "temp" and payload.get("val") is not None:
                        device_state["temp"] = float(payload["val"])
                        print(f"[BLE] {device_state['id']} Real Temp: {device_state['temp']}C")
                except Exception:
                    pass
                    
            await client.start_notify(VITALS_CHAR_UUID, handle_ble_notification)
            
            async def stream_task():
                print(f"Started streaming GOOD mock data for {mac}")
                while True:
                    did = device_state["id"]
                    bpm = int(device_state["base_hr"] + random.uniform(-2, 2))
                    spo2 = int(device_state["base_spo2"] + random.uniform(-1, 1))
                    sbp = int(device_state["base_sbp"] + random.uniform(-2, 2))
                    dbp = int(device_state["base_dbp"] + random.uniform(-2, 2))
                    
                    # ── PPG vitals (bpm + spo2) ───────────────────────────────────
                    await broadcast(json.dumps({
                        "device": did,
                        "type": "ppg",
                        "bpm": bpm,
                        "spo2": spo2,
                        "hrv_sdnn": round(random.uniform(40, 50), 1),
                        "hrv_rmssd": round(random.uniform(35, 45), 1)
                    }))

                    # ── Temperature (from actual device!) ─────────────────────────
                    await broadcast(json.dumps({
                        "device": did,
                        "type": "temp",
                        "val": device_state["temp"]
                    }))

                    # ── Blood Pressure ────────────────────────────────────────────
                    await broadcast(json.dumps({
                        "device": did,
                        "type": "bp",
                        "sbp": sbp,
                        "dbp": dbp,
                        "status": "Normal" if sbp < 125 else "Elevated"
                    }))
                    
                    # ── ECG AI label ──────────────────────────────────────────────
                    await broadcast(json.dumps({
                        "device": did,
                        "type": "ai_prediction",
                        "condition": "Normal"
                    }))

                    # ── ECG Data ──────────────────────────────────────────────────
                    await broadcast(json.dumps({
                        "device": did,
                        "type": "ecg",
                        "data": generate_fake_ecg(bpm, 250)
                    }))

                    print(f"[Mock] {did}: HR={bpm} SpO2={spo2}% Temp={device_state['temp']}C BP={sbp}/{dbp}")
                    await asyncio.sleep(1)
            
            # Start streaming loop
            task = asyncio.create_task(stream_task())
            
            # Keep connection alive
            while client.is_connected:
                await asyncio.sleep(1)
                
            task.cancel()
            print(f"Disconnected from {mac}")
            
    except Exception as e:
        print(f"Connection error for {mac}: {e}")

async def ble_worker():
    connected_macs = set()
    while True:
        try:
            devices = await BleakScanner.discover(timeout=5.0)
            for d in devices:
                if d.name == DEVICE_NAME and d.address not in connected_macs:
                    print(f"Found new device: {d.address}. Attempting connection...")
                    connected_macs.add(d.address)
                    
                    # Launch a connection in the background so it doesn't block scanning
                    async def connection_wrapper(dev=d):
                        await connect_and_stream(dev)
                        connected_macs.discard(dev.address)
                    
                    asyncio.create_task(connection_wrapper())
                    
        except Exception as e:
            print(f"Scan error: {e}")
            
        await asyncio.sleep(2) # Wait a bit before scanning again

async def main():
    print(f"--- Starting Multi-Device Connected Mock Server on ws://0.0.0.0:{WS_PORT} ---")
    ws_server = websockets.serve(register, "0.0.0.0", WS_PORT)
    await asyncio.gather(
        ws_server,
        ble_worker()
    )

if __name__ == "__main__":
    asyncio.run(main())
