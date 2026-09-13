# Implementation Plan — LeetCode Pattern Notifier

We will create a Chrome extension (Manifest V3) that detects DSA patterns for LeetCode problems. The system will first check a local cache, fall back to a local offline database (`patterns.json`), and finally query the Gemini API if the problem is not database-mapped.

## User Review Required

> [!IMPORTANT]
> **API Fallback:** The extension requires a user-provided Gemini API key for fallback analysis. The API key and settings will be saved securely using `chrome.storage.local` and configured via the Options page.

> [!NOTE]
> **Git Setup:** We will clean up the temporary clone directory `leetpattern_clone` and initialize Git in the workspace root `c:\Users\uagar\leetcode-pattern-notifier` with the remote repository `https://github.com/agrwl-utkarsh/leetpattern.git` so that all files are versioned directly in the root.

## Proposed Changes

### Component 1: Repository Setup & Cleanup

We will remove the `leetpattern_clone` folder, initialize git in the workspace root, set the remote origin, and commit the existing icons and roadmap.

#### [MODIFY] [c:\Users\uagar\leetcode-pattern-notifier](file:///c:/Users/uagar/leetcode-pattern-notifier)
- Remove `leetpattern_clone` folder.
- Run `git init`.
- Set remote origin to `https://github.com/agrwl-utkarsh/leetpattern.git`.
- Create `.gitignore` to ignore local settings / temporary scratch files.

---

### Component 2: Local Offline Database Compilation

To grow the database to ~450-500 problems (Blind 75, NeetCode 150, Grind 169), we will write a compiler script `compile_patterns.py` that merges these problem lists, removes duplicates, validates structure, and outputs a validated `patterns.json`.

#### [NEW] [compile_patterns.py](file:///c:/Users/uagar/leetcode-pattern-notifier/compile_patterns.py)
- A Python script to combine:
  - Blind 75 list
  - NeetCode 150 list (fetched dynamically or pre-embedded)
  - Grind 169 list (fetched dynamically or pre-embedded)
- Resolves conflicting pattern names to fit a unified taxonomy:
  - Arrays & Hashing
  - Two Pointers
  - Sliding Window
  - Stack
  - Binary Search
  - Linked List
  - Trees (BST, Binary Tree)
  - Heap / Priority Queue
  - Backtracking
  - Graphs & DFS/BFS
  - Advanced Graphs / Trie / Union Find
  - Dynamic Programming (1D & 2D)
  - Greedy
  - Intervals
  - Math & Geometry
  - Bit Manipulation
- Output format: `"problem-slug": { "pattern": "...", "category": "...", "tell": "..." }`.

#### [NEW] [patterns.json](file:///c:/Users/uagar/leetcode-pattern-notifier/patterns.json)
- The compiled offline database containing ~450-500 problems mapped to patterns.

---

### Component 3: Extension Core Files

We will implement the Chrome Extension Manifest V3 structure and backend files.

#### [NEW] [manifest.json](file:///c:/Users/uagar/leetcode-pattern-notifier/manifest.json)
- Manifest V3 configuration.
- Permissions: `"storage"`, `"activeTab"`.
- Host permissions: `https://leetcode.com/*` and `https://generativelanguage.googleapis.com/*`.
- Service worker: `background.js`.
- Content script: `content.js` with styling `content.css` matching `https://leetcode.com/problems/*`.
- Action popup: `popup/popup.html`.
- Options page: `options/options.html`.

#### [NEW] [background.js](file:///c:/Users/uagar/leetcode-pattern-notifier/background.js)
- Service worker listening for message `GET_PATTERN`.
- Pattern resolution flow:
  1. Check `chrome.storage.local` cache for matching slug.
  2. If cache miss, search local `patterns.json` database.
  3. If not in database, perform Gemini API request.
- Handles Gemini API with:
  - Model: `gemini-2.5-flash` (or user configuration).
  - API endpoint: `https://generativelanguage.googleapis.com/v1beta/models/...:generateContent`.
  - Exponential backoff (2 retries) for transient errors, but bypassing retry on 4xx.
- Local logging of progress history `lpn_history`.

#### [NEW] [content.js](file:///c:/Users/uagar/leetcode-pattern-notifier/content.js)
- Injected on LeetCode problem pages.
- Title & description scraper with robust selector chains and heuristics:
  - Checks `document.title`, description containers, etc.
  - Skips API fallback if description is empty or title is too short (<3 chars).
- Injects a floating widget on the LeetCode UI.
- Communicates with `background.js` to fetch pattern details.
- Implements a modern CSS-injected HUD/widget conforming to the signal/compass design system.

#### [NEW] [content.css](file:///c:/Users/uagar/leetcode-pattern-notifier/content.css)
- Sleek dark theme styling for the in-page widget.
- Incorporates compass motifs, micro-animations, and responsive sizing.

---

### Component 4: Popups and Settings UI

#### [NEW] [popup/popup.html](file:///c:/Users/uagar/leetcode-pattern-notifier/popup/popup.html) & [popup/popup.js](file:///c:/Users/uagar/leetcode-pattern-notifier/popup/popup.js)
- Quick stats tab/view showing:
  - Count of unique problems solved/seen per pattern category.
  - Total problems analyzed.
  - Gaps highlighted (patterns with zero coverage yet).
  - Interactive link to open settings.

#### [NEW] [options/options.html](file:///c:/Users/uagar/leetcode-pattern-notifier/options/options.html) & [options/options.js](file:///c:/Users/uagar/leetcode-pattern-notifier/options/options.js)
- Options interface styled with the custom theme.
- Input fields: Gemini API Key, Gemini Model selection, options reset.
- Test connection button to validate key accuracy using a quick API call.

---

## Verification Plan

### Automated Tests
- Build verification tests in Python (`test_patterns.py`) to validate `patterns.json`:
  - No duplicate slugs.
  - All keys map to expected `pattern`, `category`, and `tell` structures.
  - Every problem slug follows lower-case kebab-case.

### Manual Verification
- Load the extension as an "Unpacked Extension" in Chrome.
- Verify loading state and floating widget on a few sample LeetCode pages:
  - Problem in `patterns.json` (e.g., `two-sum` or `3sum`).
  - Problem NOT in `patterns.json` (forces Gemini fallback).
- Test Options page setting: save API key, test connection.
- Test Progress tab in Popup: solve a problem, verify it logs to history, and view stats update dynamically.
