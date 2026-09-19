import datetime
import dateutil.parser
import re

MONTH_PATTERN = re.compile(r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*', re.IGNORECASE)

def parse_timestamp(value, now=None) -> str | None:
    if value is None or isinstance(value, bool) or value == "":
        return None
        
    try:
        # 1. Handle numeric epoch
        if isinstance(value, (int, float)):
            ts = float(value)
            # Seconds (1973 to 2100)
            if 1e8 <= ts <= 4.1e9:
                dt = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc)
                return dt.isoformat().replace("+00:00", "Z")
            # Milliseconds
            elif 1e11 <= ts <= 4.1e12:
                dt = datetime.datetime.fromtimestamp(ts / 1000.0, datetime.timezone.utc)
                return dt.isoformat().replace("+00:00", "Z")
            # Microseconds
            elif 1e14 <= ts <= 4.1e15:
                dt = datetime.datetime.fromtimestamp(ts / 1e6, datetime.timezone.utc)
                return dt.isoformat().replace("+00:00", "Z")
            # Nanoseconds
            elif 1e17 <= ts <= 4.1e18:
                dt = datetime.datetime.fromtimestamp(ts / 1e9, datetime.timezone.utc)
                return dt.isoformat().replace("+00:00", "Z")
            return None

        if not isinstance(value, str):
            value = str(value)

        clean_val = value.strip().strip("[]\"'()")
        if not clean_val:
            return None

        # Pure numeric string
        if clean_val.isdigit():
            val_int = int(clean_val)
            l = len(clean_val)
            if l == 10 and 1e8 <= val_int <= 4.1e9:
                dt = datetime.datetime.fromtimestamp(val_int, datetime.timezone.utc)
                return dt.isoformat().replace("+00:00", "Z")
            elif l == 13 and 1e11 <= val_int <= 4.1e12:
                dt = datetime.datetime.fromtimestamp(val_int / 1000.0, datetime.timezone.utc)
                return dt.isoformat().replace("+00:00", "Z")
            elif l == 16 and 1e14 <= val_int <= 4.1e15:
                dt = datetime.datetime.fromtimestamp(val_int / 1e6, datetime.timezone.utc)
                return dt.isoformat().replace("+00:00", "Z")
            elif l == 19 and 1e17 <= val_int <= 4.1e18:
                dt = datetime.datetime.fromtimestamp(val_int / 1e9, datetime.timezone.utc)
                return dt.isoformat().replace("+00:00", "Z")
            return None

        # Float string epoch e.g. "1726756800.123"
        if re.match(r"^\d{9,11}\.\d+$", clean_val):
            try:
                val_flt = float(clean_val)
                if 1e8 <= val_flt <= 4.1e9:
                    dt = datetime.datetime.fromtimestamp(val_flt, datetime.timezone.utc)
                    return dt.isoformat().replace("+00:00", "Z")
            except Exception:
                pass

        # String must contain digits and at least one time/date delimiter or month name
        if not re.search(r'\d', clean_val):
            return None
        if not (re.search(r'[-/:T\s]', clean_val) or MONTH_PATTERN.search(clean_val)):
            return None

        # Normalize comma separated fractional seconds: 14:32:10,123 -> 14:32:10.123
        norm_val = re.sub(r'(\d{2}:\d{2}:\d{2}),(\d{1,6})', r'\1.\2', clean_val)

        # Handle Apache / NCSA timestamp format: dd/Mon/yyyy:hh:mm:ss with optional timezone
        match_ncsa = re.match(r'^(\d{1,2}/[A-Za-z]{3}/\d{4}):(\d{2}:\d{2}:\d{2})(?:\s+([+\-]\d{4}))?$', norm_val)
        if match_ncsa:
            d_part, t_part, tz_part = match_ncsa.groups()
            normalized_dt_str = f"{d_part} {t_part}"
            if tz_part:
                normalized_dt_str += f" {tz_part}"
            try:
                dt = dateutil.parser.parse(normalized_dt_str)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=datetime.timezone.utc)
                dt = dt.astimezone(datetime.timezone.utc)
                iso = dt.isoformat()
                if iso.endswith("+00:00"):
                    iso = iso.replace("+00:00", "Z")
                if not iso.endswith("Z"):
                    iso += "Z"
                return iso
            except Exception:
                pass

        # Handle MongoDB $date or ISO string
        if "{" in norm_val and "$date" in norm_val:
            try:
                match_mongo = re.search(r'"\$date"\s*:\s*"([^"]+)"', norm_val)
                if match_mongo:
                    norm_val = match_mongo.group(1)
            except Exception:
                pass

        now_dt = now if now else datetime.datetime.now(datetime.timezone.utc)
        if isinstance(now_dt, str):
            now_dt = dateutil.parser.parse(now_dt)
        if now_dt.tzinfo is None:
            now_dt = now_dt.replace(tzinfo=datetime.timezone.utc)
            
        try:
            dt_leap = dateutil.parser.parse(norm_val, default=datetime.datetime(2004, 1, 1))
        except Exception:
            return None
            
        try:
            dt_non_leap = dateutil.parser.parse(norm_val, default=datetime.datetime(2001, 1, 1))
            is_missing_year = (dt_leap.year != dt_non_leap.year)
        except Exception:
            is_missing_year = True
            
        if is_missing_year:
            target_year = now_dt.year
            try:
                final_dt = dt_leap.replace(year=target_year)
            except ValueError: 
                return None
                
            if final_dt.tzinfo is None:
                final_dt = final_dt.replace(tzinfo=datetime.timezone.utc)
                
            if (final_dt - now_dt).total_seconds() > 86400:
                target_year -= 1
                try:
                    final_dt = dt_leap.replace(year=target_year)
                except ValueError:
                    return None
                if final_dt.tzinfo is None:
                    final_dt = final_dt.replace(tzinfo=datetime.timezone.utc)
                    
            dt = final_dt
        else:
            dt = dt_leap
            
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
            
        dt = dt.astimezone(datetime.timezone.utc)
        iso = dt.isoformat()
        if iso.endswith("+00:00"):
            iso = iso.replace("+00:00", "Z")
        if not iso.endswith("Z"):
            iso += "Z"
        return iso
    except Exception:
        return None
