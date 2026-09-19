import pytest
from fastapi.testclient import TestClient
import datetime
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
@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "fake_key"})
def test_18_llm_testing(mock_post):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"content": [{"text": '```json\n{"method": "delimiter", "delimiter": "|"}\n```'}]}
    mock_post.return_value = mock_resp
    
    # Mock LLM Success
    res = client.post("/api/logs/ingest", json={"logs": ["a | b | c"]})
    data = res.json()["processed_logs"][0]
    assert data["inferred_by"] == "llm"
    assert data["format"] == "Pipe-Delimited"
    
    # Mock LLM Invalid method -> fallback
    mock_resp.json.return_value = {"content": [{"text": '{"method": "magic"}'}]}
    res = client.post("/api/logs/ingest", json={"logs": ["d | e | f | g"]})
    data = res.json()["processed_logs"][0]
    assert data["inferred_by"] == "heuristic"
    
    # Mock Network Error
    mock_post.side_effect = Exception("network")
    res = client.post("/api/logs/ingest", json={"logs": ["h | i | j | k | l"]})
    data = res.json()["processed_logs"][0]
    assert data["inferred_by"] == "heuristic"
