import gzip
import io
import unittest
from unittest.mock import patch
from energy_brief import bot

class FetchTests(unittest.TestCase):
    def test_gzip_json(self):
        response = io.BytesIO(gzip.compress(b'{"ok":true}'))
        response.headers = {"Content-Encoding": "gzip"}
        with patch.object(bot.urllib.request, "urlopen", return_value=response):
            self.assertEqual(bot.get_json("https://example.org", "test"), {"ok": True})

    def test_timeout_retry(self):
        response = io.BytesIO(b"valid")
        response.headers = {}
        with patch.object(bot.urllib.request, "urlopen", side_effect=[TimeoutError(), response]) as fetch, patch.object(bot.time, "sleep"):
            self.assertEqual(bot.get_bytes("https://example.org", "test"), b"valid")
            self.assertEqual(fetch.call_count, 2)
