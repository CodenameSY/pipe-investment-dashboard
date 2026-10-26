"""Daily SEC/WTI brief for Telegram. Python standard library only.

SEC access requires an honest SEC_USER_AGENT containing organization and contact.
The state file is intentionally ordinary JSON so a scheduled job can persist it.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import email.utils
import hashlib
import html
import io
import json
import os
import re
import socket
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


SEC_TICKERS = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
FRED_WTI = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DCOILWTICO"
SECTORS = {
    "Land": ("HP", "PTEN"),
    "Services": ("HAL", "SLB", "WFRD", "BKR"),
    "Offshore": ("NE", "SDRL", "RIG", "VAL"),
}
DEFAULT_TICKERS = ("HP", "PTEN", "HAL", "SLB", "WFRD", "RIG", "NE", "SDRL", "VAL")
OPTIONAL_TICKERS = ("BKR",)
FILINGS = {"8-K", "8-K/A", "10-Q", "10-Q/A", "10-K", "10-K/A", "6-K", "6-K/A", "20-F", "20-F/A"}
DIRECT_8K_ITEMS = {"1.01": "중요 계약", "2.02": "실적 발표", "2.05": "구조조정·사업 철수 비용"}
RELEVANT_TERMS = {
    "실적": (r"\b(?:financial|quarterly|annual) results\b", r"\bearnings (?:release|results)\b"),
    "수주·계약": (r"\bcontract award\b", r"\b(?:rig|drilling) contract\b", r"\bbacklog\b"),
    "전망": (r"\bguidance\b", r"\boutlook\b"),
    "자본 배분": (r"\bdividend\b", r"\bshare repurchase\b", r"\bbuyback\b"),
    "사업 구조": (r"\bacquisition\b", r"\bmerger\b", r"\bimpairment\b", r"\brestructuring\b"),
}
MAX_MESSAGE = 3500
PUBLIC_USER_AGENT = "Mozilla/5.0 EnergyBrief/1.0"


class SourceError(Exception):
    pass


class DefiniteSendError(Exception):
    pass


class AmbiguousSendError(Exception):
    pass


def utc_today() -> dt.date:
    return dt.datetime.now(dt.timezone.utc).date()


def get_bytes(url: str, user_agent: str, timeout: float = 20, limit: int = 2_000_000) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept": "application/json,text/html,text/csv,*/*"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read(limit + 1)
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise SourceError(f"source request failed ({type(exc).__name__})") from exc
    if len(data) > limit:
        raise SourceError("source response exceeds size limit")
    return data


def get_json(url: str, user_agent: str) -> dict[str, Any]:
    try:
        value = json.loads(get_bytes(url, user_agent))
    except (UnicodeError, ValueError) as exc:
        raise SourceError("invalid source JSON") from exc
    if not isinstance(value, dict):
        raise SourceError("unexpected source JSON shape")
    return value


def resolve_ciks(user_agent: str, tickers: tuple[str, ...]) -> dict[str, int]:
    try:
        table = get_json(SEC_TICKERS, user_agent)
        index = {str(row.get("ticker", "")).upper(): int(row["cik_str"])
                 for row in table.values() if isinstance(row, dict) and row.get("ticker") and row.get("cik_str")}
    except SourceError:
        # Official ticker/CIK snapshot bundled for outages of the index only.
        try:
            index = json.loads((Path(__file__).with_name("ciks.json")).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SourceError("SEC ticker map and local CIK snapshot unavailable") from exc
    missing = sorted(set(tickers) - index.keys())
    if missing:
        raise SourceError("SEC ticker map missing: " + ", ".join(missing))
    return {ticker: index[ticker] for ticker in tickers}


def fresh_date(value: str, today: dt.date, days: int = 7) -> bool:
    try:
        date = dt.date.fromisoformat(value)
    except (TypeError, ValueError):
        return False
    return dt.timedelta(0) <= today - date <= dt.timedelta(days=days)


def strip_html(raw: bytes) -> str:
    value = raw.decode("utf-8", errors="replace")
    value = re.sub(r"(?is)<(?:script|style)\b[^>]*>.*?</(?:script|style)>", " ", value)
    value = re.sub(r"(?s)<[^>]+>", " ", value)
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value)


def relevant_topics(text: str) -> list[str]:
    # Boilerplate forward-looking language routinely contains "guidance" and
    # "outlook". Exclude it from this conservative keyword screen.
    main = re.split(r"(?i)\bforward[- ]looking statements\b", text, maxsplit=1)[0][:100_000]
    return [label for label, expressions in RELEVANT_TERMS.items()
            if any(re.search(expr, main, flags=re.IGNORECASE) for expr in expressions)]


def filing_url(cik: int, accession: str, primary_document: str) -> str:
    if not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession):
        raise SourceError("invalid SEC accession")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", primary_document):
        raise SourceError("invalid SEC primary document")
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{primary_document}"


def filing_event(ticker: str, cik: int, row: dict[str, str], today: dt.date,
                 user_agent: str) -> dict[str, str] | None:
    form = row.get("form", "")
    filing_date = row.get("filingDate", "")
    if form not in FILINGS or not fresh_date(filing_date, today):
        return None
    accession = row.get("accessionNumber", "")
    url = filing_url(cik, accession, row.get("primaryDocument", ""))
    base_form = form.removesuffix("/A")
    detail = ""
    if base_form == "8-K":
        items = set(re.findall(r"\b\d\.\d{2}\b", row.get("items", "")))
        matched = [item for item in DIRECT_8K_ITEMS if item in items]
        if matched:
            detail = " · ".join(f"{item} {DIRECT_8K_ITEMS[item]}" for item in matched)
        elif "8.01" in items:
            topics = relevant_topics(strip_html(get_bytes(url, user_agent, limit=1_500_000)))
            if topics:
                detail = "8.01 기타 사건; 본문 표현: " + ", ".join(topics)
        if not detail:
            return None
    elif base_form == "6-K":
        topics = relevant_topics(strip_html(get_bytes(url, user_agent, limit=1_500_000)))
        if not topics:
            return None
        detail = "본문 표현: " + ", ".join(topics)
    else:
        detail = "정기 재무공시" if base_form in ("10-Q", "10-K", "20-F") else ""
    return {"id": f"sec:{cik}:{accession}", "ticker": ticker, "date": filing_date,
            "form": form, "detail": detail, "url": url}


def recent_rows(submissions: dict[str, Any]) -> list[dict[str, str]]:
    recent = submissions.get("filings", {}).get("recent", {})
    if not isinstance(recent, dict):
        raise SourceError("invalid SEC submissions shape")
    keys = ("form", "filingDate", "accessionNumber", "primaryDocument", "items")
    required = keys[:4]
    if any(not isinstance(recent.get(key), list) for key in required):
        raise SourceError("missing SEC submission fields")
    length = len(recent["form"])
    if any(len(recent[key]) != length for key in required):
        raise SourceError("inconsistent SEC submission fields")
    if not isinstance(recent.get("items"), list) or len(recent["items"]) != length:
        recent["items"] = [""] * length
    return [{key: str(recent[key][index] or "") for key in keys}
            for index in range(length)]


def collect_sec(user_agent: str, tickers: tuple[str, ...], today: dt.date) -> list[dict[str, str]]:
    ciks = resolve_ciks(user_agent, tickers)
    events: list[dict[str, str]] = []
    for ticker in tickers:
        submissions = get_json(SEC_SUBMISSIONS.format(cik=ciks[ticker]), user_agent)
        for row in recent_rows(submissions):
            event = filing_event(ticker, ciks[ticker], row, today, user_agent)
            if event:
                events.append(event)
    return sorted(events, key=lambda event: (event["date"], event["ticker"], event["id"]))


def collect_sec_partial(user_agent: str, tickers: tuple[str, ...],
                        today: dt.date) -> tuple[list[dict[str, str]], dict[str, str]]:
    status: dict[str, str] = {}
    try:
        ciks = resolve_ciks(user_agent, tickers)
    except SourceError as exc:
        return [], {f"sec:{ticker}": f"ERROR {exc}" for ticker in tickers}
    events: list[dict[str, str]] = []
    for ticker in tickers:
        source = f"sec:{ticker}"
        try:
            submissions = get_json(SEC_SUBMISSIONS.format(cik=ciks[ticker]), user_agent)
            ticker_events = [event for row in recent_rows(submissions)
                             if (event := filing_event(ticker, ciks[ticker], row, today, user_agent))]
        except SourceError as exc:
            status[source] = f"ERROR {exc}"
            continue
        events.extend(ticker_events)
        status[source] = "OK"
    return sorted(events, key=lambda event: (event["date"], event["ticker"], event["id"])), status


def collect_wti(user_agent: str, today: dt.date) -> dict[str, Any]:
    raw = get_bytes(FRED_WTI, PUBLIC_USER_AGENT, limit=1_000_000)
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
        date_field = "DATE" if "DATE" in (reader.fieldnames or ()) else "observation_date"
        samples = [(dt.date.fromisoformat(row[date_field]), float(row["DCOILWTICO"]))
                   for row in reader if row.get("DCOILWTICO") not in (None, ".", "")]
    except (ValueError, KeyError, UnicodeError) as exc:
        raise SourceError("invalid WTI CSV") from exc
    samples = [(date, price) for date, price in samples if date <= today]
    if not samples:
        raise SourceError("WTI CSV contains no usable prices")
    date, price = max(samples, key=lambda item: item[0])
    if not fresh_date(date.isoformat(), today):
        raise SourceError("WTI observation is stale")
    return {"date": date.isoformat(), "price": price, "url": "https://fred.stlouisfed.org/series/DCOILWTICO"}


def feed_date(value: str) -> str | None:
    try:
        when = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            when = email.utils.parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
    if when.tzinfo is None:
        return None
    return when.astimezone(dt.timezone.utc).date().isoformat()


def load_feeds(config_path: Path) -> list[dict[str, str]]:
    try:
        feeds = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SourceError("IR feed config cannot be read") from exc
    if not isinstance(feeds, list):
        raise SourceError("IR feed config must be a list")
    for feed in feeds:
        if not isinstance(feed, dict):
            raise SourceError("invalid IR feed config entry")
        if not isinstance(feed.get("symbol"), str) or not isinstance(feed.get("url"), str):
            raise SourceError("invalid IR feed config fields")
        parsed = urllib.parse.urlsplit(feed["url"])
        if parsed.scheme != "https" or not parsed.hostname:
            raise SourceError("IR feed URL must use HTTPS")
    return feeds


def parse_feed(raw: bytes, ticker: str, today: dt.date) -> list[dict[str, str]]:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise SourceError(f"invalid IR feed XML for {ticker}") from exc
    events: list[dict[str, str]] = []
    for item in list(root.iter("item")) + list(root.iter("{http://www.w3.org/2005/Atom}entry")):
        atom = item.tag.endswith("entry")
        if atom:
            namespace = "{http://www.w3.org/2005/Atom}"
            title = item.findtext(namespace + "title") or ""
            published = item.findtext(namespace + "published") or item.findtext(namespace + "updated") or ""
            summary = item.findtext(namespace + "summary") or ""
            link_element = item.find(namespace + "link")
            link = link_element.get("href", "") if link_element is not None else ""
        else:
            title = item.findtext("title") or ""
            published = item.findtext("pubDate") or ""
            summary = item.findtext("description") or ""
            link = item.findtext("link") or ""
        date = feed_date(published)
        if not date or not fresh_date(date, today):
            continue
        if urllib.parse.urlsplit(link).scheme != "https":
            continue
        topics = relevant_topics(html.unescape(title + " " + summary))
        if not topics:
            continue
        clean_title = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", title))).strip()[:140]
        digest = hashlib.sha256(link.encode("utf-8")).hexdigest()[:20]
        events.append({"id": f"rss:{ticker}:{digest}", "ticker": ticker, "date": date,
                       "form": "IR", "detail": f"{clean_title} · 본문 표현: {', '.join(topics)}", "url": link})
    return events


def collect_feeds_partial(user_agent: str, config_path: Path, tickers: tuple[str, ...],
                          today: dt.date) -> tuple[list[dict[str, str]], dict[str, str]]:
    feeds = load_feeds(config_path)
    events: list[dict[str, str]] = []
    status: dict[str, str] = {}
    for feed in feeds:
        ticker, url = feed["symbol"], feed["url"]
        if ticker not in tickers:
            continue
        source = f"ir:{ticker}"
        try:
            feed_events = parse_feed(get_bytes(url, PUBLIC_USER_AGENT, limit=1_000_000), ticker, today)
        except SourceError as exc:
            status[source] = f"ERROR {exc}"
            continue
        events.extend(feed_events)
        status[source] = "OK"
    return sorted({event["id"]: event for event in events}.values(),
                  key=lambda event: (event["date"], event["ticker"], event["id"])), status


def collect_feeds(user_agent: str, config_path: Path | None, tickers: tuple[str, ...],
                  today: dt.date) -> list[dict[str, str]]:
    if config_path is None:
        return []
    events, status = collect_feeds_partial(user_agent, config_path, tickers, today)
    if any(value.startswith("ERROR") for value in status.values()):
        raise SourceError("one or more IR feeds unavailable")
    return events


def wti_event(current: dict[str, Any], baseline: dict[str, Any] | None) -> dict[str, Any] | None:
    if not baseline or current["date"] <= baseline["date"]:
        return None
    before, after = float(baseline["price"]), float(current["price"])
    delta = after - before
    percent = delta / before * 100 if before else 0
    if abs(delta) < 3 and abs(percent) < 5:
        return None
    return {"id": f"wti:{current['date']}", "date": current["date"], "price": after,
            "base_price": before, "base_date": baseline["date"], "delta": delta,
            "percent": percent, "url": current["url"]}


def new_state() -> dict[str, Any]:
    return {"version": 1, "initialized": False, "baselined_sources": [],
            "seen_filings": [], "wti_baseline": None, "pending": None}


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return new_state()
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise SourceError("state file cannot be read") from exc
    if not isinstance(state, dict) or state.get("version") != 1:
        raise SourceError("unsupported state format")
    return state


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".energy-state-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(state, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    if os.environ.get("ENERGY_STATE_REMOTE") == "1":
        from .persist import persist_state
        persist_state(path)


def format_event(event: dict[str, str]) -> str:
    return f"• {event['ticker']} · {event['date']} · {event['form']} ({event['detail']})\n  {event['url']}"


def render_lines(events: list[dict[str, str]], wti: dict[str, Any] | None,
                 today: dt.date, source_status: dict[str, str] | None = None,
                 rigs: dict | None = None, rig_change: dict | None = None) -> list[str]:
    source_status = source_status or {}
    lines = [f"에너지 브리프 | {today.isoformat()} UTC", "", "핵심 변화"]
    if events:
        lines.append(f"최근 7일 SEC 공시·IR 소식 {len(events)}건. 공시 항목 또는 본문 표현으로 선별했습니다.")
    if wti:
        lines.append(f"WTI {wti['base_date']} ${wti['base_price']:.2f} → {wti['date']} ${wti['price']:.2f} "
                     f"({wti['delta']:+.2f}달러, {wti['percent']:+.1f}%).")
    if not events and not wti and not rig_change:
        lines.append("새 선별 항목 없음")
    if rig_change:
        lines.append(f"미국 rig {rig_change['base_value']} → {rig_change['value']} ({rig_change['delta']:+d}기), {rig_change['date']}; AOGR 재게시 자료.")
    for sector, members in SECTORS.items():
        lines.extend(("", sector))
        selected = [event for event in events if event["ticker"] in members]
        lines.extend(format_event(event) for event in selected)
        if not selected:
            failed = [ticker for ticker in members if source_status.get(f"sec:{ticker}", "OK").startswith("ERROR")]
            lines.append("SEC 수집 실패: " + ", ".join(failed) if failed else "새 선별 공시 없음")
        if sector == "Land" and rigs:
            for key in ("US_RIGS", "PERMIAN_RIGS", "HAYNESVILLE_RIGS"):
                row = rigs.get("observations", {}).get(key)
                if row:
                    label = "페이지 기준일·원자료 미대조" if row['quality'] == 'secondary_unverified' else "관측일·재게시 자료"
                    lines.append(f"{key}: {row['value']} ({row['date']}, {label})\n{row['url']}")
    lines.extend(("", "유가 연결"))
    if wti:
        lines.append("WTI 현물 가격 변화는 업스트림 지출과 서비스 수요에 간접적으로 작용할 수 있습니다. 개별 기업 영향은 공시에서 확인해야 합니다.")
        lines.append(wti["url"])
    elif source_status.get("wti", "OK").startswith("ERROR"):
        lines.append("WTI 자료 확인 실패. 유가 연결은 이번 보고서에서 평가하지 않았습니다.")
    else:
        lines.append("이번 알림 기준의 WTI 변동 임계치(5% 또는 3달러) 미도달.")
    failures = [key for key, status in source_status.items() if status.startswith("ERROR")]
    if failures:
        lines.extend(("", "자료 상태", "수집 실패: " + ", ".join(failures) + ". 해당 자료는 이번 판단에서 제외했습니다."))
    lines.extend(("", "미확보: WTI 12~24개월 곡선, frac spread, LNG 일별 feedgas, 업계 전체 offshore 가동률/dayrate, FPSO/subsea FID 전수 감시.", "", "투자판단", "공시 원문에서 계약 규모·마진·가이던스와 일회성 항목을 확인하기 전에는 실적 또는 주가 방향을 단정하지 않습니다."))
    return lines


def chunk_lines(lines: list[str], limit: int = MAX_MESSAGE) -> list[str]:
    chunks: list[str] = []
    current = ""
    for line in lines:
        if len(line) > limit:
            raise ValueError("one report line exceeds Telegram chunk limit")
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def telegram_send(token: str, chat_id: str, message: str) -> int:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    body = urllib.parse.urlencode({"chat_id": chat_id, "text": message, "disable_web_page_preview": "true"}).encode()
    request = urllib.request.Request(url, data=body, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            data = response.read(100_000)
    except urllib.error.HTTPError as exc:
        # Never include the exception string: it contains the token-bearing URL.
        if exc.code >= 500:
            raise AmbiguousSendError(f"Telegram HTTP {exc.code}: delivery uncertain") from None
        reason = ""
        if exc.code == 403:
            # Match known descriptions, but never log raw responses or token URLs.
            try:
                description = str(json.loads(exc.read(10000)).get("description", "")).lower()
            except Exception:
                description = ""
            known = {
                "bot was blocked by the user": "recipient blocked this bot; unblock it and send /start",
                "bot can't initiate conversation with a user": "open this exact bot and send /start first",
                "bots can't send messages to bots": "chat_id belongs to a bot; use your personal or group chat ID",
                "bot was kicked": "bot was removed from the target group/channel",
                "bot is not a member": "add the bot to the target group/channel",
                "not enough rights": "bot lacks permission to post in this chat",
                "user is deactivated": "recipient account is deactivated",
            }
            reason = next((hint for phrase, hint in known.items() if phrase in description), "target chat forbids this bot; check /start, block status, membership and chat_id")
        raise DefiniteSendError(f"Telegram HTTP {exc.code}" + (": " + reason if reason else "")) from None
    except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
        raise AmbiguousSendError(f"Telegram delivery uncertain ({type(exc).__name__})") from None
    try:
        result = json.loads(data)
        message_id = int(result["result"]["message_id"])
        if result.get("ok") is not True:
            raise ValueError
        return message_id
    except (ValueError, TypeError, KeyError, IndexError):
        raise AmbiguousSendError("Telegram response could not confirm delivery") from None


def make_pending(events: list[dict[str, str]], wti: dict[str, Any] | None,
                 today: dt.date, source_status: dict[str, str] | None = None,
                 rigs: dict | None = None, rig_change: dict | None = None) -> dict[str, Any]:
    messages = chunk_lines(render_lines(events, wti, today, source_status, rigs, rig_change))
    digest = hashlib.sha256('\n'.join(messages).encode()).hexdigest()[:10]
    messages = [f'[{digest} {i}/{len(messages)}]\n{message}' for i, message in enumerate(messages, 1)]
    return {"created": today.isoformat(), "filing_ids": [event["id"] for event in events],
            "rig": {"date": rig_change['date'], "value": rig_change['value']} if rig_change else None,
            "wti": {"date": wti["date"], "price": wti["price"]} if wti else None,
            "chunks": [{"text": message, "status": "ready", "telegram_message_id": None} for message in messages]}


def finish_pending(state: dict[str, Any]) -> None:
    pending = state["pending"]
    if not pending or any(chunk["status"] != "sent" for chunk in pending["chunks"]):
        return
    state["seen_filings"] = sorted(set(state.get("seen_filings", [])) | set(pending["filing_ids"]))[-2000:]
    if pending.get("wti"):
        state["wti_baseline"] = pending["wti"]
    if pending.get('rig'):
        state['rig_baseline'] = pending['rig']
    state["pending"] = None


def deliver_pending(state: dict[str, Any], path: Path, token: str, chat_id: str) -> None:
    pending = state["pending"]
    if not pending:
        return
    for index, chunk in enumerate(pending["chunks"], start=1):
        if chunk["status"] == "sent":
            continue
        if chunk["status"] in ("sending", "uncertain"):
            raise AmbiguousSendError(f"pending chunk {index} needs --resolve-uncertain sent|retry")
        chunk["status"] = "sending"
        save_state(path, state)
        try:
            message_id = telegram_send(token, chat_id, chunk["text"])
        except AmbiguousSendError:
            chunk["status"] = "uncertain"
            save_state(path, state)
            raise
        except DefiniteSendError:
            chunk["status"] = "ready"
            save_state(path, state)
            raise
        chunk["status"] = "sent"
        chunk["telegram_message_id"] = message_id
        save_state(path, state)
    finish_pending(state)
    save_state(path, state)


def run(args: argparse.Namespace) -> int:
    path = Path(args.state)
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if args.test_message:
        if not token or not chat_id:
            raise SourceError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID required")
        telegram_send(token, chat_id, "에너지 브리프 테스트 메시지 · 전송 확인")
        print("Test message sent; state unchanged.")
        return 0
    state = load_state(path)
    if args.resolve_uncertain:
        if not state.get("pending"):
            raise SourceError("no pending report")
        uncertain = [chunk for chunk in state["pending"]["chunks"] if chunk["status"] in ("sending", "uncertain")]
        if not uncertain:
            raise SourceError("no uncertain chunk")
        if args.resolve_uncertain == "sent":
            for chunk in uncertain:
                chunk["status"] = "sent"
            finish_pending(state)
        else:
            for chunk in uncertain:
                chunk["status"] = "ready"
        if not args.dry_run:
            save_state(path, state)
        print(f"Resolved {len(uncertain)} uncertain chunk(s) as {args.resolve_uncertain}.")
        return 0
    if state.get("pending"):
        if args.dry_run:
            print("Pending report exists; dry-run leaves state unchanged.")
            return 0
        if not token or not chat_id:
            raise SourceError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID required for pending delivery")
        deliver_pending(state, path, token, chat_id)
        print("Pending report delivered.")
        return 0

    user_agent = os.environ.get("SEC_USER_AGENT", "")
    if not user_agent or "@" not in user_agent:
        raise SourceError("SEC_USER_AGENT with contact email required")
    today = utc_today()
    tickers = DEFAULT_TICKERS + OPTIONAL_TICKERS if args.include_bkr else DEFAULT_TICKERS
    events, source_status = collect_sec_partial(user_agent, tickers, today)
    if args.feeds:
        try:
            feed_events, feed_status = collect_feeds_partial(user_agent, Path(args.feeds), tickers, today)
            events.extend(feed_events)
            source_status.update(feed_status)
        except SourceError as exc:
            source_status["ir_config"] = f"ERROR {exc}"
    events.sort(key=lambda event: (event["date"], event["ticker"], event["id"]))
    try:
        wti = collect_wti(user_agent, today)
        source_status["wti"] = "OK"
    except SourceError as exc:
        wti = None
        source_status["wti"] = f"ERROR {exc}"
    rigs = None
    if getattr(args, 'rigs', False):
        from .rigs import collect_rigs
        rigs = collect_rigs(lambda url: get_bytes(url, PUBLIC_USER_AGENT), today)
        source_status.update({f'rig:{key}': 'OK' for key in rigs['observations']})
        source_status.update({f'rig:{key}': f'ERROR {error}' for key, error in rigs['errors'].items()})
    print(json.dumps({"date_utc": today.isoformat(), "sources": source_status}, ensure_ascii=False, sort_keys=True))
    had_errors = any(value.startswith("ERROR") for value in source_status.values())
    if state.get("initialized") and "baselined_sources" not in state:
        # State written by the first implementation, before per-source baselines.
        state["baselined_sources"] = [f"sec:{ticker}" for ticker in tickers] + ["wti"]
    baselined = set(state.get("baselined_sources", []))
    seen = set(state.get("seen_filings", []))
    new_events: list[dict[str, str]] = []
    newly_baselined: set[str] = set()
    for event in events:
        source = (f"sec:{event['ticker']}" if event["id"].startswith("sec:") else f"ir:{event['ticker']}")
        if source not in baselined:
            seen.add(event["id"])
            newly_baselined.add(source)
        elif event["id"] not in seen:
            new_events.append(event)
    for source, status in source_status.items():
        if status == "OK" and source not in baselined:
            newly_baselined.add(source)
    price_event = None
    if wti:
        if "wti" not in baselined:
            state["wti_baseline"] = {"date": wti["date"], "price": wti["price"]}
        else:
            price_event = wti_event(wti, state.get("wti_baseline"))
    rig_change = None
    if rigs and (us := rigs['observations'].get('US_RIGS')):
        previous = state.get('rig_baseline')
        if 'rig:US_RIGS' not in baselined or previous is None:
            state['rig_baseline'] = {'date': us['date'], 'value': us['value']}
            newly_baselined.add('rig:US_RIGS')
        elif us['date'] > previous['date'] and abs(us['value'] - previous['value']) >= 5:
            rig_change = {**us, 'base_value': previous['value'], 'delta': us['value'] - previous['value']}
    if newly_baselined:
        state["baselined_sources"] = sorted(baselined | newly_baselined)
        state["seen_filings"] = sorted(seen)[-2000:]
        state["initialized"] = True
        if not args.dry_run:
            save_state(path, state)
    if not new_events and not price_event and not rig_change and newly_baselined:
        print(f"Silently baselined {len(newly_baselined)} source(s); no message sent.")
        return 1 if had_errors else 0
    if not new_events and not price_event and not rig_change:
        print("No new qualifying SEC filings or WTI threshold event.")
        return 1 if had_errors else 0
    pending = make_pending(new_events, price_event, today, source_status, rigs, rig_change)
    if args.dry_run:
        print("\n\n--- Telegram chunk ---\n\n".join(chunk["text"] for chunk in pending["chunks"]))
        print("\nDry-run: state unchanged.")
        return 1 if had_errors else 0
    if not token or not chat_id:
        raise SourceError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID required")
    state["pending"] = pending
    save_state(path, state)  # Outbox committed before any external send.
    deliver_pending(state, path, token, chat_id)
    print(f"Delivered {len(pending['chunks'])} chunk(s), {len(new_events)} filing(s).")
    return 1 if had_errors else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Daily SEC + WTI energy brief")
    parser.add_argument("--state", default="energy_brief_state.json", help="persistent JSON state path")
    parser.add_argument("--include-bkr", action="store_true")
    parser.add_argument("--rigs", action="store_true", help="public rig count context and cumulative US 5-rig threshold")
    parser.add_argument("--feeds", help="optional JSON list of verified IR RSS feeds")
    parser.add_argument("--dry-run", action="store_true", help="fetch and preview without changing state or sending")
    parser.add_argument("--test-message", action="store_true", help="send Telegram connectivity test; no state change")
    parser.add_argument("--resolve-uncertain", choices=("sent", "retry"), help="resolve ambiguous Telegram delivery after checking chat")
    args = parser.parse_args(argv)
    try:
        return run(args)
    except (SourceError, DefiniteSendError, AmbiguousSendError) as exc:
        # All exceptions presented here are curated to exclude secret-bearing URLs.
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
