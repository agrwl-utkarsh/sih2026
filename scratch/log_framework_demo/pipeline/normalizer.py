class Normalizer:
    def normalize(self, parsed_data: dict, raw_log: str) -> dict:
        fields = parsed_data.get("parsed_fields", {})
        extra = parsed_data.get("extra", {})
        
        # Merge any fields that aren't the primary ones into extra
        # if they came from non-compositional parses (like json)
        for k, v in fields.items():
            if k not in ["timestamp", "severity", "message", "source", "event_type"]:
                extra[k] = v
                
        # The parser now directly identifies these if possible via compositional extraction
        normalized = {
            "timestamp": fields.get("timestamp"),
            "source": fields.get("source"),
            "event_type": fields.get("event_type", "unknown"),
            "severity": fields.get("severity", "unknown").lower() if fields.get("severity") else "unknown",
            "message": fields.get("message"),
            "raw": raw_log,
            "extra": extra
        }
        
        return normalized
