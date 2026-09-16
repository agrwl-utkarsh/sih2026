import json
import re
import dateutil.parser
import warnings

class UniversalParser:
    def __init__(self):
        self.cache = {}
        
        # Timestamp regexes in order of precision/likelihood
        self.ts_patterns = [
            # ISO-8601 full
            r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?',
            # YYYY-MM-DD HH:MM:SS (with optional milliseconds)
            r'^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}(?:\.\d+)?',
            # Slash-delimited dates MM/DD/YYYY HH:MM:SS or YYYY/MM/DD
            r'^\d{2,4}/\d{2}/\d{2,4}\s+\d{2}:\d{2}:\d{2}',
            # Syslog style Mon DD HH:MM:SS
            r'^[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}',
            # Unix epoch (10 or 13 digits)
            r'^\d{10,13}\b'
        ]

    def fingerprint(self, log_entry: str) -> dict:
        s = log_entry.strip()
        is_json = False
        if s.startswith('{') and s.endswith('}'):
            try: 
                json.loads(s.replace('\\"', '"'))
                is_json = True
            except: 
                pass
                
        features = {
            "is_json": is_json,
            "tok_count": len(s.split()),
            "pipe_count": s.count('|'),
            "comma_count": s.count(','),
            "eq_count": s.count('='),
            "colon_count": s.count(':'),
            "bracket_count": s.count('[') + s.count('('),
            "len_bucket": len(s) // 50
        }
        return features

    def find_cached_rule(self, features: dict):
        for fp_str, rule in self.cache.items():
            cached_feat = json.loads(fp_str)
            if cached_feat["is_json"] and features["is_json"]:
                return fp_str, rule
            if not features["is_json"]:
                if (cached_feat["pipe_count"] == features["pipe_count"] and
                    cached_feat["comma_count"] == features["comma_count"] and
                    cached_feat["eq_count"] == features["eq_count"] and
                    cached_feat["bracket_count"] == features["bracket_count"] and
                    abs(cached_feat["tok_count"] - features["tok_count"]) <= 4):
                    return fp_str, rule
        return None, None

    def store_rule(self, features: dict, rule: dict):
        fp_str = json.dumps(features, sort_keys=True)
        self.cache[fp_str] = rule

    def detect_timestamp(self, line: str):
        line = line.strip()
        # 1. Try fixed patterns
        for pattern in self.ts_patterns:
            match = re.search(pattern, line)
            if match and match.start() == 0:
                matched_str = match.group(0)
                remainder = line[len(matched_str):].lstrip(' -:,|')
                # Parse to ISO
                try:
                    # handle epoch
                    if matched_str.isdigit():
                        import datetime
                        ts = int(matched_str)
                        if len(matched_str) == 13: ts = ts / 1000.0
                        iso = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).isoformat()
                    else:
                        iso = dateutil.parser.parse(matched_str).isoformat()
                    return iso, matched_str, remainder
                except:
                    pass
        
        # 2. Flexible fallback (only check first 30 chars for safety)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                # Look for something that dateutil can parse at the very beginning
                tokens = line.split()
                for i in range(1, min(4, len(tokens)+1)):
                    candidate = " ".join(tokens[:i])
                    try:
                        dt = dateutil.parser.parse(candidate, fuzzy=False)
                        remainder = line[len(candidate):].lstrip(' -:,|')
                        return dt.isoformat(), candidate, remainder
                    except:
                        pass
        except:
            pass
            
        return None, None, line

    def detect_severity(self, line: str):
        # Look for severity at start of remainder
        match = re.search(r'^(DEBUG|INFO|WARN|WARNING|ERROR|CRITICAL|FATAL|TRACE)\b', line, re.IGNORECASE)
        if match:
            matched_str = match.group(0)
            remainder = line[len(matched_str):].lstrip(' -:,|')
            return matched_str.upper(), remainder
            
        # Check syslog prefix <134>
        match = re.search(r'^<(\d{1,3})>', line)
        if match:
            matched_str = match.group(0)
            remainder = line[len(matched_str):].lstrip(' -:,|')
            val = int(match.group(1))
            sev_num = val & 7
            sevs = {0:"CRITICAL", 1:"CRITICAL", 2:"CRITICAL", 3:"ERROR", 4:"WARNING", 5:"INFO", 6:"INFO", 7:"DEBUG"}
            return sevs.get(sev_num, "UNKNOWN"), remainder
            
        return None, line

    def detect_brackets(self, line: str):
        match = re.search(r'^\[([^\]]+)\]|^\(([^)]+)\)', line)
        if match:
            matched_str = match.group(0)
            content = match.group(1) or match.group(2)
            remainder = line[len(matched_str):].lstrip(' -:,|')
            return content, remainder
        return None, line

    def parse_with_rule(self, log_entry: str, rule: dict) -> dict:
        result = {"parsed_fields": {}, "extra": {}}
        method = rule.get("method")
        
        if method == "json":
            result["parsed_fields"] = json.loads(log_entry.replace('\\"', '"'))
            
        elif method == "compositional":
            rem = log_entry.strip()
            
            # 1. Timestamp zone
            ts_iso, ts_raw, rem = self.detect_timestamp(rem)
            if ts_iso: result["parsed_fields"]["timestamp"] = ts_iso
            
            # 2. Severity zone
            sev, rem = self.detect_severity(rem)
            if sev: result["parsed_fields"]["severity"] = sev
            
            # 3. Bracket zone (e.g. thread/context)
            ctx, rem = self.detect_brackets(rem)
            if ctx: result["extra"]["context"] = ctx
            
            # 4. Message (remainder)
            if rem: result["parsed_fields"]["message"] = rem.strip()
            
            # 5. Key/Value Global Scan (over original log_entry)
            # Find key=value or key:value (if the value doesn't have spaces or if it's quoted)
            kv_pairs = re.findall(r'([a-zA-Z0-9_-]+)=([^ ,;]+)', log_entry)
            for k, v in kv_pairs:
                result["extra"][k] = v
                
        elif method == "delimiter":
            delim = rule.get("delimiter")
            parts = log_entry.split(delim)
            for i, p in enumerate(parts):
                result["parsed_fields"][f"field_{i}"] = p.strip()
                
        else:
            result["parsed_fields"]["raw_message"] = log_entry

        return result
