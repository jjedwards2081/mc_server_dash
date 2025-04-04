from flask import Flask, jsonify, request, render_template, send_file, send_from_directory
import subprocess
from pathlib import Path
import json
import os
from collections import Counter
from collections import defaultdict
import matplotlib
matplotlib.use('Agg')  # Prevent macOS issues with Matplotlib
import matplotlib.pyplot as plt
import io
import numpy as np
import requests  # Add this import to fetch the public IP address
import sys

# Start the WebSocket server
server_path = os.path.abspath("../websocket_server/server.py")  # Adjust the path as needed
subprocess.Popen([sys.executable, server_path])

app = Flask(__name__)
ws_process = None
websocket_process = None

# Determine the base directory relative to this file
APP_DIR = Path(__file__).resolve().parent
BASE_DIR = APP_DIR.parent
DATA_DIR = BASE_DIR / "data"
SERVER_PATH = BASE_DIR / "websocket_server" / "server.py"

app = Flask(__name__)

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/webserver')
def webserver():
    return render_template('webserver.html')

@app.route('/langanl')
def langanl():
    return render_template('langanl.html')

@app.route('/download/<filename>')
def download_file(filename):
    logs_dir = os.path.expanduser("~/data")  # Or wherever your event logs are
    return send_from_directory(logs_dir, filename, as_attachment=True)


@app.route('/start-server', methods=['POST'])
def start_server():
    global websocket_process
    try:
        server_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'websocket_server', 'server.py'))
        websocket_process = subprocess.Popen([sys.executable, server_path])
        return jsonify({'status': 'WebSocket server started.'})
    except Exception as e:
        return jsonify({'status': f'Failed to start server: {e}'})

@app.route('/stop-server', methods=['POST'])
def stop_server():
    global websocket_process
    if websocket_process is not None:
        websocket_process.terminate()
        websocket_process.wait()
        websocket_process = None  # ✅ Clear the reference
        return jsonify({'status': 'WebSocket server stopped.'})
    return jsonify({'status': 'Server was not running.'})

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
    positions = defaultdict(list)

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
            name = player.get("name", "Unknown")
            pos = player.get("position", {})
            x = round(pos.get("x", 0))
            z = round(pos.get("z", 0))
            positions[name].append((x, z))

    return jsonify({
        "joins": join_count,
        "messages": chat_count,
        "total_events": len(events),
        "join_timestamps": join_timestamps,
        "event_types": dict(event_types),
        "positions": dict(positions)
    })

@app.route("/generate-heatmap")
def generate_heatmap():
    filename = request.args.get("file")
    if not filename:
        return jsonify({"error": "No file provided"}), 400

    path = DATA_DIR / filename
    if not path.exists():
        return jsonify({"error": "File not found"}), 404

    with path.open() as f:
        events = json.load(f)

    positions = []
    for e in events:
        if e.get("event") == "PlayerTransform":
            player = e.get("body", {}).get("player", {})
            pos = player.get("position", {})
            x = round(pos.get("x", 0))
            z = round(pos.get("z", 0))
            positions.append((x, z))

    if not positions:
        return jsonify({"error": "No movement data"}), 400

    xs, zs = zip(*positions)
    heatmap, xedges, yedges = np.histogram2d(xs, zs, bins=100)
    extent = [xedges[0], xedges[-1], yedges[0], yedges[-1]]

    fig, ax = plt.subplots()
    cax = ax.imshow(
        heatmap.T,
        extent=extent,
        origin='lower',
        cmap='hot',
        interpolation='nearest'
    )
    ax.set_title('Player Movement Heatmap')
    ax.set_xlabel('X')
    ax.set_ylabel('Z')
    fig.colorbar(cax, ax=ax, label='Movement Density')

    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    plt.close(fig)
    buf.seek(0)

    return send_file(buf, mimetype='image/png')

@app.route('/status')
def status():
    global websocket_process
    running = websocket_process is not None and websocket_process.poll() is None
    return jsonify({'websocket_running': running})

@app.route("/connection-info", methods=["GET"])
def connection_info():
    try:
        # Fetch the public IP address
        public_ip = requests.get("https://api.ipify.org").text
        port = 19131  # The port your Flask app is running on
        connection_string = f"/connect {public_ip}:{port}"
        return jsonify({"connection_string": connection_string})
    except Exception as e:
        return jsonify({"error": "Unable to fetch connection info", "details": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050)