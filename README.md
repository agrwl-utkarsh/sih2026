# Log Pre-processing (SIH 2026)

Give it logs from anywhere (syslog, json, java/spring, k8s, csv, pipe, cef, whatever)
and it normalizes them into one common schema: timestamp, source, event_type,
severity, message, raw, extra.

Live demo: https://sih2026-w6sr.vercel.app

## how it works

```
log line
  -> fingerprint cache          (format already seen? done, no thinking)
  -> drain3 template            (same template has a learned rule? done, no LLM call)
  -> sklearn gate               (known family? or looks totally new?)
  -> LLM "what format is this?" (once per NEW format, only if a key is set)
  -> normalize to common schema
```

First time it sees a format it asks the LLM (or guesses with heuristics if no key),
remembers the answer, so the 2nd time the same format comes in it's instant.

## run it

```bash
pip install -r requirements.txt -r reqs-dev.txt
python run_demo.py        # starts the server on :8000 and runs a sample
# or
uvicorn main:app --host 0.0.0.0 --port 8000
```

then open http://localhost:8000 - paste logs (or pick a sample), hit ingest.
the "record explorer" button opens the per-record JSON view.

LLM keys are optional (without them it just uses heuristics):
- `GROQ_API_KEY` (free tier, good for the demo) or `GEMINI_API_KEY` or `ANTHROPIC_API_KEY`
- `python check_llm.py` to see which provider it will use

## the other files

- `pytest tests/ -v` - the tests
- `check_accuracy.py` - runs the pipeline over a generated corpus and prints accuracy numbers (needs `pip install -r reqs-pandas.txt`)
- `train_gate.py` - retrains the sklearn model (`models/gate.pkl`)
- `collect.sh` - tails a local log (syslog / journalctl / docker logs) and ships it to the API
- `static/` - the two frontend pages (console + record explorer)
- `vercel.json` - deployment config (that's how the live demo is hosted)

## tech

Python, FastAPI, Drain3, scikit-learn, pandas, bash - deployed on Vercel.

## team

- name here
- name here
- name here
