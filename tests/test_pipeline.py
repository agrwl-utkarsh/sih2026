import pytest
from fastapi.testclient import TestClient
import datetime
import json
from unittest.mock import patch, MagicMock

from main import app, parser, normalizer, discovery_engine
from pipeline.timeutil import parse_timestamp

client = TestClient(app)

@pytest.fixture(autouse=True)
def clear_cache():
    parser.cache.clear()
    discovery_engine._skip_gemini = False

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




@patch("pipeline.format_detector.requests.post")
@patch.dict("os.environ", {"GEMINI_API_KEY": "fake_key"})
def test_31_llm_error_surfaced_on_failure(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 403
    mock_resp.text = '{"error": {"message": "API key not valid"}}'
    mock_post.return_value = mock_resp

    unique_log = "ZXQW alpha [b1] (c2) k1=v1 k2=v2 k3=v3 k4=v4 tail"
    res = client.post("/api/logs/ingest", json={"logs": [unique_log]})
    assert res.status_code == 200
    data = res.json()["processed_logs"][0]
    assert data["mode"] == "Discovery"
    assert data["inferred_by"] == "heuristic"
    assert data["llm_error"] is not None
    assert "403" in data["llm_error"]
    assert "API key not valid" in data["llm_error"]

    # Cached path must not keep repeating a stale error
    res = client.post("/api/logs/ingest", json={"logs": [unique_log]})
    data = res.json()["processed_logs"][0]
    assert data["mode"] == "Cached"
    assert data["llm_error"] is None


@patch.dict("os.environ", {}, clear=True)
def test_32_llm_error_when_no_key_configured():
    unique_log = "QWZX beta [d3] (e4) m1=v1 m2=v2 m3=v3 m4=v4 tail"
    res = client.post("/api/logs/ingest", json={"logs": [unique_log]})
    assert res.status_code == 200
    data = res.json()["processed_logs"][0]
    assert data["mode"] == "Discovery"
    assert data["inferred_by"] == "heuristic"
    assert data["llm_error"] == "No LLM API key configured (set GEMINI_API_KEY, GROQ_API_KEY or ANTHROPIC_API_KEY)"


@patch("pipeline.format_detector.requests.post")
@patch.dict("os.environ", {"GEMINI_API_KEY": "fake_gemini_key"})
def test_33_gemini_thinking_parts_handled(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    # Simulate Gemini 3.x response with thought part followed by answer part
    mock_resp.json.return_value = {
        "candidates": [{
            "content": {
                "parts": [
                    {"thought": True, "text": "Thinking Process: The user provided pipe-delimited data..."},
                    {"text": '{"method": "delimiter", "delimiter": "|"}'}
                ]
            }
        }]
    }
    mock_post.return_value = mock_resp

    unique_log = "part1 | part2 | part3 | part4"
    res = client.post("/api/logs/ingest", json={"logs": [unique_log]})
    assert res.status_code == 200
    data = res.json()["processed_logs"][0]
    assert data["inferred_by"] == "llm"
    assert data["format"] == "Pipe-Delimited"

    # Verify the default Gemini 3.x model and thinkingLevel='low' in the payload
    # (thinkingBudget is deprecated for Gemini 3.x)
    call_args = mock_post.call_args
    assert "gemini-3.6-flash" in call_args.args[0]
    sent_payload = call_args.kwargs.get("json", {})
    assert "generationConfig" in sent_payload
    assert sent_payload["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "low"}


@patch("pipeline.format_detector.requests.post")
@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "fake_anthropic_key"}, clear=True)
def test_34_anthropic_model_and_execution(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "content": [{"type": "text", "text": '{"method": "json"}'}]
    }
    mock_post.return_value = mock_resp

    unique_log = '{"service": "test", "status": "ok"}'
    res = client.post("/api/logs/ingest", json={"logs": [unique_log]})
    assert res.status_code == 200
    data = res.json()["processed_logs"][0]
    assert data["inferred_by"] == "llm"
    assert data["format"] == "JSON Object"

    call_args = mock_post.call_args
    assert "api.anthropic.com" in call_args.args[0]
    sent_payload = call_args.kwargs.get("json", {})
    assert "claude-3-5-haiku" in sent_payload.get("model", "")


def test_35_health_and_diagnostics_endpoints():
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert "status" in data
    assert "llm_configured" in data
    assert "model" in data

    res_llm = client.get("/api/health/llm")
    assert res_llm.status_code == 200
    data_llm = res_llm.json()
    assert "status" in data_llm
    assert "configured" in data_llm


def test_36_robust_json_parsing_with_surrounding_text():
    from pipeline.format_detector import DiscoveryEngine
    engine = DiscoveryEngine()

    raw_output = 'Here is the detected format:\n```json\n{"method": "delimiter", "delimiter": ";"}\n```\nHope this helps!'
    rule, err = engine._validate_and_build_rule(raw_output, "val1;val2;val3", {"is_json": False})
    assert err is None
    assert rule["method"] == "delimiter"
    assert rule["delimiter"] == ";"
    assert rule["signature"] == "Semicolon-Delimited"


def test_37_gemini_model_resolution():
    from pipeline.format_detector import DEFAULT_MODEL, _resolve_gemini_model

    # Default model is the current Gemini 3.x flash release
    assert DEFAULT_MODEL == "gemini-3.6-flash"
    assert _resolve_gemini_model("") == "gemini-3.6-flash"
    assert _resolve_gemini_model("gemini-3") == "gemini-3.6-flash"

    # Gemini 3.x models are accepted as-is
    assert _resolve_gemini_model("gemini-3.6-flash") == "gemini-3.6-flash"
    assert _resolve_gemini_model("gemini-3.5-flash") == "gemini-3.5-flash"
    assert _resolve_gemini_model("gemini-3.5-flash-lite") == "gemini-3.5-flash-lite"

    # Deprecated Gemini 2.5 models auto-migrate to the new default
    assert _resolve_gemini_model("gemini-2.5-flash") == "gemini-3.6-flash"
    assert _resolve_gemini_model("gemini-2.5-pro") == "gemini-3.6-flash"
    assert _resolve_gemini_model("gemini-2.5-flash-lite") == "gemini-3.6-flash"

    # Non-Gemini identifiers pass through untouched
    assert _resolve_gemini_model("claude-3-5-haiku-20241022") == "claude-3-5-haiku-20241022"


@patch("pipeline.format_detector.requests.post")
@patch.dict("os.environ", {"GEMINI_API_KEY": "fake_key", "DISCOVERY_MODEL": "gemini-2.5-flash"})
def test_38_deprecated_discovery_model_migrated_in_request(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "candidates": [{
            "content": {
                "parts": [{"text": '{"method": "delimiter", "delimiter": ","}'}]
            }
        }]
    }
    mock_post.return_value = mock_resp

    unique_log = "alpha,beta,gamma,delta,epsilon"
    res = client.post("/api/logs/ingest", json={"logs": [unique_log]})
    assert res.status_code == 200
    data = res.json()["processed_logs"][0]
    assert data["inferred_by"] == "llm"

    # The deprecated 2.5 model must never reach the API; it is migrated to 3.6-flash
    call_args = mock_post.call_args
    assert "gemini-3.6-flash" in call_args.args[0]
    assert "gemini-2.5-flash" not in call_args.args[0]
    sent_payload = call_args.kwargs.get("json", {})
    assert sent_payload["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "low"}



@patch("pipeline.format_detector.requests.post")
@patch.dict("os.environ", {"GEMINI_API_KEY": "blocked_key", "GROQ_API_KEY": "gsk_fake"}, clear=True)
def test_39_groq_used_when_gemini_project_denied(mock_post):
    def side_effect(url, *args, **kwargs):
        resp = MagicMock()
        if "googleapis" in str(url):
            resp.status_code = 403
            msg = "Your project has been denied access. Please contact support."
            resp.text = json.dumps({"error": {"message": msg}})
            resp.json.return_value = {"error": {"message": msg}}
            return resp
        resp.status_code = 200
        resp.json.return_value = {
            "choices": [{"message": {"content": '{"method": "delimiter", "delimiter": "|"}'}}]
        }
        return resp

    mock_post.side_effect = side_effect
    unique_log = "gpart1 | gpart2 | gpart3 | gpart4"
    res = client.post("/api/logs/ingest", json={"logs": [unique_log]})
    assert res.status_code == 200
    data = res.json()["processed_logs"][0]
    assert data["inferred_by"] == "llm"
    assert data["format"] == "Pipe-Delimited"
    assert data["llm_error"] is None

    urls = [str(c.args[0]) for c in mock_post.call_args_list]
    assert any("googleapis" in u for u in urls)
    assert any("api.groq.com" in u for u in urls)


@patch("pipeline.format_detector.requests.post")
@patch.dict("os.environ", {"GEMINI_API_KEY": "blocked_key"}, clear=True)
def test_40_gemini_403_denied_skipped_on_next_discovery(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 403
    msg = "Your project has been denied access. Please contact support."
    mock_resp.text = json.dumps({"error": {"message": msg}})
    mock_resp.json.return_value = {"error": {"message": msg}}
    mock_post.return_value = mock_resp

    first = "ZX1 alpha [b1] (c2) k1=v1 k2=v2 k3=v3 k4=v4 tail"
    second = "INFO:zx2logger:circuit breaker second discovery"

    res1 = client.post("/api/logs/ingest", json={"logs": [first]})
    data1 = res1.json()["processed_logs"][0]
    assert data1["mode"] == "Discovery"
    assert data1["inferred_by"] == "heuristic"
    assert data1["llm_error"] is not None
    assert "denied access" in data1["llm_error"].lower() or "GROQ_API_KEY" in data1["llm_error"]

    calls_after_first = mock_post.call_count
    assert calls_after_first >= 1

    res2 = client.post("/api/logs/ingest", json={"logs": [second]})
    data2 = res2.json()["processed_logs"][0]
    assert data2["mode"] == "Discovery"
    assert data2["inferred_by"] == "heuristic"
    # Circuit breaker: do not hammer a Google project that already returned 403 denied.
    assert mock_post.call_count == calls_after_first
    # Later cards stay clean so the demo is not a wall of 403s.
    assert data2["llm_error"] is None


@patch("pipeline.format_detector.requests.post")
@patch.dict("os.environ", {"GROQ_API_KEY": "gsk_only"}, clear=True)
def test_41_groq_only_discovery(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": '{"method": "json"}'}}]
    }
    mock_post.return_value = mock_resp

    unique_log = '{"svc": "groq-only", "ok": true}'
    res = client.post("/api/logs/ingest", json={"logs": [unique_log]})
    assert res.status_code == 200
    data = res.json()["processed_logs"][0]
    assert data["inferred_by"] == "llm"
    assert data["format"] == "JSON Object"
    assert "api.groq.com" in mock_post.call_args.args[0]
    sent = mock_post.call_args.kwargs.get("json", {})
    # llama-3.1-8b-instant was retired by Groq; gpt-oss-20b is the replacement.
    assert sent.get("model") == "openai/gpt-oss-20b"
    # Groq json_object mode rejects gpt-oss reasoning output with HTTP 400,
    # so the request must not ask for it; we parse the JSON ourselves.
    assert "response_format" not in sent
    # Reasoning tokens share the budget, so 256 was too small.
    assert sent.get("max_tokens") >= 512
    assert sent.get("reasoning_effort") == "low"


def test_42_groq_model_resolution():
    from pipeline.format_detector import DEFAULT_GROQ_MODEL, _resolve_groq_model

    assert DEFAULT_GROQ_MODEL == "openai/gpt-oss-20b"

    with patch.dict("os.environ", {}, clear=True):
        assert _resolve_groq_model("") == "openai/gpt-oss-20b"
        # Retired ids (Groq shutdown 2026-08-16) auto-migrate to the default
        assert _resolve_groq_model("llama-3.1-8b-instant") == "openai/gpt-oss-20b"
        assert _resolve_groq_model("llama-3.3-70b-versatile") == "openai/gpt-oss-20b"
        # Gemini/Claude ids are never sent to Groq
        assert _resolve_groq_model("gemini-3.6-flash") == "openai/gpt-oss-20b"
        assert _resolve_groq_model("claude-3-5-haiku-20241022") == "openai/gpt-oss-20b"
        # Live Groq ids pass through untouched
        assert _resolve_groq_model("openai/gpt-oss-120b") == "openai/gpt-oss-120b"
        assert _resolve_groq_model("qwen/qwen3-32b") == "qwen/qwen3-32b"

    # GROQ_MODEL env var wins, and a retired value there is migrated too
    with patch.dict("os.environ", {"GROQ_MODEL": "openai/gpt-oss-120b"}, clear=True):
        assert _resolve_groq_model() == "openai/gpt-oss-120b"
    with patch.dict("os.environ", {"GROQ_MODEL": "llama-3.1-8b-instant"}, clear=True):
        assert _resolve_groq_model() == "openai/gpt-oss-20b"


@patch("pipeline.format_detector.requests.post")
@patch.dict("os.environ", {"GROQ_API_KEY": "gsk_only", "GROQ_MODEL": "llama-3.3-70b-versatile"}, clear=True)
def test_43_groq_reasoning_effort_only_for_gpt_oss(mock_post):
    # Sanity: a retired model in the env is migrated before the request is sent
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": '{"method": "delimiter", "delimiter": ","}'}}]
    }
    mock_post.return_value = mock_resp
    res = client.post("/api/logs/ingest", json={"logs": ["r43a,r43b,r43c,r43d,r43e"]})
    assert res.json()["processed_logs"][0]["inferred_by"] == "llm"
    sent = mock_post.call_args.kwargs.get("json", {})
    assert sent["model"] == "openai/gpt-oss-20b"
    assert sent["reasoning_effort"] == "low"

    # A non-reasoning Groq model must not get reasoning_effort (Groq 400s on it)
    with patch.dict("os.environ", {"GROQ_MODEL": "qwen/qwen3-32b"}):
        res = client.post("/api/logs/ingest", json={"logs": ["q43a,q43b,q43c,q43d,q43e,q43f"]})
        assert res.json()["processed_logs"][0]["inferred_by"] == "llm"
        sent = mock_post.call_args.kwargs.get("json", {})
        assert sent["model"] == "qwen/qwen3-32b"
        assert "reasoning_effort" not in sent
        assert "response_format" not in sent


@patch("pipeline.format_detector.requests.post")
@patch.dict("os.environ", {"GROQ_API_KEY": "gsk_only"}, clear=True)
def test_44_groq_400_failed_generation_recovered(mock_post):
    # This is the exact production failure: Groq rejects the generation with
    # 400 json_validate_failed but still returns the model's raw answer in
    # error.failed_generation. That answer is valid for us, so recover it.
    failed_gen = 'The line is pipe separated.\n{"method": "delimiter", "delimiter": "|"}'
    body = {
        "error": {
            "message": "Failed to validate JSON. Please adjust your prompt. See 'failed_generation' for more details.",
            "type": "invalid_request_error",
            "code": "json_validate_failed",
            "failed_generation": failed_gen,
        }
    }
    mock_resp = MagicMock()
    mock_resp.status_code = 400
    mock_resp.text = json.dumps(body)
    mock_resp.json.return_value = body
    mock_post.return_value = mock_resp

    unique_log = "fg44a | fg44b | fg44c | fg44d"
    res = client.post("/api/logs/ingest", json={"logs": [unique_log]})
    assert res.status_code == 200
    data = res.json()["processed_logs"][0]
    assert data["mode"] == "Discovery"
    assert data["inferred_by"] == "llm"
    assert data["format"] == "Pipe-Delimited"
    # Recovered successfully, so no "LLM fallback: Groq HTTP 400" on the card
    assert data["llm_error"] is None
    assert mock_post.call_count == 1


@patch("pipeline.format_detector.requests.post")
@patch.dict("os.environ", {"GROQ_API_KEY": "gsk_only"}, clear=True)
def test_45_groq_400_failed_generation_as_object(mock_post):
    # Groq occasionally returns failed_generation as a JSON object, not a string
    body = {
        "error": {
            "message": "Failed to validate JSON. Please adjust your prompt. See 'failed_generation' for more details.",
            "type": "invalid_request_error",
            "code": "json_validate_failed",
            "failed_generation": {"method": "json"},
        }
    }
    mock_resp = MagicMock()
    mock_resp.status_code = 400
    mock_resp.text = json.dumps(body)
    mock_resp.json.return_value = body
    mock_post.return_value = mock_resp

    unique_log = '{"svc": "fg45", "recovered": true}'
    res = client.post("/api/logs/ingest", json={"logs": [unique_log]})
    data = res.json()["processed_logs"][0]
    assert data["inferred_by"] == "llm"
    assert data["format"] == "JSON Object"
    assert data["llm_error"] is None


@patch("pipeline.format_detector.requests.post")
@patch.dict("os.environ", {"GROQ_API_KEY": "gsk_only"}, clear=True)
def test_46_groq_400_unusable_failed_generation_falls_back(mock_post):
    # failed_generation that does not validate (delimiter absent from the
    # line) must NOT be trusted; heuristics take over and the error surfaces.
    body = {
        "error": {
            "message": "Failed to validate JSON. Please adjust your prompt. See 'failed_generation' for more details.",
            "type": "invalid_request_error",
            "code": "json_validate_failed",
            "failed_generation": '{"method": "delimiter", "delimiter": ";"}',
        }
    }
    mock_resp = MagicMock()
    mock_resp.status_code = 400
    mock_resp.text = json.dumps(body)
    mock_resp.json.return_value = body
    mock_post.return_value = mock_resp

    unique_log = "FG46 alpha [b1] (c2) k1=v1 k2=v2 k3=v3 k4=v4 tail"
    res = client.post("/api/logs/ingest", json={"logs": [unique_log]})
    data = res.json()["processed_logs"][0]
    assert data["mode"] == "Discovery"
    assert data["inferred_by"] == "heuristic"
    assert data["llm_error"] is not None
    assert "Groq HTTP 400" in data["llm_error"]
    assert "Failed to validate JSON" in data["llm_error"]

    # A plain 400 without failed_generation behaves the same way
    parser.cache.clear()  # same structural fingerprint as above -> force Discovery
    body2 = {"error": {"message": "model_not_found", "type": "invalid_request_error"}}
    mock_resp.text = json.dumps(body2)
    mock_resp.json.return_value = body2
    res = client.post("/api/logs/ingest", json={"logs": ["FG46b beta [d3] (e4) m1=v1 m2=v2 m3=v3 m4=v4 tail"]})
    data = res.json()["processed_logs"][0]
    assert data["mode"] == "Discovery"
    assert data["inferred_by"] == "heuristic"
    assert "model_not_found" in data["llm_error"]


@patch("pipeline.format_detector.requests.post")
@patch.dict("os.environ", {"GROQ_API_KEY": "gsk_only"}, clear=True)
def test_47_groq_empty_content_falls_back_to_reasoning(mock_post):
    # gpt-oss can exhaust max_tokens while thinking: content is null but the
    # answer is sitting in message.reasoning.
    reasoning = (
        "We need to classify the log line. The schema is "
        '{"method": "json" | "delimiter" | "compositional", "delimiter": ","}. '
        "The line contains four pipe characters separating fields, so the "
        'answer is {"method": "delimiter", "delimiter": "|"}'
    )
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{
            "finish_reason": "length",
            "message": {"role": "assistant", "content": None, "reasoning": reasoning},
        }]
    }
    mock_post.return_value = mock_resp

    unique_log = "rs47a | rs47b | rs47c | rs47d | rs47e"
    res = client.post("/api/logs/ingest", json={"logs": [unique_log]})
    data = res.json()["processed_logs"][0]
    assert data["inferred_by"] == "llm"
    assert data["format"] == "Pipe-Delimited"
    assert data["llm_error"] is None

    # Non-empty content always wins over reasoning
    mock_resp.json.return_value = {
        "choices": [{
            "message": {
                "content": '{"method": "delimiter", "delimiter": ","}',
                "reasoning": 'I think {"method": "delimiter", "delimiter": "|"}',
            }
        }]
    }
    res = client.post("/api/logs/ingest", json={"logs": ["c47a,c47b,c47c,c47d,c47e,c47f,c47g"]})
    data = res.json()["processed_logs"][0]
    assert data["inferred_by"] == "llm"
    assert data["format"] == "Comma-Delimited"

    # Empty content AND empty reasoning -> heuristic with a clear verdict
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": "", "reasoning": ""}}]
    }
    res = client.post("/api/logs/ingest", json={"logs": ["EM47 gamma [f5] (g6) p1=v1 p2=v2 p3=v3 p4=v4 tail"]})
    data = res.json()["processed_logs"][0]
    assert data["inferred_by"] == "heuristic"
    assert data["llm_error"] == "Groq returned empty response"


def test_48_json_extraction_prefers_last_object_with_method():
    from pipeline.format_detector import DiscoveryEngine
    engine = DiscoveryEngine()

    # Schema restated first, real answer last: must not stop at the first {}
    noisy = (
        'Expected shape: {"method": "json" | "delimiter" | "compositional"}. '
        'Fields are separated by semicolons. Final: {"method": "delimiter", "delimiter": ";"}'
    )
    rule, err = engine._validate_and_build_rule(noisy, "x;y;z", {"is_json": False})
    assert err is None
    assert rule["method"] == "delimiter"
    assert rule["delimiter"] == ";"

    # An unrelated brace object before the answer is skipped too
    noisy2 = 'context {"note": "n/a"} then {"method": "compositional"}'
    rule, err = engine._validate_and_build_rule(noisy2, "hello world", {"is_json": False, "tok_count": 2, "eq_count": 0, "bracket_count": 0})
    assert err is None
    assert rule["method"] == "compositional"

    # Still rejects text with no usable object
    rule, err = engine._validate_and_build_rule("no json here at all", "hello", {"is_json": False})
    assert rule is None
    assert "invalid JSON" in err
