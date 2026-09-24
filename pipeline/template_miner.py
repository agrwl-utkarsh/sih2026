"""
Drain3 template-mining tier (Tier 2a/2b of the pipeline).

What this adds on top of the fingerprint cache:
  - Every line that misses the fingerprint cache is mined to a stable template
    (e.g. "node-<NUM> sshd[<NUM>]: Failed password for <IP>") in ~0.016 ms,
    offline, with zero API calls.
  - Rules learned by the discovery engine are keyed by TEMPLATE STRING
    (not by token-count fingerprint), so a line whose fields drifted out of
    the fingerprint cache's tolerance still resolves without re-calling an LLM.
  - Every brand-new template is recorded in a quarantine log (shadow mode),
    classifiable as novel by the scikit-learn gate, and visible at
    /api/logs/quarantine.

Enforcement is opt-in via env var:
    TPL_ENFORCE=1
        Novel templates are quarantined (heuristic parse, no LLM call) until
        the cluster has been seen TPL_GRADUATE_AFTER times, then ONE discovery
        call learns a rule for the whole cluster. Default is shadow mode
        (TPL_ENFORCE unset): discovery still runs immediately, identical to the
        pre-tier behavior, but template metadata is recorded for observability.

Optional rule persistence across serverless instances (fixes the cold-start
state loss): set UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN (a free
Vercel KV / Upstash database works). Without them, the rule map is in-memory
only, which is exactly the pre-existing cache behavior.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
from collections import OrderedDict

import requests

logger = logging.getLogger(__name__)

try:
    from drain3 import TemplateMiner
    from drain3.masking import MaskingInstruction
    from drain3.template_miner_config import TemplateMinerConfig

    logging.getLogger("drain3").setLevel(logging.WARNING)
    DRAIN3_AVAILABLE = True
except ImportError:  # pragma: no cover - drain3 is in requirements.txt
    TemplateMiner = None
    MaskingInstruction = None
    TemplateMinerConfig = None
    DRAIN3_AVAILABLE = False

MAX_QUARANTINE = 500
KV_TTL_SECONDS = 60 * 60 * 24 * 7  # learned rules live 7 days in KV

# Order matters: timestamps first (so their digits never reach <NUM>), then
# IPs/UUIDs/hex, then bare numbers. This is the single most influential knob
# for Drain3 accuracy (benchmarked: 24 clusters -> 12 at sim_th 0.5).
_MASKING = [
    (r"\d{4}[-/]\d{2}[-/]\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?", "TS"),
    (r"[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}", "TS"),
    (r"\d{2}/[A-Za-z]{3}/\d{4}(?::\d{2}:\d{2}:\d{2})?", "TS"),
    (r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", "IP"),
    (r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b", "UUID"),
    (r"\b[0-9a-fA-F]{16,}\b", "HEX"),
    (r"\b\d+\.\d+\b", "NUM"),
    (r"\b\d+\b", "NUM"),
]


def mask_line(line: str) -> str:
    """Apply the runtime masking rules WITHOUT the Drain tree. This is the
    deterministic feature text the format gate is trained and queried on:
    variant fields collapse (<IP>, <NUM>...) so the same family always lands
    in the same neighbourhood, on young and mature trees alike."""
    for pattern, mask in _MASKING:
        line = re.sub(pattern, mask, line)
    return line


def build_miner(sim_th: float = 0.5):
    """A TemplateMiner with the masking config used both at train time and
    at runtime. Keep this shared so templates are identical in both places."""
    cfg = TemplateMinerConfig()
    cfg.drain_sim_th = sim_th
    cfg.masking_instructions = [
        MaskingInstruction(pattern=p, mask_with=m) for p, m in _MASKING
    ]
    return TemplateMiner(config=cfg)


def _kv_key(template: str) -> str:
    return "sih:rule:" + hashlib.sha1(template.encode("utf-8")).hexdigest()[:16]


class TemplateMinerTier:
    """Thread-safe singleton tier; see module docstring for the flow."""

    def __init__(self):
        self.disabled = not DRAIN3_AVAILABLE
        self._lock = threading.Lock()
        self._miner = build_miner() if DRAIN3_AVAILABLE else None
        self._rules: dict[int, dict] = {}            # cluster_id -> rule (instance cache)
        self._templates_by_cluster: dict[int, str] = {}
        self._kv_seen: set[str] = set()              # templates already pulled from KV
        self._quarantine: OrderedDict[str, dict] = OrderedDict()
        self._pending_graduation: set[str] = set()
        # Occurrence counts per (line, family) — deliberately INDEPENDENT of the
        # Drain-keyed quarantine memo so cap eviction or template-ID drift cannot
        # keep a repeated novel format locked in quarantine forever: after
        # TPL_Q_GRADUATE_OCCURRENCES sightings the caller escalates it to the
        # discovery/LLM tier even though it never satisfied graduation volume.
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
        self.stats = {
            "mined": 0,
            "template_rule_hits": 0,
            "novel_templates": 0,
            "graduated_now": 0,
            "kv_backed_rules": 0,
        }
        self._kv_url = os.environ.get("UPSTASH_REDIS_REST_URL", "").rstrip("/")
        self._kv_token = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")

    # ---------------- config introspection ----------------

    def rule_backend(self) -> str:
        return "upstash" if (self._kv_url and self._kv_token) else "in-memory"

    # ---------------- mining ----------------

    def mine(self, line: str) -> tuple[str, int]:
        with self._lock:
            result = self._miner.add_log_message(line)
        return result["template_mined"], result["cluster_id"]

    # ---------------- rule store ----------------

    def _kv_get(self, kv_key: str) -> dict | None:
        url = f"{self._kv_url}/get/{kv_key}"
        try:
            r = requests.get(url, headers={"Authorization": f"Bearer {self._kv_token}"}, timeout=2)
            if r.status_code == 200:
                data = r.json()
                if data.get("result"):
                    self.stats["kv_backed_rules"] += 1
                    return json.loads(data["result"])
        except Exception as e:  # KV is best-effort; never break ingestion
            logger.warning("Upstash GET failed: %s", e)
        return None

    def _kv_set(self, kv_key: str, payload: dict) -> None:
        url = f"{self._kv_url}/set/{kv_key}"
        try:
            requests.post(
                url,
                headers={"Authorization": f"Bearer {self._kv_token}"},
                json=["SETEX", kv_key, KV_TTL_SECONDS, json.dumps(payload)],
                timeout=2,
            )
        except Exception as e:
            logger.warning("Upstash SET failed: %s", e)

    def lookup_rule(self, cluster_id: int, template: str) -> dict | None:
        if cluster_id in self._rules:
            return self._rules[cluster_id]
        if self._kv_url and self._kv_token and template not in self._kv_seen:
            rule = self._kv_get(_kv_key(template))
            self._kv_seen.add(template)
            if rule:
                self._rules[cluster_id] = rule
                return rule
        return None

    def learn_rule(self, template: str, rule: dict, cluster_id: int | None = None) -> None:
        """Store a rule under the cluster id (stable across the cluster's
        template mutations) and mirror it to KV keyed by the current template
        string so other instances can warm up from it."""
        if cluster_id is not None:
            self._rules[cluster_id] = rule
            self._templates_by_cluster[cluster_id] = template
        self._pending_graduation.discard(template)
        if self._kv_url and self._kv_token:
            self._kv_set(
                _kv_key(template),
                {"rule": rule, "template": template, "learned_at": time.time()},
            )

    # ---------------- quarantine ----------------

    def _record_template(self, template: str, sample: str, gate_info: dict) -> dict:
        entry = self._quarantine.get(template)
        if entry is None:
            entry = {
                "template": template,
                "count": 0,
                "samples": [],
                "first_seen": time.time(),
                "gate": gate_info,
            }
            self._quarantine[template] = entry
            self.stats["novel_templates"] += 1
        entry["count"] += 1
        entry["last_seen"] = time.time()
        if sample not in entry["samples"] and len(entry["samples"]) < 3:
            entry["samples"].append(sample[:300])
        self._quarantine.move_to_end(template)
        if len(self._quarantine) > MAX_QUARANTINE:
            self._quarantine.popitem(last=False)
        return entry

    # ---------------- decision ----------------

    def decide(self, line: str, gate) -> dict:
        """
        Returns one of:
          kind "rule"        -> known template with a stored rule
          kind "quarantined" -> (enforce mode only) novel template, withheld
                                from the discovery engine; count/threshold and
                                graduate_now tell the caller when to learn it
          kind "discover"    -> template not yet learned; caller runs discovery
        """
        if self.disabled:
            return {"kind": "discover", "template": None, "cluster_id": None, "gate": {}}

        template, cluster_id = self.mine(line)
        self.stats["mined"] += 1

        rule = self.lookup_rule(cluster_id, template)
        if rule is not None:
            self.stats["template_rule_hits"] += 1
            return {
                "kind": "rule",
                "template": template,
                "cluster_id": cluster_id,
                "rule": rule,
                "gate": {},
            }

        # query the gate with the deterministic masked line, not the
        # (young/mature-dependent) cluster template string
        gate_info = gate.inspect(mask_line(line)) if gate else {}
        entry = self._record_template(template, line, gate_info)

        kind = "discover"
        graduate_now = False
        occurrences = 0
        if self.enforce and gate_info.get("novel"):
            occ_key = (line, gate_info.get("family_guess"))
            self._q_counts[occ_key] = self._q_counts.get(occ_key, 0) + 1
            self._q_counts.move_to_end(occ_key)
            while len(self._q_counts) > MAX_QUARANTINE * 4:
                self._q_counts.popitem(last=False)
            occurrences = self._q_counts[occ_key]

        if (
            self.enforce
            and gate_info.get("novel")
            and entry["count"] < self.graduate_after
            and occurrences < self.q_occurrences
        ):
            kind = "quarantined"
        elif (
            self.enforce
            and gate_info.get("novel")
            and occurrences >= self.q_occurrences
        ):
            # repeated novel format: escalate to discovery regardless of the
            # graduation threshold — eviction/drift cannot stall it forever.
            kind = "escalated"
            self.stats["escalated"] = self.stats.get("escalated", 0) + 1
        elif (
            self.enforce
            and gate_info.get("novel")
            and entry["count"] >= self.graduate_after
            and template not in self._pending_graduation
        ):
            # exactly one graduation per template, ever; the rule learned by the
            # discovery call lands in the rule map and ends quarantine.
            self._pending_graduation.add(template)
            graduate_now = True
            self.stats["graduated_now"] += 1

        return {
            "kind": kind,
            "template": template,
            "cluster_id": cluster_id,
            "gate": gate_info,
            "quarantine_count": entry["count"],
            "occurrences": occurrences,
            "graduate_after": self.graduate_after,
            "graduate_now": graduate_now,
        }

    # ---------------- views / housekeeping ----------------

    def templates_view(self) -> dict:
        clusters = []
        if not self.disabled:
            for c in self._miner.drain.id_to_cluster.values():
                clusters.append(
                    {
                        "cluster_id": c.cluster_id,
                        "template": " ".join(map(str, c.log_template_tokens)),
                        "size": c.size,
                        "has_rule": c.cluster_id in self._rules,
                    }
                )
        clusters.sort(key=lambda c: c["size"], reverse=True)
        return {
            "drain3_available": DRAIN3_AVAILABLE,
            "enforce_mode": self.enforce,
            "rule_backend": self.rule_backend(),
            "clusters": len(clusters),
            "rules_learned": len(self._rules),
            "stats": dict(self.stats),
            "templates": clusters[:100],
        }

    def quarantine_view(self) -> dict:
        items = sorted(
            self._quarantine.values(), key=lambda e: e["count"], reverse=True
        )
        return {
            "enforce_mode": self.enforce,
            "novel_templates": len(items),
            "items": [dict(e, samples=e["samples"][:3]) for e in items[:100]],
        }

    def reset(self) -> None:
        """For tests: clean slate."""
        with self._lock:
            self._miner = build_miner() if DRAIN3_AVAILABLE else None
        self._rules.clear()
        self._kv_seen.clear()
        self._quarantine.clear()
        self._pending_graduation.clear()
        self._q_counts.clear()
        for k in self.stats:
            self.stats[k] = 0
        self.stats["escalated"] = 0
