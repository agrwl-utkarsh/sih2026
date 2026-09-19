import requests
import json
import time
import subprocess
import os
import sys

API_URL = "http://127.0.0.1:8000"

SAMPLE_LOGS = [
    # Syslog RFC 3164
    "Oct 11 22:14:15 mymachine su: 'su root' failed for lonvick on /dev/pts/8",
    # Modern RFC 5424 Syslog
    "<165>1 2026-09-19T14:32:10.003Z mymachine.example.com evntslog 1234 ID47 - An application event log entry",
    # JSON (Structured)
    '{"timestamp": "2026-09-13T10:00:00Z", "level": "error", "message": "Database connection failed", "host": "db-server-01"}',
    # Java / Spring Boot
    "2026-09-19 14:32:10.123 [main] INFO org.springframework.boot.Startup - Started Application in 2.5s",
    # Python Standard Logger
    "INFO:root:Connected to database successfully",
    # Kubernetes / CRI Container Log
    "2026-09-19T14:32:10.123456789Z stdout F Starting web server on :8080",
    # Nginx Web Server Error Log
    '2026/09/19 14:32:10 [error] 1234#0: *1 open() "/favicon.ico" failed, client: 192.168.1.10',
    # CEF (ArcSight / Firewall)
    "CEF:0|SecurityCompany|Firewall|1.0|100|Packet dropped|5|src=10.0.0.1 dst=10.0.0.2 spt=1234 dpt=80",
    # Logfmt / Key-Value
    'ts=2026-09-19T14:32:10.123Z level=error caller=main.go:42 msg="crash detected" err="null pointer" thread_id=9',
    # Unstructured Auth Failure
    "Failed password for invalid user admin from 192.168.1.105 port 54321 ssh2",
    # Web Access (Combined Log)
    '192.168.1.100 - john [19/Sep/2026:13:24:00 +0000] "GET /index.html HTTP/1.1" 200 4321 "https://google.com" "Mozilla/5.0"',
    # CSV
    "2026-09-13T10:15:30Z,ERROR,Connection reset by peer,app-server-02,pid=992",
    # Pipe-delimited
    "2026-09-13T10:20:00Z | CRITICAL | PaymentGateway | Transaction txn-8829 failed due to timeout after 3000ms",
    # KV with a thread
    "ts [main] ERROR c.f.Bar - (status=OK) user=\"john doe\" n=5",
    # Plain text
    "Well, this, is, odd, prose here"
]

def main():
    print("Starting FastAPI server in the background...")
    server_process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000"]
    )
    
    print("Waiting for server to start...")
    for _ in range(60):
        try:
            res = requests.get(f"{API_URL}/api/logs/cache")
            if res.status_code == 200:
                break
        except requests.exceptions.ConnectionError:
            pass
        time.sleep(0.5)

    try:
        print("\n--- Sending Logs to Pipeline ---")
        response = requests.post(f"{API_URL}/api/logs/ingest", json={"logs": SAMPLE_LOGS})
        
        if response.status_code == 200:
            data = response.json()
            for i, result in enumerate(data.get("processed_logs", [])):
                print(f"\nRecord {i+1} ({result.get('mode')} - {result.get('inferred_by')}):")
                norm = result.get("normalized", {})
                print(f"  Timestamp: {norm.get('timestamp')}")
                print(f"  Severity:  {norm.get('severity')}")
                print(f"  Source:    {norm.get('source')}")
                print(f"  Message:   {norm.get('message')}")
                print(f"  Extra:     {json.dumps(norm.get('extra', {}))}")
        else:
            print(f"Error {response.status_code}: {response.text}")

        print("\n--- Fetching Cache Inspector ---")
        cache_response = requests.get(f"{API_URL}/api/logs/cache")
        if cache_response.status_code == 200:
            print("\nExtracted Cache Rules:")
            print(json.dumps(cache_response.json(), indent=2))
            
    finally:
        print("\nShutting down server...")
        server_process.terminate()

if __name__ == "__main__":
    main()
