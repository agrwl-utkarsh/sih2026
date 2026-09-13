# Demo Implementation Plan: Universal Log Pre-processing Framework

This plan outlines the steps to build a functional prototype of the framework to demonstrate its core capabilities. We will build a lightweight, functional backend that processes raw logs into structured formats.

## User Review Required
> [!IMPORTANT]
> Please review the scope of this demo. Are there any specific log examples or formats (e.g., a specific Syslog or IoT format) you want the demo to focus on, or should I use generic network and server log samples?

## Proposed Architecture & Changes

We will create a new project in `C:\Users\uagar\.gemini\antigravity-ide\scratch\log_framework_demo`.

### 1. Project Setup & Dependencies
We will create a `requirements.txt` and install the core stack identified in the technical approach:
*   `fastapi` and `uvicorn` for the API.
*   `pandas` for normalization and data manipulation.
*   `drain3` for pattern extraction and unstructured log parsing.
*   `scikit-learn` (placeholder for unknown log handling logic if needed for the demo).

### 2. Core Processing Pipeline (`pipeline/`)
We will implement the processing stages as modular Python components:
*   **`format_detector.py`**: Heuristics to identify if a log is JSON, CSV, standard Syslog, or Unstructured.
*   **`parser.py`**: Integrates **Drain3** to automatically parse unstructured text logs, extract variables, and assign log templates (Pattern Detection).
*   **`normalizer.py`**: Uses **Pandas** to standardize common fields (e.g., mapping `time`, `date`, or `ts` fields into a unified `timestamp` standard).

### 3. API Layer (`main.py`)
We will expose the framework via a FastAPI application:
*   `POST /api/logs/ingest`: Accepts a batch of raw log strings, runs them through the pipeline, and returns the normalized JSON output.
*   `GET /api/logs/templates`: Returns the templates dynamically learned by Drain3 to demonstrate the "Unknown Format Support".

### 4. Demo Driver (`run_demo.py`)
We will create a script containing mixed log data (structured JSON, unstructured server errors, and generic network logs) that will send data to the API and print the "Before" (Raw) and "After" (Normalized & Parsed) results.

## Verification Plan

### Manual Verification
1.  Start the FastAPI server locally.
2.  Run the `run_demo.py` script.
3.  Verify that unstructured logs (like `Connection refused from 192.168.1.5`) are successfully parsed into templates (e.g., `Connection refused from <IP>`) and that variables are extracted.
4.  Verify that timestamps across different formats are unified.
