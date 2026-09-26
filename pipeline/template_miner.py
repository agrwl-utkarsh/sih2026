from __future__ import annotations
import hashlib, json, logging, os, re, threading, time
from collections import OrderedDict
import requests

logger = logging.getLogger(__name__)
try:
    from drain3 import TemplateMiner
    from drain3.masking import MaskingInstruction
    from drain3.template_miner_config import TemplateMinerConfig
    logging.getLogger("drain3").setLevel(logging.WARNING)
    DRAIN3_AVAILABLE = True
except ImportError:
    TemplateMiner = MaskingInstruction = TemplateMinerConfig = None
    DRAIN3_AVAILABLE = False

MAX_QUARANTINE = 500
KV_TTL = 60*60*24*7

_MASKING = [
    (r"\d{4}[-/]\d{2}[-/]\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+\-]\d{2}:?\d{2})?", "TS"),
    (r"[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}", "TS"),
    (r"\d{2}/[A-Za-z]{3}/\d{4}(?::\d{2}:\d{2}:\d{2})?", "TS"),
    (r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", "IP"),
    (r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b", "UUID"),
    (r"\b[0-9a-fA-F]{16,}\b", "HEX"),
    (r"\b\d+\.\d+\b", "NUM"),
    (r"\b\d+\b", "NUM"),
]

def mask_line(line: str) -> str:
    for pat, mk in _MASKING:
        line = re.sub(pat, mk, line)
    return line

def build_miner(sim_th=0.5):
    cfg = TemplateMinerConfig()
    cfg.drain_sim_th = sim_th
    cfg.masking_instructions = [MaskingInstruction(pattern=p, mask_with=m) for p, m in _MASKING]
    return TemplateMiner(config=cfg)

def _kv_key(t: str) -> str:
    return "sih:rule:" + hashlib.sha1(t.encode()).hexdigest()[:16]

class TemplateMinerTier:
    def __init__(self):
        self.disabled = not DRAIN3_AVAILABLE
        self._lock = threading.Lock()
        self._miner = build_miner() if DRAIN3_AVAILABLE else None
        self._rules: dict[int, dict] = {}
        self._kv_seen: set[str] = set()
        self._quarantine: OrderedDict[str, dict] = OrderedDict()
        self._pending: set[str] = set()
        self._q_counts: OrderedDict[tuple[str, str | None], int] = OrderedDict()
        self.enforce = os.environ.get("TPL_ENFORCE") == "1"
        try:
            self.q_occurrences = max(2, int(os.environ.get("TPL_Q_GRADUATE_OCCURRENCES", "5")))
        except ValueError:
            self.q_occurrences = 5
        try:
            self.graduate_after = max(1, int(os.environ.get("TPL_GRADUATE_AFTER", "8")))
        except ValueError:
            self.graduate_after = 8
        self.stats = {"mined":0,"template_rule_hits":0,"novel_templates":0,"graduated_now":0,"kv_backed_rules":0,"escalated":0}
        self._kv_url = os.environ.get("UPSTASH_REDIS_REST_URL","").rstrip("/")
        self._kv_token = os.environ.get("UPSTASH_REDIS_REST_TOKEN","")

    def rule_backend(self) -> str:
        return "upstash" if (self._kv_url and self._kv_token) else "in-memory"

    def mine(self, line: str):
        with self._lock:
            r = self._miner.add_log_message(line)
        return r["template_mined"], r["cluster_id"]

    def _kv_req(self, method, url, **kw):
        try:
            fn = requests.get if method=="GET" else requests.post
            hdr = {"Authorization": f"Bearer {self._kv_token}"}
            resp = fn(url, headers=hdr, timeout=2, **kw)
            return resp
        except Exception as e:
            logger.warning("Upstash %s failed: %s", method, e)
            return None

    def _kv_get(self, k: str):
        r = self._kv_req("GET", f"{self._kv_url}/get/{k}")
        if r and r.status_code==200:
            data = r.json()
            if data.get("result"):
                self.stats["kv_backed_rules"]+=1
                return json.loads(data["result"])
        return None

    def _kv_set(self, k: str, payload: dict):
        self._kv_req("POST", f"{self._kv_url}/set/{k}", json=["SETEX", k, KV_TTL, json.dumps(payload)])

    def lookup_rule(self, cid: int, tmpl: str):
        if cid in self._rules:
            return self._rules[cid]
        if self._kv_url and self._kv_token and tmpl not in self._kv_seen:
            rule = self._kv_get(_kv_key(tmpl))
            self._kv_seen.add(tmpl)
            if rule:
                self._rules[cid]=rule
                return rule
        return None

    def learn_rule(self, tmpl: str, rule: dict, cid: int | None = None):
        if cid is not None:
            self._rules[cid]=rule
        self._pending.discard(tmpl)
        if self._kv_url and self._kv_token:
            self._kv_set(_kv_key(tmpl), {"rule": rule, "template": tmpl, "learned_at": time.time()})

    def _record(self, tmpl: str, sample: str, gate_info: dict):
        e = self._quarantine.get(tmpl)
        if e is None:
            e = {"template": tmpl, "count":0, "samples":[], "first_seen": time.time(), "gate": gate_info}
            self._quarantine[tmpl]=e
            self.stats["novel_templates"]+=1
        e["count"]+=1
        e["last_seen"]=time.time()
        if sample not in e["samples"] and len(e["samples"])<3:
            e["samples"].append(sample[:300])
        self._quarantine.move_to_end(tmpl)
        if len(self._quarantine)>MAX_QUARANTINE:
            self._quarantine.popitem(last=False)
        return e

    def decide(self, line: str, gate) -> dict:
        if self.disabled:
            return {"kind":"discover","template":None,"cluster_id":None,"gate":{}}
        tmpl, cid = self.mine(line)
        self.stats["mined"]+=1
        rule = self.lookup_rule(cid, tmpl)
        if rule is not None:
            self.stats["template_rule_hits"]+=1
            return {"kind":"rule","template":tmpl,"cluster_id":cid,"rule":rule,"gate":{}}

        gate_info = gate.inspect(mask_line(line)) if gate else {}
        entry = self._record(tmpl, line, gate_info)

        kind, grad_now, occ = "discover", False, 0
        if self.enforce and gate_info.get("novel"):
            key = (line, gate_info.get("family_guess"))
            self._q_counts[key]=self._q_counts.get(key,0)+1
            self._q_counts.move_to_end(key)
            while len(self._q_counts)>MAX_QUARANTINE*4:
                self._q_counts.popitem(last=False)
            occ = self._q_counts[key]

        if self.enforce and gate_info.get("novel"):
            if entry["count"] < self.graduate_after and occ < self.q_occurrences:
                kind = "quarantined"
            elif occ >= self.q_occurrences:
                kind = "escalated"
                self.stats["escalated"]+=1
            elif entry["count"] >= self.graduate_after and tmpl not in self._pending:
                self._pending.add(tmpl)
                grad_now = True
                self.stats["graduated_now"]+=1

        return {"kind":kind,"template":tmpl,"cluster_id":cid,"gate":gate_info,"quarantine_count":entry["count"],"occurrences":occ,"graduate_after":self.graduate_after,"graduate_now":grad_now}

    def templates_view(self):
        clusters=[]
        if not self.disabled:
            for c in self._miner.drain.id_to_cluster.values():
                clusters.append({"cluster_id":c.cluster_id,"template":" ".join(map(str,c.log_template_tokens)),"size":c.size,"has_rule":c.cluster_id in self._rules})
        clusters.sort(key=lambda c:c["size"], reverse=True)
        return {"drain3_available":DRAIN3_AVAILABLE,"enforce_mode":self.enforce,"rule_backend":self.rule_backend(),"clusters":len(clusters),"rules_learned":len(self._rules),"stats":dict(self.stats),"templates":clusters[:100]}

    def quarantine_view(self):
        items=sorted(self._quarantine.values(), key=lambda e:e["count"], reverse=True)
        return {"enforce_mode":self.enforce,"novel_templates":len(items),"items":[dict(e,samples=e["samples"][:3]) for e in items[:100]]}

    def reset(self) -> dict:
        """Drop mined templates, learned rules and quarantine. Returns counts cleared."""
        with self._lock:
            n_clusters = len(self._miner.drain.id_to_cluster) if self._miner else 0
            self._miner = build_miner() if DRAIN3_AVAILABLE else None
        cleared = {"templates": n_clusters, "template_rules": len(self._rules), "quarantine": len(self._quarantine)}
        self._rules.clear(); self._kv_seen.clear(); self._quarantine.clear(); self._pending.clear(); self._q_counts.clear()
        for k in self.stats:
            self.stats[k]=0
        return cleared
