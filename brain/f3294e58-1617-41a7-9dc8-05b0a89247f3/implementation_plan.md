# LeetCode Pattern Notifier Implementation Plan

Create a Manifest V3 Chrome Extension that identifies the DSA pattern corresponding to LeetCode problems, using a local-first lookup (`patterns.json` covering Blind 75, NeetCode 150, and Grind 169) and falling back to Gemini API if the problem is not in the database.

## User Review Required

> [!IMPORTANT]
> - **Technology Stack**: This is a pure Vanilla JS/HTML/CSS Chrome extension with no build step, making it extremely lightweight and trivial to load unpackaged in Chrome.
> - **Design Motif**: We will use a "compass / signal-detection" theme with dark mode palette colors matching the requirements: Background `#15181f`, Surface `#1f2430`, Border `#2b3140`, Text Primary `#eceef3`, Text Muted `#8891a6`, Amber accent `#e8a33d`, Blue accent `#5b8def`, and Mint accent `#4ade9e`.
> - **Gemini Fallback**: The extension will allow setting a Gemini API key and model selection (defaulting to `gemini-2.5-flash` or `gemini-flash-latest`) in the Options page.

## Proposed Changes

We will create a new directory `leetcode-pattern-notifier` inside `C:\Users\uagar/leetcode-pattern-notifier` containing the entire extension.

---

### Chrome Extension Core Structure

#### [NEW] [manifest.json](file:///C:/Users/uagar/leetcode-pattern-notifier/manifest.json)
- Configures a Manifest V3 extension.
- Declares permissions: `"storage"`, `"activeTab"`.
- Declares host permissions: `"*://*.leetcode.com/*"` and `"*://generativelanguage.googleapis.com/*"`.
- Registers service worker `background.js`.
- Registers content scripts (`content.js`, `content.css`) for `*://*.leetcode.com/problems/*`.
- Configures default popup (`popup/popup.html`) and options page (`options/options.html`).

#### [NEW] [background.js](file:///C:/Users/uagar/leetcode-pattern-notifier/background.js)
- Acts as the background service worker.
- Sets up listener for runtime messages:
  - `GET_PATTERN`: Checks `chrome.storage.local` cache first. If cache miss, check local `patterns.json`. If still not found, execute Gemini API fallback. Caches results to local storage.
  - `OPEN_OPTIONS`: Opens the extension options page.
- Implements exponential backoff (2 retries) for Gemini API calls, ignoring retry for 4xx errors.
- Defines `PATTERN_TAXONOMY` to categorize LeetCode patterns.

#### [NEW] [content.js](file:///C:/Users/uagar/leetcode-pattern-notifier/content.js)
- Injected on LeetCode problem pages (`leetcode.com/problems/*`).
- Extracts problem title and slug using robust selector fallbacks:
  - `getTitleText()`: Selector chains for modern LeetCode UI.
  - `getDescriptionText()`: Extracts problem description text blocks.
- Adds self-check: skips analysis if title is empty or under 3 characters, displaying a "couldn't read this page" status.
- Renders a floating, signal-themed compass widget in the bottom-right corner.
- Sends message `GET_PATTERN` to `background.js` and updates the floating widget UI.

#### [NEW] [content.css](file:///C:/Users/uagar/leetcode-pattern-notifier/content.css)
- Stylizes the floating widget with the designated dark theme and compass/signal animations.

---

### Local Pattern Database

#### [NEW] [patterns.json](file:///C:/Users/uagar/leetcode-pattern-notifier/patterns.json)
- Holds pre-loaded problem patterns (~450-500 entries) mapping `slug` -> `{ pattern, category, tell }`.
- Includes combined and deduped lists of:
  - **Blind 75**
  - **NeetCode 150**
  - **Grind 169**
- Categorizations match the defined `PATTERN_TAXONOMY`.

---

### User Interface Component Layers

#### [NEW] [popup/popup.html](file:///C:/Users/uagar/leetcode-pattern-notifier/popup/popup.html)
- Main dropdown UI shown when clicking the extension icon.
- Features tabs:
  - **Current**: Shows the pattern details, category, and "tell" for the currently active tab.
  - **Progress**: Renders unique problem counts per category as CSS-based progress bars, total analyzed count, and flags zero-coverage patterns.
- Modern dark layout styling conforming to the design guidelines.

#### [NEW] [popup/popup.js](file:///C:/Users/uagar/leetcode-pattern-notifier/popup/popup.js)
- Requests current tab context, queries cached result from `chrome.storage.local`.
- Reads `lpn_history` list to build and render the Progress metrics.
- Navigates tabs.

#### [NEW] [options/options.html](file:///C:/Users/uagar/leetcode-pattern-notifier/options/options.html)
- Settings panel with form elements for Gemini API Key and Model selection (defaulting to `gemini-2.5-flash` or `gemini-flash-latest`).

#### [NEW] [options/options.js](file:///C:/Users/uagar/leetcode-pattern-notifier/options/options.js)
- Handles loading and saving settings to `chrome.storage.local`.

#### [NEW] [privacy.html](file:///C:/Users/uagar/leetcode-pattern-notifier/privacy.html)
- User-facing privacy policy detailing local storage constraints and Gemini API proxy terms.

---

### Assets

#### [NEW] [generate_icons.py](file:///C:/Users/uagar/leetcode-pattern-notifier/generate_icons.py)
- A helper python script that uses standard library (e.g. tkinter/canvas or simple data structures) or outputs SVG/PNG files to generate beautiful dark-compass styled PNG icons for size 16px, 48px, and 128px.

---

## Verification Plan

### Automated / Syntax Verification
- Run a Node.js lint or standard syntax check to verify `patterns.json` parses as valid JSON.
- Verify `manifest.json` schema layout.

### Manual Verification
- Load the unpacked extension in Chrome browser (`chrome://extensions/`).
- Visit multiple LeetCode problems (e.g., `two-sum`, `container-with-most-water`, `longest-substring-without-repeating-characters`) and verify that:
  - The floating widget is injected properly and styles look correct.
  - The correct pattern matches (Two Pointers, Array, etc.) from `patterns.json` are returned.
  - Visit a newer/non-indexed problem to verify Gemini API fallback activates and retrieves the pattern.
  - Visit multiple problems to verify that the "Progress" tab displays accurate counts, totals, and tracks practicing progress.
