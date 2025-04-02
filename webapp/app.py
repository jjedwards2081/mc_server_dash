"""
app.py

This script is a Flask-based web application that provides a dashboard for managing a Minecraft server.
It includes endpoints for starting/stopping a WebSocket server, listing event files, analyzing event data,
and checking the server's status. The application also serves an HTML interface for user interaction.

Author: Justin Edwards
License: MIT License
"""

# MIT License
# 
# Copyright (c) 2023 Justine Edwards
# 
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
# 
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
# 
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

from flask import Flask, jsonify, request, render_template
import subprocess
from pathlib import Path
import json
from pathlib import Path
import os
from collections import Counter

app = Flask(__name__)
ws_process = None

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

    for e in events:
        event_name = e.get("event")
        event_types[event_name] += 1
        if event_name == "PlayerJoin":
            join_count += 1
            join_timestamps.append(e.get("timestamp"))
        elif event_name == "PlayerMessage":
            chat_count += 1

    return jsonify({
        "joins": join_count,
        "messages": chat_count,
        "total_events": len(events),
        "join_timestamps": join_timestamps,
        "event_types": dict(event_types)  # 💥 this is what the chart uses
    })

@app.route("/status")
def status():
    is_running = ws_process is not None and ws_process.poll() is None
    return jsonify({
        "websocket_running": is_running
    })
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050)
