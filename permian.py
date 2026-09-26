"""EIA monthly observations, kept separate from daily dashboard snapshots."""
import math
import re


def parse_monthly(rows, end):
    by = {}
    ids = {'DUCSPM': 'PERMIAN_DUC', 'NWCPM': 'PERMIAN_MONTHLY_COMPLETIONS'}
    for row in rows:
        period, sid = row.get('period', ''), row.get('seriesId')
        if sid not in ids or not re.fullmatch(r'\d{4}-\d{2}', period) or period > end:
            continue
        try:
            value = float(row['value'])
        except (ValueError, TypeError, KeyError):
            continue
        if not math.isfinite(value) or value < 0 or (sid == 'NWCPM' and value == 0):
            continue
        by.setdefault(period, {'period': period})[ids[sid]] = value
    result = []
    for period, row in sorted(by.items()):
        if all(key in row for key in ids.values()):
            row['DUC_COVER'] = round(row['PERMIAN_DUC'] / row['PERMIAN_MONTHLY_COMPLETIONS'], 2)
            result.append(row)
    if not result:
        raise ValueError('No matching monthly DUC/completions observations')
    return result


def apply_monthly(data, history, observations, source):
    latest = observations[-1]
    history['permian_monthly'] = observations
    history['permian_monthly_source'] = source
    s = data['shale_cycle']
    s.update(PERMIAN_DUC=latest['PERMIAN_DUC'],
             PERMIAN_COMPLETIONS=latest['PERMIAN_MONTHLY_COMPLETIONS'],
             PERMIAN_COMPLETIONS_Q=None, DUC_COVER=latest['DUC_COVER'],
             PERMIAN_PERIOD=latest['period'],
             DUC_CHANGE=round((latest['PERMIAN_DUC']/observations[-2]['PERMIAN_DUC']-1)*100, 2)
             if len(observations)>1 and observations[-2]['PERMIAN_DUC'] else None)
    s.setdefault('as_of', {})['PERMIAN_DUC'] = latest['period'] + ' EIA STEO monthly'
    status = {'status': 'AUTO', 'date': latest['period'], 'url': source, 'error': None}
    s.setdefault('sources', {})['EIA STEO'] = status
    data['meta'].setdefault('source_status', {})['EIA STEO'] = status
