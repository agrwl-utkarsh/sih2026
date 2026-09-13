import time
import json
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List
from pipeline.format_detector import LLMDiscoveryEngine
from pipeline.parser import UniversalParser
from pipeline.normalizer import Normalizer

app = FastAPI(title="Format-Agnostic Two-Tier Log Pipeline (SIH26)")

# Mount the static directory for the frontend
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def read_index():
    return FileResponse("static/index.html")

discovery_engine = LLMDiscoveryEngine()
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
    
    for line in lines:
        # If line starts with whitespace, it's definitely a continuation
        # Or if we're inside a JSON blob. For simplicity, just check whitespace start
        # A more robust check might look for timestamp shape at the beginning
        if line.startswith(' ') or line.startswith('\t'):
            if current_entry:
                current_entry.append(line)
            else:
                current_entry = [line]
        else:
            if current_entry:
                buffered.append('\n'.join(current_entry))
            current_entry = [line]
            
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
