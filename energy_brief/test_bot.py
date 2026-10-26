import argparse
import datetime as dt
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from energy_brief import bot


TODAY = dt.date(2026, 10, 25)
TEST_TEMP = Path.cwd() / "work"
TEST_TEMP.mkdir(exist_ok=True)
EVENT = {"id": "sec:1:0000000001-26-000001", "ticker": "HP", "date": "2026-10-24",
         "form": "8-K", "detail": "2.02 실적 발표", "url": "https://www.sec.gov/example"}
WTI = {"date": "2026-10-24", "price": 72.0, "url": bot.FRED_WTI}


class BotTests(unittest.TestCase):
    def test_rig_cumulative_threshold_and_repeat_suppression(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as temp:
            path = Path(temp) / 'state.json'
            args = argparse.Namespace(state=str(path), test_message=False, resolve_uncertain=None,
                                      dry_run=False, include_bkr=False, feeds=None, rigs=True)
            row = {'value': 600, 'date': '2026-10-20', 'quality': 'secondary_reconciled', 'url': 'https://example.org/rigs'}
            collected = {'observations': {'US_RIGS': row}, 'errors': {}}
            with patch.dict(os.environ, {'SEC_USER_AGENT': 'Example me@example.com', 'TELEGRAM_BOT_TOKEN': 'fake', 'TELEGRAM_CHAT_ID': 'fake'}), \
                 patch.object(bot, 'utc_today', return_value=TODAY), \
                 patch.object(bot, 'collect_sec_partial', return_value=([], {'sec:HP': 'OK'})), \
                 patch.object(bot, 'collect_wti', return_value=WTI), \
                 patch('energy_brief.rigs.collect_rigs', return_value=collected), \
                 patch.object(bot, 'telegram_send', return_value=123) as send:
                bot.run(args)
                row.update(value=603, date='2026-10-21')
                bot.run(args)
                send.assert_not_called()
                row.update(value=605, date='2026-10-22')
                bot.run(args)
                self.assertEqual(send.call_count, 1)
                self.assertIn('1/1]', send.call_args.args[2])
                bot.run(args)
                self.assertEqual(send.call_count, 1)
                self.assertEqual(bot.load_state(path)['rig_baseline']['value'], 605)

    def test_date_window_excludes_future_and_old(self):
        self.assertTrue(bot.fresh_date("2026-10-18", TODAY))
        self.assertFalse(bot.fresh_date("2026-10-17", TODAY))
        self.assertFalse(bot.fresh_date("2026-10-26", TODAY))
        self.assertFalse(bot.fresh_date("bad", TODAY))

    def test_8k_item_requires_relevant_item_and_6k_requires_actual_text(self):
        base = {"form": "8-K", "filingDate": "2026-10-24", "accessionNumber": "0000000001-26-000001",
                "primaryDocument": "report.htm", "items": "2.02,9.01"}
        event = bot.filing_event("HP", 1, base, TODAY, "Example (me@example.com)")
        self.assertIn("실적 발표", event["detail"])
        self.assertIsNone(bot.filing_event("HP", 1, {**base, "items": "9.01"}, TODAY, "x@y.com"))
        six = {**base, "form": "6-K", "items": ""}
        with patch.object(bot, "get_bytes", return_value=b"<p>We received a drilling contract award.</p>"):
            self.assertIn("수주", bot.filing_event("NE", 1, six, TODAY, "x@y.com")["detail"])
        with patch.object(bot, "get_bytes", return_value=b"<p>Forward-looking statements include guidance and outlook.</p>"):
            self.assertIsNone(bot.filing_event("NE", 1, six, TODAY, "x@y.com"))

    def test_wti_threshold_uses_last_alerted_baseline(self):
        baseline = {"date": "2026-10-20", "price": 70.0}
        self.assertIsNone(bot.wti_event({**WTI, "price": 72.9}, baseline))
        self.assertIsNotNone(bot.wti_event({**WTI, "price": 73.0}, baseline))
        self.assertIsNotNone(bot.wti_event({**WTI, "price": 66.4}, baseline))
        self.assertIsNone(bot.wti_event({**WTI, "price": 75.0, "date": "2026-10-20"}, baseline))

    def test_wti_csv_current_header_and_staleness(self):
        raw = b"observation_date,DCOILWTICO\n2026-10-22,70.00\n2026-10-23,71.25\n2026-10-26,99.00\n"
        with patch.object(bot, "get_bytes", return_value=raw):
            self.assertEqual(bot.collect_wti("x@y.com", TODAY)["price"], 71.25)
        with patch.object(bot, "get_bytes", return_value=b"observation_date,DCOILWTICO\n2026-10-01,70.00\n"):
            with self.assertRaises(bot.SourceError):
                bot.collect_wti("x@y.com", TODAY)

    def test_first_run_baselines_silently_and_dry_run_does_not_write(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as temp:
            state_path = Path(temp) / "state.json"
            args = argparse.Namespace(state=str(state_path), test_message=False, resolve_uncertain=None,
                                      dry_run=True, include_bkr=False, feeds=None)
            with patch.dict(os.environ, {"SEC_USER_AGENT": "Example me@example.com"}), \
                 patch.object(bot, "utc_today", return_value=TODAY), \
                 patch.object(bot, "collect_sec_partial", return_value=([EVENT], {f"sec:{ticker}": "OK" for ticker in bot.DEFAULT_TICKERS})), \
                 patch.object(bot, "collect_wti", return_value=WTI), \
                 patch.object(bot, "telegram_send") as send:
                self.assertEqual(bot.run(args), 0)
                self.assertFalse(state_path.exists())
                args.dry_run = False
                self.assertEqual(bot.run(args), 0)
                self.assertTrue(state_path.exists())
                state = bot.load_state(state_path)
                self.assertEqual(state["seen_filings"], [EVENT["id"]])
                self.assertEqual(state["wti_baseline"]["price"], 72.0)
                self.assertIn("sec:HP", state["baselined_sources"])
                send.assert_not_called()

    def test_partial_source_failure_keeps_successful_baseline_and_reports_error(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as temp:
            path = Path(temp) / "state.json"
            args = argparse.Namespace(state=str(path), test_message=False, resolve_uncertain=None,
                                      dry_run=False, include_bkr=False, feeds=None)
            with patch.dict(os.environ, {"SEC_USER_AGENT": "Example me@example.com"}), \
                 patch.object(bot, "utc_today", return_value=TODAY), \
                 patch.object(bot, "collect_sec_partial", return_value=([EVENT], {"sec:HP": "OK", "sec:NE": "ERROR timeout"})), \
                 patch.object(bot, "collect_wti", side_effect=bot.SourceError("WTI stale")):
                self.assertEqual(bot.run(args), 2)
            saved = bot.load_state(path)
            self.assertIn("sec:HP", saved["baselined_sources"])
            self.assertNotIn("sec:NE", saved["baselined_sources"])
            self.assertNotIn("wti", saved["baselined_sources"])
            self.assertEqual(saved["seen_filings"], [EVENT["id"]])

    def test_pending_outbox_preserves_chunk_receipts_and_blocks_ambiguous_retry(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as temp:
            path = Path(temp) / "state.json"
            state = bot.new_state()
            state["initialized"] = True
            state["pending"] = {"created": TODAY.isoformat(), "filing_ids": [EVENT["id"]],
                                "wti": {"date": WTI["date"], "price": WTI["price"]},
                                "chunks": [{"text": f"part {i}", "status": "ready", "telegram_message_id": None}
                                           for i in range(2)]}
            bot.save_state(path, state)
            with patch.object(bot, "telegram_send", side_effect=[101, bot.AmbiguousSendError("timeout")]) as send:
                with self.assertRaises(bot.AmbiguousSendError):
                    bot.deliver_pending(state, path, "secret", "123")
                self.assertEqual(send.call_count, 2)
            saved = bot.load_state(path)
            self.assertEqual([chunk["status"] for chunk in saved["pending"]["chunks"]], ["sent", "uncertain"])
            self.assertEqual(saved["pending"]["chunks"][0]["telegram_message_id"], 101)
            self.assertEqual(saved["seen_filings"], [])
            with patch.object(bot, "telegram_send") as send:
                with self.assertRaises(bot.AmbiguousSendError):
                    bot.deliver_pending(saved, path, "secret", "123")
                send.assert_not_called()
            saved["pending"]["chunks"][1]["status"] = "sent"  # operator checked Telegram chat
            bot.finish_pending(saved)
            self.assertIsNone(saved["pending"])
            self.assertEqual(saved["seen_filings"], [EVENT["id"]])

    def test_state_is_committed_as_sending_before_external_call(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as temp:
            path = Path(temp) / "state.json"
            state = bot.new_state()
            state["pending"] = {"created": TODAY.isoformat(), "filing_ids": [], "wti": None,
                                "chunks": [{"text": "hello", "status": "ready", "telegram_message_id": None}]}
            bot.save_state(path, state)

            def inspect_before_send(*_):
                self.assertEqual(bot.load_state(path)["pending"]["chunks"][0]["status"], "sending")
                return 104

            with patch.object(bot, "telegram_send", side_effect=inspect_before_send):
                bot.deliver_pending(state, path, "secret", "123")
            self.assertIsNone(bot.load_state(path)["pending"])

    def test_telegram_5xx_is_ambiguous_and_4xx_is_definite_without_token_leak(self):
        for code, error_type in ((502, bot.AmbiguousSendError), (429, bot.DefiniteSendError)):
            with self.subTest(code=code), patch.object(bot.urllib.request, "urlopen",
                                                     side_effect=urllib.error.HTTPError("https://api.telegram.org/botsecret/sendMessage", code, "bad", None, None)):
                with self.assertRaises(error_type) as caught:
                    bot.telegram_send("secret", "123", "hello")
                self.assertNotIn("secret", str(caught.exception))

    def test_missing_sec_items_array_is_safe(self):
        rows = bot.recent_rows({"filings": {"recent": {"form": ["8-K"], "filingDate": ["2026-10-24"],
                             "accessionNumber": ["0000000001-26-000001"], "primaryDocument": ["report.htm"]}}})
        self.assertEqual(rows[0]["items"], "")

    def test_official_cik_snapshot_fallback_when_index_unavailable(self):
        with patch.object(bot, "get_json", side_effect=bot.SourceError("HTTP 403")):
            self.assertEqual(bot.resolve_ciks("x@y.com", ("HP", "BKR")), {"HP": 46765, "BKR": 1701605})

    def test_feed_parses_rss_date_and_ignores_unrelated(self):
        rss = b'''<rss><channel>
        <item><title>Contract award</title><pubDate>Sat, 24 Oct 2026 15:00:00 GMT</pubDate>
        <link>https://example.com/a</link><description>New rig contract</description></item>
        <item><title>Community event</title><pubDate>Sat, 24 Oct 2026 15:00:00 GMT</pubDate>
        <link>https://example.com/b</link></item>
        </channel></rss>'''
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as temp:
            config = Path(temp) / "feeds.json"
            config.write_text(json.dumps([{"symbol": "NE", "url": "https://example.com/feed.xml"}]), encoding="utf-8")
            with patch.object(bot, "get_bytes", return_value=rss):
                events = bot.collect_feeds("me@example.com", config, ("NE",), TODAY)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["date"], "2026-10-24")


if __name__ == "__main__":
    unittest.main()
