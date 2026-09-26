import datetime, re
import dateutil.parser

MONTH_RE = re.compile(r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*', re.I)
EPOCH_RANGES = [(1e8, 4.1e9, 1), (1e11, 4.1e12, 1e3), (1e14, 4.1e15, 1e6), (1e17, 4.1e18, 1e9)]
LEN_DIV = {10: 1, 13: 1e3, 16: 1e6, 19: 1e9}

def _utc_iso(dt: datetime.datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    dt = dt.astimezone(datetime.timezone.utc)
    iso = dt.isoformat()
    return iso.replace("+00:00", "Z") if iso.endswith("+00:00") else (iso if iso.endswith("Z") else iso + "Z")

def _from_epoch(v: float) -> str | None:
    for lo, hi, div in EPOCH_RANGES:
        if lo <= v <= hi:
            return _utc_iso(datetime.datetime.fromtimestamp(v / div, datetime.timezone.utc))
    return None

def parse_timestamp(value, now=None) -> str | None:
    if value is None or isinstance(value, bool) or value == "":
        return None
    try:
        if isinstance(value, (int, float)):
            return _from_epoch(float(value))

        s = str(value).strip().strip("[]\"'()")
        if not s:
            return None

        if s.isdigit():
            div = LEN_DIV.get(len(s))
            if div:
                iv = int(s)
                # quick range check using EPOCH_RANGES
                for lo, hi, d in EPOCH_RANGES:
                    if d == div and lo <= iv / (1 if d == 1 else 1) <= hi or (div == 1 and lo <= iv <= hi):
                        if (div == 1 and 1e8 <= iv <= 4.1e9) or div != 1:
                            return _utc_iso(datetime.datetime.fromtimestamp(iv / div, datetime.timezone.utc))
            return None

        if re.match(r"^\d{9,11}\.\d+$", s):
            try:
                fv = float(s)
                if 1e8 <= fv <= 4.1e9:
                    return _utc_iso(datetime.datetime.fromtimestamp(fv, datetime.timezone.utc))
            except Exception:
                pass

        if not re.search(r"\d", s):
            return None
        if not (re.search(r"[-/:T\s]", s) or MONTH_RE.search(s)):
            return None

        s = re.sub(r"(\d{2}:\d{2}:\d{2}),(\d{1,6})", r"\1.\2", s)

        m = re.match(r"^(\d{1,2}/[A-Za-z]{3}/\d{4}):(\d{2}:\d{2}:\d{2})(?:\s+([+\-]\d{4}))?$", s)
        if m:
            d_part, t_part, tz = m.groups()
            txt = f"{d_part} {t_part}" + (f" {tz}" if tz else "")
            try:
                return _utc_iso(dateutil.parser.parse(txt))
            except Exception:
                pass

        if "{" in s and "$date" in s:
            mm = re.search(r'"\$date"\s*:\s*"([^"]+)"', s)
            if mm:
                s = mm.group(1)

        now_dt = now or datetime.datetime.now(datetime.timezone.utc)
        if isinstance(now_dt, str):
            now_dt = dateutil.parser.parse(now_dt)
        if now_dt.tzinfo is None:
            now_dt = now_dt.replace(tzinfo=datetime.timezone.utc)

        try:
            dt_leap = dateutil.parser.parse(s, default=datetime.datetime(2004, 1, 1))
        except Exception:
            return None
        try:
            dt_non = dateutil.parser.parse(s, default=datetime.datetime(2001, 1, 1))
            missing_year = dt_leap.year != dt_non.year
        except Exception:
            missing_year = True

        if missing_year:
            try:
                dt = dt_leap.replace(year=now_dt.year)
            except ValueError:
                return None
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
            if (dt - now_dt).total_seconds() > 86400:
                try:
                    dt = dt_leap.replace(year=now_dt.year - 1)
                except ValueError:
                    return None
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=datetime.timezone.utc)
        else:
            dt = dt_leap

        return _utc_iso(dt)
    except Exception:
        return None
