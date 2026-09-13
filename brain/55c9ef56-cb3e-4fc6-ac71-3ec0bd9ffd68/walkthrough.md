# Walkthrough: Deployment to Netlify with Local Backend

We have successfully configured the project to support deployment of the React frontend on Netlify while keeping the Python Flask backend running locally on your computer.

## 🛠️ Changes Made

### 1. Frontend Configuration
* Modified [App.js](file:///c:/Users/uagar/ai-captioner/frontend/src/App.js) to dynamically resolve the API base URL:
  ```javascript
  const apiBaseUrl = process.env.REACT_APP_API_URL || 'http://localhost:5000';
  ```
  This defaults to `http://localhost:5000` (your local computer backend) but allows you to specify a production URL in Netlify if you decide to host the backend online in the future.
* Created [netlify.toml](file:///c:/Users/uagar/ai-captioner/frontend/netlify.toml) to configure Netlify's build target and handle single-page application redirects.

### 2. Backend Configuration
* Modified [app.py](file:///c:/Users/uagar/ai-captioner/backend/app.py) to construct the captioned video's URL dynamically using `request.host_url`:
  ```python
  "videoUrl": f"{request.host_url}download/{output_video_name}"
  ```
  This ensures that whether the backend is run locally or in the cloud, it returns the correct domain/port to the frontend for video playback and download.

---

## 🧪 Verification Results
* Ran `npm run build` inside the `frontend` workspace.
* The React app compiled successfully without any errors or warning issues.

---

## 🚀 How to Deploy on Netlify

Since your backend will be run on your local computer, follow these steps to deploy and use your frontend on Netlify:

### Step 1: Push Frontend to Git (GitHub/GitLab)
Ensure your frontend workspace is pushed to a repository on GitHub, GitLab, or Bitbucket.

### Step 2: Connect to Netlify
1. Log in to your [Netlify Dashboard](https://app.netlify.com/).
2. Click **Add new site** -> **Import an existing project**.
3. Select your Git provider and authorize Netlify.
4. Select the repository containing your React app.

### Step 3: Configure Build Settings
During setup on Netlify, configure these settings:
* **Base Directory**: `frontend` (or leave empty if the repository only contains the frontend code).
* **Build Command**: `npm run build`
* **Publish Directory**: `frontend/build` (or `build` if base directory is set to `frontend`).

### Step 4: Environment Variables (Optional)
* Since the code defaults to `http://localhost:5000` if `REACT_APP_API_URL` is not set, **you do not need to configure any environment variables in Netlify** to run the backend on your local computer.
* When you open the Netlify website in your browser, the JavaScript runs locally on your machine and will make requests to `http://localhost:5000` successfully.

### Step 5: Allow CORS
Your backend [app.py](file:///c:/Users/uagar/ai-captioner/backend/app.py) already has CORS enabled via `CORS(app)`. This allows the Netlify frontend to securely make cross-origin requests to your local computer backend.
