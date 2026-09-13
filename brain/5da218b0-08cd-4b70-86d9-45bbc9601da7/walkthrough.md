# Walkthrough: AI Smart Captioner Upgrade

We have upgraded the basic captioner into a professional, real-time interactive subtitle workstation. The project now separates transcription from rendering, supports style presets, and allows timing/text adjustments.

---

## What Was Added/Changed

### 1. Database Persistence Layer
- Created a SQLite module ([db.py](file:///c:/Users/uagar/ai-captioner/backend/db.py)) storing:
  - `videos`: Tracks background transcription status (`pending`, `transcribing`, `completed`, `error`).
  - `segments`: Stores specific word/sentence timings, texts, and speaker tags.
  - `presets`: Stores custom style configurations. Seeds default styles on startup.

### 2. Upgraded Backend REST API
- Overwrote the backend ([app.py](file:///c:/Users/uagar/ai-captioner/backend/app.py)) with the following endpoints:
  - `POST /api/upload`: Handles video uploads asynchronously, running Whisper in a background thread.
  - `GET /api/videos/<id>`: Fetches transcription state.
  - `GET /api/videos/<id>/segments`: Pulls all segments.
  - `PUT /api/videos/<id>/segments`: Bulk updates text, timing, and speaker labels.
  - `GET /POST/DELETE /api/presets`: Manages style presets.
  - `POST /api/videos/<id>/burn`: Runs FFmpeg in a background thread to prevent HTTP request timeouts. Automatically detects and utilizes GPU hardware acceleration (Intel QuickSync/QSV, NVIDIA NVENC, or AMD AMF) to drastically reduce rendering time; falls back to CPU encoding with the `ultrafast` preset if no GPU is available.
  - `POST /api/videos/<id>/export`: Downloads subtitles as `.srt`, `.vtt`, or `.json`.

### 3. High-Fidelity React Workspace
- Refactored frontend styling ([App.css](file:///c:/Users/uagar/ai-captioner/frontend/src/App.css)) and component structure ([App.js](file:///c:/Users/uagar/ai-captioner/frontend/src/App.js)) to feature:
  - **Style Side-Panel**: Font picker, colors, stroke thickness, backdrop box styling, and preset CRUD.
  - **Live Subtitle Overlay**: Pure CSS overlay rendered on top of the HTML5 video player, updating in real-time as the video plays to match the active segment.
  - **Asynchronous Status Polling**: Triggers background rendering and queries state until complete or failed, keeping the browser UI active and displaying live status feedback.
  - **Render & Export Panel**: Options to export formats or render the styled subtitles into a final downloadable MP4.

---

## How to Run & Verify

### Step 1: Start the Backend Server
Run the Flask server from the `backend/` directory:
```bash
cd backend
.\venv\Scripts\python.exe app.py
```
*The server starts on `http://localhost:5000` and creates `captions.db`.*

### Step 2: Start the Frontend Application
Run the React development server from the `frontend/` directory:
```bash
cd frontend
npm start
```
*The app will load in the browser at `http://localhost:3000` (proxied to port 5000).*

### Verification Steps
1. **Upload & Transcribe**: Upload an MP4 video, select English/Hindi, and observe the live transcription spinner polling the status API.
2. **Interactive Preview**: Press play. Observe that subtitle text overlays on the video, matching the active segment's styling.
3. **Style Customization**: Select presets (e.g., *Neon Green*, *Minimal White*) or adjust sliders (Font Size, Backdrop Opacity). The preview updates immediately.
4. **Segment Editing**: Edit text, timing numbers, or speaker tags. Click "Save Edits".
5. **Video Render**: Click "Burn Styles & Render Video". When finished, play and download the final rendered video with hard-coded styled subtitles!
