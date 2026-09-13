# Universal Log Pre-processing Framework - Demo Walkthrough

I have implemented a functional prototype of the Universal Log Pre-processing Framework according to our plan. The demo is built using **FastAPI**, **Pandas**, and **Drain3**.

## Components Implemented

All source code is located in `scratch/log_framework_demo/`:

1.  **Format Detector (`pipeline/format_detector.py`)**: Uses heuristics and regular expressions to identify whether incoming log strings are JSON, standard Syslog, or unstructured text.
2.  **Universal Parser (`pipeline/parser.py`)**: Integrates the **Drain3** library to automatically extract templates from unstructured logs. It dynamically learns the structure of proprietary logs (like "Connection refused from X on port Y").
3.  **Normalizer (`pipeline/normalizer.py`)**: Uses **Pandas** to standardize common fields, mapping various timestamp formats into a unified ISO 8601 standard (`standard_timestamp`).
4.  **API Backend (`main.py`)**: A FastAPI application exposing endpoints to ingest logs and retrieve the learned templates.

## How It Works

When you send a batch of diverse logs to the `/api/logs/ingest` endpoint:
1.  The system identifies the format.
2.  If structured (JSON/Syslog), it parses the known fields.
3.  If unstructured, it passes the log to Drain3, which identifies the static template (e.g., `Connection refused from <IP> on port <NUM>`) and extracts the dynamic parameters.
4.  Finally, all parsed fields go through the Normalizer to unify critical fields like timestamps.

## Running the Demo

You can run the demo script which starts the server and sends a mix of Syslog, JSON, and unstructured proprietary logs:

```powershell
cd C:\Users\uagar\.gemini\antigravity-ide\scratch\log_framework_demo
py run_demo.py
```

Alternatively, you can start the API server manually:
```powershell
py -m uvicorn main:app --reload
```
And then test it using the built-in Swagger UI at `http://127.0.0.1:8000/docs`.

---
> [!TIP]
> The Drain3 template miner maintains its state in memory for this demo. For a production system, this state would be persisted to a database or shared storage (like Redis) so that multiple worker nodes can share the learned log templates.
