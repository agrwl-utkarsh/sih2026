import os
import time
import json
import logging
import re
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, StringConstraints
from typing import List
from typing_extensions import Annotated
from pipeline.format_detector import DiscoveryEngine, DEFAULT_MODEL
from pipeline.parser import UniversalParser
from pipeline.normalizer import Normalizer

app = FastAPI(title="Format-Agnostic Two-Tier Log Pipeline (SIH26)")

static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

@app.get("/")
def read_index():
    return FileResponse(str(static_dir / "index.html"))

@app.get("/api/health")
def health():
    return {
        "llm_configured": bool(os.environ.get("GEMINI_API_KEY")),
        "model": os.environ.get("DISCOVERY_MODEL", DEFAULT_MODEL)
    }

discovery_engine = DiscoveryEngine()
parser = UniversalParser()
normalizer = Normalizer()

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
        
        # update JSON depth (crude but follows instructions)
        # track "{" depth outside strings; if a line leaves a string open, stop treating the record as JSON
        # This is very complex to do perfectly with regex, we'll do a simple count of { and }
        
        if current_entry:
            if json_depth > 0:
                continues = True
            elif line.startswith(' ') or line.startswith('\t'):
                continues = True
            elif line.startswith('Caused by:'):
                continues = True
            elif in_traceback and EXC_PATTERN.match(line):
                continues = True
                in_traceback = False # Exception line usually ends the traceback block
                
        if continues and len(current_entry) < 500:
            current_entry.append(line)
        else:
            if current_entry:
                buffered.append('\n'.join(current_entry))
            current_entry = [line]
            json_depth = 0
            in_string = False
            in_traceback = False
            
        # Update state for next line based on the current line being added
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
            
        if "Traceback (most recent call last):" in line:
            in_traceback = True

    if current_entry:
        buffered.append('\n'.join(current_entry))
        
    return buffered

def process_record(log: str) -> dict:
    start_time = time.perf_counter()
    try:
        features = parser.fingerprint(log)
        fp_str, rule = parser.find_cached_rule(features)
        
        if fp_str and rule:
            mode = "Cached"
        else:
            mode = "Discovery"
            rule = discovery_engine.run_inference(log, features)
            parser.store_rule(features, rule)
            
        parsed = parser.parse_with_rule(log, rule)
        normalized = normalizer.normalize(parsed, raw_log=log)
        
        latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
        
        return {
            "mode": mode,
            "format": rule.get("signature", "Unknown Signature"),
            "inferred_by": rule.get("inferred_by"),
            "latency_ms": latency_ms,
            "extracted_fields": parsed.get("parsed_fields", {}),
            "normalized": normalized
        }
    except Exception as e:
        logging.exception("Failed to process record")
        return {
            "mode": "Error",
            "format": "n/a",
            "inferred_by": None,
            "latency_ms": round((time.perf_counter() - start_time) * 1000, 2),
            "extracted_fields": {},
            "normalized": normalizer.empty(log),
            "error": f"{type(e).__name__}: {str(e)}"
        }

@app.post("/api/logs/ingest")
def ingest_logs(batch: LogBatch):
    buffered_logs = buffer_lines(batch.logs)
    results = [process_record(log) for log in buffered_logs]
    return {"processed_logs": results}

@app.get("/api/logs/cache")
def get_cache():
    return {"cache": parser.snapshot_cache()}
