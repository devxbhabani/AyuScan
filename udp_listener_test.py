"""
Minimal UDP listener — no WebSocket, no asyncio.
Purpose: confirm the ESP32's packets are actually reaching this PC
before debugging the WebSocket bridge on top of it.

Run this, then power on / reset your ESP32. You should see lines
printed here within a couple seconds of the ESP32 connecting to WiFi.

If you see NOTHING here after 10-15 seconds:
  1. Run `ipconfig` (Windows) or `ifconfig`/`ip addr` (Linux/Mac) and
     confirm this PC's IP on the same network as the ESP32.
     Update SERVER_IP in the ESP32 sketch to match EXACTLY.
  2. Temporarily disable Windows Firewall (or add an inbound rule
     for UDP port 5005) and try again.
  3. Confirm the ESP32 Serial Monitor shows "Connected. IP: ..." —
     if it never gets past "Connecting to WiFi...", it's not even
     on the same network yet, so nothing will arrive.
"""

import socket

UDP_PORT = 5005

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# Bind to 0.0.0.0 (all interfaces) rather than a specific IP —
# avoids silent failures when there are multiple network adapters
# (e.g. WiFi + hotspot + ethernet) and the "wrong" one was picked.
sock.bind(("0.0.0.0", UDP_PORT))

print(f"Listening on UDP port {UDP_PORT} (all interfaces)...")
print("Waiting for packets from the ESP32...\n")

while True:
    data, addr = sock.recvfrom(65535)
    decoded = data.decode("utf-8", errors="ignore")
    print(f"[{addr[0]}:{addr[1]}] {decoded}")
