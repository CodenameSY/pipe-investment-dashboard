"""Read-only source diagnostics. Never print credentials or response bodies."""
import datetime as dt
import json
import os
import urllib.request
import urllib.error
ua = os.environ.get("SEC_USER_AGENT", "")
print(json.dumps({"check":"sec_header_validation","has_linebreak": "\\r" in ua or "\\n" in ua, "ascii_only":ua.isascii(), "has_at":"@" in ua, "outer_whitespace":ua != ua.strip()}),flush=True)
checks = [
 ("sec_default", "https://data.sec.gov/submissions/CIK0000046765.json", ua, None),
 ("sec_accept", "https://data.sec.gov/submissions/CIK0000046765.json", ua, "application/json"),
 ("wti_recent", "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DCOILWTICO&cosd=" + (dt.date.today()-dt.timedelta(days=30)).isoformat(), "Mozilla/5.0 EnergyBrief/1.0", None),
 ("rig_feed", "https://investor.deepwater.com/rss/news-releases.xml", "Mozilla/5.0 EnergyBrief/1.0", None),
]
for name, url, agent, accept in checks:
    headers = {"User-Agent":agent, "Accept-Encoding":"identity"}
    if accept: headers["Accept"]=accept
    result={"check":name}
    try:
        with urllib.request.urlopen(urllib.request.Request(url,headers=headers),timeout=15) as response:
            raw=response.read(2000000)
            result.update(status=response.status, type=response.headers.get("Content-Type"), encoding=response.headers.get("Content-Encoding"), size=len(raw))
        result["shape"] = "html" if raw.lstrip().startswith((b"<",b"<!")) else "json" if raw.lstrip().startswith(b"{") else "gzip" if raw.startswith(bytes([31,139])) else "other"
        if name.startswith("sec"):
            try:
                parsed=json.loads(raw)
                result["json_valid"]=True
                result["has_filings"]=isinstance(parsed,dict) and "filings" in parsed
            except (ValueError,UnicodeError) as exc:
                result["parse_error"]=type(exc).__name__
                result["position"]=getattr(exc,"pos",None)
        else:
            result["has_csv_header"]=b"observation_date,DCOILWTICO" in raw[:100]
    except Exception as exc:
        result.update(error=type(exc).__name__,http_status=getattr(exc,"code",None))
    print(json.dumps(result),flush=True)
