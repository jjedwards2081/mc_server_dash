from flask import Flask, jsonify, request, render_template, send_file, send_from_directory, abort
import subprocess
from pathlib import Path
import json
import os
from collections import Counter, defaultdict
import matplotlib
matplotlib.use('Agg')  # For macOS
import matplotlib.pyplot as plt
import io
import numpy as np
import requests
import sys
from werkzeug.utils import secure_filename
import textstat
import re
import zipfile
import tempfile
from datetime import datetime
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')  # Ensure headless rendering
import hashlib

app = Flask(__name__)

# Globals for process tracking
websocket_process = None

MAX_TOKENS = 4000  # Safe chunk size (adjust based on your model's capacity)
PLACEHOLDER_PATTERN = r"\{.*?\}|\%s|\§."

# Directories
APP_DIR = Path(__file__).resolve().parent
BASE_DIR = APP_DIR.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)  # Ensure the parent directory exists

LANGUAGE_TOOL_DIR = DATA_DIR / "languagetooldata"
LANGUAGE_TOOL_DIR.mkdir(exist_ok=True)  # Create the subdirectory

PLACEHOLDER_PATTERN = r"(%\d*\$?[sd]|\\n|\u00a7.)"

def is_just_formatting(value):
    cleaned = re.sub(PLACEHOLDER_PATTERN, "", value)
    return not cleaned.strip()

# ────────────────────────────── ROUTES ────────────────────────────── #

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/webserver')
def webserver():
    return render_template('webserver.html')

@app.route('/langanl')
def langanl():
    return render_template('langanl.html')

@app.route('/materials-generator')
def materials_generator():
    return render_template('ai_materials_gen.html')


@app.route('/upload-lang-file', methods=['POST'])
def upload_lang_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    filename = secure_filename(file.filename)
    save_path = LANGUAGE_TOOL_DIR / filename
    file.save(save_path)
    return jsonify({'status': f'File {filename} uploaded.'})

@app.route('/upload-mcworld', methods=['POST'])
def upload_mcworld():
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'Empty filename'}), 400

    filename = secure_filename(file.filename)
    world_name = Path(filename).stem
    world_dir = LANGUAGE_TOOL_DIR / world_name
    world_dir.mkdir(parents=True, exist_ok=True)

    # Save the uploaded file temporarily
    temp_path = LANGUAGE_TOOL_DIR / filename
    file.save(temp_path)

    try:
        # Unzip the .mcworld into the world-specific folder
        with zipfile.ZipFile(temp_path, 'r') as zip_ref:
            zip_ref.extractall(world_dir)

        # Save the original .mcworld filename for later reporting
        with open(world_dir / "source_world_name.txt", "w", encoding="utf-8") as f:
            f.write(filename)

    except Exception as e:
        return jsonify({'error': f'Failed to unzip: {e}'}), 500
    finally:
        temp_path.unlink(missing_ok=True)  # Clean up uploaded zip

    # Find all .lang files inside the extracted world folder
    lang_files = []
    for path in world_dir.rglob('*.lang'):
        size_kb = round(path.stat().st_size / 1024, 2)
        relative = path.relative_to(LANGUAGE_TOOL_DIR)
        lang_files.append({'name': str(relative), 'size': size_kb})

    return jsonify({'lang_files': lang_files})

@app.route('/analyze-lang-file', methods=['POST'])
def analyze_lang_file():
    data = request.json
    rel_path = data.get("filename")
    if not rel_path:
        return jsonify({"error": "No file provided"}), 400

    path = LANGUAGE_TOOL_DIR / rel_path
    if not path.exists():
        return jsonify({"error": "File not found"}), 404

    # Walk up from lang file path to find original .mcworld filename
    current_dir = path.parent
    world_filename = "(unknown)"
    while current_dir != LANGUAGE_TOOL_DIR:
        candidate = current_dir / "source_world_name.txt"
        if candidate.exists():
            with open(candidate, "r", encoding="utf-8") as f:
                world_filename = f.read().strip()
            break
        current_dir = current_dir.parent

    # Read all lines from the lang file
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # Extract useful lines
    texts = [line.strip().split("=", 1)[1] for line in lines if "=" in line and not is_just_formatting(line)]
    joined_text = "\n".join(texts)

    # Compute readability metrics
    difficult_words_list = textstat.difficult_words_list(joined_text)
    difficult_word_counts = {word: difficult_words_list.count(word) for word in set(difficult_words_list)}

    analysis = {
        "Flesch Reading Ease": textstat.flesch_reading_ease(joined_text),
        "Flesch-Kincaid Grade": textstat.flesch_kincaid_grade(joined_text),
        "SMOG Index": textstat.smog_index(joined_text),
        "Dale-Chall Score": textstat.dale_chall_readability_score(joined_text),
        "Automated Readability Index": textstat.automated_readability_index(joined_text),
        "Difficult Word Count": len(difficult_words_list),
        "Line Count": len(texts),
        "Difficult Words": difficult_word_counts
    }

    # ── Save main summary .txt report ─────────────────────────────
    analysis_file = path.parent / f"analysis_{Path(rel_path).stem}.txt"
    with open(analysis_file, "w", encoding="utf-8") as f:
        f.write(f"World File: {world_filename}\n")
        f.write(f"Language File: {Path(rel_path).name}\n")
        f.write(f"Analysis Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("-" * 50 + "\n\n")
        for key, value in analysis.items():
            if isinstance(value, dict):
                f.write(f"\n{key}:\n")
                for word, count in sorted(value.items()):
                    f.write(f"  - {word} ({count})\n")
            else:
                f.write(f"{key}: {value}\n")

    # ── Save per-line reading age .json ──────────────────────────
    line_analysis = []
    for i, line in enumerate(lines, 1):
        if "=" in line and not is_just_formatting(line):
            try:
                _, value = line.strip().split("=", 1)
                reading_age = textstat.flesch_kincaid_grade(value)
            except Exception:
                value = ""
                reading_age = None
            line_analysis.append({
                "line": i,
                "text": value.strip(),
                "reading_age": reading_age
            })

    json_path = path.parent / f"line_analysis_{Path(rel_path).stem}.json"
    with open(json_path, "w", encoding="utf-8") as jf:
        json.dump(line_analysis, jf, indent=2)

    # ── Generate histogram chart (only reading_age > 0) ──────────
    filtered_reading_ages = [
        entry["reading_age"] for entry in line_analysis
        if isinstance(entry["reading_age"], (int, float)) and entry["reading_age"] > 0
    ]

    chart_path = path.parent / f"reading_age_distribution_{Path(rel_path).stem}.png"
    if filtered_reading_ages:
        plt.figure(figsize=(10, 6))
        plt.hist(filtered_reading_ages, bins=30, color='orange', edgecolor='black')
        plt.title("Distribution of Reading Age")
        plt.xlabel("Reading Age")
        plt.ylabel("Frequency")
        plt.savefig(chart_path)
        plt.close()

    # ── Save lines with reading_age > 16 ─────────────────────────
    high_reading_lines = [
        f"Line {entry['line']}: {entry['text']} (Reading Age: {entry['reading_age']})"
        for entry in line_analysis
        if isinstance(entry["reading_age"], (int, float)) and entry["reading_age"] > 16
    ]

    high_reading_path = path.parent / f"above_reading_age_16_{Path(rel_path).stem}.txt"
    with open(high_reading_path, "w", encoding="utf-8") as f:
        f.write("Lines with Reading Age > 16\n")
        f.write("=" * 40 + "\n\n")
        for line in high_reading_lines:
            f.write(line + "\n")

    # ── Return file URLs for frontend download ───────────────────
    return jsonify({
        "file_url": f"/download-analysis/{analysis_file.relative_to(LANGUAGE_TOOL_DIR)}",
        "json_url": f"/download-analysis/{json_path.relative_to(LANGUAGE_TOOL_DIR)}",
        "chart_url": f"/download-analysis/{chart_path.relative_to(LANGUAGE_TOOL_DIR)}",
        "high_reading_url": f"/download-analysis/{high_reading_path.relative_to(LANGUAGE_TOOL_DIR)}"
    })

@app.route('/download-analysis/<path:filename>')
def download_analysis_file(filename):
    file_path = LANGUAGE_TOOL_DIR / filename
    if not file_path.exists():
        return abort(404)
    return send_from_directory(LANGUAGE_TOOL_DIR, filename, as_attachment=True)

@app.route('/start-server', methods=['POST'])
def start_server():
    global websocket_process
    try:
        websocket_process = subprocess.Popen([sys.executable, str(SERVER_PATH)])
        return jsonify({'status': 'WebSocket server started.'})
    except Exception as e:
        return jsonify({'status': f'Failed to start server: {e}'})

@app.route('/stop-server', methods=['POST'])
def stop_server():
    global websocket_process
    if websocket_process is not None:
        websocket_process.terminate()
        websocket_process.wait()
        websocket_process = None
        return jsonify({'status': 'WebSocket server stopped.'})
    return jsonify({'status': 'Server was not running.'})

@app.route('/clear-json-data', methods=['POST'])
def clear_json_data():
    deleted = []
    for file in DATA_DIR.glob("*.json"):
        try:
            file.unlink()
            deleted.append(file.name)
        except Exception as e:
            return jsonify({'status': f'Failed to delete {file.name}: {e}'}), 500
    return jsonify({'status': f'Deleted {len(deleted)} JSON file(s).'}) 

@app.route('/status')
def status():
    global websocket_process
    running = websocket_process is not None and websocket_process.poll() is None
    return jsonify({'websocket_running': running})

@app.route("/list-files", methods=["GET"])
def list_files():
    files = [f.name for f in DATA_DIR.glob("events_*.json")]
    lang_files = [f.name for f in (DATA_DIR / "languagetooldata").glob("*.lang")]
    return jsonify({"files": files + lang_files})

@app.route("/download/<path:filename>", methods=['GET'])
def download_file(filename):
    directory = LANGUAGE_TOOL_DIR  # Ensure this points to the directory where JSON files are stored
    return send_from_directory(directory, filename, as_attachment=True)

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

@app.route("/connection-info", methods=["GET"])
def connection_info():
    try:
        public_ip = requests.get("https://api.ipify.org").text
        port = 19131
        connection_string = f"/connect {public_ip}:{port}"
        return jsonify({"connection_string": connection_string})
    except Exception as e:
        return jsonify({"error": "Unable to fetch connection info", "details": str(e)}), 500

@app.route('/ai_lang_tool')
def ai_lang_tool():
    return render_template('ai_lang_tool.html')

@app.route("/run-lang-analysis", methods=["POST"])
def run_lang_analysis():
    data = request.json
    filename = data.get("filename")
    model = data.get("model", "phi4")  # Allow user to specify model, default to phi4

    if not filename:
        return jsonify({"error": "Filename is required"}), 400

    file_path = LANGUAGE_TOOL_DIR / filename
    if not file_path.exists():
        return jsonify({"error": "File not found"}), 404

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            file_content = f.read()
    except Exception as e:
        return jsonify({"error": f"Failed to read file: {e}"}), 500

    # Extract only dialogue-related text
    npc_texts = []
    for line in file_content.splitlines():
        if "=" in line and not is_just_formatting(line):
            key, value = line.split("=", 1)
            key_lower = key.lower()
            if key_lower.startswith("dialogue.") or key_lower.startswith("npc.") or "dialogue" in key_lower:
                cleaned_value = re.sub(PLACEHOLDER_PATTERN, "", value).strip()
                if cleaned_value:
                    npc_texts.append(cleaned_value)

    # If no NPC text extracted, fallback to analyzing ALL meaningful lines
    if not npc_texts:
        for line in file_content.splitlines():
            if "=" in line and not is_just_formatting(line):
                _, value = line.split("=", 1)
                cleaned_value = re.sub(PLACEHOLDER_PATTERN, "", value).strip()
                if cleaned_value:
                    npc_texts.append(cleaned_value)

    # If too large, break into chunks
    npc_chunks = []
    current_chunk = []
    current_length = 0

    for text in npc_texts:
        text_length = len(text.split())
        if current_length + text_length > MAX_TOKENS:
            npc_chunks.append("\n".join(current_chunk))
            current_chunk = [text]
            current_length = text_length
        else:
            current_chunk.append(text)
            current_length += text_length

    if current_chunk:
        npc_chunks.append("\n".join(current_chunk))

    final_report = []

    for idx, chunk in enumerate(npc_chunks):
        prompt = (
            "You are an expert in education content development.\n"
            "I will provide a Minecraft Education language file.\n"
            "Focus ONLY on NPC game text. Ignore placeholders and formatting.\n"
            "Your tasks are:\n"
            "States the learning objectives of this game, given the NPC game text.\n"
            f"Here is the extracted NPC text chunk ({idx+1}/{len(npc_chunks)}):\n\n{chunk}\n\n"
            "Please write a detailed analysis report."
        )

        try:
            process = subprocess.run(
                ["ollama", "run", model],
                input=prompt.encode("utf-8"),
                text=False,
                capture_output=True,
                check=True
            )
            output = process.stdout.decode("utf-8").strip()
            final_report.append(output)
        except subprocess.CalledProcessError as e:
            return jsonify({"error": f"Ollama model error: {e.stderr.decode('utf-8').strip()}"}), 500

    # Combine all chunk analyses
    full_output1 = "\n\n".join(final_report)
    
    final_report = []

    for idx, chunk in enumerate(npc_chunks):
        prompt = (
            "You are an expert in education content development.\n"
            "I will provide a Minecraft Education language file.\n"
            "Focus ONLY on NPC game text. Ignore placeholders and formatting.\n"
            "Your tasks are:\n"
            "- Highlight grammar and readability issues, with examples.\n\n"
            f"Here is the extracted NPC text chunk ({idx+1}/{len(npc_chunks)}):\n\n{chunk}\n\n"
            "Please write a detailed analysis report."
        )

        try:
            process = subprocess.run(
                ["ollama", "run", model],
                input=prompt.encode("utf-8"),
                text=False,
                capture_output=True,
                check=True
            )
            output = process.stdout.decode("utf-8").strip()
            final_report.append(output)
        except subprocess.CalledProcessError as e:
            return jsonify({"error": f"Ollama model error: {e.stderr.decode('utf-8').strip()}"}), 500

            # Combine all chunk analyses
    
    full_output2 = "\n\n".join(final_report)
    
    full_output = "Part 1:\n\n" + full_output1 + "\n\nPart 2:\n\n" + full_output2

    return jsonify({"output": full_output})

@app.route('/unpack-and-json', methods=['POST'])
def unpack_and_json():
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'Empty filename'}), 400

    filename = secure_filename(file.filename)
    world_name = Path(filename).stem
    world_dir = LANGUAGE_TOOL_DIR / world_name
    world_dir.mkdir(parents=True, exist_ok=True)

    # Save the uploaded file temporarily
    temp_path = LANGUAGE_TOOL_DIR / filename
    file.save(temp_path)

    try:
        # Unzip the .mcworld into the world-specific folder
        with zipfile.ZipFile(temp_path, 'r') as zip_ref:
            zip_ref.extractall(world_dir)

        # Find the largest en_US.lang file
        lang_files = list(world_dir.rglob('*en_US.lang'))
        if not lang_files:
            return jsonify({'error': 'No en_US.lang file found'}), 400

        largest_file = max(lang_files, key=lambda f: f.stat().st_size)

        # Convert the largest en_US.lang file to JSON
        json_output_path = world_dir / f"{world_name}_en_US.json"
        with open(largest_file, 'r', encoding='utf-8') as lang_file, open(json_output_path, 'w', encoding='utf-8') as json_file:
            json_data = {}
            for line_number, line in enumerate(lang_file, start=1):
                json_data[line_number] = line.strip()
            json.dump(json_data, json_file, indent=4)

        # Return the relative path for the JSON file
        relative_json_path = json_output_path.relative_to(LANGUAGE_TOOL_DIR)
        return jsonify({
            'status': 'File processed successfully',
            'json_file': f"/download/{relative_json_path.as_posix()}",
            'lang_files': [{'name': f.name, 'size': round(f.stat().st_size / 1024, 2)} for f in lang_files]
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        temp_path.unlink(missing_ok=True)  # Clean up uploaded zip

# ────────────────────────────── RUN ────────────────────────────── #

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050)