import json
import datetime
from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient

from main import app, parser, normalizer, discovery_engine, template_tier
from pipeline.time_util import parse_timestamp
from pipeline.gate import GATE

client = TestClient(app)


@pytest.fixture(autouse=True)
def clear_state():
    parser.cache.clear()
    parser.family_cache.clear()
    parser._parsed_fps.clear()
    template_tier.reset()
    discovery_engine._skip_gemini = False


def _ingest(lines):
    res = client.post("/api/logs/ingest", json={"logs": lines})
    assert res.status_code == 200, res.text
    return res.json()["processed_logs"]


def test_ingest_mixed_lines():
    data = _ingest(['{"a": 1}', 'hello'])
    assert len(data) == 2
    assert data[0]["mode"] == "Discovery"
    assert data[1]["mode"] == "Discovery"
    assert data[0]["format"] == "JSON Object"
    assert data[1]["format"] != "JSON Object"


def test_severity_normalization():
    data = _ingest([
        '{"severity": 3, "msg": "test"}',
        '{"severity": [1], "msg": "test"}',
        '{"level": "verbose", "msg": "test"}'
    ])
    assert data[0]["normalized"]["severity"] == "error"
    assert data[1]["normalized"]["severity"] == "unknown"
    assert data[2]["normalized"]["severity"] == "unknown"
    assert data[2]["normalized"]["extra"]["severity_raw"] == "verbose"


def test_one_bad_record_does_not_kill_batch():
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


def test_json_field_mapping():
    log = '{"level":"warn","ts":1700000000,"msg":"hi","host":"h1","event":"login","nested":{"a":1}}'
    data = _ingest([log])
    norm = data[0]["normalized"]
    assert norm["severity"] == "warning"
    assert norm["message"] == "hi"
    assert norm["source"] == "h1"
    assert norm["event_type"] == "login"
    assert norm["timestamp"] == "2023-11-14T22:13:20Z"
    assert norm["extra"] == {"nested": {"a": 1}}


def test_csv_log():
    log = '2026-09-13T10:15:30Z,ERROR,Connection reset by peer,app-server-02,pid=992'
    norm = _ingest([log])[0]["normalized"]
    assert norm["timestamp"] == "2026-09-13T10:15:30Z"
    assert norm["severity"] == "error"
    assert norm["message"] == "Connection reset by peer"
    assert norm["source"] == "app-server-02"
    assert norm["extra"]["pid"] == "992"


def test_pipe_log():
    log = '2026-09-13T10:20:00Z | CRITICAL | PaymentGateway | Transaction txn-8829 failed due to timeout after 3000ms'
    norm = _ingest([log])[0]["normalized"]
    assert norm["severity"] == "critical"
    assert norm["source"] == "PaymentGateway"
    assert norm["message"].startswith("Transaction txn-8829")


def test_syslog():
    norm1 = _ingest(["Oct 11 22:14:15 mymachine su: 'su root' failed for lonvick"])[0]["normalized"]
    assert norm1["source"] == "mymachine"
    assert norm1["extra"]["program"] == "su"

    norm2 = _ingest(["<134>Oct 11 22:14:15 host app[42]: hello"])[0]["normalized"]
    assert norm2["severity"] == "info"
    assert norm2["source"] == "host"
    assert norm2["extra"]["pid"] == "42"
    assert norm2["timestamp"] is not None


def test_bracket_severity():
    data = _ingest(["[ERROR] disk full", "2026-09-13 [main] ERROR c.f.Bar - boom"])
    assert data[0]["normalized"]["severity"] == "error"
    assert data[1]["normalized"]["severity"] == "error"


def test_kv_pairs():
    extra = _ingest(['(status=OK) user="john doe" n=5'])[0]["normalized"]["extra"]
    assert extra["status"] == "OK"
    assert extra["user"] == "john doe"
    assert extra["n"] == "5"


def test_timezones():
    assert parse_timestamp("2026-09-13T10:00:00") == "2026-09-13T10:00:00Z"
    assert parse_timestamp("2026-09-13T10:00:00+05:30") == "2026-09-13T04:30:00Z"
    assert parse_timestamp("2026-09-13T10:00:00+00:00") == "2026-09-13T10:00:00Z"


def test_year_inference():
    now1 = datetime.datetime(2026, 1, 5, tzinfo=datetime.timezone.utc)
    assert parse_timestamp("Dec 30 10:00:00", now=now1) == "2025-12-30T10:00:00Z"
    assert parse_timestamp("Jan 4 10:00:00", now=now1) == "2026-01-04T10:00:00Z"


def test_garbage_timestamp():
    assert parse_timestamp("12 users connected") is None
    assert parse_timestamp("10:15:32 ERROR x") is None


def test_multiline_buffering():
    logs = [
        "{",
        '  "level": "error",',
        '  "message": "boom"',
        "}",
        "Traceback (most recent call last):",
        '  File "test.py", line 1',
        "ValueError: boom",
        "Caused by: test",
        '{"a": "unterminated',
        "b",
        "independent line 1",
        "independent line 2"
    ]
    data = _ingest(logs)
    assert data[0]["format"] == "JSON Object"
    assert "ValueError: boom" in data[1]["normalized"]["raw"]
    assert "Caused by: test" in data[1]["normalized"]["raw"]
    assert len(data) == 6


def test_cache_eviction():
    for i in range(510):
        parser.store_rule({"is_json": False, "tok_count": i, "bracket_count": 0, "comma_count": 0, "eq_count": 0, "pipe_count": 0, "delim": None}, {"method": "compositional"})
    assert len(parser.cache) <= 500
    cache_res = client.get("/api/logs/cache")
    assert len(cache_res.json()["cache"]) <= 500


def test_batch_limits():
    res = client.post("/api/logs/ingest", json={"logs": ["a"] * 1001})
    assert res.status_code == 422
    res = client.post("/api/logs/ingest", json={"logs": ["a" * 10001]})
    assert res.status_code == 422
    res = client.post("/api/logs/ingest", json={"logs": []})
    assert res.json()["processed_logs"] == []


@patch("pipeline.llm.requests.post")
@patch.dict("os.environ", {"GEMINI_API_KEY": "fake_key"})
def test_llm_rule_lifecycle(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": '```json\n{"method": "delimiter", "delimiter": "|"}\n```'}]}}]
    }
    mock_post.return_value = mock_resp

    data = _ingest(["a | b | c"])
    assert data[0]["inferred_by"] == "llm"
    assert data[0]["format"] == "Pipe-Delimited"

    parser.family_cache.clear()
    parser.cache.clear()
    parser._parsed_fps.clear()

    mock_resp.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": '{"method": "magic"}'}]}}]
    }
    data = _ingest(["d | e | f | g"])
    assert data[0]["inferred_by"] == "heuristic"

    parser.family_cache.clear()
    parser.cache.clear()
    parser._parsed_fps.clear()

    mock_post.side_effect = Exception("network")
    data = _ingest(["h | i | j | k | l"])
    assert data[0]["inferred_by"] == "heuristic"


def test_ncsa_combined():
    log = '192.168.1.100 - john [19/Sep/2026:13:24:00 +0000] "GET /index.html HTTP/1.1" 200 4321 "https://google.com" "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"'
    data = _ingest([log])
    assert data[0]["format"] == "NCSA Combined / Web Access Log"
    norm = data[0]["normalized"]
    assert norm["timestamp"] == "2026-09-19T13:24:00Z"
    assert norm["source"] == "192.168.1.100"
    assert norm["event_type"] == "http_request"
    assert norm["severity"] == "info"
    assert norm["message"] == "GET /index.html HTTP/1.1"
    assert norm["extra"]["http_status"] == 200
    assert norm["extra"]["user"] == "john"
    assert norm["extra"]["bytes_sent"] == 4321
    assert norm["extra"]["http_method"] == "GET"


def test_spring_boot():
    log = "2026-09-19 14:32:10.123 [main] INFO org.springframework.boot.Startup - Started Application in 2.5s"
    data = _ingest([log])
    assert "Java Application" in data[0]["format"]
    norm = data[0]["normalized"]
    assert norm["timestamp"] == "2026-09-19T14:32:10.123000Z"
    assert norm["severity"] == "info"
    assert norm["source"] == "org.springframework.boot.Startup"
    assert norm["message"] == "Started Application in 2.5s"
    assert norm["extra"]["thread"] == "main"


def test_python_logger():
    log = "INFO:root:Connected to database successfully"
    data = _ingest([log])
    assert data[0]["format"] == "Python Standard Logger"
    norm = data[0]["normalized"]
    assert norm["severity"] == "info"
    assert norm["source"] == "root"
    assert norm["message"] == "Connected to database successfully"


def test_k8s_cri():
    log = "2026-09-19T14:32:10.123456789Z stdout F Starting web server on :8080"
    data = _ingest([log])
    assert data[0]["format"] == "Kubernetes / CRI Container Log"
    norm = data[0]["normalized"]
    assert norm["timestamp"] == "2026-09-19T14:32:10.123456Z"
    assert norm["severity"] == "info"
    assert norm["message"] == "Starting web server on :8080"
    assert norm["extra"]["stream"] == "stdout"


def test_nginx_error():
    log = '2026/09/19 14:32:10 [error] 1234#0: *1 open() "/favicon.ico" failed, client: 192.168.1.10'
    data = _ingest([log])
    assert data[0]["format"] == "Nginx / Web Server Error Log"
    norm = data[0]["normalized"]
    assert norm["timestamp"] == "2026-09-19T14:32:10Z"
    assert norm["severity"] == "error"
    assert norm["source"] == "nginx"
    assert norm["message"] == 'open() "/favicon.ico" failed'
    assert norm["extra"]["client"] == "192.168.1.10"


def test_rfc5424_syslog():
    log = "<165>1 2026-09-19T14:32:10.003Z mymachine.example.com evntslog 1234 ID47 - An application event log entry"
    data = _ingest([log])
    assert data[0]["format"] == "RFC 5424 Syslog"
    norm = data[0]["normalized"]
    assert norm["timestamp"] == "2026-09-19T14:32:10.003000Z"
    assert norm["severity"] == "info"
    assert norm["source"] == "mymachine.example.com"
    assert norm["event_type"] == "ID47"
    assert norm["message"] == "An application event log entry"
    assert norm["extra"]["program"] == "evntslog"


def test_cef():
    log = "CEF:0|SecurityCompany|Firewall|1.0|100|Packet dropped|5|src=10.0.0.1 dst=10.0.0.2 spt=1234 dpt=80"
    data = _ingest([log])
    assert data[0]["format"] == "CEF (Common Event Format)"
    norm = data[0]["normalized"]
    assert norm["source"] == "SecurityCompany Firewall"
    assert norm["event_type"] == "100"
    assert norm["message"] == "Packet dropped"
    assert norm["extra"]["src"] == "10.0.0.1"
    assert norm["extra"]["dpt"] == "80"


def test_logfmt():
    log = 'ts=2026-09-19T14:32:10.123Z level=error caller=main.go:42 msg="crash detected" err="null pointer" thread_id=9'
    data = _ingest([log])
    assert data[0]["format"] == "Logfmt / Key-Value Stream"
    norm = data[0]["normalized"]
    assert norm["timestamp"] == "2026-09-19T14:32:10.123000Z"
    assert norm["severity"] == "error"
    assert norm["source"] == "main.go:42"
    assert norm["message"] == "crash detected"
    assert norm["extra"]["err"] == "null pointer"


def test_docker_wrapped_json():
    inner = '2026-09-19 14:32:10.123 [main] INFO org.demo.App - Server ready'
    log = json.dumps({"log": inner + "\n", "stream": "stdout", "time": "2026-09-19T14:32:10.500Z"})
    data = _ingest([log])
    assert data[0]["format"] == "JSON Object"
    norm = data[0]["normalized"]
    assert norm["timestamp"] == "2026-09-19T14:32:10.123000Z"
    assert norm["severity"] == "info"
    assert norm["source"] == "org.demo.App"
    assert norm["message"] == "Server ready"
    assert norm["extra"]["stream"] == "stdout"


def test_ansi_stripped():
    log = "\x1b[32m2026-09-19 14:32:10.123 [main] INFO org.demo.App - Colorized message\x1b[0m"
    norm = _ingest([log])[0]["normalized"]
    assert norm["severity"] == "info"
    assert norm["message"] == "Colorized message"


def test_auth_failure_entities():
    log = "Failed password for invalid user admin from 192.168.1.105 port 54321 ssh2"
    norm = _ingest([log])[0]["normalized"]
    assert norm["event_type"] == "auth_failure"
    assert norm["severity"] == "warning"
    assert norm["source"] == "192.168.1.105"
    assert norm["extra"]["ip"] == "192.168.1.105"
    assert norm["extra"]["port"] == "54321"
    assert norm["extra"]["user"] == "admin"


@patch("pipeline.llm.requests.post")
@patch.dict("os.environ", {"GEMINI_API_KEY": "fake_key"})
def test_llm_error_surfaced_on_failure(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 403
    mock_resp.text = '{"error": {"message": "API key not valid"}}'
    mock_post.return_value = mock_resp

    unique_log = "ZXQW alpha [b1] (c2) k1=v1 k2=v2 k3=v3 k4=v4 tail"
    data = _ingest([unique_log])
    assert data[0]["mode"] == "Discovery"
    assert data[0]["inferred_by"] == "heuristic"
    assert data[0]["llm_error"] is not None
    assert "403" in data[0]["llm_error"]

    data = _ingest([unique_log])
    assert data[0]["mode"] == "Cached"
    assert data[0]["llm_error"] is None


@patch.dict("os.environ", {}, clear=True)
def test_no_key_message():
    unique_log = "QWZX beta [d3] (e4) m1=v1 m2=v2 m3=v3 m4=v4 tail"
    data = _ingest([unique_log])
    assert data[0]["mode"] == "Discovery"
    assert data[0]["inferred_by"] == "heuristic"
    assert data[0]["llm_error"] == "No LLM API key configured (set GEMINI_API_KEY, GROQ_API_KEY or ANTHROPIC_API_KEY)"


@patch("pipeline.llm.requests.post")
@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "fake_anthropic_key"}, clear=True)
def test_anthropic_provider(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"content": [{"type": "text", "text": '{"method": "json"}'}]}
    mock_post.return_value = mock_resp

    data = _ingest(['{"service": "test", "status": "ok"}'])
    assert data[0]["inferred_by"] == "llm"
    assert data[0]["format"] == "JSON Object"
    assert "api.anthropic.com" in mock_post.call_args.args[0]


@patch("pipeline.llm.requests.post")
@patch.dict("os.environ", {"GEMINI_API_KEY": "blocked_key", "GROQ_API_KEY": "gsk_fake"}, clear=True)
def test_groq_fallback_when_gemini_denied(mock_post):
    def side_effect(url, *args, **kwargs):
        resp = MagicMock()
        if "googleapis" in str(url):
            resp.status_code = 403
            msg = "Your project has been denied access. Please contact support."
            resp.text = json.dumps({"error": {"message": msg}})
            resp.json.return_value = {"error": {"message": msg}}
            return resp
        resp.status_code = 200
        resp.json.return_value = {"choices": [{"message": {"content": '{"method": "delimiter", "delimiter": "|"}'}}]}
        return resp

    mock_post.side_effect = side_effect
    data = _ingest(["gpart1 | gpart2 | gpart3 | gpart4"])
    assert data[0]["inferred_by"] == "llm"
    assert data[0]["format"] == "Pipe-Delimited"
    urls = [str(c.args[0]) for c in mock_post.call_args_list]
    assert any("googleapis" in u for u in urls)
    assert any("api.groq.com" in u for u in urls)


@patch("pipeline.llm.requests.post")
@patch.dict("os.environ", {"GEMINI_API_KEY": "blocked_key"}, clear=True)
def test_gemini_403_breaker(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 403
    msg = "Your project has been denied access. Please contact support."
    mock_resp.text = json.dumps({"error": {"message": msg}})
    mock_resp.json.return_value = {"error": {"message": msg}}
    mock_post.return_value = mock_resp

    first = "ZX1 alpha [b1] (c2) k1=v1 k2=v2 k3=v3 k4=v4 tail"
    second = "INFO:zx2logger:circuit breaker second discovery"

    data1 = _ingest([first])[0]
    assert data1["mode"] == "Discovery"
    assert data1["inferred_by"] == "heuristic"
    calls_after_first = mock_post.call_count
    assert calls_after_first >= 1

    _ingest([second])
    assert mock_post.call_count == calls_after_first


@patch("pipeline.llm.requests.post")
@patch.dict("os.environ", {"GROQ_API_KEY": "gsk_only"}, clear=True)
def test_groq_only(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"choices": [{"message": {"content": '{"method": "json"}'}}]}
    mock_post.return_value = mock_resp

    data = _ingest(['{"svc": "groq-only", "ok": true}'])
    assert data[0]["inferred_by"] == "llm"
    assert "api.groq.com" in mock_post.call_args.args[0]
    sent = mock_post.call_args.kwargs.get("json", {})
    assert sent.get("model") == "openai/gpt-oss-20b"
    assert sent.get("reasoning_effort") == "low"


@patch("pipeline.llm.requests.post")
@patch.dict("os.environ", {"GROQ_API_KEY": "gsk_only"}, clear=True)
def test_groq_400_failed_generation_recovered(mock_post):
    failed_gen = 'The line is pipe separated.\n{"method": "delimiter", "delimiter": "|"}'
    body = {"error": {"message": "Failed to validate JSON. See 'failed_generation' for details.", "code": "json_validate_failed", "failed_generation": failed_gen}}
    mock_resp = MagicMock()
    mock_resp.status_code = 400
    mock_resp.text = json.dumps(body)
    mock_resp.json.return_value = body
    mock_post.return_value = mock_resp

    data = _ingest(["fg44a | fg44b | fg44c | fg44d"])
    assert data[0]["mode"] == "Discovery"
    assert data[0]["inferred_by"] == "llm"
    assert data[0]["format"] == "Pipe-Delimited"
    assert data[0]["llm_error"] is None


@patch("pipeline.llm.requests.post")
@patch.dict("os.environ", {"GROQ_API_KEY": "gsk_only"}, clear=True)
def test_groq_empty_content_reasoning_fallback(mock_post):
    reasoning = (
        'We need to classify the log line. It contains four pipe characters, '
        'so the answer is {"method": "delimiter", "delimiter": "|"}'
    )
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"choices": [{"message": {"content": None, "reasoning": reasoning}}]}
    mock_post.return_value = mock_resp

    data = _ingest(["rs47a | rs47b | rs47c | rs47d | rs47e"])
    assert data[0]["inferred_by"] == "llm"
    assert data[0]["format"] == "Pipe-Delimited"


def test_health_endpoints():
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert "status" in data
    assert "llm_configured" in data

    res_llm = client.get("/api/health/llm")
    assert res_llm.status_code == 200
    assert "status" in res_llm.json()


def test_json_candidate_extraction():
    from pipeline.llm import DiscoveryEngine
    engine = DiscoveryEngine()

    noisy = (
        'Expected shape: {"method": "json" | "delimiter" | "compositional"}. '
        'Fields are separated by semicolons. Final: {"method": "delimiter", "delimiter": ";"}'
    )
    rule, err = engine._validate_and_build_rule(noisy, "x;y;z", {"is_json": False})
    assert err is None
    assert rule["method"] == "delimiter"
    assert rule["delimiter"] == ";"

    rule, err = engine._validate_and_build_rule("no json here at all", "hello", {"is_json": False})
    assert rule is None
    assert "invalid JSON" in err


def test_clear_endpoint():
    _ingest([
        "2026-09-13T10:15:30Z,ERROR,Connection reset by peer,app-server-02,pid=992",
        "2026-09-13T10:16:00Z,WARNING,Timeout,app-server-03,pid=100",
        "some completely unstructured generic log line about a failure",
    ])
    assert parser.family_cache
    assert parser.cache

    res = client.post("/api/logs/clear")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "cleared"
    assert body["cleared"]["family_cache"] >= 1
    assert body["cleared"]["fingerprint_cache"] >= 1
    assert parser.family_cache == {}
    assert parser.cache == {}
    assert template_tier.quarantine_view()["items"] == []
    assert all(v == 0 for v in template_tier.stats.values())


def test_clear_makes_next_ingest_discover_again():
    csv_a = "2026-09-13T10:15:30Z,ERROR,Connection reset by peer,app-server-02,pid=992"
    csv_b = "2026-09-13T10:16:00Z,WARNING,Timeout,app-server-03,pid=100"

    assert _ingest([csv_a])[0]["mode"] == "Discovery"
    assert _ingest([csv_b])[0]["mode"] == "Cached"
    client.post("/api/logs/clear")
    assert _ingest([csv_b])[0]["mode"] == "Discovery"


def test_clear_idempotent():
    client.post("/api/logs/clear")
    body = client.post("/api/logs/clear").json()
    assert body["cleared"]["family_cache"] == 0
    assert body["cleared"]["fingerprint_cache"] == 0
    assert body["cleared"]["templates"] == 0


BASE_LOG = "Oct 3 12:01:01 node-1 sshd[6001]: Failed password for root from 10.0.0.7 port 33337 ssh2"


def test_template_rule_learned():
    data = _ingest([BASE_LOG])
    assert data[0]["mode"] == "Discovery"
    assert data[0]["template"] is not None
    assert data[0]["cluster_id"] is not None


def test_second_identical_line_cached():
    _ingest([BASE_LOG])
    data = _ingest([BASE_LOG])
    assert data[0]["mode"] == "Cached"


def test_gate_metadata_on_new_templates():
    if not GATE.loaded:
        pytest.skip("model artifact not present")
    data = _ingest([BASE_LOG])
    assert "gate" in data[0]
    assert data[0]["gate"]["novel"] in (True, False)
    assert data[0]["gate"]["family_guess"] in GATE.info["families"]
    assert data[0]["gate"]["novel"] is False


def test_novel_format_flagged():
    if not GATE.loaded:
        pytest.skip("model artifact not present")
    xml = ("<Event xmlns='http://schemas.microsoft.com/win/2004/08/events/event'>"
           "<System><Provider Name='Microsoft-Windows-Security-Auditing'/><EventID>4625</EventID>"
           "<Level>0</Level><TimeCreated SystemTime='2026-09-13T10:00:00.000Z'/></System></Event>")
    data = _ingest([xml])
    assert data[0]["gate"]["novel"] is True
    assert data[0]["mode"] == "Discovery"
    q = client.get("/api/logs/quarantine").json()
    assert q["novel_templates"] == 1
    assert q["items"][0]["count"] == 1


@patch.dict("os.environ", {"TPL_ENFORCE": "1", "TPL_GRADUATE_AFTER": "3"})
def test_enforce_mode_graduation():
    template_tier.enforce = True
    template_tier.graduate_after = 3
    try:
        xml_lines = [
            f"<Event xmlns='x'><System><EventID>4625</EventID>"
            f"<Level>{i}</Level><TimeCreated SystemTime='2026-09-13T1{i}:00:00Z'/>"
            f"</System><Data Name='Ipaddress'>192.168.0.{i * 7}</Data></Event>"
            for i in range(1, 6)
        ]
        modes = [_ingest([l])[0]["mode"] for l in xml_lines]
        assert modes[0] == "Quarantined"
        assert modes[1] == "Quarantined"
        assert modes[2] == "Discovery"
        assert all(m in ("Cached", "Template-Rule") for m in modes[3:])
        assert template_tier.stats["graduated_now"] == 1
        assert client.get("/api/logs/quarantine").json()["novel_templates"] >= 1
    finally:
        template_tier.enforce = False
        template_tier.graduate_after = 8


def test_gate_fail_open_when_model_absent():
    xml = "<Event xmlns='x'><System><EventID>9999</EventID></System></Event>"
    with patch.object(GATE, "loaded", False):
        data = _ingest([xml])
        assert data[0]["mode"] == "Discovery"


def test_templates_endpoint():
    _ingest(["Oct 3 12:30:00 node-2 cron[90]: (root) CMD (echo hi)",
             "Oct 3 23:59:59 node-2 cron[9142]: (root) CMD ((echo hi))"])
    t = client.get("/api/logs/templates").json()
    assert t["drain3_available"] is True
    assert t["clusters"] >= 1
    assert t["rules_learned"] >= 1
    cron = [tpl for tpl in t["templates"] if "cron" in tpl["template"]]
    assert cron and cron[0]["size"] >= 1
    assert cron[0]["has_rule"] is True


@patch.dict("os.environ", {"INGEST_API_KEY": "sekrit"})
def test_ingest_key_guard():
    r = client.post("/api/logs/ingest", json={"logs": [BASE_LOG]})
    assert r.status_code == 401
    r = client.post("/api/logs/ingest", json={"logs": [BASE_LOG]}, headers={"x-ingest-key": "sekrit"})
    assert r.status_code == 200


def test_health_reports_tier_and_gate():
    h = client.get("/api/health").json()
    assert h["template_tier"]["drain3_available"] is True
    assert h["format_gate"]["loaded"] == GATE.loaded


def test_pages_served():
    console = client.get("/")
    assert console.status_code == 200
    assert "text/html" in console.headers["content-type"]
    assert '/static/common.js' in console.text
    assert '/static/style.css' in console.text

    explorer = client.get("/records")
    assert explorer.status_code == 200
    assert "/static/common.js" in explorer.text
    assert "/static/records.js" in explorer.text

    ui = client.get("/static/common.js")
    assert ui.status_code == 200
    for symbol in ("highlightJSON", "recordNotes", "saveRun", "getRun"):
        assert symbol in ui.text
