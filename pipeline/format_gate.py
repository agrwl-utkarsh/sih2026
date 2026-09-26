from __future__ import annotations
import logging, os, time
from pathlib import Path

logger = logging.getLogger(__name__)
MODEL_PATH = Path(__file__).resolve().parent.parent / "models" / "format_gate.pkl"
GATE_FEATURE_VERSION = 2
try:
    _DEF_MARGIN = float(os.environ.get("GATE_MARGIN", "1.0"))
except ValueError:
    _DEF_MARGIN = 1.0

class FormatGate:
    def __init__(self, model_path: Path | None = None):
        self.loaded = False
        self._clf = self._knn = self._threshold = None
        self.info = {"loaded": False, "model_path": str(model_path or MODEL_PATH), "reason": None, "families": [], "threshold": None, "margin": _DEF_MARGIN, "trained_at": None, "n_train": 0}
        path = model_path or MODEL_PATH
        if not path.exists():
            self.info["reason"] = "model artifact missing (run scripts/train_format_gate.py)"
            return
        try:
            import joblib
            t0 = time.perf_counter()
            p = joblib.load(path)
            if p.get("gate_version") != GATE_FEATURE_VERSION:
                raise ValueError(f"gate feature version {p.get('gate_version')} != runtime {GATE_FEATURE_VERSION} — retrain")
            self._clf, self._knn, self._threshold = p["clf"], p["knn"], float(p["threshold"])
            self.loaded = True
            self.info.update(loaded=True, reason=None, gate_version=GATE_FEATURE_VERSION, families=list(p.get("families", [])), threshold=self._threshold, trained_at=p.get("trained_at"), n_train=int(p.get("n_train", 0)), sklearn_version_expected=p.get("sklearn_version"), load_ms=round((time.perf_counter()-t0)*1000,1))
        except FileNotFoundError:
            self.info["reason"] = "model artifact missing"
        except ImportError:
            self.info["reason"] = "scikit-learn not installed"
        except Exception as e:
            self.info["reason"] = f"model load failed: {type(e).__name__}: {e}"
            logger.warning("FormatGate: %s", self.info["reason"])

    @property
    def margin(self) -> float:
        try:
            return float(os.environ.get("GATE_MARGIN", str(_DEF_MARGIN)))
        except ValueError:
            return _DEF_MARGIN

    def distance(self, template: str) -> float | None:
        if not self.loaded:
            return None
        x = self._clf.named_steps["tfidf"].transform([template])
        dist, _ = self._knn.kneighbors(x, return_distance=True)
        return float(dist.mean())

    def family_of(self, template: str) -> str | None:
        return str(self._clf.predict([template])[0]) if self.loaded else None

    def is_novel(self, template: str) -> bool:
        if not self.loaded:
            return False
        d = self.distance(template)
        return bool(d is not None and d > self._threshold * self.margin)

    def inspect(self, template: str) -> dict:
        if not self.loaded:
            return {"loaded": False}
        d = self.distance(template)
        return {"loaded": True, "gate_version": GATE_FEATURE_VERSION, "novel": bool(d is not None and d > self._threshold * self.margin), "distance": round(d, 4) if d is not None else None, "threshold": round(self._threshold * self.margin, 4), "family_guess": self.family_of(template)}

GATE = FormatGate()
