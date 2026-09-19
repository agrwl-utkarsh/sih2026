import json
import re
from .timeutil import parse_timestamp

class Normalizer:
    def __init__(self):
        self.aliases = {
            "timestamp": ["timestamp", "@timestamp", "ts", "time", "datetime", "date", "t", "eventtime", "devtime", "time_local", "log_time", "logged_at"],
            "severity": ["severity", "level", "lvl", "loglevel", "log_level", "levelname", "log.level", "priority", "syslog_severity", "status_code_severity", "s"],
            "message": ["message", "msg", "log", "text", "body", "payload", "raw_log", "description", "details", "reason"],
            "source": ["source", "host", "hostname", "service", "app", "application", "logger", "logger_name", "name", "component", "program", "caller", "c", "device_vendor"],
            "event_type": ["event_type", "event", "type", "action", "operation", "category", "method", "command", "event_class_id", "msg_id"]
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
            "dbg": "debug",
            "d": "debug",
            "info": "info",
            "inform": "info",
            "information": "info",
            "informational": "info",
            "notice": "info",
            "note": "info",
            "system": "info",
            "successful": "info",
            "ok": "info",
            "i": "info",
            "warning": "warning",
            "warn": "warning",
            "w": "warning",
            "error": "error",
            "err": "error",
            "exception": "error",
            "fail": "error",
            "failure": "error",
            "bad": "error",
            "e": "error",
            "critical": "critical",
            "crit": "critical",
            "fatal": "critical",
            "severe": "critical",
            "emerg": "critical",
            "emergency": "critical",
            "alert": "critical",
            "panic": "critical",
            "f": "critical"
        }
        if s in mapping:
            return mapping[s], None
        return "unknown", value

    def _infer_event_type(self, message: str, extra: dict) -> str:
        if extra.get("http_method") or extra.get("http_status"):
            return "http_request"
            
        msg = message or ""
        if re.search(r'\b(?:failed\s+password|authentication\s+fail(?:ed|ure)|invalid\s+credentials|unauthorized|permission\s+denied|access\s+denied)\b', msg, re.I):
            return "auth_failure"
        if re.search(r'\b(?:accepted\s+password|session\s+opened|login\s+successful|authentication\s+succeeded)\b', msg, re.I):
            return "auth_success"
        if re.search(r'\b(?:SELECT|INSERT|UPDATE|DELETE|FROM|WHERE)\b|statement:\s+|duration:\s+\d+\.\d+\s+ms', msg):
            return "db_query"
        if re.search(r'\b(?:connection\s+(?:refused|reset|timeout|failed|closed)|failed\s+to\s+connect|network\s+unreachable)\b', msg, re.I):
            return "connection_error"
        if re.search(r'\b(?:started|shutting\s+down|shutdown|ready\s+for\s+connections|ready\s+to\s+accept|listening\s+on|server\s+startup)\b', msg, re.I):
            return "service_lifecycle"
        if re.search(r'\b(?:exception|traceback|fatal\s+error|panic:)\b', msg, re.I):
            return "exception"
            
        return "unknown"

    def normalize(self, parsed_data: dict, raw_log: str) -> dict:
        fields = parsed_data.get("parsed_fields", {})
        extra_in = parsed_data.get("extra", {})
        
        extracted = {}
        extra = {}
        
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
                    extra[k] = v
                else:
                    extra[k] = v
                    
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
            
        # Source
        src_raw = extracted.get("source")
        if src_raw is not None:
            final_src = str(src_raw)
        else:
            # Fallback to smart extra keys if available
            for candidate_key in ["program", "logger", "app_name", "host", "hostname", "device_vendor", "client", "ip"]:
                if candidate_key in extra and extra[candidate_key]:
                    final_src = str(extra[candidate_key])
                    break
            else:
                final_src = "unknown"
        
        # Event Type
        event_raw = extracted.get("event_type")
        if event_raw is not None:
            final_event = str(event_raw)
        else:
            final_event = self._infer_event_type(final_msg or raw_log, extra)

        # Smart severity inference if still unknown
        if final_sev == "unknown":
            if "http_status" in extra:
                try:
                    code = int(extra["http_status"])
                    if code >= 500: final_sev = "error"
                    elif code >= 400: final_sev = "warning"
                    elif 100 <= code < 400: final_sev = "info"
                except Exception:
                    pass
            elif final_event in ("auth_failure", "connection_error", "exception"):
                final_sev = "error" if final_event != "auth_failure" else "warning"

        return {
            "timestamp": final_ts,
            "source": final_src,
            "event_type": final_event,
            "severity": final_sev,
            "message": final_msg if final_msg is not None else raw_log.strip(),
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
