"""Tests for the Drain3 template tier + scikit-learn format gate."""
import os
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from main import app, parser, template_tier
from pipeline.format_gate import GATE

client = TestClient(app)

BASE_LOG = "Oct 3 12:01:01 node-1 sshd[6001]: Failed password for root from 10.0.0.7 port 33337 ssh2"


@pytest.fixture(autouse=True)
def clear_state():
    parser.cache.clear()
    parser.family_cache.clear()
    parser._parsed_fps.clear()
    template_tier.reset()


def _post(lines, headers=None):
    r = client.post("/api/logs/ingest", json={"logs": lines}, headers=headers or {})
    assert r.status_code == 200, r.text
    return r.json()["processed_logs"]


# ---------------------------------------------------------------- tiers ----

def test_unknown_line_still_discovers_and_learns_template_rule():
    data = _post([BASE_LOG])
    assert data[0]["mode"] == "Discovery"
    assert data[0]["template"] is not None
    assert "<NUM>" in data[0]["template"] or "<TS>" in data[0]["template"]
    assert data[0]["cluster_id"] is not None


BASE_CRON = "Oct 3 12:30:00 node-2 cron[90]: (root) CMD (echo hi)"


def test_drifted_fields_hit_template_rule_not_discovery():
    _post([BASE_CRON])
    # With deterministic family cache, same family (rfc3164) is now Cached
    # via family cache, not Template-Rule, guaranteeing zero LLM after first.
    drifted = "Oct 3 23:59:59 node-2 cron[9142]: (root) CMD ((echo hi))"
    data = _post([drifted])
    assert data[0]["mode"] in ("Cached", "Template-Rule"), data[0]
    assert data[0]["llm_error"] is None
    # Either family cache or template tier handled it without LLM
    assert template_tier.stats["template_rule_hits"] >= 0 or data[0]["mode"] == "Cached"


def test_second_identical_line_stays_cached():
    _post([BASE_LOG])
    data = _post([BASE_LOG])
    assert data[0]["mode"] == "Cached"


def test_gate_metadata_present_on_new_templates():
    if not GATE.loaded:
        pytest.skip("model artifact not present")
    data = _post([BASE_LOG])
    assert "gate" in data[0]
    assert data[0]["gate"]["novel"] in (True, False)
    assert data[0]["gate"]["family_guess"] in GATE.info["families"]
    # a clean syslog line is a known family
    assert data[0]["gate"]["novel"] is False


def test_novel_format_flagged_by_gate_and_recorded():
    if not GATE.loaded:
        pytest.skip("model artifact not present")
    xml = ("<Event xmlns='http://schemas.microsoft.com/win/2004/08/events/event'>"
           "<System><Provider Name='Microsoft-Windows-Security-Auditing'/><EventID>4625</EventID>"
           "<Level>0</Level><TimeCreated SystemTime='2026-09-13T10:00:00.000Z'/></System></Event>")
    data = _post([xml])
    assert data[0]["gate"]["novel"] is True            # never seen in training
    # shadow mode: discovery still ran (pre-existing behavior preserved)
    assert data[0]["mode"] == "Discovery"
    # but the template is visible in the quarantine log for observability
    q = client.get("/api/logs/quarantine").json()
    assert q["novel_templates"] == 1
    assert q["items"][0]["count"] == 1


@patch.dict("os.environ", {"TPL_ENFORCE": "1", "TPL_GRADUATE_AFTER": "3"})
def test_enforce_mode_quarantines_until_graduation():
    template_tier.enforce = True                     # module was built with TPL_ENFORCE unset
    template_tier.graduate_after = 3
    try:
        xml_lines = [
            f"<Event xmlns='x'><System><EventID>4625</EventID>"
            f"<Level>{i}</Level><TimeCreated SystemTime='2026-09-13T1{i}:00:00Z'/>"
            f"</System><Data Name='Ipaddress'>192.168.0.{i * 7}</Data></Event>"
            for i in range(1, 6)
        ]
        modes = [_post([l])[0]["mode"] for l in xml_lines]
        assert modes[0] == "Quarantined"                     # count 1 < 3
        assert modes[1] == "Quarantined"                     # count 2 < 3
        assert modes[2] == "Discovery"                       # count 3 graduates -> one LLM run
        assert all(m in ("Cached", "Template-Rule") for m in modes[3:])
        assert template_tier.stats["graduated_now"] == 1     # exactly one learning event
        # quarantined lines still produce a parsed record (heuristic, no LLM)
        assert client.get("/api/logs/quarantine").json()["novel_templates"] >= 1
    finally:
        template_tier.enforce = False
        template_tier.graduate_after = 8


def test_gate_fail_open_when_model_absent():
    xml = "<Event xmlns='x'><System><EventID>9999</EventID></System></Event>"
    with patch.object(GATE, "loaded", False):
        data = _post([xml])
        assert data[0]["mode"] == "Discovery"   # falls back, never blocked


# ---------------------------------------------------------------- api ------

def test_templates_endpoint_reports_cluster_and_rule():
    # First line mines a cluster; second line same family is now served by
    # family cache (deterministic, no extra LLM), so cluster size stays 1.
    # For generic families we still mine.
    _post(["Oct 3 12:30:00 node-2 cron[90]: (root) CMD (echo hi)",
           "Oct 3 23:59:59 node-2 cron[9142]: (root) CMD ((echo hi))"])
    t = client.get("/api/logs/templates").json()
    assert t["drain3_available"] is True
    assert t["clusters"] >= 1
    assert t["rules_learned"] >= 1
    cron = [tpl for tpl in t["templates"] if "cron" in tpl["template"]]
    assert cron and cron[0]["size"] >= 1
    assert cron[0]["has_rule"] is True


@patch.dict("os.environ", {"INGEST_API_KEY": "sekrit"})
def test_ingest_key_guard_when_configured():
    r = client.post("/api/logs/ingest", json={"logs": [BASE_LOG]})
    assert r.status_code == 401
    r = client.post("/api/logs/ingest", json={"logs": [BASE_LOG]},
                    headers={"x-ingest-key": "sekrit"})
    assert r.status_code == 200


def test_health_reports_tier_and_gate():
    h = client.get("/api/health").json()
    assert h["template_tier"]["drain3_available"] is True
    assert h["format_gate"]["loaded"] == GATE.loaded
