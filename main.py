import os
import time
import json
import logging
import re
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, StringConstraints
from typing import List
from typing_extensions import Annotated
from pipeline.format_detector import (
    DiscoveryEngine,
    DEFAULT_MODEL,
    _resolve_gemini_model,
    _resolve_anthropic_model,
    _resolve_groq_model,
)
from pipeline.parser import UniversalParser
from pipeline.normalizer import Normalizer
from pipeline.template_miner import TemplateMinerTier
from pipeline.format_gate import GATE

app = FastAPI(title="Format-Agnostic Two-Tier Log Pipeline (SIH26)")

static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

@app.get("/")
def read_index():
    return FileResponse(str(static_dir / "index.html"))

discovery_engine = DiscoveryEngine()
parser = UniversalParser()
normalizer = Normalizer()
template_tier = TemplateMinerTier()


def _require_ingest_key(request: Request) -> None:
    expected = os.environ.get("INGEST_API_KEY")
    if expected and request.headers.get("x-ingest-key", "") != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing x-ingest-key header")

@app.get("/api/health")
def health(check_live: bool = False):
    raw_model = os.environ.get("DISCOVERY_MODEL", DEFAULT_MODEL)
    has_gemini = bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
    has_groq = bool(os.environ.get("GROQ_API_KEY"))
    has_anthropic = bool(os.environ.get("ANTHROPIC_API_KEY"))
    gemini_skipped = bool(getattr(discovery_engine, "_skip_gemini", False))

    if has_gemini and not gemini_skipped:
        active_provider = "gemini"
        resolved_model = _resolve_gemini_model(raw_model)
    elif has_groq:
        active_provider = "groq"
        resolved_model = _resolve_groq_model()
    elif has_anthropic:
        active_provider = "anthropic"
        resolved_model = _resolve_anthropic_model()
    elif has_gemini:
        active_provider = "gemini"
        resolved_model = _resolve_gemini_model(raw_model)
    else:
        active_provider = None
        resolved_model = _resolve_gemini_model(raw_model)

    # family cache stats
    try:
        family_snapshot = parser.snapshot_family_cache()
        family_stats = {
            "families_learned": len(family_snapshot),
            "families": list(family_snapshot.keys()),
        }
    except Exception:
        family_stats = {"families_learned": 0, "families": []}

    resp = {
        "status": "healthy",
        "llm_configured": bool(has_gemini or has_groq or has_anthropic),
        "provider": active_provider,
        "model": resolved_model,
        "raw_model": raw_model,
        "gemini_skipped": gemini_skipped,
        "has_groq": has_groq,
        "template_tier": {
            "drain3_available": not template_tier.disabled,
            "enforce_mode": template_tier.enforce,
            "rule_backend": template_tier.rule_backend(),
            "stats": dict(template_tier.stats),
        },
        "format_gate": GATE.info,
        "family_cache": family_stats,
        "ingest_auth": bool(os.environ.get("INGEST_API_KEY")),
    }
    if check_live:
        resp["live_check"] = discovery_engine.check_llm()
    return resp

@app.get("/api/health/llm")
def health_llm():
    return discovery_engine.check_llm()

class LogBatch(BaseModel):
    logs: Annotated[List[Annotated[str, StringConstraints(max_length=10000)]], Field(max_length=1000)]

EXC_PATTERN = re.compile(r'^[A-Za-z_][\w.]*(Error|Exception|Exit|Interrupt|Warning)\b')

def buffer_lines(lines: List[str]) -> List[str]:
    if not lines:
        return []

    buffered = []
    current_entry = []

    json_depth = 0
    in_string = False
    in_traceback = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        continues = False

        if current_entry:
            if json_depth > 0:
                continues = True
            elif line.startswith(' ') or line.startswith('\t'):
                continues = True
            elif line.startswith('Caused by:') or line.startswith('... '):
                continues = True
            elif line.strip().startswith('at ') and ('(' in line or '.' in line):
                continues = True
            elif in_traceback and EXC_PATTERN.match(line):
                continues = True
                in_traceback = False

        if continues and len(current_entry) < 500:
            current_entry.append(line)
        else:
            if current_entry:
                buffered.append('\n'.join(current_entry))
            current_entry = [line]
            json_depth = 0
            in_string = False
            in_traceback = False

        i = 0
        while i < len(line):
            c = line[i]
            if in_string:
                if c == '\\': i += 1
                elif c == '"': in_string = False
            else:
                if c == '"': in_string = True
                elif c == '{': json_depth += 1
                elif c == '}': json_depth -= 1
            i += 1

        if json_depth < 0: json_depth = 0
        if in_string:
            json_depth = 0
            in_string = False

        if "Traceback (most recent call last):" in line or "Exception in thread" in line:
            in_traceback = True

    if current_entry:
        buffered.append('\n'.join(current_entry))

    return buffered

def process_record(log: str) -> dict:
    start_time = time.perf_counter()
    try:
        # --- Deterministic family detection (primary cache key) ---
        from pipeline.parser import KNOWN_FAMILIES
        family = parser.detect_family(log)

        # Family cache is authoritative ONLY for known families.
        # Generic is intentionally NOT family-cached: each template is learned separately
        # so novelty gate and quarantine can work for truly unseen formats (e.g., XML).
        is_known_family = family in KNOWN_FAMILIES
        rule = parser.get_family_rule(family) if is_known_family else None

        tier_result = {"kind": "family" if rule else "unknown", "template": None, "cluster_id": None, "gate": {}, "family": family}
        mode = "Cached"
        features = None

        if rule:
            # Fast path: known family already learned, zero LLM, zero Drain mining
            mode = "Cached"
        else:
            # Family miss: compute detailed fingerprint
            features = parser.fingerprint(log)
            fp_str, cached_rule = parser.find_cached_rule(features)

            if cached_rule:
                # Fingerprint cache hit (legacy or previous variation)
                rule = cached_rule
                mode = "Cached"
                # Promote to family cache if known family
                if is_known_family:
                    parser.store_family_rule(family, rule)
                tier_result = {"kind": "fingerprint", "template": None, "cluster_id": None, "gate": {}, "family": family}
            else:
                # No fingerprint: consult Drain template tier
                tier_result = template_tier.decide(log, GATE)
                tier_result["family"] = family

                if tier_result["kind"] == "rule":
                    rule = tier_result["rule"]
                    # Unify to Cached for deterministic UI, but keep template_rule_hits stat
                    mode = "Cached"
                    parser.store_rule(features, rule)
                    if is_known_family:
                        parser.store_family_rule(family, rule)
                elif tier_result["kind"] == "quarantined":
                    mode = "Quarantined"
                    rule = discovery_engine.run_inference(log, features, force_heuristic=True)
                    # Do NOT store in family cache while quarantined
                else:
                    mode = "Discovery"
                    rule = discovery_engine.run_inference(log, features)
                    parser.store_rule(features, rule)
                    if is_known_family:
                        parser.store_family_rule(family, rule)
                    if tier_result.get("template"):
                        template_tier.learn_rule(
                            tier_result["template"], rule, tier_result["cluster_id"]
                        )

        parsed = parser.parse_with_rule(log, rule)
        normalized = normalizer.normalize(parsed, raw_log=log)

        latency_ms = round((time.perf_counter() - start_time) * 1000, 2)

        resp = {
            "mode": mode,
            "format": rule.get("signature", "Unknown Signature"),
            "family": family,
            "inferred_by": rule.get("inferred_by"),
            "llm_error": rule.get("llm_error") if mode in ("Discovery", "Quarantined") else None,
            "latency_ms": latency_ms,
            "extracted_fields": parsed.get("parsed_fields", {}),
            "normalized": normalized,
            "template": (tier_result.get("template") or "")[:300] or None,
            "cluster_id": tier_result.get("cluster_id"),
        }
        gate_info = tier_result.get("gate") or {}
        if gate_info.get("loaded"):
            resp["gate"] = {
                "novel": gate_info.get("novel"),
                "distance": gate_info.get("distance"),
                "family_guess": gate_info.get("family_guess"),
            }
        if tier_result.get("kind") == "quarantined":
            resp["quarantine"] = {
                "count": tier_result.get("quarantine_count"),
                "graduate_after": tier_result.get("graduate_after"),
            }
        return resp
    except Exception as e:
        logging.exception("Failed to process record")
        return {
            "mode": "Error",
            "format": "n/a",
            "family": "unknown",
            "inferred_by": None,
            "latency_ms": round((time.perf_counter() - start_time) * 1000, 2),
            "extracted_fields": {},
            "normalized": normalizer.empty(log),
            "error": f"{type(e).__name__}: {str(e)}"
        }

@app.post("/api/logs/ingest")
def ingest_logs(batch: LogBatch, request: Request):
    _require_ingest_key(request)
    buffered_logs = buffer_lines(batch.logs)
    results = [process_record(log) for log in buffered_logs]
    return {"processed_logs": results}

@app.get("/api/logs/cache")
def get_cache():
    return {
        "cache": parser.snapshot_cache(),
        "family_cache": parser.snapshot_family_cache(),
    }

@app.get("/api/logs/templates")
def get_templates():
    return template_tier.templates_view()

@app.get("/api/logs/quarantine")
def get_quarantine():
    return template_tier.quarantine_view()
