"""
app.py

This script is a Flask-based web application that provides a dashboard for managing a Minecraft server.
It includes endpoints for starting/stopping a WebSocket server, listing event files, analyzing event data,
and checking the server's status. The application also serves an HTML interface for user interaction.

Author: Justin Edwards
License: MIT License
"""

from flask import Flask, jsonify, request, render_template
import subprocess
from pathlib import Path
import json
import os
from collections import Counter

app = Flask(__name__)
ws_process = None

# Define base paths
APP_DIR = Path(__file__).resolve().parent
BASE_DIR = APP_DIR.parent
DATA_DIR = BASE_DIR / "data"
SERVER_PATH = BASE_DIR / "websocket_server" / "server.py"

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/start-server", methods=["POST"])
def start_server():
    global ws_process
    if ws_process is None:
        ws_process = subprocess.Popen(["python3", str(SERVER_PATH)])
        return jsonify({"status": "started"})
    return jsonify({"status": "already running"})

@app.route("/stop-server", methods=["POST"])
def stop_server():
    global ws_process
    if ws_process:
        ws_process.terminate()
        ws_process = None
        return jsonify({"status": "stopped"})
    return jsonify({"status": "not running"})

@app.route("/list-files", methods=["GET"])
def list_files():
    files = [f.name for f in DATA_DIR.glob("events_*.json")]
    return jsonify({"files": files})

@app.route("/analyze", methods=["GET"])
def analyze():
    filename = request.args.get("file")
    if not filename:
        return jsonify({"error": "No file provided"}), 400

    path = DATA_DIR / filename
    if not path.exists():
        return jsonify({"error": "File not found"}), 404

    with path.open() as f:
        events = json.load(f)

    event_types = Counter()
    join_count = 0
    chat_count = 0
    join_timestamps = []
    positions = []

    for e in events:
        event_name = e.get("event")
        event_types[event_name] += 1

        if event_name == "PlayerJoin":
            join_count += 1
            join_timestamps.append(e.get("timestamp"))
        elif event_name == "PlayerMessage":
            chat_count += 1
        elif event_name == "PlayerTransform":
            player = e.get("body", {}).get("player", {})
            pos = player.get("position", {})
            x = round(pos.get("x", 0))
            z = round(pos.get("z", 0))
            positions.append((x, z))

    return jsonify({
        "joins": join_count,
        "messages": chat_count,
        "total_events": len(events),
        "join_timestamps": join_timestamps,
        "event_types": dict(event_types),
        "positions": positions  # 👈 for the heatmap
    })

@app.route("/status")
def status():
    is_running = ws_process is not None and ws_process.poll() is None
    return jsonify({
        "websocket_running": is_running
    })

if __name__ == "__