# AI Smart Captioner - Tier 1 Implementation Plan

We will upgrade the AI Smart Captioner from a basic synchronous transcribe-and-burn tool to a state-of-the-art interactive subtitle editor.

This plan details:
1. Adding a local SQLite database to store videos, caption segments, and style presets.
2. Refactoring the Flask backend to support async transcription, segment editing, and preset management.
3. Building a premium React-based frontend featuring:
   - Interactive caption editor (text, timing, speaker tags).
   - Real-time CSS-styled overlay preview on the video.
   - Preset management & custom styling options.
   - Dynamic video rendering using FFmpeg.

---

## User Review Required

> [!IMPORTANT]
> **Storage & Database**: We will use SQLite for simplicity and zero setup. The database file `captions.db` will be created in the `backend` folder.
> **FFmpeg Rendering**: Renders will be executed via `ffmpeg` CLI. Ensure you have `ffmpeg` on your PATH (verified as present and working!).
> **Speaker Diarization**: Standard Whisper does not segment speakers natively. We will implement manual speaker labeling in the UI and a simple, heuristic-based automatic speaker partitioner (based on pauses/turn-taking) in the backend to start with, which the user can edit.

---

## Open Questions

None at this stage, but please provide feedback if you'd like to adjust specific styling details (e.g., custom fonts, layout choices) or have constraints regarding database/API routing.

---

## Proposed Changes

### Backend Component

We will introduce a SQLite-based database layer and expand `app.py` to support granular API endpoints.

#### [NEW] [db.py](file:///c:/Users/uagar/ai-captioner/backend/db.py)
A database helper module utilizing Python's built-in `sqlite3` to manage schemas:
- `videos` (id, filename, status, created_at)
- `segments` (id, video_id, start_time, end_time, text, speaker, display_order)
- `presets` (id, name, font_color, border_color, font_size, border_width, font_family, bg_color, bg_opacity, bold, italic)

#### [MODIFY] [app.py](file:///c:/Users/uagar/ai-captioner/backend/app.py)
Refactor `app.py` to:
- Serve static video files.
- Implement API endpoints:
  - `POST /api/upload`: Upload video and start transcription in a background thread.
  - `GET /api/videos/<id>`: Get video metadata and status.
  - `GET /api/videos/<id>/segments`: Retrieve transcription segments.
  - `PUT /api/videos/<id>/segments`: Bulk save updated segments (text, speaker, timestamps).
  - `GET /api/presets` / `POST /api/presets` / `DELETE /api/presets/<id>`: Preset management.
  - `POST /api/videos/<id>/burn`: Render the final video with custom styles.
  - `POST /api/videos/<id>/export`: Generate SRT/VTT/JSON subtitle files.

---

### Frontend Component

We will revamp the React App with a modern, dark-themed responsive layout split into three columns/zones: Style Editor, Video Player + Interactive Subtitles Overlay, and Timeline/Segment List.

#### [MODIFY] [App.js](file:///c:/Users/uagar/ai-captioner/frontend/src/App.js)
Refactor `App.js` to build the new interactive workspace:
- **StylePresetSelector & FontStyleEditor**: In the sidebar, allowing selection of predefined styles and saving new ones.
- **Video Player**: Uses native `<video>` with a timeupdate listener to sync the active subtitle segment in real-time.
- **Subtitle Overlay**: HTML/CSS based text container overlaid on the video preview, styled dynamically.
- **TimingAdjuster & SpeakerLabeler**: Lists all segments with inputs to modify text, start time, end time, and speaker label. Includes a "Play Segment" button to jump the playhead.
- **Exporter**: Allows exporting SRT, VTT, or JSON files.

#### [MODIFY] [App.css](file:///c:/Users/uagar/ai-captioner/frontend/src/App.css)
Update CSS to match a premium dark interface (radial gradients, glowing borders, smooth slide-ins, glassmorphism card panels).

---

## Verification Plan

### Automated Tests
- Test API endpoints using Python requests script.
- Verify SRT/VTT outputs are formatted correctly.

### Manual Verification
1. Run backend: `flask run` (or `python app.py`).
2. Run frontend: `npm start`.
3. Upload a sample video file, observe background transcribing progress.
4. Edit the transcribed text, change speaker labels, adjust start/end timings.
5. Play the video, verify subtitles update in real-time and match edited text/timings.
6. Customize the font style (size, color, stroke, background), verify overlay updates.
7. Click "Export" to verify SRT/VTT files are downloaded successfully.
8. Click "Burn & Render" to trigger FFmpeg rendering, and download the output.
