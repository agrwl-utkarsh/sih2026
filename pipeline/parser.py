import json
import re
import warnings
import threading
import csv
import io
from .timeutil import parse_timestamp

class UniversalParser:
    def __init__(self):
        self.cache = {}
        self.cache_lock = threading.Lock()
        
        self.ts_patterns = [
            r'^\[?\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?\]?',
            r'^\[?\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}(?:\.\d+)?\]?',
            r'^\[?\d{2,4}/\d{2}/\d{2,4}\s+\d{2}:\d{2}:\d{2}\]?',
            r'^\[?[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}\]?',
            r'^\[?\d{4}-\d{2}-\d{2}\b\]?',
            r'^\[?\d{10,13}\b\]?'
        ]

        self.severity_words = [
            "CRITICAL", "WARNING", "EMERGENCY", "SEVERE", "NOTICE", "TRACE", 
            "DEBUG", "ERROR", "FATAL", "EMERG", "ALERT", "CRIT", "INFO", "WARN", "ERR"
        ]
        words_pipe = "|".join(self.severity_words)
        self.sev_pattern = re.compile(rf'\[?({words_pipe})\]?(?![A-Za-z0-9_])', re.IGNORECASE)
        self.date_fallback_pattern = re.compile(r'(\d{4}-\d{2}-\d{2}|\d{2,4}/\d{2}/\d{2,4}|[A-Z][a-z]{2}\s+\d{1,2})', re.IGNORECASE)

    def snapshot_cache(self):
        with self.cache_lock:
            return [{"fingerprint_features": json.loads(k), "inferred_rule": v} for k, v in self.cache.items()]

    def store_rule(self, features: dict, rule: dict):
        fp_str = json.dumps(features, sort_keys=True)
        with self.cache_lock:
            if fp_str not in self.cache:
                if len(self.cache) >= 500:
                    oldest_key = next(iter(self.cache))
                    del self.cache[oldest_key]
            self.cache[fp_str] = rule

    def looks_like_ts_or_sev(self, field: str) -> bool:
        field = field.strip()
        if not field:
            return False
        if parse_timestamp(field):
            return True
        if self.sev_pattern.match(field):
            return True
        return False

    def fingerprint(self, log_entry: str) -> dict:
        s = log_entry.strip()
        is_json = False
        if s.startswith('{') and s.endswith('}'):
            try: 
                parsed = json.loads(s)
                if isinstance(parsed, dict):
                    is_json = True
            except: 
                pass
                
        tok_count = len(s.split())
        pipe_count = s.count('|')
        comma_count = s.count(',')
        eq_count = s.count('=')
        bracket_count = s.count('[') + s.count('(')
        
        delim = None
        if not is_json:
            if pipe_count >= 2:
                delim = "|"
            elif comma_count >= 3:
                first_field = s.split(',', 1)[0]
                if tok_count == 1 or self.looks_like_ts_or_sev(first_field):
                    delim = ","
                    
        return {
            "is_json": is_json,
            "tok_count": tok_count,
            "pipe_count": pipe_count,
            "comma_count": comma_count,
            "eq_count": eq_count,
            "bracket_count": bracket_count,
            "delim": delim
        }

    def find_cached_rule(self, features: dict):
        best_match_fp = None
        best_match_rule = None
        best_diff = float('inf')

        with self.cache_lock:
            for fp_str, rule in self.cache.items():
                cached_feat = json.loads(fp_str)
                if cached_feat["is_json"] != features["is_json"]:
                    continue
                    
                if features["is_json"]:
                    if rule.get("method") == "json":
                        return fp_str, rule
                    continue
                    
                if cached_feat.get("delim") != features["delim"]:
                    continue
                    
                if (cached_feat["pipe_count"] == features["pipe_count"] and
                    cached_feat["comma_count"] == features["comma_count"] and
                    cached_feat["eq_count"] == features["eq_count"] and
                    cached_feat["bracket_count"] == features["bracket_count"]):
                    
                    diff = abs(cached_feat["tok_count"] - features["tok_count"])
                    if features["delim"] is not None:
                        if diff == 0:
                            return fp_str, rule
                    else:
                        if diff <= 4 and diff < best_diff:
                            best_diff = diff
                            best_match_fp = fp_str
                            best_match_rule = rule

        return best_match_fp, best_match_rule

    def detect_timestamp(self, line: str):
        line = line.strip()
        for i, pattern in enumerate(self.ts_patterns):
            match = re.search(pattern, line)
            if match and match.start() == 0:
                matched_str = match.group(0)
                clean_str = matched_str.strip('[]')
                iso = parse_timestamp(clean_str)
                if iso:
                    remainder = line[len(matched_str):].lstrip(' -:,|')
                    was_syslog = (i == 3)
                    remainder = line[len(matched_str):].lstrip(' -:,|')
                    return iso, was_syslog, remainder
                    
        tokens = line.split()
        for i in range(1, min(4, len(tokens)+1)):
            candidate = " ".join(tokens[:i])
            clean_cand = candidate.strip('[]')
            if self.date_fallback_pattern.search(clean_cand):
                iso = parse_timestamp(clean_cand)
                if iso:
                    remainder = line[len(candidate):].lstrip(' -:,|')
                    was_syslog = bool(re.search(r'^[A-Z][a-z]{2}\s+\d{1,2}', clean_cand))
                    remainder = line[len(matched_str):].lstrip(' -:,|')
                    return iso, was_syslog, remainder
        return None, False, line

    def parse_compositional(self, log_entry: str) -> dict:
        result = {"parsed_fields": {}, "extra": {}}
        rem = log_entry.strip()
        
        # Check Combined / Common Log Format (NCSA / Apache / Nginx)
        # e.g.: 192.168.1.100 - john [19/Sep/2026:13:24:00 +0000] "GET /index.html HTTP/1.1" 200 4321 "https://google.com" "Mozilla/5.0..."
        combined_match = re.match(
            r'^(\S+)\s+(\S+)\s+(\S+)\s+\[([\w:/]+\s+[+\-]\d{4})\]\s+"([^"]+)"\s+(\d{3})\s+(\S+)(?:\s+"([^"]*)"\s+"([^"]*)")?',
            rem
        )
        if combined_match:
            ip, ident, user, raw_ts, request, status, size, referer, agent = combined_match.groups()
            result["parsed_fields"]["source"] = ip
            ts_iso = parse_timestamp(raw_ts)
            if ts_iso:
                result["parsed_fields"]["timestamp"] = ts_iso
            result["parsed_fields"]["message"] = request
            result["parsed_fields"]["event_type"] = "http_request"
            
            # Map HTTP status to canonical severity
            try:
                status_int = int(status)
                result["extra"]["http_status"] = status_int
                if status_int >= 500:
                    result["parsed_fields"]["severity"] = "ERROR"
                elif status_int >= 400:
                    result["parsed_fields"]["severity"] = "WARNING"
                else:
                    result["parsed_fields"]["severity"] = "INFO"
            except ValueError:
                pass
                
            if ident and ident != "-":
                result["extra"]["ident"] = ident
            if user and user != "-":
                result["extra"]["user"] = user
            if size and size != "-":
                result["extra"]["bytes_sent"] = int(size) if size.isdigit() else size
            if referer and referer != "-":
                result["extra"]["referer"] = referer
            if agent and agent != "-":
                result["extra"]["user_agent"] = agent
                
            req_tokens = request.split()
            if len(req_tokens) >= 2:
                result["extra"]["http_method"] = req_tokens[0]
                result["extra"]["http_path"] = req_tokens[1]
                if len(req_tokens) >= 3:
                    result["extra"]["http_proto"] = req_tokens[2]
                    
            return result

        # 0. Syslog prefix
        match = re.search(r'^<(\d{1,3})>', rem)
        if match:
            matched_str = match.group(0)
            rem = rem[len(matched_str):].lstrip(' -:,|')
            val = int(match.group(1))
            sev_num = val & 7
            sevs = {0:"CRITICAL", 1:"CRITICAL", 2:"CRITICAL", 3:"ERROR", 4:"WARNING", 5:"INFO", 6:"INFO", 7:"DEBUG"}
            result["parsed_fields"]["severity"] = sevs.get(sev_num, "UNKNOWN")
            result["extra"]["facility"] = val >> 3

        # 1. Timestamp
        ts_iso, was_syslog, rem = self.detect_timestamp(rem)
        if ts_iso: 
            result["parsed_fields"]["timestamp"] = ts_iso
            
        # 2. Severity
        if "severity" not in result["parsed_fields"]:
            match = self.sev_pattern.search(rem)
            if match and match.start() == 0:
                matched_str = match.group(0)
                rem = rem[len(matched_str):].lstrip(' -:,|')
                result["parsed_fields"]["severity"] = match.group(1).upper()
                
        # 3. Syslog host/program
        if ts_iso and was_syslog:
            host_match = re.match(r'^([a-zA-Z0-9_-]+)\s+([a-zA-Z0-9_-]+)(?:\[(\d+)\])?:\s*', rem)
            if host_match:
                result["parsed_fields"]["source"] = host_match.group(1)
                result["extra"]["program"] = host_match.group(2)
                if host_match.group(3):
                    result["extra"]["pid"] = host_match.group(3)
                rem = rem[len(host_match.group(0)):]
                
        # 4. Context brackets
        match = re.search(r'^\[([^\]]+)\]|^\(([^)]+)\)', rem)
        if match:
            matched_str = match.group(0)
            content = match.group(1) or match.group(2)
            rem = rem[len(matched_str):].lstrip(' -:,|')
            result["extra"]["context"] = content
            
            if "severity" not in result["parsed_fields"]:
                sev_match = self.sev_pattern.search(rem)
                if sev_match and sev_match.start() == 0:
                    sev_str = sev_match.group(0)
                    rem = rem[len(sev_str):].lstrip(' -:,|')
                    result["parsed_fields"]["severity"] = sev_match.group(1).upper()

        # 5. Message
        if rem: 
            result["parsed_fields"]["message"] = rem.strip()
            
        # 6. KV scan
        kv_pattern = re.compile(r'([a-zA-Z0-9_-]+)=("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|[^ \t\n\r,;\]\}>\)&]+)')
        for k, v in kv_pattern.findall(log_entry):
            if v.startswith('"') and v.endswith('"'): v = v[1:-1]
            elif v.startswith("'") and v.endswith("'"): v = v[1:-1]
            result["extra"][k] = v

        return result

    def parse_with_rule(self, log_entry: str, rule: dict) -> dict:
        result = {"parsed_fields": {}, "extra": {}}
        method = rule.get("method")
        
        if method == "json":
            try:
                parsed = json.loads(log_entry)
                if isinstance(parsed, dict):
                    result["parsed_fields"] = parsed
                    return result
            except:
                pass
            method = "compositional"
            
        if method == "delimiter":
            delim = rule.get("delimiter")
            try:
                reader = csv.reader(io.StringIO(log_entry.strip()), delimiter=delim)
                parts = next(reader)
            except:
                parts = [p.strip() for p in log_entry.split(delim)]
                
            parts = [p.strip() for p in parts if p.strip()]
            
            ts_val = None
            sev_val = None
            rests = []
            
            for p in parts:
                if not ts_val:
                    iso = parse_timestamp(p)
                    if iso:
                        ts_val = iso
                        continue
                if not sev_val:
                    if self.sev_pattern.match(p) and len(p) <= 12:
                        sev_val = p.strip('[]').upper()
                        continue
                if '=' in p:
                    k, v = p.split('=', 1)
                    if ' ' not in k:
                        result["extra"][k.strip()] = v.strip()
                        continue
                rests.append(p)
                
            if not ts_val and not sev_val:
                for i, p in enumerate(parts):
                    result["parsed_fields"][f"field_{i}"] = p
                return result
                
            if ts_val: result["parsed_fields"]["timestamp"] = ts_val
            if sev_val: result["parsed_fields"]["severity"] = sev_val
            
            if rests:
                lengths = [len(r.split()) for r in rests]
                msg_idx = lengths.index(max(lengths))
                result["parsed_fields"]["message"] = rests[msg_idx]
                
                src_found = False
                for i, r in enumerate(rests):
                    if i != msg_idx:
                        if not src_found and len(r.split()) == 1:
                            result["parsed_fields"]["source"] = r
                            src_found = True
                        else:
                            result["extra"][f"field_{i}"] = r
                            
            return result

        if method == "compositional":
            return self.parse_compositional(log_entry)
            
        result["parsed_fields"]["raw_message"] = log_entry
        return result

