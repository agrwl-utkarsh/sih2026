# Tasks — LeetCode Pattern Notifier

- `[x]` Git setup and workspace cleanup (remove `leetpattern_clone`, `git init`, link remote)
- `[/]` Compile local patterns database (`compile_patterns.py` -> `patterns.json`)
- `[ ]` Create extension base files: `manifest.json`
- `[ ]` Implement background service worker: `background.js` (offline caching, Gemini API, backoff)
- `[ ]` Implement content scripts: `content.js` (DOM scraper, heuristics) and `content.css` (floating HUD styling)
- `[ ]` Build Options page: `options/options.html` and `options/options.js` (API key test, saving configuration)
- `[ ]` Build Popup UI: `popup/popup.html` and `popup/popup.js` (progress statistics, gap highlights)
- `[ ]` Validation and Testing (write validation script, load unpacked, verify flows)
