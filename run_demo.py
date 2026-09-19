import requests
import json
import time
import subprocess
import os
import sys

API_URL = "http://127.0.0.1:8000"

SAMPLE_LOGS = [
    # Syslog
    "Oct 11 22:14:15 mymachine su: 'su root' failed for lonvick on /dev/pts/8",
    # JSON
    '{"timestamp": "2026-09-13T10:00:00Z", "level": "error", "message": "Database connection failed", "host": "db-server-01"}',
    # Unstructured / Proprietary
    "Connection refused from 192.168.1.5 on port 22",
    "Connection refused from 10.0.0.9 on port 80",
    "User admin logged in from 192.168.1.100",
    "User guest logged in from 10.0.0.1"
]

def main():
    print("Starting FastAPI server in the background...")
    server_process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000"]
    )
    
    print("Waiting for server to start...")
    for _ in range(30):
        try:
            res = requests.get(f"{API_URL}/")
            if res.status_code == 200:
                break
        except requests.exceptions.ConnectionError:
            time.sleep(0.5)

    try:
        print("\n--- Sending Logs to Pipeline ---")
        response = requests.post(f"{API_URL}/api/logs/ingest", json={"logs": SAMPLE_LOGS})
        
        if response.status_code == 200:
            print("\nProcessed Logs Output:")
            print(json.dumps(response.json(), indent=2))
        else:
            print(f"Error {response.status_code}: {response.text}")

        print("\n--- Fetching Cache Inspector ---")
        template_response = requests.get(f"{API_URL}/api/logs/cache")
        if template_response.status_code == 200:
            print("\nExtracted Cache:")
            print(json.dumps(template_response.json(), indent=2))
            
    finally:
        print("\nShutting down server...")
        server_process.terminate()

if __name__ == "__main__":
    main()
