import time
import json
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os
from pydantic import BaseModel
from typing import List
import re
from pipeline.format_detector import HeuristicDiscoveryEngine
from pipeline.parser import UniversalParser
from pipeline.normalizer import Normalizer

app = FastAPI(title="Format-Agnostic Two-Tier Log Pipeline (SIH26)")

# Mount the static directory for the frontend
static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
async def read_index():
    return FileResponse(os.path.join(static_dir, "index.html"))

discovery_engine = HeuristicDiscoveryEngine()
parser = UniversalParser()
normalizer = Normalizer()

class LogBatch(BaseModel):
    logs: List[str]

def buffer_lines(lines: List[str]) -> List[str]:
    """Merge continuation lines (stack traces, pretty-print JSON) into single log records."""
    if not lines:
        return []
        
    buffered = []
    current_entry = []
    in_traceback = False
    in_json = False
    
    new_log_pattern = re.compile(r'^([\{\[]|\d|<|[A-Z][a-z]{2}\s+\d|DEBUG|INFO|WARN|ERROR|CRITICAL|FATAL|TRACE)')
    
    for line in lines:
        stripped = line.strip()
        is_new = False
        
        if not current_entry:
            is_new = True
        else:
            if in_json:
                is_new = False
                if stripped == '}' or stripped == '},':
                    in_json = False
            elif in_traceback:
                if line.startswith(' ') or line.startswith('\t'):
                    is_new = False
                elif re.match(r'^\w+:', line):
                    is_new = False
                    in_traceback = False
                else:
                    is_new = True
                    in_traceback = False
            else:
                if line.startswith(' ') or line.startswith('\t'):
                    is_new = False
                elif new_log_pattern.match(line):
                    is_new = True
                else:
                    is_new = True
                    
        if is_new and current_entry:
            buffered.append('\n'.join(current_entry))
            current_entry = [line]
            if stripped == '{':
                in_json = True
            if line.startswith('Traceback '):
                in_traceback = True
        else:
            if not current_entry:
                current_entry = [line]
                if stripped == '{':
                    in_json = True
                if line.startswith('Traceback '):
                    in_traceback = True
            else:
                current_entry.append(line)
            
    if current_entry:
        buffered.append('\n'.join(current_entry))
        
    return buffered

@app.post("/api/logs/ingest")
async def ingest_logs(batch: LogBatch):
    results = []
    
    # 1. Edge Case: Multi-line handling (do not shred stack traces)
    buffered_logs = buffer_lines(batch.logs)
    
    for log in buffered_logs:
        if not log.strip():
            continue # Edge Case: Skip empty lines silently
            
        start_time = time.time()
        
        try:
            # Tier 1: Structural Fingerprinting (Runs on EVERY line)
            features = parser.fingerprint(log)
            
            # Tier 2b: Execution (Check Cache by nearest fingerprint match)
            fp_str, rule = parser.find_cached_rule(features)
            
            if fp_str and rule:
                mode = "Cached"
                # Execution Path (Fast)
                parsed = parser.parse_with_rule(log, rule)
            else:
                # Tier 2a: Discovery (Run LLM/Heuristic Fallback)
                mode = "Discovery"
                rule = discovery_engine.run_inference(log, features)
                
                # Cache the new rule dynamically
                parser.store_rule(features, rule)
                
                # Execute it
                parsed = parser.parse_with_rule(log, rule)
                
            # Tier 3: Normalization
            normalized = normalizer.normalize(parsed, raw_log=log)
            
            latency_ms = round((time.time() - start_time) * 1000, 2)
            
            results.append({
                "mode": mode,
                "format": rule.get("signature", "Unknown Signature"),
                "latency_ms": latency_ms,
                "extracted_fields": parsed.get("parsed_fields", {}),
                "normalized": normalized
            })
        except Exception as e:
            results.append({
                "mode": "Error",
                "format": "Processing Error",
                "latency_ms": round((time.time() - start_time) * 1000, 2),
                "extracted_fields": {},
                "normalized": {"raw": log, "error": str(e)}
            })
        
    return {"processed_logs": results}

@app.get("/api/logs/cache")
async def get_cache():
    """Cache Inspector endpoint"""
    inspector_data = []
    for fp, rule in parser.cache.items():
        inspector_data.append({
            "fingerprint_features": json.loads(fp),
            "inferred_rule": rule
        })
    return {"cache": inspector_data}
