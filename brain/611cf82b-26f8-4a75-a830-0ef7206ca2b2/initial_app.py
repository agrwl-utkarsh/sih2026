import os
import subprocess
import shutil
import torch
import whisper
import datetime
import threading
import uuid
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import db

app = Flask(__name__)
# Enable CORS for all routes and allow typical headers
CORS(app, resources={r"/*": {"origins": "*"}})

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
OUTPUT_FOLDER = os.path.join(BASE_DIR, 'outputs')

# Initialize DB structure
db.init_db()

def startup_cleanup():
    # Keep directory structure but clean file uploads/outputs on start if desired.
    # Note: For production we wouldn't wipe existing ones, but for local MVP it keeps it clean.
    for folder in [UPLOAD_FOLDER, OUTPUT_FOLDER]:
        if not os.path.exists(folder):
            os.makedirs(folder)

startup_cleanup()

# Load Whisper - Optimized for Hindi + English
device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"--- AI ENGINE: {device.upper()} (Hindi/English Support) ---")
model = whisper.load_model("base", device=device)

# Global lock for Whisper to prevent multi-thread execution conflicts
transcribe_lock = threading.Lock()

def web_to_ass_color(web_hex, opacity=1.0):
    """Converts #RRGGBB and opacity (0.0 to 1.0) to ASS format &H[Alpha]BBGGRR
    Note that ASS alpha is reversed (00 = fully opaque, FF = fully transparent)
    """
    hex_val = web_hex.lstrip('#')
    if len(hex_val) == 3:
        hex_val = "".join([c*2 for c in hex_val])
    r, g, b = hex_val[0:2], hex_val[2:4], hex_val[4:6]
    
    # Calculate inverse alpha for ASS (0 = fully opaque, 255 = fully transparent)
    alpha_int = int((1.0 - opacity) * 255)
    alpha_hex = f"{alpha_int:02X}"
    return f"&H{alpha_hex}{b}{g}{r}"

def format_timestamp_srt(seconds: float):
    td = datetime.timedelta(seconds=seconds)
    ts = int(td.total_seconds())
    ms = int(td.microseconds / 1000)
    return f"{ts//3600:02d}:{(ts%3600)//60:02d}:{ts%60:02d},{ms:03d}"

def format_timestamp_vtt(seconds: float):
    td = datetime.timedelta(seconds=seconds)
    ts = int(td.total_seconds())
    ms = int(td.microseconds / 1000)
    return f"{ts//3600:02d}:{(ts%3600)//60:02d}:{ts%60:02d}.{ms:03d}"

def run_transcription(video_id, video_path, language):
    with transcribe_lock:
        conn = db.get_db()
        cursor = conn.cursor()
        try:
            cursor.execute("UPDATE videos SET status = 'transcribing' WHERE id = ?", (video_id,))
            conn.commit()
            
            options = {}
            if language and language != 'auto':
                options['language'] = language
                
            result = model.transcribe(video_path, **options)
            
            speaker = "Speaker 1"
            last_end = 0.0
            
            for i, s in enumerate(result['segments']):
                text = s['text'].strip()
                start = s['start']
                end = s['end']
                
                # Heuristic Speaker Diarization based on gaps/silence
                if start - last_end > 1.8:
                    speaker = "Speaker 2" if speaker == "Speaker 1" else "Speaker 1"
                
                cursor.execute("""
                    INSERT INTO segments (video_id, start_time, end_time, text, speaker, display_order)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (video_id, start, end, text, speaker, i + 1))
                last_end = end
                
            cursor.execute("UPDATE videos SET status = 'completed' WHERE id = ?", (video_id,))
            conn.commit()
        except Exception as e:
            print(f"Error transcribing {video_id}: {str(e)}")
            cursor.execute("UPDATE videos SET status = 'error', error_message = ? WHERE id = ?", (str(e), video_id))
            conn.commit()
        finally:
            conn.close()

# STATIC FILE SERVERS
@app.route('/uploads/<filename>')
def serve_upload(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

@app.route('/outputs/<filename>')
def serve_output(filename):
    return send_from_directory(OUTPUT_FOLDER, filename)

@app.route('/download/<filename>')
def download_file(filename):
    return send_from_directory(OUTPUT_FOLDER, filename, as_attachment=True)

# VIDEOS ENDPOINTS
@app.route('/api/upload', methods=['POST'])
def upload_video():
    if 'video' not in request.files:
        return jsonify({"error": "No video file provided"}), 400
        
    file = request.files['video']
    if file.filename == '':
        return jsonify({"error": "Empty filename"}), 400
        
    language = request.form.get('language', 'auto')
    
    # Generate unique ID
    video_id = str(uuid.uuid4())
    ext = os.path.splitext(file.filename)[1]
    safe_filename = f"{video_id}{ext}"
    video_path = os.path.join(UPLOAD_FOLDER, safe_filename)
    
    file.save(video_path)
    
    # Insert pending status in DB
    conn = db.get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO videos (id, filename, status)
        VALUES (?, ?, ?)
    """, (video_id, file.filename, 'pending'))
    conn.commit()
    conn.close()
    
    # Spawn background thread for Whisper transcription
    thread = threading.Thread(target=run_transcription, args=(video_id, video_path, language))
    thread.start()
    
    return jsonify({
        "videoId": video_id,
        "filename": file.filename,
        "videoUrl": f"http://localhost:5000/uploads/{safe_filename}",
        "status": "pending"
    })

@app.route('/api/videos/<video_id>', methods=['GET'])
def get_video_status(video_id):
    conn = db.get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, filename, status, error_message, created_at FROM videos WHERE id = ?", (video_id,))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return jsonify({"error": "Video not found"}), 404
        
    # Get ext of video to return URL
    ext = ""
    for file in os.listdir(UPLOAD_FOLDER):
        if file.startswith(video_id):
            ext = os.path.splitext(file)[1]
            break
            
    video_url = f"http://localhost:5000/uploads/{video_id}{ext}" if ext else ""
    
    return jsonify({
        "id": row["id"],
        "filename": row["filename"],
        "status": row["status"],
        "error_message": row["error_message"],
        "created_at": row["created_at"],
        "videoUrl": video_url
    })

@app.route('/api/videos/<video_id>/segments', methods=['GET'])
def get_video_segments(video_id):
    conn = db.get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM segments WHERE video_id = ? ORDER BY display_order ASC", (video_id,))
    rows = cursor.fetchall()
    conn.close()
    
    segments = []
    for r in rows:
        segments.append({
            "id": r["id"],
            "video_id": r["video_id"],
            "start_time": r["start_time"],
            "end_time": r["end_time"],
            "text": r["text"],
            "speaker": r["speaker"],
            "display_order": r["display_order"]
        })
    return jsonify({"segments": segments})

@app.route('/api/videos/<video_id>/segments', methods=['PUT'])
def update_video_segments(video_id):
    data = request.json
    if not data or 'segments' not in data:
        return jsonify({"error": "Missing segments in request body"}), 400
        
    conn = db.get_db()
    cursor = conn.cursor()
    try:
        # Check if video exists
        cursor.execute("SELECT id FROM videos WHERE id = ?", (video_id,))
        if not cursor.fetchone():
            return jsonify({"error": "Video not found"}), 404
            
        # Delete old segments
        cursor.execute("DELETE FROM segments WHERE video_id = ?", (video_id,))
        
        # Insert new segments
        for i, s in enumerate(data['segments']):
            cursor.execute("""
                INSERT INTO segments (video_id, start_time, end_time, text, speaker, display_order)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (video_id, float(s['start_time']), float(s['end_time']), s['text'].strip(), s['speaker'].strip(), i + 1))
            
        conn.commit()
        return jsonify({"success": True, "message": f"Successfully updated {len(data['segments'])} segments."})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

# PRESETS ENDPOINTS
@app.route('/api/presets', methods=['GET'])
def get_presets():
    conn = db.get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM presets ORDER BY id ASC")
    rows = cursor.fetchall()
    conn.close()
    
    presets = []
    for r in rows:
        presets.append({
            "id": r["id"],
            "name": r["name"],
            "font_color": r["font_color"],
            "border_color": r["border_color"],
            "font_size": r["font_size"],
            "border_width": r["border_width"],
            "font_family": r["font_family"],
            "bg_color": r["bg_color"],
            "bg_opacity": r["bg_opacity"],
            "bold": bool(r["bold"]),
            "italic": bool(r["italic"])
        })
    return jsonify(presets)

@app.route('/api/presets', methods=['POST'])
def save_preset():
    data = request.json
    if not data or 'name' not in data:
        return jsonify({"error": "Missing preset name"}), 400
        
    conn = db.get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT OR REPLACE INTO presets 
            (name, font_color, border_color, font_size, border_width, font_family, bg_color, bg_opacity, bold, italic)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data['name'].strip(),
            data['font_color'],
            data['border_color'],
            int(data['font_size']),
            float(data['border_width']),
            data['font_family'],
            data.get('bg_color', '#000000'),
            float(data.get('bg_opacity', 0.0)),
            1 if data.get('bold') else 0,
            1 if data.get('italic') else 0
        ))
        conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@app.route('/api/presets/<int:preset_id>', methods=['DELETE'])
def delete_preset(preset_id):
    conn = db.get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM presets WHERE id = ?", (preset_id,))
        conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

# EXPORT / BURN ENDPOINTS
@app.route('/api/videos/<video_id>/export', methods=['POST'])
def export_captions(video_id):
    data = request.json or {}
    export_format = data.get('format', 'srt').lower()
    show_speakers = bool(data.get('showSpeakerLabels', False))
    
    conn = db.get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM segments WHERE video_id = ? ORDER BY display_order ASC", (video_id,))
    rows = cursor.fetchall()
    conn.close()
    
    if not rows:
        return jsonify({"error": "No caption segments found. Did you transcribe first?"}), 404
        
    out_filename = f"{video_id}_export.{export_format}"
    out_path = os.path.join(OUTPUT_FOLDER, out_filename)
    
    try:
        if export_format == 'srt':
            content = ""
            for i, r in enumerate(rows):
                text = r['text']
                if show_speakers:
                    text = f"[{r['speaker']}]: {text}"
                content += f"{i+1}\n{format_timestamp_srt(r['start_time'])} --> {format_timestamp_srt(r['end_time'])}\n{text}\n\n"
            with open(out_path, 'w', encoding='utf-8') as f:
                f.write(content)
                
        elif export_format == 'vtt':
            content = "WEBVTT\n\n"
            for i, r in enumerate(rows):
                text = r['text']
                if show_speakers:
                    text = f"[{r['speaker']}]: {text}"
                content += f"{i+1}\n{format_timestamp_vtt(r['start_time'])} --> {format_timestamp_vtt(r['end_time'])}\n{text}\n\n"
            with open(out_path, 'w', encoding='utf-8') as f:
                f.write(content)
                
        elif export_format == 'json':
            import json
            segments_list = []
            for r in rows:
                segments_list.append({
                    "start": r['start_time'],
                    "end": r['end_time'],
                    "text": r['text'],
                    "speaker": r['speaker']
                })
            with open(out_path, 'w', encoding='utf-8') as f:
                json.dump(segments_list, f, indent=2)
                
        else:
            return jsonify({"error": f"Unsupported format: {export_format}"}), 400
            
        return jsonify({"downloadUrl": f"http://localhost:5000/download/{out_filename}"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def run_burning(video_id, video_path, srt_path, style_str, show_speakers, out_path):
    conn = db.get_db()
    cursor = conn.cursor()
    try:
        # Generate styled SRT content from database segments
        cursor.execute("SELECT * FROM segments WHERE video_id = ? ORDER BY display_order ASC", (video_id,))
        rows = cursor.fetchall()
        
        srt_content = ""
        for i, r in enumerate(rows):
            text = r['text']
            if show_speakers:
                text = f"[{r['speaker']}]: {text}"
            srt_content += f"{i+1}\n{format_timestamp_srt(r['start_time'])} --> {format_timestamp_srt(r['end_time'])}\n{text}\n\n"
            
        with open(srt_path, 'w', encoding='utf-8') as f:
            f.write(srt_content)
            
        safe_srt = srt_path.replace('\\', '/').replace(':', '\\:')
        
        # Use superfast preset for optimized background rendering speed
        cmd = [
            'ffmpeg', '-y', '-i', video_path,
            '-vf', f"subtitles='{safe_srt}':force_style='{style_str}'",
            '-c:v', 'libx264', '-preset', 'superfast',
            '-c:a', 'copy', out_path
        ]
        
        print(f"Executing FFmpeg for {video_id}: {' '.join(cmd)}")
        res = subprocess.run(cmd, capture_output=True, text=True)
        
        if res.returncode != 0:
            raise Exception(res.stderr)
            
        cursor.execute("UPDATE videos SET status = 'completed', error_message = NULL WHERE id = ?", (video_id,))
        conn.commit()
    except Exception as e:
        print(f"Burn error for {video_id}: {str(e)}")
        cursor.execute("UPDATE videos SET status = 'error', error_message = ? WHERE id = ?", (str(e), video_id))
        conn.commit()
    finally:
        conn.close()

@app.route('/api/videos/<video_id>/burn', methods=['POST'])
def burn_captions(video_id):
    data = request.json or {}
    show_speakers = bool(data.get('showSpeakerLabels', False))
    
    font_color = web_to_ass_color(data.get('fontColor', '#FFFF00'), 1.0)
    border_color = web_to_ass_color(data.get('borderColor', '#000000'), 1.0)
    font_size = int(data.get('fontSize', 24))
    border_width = float(data.get('borderWidth', 1.5))
    font_family = data.get('fontFamily', 'Inter')
    bg_color = web_to_ass_color(data.get('bgColor', '#000000'), float(data.get('bgOpacity', 0.0)))
    bold = 1 if data.get('bold') else 0
    italic = 1 if data.get('italic') else 0
    
    bg_opacity = float(data.get('bgOpacity', 0.0))
    border_style = 3 if bg_opacity > 0.0 else 1
    
    ext = ""
    for file in os.listdir(UPLOAD_FOLDER):
        if file.startswith(video_id) and not file.endswith('.srt') and not file.startswith('captioned_'):
            ext = os.path.splitext(file)[1]
            break
            
    if not ext:
        return jsonify({"error": "Original video not found"}), 404
        
    video_path = os.path.join(UPLOAD_FOLDER, f"{video_id}{ext}")
    srt_path = os.path.join(UPLOAD_FOLDER, f"{video_id}_temp.srt")
    out_filename = f"captioned_{video_id}.mp4"
    out_path = os.path.join(OUTPUT_FOLDER, out_filename)
    
    style_str = (
        f"Fontname={font_family},FontSize={font_size},PrimaryColour={font_color},"
        f"OutlineColour={border_color},BackColour={bg_color},BorderStyle={border_style},"
        f"Outline={border_width},Shadow=1,Alignment=2,Bold={bold},Italic={italic}"
    )
    
    # Mark status as rendering
    conn = db.get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE videos SET status = 'rendering', error_message = NULL WHERE id = ?", (video_id,))
    conn.commit()
    conn.close()
    
    if os.path.exists(out_path):
        try:
            os.remove(out_path)
        except:
            pass
            
    # Spawn burning thread
    thread = threading.Thread(
        target=run_burning, 
        args=(video_id, video_path, srt_path, style_str, show_speakers, out_path)
    )
    thread.start()
    
    return jsonify({
        "status": "rendering",
        "message": "Video rendering started in background."
    })

if __name__ == '__main__':
    app.run(debug=True, port=5000)
