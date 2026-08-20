import socket
import asyncio
import websockets
import threading
import json
import sys
import os
import torch
import numpy as np
from scipy.signal import butter, filtfilt, resample

# Add AI model path
sys.path.append(os.path.join(os.path.dirname(__file__), 'backend', 'AI-model'))
try:
    from model import ECG1DCNN
    
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    ai_model = ECG1DCNN(num_classes=4).to(device)
    model_path = os.path.join(os.path.dirname(__file__), 'backend', 'ecg_model.pth')
    if os.path.exists(model_path):
        ai_model.load_state_dict(torch.load(model_path, map_location=device))
        ai_model.eval()
        print("AI Model loaded successfully from:", model_path)
    else:
        print("AI Model not found at", model_path, "- waiting for training to finish.")
        ai_model = None
except Exception as e:
    print("AI Model failed to initialize:", e)
    ai_model = None

# Class names mapping
DISEASE_CLASSES = {
    0: "Normal",
    1: "Bradycardia",
    2: "Tachycardia",
    3: "Arrhythmia"
}

# Buffer for ECG data
ecg_buffers = {} # device_id -> list of points

UDP_IP = "192.168.137.1"
UDP_PORT = 5005
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
    # Use gather to send to all clients concurrently
    await asyncio.gather(*(client.send(message) for client in clients), return_exceptions=True)

def udp_listener(loop):
    global ai_model
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((UDP_IP, UDP_PORT))
    print(f"Listening on UDP port {UDP_PORT}...")
    
    while True:
        try:
            data, addr = sock.recvfrom(65535)
            decoded = data.decode('utf-8', errors='ignore')
            
            # Schedule the broadcast in the async event loop
            loop.call_soon_threadsafe(lambda d=decoded: asyncio.create_task(broadcast(d)))
            
            # Try reloading model if it wasn't there before
            if ai_model is None and os.path.exists(os.path.join(os.path.dirname(__file__), 'backend', 'ecg_model.pth')):
                print("Model file found, attempting to load...")
                try:
                    ai_model = ECG1DCNN(num_classes=4).to(device)
                    ai_model.load_state_dict(torch.load(os.path.join(os.path.dirname(__file__), 'backend', 'ecg_model.pth'), map_location=device))
                    ai_model.eval()
                    print("AI Model loaded dynamically.")
                except:
                    pass

            # Run inference if AI model is loaded and this is ECG data
            if ai_model:
                try:
                    payload = json.loads(decoded)
                    if payload.get("type") == "ecg":
                        dev_id = payload.get("device")
                        ecg_data = payload.get("data", [])
                        
                        if dev_id not in ecg_buffers:
                            ecg_buffers[dev_id] = []
                            
                        ecg_buffers[dev_id].extend(ecg_data)
                        
                        # If we have 2500 points (10s at 250Hz)
                        if len(ecg_buffers[dev_id]) >= 2500:
                            # Take the latest 2500 points
                            raw_signal = np.array(ecg_buffers[dev_id][-2500:], dtype=np.float32)
                            
                            # Downsample from 250Hz (ESP32) to 100Hz (Model requirement) -> 1000 points
                            signal = resample(raw_signal, 1000)
                            
                            # Bandpass filter (0.5Hz to 40Hz)
                            nyquist = 0.5 * 100.0
                            low = 0.5 / nyquist
                            high = 40.0 / nyquist
                            b, a = butter(3, [low, high], btype='band')
                            signal = filtfilt(b, a, signal)
                            
                            # Normalize
                            if np.std(signal) != 0:
                                signal = (signal - np.mean(signal)) / np.std(signal)
                                
                            tensor_signal = torch.tensor(signal, dtype=torch.float32).unsqueeze(0).unsqueeze(0).to(device)
                            
                            with torch.no_grad():
                                outputs = ai_model(tensor_signal)
                                _, predicted = torch.max(outputs.data, 1)
                                condition_idx = predicted.item()
                                condition = DISEASE_CLASSES.get(condition_idx, "Unknown")
                                
                            print(f"[AI] Device {dev_id} predicted condition: {condition}")
                            
                            # Keep only a sliding window to prevent infinite growth (keep last 5s = 1250 points)
                            ecg_buffers[dev_id] = ecg_buffers[dev_id][-1250:]
                            
                            diagnosis_msg = json.dumps({
                                "type": "diagnosis",
                                "device": dev_id,
                                "condition": condition
                            })
                            loop.call_soon_threadsafe(lambda d=diagnosis_msg: asyncio.create_task(broadcast(d)))
                except json.JSONDecodeError:
                    pass
                except Exception as e:
                    print("Inference error:", e)
                    
        except Exception as e:
            print(f"UDP Error: {e}")

async def main():
    loop = asyncio.get_running_loop()
    
    # Run the UDP listener in a daemon thread so it doesn't block asyncio
    thread = threading.Thread(target=udp_listener, args=(loop,), daemon=True)
    thread.start()
    
    # Start WebSocket server
    async with websockets.serve(register, "0.0.0.0", WS_PORT):
        print(f"WebSocket server running on ws://0.0.0.0:{WS_PORT}")
        await asyncio.Future()  # Run forever

if __name__ == "__main__":
    asyncio.run(main())