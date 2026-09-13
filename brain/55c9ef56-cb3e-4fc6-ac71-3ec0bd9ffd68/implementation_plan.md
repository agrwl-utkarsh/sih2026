# Deployment Plan: Netlify Frontend & Production Backend

This plan outlines the steps required to deploy the React frontend on Netlify and configure the Flask backend for production hosting.

## User Review Required

> [!IMPORTANT]
> **Netlify Limitation**: Netlify only hosts static frontend sites. It cannot run the Flask backend because the backend requires a persistent Python environment, Whisper AI model execution, and FFmpeg video processing.
>
> To make the full-stack application work in production, we must:
> 1. Deploy the frontend on Netlify.
> 2. Deploy the backend on a platform that supports Python and system packages like FFmpeg (e.g., Render, Railway, or Fly.io).
> 3. Connect the frontend to the deployed backend's URL.

## Proposed Changes

### Frontend Configuration

We will make the API URL configurable using environment variables so that the frontend can talk to the production API.

#### [MODIFY] [App.js](file:///c:/Users/uagar/ai-captioner/frontend/src/App.js)
- Change the hardcoded API endpoint from `http://localhost:5000` to `process.env.REACT_APP_API_URL || 'http://localhost:5000'`.

#### [NEW] [netlify.toml](file:///c:/Users/uagar/ai-captioner/frontend/netlify.toml)
- Add a Netlify configuration file to handle React single-page app (SPA) routing redirects and define the build command.

---

### Backend Configuration

#### [MODIFY] [app.py](file:///c:/Users/uagar/ai-captioner/backend/app.py)
- Replace the hardcoded `http://localhost:5000` base URL in the `/transcribe` return payload with a dynamic URL using `request.host_url`. This ensures the download link dynamically points to the correct deployment domain.

---

## Deployment Steps

### 1. Backend Deployment (e.g., Render)
Since the backend requires **FFmpeg** and **Whisper**, hosting on **Render** (free tier/paid) or **Railway** is recommended.
* We can use a custom `render.yaml` or Dockerfile to ensure FFmpeg is installed alongside python dependencies.
* Once deployed, we will get a backend URL (e.g. `https://my-captioner-backend.onrender.com`).

### 2. Frontend Deployment (Netlify)
1. Build command: `npm run build`
2. Publish directory: `build`
3. Set the environment variable: `REACT_APP_API_URL` to your production backend URL (e.g. `https://my-captioner-backend.onrender.com`).

---

## Verification Plan

### Manual Verification
- Test running the modified frontend and backend locally first with `REACT_APP_API_URL` configured to `http://localhost:5000` to verify functionality.
- Once deployed, perform a test upload of a video to verify caption generation, subtitle burning, and downloading.
