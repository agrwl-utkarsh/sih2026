class Normalizer:
    def normalize(self, parsed_data: dict, raw_log: str) -> dict:
        fields = parsed_data.get("parsed_fields", {})
        extra = parsed_data.get("extra", {})
        
        # Map common aliases for standard fields
        aliases = {
            "level": "severity",
            "msg": "message",
            "message": "message",
            "ts": "timestamp",
            "timestamp": "timestamp",
            "time": "timestamp",
            "host": "source",
            "hostname": "source",
            "source": "source",
            "event": "event_type",
            "event_type": "event_type"
        }
        
        mapped_fields = {}
        for k, v in fields.items():
            lower_k = k.lower()
            if lower_k in aliases:
                mapped_fields[aliases[lower_k]] = v
            else:
                extra[k] = v
                
        severity = mapped_fields.get("severity")
        if isinstance(severity, str):
            severity = severity.lower()
        elif severity is not None:
            severity = str(severity)
        else:
            severity = "unknown"

        normalized = {
            "timestamp": mapped_fields.get("timestamp"),
            "source": mapped_fields.get("source", "unknown"),
            "event_type": mapped_fields.get("event_type", "unknown"),
            "severity": severity,
            "message": mapped_fields.get("message"),
            "raw": raw_log,
            "extra": extra
        }
        
        return normalized
