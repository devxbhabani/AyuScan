import socket
import asyncio
import websockets
import threading

UDP_IP = "0.0.0.0"
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
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((UDP_IP, UDP_PORT))
    print(f"Listening on UDP port {UDP_PORT}...")
    
    while True:
        try:
            data, addr = sock.recvfrom(65535)
            # Print to console for debugging, just like original
            decoded = data.decode('utf-8', errors='ignore')
            print(f"Received from {addr}: {decoded[:100]}...")
            
            # Schedule the broadcast in the async event loop
            loop.call_soon_threadsafe(lambda: asyncio.create_task(broadcast(decoded)))
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