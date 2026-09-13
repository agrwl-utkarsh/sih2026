# Implementation Plan - Restore Asynchronous Architecture

We will restore the original, multi-stage, asynchronous architecture to resolve the connection timeout issues (which cause the "infinite wait" problem) and bring back the editing workspace, style presets, and live subtitle preview.

## User Review Required

> [!IMPORTANT]
> The current synchronous implementation causes browser requests to time out (since CPU transcription takes ~2 minutes) and removes the editing interface. Restoring the asynchronous architecture will run transcription and subtitle burning in background threads, polling for status updates, and bringing back the style presets and segment editing features.

## Proposed Changes

---

### Backend Components

We will replace the simplified `backend/app.py` with the original full-featured database-backed implementation, including a fix to return the output captioned video URL.

#### [MODIFY] [app.py](file:///c:/Users/uagar/ai-captioner/backend/app.py)

- Restore background threading (`run_transcription`, `run_burning`).
- Restore preset management routes (`GET /api/presets`, `POST /api/presets`, `DELETE /api/presets/<id>`).
- Restore video-specific routes (`POST /api/upload`, `GET /api/videos/<video_id>`, `GET /api/videos/<video_id>/segments`, `PUT /api/videos/<video_id>/segments`, `POST /api/videos/<video_id>/burn`, `POST /api/videos/<video_id>/export`).
- Modify `get_video_status` (`GET /api/videos/<video_id>`) to return `renderedUrl` if `outputs/captioned_{video_id}.mp4` exists in the filesystem.

---

### Frontend Components

We will replace the simplified frontend workspace with the full style engine, timeline sync, and status-polling dashboard.

#### [MODIFY] [App.js](file:///c:/Users/uagar/ai-captioner/frontend/src/App.js)

- Restore imports from `lucide-react`.
- Restore polling logic for transcription (`startPollingStatus`) and rendering (`startPollingRenderStatus`).
- Restore custom style configuration options, typography, outlines, and backgrounds.
- Restore style presets loading, saving, and deletion.
- Restore the live dynamic subtitle overlay synchronized with the HTML5 video player.

---

## Verification Plan

### Automated Tests
- Run backend diagnostics using `pytest` if test suites exist, or check syntax/imports with:
  ```powershell
  .\venv\Scripts\python.exe -m py_compile backend/app.py
  ```

### Manual Verification
1. Run the Flask backend (`python app.py`) and React frontend (`npm start`).
2. Upload a video and verify that the page immediately moves to "AI Transcribing via Whisper..." status, showing background progress without timing out.
3. Once transcribed, verify the workspace loads the video and segments.
4. Customize text/styles and click "Burn Styles & Render Video".
5. Verify that it polls, completes the burn rapidly via FFmpeg `-preset superfast`, and displays the downloadable captioned video player.
