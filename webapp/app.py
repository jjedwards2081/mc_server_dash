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
    count = len(ws_process._children) if ws_process else 0
    return jsonify({"websocket_running": ws_process is not None, "connected_clients": count})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050)
