import json, re, threading, csv, io
from .timeutil import parse_timestamp

def strip_ansi(s: str) -> str:
    return re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', s)

KNOWN_FAMILIES = {"json","cef","leef","ncsa","rfc5424","rfc3164","cri","nginx_error","python","java","postgres","logfmt","pipe","csv","semicolon","tab"}

SEV_WORDS = ["CRITICAL","WARNING","EMERGENCY","SEVERE","NOTICE","TRACE","DEBUG","ERROR","FATAL","EMERG","ALERT","CRIT","INFO","WARN","ERR"]
SEV_RE = re.compile(rf'\[?({"|".join(SEV_WORDS)})]?(?![A-Za-z0-9_])', re.I)
DATE_FALLBACK_RE = re.compile(r'(\d{4}-\d{2}-\d{2}|\d{2,4}/\d{2}/\d{2,4}|[A-Z][a-z]{2}\s+\d{1,2})', re.I)

TS_PATS = [re.compile(p) for p in [
    r'^\[?\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+\-]\d{2}:?\d{2})?\]?',
    r'^\[?\d{4}[/-]\d{2}[/-]\d{2}\s+\d{2}:\d{2}:\d{2}(?:[.,]\d+)?\]?',
    r'^\[?\d{2,4}/\d{2}/\d{2,4}\s+\d{2}:\d{2}:\d{2}\]?',
    r'^\[?[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}(?:\.\d+)?\]?',
    r'^\[?\d{4}-\d{2}-\d{2}\b\]?',
    r'^\[?\d{10,13}\b\]?'
]]

def _mk_res(fields=None, extra=None):
    return {"parsed_fields": fields or {}, "extra": extra or {}}

class UniversalParser:
    def __init__(self):
        self.cache = {}
        self._parsed_fps = {}
        self.cache_lock = threading.Lock()
        self.family_cache = {}
        self.family_lock = threading.Lock()

    def snapshot_cache(self):
        with self.cache_lock:
            return [{"fingerprint_features": json.loads(k), "inferred_rule": v} for k, v in self.cache.items()]

    def snapshot_family_cache(self):
        with self.family_lock:
            return dict(self.family_cache)

    def store_rule(self, feat, rule):
        fp = json.dumps(feat, sort_keys=True)
        with self.cache_lock:
            if fp not in self.cache and len(self.cache) >= 500:
                oldest = next(iter(self.cache))
                del self.cache[oldest]
                self._parsed_fps.pop(oldest, None)
            self.cache[fp] = rule
            self._parsed_fps[fp] = dict(feat)

    def get_family_rule(self, fam):
        with self.family_lock:
            return self.family_cache.get(fam)

    def store_family_rule(self, fam, rule):
        with self.family_lock:
            cur = self.family_cache.get(fam)
            if cur is None or (cur.get("inferred_by") != "llm" and rule.get("inferred_by") == "llm"):
                self.family_cache[fam] = dict(rule)

    def looks_like_ts_or_sev(self, field):
        f = field.strip()
        return bool(f and (parse_timestamp(f) or SEV_RE.match(f)))

    def detect_family(self, log_entry):
        s = strip_ansi(log_entry).strip()
        if not s:
            return "generic"
        if s.startswith('{') and s.endswith('}'):
            try:
                if isinstance(json.loads(s), dict):
                    return "json"
            except Exception:
                pass
        if s.startswith("CEF:"): return "cef"
        if s.startswith("LEEF:"): return "leef"
        if re.search(r'\[[^\]]+\]\s+"[A-Z]+\s+[^"]+"\s+\d{3}', s): return "ncsa"
        if re.match(r'^<\d{1,3}>\d+\s+', s): return "rfc5424"
        if re.match(r'^(?:<\d{1,3}>)?[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}\s+[a-zA-Z0-9_.-]+\s+[a-zA-Z0-9_./-]+(?:\[\d+\])?:\s*', s): return "rfc3164"
        if re.match(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+\-]\d{2}:?\d{2})\s+(?:stdout|stderr)\s+[FP]\s+', s): return "cri"
        if re.match(r'^\d{4}[/-]\d{2}[/-]\d{2}\s+\d{2}:\d{2}:\d{2}\s+\[[a-z]+\]\s+\d+#\d+:', s): return "nginx_error"
        m = re.match(r'^([A-Z]{3,8}):[a-zA-Z0-9_.]+:', s)
        if m and m.group(1).upper() in [w.upper() for w in SEV_WORDS]: return "python"
        if re.match(r'^\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}[,.]\d{3}', s) and (re.search(r'\[main\]\s+(?:[A-Z]{3,8}\s+)?[a-zA-Z0-9_.$]+', s) or re.match(r'^\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}[,.]\d{3}\s+\d+\s+---\s+\[', s) or re.match(r'^\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}[,.]\d{3}\s+(?:\[[^\]]+\]\s+)?[A-Z]{3,8}\s+', s)):
            return "java"
        if re.match(r'^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:\s+[A-Z]{3,4})?\s+\[\d+\]\s+(?:[a-zA-Z0-9_.-]+@[a-zA-Z0-9_.-]+\s+)?[A-Z]{3,8}:\s+', s): return "postgres"

        pc, cc, sc, tc, eq = s.count('|'), s.count(','), s.count(';'), s.count('\t'), s.count('=')
        if pc >= 2: return "pipe"
        if cc >= 2 and eq < 3:
            first = s.split(',', 1)[0]
            if self.looks_like_ts_or_sev(first) or len(s.split()) <= 6 or cc >= 3:
                return "csv"
        if sc >= 2 and eq < 3: return "semicolon"
        if tc >= 2: return "tab"
        if eq >= 3 and '[' not in s and '(' not in s:
            kv_pat = re.compile(r'[a-zA-Z0-9_.-]+=(?:"[^"]*"|\'[^\']*\'|[^ \t\n\r,;\]\}>\\)&]+)')
            matches = kv_pat.findall(s)
            if len(matches) >= 3 and sum(len(m) for m in matches) >= len(s) * 0.35:
                return "logfmt"
        return "generic"

    def fingerprint(self, log_entry):
        s = strip_ansi(log_entry).strip()
        is_json = False
        if s.startswith('{') and s.endswith('}'):
            try:
                is_json = isinstance(json.loads(s), dict)
            except Exception:
                pass
        tok, pc, cc, eq, br = len(s.split()), s.count('|'), s.count(','), s.count('='), s.count('[')+s.count('(')
        delim = None
        if not is_json and not (s.startswith("CEF:") or s.startswith("LEEF:")):
            if pc >= 2: delim = "|"
            elif cc >= 3 and (len(s.split()) == 1 or self.looks_like_ts_or_sev(s.split(',',1)[0])): delim = ","
        fmt = "generic"
        if is_json: fmt = "json"
        elif s.startswith("CEF:"): fmt = "cef"
        elif s.startswith("LEEF:"): fmt = "leef"
        elif re.search(r'\[[^\]]+\]\s+"[A-Z]+\s+[^"]+"\s+\d{3}', s): fmt = "ncsa"
        elif re.match(r'^<\d{1,3}>\d+\s+', s): fmt = "rfc5424"
        elif re.match(r'^(?:<\d{1,3}>)?[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}\s+', s): fmt = "rfc3164"
        elif re.match(r'^\d{4}-\d{2}-\d{2}T.*\s+(?:stdout|stderr)\s+[FP]\s+', s): fmt = "cri"
        elif re.match(r'^\d{4}[/-]\d{2}[/-]\d{2}\s+\d{2}:\d{2}:\d{2}\s+\[[a-z]+\]\s+\d+#\d+:', s): fmt = "nginx_err"
        elif re.match(r'^[A-Z]{3,8}:[a-zA-Z0-9_.]+:', s): fmt = "python"
        elif re.search(r'\[main\]\s+(?:[A-Z]{3,8}\s+)?[a-zA-Z0-9_.$]+', s) or re.match(r'^\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}[,.]\d{3}\s+\d+\s+---\s+\[', s): fmt = "java"
        elif eq >= 3 and '[' not in s and '(' not in s and re.search(r'=\S+', s): fmt = "logfmt"
        elif delim: fmt = f"delim_{delim}"
        return {"is_json": is_json, "tok_count": tok, "pipe_count": pc, "comma_count": cc, "eq_count": eq, "bracket_count": br, "delim": delim, "fmt_type": fmt, "family": self.detect_family(log_entry)}

    def find_cached_rule(self, feat):
        with self.cache_lock:
            if not self.cache and self._parsed_fps:
                self._parsed_fps.clear()
            fam = feat.get("family")
            if fam:
                with self.family_lock:
                    fr = self.family_cache.get(fam)
                    if fr:
                        return f"family:{fam}", fr
            for fp_str, rule in self.cache.items():
                cf = self._parsed_fps.get(fp_str)
                if cf is None:
                    try:
                        cf = json.loads(fp_str)
                    except Exception:
                        continue
                    self._parsed_fps[fp_str] = cf
                if cf.get("is_json") != feat.get("is_json"):
                    continue
                if feat.get("is_json"):
                    if rule.get("method") == "json":
                        return fp_str, rule
                    continue
                if "family" in cf and "family" in feat:
                    if cf["family"] == feat["family"]:
                        return fp_str, rule
                    continue
                if cf.get("fmt_type") and feat.get("fmt_type") and cf["fmt_type"] == feat["fmt_type"]:
                    if feat.get("delim") is None or cf.get("delim") == feat.get("delim"):
                        return fp_str, rule
                if cf.get("delim") and feat.get("delim") and cf["delim"] == feat["delim"]:
                    return fp_str, rule
        return None, None

    def detect_timestamp(self, line):
        line = line.strip()
        for i, pat in enumerate(TS_PATS):
            m = pat.search(line)
            if m and m.start() == 0:
                ms = m.group(0)
                iso = parse_timestamp(ms.strip('[]'))
                if iso:
                    return iso, i == 3, line[len(ms):].lstrip(' -:,|')
        toks = line.split()
        for i in range(1, min(4, len(toks)+1)):
            cand = " ".join(toks[:i])
            clean = cand.strip('[]')
            if DATE_FALLBACK_RE.search(clean):
                iso = parse_timestamp(clean)
                if iso:
                    return iso, bool(re.search(r'^[A-Z][a-z]{2}\s+\d{1,2}', clean)), line[len(cand):].lstrip(' -:,|')
        return None, False, line

    def _parse_cef(self, s):
        m = re.match(r'^CEF:\s*(\d+)\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|(.*)$', s)
        if not m: return None
        ver, vend, prod, dver, cid, name, sev, ext = m.groups()
        pf = {"source": f"{vend} {prod}".strip() or "unknown", "message": name, "event_type": cid or "security_event", "severity": sev}
        ex = {"cef_version": ver}
        if vend: ex["device_vendor"]=vend
        if prod: ex["device_product"]=prod
        if dver: ex["device_version"]=dver
        if cid: ex["event_class_id"]=cid
        for k,v in re.findall(r'(\w+)=((?:\\=|[^=])*)(?:\s+|$)', ext):
            ex[k.strip()] = v.strip().replace(r'\=', '=')
        return _mk_res(pf, ex)

    def _parse_leef(self, s):
        m = re.match(r'^LEEF:\s*(\d+(?:\.\d+)?)\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|(.*)$', s)
        if not m: return None
        ver, vend, prod, _, eid, ext = m.groups()
        pf = {"source": f"{vend} {prod}".strip() or "unknown", "event_type": eid or "security_event"}
        ex = {"leef_version": ver, "device_vendor": vend, "device_product": prod}
        delim = '\t' if '\t' in ext else r'\s+'
        for k,v in re.findall(r'(\w+)=((?:\\=|[^=])*)(?:'+delim+r'|$)', ext):
            ex[k.strip()] = v.strip().replace(r'\=', '=')
        return _mk_res(pf, ex)

    def _parse_rfc5424(self, s):
        m = re.match(r'^<(\d{1,3})>(\d+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)(?:\s+(.*))?$', s)
        if not m: return None
        pri, ver, ts, host, app, pid, mid, rest = m.groups()
        sev = {0:"CRITICAL",1:"CRITICAL",2:"CRITICAL",3:"ERROR",4:"WARNING",5:"INFO",6:"INFO",7:"DEBUG"}.get(int(pri)&7,"UNKNOWN")
        pf, ex = {"severity": sev}, {"facility": int(pri)>>3, "syslog_version": int(ver)}
        iso = parse_timestamp(ts)
        if iso: pf["timestamp"]=iso
        if host != "-": pf["source"]=host
        if app != "-": ex["program"]=app
        if pid != "-": ex["pid"]=pid
        if mid != "-": pf["event_type"]=mid
        if rest:
            sd = re.match(r'^(\[[^\]]+\])\s*(.*)$', rest)
            pf["message"] = (sd.group(2).lstrip('- ').strip() if sd else rest.lstrip('- ').strip())
            if sd: ex["structured_data"]=sd.group(1)
        return _mk_res(pf, ex)

    def _parse_cri(self, s):
        m = re.match(r'^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+\-]\d{2}:?\d{2}))\s+(stdout|stderr)\s+([FP])\s+(.*)$', s)
        if not m: return None
        ts, stream, flag, inner = m.groups()
        pf, ex = {}, {"stream": stream, "cri_flag": flag, "severity": "ERROR" if stream=="stderr" else "INFO"}
        iso = parse_timestamp(ts)
        if iso: pf["timestamp"]=iso
        pf["severity"]=ex["severity"]
        inner=inner.strip()
        if inner.startswith('{') and inner.endswith('}'):
            try:
                j=json.loads(inner)
                if isinstance(j, dict):
                    pf.update(j)
                    return _mk_res(pf, ex)
            except Exception:
                pass
        comp=self.parse_compositional(inner)
        for k,v in comp["parsed_fields"].items():
            if not (k=="timestamp" and pf.get("timestamp")):
                pf[k]=v
        ex.update(comp["extra"])
        pf.setdefault("message", inner)
        return _mk_res(pf, ex)

    def _parse_nginx_error(self, s):
        m=re.match(r'^(\d{4}[/-]\d{2}[/-]\d{2}\s+\d{2}:\d{2}:\d{2})\s+\[([a-z]+)\]\s+(\d+#\d+):\s+(?:\*(\d+)\s+)?(.*)$', s)
        if not m: return None
        ts, sev, pid, cid, msg = m.groups()
        pf={"severity":sev.upper(),"source":"nginx","event_type":"web_error"}
        ex={"pid":pid}
        iso=parse_timestamp(ts)
        if iso: pf["timestamp"]=iso
        if cid: ex["connection_id"]=cid
        main_msg=msg
        tr=re.search(r',\s*(client:\s*[^,]+.*)$', msg)
        if tr:
            main_msg=msg[:tr.start()].strip()
            for pair in re.split(r',\s*', tr.group(1)):
                if ':' in pair:
                    k,v=pair.split(':',1)
                    ex[k.strip()]=v.strip().strip('"')
        pf["message"]=main_msg
        return _mk_res(pf, ex)

    def _parse_spring_boot(self, s):
        m=re.match(r'^(\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}[,.]\d{3})\s+([A-Z]{3,8})\s+(\d+)\s+---\s+\[([^\]]+)\]\s+([a-zA-Z0-9_.$]+)\s*:\s*(.*)$', s)
        if not m: return None
        ts, sev, pid, thr, logg, msg=m.groups()
        pf={"severity":sev,"source":logg,"message":msg.strip()}
        ex={"pid":pid,"thread":thr.strip()}
        iso=parse_timestamp(ts)
        if iso: pf["timestamp"]=iso
        return _mk_res(pf, ex)

    def _parse_java_log(self, s):
        p1=re.compile(r'^(\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}[,.]\d{3})\s+(?:\[([^\]]+)\]\s+)?([A-Z]{3,8})\s+(?:\[([a-zA-Z0-9_.$]+)\]|\(([a-zA-Z0-9_.$]+)\)|([a-zA-Z0-9_.$]+))\s*(?:\(([a-zA-Z0-9_.$]+)\)\s*|\[([a-zA-Z0-9_.$]+)\]\s*)?(?:[-:]\s+)?(.*)$')
        m=p1.match(s)
        if m:
            ts, th1, sev, b1, p1_, raw, ep, eb, msg=m.groups()
            pf={"severity":sev,"message":msg.strip()}
            ex={}
            iso=parse_timestamp(ts)
            if iso: pf["timestamp"]=iso
            lg=b1 or p1_ or raw
            if lg and len(lg)>2: pf["source"]=lg
            th=th1 or ep or eb
            if th: ex["thread"]=th
            return _mk_res(pf, ex)
        p2=re.compile(r'^\[?([A-Z]{3,8})\]?\s+(\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}[,.]\d{3})\s+(?:\[([^\]]+)\]\s+)?([a-zA-Z0-9_.$]+(?:\.[a-zA-Z0-9_$]+)*)\s*(?:-+|:)\\s*(.*)$')
        m2=p2.match(s)
        if m2:
            sev, ts, th, lg, msg=m2.groups()
            pf={"severity":sev,"message":msg.strip()}
            ex={}
            iso=parse_timestamp(ts)
            if iso: pf["timestamp"]=iso
            if lg: pf["source"]=lg
            if th: ex["thread"]=th
            return _mk_res(pf, ex)
        return None

    def _parse_python_log(self, s):
        m1=re.match(r'^([A-Z]{3,8}):([a-zA-Z0-9_.]+):(.*)$', s)
        if m1 and m1.group(1).upper() in SEV_WORDS:
            sev, lg, msg=m1.groups()
            return _mk_res({"severity":sev.upper(),"source":lg,"message":msg.strip()})
        m2=re.match(r'^(\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-\s*([a-zA-Z0-9_.]+)\s*-\s*([A-Z]{3,8})\s*-\s*(.*)$', s)
        if m2:
            ts, lg, sev, msg=m2.groups()
            pf={"severity":sev.upper(),"source":lg,"message":msg.strip()}
            iso=parse_timestamp(ts)
            if iso: pf["timestamp"]=iso
            return _mk_res(pf)
        m3=re.match(r'^\[(\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}[,.]\d{3})\]\s*\{([^}]+)\}\s*([A-Z]{3,8})\s*-\s*(.*)$', s)
        if m3:
            ts, caller, sev, msg=m3.groups()
            pf={"severity":sev.upper(),"source":caller,"message":msg.strip()}
            iso=parse_timestamp(ts)
            if iso: pf["timestamp"]=iso
            return _mk_res(pf, {"caller":caller})
        return None

    def _parse_postgres(self, s):
        m=re.match(r'^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:\s+[A-Z]{3,4})?)\s+\[(\d+)\]\s+(?:([a-zA-Z0-9_.-]+@[a-zA-Z0-9_.-]+)\s+)?([A-Z]{3,8}):\s+(.*)$', s)
        if not m: return None
        ts, pid, udb, sev, msg=m.groups()
        pf={"severity":sev,"source":"postgres","message":msg.strip()}
        ex={"pid":pid}
        iso=parse_timestamp(ts)
        if iso: pf["timestamp"]=iso
        if udb: ex["user_database"]=udb
        return _mk_res(pf, ex)

    def _parse_logfmt(self, s):
        if '(' in s or '[' in s: return None
        pat=re.compile(r'([a-zA-Z0-9_.-]+)=(?:\"([^\"]*)\"|\'([^\']*)\'|([^ \t\n\r,;\]\}>\\)&]+))')
        matches=pat.findall(s)
        if len(matches)<3 or sum(len(m[0])+1+len(m[1] or m[2] or m[3]) for m in matches) < len(s)*0.45:
            return None
        pf, ex = {}, {}
        for k,v1,v2,v3 in matches:
            val=v1 if v1!="" else (v2 if v2!="" else v3)
            low=k.lower()
            if low in ("ts","time","timestamp","datetime","date") and "timestamp" not in pf:
                iso=parse_timestamp(val)
                if iso:
                    pf["timestamp"]=iso
                    continue
            if low in ("level","lvl","severity") and "severity" not in pf:
                pf["severity"]=val.upper()
                continue
            if low in ("msg","message") and "message" not in pf:
                pf["message"]=val
                continue
            if low in ("caller","service","host","logger","app") and "source" not in pf:
                pf["source"]=val
                continue
            ex[k]=val
        return _mk_res(pf, ex)

    def parse_compositional(self, log_entry):
        rem=strip_ansi(log_entry).strip()
        m=re.match(r'^(\S+)\s+(\S+)\s+(\S+)\s+\[([\w:/]+\s+[+\-]\d{4})\]\s+"([^"]+)"\s+(\d{3})\s+(\S+)(?:\s+"([^"]*)"\s+"([^"]*)")?', rem)
        if m:
            ip, _, user, raw_ts, req, status, size, ref, agent=m.groups()
            pf={"source":ip,"message":req,"event_type":"http_request"}
            ex={}
            iso=parse_timestamp(raw_ts)
            if iso: pf["timestamp"]=iso
            try:
                sc=int(status)
                ex["http_status"]=sc
                pf["severity"]="ERROR" if sc>=500 else "WARNING" if sc>=400 else "INFO"
            except ValueError:
                pass
            if user!="-": ex["user"]=user
            if size!="-": ex["bytes_sent"]=int(size) if size.isdigit() else size
            if ref and ref!="-": ex["referer"]=ref
            if agent and agent!="-": ex["user_agent"]=agent
            toks=req.split()
            if len(toks)>=2:
                ex["http_method"]=toks[0]
                ex["http_path"]=toks[1]
                if len(toks)>=3: ex["http_proto"]=toks[2]
            return _mk_res(pf, ex)

        for fn in [self._parse_cef,self._parse_leef,self._parse_rfc5424,self._parse_cri,self._parse_nginx_error,self._parse_spring_boot,self._parse_java_log,self._parse_python_log,self._parse_postgres,self._parse_logfmt]:
            r=fn(rem)
            if r: return r

        pf, ex = {}, {}
        mm=re.search(r'^<(\d{1,3})>', rem)
        if mm:
            rem=rem[len(mm.group(0)):].lstrip(' -:,|')
            v=int(mm.group(1))
            pf["severity"]={0:"CRITICAL",1:"CRITICAL",2:"CRITICAL",3:"ERROR",4:"WARNING",5:"INFO",6:"INFO",7:"DEBUG"}.get(v&7,"UNKNOWN")
            ex["facility"]=v>>3

        ts_iso, was_sys, rem = self.detect_timestamp(rem)
        if ts_iso: pf["timestamp"]=ts_iso
        if "severity" not in pf:
            mm=SEV_RE.search(rem)
            if mm and mm.start()==0:
                rem=rem[len(mm.group(0)):].lstrip(' -:,|')
                pf["severity"]=mm.group(1).upper()

        if ts_iso and was_sys:
            hm=re.match(r'^([a-zA-Z0-9_-]+)\s+([a-zA-Z0-9_.-]+)(?:\[(\d+)\])?:\s*', rem)
            if hm:
                pf["source"]=hm.group(1)
                ex["program"]=hm.group(2)
                if hm.group(3): ex["pid"]=hm.group(3)
                rem=rem[len(hm.group(0)):]

        mm=re.search(r'^\[([^\]]+)\]|^\(([^)]+)\)', rem)
        if mm:
            rem=rem[len(mm.group(0)):].lstrip(' -:,|')
            ex["context"]=mm.group(1) or mm.group(2)
            if "severity" not in pf:
                sm=SEV_RE.search(rem)
                if sm and sm.start()==0:
                    rem=rem[len(sm.group(0)):].lstrip(' -:,|')
                    pf["severity"]=sm.group(1).upper()

        mj=re.search(r'(\{.*\}|\[.*\])\s*$', rem)
        if mj:
            try:
                pj=json.loads(mj.group(1))
                if isinstance(pj, dict):
                    ex["json_payload"]=pj
                    rem=rem[:mj.start()].rstrip(' -:,|')
            except Exception:
                pass

        if rem: pf["message"]=rem.strip()

        ip=re.search(r'\b(?:\d{1,3}\.){3}\d{1,3}\b', log_entry)
        if ip:
            ex["ip"]=ip.group(0)
            pf.setdefault("source", ip.group(0))
        pm=re.search(r'\bport\s*[:=]?\s*(\d{2,5})\b', log_entry, re.I) or (re.search(rf"{re.escape(ip.group(0))}:(\d{{2,5}})\b", log_entry) if ip else None)
        if pm: ex["port"]=pm.group(1)
        um=re.search(r'(?:for\s+(?:invalid\s+user\s+)?|user[\s=:]+)([a-zA-Z0-9_.-]+)', log_entry, re.I)
        if um:
            uv=um.group(1)
            if uv.lower() not in ("invalid","authentication","to","the","a","an"):
                ex["user"]=uv

        for k, v in re.findall(r'([a-zA-Z0-9_-]+)=("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|[^ \t\n\r,;\]\}>\\)&]+)', log_entry):
            if v.startswith('"') and v.endswith('"'): v = v[1:-1]
            elif v.startswith("'") and v.endswith("'"): v = v[1:-1]
            ex.setdefault(k, v)

        return _mk_res(pf, ex)

    def parse_with_rule(self, log_entry, rule):
        method=rule.get("method")
        s=strip_ansi(log_entry).strip()
        if method=="json":
            try:
                pj=json.loads(s)
                if isinstance(pj, dict):
                    if "log" in pj and isinstance(pj["log"], str) and ("stream" in pj or "time" in pj):
                        inner=pj["log"].strip()
                        comp=self.parse_compositional(inner)
                        pf=comp["parsed_fields"]
                        ex=comp["extra"]
                        for k,v in pj.items():
                            if k!="log": ex[k]=v
                        return _mk_res(pf, ex)
                    if "t" in pj and isinstance(pj["t"], dict) and "$date" in pj["t"]:
                        pj["timestamp"]=pj.pop("t")["$date"]
                    if "s" in pj and "severity" not in pj:
                        pj["severity"]=pj.pop("s")
                    if "c" in pj and "source" not in pj:
                        pj["source"]=pj.pop("c")
                    return _mk_res(pj)
            except Exception:
                pass
            method="compositional"

        if method=="delimiter":
            delim=rule.get("delimiter")
            try:
                parts=next(csv.reader(io.StringIO(s), delimiter=delim))
            except Exception:
                parts=[p.strip() for p in s.split(delim)]
            parts=[p.strip() for p in parts if p.strip()]
            pf, ex, rests, ts_val, sev_val = {}, {}, [], None, None
            for p in parts:
                if not ts_val:
                    iso=parse_timestamp(p)
                    if iso:
                        ts_val=iso
                        continue
                if not sev_val and SEV_RE.match(p) and len(p)<=12:
                    sev_val=p.strip('[]').upper()
                    continue
                if '=' in p and ' ' not in p.split('=',1)[0]:
                    k,v=p.split('=',1)
                    ex[k.strip()]=v.strip()
                    continue
                rests.append(p)
            if not ts_val and not sev_val:
                return _mk_res({f"field_{i}": p for i,p in enumerate(parts)})
            if ts_val: pf["timestamp"]=ts_val
            if sev_val: pf["severity"]=sev_val
            if rests:
                msg_idx=max(range(len(rests)), key=lambda i: len(rests[i].split()))
                pf["message"]=rests[msg_idx]
                src=False
                for i,r in enumerate(rests):
                    if i==msg_idx: continue
                    if not src and len(r.split())==1:
                        pf["source"]=r
                        src=True
                    else:
                        ex[f"field_{i}"]=r
            return _mk_res(pf, ex)

        if method=="compositional":
            return self.parse_compositional(s)
        return _mk_res({"raw_message": s})
