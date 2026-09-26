import os, time, logging, re
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, StringConstraints
from typing import List
from typing_extensions import Annotated
from pipeline.format_detector import DiscoveryEngine, DEFAULT_MODEL, _resolve_gemini_model, _resolve_groq_model, _resolve_anthropic_model
from pipeline.parser import UniversalParser, KNOWN_FAMILIES
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

def _require_ingest_key(request: Request):
    exp = os.environ.get("INGEST_API_KEY")
    if exp and request.headers.get("x-ingest-key","") != exp:
        raise HTTPException(status_code=401, detail="Invalid or missing x-ingest-key header")

def _active_provider():
    raw = os.environ.get("DISCOVERY_MODEL", DEFAULT_MODEL)
    has_gem = bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
    has_groq = bool(os.environ.get("GROQ_API_KEY"))
    has_anth = bool(os.environ.get("ANTHROPIC_API_KEY"))
    skip = bool(getattr(discovery_engine, "_skip_gemini", False))
    if has_gem and not skip: return "gemini", _resolve_gemini_model(raw), raw, has_groq, skip
    if has_groq: return "groq", _resolve_groq_model(), raw, has_groq, skip
    if has_anth: return "anthropic", _resolve_anthropic_model(), raw, has_groq, skip
    if has_gem: return "gemini", _resolve_gemini_model(raw), raw, has_groq, skip
    return None, _resolve_gemini_model(raw), raw, has_groq, skip

@app.get("/api/health")
def health(check_live: bool = False):
    prov, model, raw_model, has_groq, skip = _active_provider()
    try:
        fam = parser.snapshot_family_cache()
        fam_stats = {"families_learned": len(fam), "families": list(fam.keys())}
    except Exception:
        fam_stats = {"families_learned":0,"families":[]}
    resp = {
        "status":"healthy",
        "llm_configured": bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or os.environ.get("GROQ_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")),
        "provider": prov, "model": model, "raw_model": raw_model,
        "gemini_skipped": skip, "has_groq": has_groq,
        "template_tier": {"drain3_available": not template_tier.disabled, "enforce_mode": template_tier.enforce, "rule_backend": template_tier.rule_backend(), "stats": dict(template_tier.stats)},
        "format_gate": GATE.info, "family_cache": fam_stats,
        "ingest_auth": bool(os.environ.get("INGEST_API_KEY")),
    }
    if check_live:
        resp["live_check"]=discovery_engine.check_llm()
    return resp

@app.get("/api/health/llm")
def health_llm():
    return discovery_engine.check_llm()

class LogBatch(BaseModel):
    logs: Annotated[List[Annotated[str, StringConstraints(max_length=10000)]], Field(max_length=1000)]

EXC_RE = re.compile(r'^[A-Za-z_][\w.]*(Error|Exception|Exit|Interrupt|Warning)\b')

def buffer_lines(lines: List[str]) -> List[str]:
    if not lines: return []
    buf, cur, depth, in_str, in_tb = [], [], 0, False, False
    for line in lines:
        if not line.strip(): continue
        cont = False
        if cur:
            if depth>0: cont=True
            elif line.startswith((' ','\t')): cont=True
            elif line.startswith(('Caused by:','... ')): cont=True
            elif line.strip().startswith('at ') and ('(' in line or '.' in line): cont=True
            elif in_tb and EXC_RE.match(line):
                cont=True; in_tb=False
        if cont and len(cur)<500:
            cur.append(line)
        else:
            if cur: buf.append('\n'.join(cur))
            cur, depth, in_str, in_tb = [line], 0, False, False

        i=0
        while i < len(line):
            c=line[i]
            if in_str:
                if c=='\\': i+=1
                elif c=='"': in_str=False
            else:
                if c=='"': in_str=True
                elif c=='{': depth+=1
                elif c=='}': depth-=1
            i+=1
        if depth<0: depth=0
        if in_str: depth=0; in_str=False
        if "Traceback (most recent call last):" in line or "Exception in thread" in line:
            in_tb=True
    if cur: buf.append('\n'.join(cur))
    return buf

def process_record(log: str) -> dict:
    t0=time.perf_counter()
    try:
        fam=parser.detect_family(log)
        is_known=fam in KNOWN_FAMILIES
        rule=parser.get_family_rule(fam) if is_known else None
        tier={"kind":"family" if rule else "unknown","template":None,"cluster_id":None,"gate":{},"family":fam}
        mode="Cached"; feat=None

        if not rule:
            feat=parser.fingerprint(log)
            _, cached=parser.find_cached_rule(feat)
            if cached:
                rule=cached
                if is_known: parser.store_family_rule(fam, rule)
                tier={"kind":"fingerprint","template":None,"cluster_id":None,"gate":{},"family":fam}
            else:
                tier=template_tier.decide(log, GATE)
                tier["family"]=fam
                if tier["kind"]=="rule":
                    rule=tier["rule"]
                    parser.store_rule(feat, rule)
                    if is_known: parser.store_family_rule(fam, rule)
                elif tier["kind"]=="quarantined":
                    mode="Quarantined"
                    rule=discovery_engine.run_inference(log, feat, force_heuristic=True)
                else:
                    mode="Discovery"
                    rule=discovery_engine.run_inference(log, feat)
                    parser.store_rule(feat, rule)
                    if is_known: parser.store_family_rule(fam, rule)
                    if tier.get("template"):
                        template_tier.learn_rule(tier["template"], rule, tier["cluster_id"])

        parsed=parser.parse_with_rule(log, rule)
        norm=normalizer.normalize(parsed, raw_log=log)
        lat=round((time.perf_counter()-t0)*1000,2)
        resp={"mode":mode,"format":rule.get("signature","Unknown Signature"),"family":fam,"inferred_by":rule.get("inferred_by"),"llm_error":rule.get("llm_error") if mode in ("Discovery","Quarantined") else None,"latency_ms":lat,"extracted_fields":parsed.get("parsed_fields",{}),"normalized":norm,"template":(tier.get("template") or "")[:300] or None,"cluster_id":tier.get("cluster_id")}
        gi=tier.get("gate") or {}
        if gi.get("loaded"):
            resp["gate"]={"novel":gi.get("novel"),"distance":gi.get("distance"),"family_guess":gi.get("family_guess")}
        if tier.get("kind")=="quarantined":
            resp["quarantine"]={"count":tier.get("quarantine_count"),"graduate_after":tier.get("graduate_after")}
        return resp
    except Exception as e:
        logging.exception("Failed to process record")
        return {"mode":"Error","format":"n/a","family":"unknown","inferred_by":None,"latency_ms":round((time.perf_counter()-t0)*1000,2),"extracted_fields":{},"normalized":normalizer.empty(log),"error":f"{type(e).__name__}: {str(e)}"}

@app.post("/api/logs/ingest")
def ingest_logs(batch: LogBatch, request: Request):
    _require_ingest_key(request)
    return {"processed_logs": [process_record(l) for l in buffer_lines(batch.logs)]}

@app.get("/api/logs/cache")
def get_cache():
    return {"cache": parser.snapshot_cache(), "family_cache": parser.snapshot_family_cache()}

@app.get("/api/logs/templates")
def get_templates():
    return template_tier.templates_view()

@app.get("/api/logs/quarantine")
def get_quarantine():
    return template_tier.quarantine_view()
