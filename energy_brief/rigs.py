"""Free public rig-count pages; no paid API or guessed missing values.

AOGR republishes Baker Hughes weekly data. Basin previews are explicitly
secondary/unverified, and their 'As of' date is a page date, not an independently
confirmed Baker Hughes observation date. Do not use these as primary signals.
"""
from __future__ import annotations

import datetime as dt
import html
import re
from typing import Callable


def text_of(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace")
    text = re.sub(r"(?is)<(?:script|style)\b[^>]*>.*?</(?:script|style)>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def checked_date(value: str, fmt: str, today: dt.date) -> str:
    date = dt.datetime.strptime(value, fmt).date()
    age = (today - date).days
    if not 0 <= age <= 14:
        raise ValueError("rig source date is future or older than 14 days")
    return date.isoformat()


def parse_aogr(raw: bytes, today: dt.date) -> dict:
    text = text_of(raw)
    # Each match is bounded by the next dated row; a malformed current row must
    # never borrow values from the previous week's row.
    rows = re.split(r"(?<!\d)(\d{2}/\d{2}/\d{4})(?!\d)", text)
    dated = []
    for i in range(1, len(rows) - 1, 2):
        date = dt.datetime.strptime(rows[i], "%m/%d/%Y").date()
        body = rows[i + 1]
        if "Total Rigs" in body and "(Wk./Wk.)" in body:
            dated.append((date, body))
    if not dated:
        raise ValueError("AOGR current rig table missing")
    date, body = max(dated, key=lambda pair: pair[0])
    checked_date(date.isoformat(), "%Y-%m-%d", today)
    total = re.search(rf"Total Rigs\s+{date.year}\s*\(Wk\./Wk\.\)\s*([+\-]?\d+)\s+(\d+)\b", body)
    values = {}
    changes = {}
    if not total:
        raise ValueError("AOGR latest total missing")
    values["US_RIGS"] = int(total.group(2))
    changes["US_RIGS"] = int(total.group(1))
    for label, key in (("Oil", "OIL_RIGS"), ("Gas", "GAS_RIGS"), (r"Misc\.", "MISC_RIGS")):
        match = re.search(rf"{label}\s*\(Wk\./Wk\.\)\s*([+\-]?\d+)\s*\((\d+)\)", body)
        if not match:
            raise ValueError("AOGR latest component missing")
        values[key] = int(match.group(2))
        changes[key] = int(match.group(1))
    if any(not 0 <= value <= 10000 for value in values.values()):
        raise ValueError("rig count out of range")
    if values["US_RIGS"] != sum(values[key] for key in ("OIL_RIGS", "GAS_RIGS", "MISC_RIGS")):
        raise ValueError("AOGR total does not equal component counts")
    if changes["US_RIGS"] != sum(changes[key] for key in ("OIL_RIGS", "GAS_RIGS", "MISC_RIGS")):
        raise ValueError("AOGR weekly changes do not reconcile")
    return {"date": date.isoformat(), "counts": values, "changes": changes}


def parse_basin(raw: bytes, basin: str, today: dt.date) -> dict:
    labels = {"permian": "Permian Basin", "haynesville": "Haynesville Shale"}
    label = labels[basin]
    text = text_of(raw)
    # Bind both values to the headline/main card, before navigation or FAQ.
    headline = re.search(rf"{re.escape(label)} Rig Count\s+(?:Holds at|Rises to|Falls to|Drops to|Increases to|Decreases to)\s+(\d+)\s+Active Rigs", text, re.I)
    if not headline:
        raise ValueError("basin headline count missing")
    main = text[headline.end():].split("About the", 1)[0]
    card = re.search(r"\b(\d+)\s+Active Rigs\b.{0,200}?\bAs of\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})", main, re.I)
    if not card or card.group(1) != headline.group(1):
        raise ValueError("basin headline/card count mismatch")
    value = int(card.group(1))
    if not 0 <= value <= 10000:
        raise ValueError("basin count out of range")
    return {"value": value, "date": checked_date(card.group(2), "%B %d, %Y", today),
            "date_kind": "source_page_as_of", "quality": "secondary_unverified"}


def collect_rigs(fetch: Callable[[str], bytes], today: dt.date) -> dict:
    """Return independently dated observations and explicit partial failures.

    Fetch exceptions are intentionally reduced to their class names: callers
    may provide HTTP clients whose exception URLs contain credentials.
    """
    url = f"https://www.aogr.com/web-exclusives/us-rig-count/{today.year}"
    observations, errors = {}, {}
    try:
        result = parse_aogr(fetch(url), today)
        for key, value in result["counts"].items():
            observations[key] = {"value": value, "date": result["date"],
                "weekly_change": result["changes"][key], "url": url,
                "source": "AOGR / Baker Hughes", "quality": "secondary_reconciled",
                "date_kind": "observation"}
    except Exception as exc:
        errors["US_RIGS"] = f"unavailable: {type(exc).__name__}"
    for basin in ("permian", "haynesville"):
        key = basin.upper() + "_RIGS"
        basin_url = f"https://www.oilpriceapi.com/data/rig-count/{basin}"
        try:
            row = parse_basin(fetch(basin_url), basin, today)
            row.update(url=basin_url, source="OilPriceAPI public preview / Baker Hughes")
            observations[key] = row
        except Exception as exc:
            errors[key] = f"unavailable: {type(exc).__name__}"
    return {"date": max((row["date"] for row in observations.values()), default=None),
            "counts": {key: row["value"] for key, row in observations.items()},
            "observations": observations, "errors": errors, "url": url}
