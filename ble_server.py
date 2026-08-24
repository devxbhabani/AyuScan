import asyncio
import websockets
import json
import sys
import os
import csv
import time
from datetime import datetime
import torch
import numpy as np
from scipy.signal import butter, filtfilt, resample, find_peaks
from bleak import BleakClient, BleakScanner

# Add backend to path globally
sys.path.append(os.path.join(os.path.dirname(__file__), 'backend'))
from ppg_algorithm import PPGProcessor

# --- Data Logging Setup ---
os.makedirs("datasets", exist_ok=True)
ecg_csv_path = os.path.join("datasets", "ecg_data_master.csv")
vitals_csv_path = os.path.join("datasets", "vitals_data_master.csv")

# Create files with headers if they don't exist
if not os.path.exists(ecg_csv_path):
    with open(ecg_csv_path, 'w', newline='') as f:
        csv.writer(f).writerow(['timestamp', 'device', 'ecg_value'])
        
if not os.path.exists(vitals_csv_path):
    with open(vitals_csv_path, 'w', newline='') as f:
        csv.writer(f).writerow(['timestamp', 'device', 'spo2', 'hrv_sdnn', 'hrv_rmssd'])
# --------------------------

SERVICE_UUID = "4fafc201-1fb5-459e-8fcc-c5c9c331914b"
ECG_CHAR_UUID = "beb5483e-36e1-4688-b7f5-ea07361b26a8"
VITALS_CHAR_UUID = "e3223119-9445-4e96-a4a1-85358ce291d0"
DEVICE_NAME = "AyuScan_Node"

# Add AI model path
sys.path.append(os.path.join(os.path.dirname(__file__), 'backend', 'AI-model'))
sys.path.append(os.path.join(os.path.dirname(__file__), 'backend', 'Spo2-Mocdel'))
sys.path.append(os.path.join(os.path.dirname(__file__), 'backend', 'Bp-model'))

try:
    from model import ECG1DCNN
    
    # Temporarily remove AI-model from path to load SpO2_GRU correctly
    sys.path.remove(os.path.join(os.path.dirname(__file__), 'backend', 'AI-model'))
    from train import SpO2_GRU
    # Put it back
    sys.path.append(os.path.join(os.path.dirname(__file__), 'backend', 'AI-model'))
    
    from bp_model.predictor import predict_bp
    
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    
    # Load ECG Model
    ai_model = ECG1DCNN(num_classes=4).to(device)
    ecg_model_path = os.path.join(os.path.dirname(__file__), 'backend', 'ecg_model.pth')
    if os.path.exists(ecg_model_path):
        ai_model.load_state_dict(torch.load(ecg_model_path, map_location=device))
        ai_model.eval()
        print("ECG AI Model loaded successfully.")
    else:
        ai_model = None

    # Load SpO2 Model
    spo2_model = SpO2_GRU(num_classes=4).to(device)
    spo2_model_path = os.path.join(os.path.dirname(__file__), 'backend', 'Spo2-Mocdel', 'spo2_model.pth')
    if os.path.exists(spo2_model_path):
        spo2_model.load_state_dict(torch.load(spo2_model_path, map_location=device, weights_only=True))
        spo2_model.eval()
        print("SpO2 AI Model loaded successfully.")
    else:
        spo2_model = None

except Exception as e:
    print("AI Model failed to initialize:", e)
    ai_model = None
    spo2_model = None

# Class names mapping
DISEASE_CLASSES = {
    0: "Normal",
    1: "Bradycardia",
    2: "Tachycardia",
    3: "Arrhythmia"
}

SPO2_CLASSES = {
    0: "Stable",
    1: "Mild Decline",
    2: "Rapid Decline",
    3: "Critical"
}

ecg_buffers = {}
ppg_ir_buffer = {}
ppg_red_buffer = {}
spo2_history_buf = {}
WS_PORT = 8080
clients = set()

async def register(websocket):
    clients.add(websocket)
    try:
        await websocket.wait_closed()
    finally:
        clients.remove(websocket)

async def broadcast(message):
    if not clients:
        return
    await asyncio.gather(*(client.send(message) for client in clients), return_exceptions=True)

def handle_ble_notification(sender, data: bytearray):
    global ai_model
    try:
        # Arduino might send 'nan' for temperature if sensor is disconnected
        decoded = data.decode('utf-8', errors='ignore').replace(':nan', ':null')
        
        # Broadcast raw data to dashboard
        loop = asyncio.get_running_loop()
        loop.create_task(broadcast(decoded))
        
        # Try reloading model dynamically
        if ai_model is None and os.path.exists(os.path.join(os.path.dirname(__file__), 'backend', 'ecg_model.pth')):
            print("Model file found, attempting to load...")
            try:
                ai_model = ECG1DCNN(num_classes=4).to(device)
                ai_model.load_state_dict(torch.load(os.path.join(os.path.dirname(__file__), 'backend', 'ecg_model.pth'), map_location=device))
                ai_model.eval()
                print("AI Model loaded dynamically.")
            except:
                pass

        payload = json.loads(decoded)
        
        if payload.get("type") == "ecg":
            dev_id = payload.get("device")
            ecg_data = payload.get("data", [])
            
            # --- Log ECG to CSV ---
            with open(ecg_csv_path, 'a', newline='') as f:
                writer = csv.writer(f)
                ts = datetime.now().isoformat()
                for val in ecg_data:
                    writer.writerow([ts, dev_id, val])
            # ----------------------
            
            if ai_model:
                
                if dev_id not in ecg_buffers:
                    ecg_buffers[dev_id] = []
                    
                ecg_buffers[dev_id].extend(ecg_data)
                
                if len(ecg_buffers[dev_id]) >= 2500:
                    raw_signal = np.array(ecg_buffers[dev_id][-2500:], dtype=np.float32)
                    signal = resample(raw_signal, 1000)
                    
                    nyquist = 0.5 * 100.0
                    low = 0.5 / nyquist
                    high = 40.0 / nyquist
                    b, a = butter(3, [low, high], btype='band')
                    signal = filtfilt(b, a, signal)
                    
                    if np.std(signal) != 0:
                        signal = (signal - np.mean(signal)) / np.std(signal)
                        
                    tensor_signal = torch.tensor(signal, dtype=torch.float32).unsqueeze(0).unsqueeze(0).to(device)
                    
                    with torch.no_grad():
                        outputs = ai_model(tensor_signal)
                        _, predicted = torch.max(outputs.data, 1)
                        condition_idx = predicted.item()
                        condition = DISEASE_CLASSES.get(condition_idx, "Unknown")
                        
                    print(f"[AI] Device {dev_id} predicted condition: {condition}")
                    ecg_buffers[dev_id] = ecg_buffers[dev_id][-1250:]
                    
                    # Send AI prediction to dashboard
                    prediction_msg = json.dumps({
                        "device": dev_id,
                        "type": "ai_prediction",
                        "condition": condition
                    })
                    asyncio.create_task(broadcast(prediction_msg))
                    
        elif payload.get("type") == "ppg_raw":
            dev_id = payload.get("device")
            
            if "ppg_processors" not in globals():
                global ppg_processors
                ppg_processors = {}
                
            if dev_id not in ppg_processors:
                ppg_processors[dev_id] = PPGProcessor(fs=100)
                
            processor = ppg_processors[dev_id]
            ir_array = payload.get("ir", [])
            red_array = payload.get("red", [])
            
            # --- Buffer PPG for BP Inference ---
            if dev_id not in ppg_ir_buffer:
                ppg_ir_buffer[dev_id] = []
            ppg_ir_buffer[dev_id].extend(ir_array)
            
            if len(ppg_ir_buffer[dev_id]) > 500:
                ppg_ir_buffer[dev_id] = ppg_ir_buffer[dev_id][-500:]
                
            if len(ecg_buffers.get(dev_id, [])) >= 500 and len(ppg_ir_buffer[dev_id]) == 500:
                ecg_win = ecg_buffers[dev_id][-500:]
                ppg_win = ppg_ir_buffer[dev_id]
                
                try:
                    bp_result = predict_bp(ecg_win, ppg_win, fs=100)
                    if bp_result is not None:
                        bp_msg = json.dumps({
                            "device": dev_id,
                            "type": "bp",
                            "sbp": bp_result["sbp"],
                            "dbp": bp_result["dbp"],
                            "status": bp_result["status"]
                        })
                        asyncio.create_task(broadcast(bp_msg))
                except Exception as e:
                    pass
            # -----------------------------------
            
            bpm, spo2, hrv_sdnn, hrv_rmssd = processor.process_samples(ir_array, red_array)
            
            print(f"[Vitals] bpm: {bpm}, spo2: {spo2}% (history: {len(processor.bpm_history)})")
            
            # --- Log Vitals to CSV ---
            if bpm > 0:
                with open(vitals_csv_path, 'a', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow([datetime.now().isoformat(), dev_id, spo2, round(hrv_sdnn, 1), round(hrv_rmssd, 1)])
            # -------------------------
            
            # --- SpO2 AI Inference ---
            if "spo2_model" in globals() and spo2_model is not None and spo2 > 0:
                if dev_id not in spo2_history_buf:
                    spo2_history_buf[dev_id] = []
                spo2_history_buf[dev_id].append(spo2)
                
                # Keep sliding window of 60 seconds
                if len(spo2_history_buf[dev_id]) > 60:
                    spo2_history_buf[dev_id].pop(0)
                    
                if len(spo2_history_buf[dev_id]) == 60:
                    raw_spo2 = np.array(spo2_history_buf[dev_id], dtype=np.float32)
                    # Normalize identically to training
                    norm_spo2 = (raw_spo2 - 90.0) / 10.0
                    
                    tensor_spo2 = torch.tensor(norm_spo2, dtype=torch.float32).unsqueeze(0).unsqueeze(-1).to(device)
                    with torch.no_grad():
                        outputs = spo2_model(tensor_spo2)
                        _, predicted = torch.max(outputs.data, 1)
                        condition_idx = predicted.item()
                        
                    if condition_idx > 0:
                        condition = SPO2_CLASSES.get(condition_idx, "Unknown")
                        print(f"[AI] SpO2 deterioration detected: {condition}")
                        warning_msg = json.dumps({
                            "device": dev_id,
                            "type": "spo2_warning",
                            "condition": condition
                        })
                        asyncio.create_task(broadcast(warning_msg))
            # -------------------------
            
            # Always broadcast processed vitals so dashboard updates
            summary = {
                "device": dev_id,
                "type": "ppg",
                "bpm": bpm,
                "spo2": spo2,
                "hrv_sdnn": round(hrv_sdnn, 1),
                "hrv_rmssd": round(hrv_rmssd, 1)
            }
            asyncio.create_task(broadcast(json.dumps(summary)))

        elif payload.get("type") == "temp":
            dev_id = payload.get("device")
            temp_val = payload.get("val")
            if temp_val is None:
                temp_val = 0.0
            
            # Forward directly to dashboard
            summary = {
                "device": dev_id,
                "type": "temp",
                "val": temp_val
            }
            asyncio.create_task(broadcast(json.dumps(summary)))
            
        elif payload.get("type") == "ppg":
            # If user flashed ayuScan_2nd.ino, it sends summarized PPG instead of ppg_raw
            dev_id = payload.get("device")
            bpm = payload.get("bpm", 0)
            spo2 = payload.get("spo2", 0)
            
            summary = {
                "device": dev_id,
                "type": "ppg",
                "bpm": bpm,
                "spo2": spo2,
                "hrv_sdnn": payload.get("hrv_sdnn", 0),
                "hrv_rmssd": payload.get("hrv_rmssd", 0)
            }
            asyncio.create_task(broadcast(json.dumps(summary)))

    except json.JSONDecodeError as e:
        print(f"JSON Decode Error: {e} - Raw data: {decoded[:100]}...")
    except Exception as e:
        print("Inference error:", e)

async def ble_worker():
    while True:
        try:
            print(f"Scanning for BLE device: {DEVICE_NAME}...")
            devices = await BleakScanner.discover(timeout=5.0)
            target_device = None
            for d in devices:
                if d.name == DEVICE_NAME:
                    target_device = d
                    break
            
            if target_device is None:
                print(f"Device {DEVICE_NAME} not found. Retrying in 5s...")
                await asyncio.sleep(5)
                continue

            print(f"Found {DEVICE_NAME}. Connecting...")
            async with BleakClient(target_device.address) as client:
                print("Connected! Subscribing to characteristics...")
                
                await client.start_notify(ECG_CHAR_UUID, handle_ble_notification)
                await client.start_notify(VITALS_CHAR_UUID, handle_ble_notification)
                
                print("Streaming data... Press Ctrl+C to stop.")
                
                # Keep connection alive
                while client.is_connected:
                    await asyncio.sleep(1)
                    
            print("BLE device disconnected.")
        except Exception as e:
            print(f"BLE Error: {e}")
            await asyncio.sleep(5)

async def main():
    # Start WebSocket server
    ws_server = websockets.serve(register, "0.0.0.0", WS_PORT)
    print(f"WebSocket server running on ws://0.0.0.0:{WS_PORT}")
    
    # Run BLE worker and WS server concurrently
    await asyncio.gather(
        ws_server,
        ble_worker()
    )

if __name__ == "__main__":
    asyncio.run(main())
