import json, re
from .timeutil import parse_timestamp

ALIASES = {
    "timestamp": ["timestamp","@timestamp","ts","time","datetime","date","t","eventtime","devtime","time_local","log_time","logged_at"],
    "severity": ["severity","level","lvl","loglevel","log_level","levelname","log.level","priority","syslog_severity","status_code_severity","s"],
    "message": ["message","msg","log","text","body","payload","raw_log","description","details","reason"],
    "source": ["source","host","hostname","service","app","application","logger","logger_name","name","component","program","caller","c","device_vendor"],
    "event_type": ["event_type","event","type","action","operation","category","method","command","event_class_id","msg_id"]
}
REV_ALIAS = {a.lower(): k for k, lst in ALIASES.items() for a in lst}

SEV_MAP = {
    "trace":"debug","debug":"debug","dbg":"debug","d":"debug",
    "info":"info","inform":"info","information":"info","informational":"info","notice":"info","note":"info","system":"info","successful":"info","ok":"info","i":"info",
    "warning":"warning","warn":"warning","w":"warning",
    "error":"error","err":"error","exception":"error","fail":"error","failure":"error","bad":"error","e":"error",
    "critical":"critical","crit":"critical","fatal":"critical","severe":"critical","emerg":"critical","emergency":"critical","alert":"critical","panic":"critical","f":"critical"
}
SEV_NUM = {0:"critical",1:"critical",2:"critical",3:"error",4:"warning",5:"info",6:"info",7:"debug"}

EVENT_PATTERNS = [
    (re.compile(r'\b(?:failed\s+password|authentication\s+fail(?:ed|ure)|invalid\s+credentials|unauthorized|permission\s+denied|access\s+denied)\b', re.I), "auth_failure"),
    (re.compile(r'\b(?:accepted\s+password|session\s+opened|login\s+successful|authentication\s+succeeded)\b', re.I), "auth_success"),
    (re.compile(r'\b(?:SELECT|INSERT|UPDATE|DELETE|FROM|WHERE)\b|statement:\s+|duration:\s+\d+\.\d+\s+ms'), "db_query"),
    (re.compile(r'\b(?:connection\s+(?:refused|reset|timeout|failed|closed)|failed\s+to\s+connect|network\s+unreachable)\b', re.I), "connection_error"),
    (re.compile(r'\b(?:started|shutting\s+down|shutdown|ready\s+for\s+connections|ready\s+to\s+accept|listening\s+on|server\s+startup)\b', re.I), "service_lifecycle"),
    (re.compile(r'\b(?:exception|traceback|fatal\s+error|panic:)\b', re.I), "exception"),
]

class Normalizer:
    def _canon_sev(self, v):
        if v is None or isinstance(v, (list, dict, bool)):
            return "unknown", v
        try:
            n = int(v)
            return SEV_NUM.get(n, "unknown"), None if n in SEV_NUM else v
        except Exception:
            pass
        s = str(v).lower().strip('[]() ')
        return (SEV_MAP[s], None) if s in SEV_MAP else ("unknown", v)

    def _infer_event(self, msg, extra):
        if extra.get("http_method") or extra.get("http_status"):
            return "http_request"
        m = msg or ""
        for pat, typ in EVENT_PATTERNS:
            if pat.search(m):
                return typ
        return "unknown"

    def normalize(self, parsed_data, raw_log):
        fields = parsed_data.get("parsed_fields", {})
        extra_in = parsed_data.get("extra", {})
        extracted, extra = {}, {}

        for src in (fields, extra_in):
            for k, v in src.items():
                if k == "raw_message" or v in (None, ""):
                    continue
                can = REV_ALIAS.get(k.lower())
                if can and can not in extracted:
                    extracted[can] = v
                else:
                    extra[k if not can else k] = v
                    if can and can in extracted:
                        extra[k] = v

        ts_raw = extracted.get("timestamp")
        ts_parsed = parse_timestamp(ts_raw)
        final_ts = ts_parsed
        if not ts_parsed and ts_raw is not None:
            extra["timestamp_raw"] = ts_raw

        sev_raw = extracted.get("severity")
        final_sev, unmapped = self._canon_sev(sev_raw)
        if unmapped is not None and sev_raw is not None:
            extra["severity_raw"] = unmapped

        msg_raw = extracted.get("message")
        final_msg = json.dumps(msg_raw) if msg_raw is not None and not isinstance(msg_raw, str) else msg_raw

        src_raw = extracted.get("source")
        if src_raw is not None:
            final_src = str(src_raw)
        else:
            final_src = next((str(extra[k]) for k in ("program","logger","app_name","host","hostname","device_vendor","client","ip") if extra.get(k)), "unknown")

        event_raw = extracted.get("event_type")
        final_event = str(event_raw) if event_raw is not None else self._infer_event(final_msg or raw_log, extra)

        if final_sev == "unknown":
            if "http_status" in extra:
                try:
                    code = int(extra["http_status"])
                    final_sev = "error" if code >= 500 else "warning" if code >= 400 else "info" if 100 <= code < 400 else "unknown"
                except Exception:
                    pass
            elif final_event in ("auth_failure","connection_error","exception"):
                final_sev = "warning" if final_event == "auth_failure" else "error"

        return {
            "timestamp": final_ts,
            "source": final_src,
            "event_type": final_event,
            "severity": final_sev,
            "message": final_msg if final_msg is not None else raw_log.strip(),
            "raw": raw_log,
            "extra": extra
        }

    def empty(self, raw_log):
        return {"timestamp": None, "source": "unknown", "event_type": "unknown", "severity": "unknown", "message": None, "raw": raw_log, "extra": {}}
