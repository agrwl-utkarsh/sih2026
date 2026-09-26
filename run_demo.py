import requests, json, time, subprocess, sys
API_URL="http://127.0.0.1:8000"
SAMPLE_LOGS=[
    "Oct 11 22:14:15 mymachine su: 'su root' failed for lonvick on /dev/pts/8",
    "<165>1 2026-09-19T14:32:10.003Z mymachine.example.com evntslog 1234 ID47 - An application event log entry",
    '{"timestamp": "2026-09-13T10:00:00Z", "level": "error", "message": "Database connection failed", "host": "db-server-01"}',
    "2026-09-19 14:32:10.123 [main] INFO org.springframework.boot.Startup - Started Application in 2.5s",
    "INFO:root:Connected to database successfully",
    "2026-09-19T14:32:10.123456789Z stdout F Starting web server on :8080",
    '2026/09/19 14:32:10 [error] 1234#0: *1 open() "/favicon.ico" failed, client: 192.168.1.10',
    "CEF:0|SecurityCompany|Firewall|1.0|100|Packet dropped|5|src=10.0.0.1 dst=10.0.0.2 spt=1234 dpt=80",
    'ts=2026-09-19T14:32:10.123Z level=error caller=main.go:42 msg="crash detected" err="null pointer" thread_id=9',
    "Failed password for invalid user admin from 192.168.1.105 port 54321 ssh2",
    '192.168.1.100 - john [19/Sep/2026:13:24:00 +0000] "GET /index.html HTTP/1.1" 200 4321 "https://google.com" "Mozilla/5.0"',
    "2026-09-13T10:15:30Z,ERROR,Connection reset by peer,app-server-02,pid=992",
    "2026-09-13T10:20:00Z | CRITICAL | PaymentGateway | Transaction txn-8829 failed due to timeout after 3000ms",
]

def wait_health():
    for _ in range(60):
        try:
            r=requests.get(f"{API_URL}/api/health", timeout=1)
            if r.ok:
                h=r.json()
                return f"{h.get('provider')}/{h.get('model')}" if h.get('llm_configured') else "Heuristic Fallback"
        except Exception:
            pass
        time.sleep(0.5)
    return "Unknown"

def main():
    print("Starting server...")
    proc=subprocess.Popen([sys.executable,"-m","uvicorn","main:app","--host","127.0.0.1","--port","8000"])
    try:
        mode=wait_health()
        print(f"Server ready. Mode: {mode}\n--- Sending Logs ---")
        resp=requests.post(f"{API_URL}/api/logs/ingest", json={"logs":SAMPLE_LOGS})
        if resp.ok:
            for i,r in enumerate(resp.json().get("processed_logs",[])):
                n=r.get("normalized",{})
                print(f"\nRecord {i+1} ({r.get('mode')}-{r.get('inferred_by')}): {n.get('timestamp')} {n.get('severity')} {n.get('source')} -> {n.get('message')}")
        else:
            print(f"Error {resp.status_code}: {resp.text}")
        print("\n--- Cache ---")
        cr=requests.get(f"{API_URL}/api/logs/cache")
        if cr.ok: print(json.dumps(cr.json(), indent=2))
    finally:
        print("\nShutting down...")
        proc.terminate()

if __name__=="__main__": main()
