#!/usr/bin/env python3
"""
Offline trainer for the FormatGate artifact (models/format_gate.pkl).

Labels come from a self-contained synthetic corpus mirroring the 12 families
the parser supports; the same Drain3 masking config as runtime
(pipeline.template_miner.build_miner) guarantees train/serve template parity.

Trains:
  - TF-IDF (char 2-4-grams) -> LogisticRegression  (family classification)
  - NearestNeighbors (k=3) + p99 distance threshold (novelty gate)

Validation printed at the end must pass or the script exits 1 (CI-friendly):
  - held-out family accuracy  >= 0.95
  - unknown-family catch rate >= 0.90   (4 families NEVER seen in training)

Usage:  python scripts/train_format_gate.py [--n-per-family 400]
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.template_miner import build_miner, mask_line  # noqa: E402

KNOWN_MIN_ACC = 0.95
UNKNOWN_MIN_CATCH = 0.90

# ---------------------------------------------------------------- corpus ----
HOSTS = ["node-01", "api-gw-03", "db-server-01", "k8s-worker-7", "web-front-2"]
_R = random.randint


def _json_line(level=None):
    return json.dumps({
        "timestamp": f"2026-09-{_R(1, 28):02d}T{_R(0, 23):02d}:{_R(0, 59):02d}:{_R(0, 59):02d}Z",
        "level": level or random.choice(["info", "error", "warn", "debug"]),
        "service": random.choice(["auth", "orders", "gateway", "users"]),
        "msg": random.choice(["token expired", "db conn failed", "login ok", "cache miss", "request served"]),
        "latency_ms": _R(1, 900),
        "req_id": "".join(random.choices("abcdef0123456789", k=16)),
    })


def gen_syslog():
    # covers the classic BSD-syslog messages a real /var/log/auth.log produces
    tail = random.choice([
        f"Failed password for {random.choice(['root','admin','alice','ubuntu'])} from 10.0.0.{_R(1,254)} port {_R(1024,65535)} ssh2",
        f"Failed password for invalid user {random.choice(['root','ops','qa'])} from 10.0.0.{_R(1,254)} port {_R(1024,65535)} ssh2",
        f"Accepted {random.choice(['password','publickey'])} for {random.choice(['root','admin','ubuntu','alice'])} from 10.0.0.{_R(1,254)} port {_R(1024,65535)} ssh2",
        f"session opened for user {random.choice(['root','ubuntu'])} by (uid={_R(0,1000)})",
        f"session closed for user {random.choice(['root','ubuntu'])}",
        f"({random.choice(['root','www-data'])}) CMD ({random.choice(['echo hi','run-parts /etc/cron.hourly','cd /tmp && bash subs.sh'])})",
        f"pam_unix(sshd:session): session opened for user {random.choice(['root','alice'])}",
    ])
    proc = "cron" if tail.startswith("(") else random.choice(["sshd", "sudo", "sshd", "sshd"])
    return (f"{random.choice(['Jan','Mar','Sep','Oct'])} {_R(1,28):2d} {_R(0,23):02d}:{_R(0,59):02d}:{_R(0,59):02d} "
            f"{random.choice(HOSTS)} {proc}[{_R(100,9999)}]: {tail}")


GENS = {
    "syslog_bsd": lambda: gen_syslog(),
    "syslog_rfc5424": lambda: (
        f"<{_R(0,191)}>1 2026-{_R(1,12):02d}-{_R(1,28):02d}T{_R(0,23):02d}:{_R(0,59):02d}:{_R(0,59):02d}.{_R(0,999):03d}Z "
        f"{random.choice(HOSTS)} evntslog {_R(100,9999)} ID47 - "
        f"{random.choice(['kernel: OOM killer invoked','service restarted','disk quota exceeded'])}"
    ),
    "json_structured": lambda: _json_line(),
    "spring_boot": lambda: (
        f"2026-09-{_R(1,28):02d} {_R(0,23):02d}:{_R(0,59):02d}:{_R(0,59):02d}.{_R(100,999)}  "
        f"{random.choice(['INFO','WARN','ERROR'])} {_R(1,9999)} --- [nio-{_R(1000,9999)}-exec-{_R(1,50)}] "
        f"o.s.b.w.embedded.tomcat.{random.choice(['CoyoteAdapter','TomcatWebServer'])}  : "
        f"{random.choice(['Started Application in','HikariPool-1 - Connection is not available','Unhandled exception'])} {_R(1,300)}"
    ),
    "python_logging": lambda: (
        f"{random.choice(['DEBUG','INFO','ERROR','WARNING'])}:{random.choice(['root','app.views','urllib3.connectionpool'])}:"
        f"{random.choice(['Connected to database successfully','Starting new HTTP request','Traceback detected'])}"
    ),
    "k8s_cri": lambda: (
        f"2026-09-{_R(1,28):02d}T{_R(0,23):02d}:{_R(0,59):02d}:{_R(0,59):02d}.{_R(0,999999999):09d}Z "
        f"{random.choice(['stdout','stderr'])} {random.choice(['F','P'])} "
        f"{random.choice(['Starting web server on :8080','Liveness probe failed','ContainerOOMKilled'])}"
    ),
    "nginx_err": lambda: (
        "2026/09/%02d %02d:%02d:%02d [error] %d#%d: *%d %s while reading response, client: 172.16.%d.%d"
        % (_R(1,28), _R(0,23), _R(0,59), _R(0,59), _R(100,9999), _R(0,9), _R(1,9999),
           random.choice(["open() /favicon.ico failed","upstream timed out connecting","connect() failed"]),
           _R(0,255), _R(1,254))
    ),
    "cef": lambda: (
        f"CEF:0|{random.choice(['SecurityCo','Acme'])}|{random.choice(['Firewall','IDS','AFE'])}|1.0|{_R(100,999)}|"
        f"{random.choice(['Packet dropped','Intrusion detected','Signature violation'])}|{_R(1,10)}|"
        f"src=10.0.0.{_R(1,254)} dst=10.0.1.{_R(1,254)} spt={_R(1024,65535)} dpt=80"
    ),
    "logfmt": lambda: (
        f"ts=2026-09-{_R(1,28):02d}T{_R(0,23):02d}:00:00Z level={random.choice(['error','info','warn'])} "
        f"caller={random.choice(['main.go','server.go:42'])} "
        f'msg="{random.choice(["crash detected","request served","cache miss"])}" thread_id={_R(1,64)} dur={_R(1,900)}ms'
    ),
    "postgres": lambda: (
        f"2026-09-{_R(1,28):02d} {_R(0,23):02d}:{_R(0,59):02d}:{_R(0,59):02d}.{_R(0,999):03d} UTC [{_R(100,99999)}] "
        f"{random.choice(['postgres','mydb'])}@{random.choice(['mydb','users'])} {random.choice(['LOG','ERROR'])}:  "
        f"duration: {_R(1,9000)}.{_R(100,999)} ms {random.choice(['statement: SELECT * FROM users','idle in transaction'])}"
    ),
    "ncsa_combined": lambda: (
        f"192.168.{_R(0,255)}.{_R(1,254)} - {random.choice(['john','alice','-'])} "
        f"[{_R(1,28):02d}/Sep/2026:{_R(0,23):02d}:{_R(0,59):02d}:{_R(0,59):02d} +0000] "
        f"\"{random.choice(['GET','POST','PUT'])} /{random.choice(['index.html','api/v1/login','static/app.js'])} HTTP/1.1\" "
        f"{random.choice([200,301,404,500])} {_R(50,90000)} \"https://google.com\" \"Mozilla/5.0\""
    ),
    "app_generic_kv": lambda: (
        f"[2026-09-{_R(1,28):02d}T{_R(0,23):02d}:{_R(0,59):02d}:{_R(0,59):02d}Z] {random.choice(['CRITICAL','ERROR','WARN'])} "
        f"{random.choice(['PaymentGateway','OrderService','AuthService'])} "
        f"Transaction txn-{_R(1000,9999)} failed due to timeout after {_R(100,9000)}ms"
    ),
}

ALL_FAMILIES = sorted(GENS)

# Families the model NEVER sees; used only to validate the novelty gate.
UNKNOWN = {
    "aws_cloudtrail": lambda: json.dumps({
        "eventVersion": "1.09", "eventSource": "s3.amazonaws.com", "eventName": "GetObject",
        "userIdentity": {"type": "IAMUser", "userName": f"user{_R(1,999)}"},
        "sourceIPAddress": f"52.14.{_R(0,255)}.{_R(1,254)}",
        "requestParameters": {"bucketName": "logs-2026"},
    }),
    "windows_evtxml": lambda: (
        "<Event xmlns='http://schemas.microsoft.com/win/2004/08/events/event'>"
        "<System><Provider Name='Microsoft-Windows-Security-Auditing'/><EventID>4625</EventID>"
        f"<Level>{_R(0,5)}</Level><TimeCreated SystemTime='2026-09-13T10:00:00.000Z'/></System></Event>"
    ),
    "juniper_netconf": lambda: (
        f"Sep {_R(1,28)} {_R(0,23):02d}:{_R(0,59):02d}:{_R(0,59):02d} {random.choice(['r0','r1'])} {random.choice(['IFL','chassid'])}: "
        f"{random.choice(['mib2d','dcd'])}[{_R(100,9999)}]: {random.choice(['mgmt ifd operation error','link mode changed to 10G'])} {_R(0,9999)}"
    ),
    "oracle_audit": lambda: (
        f"WARNING: more information in Audit Trail file {_R(1,999)}.log ORA-{_R(1000,9999)} detected at {_R(0,23)}:{_R(0,59)}"
    ),
}


def make_corpus(n_per: int, gens: dict) -> tuple[list[str], list[str]]:
    X, y = [], []
    for fam, gen in gens.items():
        for _ in range(n_per):
            X.append(gen())
            y.append(fam)
    idx = list(range(len(X)))
    random.shuffle(idx)
    return [X[i] for i in idx], [y[i] for i in idx]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-per-family", type=int, default=400)
    ap.add_argument("--output", default=str(Path(__file__).resolve().parent.parent / "models" / "format_gate.pkl"))
    ap.add_argument("--seed", type=int, default=11)
    args = ap.parse_args()
    random.seed(args.seed)

    import joblib
    import numpy as np
    import sklearn
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import accuracy_score
    from sklearn.model_selection import train_test_split
    from sklearn.neighbors import NearestNeighbors
    from sklearn.pipeline import Pipeline

    miner = build_miner()

    def mine(lines):
        """Gate features are the deterministic MASKED LINES (same regexes as the
        runtime), not tree maturation snapshots; the tree is only used here to
        report cluster count and introspect quality."""
        for l in lines:
            miner.add_log_message(l)
        return [mask_line(l) for l in lines]

    print(f"[*] generating {args.n_per_family}/family across {len(ALL_FAMILIES)} known families")
    X, y = make_corpus(args.n_per_family, GENS)
    t0 = time.perf_counter()
    Xtp = mine(X)
    print(f"[*] masked {len(X)} lines in {time.perf_counter()-t0:.2f}s; drain quality: {len(miner.drain.id_to_cluster)} clusters")

    Xtr, Xte, ytr, yte = train_test_split(Xtp, y, test_size=0.2, random_state=args.seed, stratify=y)

    clf = Pipeline(steps=[
        ("tfidf", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), sublinear_tf=True, min_df=2, max_features=10000)),
        ("lr", LogisticRegression(max_iter=2000, C=8.0)),
    ])
    t0 = time.perf_counter()
    clf.fit(Xtr, ytr)
    acc = accuracy_score(yte, clf.predict(Xte))
    print(f"[*] classifier fit in {time.perf_counter()-t0:.2f}s | held-out family accuracy: {acc*100:.2f}%")

    tfidf = clf.named_steps["tfidf"]
    knn = NearestNeighbors(n_neighbors=3).fit(tfidf.transform(Xtr))

    # Honest calibration: held-out train lines are members of the same finite
    # template multiset as train (distance ~0 -> vacuous). Calibrate instead on
    # an INDEPENDENT corpus of the same families but with hosts the training
    # set never saw -> this measures true generalization drift.
    global HOSTS
    orig_hosts, HOSTS = HOSTS, ["srv-a", "hq-db-1", "edge-9", "mail-2", "proxy-7"]
    Xcal, ycal = make_corpus(120, GENS)
    Xcal_tp = mine(Xcal)
    HOSTS = orig_hosts
    cal_dist = knn.kneighbors(tfidf.transform(Xcal_tp), return_distance=True)[0].mean(axis=1)
    threshold = max(float(np.percentile(cal_dist, 99)), 0.02)
    cal_false_alarm = float(np.mean(cal_dist > threshold))
    holdout_known_dist = knn.kneighbors(tfidf.transform(Xte), return_distance=True)[0].mean(axis=1)
    print(f"[*] novelty gate: kNN p99 on foreign-host calibration = {threshold:.4f} "
          f"(calibration false-alarm {cal_false_alarm*100:.1f}%; "
          f"in-sample held-out dist max {holdout_known_dist.max():.4f})")
    false_alarm = cal_false_alarm

    # Validate against families never seen in training
    xu, yu = make_corpus(60, UNKNOWN)
    xutp = mine(xu)
    dist_u = knn.kneighbors(tfidf.transform(xutp), return_distance=True)[0].mean(axis=1)
    caught = dist_u > threshold
    per_family = {
        fam: round(float(caught[[i for i, t in enumerate(yu) if t == fam]].mean()), 3)
        for fam in UNKNOWN
    }
    catch_rate = float(np.mean(caught))
    print(f"[*] novelty catch rate on never-seen families: {catch_rate*100:.1f}%  {per_family}")

    payload = {
        "clf": clf,
        "knn": knn,
        "threshold": threshold,
        "families": ALL_FAMILIES,
        "false_alarm_heldout": false_alarm,
        "heldout_accuracy": float(acc),
        "unknown_catch_rate": catch_rate,
        "trained_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "n_train": len(Xtr),
        "n_clusters_seen": len(miner.drain.id_to_cluster),
        "sklearn_version": sklearn.__version__,
        "masking_version": 1,
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(payload, args.output)
    size_kb = Path(args.output).stat().st_size / 1024
    print(f"[+] wrote {args.output} ({size_kb:.0f} KB) with sklearn {sklearn.__version__}")

    ok = acc >= KNOWN_MIN_ACC and catch_rate >= UNKNOWN_MIN_CATCH
    print(f"[{'OK' if ok else 'FAIL'}] gates: acc>={KNOWN_MIN_ACC}, catch>={UNKNOWN_MIN_CATCH}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
