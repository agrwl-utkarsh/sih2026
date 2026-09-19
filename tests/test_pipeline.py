import pytest
from fastapi.testclient import TestClient
import datetime
import json
from unittest.mock import patch, MagicMock

from main import app, parser, normalizer
from pipeline.timeutil import parse_timestamp

client = TestClient(app)

@pytest.fixture(autouse=True)
def clear_cache():
    parser.cache.clear()

def test_1_plain_line_after_json_no_500():
    res = client.post("/api/logs/ingest", json={"logs": ['{"a": 1}', 'hello']})
    assert res.status_code == 200
    data = res.json()["processed_logs"]
    assert len(data) == 2
    assert data[0]["mode"] == "Discovery"
    assert data[1]["mode"] == "Discovery"
    assert data[0]["format"] == "JSON Object"
    assert data[1]["format"] != "JSON Object"

def test_2_severity_parsing():
    res = client.post("/api/logs/ingest", json={"logs": [
        '{"severity": 3, "msg": "test"}',
        '{"severity": [1], "msg": "test"}',
        '{"level": "verbose", "msg": "test"}'
    ]})
    assert res.status_code == 200
    data = res.json()["processed_logs"]
    
    assert data[0]["normalized"]["severity"] == "error"
    assert data[1]["normalized"]["severity"] == "unknown"
    assert data[2]["normalized"]["severity"] == "unknown"
    assert data[2]["normalized"]["extra"]["severity_raw"] == "verbose"

def test_3_one_record_raises():
    original_normalize = normalizer.normalize
    def mock_normalize(parsed, raw_log):
        if raw_log == "bad":
            raise ValueError("boom")
        return original_normalize(parsed, raw_log)
        
    with patch.object(normalizer, 'normalize', side_effect=mock_normalize):
        res = client.post("/api/logs/ingest", json={"logs": ["good", "bad", "good2"]})
        assert res.status_code == 200
        data = res.json()["processed_logs"]
        assert data[0]["mode"] == "Discovery"
        assert data[1]["mode"] == "Error"
        assert data[1]["error"] == "ValueError: boom"
        assert data[2]["mode"] == "Cached"

def test_4_json_extraction_mapping():
    log = '{"level":"warn","ts":1700000000,"msg":"hi","host":"h1","event":"login","nested":{"a":1}}'
    res = client.post("/api/logs/ingest", json={"logs": [log]})
    data = res.json()["processed_logs"][0]["normalized"]
    
    assert data["severity"] == "warning"
    assert data["message"] == "hi"
    assert data["source"] == "h1"
    assert data["event_type"] == "login"
    assert data["timestamp"] == "2023-11-14T22:13:20Z"
    assert data["extra"] == {"nested": {"a": 1}}

def test_5_json_escaped_quotes():
    log = '{"msg": "he said \\"hello\\""}'
    res = client.post("/api/logs/ingest", json={"logs": [log]})
    data = res.json()["processed_logs"][0]
    
    assert data["format"] == "JSON Object"
    assert data["normalized"]["message"] == 'he said "hello"'

def test_6_csv():
    log = '2026-09-13T10:15:30Z,ERROR,Connection reset by peer,app-server-02,pid=992'
    res = client.post("/api/logs/ingest", json={"logs": [log]})
    data = res.json()["processed_logs"][0]["normalized"]
    
    assert data["timestamp"] == "2026-09-13T10:15:30Z"
    assert data["severity"] == "error"
    assert data["message"] == "Connection reset by peer"
    assert data["source"] == "app-server-02"
    assert data["extra"]["pid"] == "992"

def test_7_pipe():
    log = '2026-09-13T10:20:00Z | CRITICAL | PaymentGateway | Transaction txn-8829 failed due to timeout after 3000ms'
    res = client.post("/api/logs/ingest", json={"logs": [log]})
    data = res.json()["processed_logs"][0]["normalized"]
    
    assert data["severity"] == "critical"
    assert data["source"] == "PaymentGateway"
    assert data["message"].startswith("Transaction txn-8829")

def test_8_prose_many_commas():
    log = 'Well, this, is, odd, prose here'
    res = client.post("/api/logs/ingest", json={"logs": [log]})
    data = res.json()["processed_logs"][0]
    
    assert "Comma-Delimited" not in data["format"]
    assert "Compositional Zone Extraction" in data["format"]

def test_9_syslog():
    log1 = "Oct 11 22:14:15 mymachine su: 'su root' failed for lonvick"
    res1 = client.post("/api/logs/ingest", json={"logs": [log1]})
    data1 = res1.json()["processed_logs"][0]["normalized"]
    assert data1["source"] == "mymachine"
    assert data1["extra"]["program"] == "su"
    
    log2 = "<134>Oct 11 22:14:15 host app[42]: hello"
    res2 = client.post("/api/logs/ingest", json={"logs": [log2]})
    data2 = res2.json()["processed_logs"][0]["normalized"]
    assert data2["severity"] == "info"
    assert data2["source"] == "host"
    assert data2["extra"]["pid"] == "42"
    assert data2["timestamp"] is not None

def test_10_brackets():
    res = client.post("/api/logs/ingest", json={"logs": [
        "[ERROR] disk full",
        "2026-09-13 [main] ERROR c.f.Bar - boom"
    ]})
    data = res.json()["processed_logs"]
    assert data[0]["normalized"]["severity"] == "error"
    assert data[1]["normalized"]["severity"] == "error"

def test_11_kv_scan():
    log = '(status=OK) user="john doe" n=5'
    res = client.post("/api/logs/ingest", json={"logs": [log]})
    data = res.json()["processed_logs"][0]["normalized"]["extra"]
    
    assert data["status"] == "OK"
    assert data["user"] == "john doe"
    assert data["n"] == "5"

def test_12_timezones():
    # Naive is UTC
    assert parse_timestamp("2026-09-13T10:00:00") == "2026-09-13T10:00:00Z"
    # +05:30 -> UTC
    assert parse_timestamp("2026-09-13T10:00:00+05:30") == "2026-09-13T04:30:00Z"
    # JSON +00:00 -> Z
    assert parse_timestamp("2026-09-13T10:00:00+00:00") == "2026-09-13T10:00:00Z"

def test_13_parse_timestamp_leap():
    now1 = datetime.datetime(2026, 1, 5, tzinfo=datetime.timezone.utc)
    assert parse_timestamp("Dec 30 10:00:00", now=now1) == "2025-12-30T10:00:00Z"
    assert parse_timestamp("Jan 4 10:00:00", now=now1) == "2026-01-04T10:00:00Z"

def test_14_timestamp_none_for_random():
    assert parse_timestamp("12 users connected") is None
    assert parse_timestamp("10:15:32 ERROR x") is None

def test_15_pretty_json_buffering():
    logs = [
        "{",
        '  "level": "error",',
        '  "message": "boom"',
        "}",
        "Traceback (most recent call last):",
        "  File \"test.py\", line 1",
        "ValueError: boom",
        "Caused by: test",
        '{"a": "unterminated',
        "b",
        "independent line 1",
        "independent line 2"
    ]
    res = client.post("/api/logs/ingest", json={"logs": logs})
    data = res.json()["processed_logs"]
    
    # 1. Pretty JSON
    assert data[0]["format"] == "JSON Object"
    # 2. Traceback
    assert "ValueError: boom" in data[1]["normalized"]["raw"]
    assert "Caused by: test" in data[1]["normalized"]["raw"]
    # 3. Unclosed JSON
    # 4. b
    # 5. independent 1
    # 6. independent 2
    # Total should be 6
    assert len(data) == 6

def test_16_cache_limits():
    res = client.post("/api/logs/ingest", json={"logs": ["a", "b"]})
    data = res.json()["processed_logs"]
    assert data[0]["mode"] == "Discovery"
    assert data[1]["mode"] == "Cached"
    
    # Check cache size (mock out to 501 items to see it pop)
    # The cache eviction logic is tested.
    for i in range(510):
        parser.store_rule({"is_json": False, "tok_count": i, "bracket_count": 0, "comma_count": 0, "eq_count": 0, "pipe_count": 0, "delim": None}, {"method": "compositional"})
    assert len(parser.cache) <= 500
    
    cache_res = client.get("/api/logs/cache")
    assert len(cache_res.json()["cache"]) <= 500

def test_17_limits():
    res = client.post("/api/logs/ingest", json={"logs": ["a"] * 1001})
    assert res.status_code == 422
    
    res = client.post("/api/logs/ingest", json={"logs": ["a" * 10001]})
    assert res.status_code == 422
    
    res = client.post("/api/logs/ingest", json={"logs": []})
    assert res.json()["processed_logs"] == []

@patch("pipeline.format_detector.requests.post")
@patch.dict("os.environ", {"GEMINI_API_KEY": "fake_key"})
def test_18_llm_testing(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "candidates": [{
            "content": {
                "parts": [{"text": '```json\n{"method": "delimiter", "delimiter": "|"}\n```'}]
            }
        }]
    }
    mock_post.return_value = mock_resp
    
    # Mock LLM Success
    res = client.post("/api/logs/ingest", json={"logs": ["a | b | c"]})
    data = res.json()["processed_logs"][0]
    assert data["inferred_by"] == "llm"
    assert data["format"] == "Pipe-Delimited"
    
    # Mock LLM Invalid method -> fallback
    mock_resp.json.return_value = {
        "candidates": [{
            "content": {
                "parts": [{"text": '{"method": "magic"}'}]
            }
        }]
    }
    res = client.post("/api/logs/ingest", json={"logs": ["d | e | f | g"]})
    data = res.json()["processed_logs"][0]
    assert data["inferred_by"] == "heuristic"
    
    # Mock Network Error
    mock_post.side_effect = Exception("network")
    res = client.post("/api/logs/ingest", json={"logs": ["h | i | j | k | l"]})
    data = res.json()["processed_logs"][0]
    assert data["inferred_by"] == "heuristic"

def test_19_ncsa_combined_log():
    log = '192.168.1.100 - john [19/Sep/2026:13:24:00 +0000] "GET /index.html HTTP/1.1" 200 4321 "https://google.com" "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"'
    res = client.post("/api/logs/ingest", json={"logs": [log]})
    assert res.status_code == 200
    data = res.json()["processed_logs"][0]
    
    assert data["format"] == "NCSA Combined / Web Access Log"
    norm = data["normalized"]
    assert norm["timestamp"] == "2026-09-19T13:24:00Z"
    assert norm["source"] == "192.168.1.100"
    assert norm["event_type"] == "http_request"
    assert norm["severity"] == "info"
    assert norm["message"] == "GET /index.html HTTP/1.1"
    assert norm["extra"]["http_status"] == 200
    assert norm["extra"]["user"] == "john"
    assert norm["extra"]["bytes_sent"] == 4321
    assert norm["extra"]["referer"] == "https://google.com"
    assert norm["extra"]["http_method"] == "GET"
    assert norm["extra"]["http_path"] == "/index.html"

def test_20_date_fallback_without_timestamp():
    log = 'Jan 15 myhost myapp: connection established'
    res = client.post("/api/logs/ingest", json={"logs": [log]})
    assert res.status_code == 200
    data = res.json()["processed_logs"][0]["normalized"]
    assert data["timestamp"] is not None
    assert "2026-01-15" in data["timestamp"] or "2025-01-15" in data["timestamp"]
    assert data["source"] == "myhost"
    assert data["extra"]["program"] == "myapp"

def test_21_spring_boot_and_java_log4j():
    log = "2026-09-19 14:32:10.123 [main] INFO org.springframework.boot.Startup - Started Application in 2.5s"
    res = client.post("/api/logs/ingest", json={"logs": [log]})
    assert res.status_code == 200
    data = res.json()["processed_logs"][0]
    assert "Java Application" in data["format"]
    norm = data["normalized"]
    assert norm["timestamp"] == "2026-09-19T14:32:10.123000Z"
    assert norm["severity"] == "info"
    assert norm["source"] == "org.springframework.boot.Startup"
    assert norm["message"] == "Started Application in 2.5s"
    assert norm["extra"]["thread"] == "main"

def test_22_python_logger():
    log = "INFO:root:Connected to database successfully"
    res = client.post("/api/logs/ingest", json={"logs": [log]})
    assert res.status_code == 200
    data = res.json()["processed_logs"][0]
    assert data["format"] == "Python Standard Logger"
    norm = data["normalized"]
    assert norm["severity"] == "info"
    assert norm["source"] == "root"
    assert norm["message"] == "Connected to database successfully"

def test_23_kubernetes_cri():
    log = "2026-09-19T14:32:10.123456789Z stdout F Starting web server on :8080"
    res = client.post("/api/logs/ingest", json={"logs": [log]})
    assert res.status_code == 200
    data = res.json()["processed_logs"][0]
    assert data["format"] == "Kubernetes / CRI Container Log"
    norm = data["normalized"]
    assert norm["timestamp"] == "2026-09-19T14:32:10.123456Z"
    assert norm["severity"] == "info"
    assert norm["message"] == "Starting web server on :8080"
    assert norm["extra"]["stream"] == "stdout"
    assert norm["extra"]["cri_flag"] == "F"

def test_24_nginx_error_log():
    log = '2026/09/19 14:32:10 [error] 1234#0: *1 open() "/favicon.ico" failed, client: 192.168.1.10'
    res = client.post("/api/logs/ingest", json={"logs": [log]})
    assert res.status_code == 200
    data = res.json()["processed_logs"][0]
    assert data["format"] == "Nginx / Web Server Error Log"
    norm = data["normalized"]
    assert norm["timestamp"] == "2026-09-19T14:32:10Z"
    assert norm["severity"] == "error"
    assert norm["source"] == "nginx"
    assert norm["message"] == 'open() "/favicon.ico" failed'
    assert norm["extra"]["client"] == "192.168.1.10"
    assert norm["extra"]["pid"] == "1234#0"

def test_25_rfc_5424_syslog():
    log = "<165>1 2026-09-19T14:32:10.003Z mymachine.example.com evntslog 1234 ID47 - An application event log entry"
    res = client.post("/api/logs/ingest", json={"logs": [log]})
    assert res.status_code == 200
    data = res.json()["processed_logs"][0]
    assert data["format"] == "RFC 5424 Syslog"
    norm = data["normalized"]
    assert norm["timestamp"] == "2026-09-19T14:32:10.003000Z"
    assert norm["severity"] == "info"
    assert norm["source"] == "mymachine.example.com"
    assert norm["event_type"] == "ID47"
    assert norm["message"] == "An application event log entry"
    assert norm["extra"]["program"] == "evntslog"
    assert norm["extra"]["pid"] == "1234"

def test_26_cef_firewall():
    log = "CEF:0|SecurityCompany|Firewall|1.0|100|Packet dropped|5|src=10.0.0.1 dst=10.0.0.2 spt=1234 dpt=80"
    res = client.post("/api/logs/ingest", json={"logs": [log]})
    assert res.status_code == 200
    data = res.json()["processed_logs"][0]
    assert data["format"] == "CEF (Common Event Format)"
    norm = data["normalized"]
    assert norm["source"] == "SecurityCompany Firewall"
    assert norm["event_type"] == "100"
    assert norm["message"] == "Packet dropped"
    assert norm["extra"]["src"] == "10.0.0.1"
    assert norm["extra"]["dst"] == "10.0.0.2"
    assert norm["extra"]["spt"] == "1234"
    assert norm["extra"]["dpt"] == "80"

def test_27_logfmt_key_value():
    log = 'ts=2026-09-19T14:32:10.123Z level=error caller=main.go:42 msg="crash detected" err="null pointer" thread_id=9'
    res = client.post("/api/logs/ingest", json={"logs": [log]})
    assert res.status_code == 200
    data = res.json()["processed_logs"][0]
    assert data["format"] == "Logfmt / Key-Value Stream"
    norm = data["normalized"]
    assert norm["timestamp"] == "2026-09-19T14:32:10.123000Z"
    assert norm["severity"] == "error"
    assert norm["source"] == "main.go:42"
    assert norm["message"] == "crash detected"
    assert norm["extra"]["err"] == "null pointer"
    assert norm["extra"]["thread_id"] == "9"

def test_28_docker_wrapped_json():
    inner = '2026-09-19 14:32:10.123 [main] INFO org.demo.App - Server ready'
    log = json.dumps({"log": inner + "\n", "stream": "stdout", "time": "2026-09-19T14:32:10.500Z"})
    res = client.post("/api/logs/ingest", json={"logs": [log]})
    assert res.status_code == 200
    data = res.json()["processed_logs"][0]
    assert data["format"] == "JSON Object"
    norm = data["normalized"]
    assert norm["timestamp"] == "2026-09-19T14:32:10.123000Z"
    assert norm["severity"] == "info"
    assert norm["source"] == "org.demo.App"
    assert norm["message"] == "Server ready"
    assert norm["extra"]["stream"] == "stdout"

def test_29_ansi_color_stripping():
    log = "\x1b[32m2026-09-19 14:32:10.123 [main] INFO org.demo.App - Colorized message\x1b[0m"
    res = client.post("/api/logs/ingest", json={"logs": [log]})
    assert res.status_code == 200
    data = res.json()["processed_logs"][0]
    norm = data["normalized"]
    assert norm["severity"] == "info"
    assert norm["message"] == "Colorized message"

def test_30_auth_failure_entity_extraction():
    log = "Failed password for invalid user admin from 192.168.1.105 port 54321 ssh2"
    res = client.post("/api/logs/ingest", json={"logs": [log]})
    assert res.status_code == 200
    data = res.json()["processed_logs"][0]
    norm = data["normalized"]
    assert norm["event_type"] == "auth_failure"
    assert norm["severity"] == "warning"
    assert norm["source"] == "192.168.1.105"
    assert norm["extra"]["ip"] == "192.168.1.105"
    assert norm["extra"]["port"] == "54321"
    assert norm["extra"]["user"] == "admin"



