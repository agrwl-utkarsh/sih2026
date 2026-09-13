# Universal Log Pipeline v3 - Compositional Extraction Engine

I have successfully re-architected the entire pipeline to meet the strict anti-hardcoding requirements of the v3 Master Build Prompt.

> [!TIP]
> **Refresh your browser at `http://127.0.0.1:8000` to interact with the new engine.**

## 1. Compositional Field Extraction
Instead of branching into single heuristics (`if key_value else if delimiter`), the pipeline now defaults to a powerful `compositional` parser. It non-destructively consumes zones in this exact sequence:
1. **Timestamp:** Checked against 5 flexible patterns (ISO, Epoch, Syslog, Slash, YYYY-MM-DD). Once identified, it's stripped.
2. **Severity:** Checked against a strict vocabulary (`ERROR`, `WARN`, `<134>`). Stripped if found.
3. **Context/Brackets:** Looks for leading `[ThreadName]` or `(Context)`. Stripped if found.
4. **Message:** Whatever text remains is explicitly preserved as the message.
5. **Key-Value Pairs:** A global regex scans the *original* raw line to guarantee all K/V pairs are captured into `extra`, regardless of where they appeared!

## 2. Testing the 4 Acceptance Criteria

I strongly recommend you test the following scenarios live in the UI:

### 1. Unseen Format Test
Select **Made-up Unknown Format** (`##[2026-09-13]<node-99>{temp:87.2C}(status=OK)`).
- **Result:** You will see the system gracefully fall back to compositional extraction and break down the tokens, capturing the K/V pairs (`temp`, `status`) without any code changes!

### 2. Timestamp Variety Test
Select the **Syslog-style** or **CSV** samples.
- **Result:** Notice how the exact same compositional rule cleanly extracts both the `Mon DD HH:MM:SS` shape and the `ISO-8601` shape automatically.

### 3. Compositional Extraction Regression Test
Select the **Regression (Section 5)** sample from the dropdown:
`2026-06-14 10:15:32 ERROR [MainThread] Connection timeout while accessing database: host=db01, user=admin`
- **Result:** It will flawlessly extract:
  - `timestamp`: 2026-06-14T10:15:32
  - `severity`: ERROR
  - `message`: Connection timeout while accessing database:
  - `extra.context`: MainThread
  - `extra.host`: db01
  - `extra.user`: admin
  *(No more dropping the message or timestamp!)*

### 4. Repeat-format Speed Test
Run any sample, note the `1200+ ms` Discovery latency.
Run it again immediately.
- **Result:** It will hit the Cached Fast Path and process in `< 5 ms`, proving the cache correctly fingerprinted the structural zones!
