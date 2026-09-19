import json
from .timeutil import parse_timestamp

class Normalizer:
    def __init__(self):
        self.aliases = {
            "timestamp": ["timestamp", "@timestamp", "ts", "time", "datetime", "date", "t"],
            "severity": ["severity", "level", "lvl", "loglevel", "log_level", "levelname"],
            "message": ["message", "msg", "log", "text", "body"],
            "source": ["source", "host", "hostname", "service", "app", "application", "logger"],
            "event_type": ["event_type", "event", "type"]
        }
        self.reverse_aliases = {}
        for canonical, aliases in self.aliases.items():
            for alias in aliases:
                self.reverse_aliases[alias.lower()] = canonical

    def _canonicalize_severity(self, value):
        if value is None or isinstance(value, (list, dict, bool)):
            return "unknown", value
            
        # Handle numeric
        try:
            num = int(value)
            if 0 <= num <= 2: return "critical", None
            if num == 3: return "error", None
            if num == 4: return "warning", None
            if 5 <= num <= 6: return "info", None
            if num == 7: return "debug", None
            return "unknown", value
        except:
            pass
            
        s = str(value).lower().strip('[]() ')
        
        mapping = {
            "trace": "debug",
            "debug": "debug",
            "info": "info",
            "notice": "info",
            "information": "info",
            "warning": "warning",
            "warn": "warning",
            "error": "error",
            "err": "error",
            "critical": "critical",
            "crit": "critical",
            "fatal": "critical",
            "severe": "critical",
            "emerg": "critical",
            "emergency": "critical",
            "alert": "critical"
        }
        if s in mapping:
            return mapping[s], None
        return "unknown", value

    def normalize(self, parsed_data: dict, raw_log: str) -> dict:
        fields = parsed_data.get("parsed_fields", {})
        extra_in = parsed_data.get("extra", {})
        
        extracted = {}
        extra = {}
        
        # Merge fields and extra_in to scan (without mutating)
        # We should only map fields if they are in parsed_fields or extra
        # but wait, parsed_fields and extra might have overlapping keys.
        # Usually we just scan both? The prompt says "Every field not consumed by an alias goes into extra (except raw_message)."
        
        consumed_keys = set()
        
        for source_dict in [fields, extra_in]:
            for k, v in source_dict.items():
                if k == "raw_message":
                    continue
                k_lower = k.lower()
                canonical = self.reverse_aliases.get(k_lower)
                
                if canonical and canonical not in extracted and v is not None and v != "":
                    extracted[canonical] = v
                    consumed_keys.add(k)
                elif canonical and canonical in extracted:
                    # Already consumed the first non-empty hit for this canonical
                    # So put this one in extra
                    extra[k] = v
                else:
                    extra[k] = v
                    
        # Apply rules
        # Timestamp
        ts_raw = extracted.get("timestamp")
        ts_parsed = parse_timestamp(ts_raw)
        if ts_parsed:
            final_ts = ts_parsed
        else:
            final_ts = None
            if ts_raw is not None:
                extra["timestamp_raw"] = ts_raw
                
        # Severity
        sev_raw = extracted.get("severity")
        final_sev, sev_unmapped = self._canonicalize_severity(sev_raw)
        if sev_unmapped is not None and sev_raw is not None:
            extra["severity_raw"] = sev_unmapped
            
        # Message
        msg_raw = extracted.get("message")
        if msg_raw is None:
            final_msg = None
        elif not isinstance(msg_raw, str):
            final_msg = json.dumps(msg_raw)
        else:
            final_msg = msg_raw
            
        # Source and Event Type
        src_raw = extracted.get("source")
        final_src = str(src_raw) if src_raw is not None else "unknown"
        
        event_raw = extracted.get("event_type")
        final_event = str(event_raw) if event_raw is not None else "unknown"

        return {
            "timestamp": final_ts,
            "source": final_src,
            "event_type": final_event,
            "severity": final_sev,
            "message": final_msg,
            "raw": raw_log,
            "extra": extra
        }

    def empty(self, raw_log: str) -> dict:
        return {
            "timestamp": None,
            "source": "unknown",
            "event_type": "unknown",
            "severity": "unknown",
            "message": None,
            "raw": raw_log,
            "extra": {}
        }
