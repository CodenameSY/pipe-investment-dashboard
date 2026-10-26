import datetime as dt
import unittest
from energy_brief.rigs import collect_rigs, parse_aogr, parse_basin


TODAY = dt.date(2026, 10, 25)
AOGR = b'''<table><tr><td>10/23/2026</td><td>Total Rigs 2026 (Wk./Wk.) 0 603</td>
<td>Oil (Wk./Wk.) +1 (460)</td><td>Gas (Wk./Wk.) -1 (132)</td>
<td>Misc. (Wk./Wk.) 0 (11)</td><td>Total Rigs 2025 550</td></tr>
<tr><td>10/16/2026</td><td>Total Rigs 2026 (Wk./Wk.) 0 603</td>
<td>Oil (Wk./Wk.) -3 (459)</td><td>Gas (Wk./Wk.) +1 (133)</td>
<td>Misc. (Wk./Wk.) +2 (11)</td></tr></table>'''
BASIN = b'''<h1>Permian Basin Rig Count Holds at 267 Active Rigs</h1>
<p>267 Active Rigs Unchanged WoW As of October 24, 2026</p><h2>About the Permian Basin</h2>'''


class RigTests(unittest.TestCase):
    def test_components_and_source_date(self):
        result = parse_aogr(AOGR, TODAY)
        self.assertEqual(result["date"], "2026-10-23")
        self.assertEqual(result["counts"]["US_RIGS"], 603)
        self.assertEqual(result["changes"]["OIL_RIGS"], 1)

    def test_malformed_latest_does_not_borrow_previous(self):
        with self.assertRaises(ValueError):
            parse_aogr(AOGR.replace(b"(460)", b"(unavailable)"), TODAY)

    def test_reject_total_mismatch(self):
        with self.assertRaises(ValueError):
            parse_aogr(AOGR.replace(b"0 603", b"0 604", 1), TODAY)

    def test_basin_source_date_not_observation(self):
        row = parse_basin(BASIN, "permian", TODAY)
        self.assertEqual(row["value"], 267)
        self.assertEqual(row["quality"], "secondary_unverified")
        self.assertEqual(row["date_kind"], "source_page_as_of")

    def test_stale_and_future_rejected(self):
        for today in (dt.date(2026, 11, 20), dt.date(2026, 10, 20)):
            with self.assertRaises(ValueError):
                parse_basin(BASIN, "permian", today)

    def test_card_disagrees(self):
        with self.assertRaises(ValueError):
            parse_basin(BASIN.replace(b"<p>267", b"<p>268"), "permian", TODAY)

    def test_partial_failure_preserves_other_observations(self):
        def fetch(url):
            if "aogr.com" in url:
                return AOGR
            if url.endswith("permian"):
                return BASIN
            raise RuntimeError("secret must not be echoed")
        result = collect_rigs(fetch, TODAY)
        self.assertEqual(result["counts"]["PERMIAN_RIGS"], 267)
        self.assertNotIn("HAYNESVILLE_RIGS", result["counts"])
        self.assertEqual(result["errors"]["HAYNESVILLE_RIGS"], "unavailable: RuntimeError")


if __name__ == "__main__":
    unittest.main()
