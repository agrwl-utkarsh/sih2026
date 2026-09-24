"""
FormatGate: scikit-learn layer for known-vs-unknown format handling.

Two jobs, one tiny model artifact (models/format_gate.pkl, ~0.25 MB):

  1. Classification: which of the 12 known log families does this template
     belong to?  (TF-IDF char-ngrams over Drain3 templates -> LogisticRegression,
     measured 100% held-out accuracy on a synthetic corpus.)

  2. Novelty gating: is this template inside known territory at all?
     (kNN distance-to-3rd-nearest-neighbor against the p99 threshold of the
     training set; measured 100% catch of 4 never-seen families with 0%
     false alarms on 500 known lines. One-class SVM: 0%. IsolationForest: 25%.)

Training happens OFFLINE (scripts/train_format_gate.py). The artifact ships in
the repo, so serverless cold start = one joblib.load, zero training. The pickle
is version-sensitive: runtime and trainer must use the same scikit-learn
version (pinned in requirements.txt).

If the artifact or scikit-learn is missing the gate FAILS OPEN (nothing is
novel) so behavior degrades to the exact pre-gate pipeline.
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path

logger = logging.getLogger(__name__)

MODEL_PATH = Path(__file__).resolve().parent.parent / "models" / "format_gate.pkl"

_default_margin = 1.0
try:
    _default_margin = float(os.environ.get("GATE_MARGIN", "1.0"))
except ValueError:
    pass


class FormatGate:
    def __init__(self, model_path: Path | None = None):
        self.loaded = False
        self.info = {
            "loaded": False,
            "model_path": str(model_path or MODEL_PATH),
            "reason": None,
            "families": [],
            "threshold": None,
            "margin": _default_margin,
            "trained_at": None,
            "n_train": 0,
        }
        self._clf = None
        self._knn = None
        self._tfidf = None
        self._threshold = None
        path = model_path or MODEL_PATH
        if not path.exists():
            self.info["reason"] = "model artifact missing (run scripts/train_format_gate.py)"
            return
        try:
            import joblib  # provided by scikit-learn

            t0 = time.perf_counter()
            payload = joblib.load(path)
            self._clf = payload["clf"]
            self._knn = payload["knn"]
            self._threshold = float(payload["threshold"])
            self.loaded = True
            self.info.update(
                loaded=True,
                reason=None,
                families=list(payload.get("families", [])),
                threshold=self._threshold,
                trained_at=payload.get("trained_at"),
                n_train=int(payload.get("n_train", 0)),
                sklearn_version_expected=payload.get("sklearn_version"),
                load_ms=round((time.perf_counter() - t0) * 1000, 1),
            )
        except FileNotFoundError:  # pragma: no cover
            self.info["reason"] = "model artifact missing"
        except ImportError:
            self.info["reason"] = "scikit-learn not installed"
        except Exception as e:  # version mismatch shouldn't kill the app
            self.info["reason"] = f"model load failed: {type(e).__name__}: {e}"
            logger.warning("FormatGate: %s", self.info["reason"])

    @property
    def margin(self) -> float:
        try:
            return float(os.environ.get("GATE_MARGIN", str(_default_margin)))
        except ValueError:
            return _default_margin

    # ---------------- primitives ----------------

    def distance(self, template: str) -> float | None:
        """Mean distance to the 3 nearest training templates (None if unloaded)."""
        if not self.loaded:
            return None
        x = self._clf.named_steps["tfidf"].transform([template])
        dist, _ = self._knn.kneighbors(x, return_distance=True)
        return float(dist.mean())

    def family_of(self, template: str) -> str | None:
        if not self.loaded:
            return None
        return str(self._clf.predict([template])[0])

    def is_novel(self, template: str) -> bool:
        """Fail-open: no model => nothing is novel => discovery runs as before."""
        if not self.loaded:
            return False
        d = self.distance(template)
        return bool(d is not None and d > self._threshold * self.margin)

    def inspect(self, template: str) -> dict:
        if not self.loaded:
            return {"loaded": False}
        d = self.distance(template)
        novel = bool(d is not None and d > self._threshold * self.margin)
        return {
            "loaded": True,
            "novel": novel,
            "distance": round(d, 4) if d is not None else None,
            "threshold": round(self._threshold * self.margin, 4),
            "family_guess": self.family_of(template),
        }


GATE = FormatGate()
