import asyncio
import websockets
import json
import uuid
import signal
import sys
import socket
from pathlib import Path
from datetime import datetime

clients = set()

# Setup data file
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
DATA_FILE = DATA_DIR / f"events_{timestamp}.json"
LOG_FILE = DATA_DIR / f"server_{timestamp}.log"

event_log = []

# Set up logging function
def log_message(message):
    with open(LOG_FILE, "a") as log_file:
        log_file.write(f"{datetime.now().isoformat()} - {message}\n")
    print(message)  # Print to console as well

# Fetch local IP address
def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(('8.8.8.8', 80))  # Google DNS
    local_ip = s.getsockname()[0]
    s.close()
    return local_ip

async def save_event_log():
    try:
        with DATA_FILE.open("w") as f:
            json.dump(event_log, f, indent=2)
        log_message(f"Events saved to: {DATA_FILE}")
    except Exception as e:
        log_message(f"Error saving events: {e}")

async def subscribe_event(websocket, event_name):
    await websocket.send(json.dumps({
        "header": {
            "version": 1,
            "requestId": str(uuid.uuid4()),
            "messagePurpose": "subscribe",
            "messageType": "commandRequest"
        },
        "body": {
            "eventName": event_name
        }
    }))
    log_message(f"[{websocket.remote_address[0]}] ← Subscribed to {event_name}")

async def handler(websocket):
    client_ip = websocket.remote_address[0]
    clients.add(websocket)

    log_message(f"[+] Connection from {client_ip}")

    # Subscribe to all desired events
    for event in ["PlayerJoin", "PlayerLeave", "PlayerMessage", "PlayerTransform", "BlockPlaced"]:
        await subscribe_event(websocket, event)

    try:
        async for message in websocket:
            try:
                data = json.loads(message)
            except json.JSONDecodeError:
                continue

            header = data.get("header", {})
            body = data.get("body", {})
            event_name = header.get("eventName", "")
            message_type = header.get("messagePurpose", "")

            # Only handle event messages
            if message_type == "event":
                event_entry = {
                    "event": event_name,
                    "body": body,
                    "client_ip": client_ip,
                    "timestamp": datetime.now().isoformat()
                }

                event_log.append(event_entry)
                await save_event_log()

    except websockets.exceptions.ConnectionClosed as e:
        pass
    except Exception as e:
        log_message(f"[!!] Error with {client_ip}: {e}")
    finally:
        clients.remove(websocket)
        log_message(f"Connected: {len(clients)}")  # Print active client count

async def main():
    # Fetch the local IP address of the server
    local_ip = get_local_ip()
    server_url = f"To connect, type in Minecraft chat: /connect {local_ip}:19131"
    
    log_message(f"Server starting on {server_url}")
    log_message(f"Events will be logged to: {DATA_FILE}")
    
    # Start WebSocket server
    server = await websockets.serve(handler, local_ip, 19131)

    # Set up signal handling for graceful exit
    loop = asyncio.get_event_loop()
    loop.add_signal_handler(signal.SIGINT, lambda: asyncio.create_task(shutdown(server)))

    # Wait for server to run until we receive a signal
    try:
        await asyncio.Future()  # Run forever
    except asyncio.CancelledError:
        pass
    finally:
        await shutdown(server)

async def shutdown(server):
    log_message("\nServer is shutting down...")
    server.close()
    await server.wait_closed()
    log_message("Server closed gracefully.")
    await save_event_log()  # Save the final events before exit

if __name__ == "__main__":
    asyncio.run(main())

