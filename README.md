# Log Pre-processing

This project takes log messages in different formats and converts them into one common format.
It can handle formats such as JSON, syslog, Java logs, Kubernetes logs, CSV, and CEF.

## How it works

```text
Log message
    |
    v
Check for a format seen before
    |
    +--> Yes: use the saved format
    |
    +--> No: find the log pattern
              |
              v
        Check the format model
              |
              +--> Known format: use it
              |
              +--> New format: use an LLM if a key is available,
                              otherwise use simple rules
              |
              v
      Convert to the common log format
```

The common format includes the timestamp, source, event type, severity, message,
original log, and other extra fields.

The project remembers formats it has already seen. This makes later messages
faster to process.

## Project files

- `main.py` - starts the API
- `pipeline/` - reads, detects, and converts log messages
- `static/` - contains the web pages
- `tests/` - contains tests
- `models/` - contains the saved format model
- `run_demo.py` - demo script
- `collect.sh` - sends local logs to the API

## Built with

Python, FastAPI, Drain3, scikit-learn, pandas, and JavaScript.
