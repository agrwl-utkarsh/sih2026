import json
import re
import threading
import csv
import io
from .timeutil import parse_timestamp

def strip_ansi(s: str) -> str:
    return re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', s)

# ---------- Family definitions (deterministic, coarse) ----------
# Order matters: most specific first.
KNOWN_FAMILIES = {
    "json", "cef", "leef", "ncsa", "rfc5424", "rfc3164", "cri",
    "nginx_error", "python", "java", "postgres", "logfmt",
    "pipe", "csv", "semicolon", "tab"
}

FAMILY_PATTERNS = [
    ("json", re.compile(r'^\s*\{.*\}\s*$', re.DOTALL)),
    ("cef", re.compile(r'^CEF:')),
    ("leef", re.compile(r'^LEEF:')),
    ("ncsa", re.compile(r'\[\w+:/\s*[+\-]\d{4}\]\s+"[^"]+"\s+\d{3}')),
    ("rfc5424", re.compile(r'^<\d{1,3}>\d+\s+')),
    ("rfc3164", re.compile(r'^(?:<\d{1,3}>)?[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}\s+[a-zA-Z0-9_.-]+\s+[a-zA-Z0-9_./-]+(?:\[\d+\])?:\s*')),
    ("cri", re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+\-]\d{2}:?\d{2})\s+(?:stdout|stderr)\s+[FP]\s+')),
    ("nginx_error", re.compile(r'^\d{4}[/-]\d{2}[/-]\d{2}\s+\d{2}:\d{2}:\d{2}\s+\[[a-z]+\]\s+\d+#\d+:')),
    ("python", re.compile(r'^[A-Z]{3,8}:[a-zA-Z0-9_.]+:')),
    ("java", re.compile(r'(\[main\]\s+(?:[A-Z]{3,8}\s+)?[a-zA-Z0-9_.$]+|^\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}[,.]\d{3}\s+\d+\s+---\s+\[|^\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}[,.]\d{3}\s+(?:\[[^\]]+\]\s+)?[A-Z]{3,8}\s+)')),
    ("postgres", re.compile(r'^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:\s+[A-Z]{3,4})?\s+\[\d+\]\s+(?:[a-zA-Z0-9_.-]+@[a-zA-Z0-9_.-]+\s+)?[A-Z]{3,8}:\s+')),
    ("logfmt", re.compile(r'([a-zA-Z0-9_.-]+=)')),
]

class UniversalParser:
    def __init__(self):
        self.cache = {}
        self._parsed_fps = {}
        self.cache_lock = threading.Lock()

        # Family cache: family_id -> rule, NEVER evicted, deterministic.
        # This is the primary gate that guarantees "once per format, LLM once".
        self.family_cache = {}
        self.family_lock = threading.Lock()

        self.ts_patterns = [
            r'^\[?\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+\-]\d{2}:?\d{2})?\]?',
            r'^\[?\d{4}[/-]\d{2}[/-]\d{2}\s+\d{2}:\d{2}:\d{2}(?:[.,]\d+)?\]?',
            r'^\[?\d{2,4}/\d{2}/\d{2,4}\s+\d{2}:\d{2}:\d{2}\]?',
            r'^\[?[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}(?:\.\d+)?\]?',
            r'^\[?\d{4}-\d{2}-\d{2}\b\]?',
            r'^\[?\d{10,13}\b\]?'
        ]
        self.compiled_ts_patterns = [re.compile(p) for p in self.ts_patterns]

        self.severity_words = [
            "CRITICAL", "WARNING", "EMERGENCY", "SEVERE", "NOTICE", "TRACE",
            "DEBUG", "ERROR", "FATAL", "EMERG", "ALERT", "CRIT", "INFO", "WARN", "ERR"
        ]
        words_pipe = "|".join(self.severity_words)
        self.sev_pattern = re.compile(rf'\[?({words_pipe})\]?(?![A-Za-z0-9_])', re.IGNORECASE)
        self.date_fallback_pattern = re.compile(r'(\d{4}-\d{2}-\d{2}|\d{2,4}/\d{2}/\d{2,4}|[A-Z][a-z]{2}\s+\d{1,2})', re.IGNORECASE)

    # ---------- Cache introspection ----------
    def snapshot_cache(self):
        with self.cache_lock:
            fps = [{"fingerprint_features": json.loads(k), "inferred_rule": v} for k, v in self.cache.items()]
        with self.family_lock:
            families = [{"family": fam, "rule": rule} for fam, rule in self.family_cache.items()]
        return fps  # keep API compat; family cache exposed via separate method

    def snapshot_family_cache(self):
        with self.family_lock:
            return dict(self.family_cache)

    def store_rule(self, features: dict, rule: dict):
        fp_str = json.dumps(features, sort_keys=True)
        with self.cache_lock:
            if fp_str not in self.cache:
                if len(self.cache) >= 500:
                    oldest_key = next(iter(self.cache))
                    del self.cache[oldest_key]
                    self._parsed_fps.pop(oldest_key, None)
            self.cache[fp_str] = rule
            self._parsed_fps[fp_str] = dict(features)

    # ---------- Family cache (deterministic, no eviction) ----------
    def get_family_rule(self, family: str):
        with self.family_lock:
            return self.family_cache.get(family)

    def store_family_rule(self, family: str, rule: dict):
        with self.family_lock:
            # Never overwrite with a less specific rule; first rule wins unless explicit upgrade.
            # But allow upgrade if existing rule is heuristic and new is llm, or if signature more specific.
            existing = self.family_cache.get(family)
            if existing is None:
                self.family_cache[family] = dict(rule)
            else:
                # Prefer llm over heuristic, and keep first learned signature.
                if existing.get("inferred_by") != "llm" and rule.get("inferred_by") == "llm":
                    self.family_cache[family] = dict(rule)
                # otherwise keep existing (deterministic)

    def clear_all(self):
        with self.cache_lock:
            self.cache.clear()
            self._parsed_fps.clear()
        with self.family_lock:
            self.family_cache.clear()

    def looks_like_ts_or_sev(self, field: str) -> bool:
        field = field.strip()
        if not field:
            return False
        if parse_timestamp(field):
            return True
        if self.sev_pattern.match(field):
            return True
        return False

    # ---------- Family detection (coarse, stable) ----------
    def detect_family(self, log_entry: str) -> str:
        s = strip_ansi(log_entry).strip()
        if not s:
            return "generic"

        # JSON fast path
        if s.startswith('{') and s.endswith('}'):
            try:
                parsed = json.loads(s)
                if isinstance(parsed, dict):
                    return "json"
            except Exception:
                pass

        # Security formats
        if s.startswith("CEF:"):
            return "cef"
        if s.startswith("LEEF:"):
            return "leef"

        # NCSA combined (Apache/Nginx access)
        if re.search(r'\[\w+:/\s*[+\-]\d{4}\]\s+"[^"]+"\s+\d{3}', s):
            return "ncsa"

        if re.match(r'^<\d{1,3}>\d+\s+', s):
            return "rfc5424"
        if re.match(r'^(?:<\d{1,3}>)?[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}\s+[a-zA-Z0-9_.-]+\s+[a-zA-Z0-9_./-]+(?:\[\d+\])?:\s*', s):
            return "rfc3164"
        if re.match(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+\-]\d{2}:?\d{2})\s+(?:stdout|stderr)\s+[FP]\s+', s):
            return "cri"
        if re.match(r'^\d{4}[/-]\d{2}[/-]\d{2}\s+\d{2}:\d{2}:\d{2}\s+\[[a-z]+\]\s+\d+#\d+:', s):
            return "nginx_error"
        if re.match(r'^[A-Z]{3,8}:[a-zA-Z0-9_.]+:', s):
            # Validate severity
            m = re.match(r'^([A-Z]{3,8}):', s)
            if m and m.group(1).upper() in [w.upper() for w in self.severity_words]:
                return "python"

        # Java / Spring
        if re.search(r'\[main\]\s+(?:[A-Z]{3,8}\s+)?[a-zA-Z0-9_.$]+', s) or re.match(r'^\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}[,.]\d{3}\s+\d+\s+---\s+\[', s) or re.match(r'^\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}[,.]\d{3}\s+(?:\[[^\]]+\]\s+)?[A-Z]{3,8}\s+(?:\[[^\]]+\]|\([^)]+\)|[a-zA-Z0-9_.$]+)', s):
            # Ensure not already matched as other
            if re.match(r'^\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}[,.]\d{3}', s):
                return "java"

        # Postgres
        if re.match(r'^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:\s+[A-Z]{3,4})?\s+\[\d+\]\s+(?:[a-zA-Z0-9_.-]+@[a-zA-Z0-9_.-]+\s+)?[A-Z]{3,8}:\s+', s):
            return "postgres"

        # Delimited detection (pipe, comma, semicolon, tab) - must be before logfmt
        pipe_count = s.count('|')
        comma_count = s.count(',')
        semi_count = s.count(';')
        tab_count = s.count('\t')
        eq_count = s.count('=')

        # Pipe delimited: at least 2 pipes
        if pipe_count >= 2:
            return "pipe"

        # CSV: at least 2 commas and not mostly k=v
        if comma_count >= 2:
            # If it looks like logfmt (many k=v), don't treat as csv
            if eq_count < 3:
                # Check first field looks like timestamp or single token or severity
                first = s.split(',', 1)[0]
                if self.looks_like_ts_or_sev(first) or len(s.split()) <= 6 or comma_count >= 3:
                    return "csv"

        if semi_count >= 2 and eq_count < 3:
            return "semicolon"

        if tab_count >= 2:
            return "tab"

        # Logfmt: at least 3 k=v pairs and not bracket heavy
        if eq_count >= 3 and '[' not in s and '(' not in s:
            kv_pat = re.compile(r'[a-zA-Z0-9_.-]+=(\"[^\"]*\"|\'[^\']*\'|[^ \t\n\r,;\]\}>\)&]+)')
            matches = kv_pat.findall(s)
            if len(matches) >= 3:
                total_kv_len = sum(len(m) for m in matches)
                # At least 40% of string is k=v
                if total_kv_len >= len(s) * 0.35:
                    return "logfmt"

        # Fallback generic (includes auth failures, custom formats, etc.)
        return "generic"

    def fingerprint(self, log_entry: str) -> dict:
        s = strip_ansi(log_entry).strip()
        is_json = False
        if s.startswith('{') and s.endswith('}'):
            try:
                parsed = json.loads(s)
                if isinstance(parsed, dict):
                    is_json = True
            except Exception:
                pass

        tok_count = len(s.split())
        pipe_count = s.count('|')
        comma_count = s.count(',')
        eq_count = s.count('=')
        bracket_count = s.count('[') + s.count('(')

        delim = None
        is_security_format = s.startswith("CEF:") or s.startswith("LEEF:")
        if not is_json and not is_security_format:
            if pipe_count >= 2:
                delim = "|"
            elif comma_count >= 3:
                first_field = s.split(',', 1)[0]
                if tok_count == 1 or self.looks_like_ts_or_sev(first_field):
                    delim = ","

        fmt_type = "generic"
        if is_json:
            fmt_type = "json"
        elif s.startswith("CEF:"):
            fmt_type = "cef"
        elif s.startswith("LEEF:"):
            fmt_type = "leef"
        elif re.search(r'\[\w+:/\s*[+\-]\d{4}\]\s+"[^"]+"\s+\d{3}', s):
            fmt_type = "ncsa"
        elif re.match(r'^<\d{1,3}>\d+\s+', s):
            fmt_type = "rfc5424"
        elif re.match(r'^(?:<\d{1,3}>)?[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}\s+[a-zA-Z0-9_.-]+\s+[a-zA-Z0-9_./-]+(?:\[\d+\])?:\s*', s):
            fmt_type = "rfc3164"
        elif re.match(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+\-]\d{2}:?\d{2})\s+(?:stdout|stderr)\s+[FP]\s+', s):
            fmt_type = "cri"
        elif re.match(r'^\d{4}[/-]\d{2}[/-]\d{2}\s+\d{2}:\d{2}:\d{2}\s+\[[a-z]+\]\s+\d+#\d+:', s):
            fmt_type = "nginx_err"
        elif re.match(r'^[A-Z]{3,8}:[a-zA-Z0-9_.]+:', s):
            fmt_type = "python"
        elif re.search(r'\[main\]\s+(?:[A-Z]{3,8}\s+)?[a-zA-Z0-9_.$]+', s) or re.match(r'^\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}[,.]\d{3}\s+\d+\s+---\s+\[', s):
            fmt_type = "java"
        elif eq_count >= 3 and '[' not in s and '(' not in s and re.search(r'=\S+', s):
            fmt_type = "logfmt"
        elif delim is not None:
            fmt_type = f"delim_{delim}"

        family = self.detect_family(log_entry)

        return {
            "is_json": is_json,
            "tok_count": tok_count,
            "pipe_count": pipe_count,
            "comma_count": comma_count,
            "eq_count": eq_count,
            "bracket_count": bracket_count,
            "delim": delim,
            "fmt_type": fmt_type,
            "family": family
        }

    def find_cached_rule(self, features: dict):
        # Fast path: family cache is checked outside, but keep here for compat.
        # This method now uses relaxed matching: same fmt_type or same delim or same family.
        best_match_fp = None
        best_match_rule = None

        with self.cache_lock:
            if not self.cache and self._parsed_fps:
                self._parsed_fps.clear()

            # First pass: exact family match if present in features
            fam = features.get("family")
            if fam:
                with self.family_lock:
                    fr = self.family_cache.get(fam)
                    if fr:
                        return f"family:{fam}", fr

            for fp_str, rule in self.cache.items():
                cached_feat = self._parsed_fps.get(fp_str)
                if cached_feat is None:
                    try:
                        cached_feat = json.loads(fp_str)
                    except Exception:
                        continue
                    self._parsed_fps[fp_str] = cached_feat

                if cached_feat.get("is_json") != features.get("is_json"):
                    continue

                if features.get("is_json"):
                    if rule.get("method") == "json":
                        return fp_str, rule
                    continue

                # Family must match if both have it
                if "family" in cached_feat and "family" in features:
                    if cached_feat["family"] == features["family"]:
                        return fp_str, rule
                    # If families differ, skip
                    continue

                # Legacy fmt_type matching (relaxed)
                if cached_feat.get("fmt_type") and features.get("fmt_type"):
                    if cached_feat["fmt_type"] == features["fmt_type"]:
                        # For delimited, ignore token counts
                        if features.get("delim") is not None:
                            if cached_feat.get("delim") == features.get("delim"):
                                return fp_str, rule
                        else:
                            return fp_str, rule

                # Fallback: delim match
                if cached_feat.get("delim") and features.get("delim"):
                    if cached_feat["delim"] == features["delim"]:
                        return fp_str, rule

        return None, None

    def detect_timestamp(self, line: str):
        line = line.strip()
        for i, pattern in enumerate(self.compiled_ts_patterns):
            match = pattern.search(line)
            if match and match.start() == 0:
                matched_str = match.group(0)
                clean_str = matched_str.strip('[]')
                iso = parse_timestamp(clean_str)
                if iso:
                    remainder = line[len(matched_str):].lstrip(' -:,|')
                    was_syslog = (i == 3)
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
                    return iso, was_syslog, remainder
        return None, False, line

    # --- Specialized Format Parsers ---

    def _parse_cef(self, s: str) -> dict | None:
        m = re.match(r'^CEF:\s*(\d+)\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|(.*)$', s)
        if not m:
            return None
        cef_ver, vendor, product, dev_ver, class_id, name, sev, ext = m.groups()
        res = {"parsed_fields": {}, "extra": {}}
        res["parsed_fields"]["source"] = f"{vendor} {product}".strip() if vendor or product else "unknown"
        res["parsed_fields"]["message"] = name
        res["parsed_fields"]["event_type"] = class_id or "security_event"
        res["parsed_fields"]["severity"] = sev
        res["extra"]["cef_version"] = cef_ver
        if vendor: res["extra"]["device_vendor"] = vendor
        if product: res["extra"]["device_product"] = product
        if dev_ver: res["extra"]["device_version"] = dev_ver
        if class_id: res["extra"]["event_class_id"] = class_id

        kv_pairs = re.findall(r'(\w+)=((?:\\=|[^=])*)(?:\s+|$)', ext)
        for k, v in kv_pairs:
            res["extra"][k.strip()] = v.strip().replace(r'\=', '=')
        return res

    def _parse_leef(self, s: str) -> dict | None:
        m = re.match(r'^LEEF:\s*(\d+(?:\.\d+)?)\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|(.*)$', s)
        if not m:
            return None
        leef_ver, vendor, product, dev_ver, event_id, ext = m.groups()
        res = {"parsed_fields": {}, "extra": {}}
        res["parsed_fields"]["source"] = f"{vendor} {product}".strip() if vendor or product else "unknown"
        res["parsed_fields"]["event_type"] = event_id or "security_event"
        res["extra"]["leef_version"] = leef_ver
        res["extra"]["device_vendor"] = vendor
        res["extra"]["device_product"] = product

        delim = '\t' if '\t' in ext else r'\s+'
        kv_pairs = re.findall(r'(\w+)=((?:\\=|[^=])*)(?:' + delim + r'|$)', ext)
        for k, v in kv_pairs:
            res["extra"][k.strip()] = v.strip().replace(r'\=', '=')
        return res

    def _parse_rfc5424(self, s: str) -> dict | None:
        m = re.match(r'^<(\d{1,3})>(\d+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)(?:\s+(.*))?$', s)
        if not m:
            return None
        pri_str, ver, ts, host, app, procid, msgid, rest = m.groups()
        res = {"parsed_fields": {}, "extra": {}}
        val = int(pri_str)
        sev_num = val & 7
        sevs = {0:"CRITICAL", 1:"CRITICAL", 2:"CRITICAL", 3:"ERROR", 4:"WARNING", 5:"INFO", 6:"INFO", 7:"DEBUG"}
        res["parsed_fields"]["severity"] = sevs.get(sev_num, "UNKNOWN")
        res["extra"]["facility"] = val >> 3
        res["extra"]["syslog_version"] = int(ver)

        iso = parse_timestamp(ts)
        if iso:
            res["parsed_fields"]["timestamp"] = iso
        if host and host != "-":
            res["parsed_fields"]["source"] = host
        if app and app != "-":
            res["extra"]["program"] = app
        if procid and procid != "-":
            res["extra"]["pid"] = procid
        if msgid and msgid != "-":
            res["parsed_fields"]["event_type"] = msgid

        if rest:
            sd_match = re.match(r'^(\[[^\]]+\])\s*(.*)$', rest)
            if sd_match:
                res["extra"]["structured_data"] = sd_match.group(1)
                msg_clean = sd_match.group(2).lstrip('- ').strip()
            else:
                msg_clean = rest.lstrip('- ').strip()
            res["parsed_fields"]["message"] = msg_clean
        return res

    def _parse_cri(self, s: str) -> dict | None:
        m = re.match(r'^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+\-]\d{2}:?\d{2}))\s+(stdout|stderr)\s+([FP])\s+(.*)$', s)
        if not m:
            return None
        ts, stream, flag, inner_msg = m.groups()
        res = {"parsed_fields": {}, "extra": {}}
        iso = parse_timestamp(ts)
        if iso:
            res["parsed_fields"]["timestamp"] = iso
        res["extra"]["stream"] = stream
        res["extra"]["cri_flag"] = flag
        res["parsed_fields"]["severity"] = "ERROR" if stream == "stderr" else "INFO"

        inner_trimmed = inner_msg.strip()
        if inner_trimmed.startswith('{') and inner_trimmed.endswith('}'):
            try:
                inner_json = json.loads(inner_trimmed)
                if isinstance(inner_json, dict):
                    res["parsed_fields"].update(inner_json)
                    return res
            except Exception:
                pass

        inner_parsed = self.parse_compositional(inner_trimmed)
        for k, v in inner_parsed["parsed_fields"].items():
            if k == "timestamp" and res["parsed_fields"].get("timestamp"):
                continue
            res["parsed_fields"][k] = v
        for k, v in inner_parsed["extra"].items():
            res["extra"][k] = v
        if not res["parsed_fields"].get("message"):
            res["parsed_fields"]["message"] = inner_trimmed
        return res

    def _parse_nginx_error(self, s: str) -> dict | None:
        m = re.match(r'^(\d{4}[/-]\d{2}[/-]\d{2}\s+\d{2}:\d{2}:\d{2})\s+\[([a-z]+)\]\s+(\d+#\d+):\s+(?:\*(\d+)\s+)?(.*)$', s)
        if not m:
            return None
        ts, sev, pid, cid, msg_part = m.groups()
        res = {"parsed_fields": {}, "extra": {}}
        iso = parse_timestamp(ts)
        if iso: res["parsed_fields"]["timestamp"] = iso
        res["parsed_fields"]["severity"] = sev.upper()
        res["extra"]["pid"] = pid
        if cid: res["extra"]["connection_id"] = cid
        res["parsed_fields"]["source"] = "nginx"
        res["parsed_fields"]["event_type"] = "web_error"

        main_msg = msg_part
        trailer_match = re.search(r',\s*(client:\s*[^,]+.*)$', msg_part)
        if trailer_match:
            main_msg = msg_part[:trailer_match.start()].strip()
            trailer_str = trailer_match.group(1)
            for pair in re.split(r',\s*', trailer_str):
                if ':' in pair:
                    k, v = pair.split(':', 1)
                    res["extra"][k.strip()] = v.strip().strip('"')
        res["parsed_fields"]["message"] = main_msg
        return res

    def _parse_spring_boot(self, s: str) -> dict | None:
        m = re.match(r'^(\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}[,.]\d{3})\s+([A-Z]{3,8})\s+(\d+)\s+---\s+\[([^\]]+)\]\s+([a-zA-Z0-9_.$]+)\s*:\s*(.*)$', s)
        if not m:
            return None
        ts, sev, pid, thread, logger, msg = m.groups()
        res = {"parsed_fields": {}, "extra": {}}
        iso = parse_timestamp(ts)
        if iso: res["parsed_fields"]["timestamp"] = iso
        res["parsed_fields"]["severity"] = sev
        res["parsed_fields"]["source"] = logger
        res["parsed_fields"]["message"] = msg.strip()
        res["extra"]["pid"] = pid
        res["extra"]["thread"] = thread.strip()
        return res

    def _parse_java_log(self, s: str) -> dict | None:
        p1 = re.compile(
            r'^(\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}[,.]\d{3})\s+(?:\[([^\]]+)\]\s+)?([A-Z]{3,8})\s+(?:\[([a-zA-Z0-9_.$]+)\]|\(([a-zA-Z0-9_.$]+)\)|([a-zA-Z0-9_.$]+))\s*(?:\(([a-zA-Z0-9_.$]+)\)\s*|\[([a-zA-Z0-9_.$]+)\]\s*)?(?:[-:]\s+)?(.*)$'
        )
        m = p1.match(s)
        if m:
            ts, thread1, sev, l_b1, l_p1, l_raw, extra_p, extra_b, msg = m.groups()
            res = {"parsed_fields": {}, "extra": {}}
            iso = parse_timestamp(ts)
            if iso: res["parsed_fields"]["timestamp"] = iso
            res["parsed_fields"]["severity"] = sev
            logger = l_b1 or l_p1 or l_raw
            if logger and len(logger) > 2:
                res["parsed_fields"]["source"] = logger
            thread = thread1 or extra_p or extra_b
            if thread: res["extra"]["thread"] = thread
            res["parsed_fields"]["message"] = msg.strip()
            return res

        p2 = re.compile(
            r'^\[?([A-Z]{3,8})\]?\s+(\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}[,.]\d{3})\s+(?:\[([^\]]+)\]\s+)?([a-zA-Z0-9_.$]+(?:\.[a-zA-Z0-9_$]+)*)\s*(?:-+|:)\\s*(.*)$'
        )
        m2 = p2.match(s)
        if m2:
            sev, ts, thread, logger, msg = m2.groups()
            res = {"parsed_fields": {}, "extra": {}}
            iso = parse_timestamp(ts)
            if iso: res["parsed_fields"]["timestamp"] = iso
            res["parsed_fields"]["severity"] = sev
            if logger: res["parsed_fields"]["source"] = logger
            if thread: res["extra"]["thread"] = thread
            res["parsed_fields"]["message"] = msg.strip()
            return res
        return None

    def _parse_python_log(self, s: str) -> dict | None:
        m1 = re.match(r'^([A-Z]{3,8}):([a-zA-Z0-9_.]+):(.*)$', s)
        if m1 and m1.group(1).upper() in self.severity_words:
            sev, logger, msg = m1.groups()
            return {
                "parsed_fields": {
                    "severity": sev.upper(),
                    "source": logger,
                    "message": msg.strip()
                },
                "extra": {}
            }

        m2 = re.match(r'^(\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-\s*([a-zA-Z0-9_.]+)\s*-\s*([A-Z]{3,8})\s*-\s*(.*)$', s)
        if m2:
            ts, logger, sev, msg = m2.groups()
            iso = parse_timestamp(ts)
            res = {"parsed_fields": {"severity": sev.upper(), "source": logger, "message": msg.strip()}, "extra": {}}
            if iso: res["parsed_fields"]["timestamp"] = iso
            return res

        m3 = re.match(r'^\[(\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}[,.]\d{3})\]\s*\{([^}]+)\}\s*([A-Z]{3,8})\s*-\s*(.*)$', s)
        if m3:
            ts, caller, sev, msg = m3.groups()
            iso = parse_timestamp(ts)
            res = {"parsed_fields": {"severity": sev.upper(), "source": caller, "message": msg.strip()}, "extra": {"caller": caller}}
            if iso: res["parsed_fields"]["timestamp"] = iso
            return res
        return None

    def _parse_postgres(self, s: str) -> dict | None:
        p_pg = re.compile(
            r'^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:\s+[A-Z]{3,4})?)\s+\[(\d+)\]\s+(?:([a-zA-Z0-9_.-]+@[a-zA-Z0-9_.-]+)\s+)?([A-Z]{3,8}):\s+(.*)$'
        )
        m = p_pg.match(s)
        if not m:
            return None
        ts, pid, user_db, sev, msg = m.groups()
        res = {"parsed_fields": {}, "extra": {}}
        iso = parse_timestamp(ts)
        if iso: res["parsed_fields"]["timestamp"] = iso
        res["parsed_fields"]["severity"] = sev
        res["parsed_fields"]["source"] = "postgres"
        res["parsed_fields"]["message"] = msg.strip()
        res["extra"]["pid"] = pid
        if user_db:
            res["extra"]["user_database"] = user_db
        return res

    def _parse_logfmt(self, s: str) -> dict | None:
        if '(' in s or '[' in s:
            return None
        kv_pattern = re.compile(r'([a-zA-Z0-9_.-]+)=(?:\"([^\"]*)\"|\'([^\']*)\'|([^ \t\n\r,;\]\}>\\)&]+))')
        matches = kv_pattern.findall(s)
        if len(matches) < 3:
            return None

        total_kv_len = sum(len(m[0]) + 1 + len(m[1] or m[2] or m[3]) for m in matches)
        if total_kv_len < len(s) * 0.45:
            return None

        res = {"parsed_fields": {}, "extra": {}}
        for k, v1, v2, v3 in matches:
            val = v1 if v1 != "" else (v2 if v2 != "" else v3)
            k_low = k.lower()
            if k_low in ("ts", "time", "timestamp", "datetime", "date") and "timestamp" not in res["parsed_fields"]:
                iso = parse_timestamp(val)
                if iso:
                    res["parsed_fields"]["timestamp"] = iso
                    continue
            if k_low in ("level", "lvl", "severity") and "severity" not in res["parsed_fields"]:
                res["parsed_fields"]["severity"] = val.upper()
                continue
            if k_low in ("msg", "message") and "message" not in res["parsed_fields"]:
                res["parsed_fields"]["message"] = val
                continue
            if k_low in ("caller", "service", "host", "logger", "app") and "source" not in res["parsed_fields"]:
                res["parsed_fields"]["source"] = val
                continue
            res["extra"][k] = val
        return res

    def parse_compositional(self, log_entry: str) -> dict:
        rem = strip_ansi(log_entry).strip()

        # Check Combined / Common Log Format (NCSA / Apache / Nginx)
        combined_match = re.match(
            r'^(\S+)\s+(\S+)\s+(\S+)\s+\[([\w:/]+\s+[+\-]\d{4})\]\s+"([^"]+)"\s+(\d{3})\s+(\S+)(?:\s+"([^"]*)"\s+"([^"]*)")?',
            rem
        )
        if combined_match:
            ip, ident, user, raw_ts, request, status, size, referer, agent = combined_match.groups()
            result = {"parsed_fields": {}, "extra": {}}
            result["parsed_fields"]["source"] = ip
            ts_iso = parse_timestamp(raw_ts)
            if ts_iso:
                result["parsed_fields"]["timestamp"] = ts_iso
            result["parsed_fields"]["message"] = request
            result["parsed_fields"]["event_type"] = "http_request"

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

            if ident and ident != "-": result["extra"]["ident"] = ident
            if user and user != "-": result["extra"]["user"] = user
            if size and size != "-": result["extra"]["bytes_sent"] = int(size) if size.isdigit() else size
            if referer and referer != "-": result["extra"]["referer"] = referer
            if agent and agent != "-": result["extra"]["user_agent"] = agent

            req_tokens = request.split()
            if len(req_tokens) >= 2:
                result["extra"]["http_method"] = req_tokens[0]
                result["extra"]["http_path"] = req_tokens[1]
                if len(req_tokens) >= 3:
                    result["extra"]["http_proto"] = req_tokens[2]
            return result

        # Try specialized format parsers
        for parser_fn in [
            self._parse_cef,
            self._parse_leef,
            self._parse_rfc5424,
            self._parse_cri,
            self._parse_nginx_error,
            self._parse_spring_boot,
            self._parse_java_log,
            self._parse_python_log,
            self._parse_postgres,
            self._parse_logfmt
        ]:
            special_res = parser_fn(rem)
            if special_res:
                return special_res

        # Master Fallback: Compositional Zone Extraction
        result = {"parsed_fields": {}, "extra": {}}

        # 0. Syslog priority prefix <PRI>
        match = re.search(r'^<(\d{1,3})>', rem)
        if match:
            matched_str = match.group(0)
            rem = rem[len(matched_str):].lstrip(' -:,|')
            val = int(match.group(1))
            sev_num = val & 7
            sevs = {0:"CRITICAL", 1:"CRITICAL", 2:"CRITICAL", 3:"ERROR", 4:"WARNING", 5:"INFO", 6:"INFO", 7:"DEBUG"}
            result["parsed_fields"]["severity"] = sevs.get(sev_num, "UNKNOWN")
            result["extra"]["facility"] = val >> 3

        # 1. Timestamp Detection (leading or bracketed)
        ts_iso, was_syslog, rem = self.detect_timestamp(rem)
        if ts_iso:
            result["parsed_fields"]["timestamp"] = ts_iso

        # 2. Leading Severity
        if "severity" not in result["parsed_fields"]:
            match = self.sev_pattern.search(rem)
            if match and match.start() == 0:
                matched_str = match.group(0)
                rem = rem[len(matched_str):].lstrip(' -:,|')
                result["parsed_fields"]["severity"] = match.group(1).upper()

        # 3. Syslog host/program
        if ts_iso and was_syslog:
            host_match = re.match(r'^([a-zA-Z0-9_-]+)\s+([a-zA-Z0-9_.-]+)(?:\[(\d+)\])?:\s*', rem)
            if host_match:
                result["parsed_fields"]["source"] = host_match.group(1)
                result["extra"]["program"] = host_match.group(2)
                if host_match.group(3):
                    result["extra"]["pid"] = host_match.group(3)
                rem = rem[len(host_match.group(0)):]

        # 4. Context brackets [thread] or (process)
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

        # 5. Check for trailing JSON payload
        m_json = re.search(r'(\{.*\}|\[.*\])\s*$', rem)
        if m_json:
            try:
                parsed_json = json.loads(m_json.group(1))
                if isinstance(parsed_json, dict):
                    result["extra"]["json_payload"] = parsed_json
                    rem = rem[:m_json.start()].rstrip(' -:,|')
            except Exception:
                pass

        # 6. Message
        if rem:
            result["parsed_fields"]["message"] = rem.strip()

        # 7. Entity Recognition: IPs, Ports, Users
        full_text = log_entry
        ip_match = re.search(r'\b(?:\d{1,3}\.){3}\d{1,3}\b', full_text)
        if ip_match:
            ip_val = ip_match.group(0)
            result["extra"]["ip"] = ip_val
            if "source" not in result["parsed_fields"]:
                result["parsed_fields"]["source"] = ip_val

        port_match = re.search(r'\bport\s*[:=]?\s*(\d{2,5})\b', full_text, re.I)
        if not port_match and ip_match:
            port_match = re.search(rf"{re.escape(ip_match.group(0))}:(\d{{2,5}})\b", full_text)
        if port_match:
            result["extra"]["port"] = port_match.group(1)

        user_match = re.search(r'(?:for\s+(?:invalid\s+user\s+)?|user[\s=:]+)([a-zA-Z0-9_.-]+)', full_text, re.I)
        if user_match:
            user_val = user_match.group(1)
            if user_val.lower() not in ("invalid", "authentication", "to", "the", "a", "an"):
                result["extra"]["user"] = user_val

        # 8. KV scan
        kv_pattern = re.compile(r'([a-zA-Z0-9_-]+)=("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|[^ \t\n\r,;\]\}>\)&]+)')
        for k, v in kv_pattern.findall(full_text):
            if v.startswith('"') and v.endswith('"'): v = v[1:-1]
            elif v.startswith("'") and v.endswith("'"): v = v[1:-1]
            result["extra"][k] = v

        return result

    def parse_with_rule(self, log_entry: str, rule: dict) -> dict:
        result = {"parsed_fields": {}, "extra": {}}
        method = rule.get("method")
        clean_entry = strip_ansi(log_entry).strip()

        if method == "json":
            try:
                parsed = json.loads(clean_entry)
                if isinstance(parsed, dict):
                    if "log" in parsed and isinstance(parsed["log"], str) and ("stream" in parsed or "time" in parsed):
                        inner = parsed["log"].strip()
                        inner_parsed = self.parse_compositional(inner)
                        result["parsed_fields"] = inner_parsed.get("parsed_fields", {})
                        result["extra"] = inner_parsed.get("extra", {})
                        for k, v in parsed.items():
                            if k != "log":
                                result["extra"][k] = v
                        return result

                    if "t" in parsed and isinstance(parsed["t"], dict) and "$date" in parsed["t"]:
                        parsed["timestamp"] = parsed.pop("t")["$date"]
                    if "s" in parsed and "severity" not in parsed:
                        parsed["severity"] = parsed.pop("s")
                    if "c" in parsed and "source" not in parsed:
                        parsed["source"] = parsed.pop("c")

                    result["parsed_fields"] = parsed
                    return result
            except Exception:
                pass
            method = "compositional"

        if method == "delimiter":
            delim = rule.get("delimiter")
            try:
                reader = csv.reader(io.StringIO(clean_entry), delimiter=delim)
                parts = next(reader)
            except Exception:
                parts = [p.strip() for p in clean_entry.split(delim)]

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
            return self.parse_compositional(clean_entry)

        result["parsed_fields"]["raw_message"] = clean_entry
        return result
