import datetime
import dateutil.parser
import re

def parse_timestamp(value, now=None) -> str | None:
    if value is None or isinstance(value, bool) or value == "":
        return None
        
    try:
        if isinstance(value, (int, float)):
            ts = float(value)
            if ts > 1e11:
                ts = ts / 1000.0
            dt = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc)
            return dt.isoformat().replace("+00:00", "Z")
            
        if isinstance(value, str) and value.isdigit():
            if len(value) in (10, 13):
                ts = float(value)
                if ts > 1e11:
                    ts = ts / 1000.0
                dt = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc)
                return dt.isoformat().replace("+00:00", "Z")
                
        if not isinstance(value, str):
            value = str(value)

        # Handle Apache / NCSA timestamp format: dd/Mon/yyyy:hh:mm:ss with optional timezone
        clean_val = value.strip('[]')
        match_ncsa = re.match(r'^(\d{1,2}/[A-Za-z]{3}/\d{4}):(\d{2}:\d{2}:\d{2})(?:\s+([+\-]\d{4}))?$', clean_val)
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
                
        now_dt = now if now else datetime.datetime.now(datetime.timezone.utc)
        if isinstance(now_dt, str):
            now_dt = dateutil.parser.parse(now_dt)
        if now_dt.tzinfo is None:
            now_dt = now_dt.replace(tzinfo=datetime.timezone.utc)
            
        try:
            dt_leap = dateutil.parser.parse(value, default=datetime.datetime(2004, 1, 1))
        except Exception:
            return None
            
        try:
            dt_non_leap = dateutil.parser.parse(value, default=datetime.datetime(2001, 1, 1))
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
