# Permian monthly data correction (2026-09-26)

Verified directly against the EIA STEO monthly API (`DUCSPM`, `NWCPM`).
The original API response is retained in `tests/eia-2026-09-monthly.json`.

| Observation month | DUC (wells) | Completions (wells/month) | DUC / completions (months) |
| --- | ---: | ---: | ---: |
| 2026-06 | 828 | 475 | 1.74 |
| 2026-07 | 828 | 484 | 1.71 |
| 2026-08 | 839 | 488 | 1.72 |

The previous dashboard showed Q2 DUC 828 and quarterly completions 1,412
divided by three (470.67), resulting in 1.76 months. These are not the
latest monthly observations. Monthly NWCPM must not be divided by three.

`history.json.permian_monthly` contains matched observations from the latest
retrieved vintage. Charts use its latest three observation months, with no
daily forward filling. Old `snapshots` remain an audit of what the dashboard
reported on each collection day; they are not a monthly EIA time series and
are no longer used for these three charts. Revisions replace the monthly
series together. DUC and completions are paired by month before division;
missing, nonfinite, negative and zero-denominator values are rejected.
The current/future month is excluded. A failed fetch retains the last verified
monthly series and displays STALE/FALLBACK with its observation month.

Push deployments publish committed data; scheduled/manual runs still refresh
data. This permits a focused correction without refreshing unrelated HRC,
OCTG, market prices or scores. Existing HRC/OCTG configuration is unchanged.

Source: https://api.eia.gov/v2/steo/data/ (frequency=monthly)
Report: https://www.eia.gov/outlooks/steo/

Validation: `python -m unittest discover -s tests` and dashboard script checks
for the three monthly charts and latest-value cards.
