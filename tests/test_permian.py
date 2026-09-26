import unittest
from permian import parse_monthly, apply_monthly


def row(period, sid, value):
    return dict(period=period, seriesId=sid, value=value)


class MonthlyTests(unittest.TestCase):
    def test_matching_periods_and_no_quarter_conversion(self):
        rows = [row('2026-08','DUCSPM','839'), row('2026-08','NWCPM','488'),
                row('2026-07','DUCSPM','828'), row('2026-07','NWCPM','484'),
                row('2026-06','DUCSPM','828'), row('2026-06','NWCPM','475'),
                row('2026-09','DUCSPM','900'), row('2026-09','NWCPM','500'),
                row('2026-Q2','DUCSPM','828')]
        result = parse_monthly(rows, '2026-08')
        self.assertEqual([r['DUC_COVER'] for r in result], [1.74,1.71,1.72])
        self.assertEqual(result[-1]['PERMIAN_MONTHLY_COMPLETIONS'],488)
        d={'shale_cycle':{},'meta':{}}; h={}
        apply_monthly(d,h,result,'official')
        self.assertEqual(d['shale_cycle']['PERMIAN_PERIOD'],'2026-08')
        self.assertEqual(d['shale_cycle']['DUC_CHANGE'],1.33)

    def test_missing_invalid_and_zero_not_paired_across_months(self):
        rows=[row('2026-08','DUCSPM',839),row('2026-07','NWCPM',484),
              row('2026-06','DUCSPM','NaN'),row('2026-06','NWCPM',475),
              row('2026-05','DUCSPM',826),row('2026-05','NWCPM',0)]
        with self.assertRaises(ValueError): parse_monthly(rows,'2026-08')


if __name__ == '__main__': unittest.main()
