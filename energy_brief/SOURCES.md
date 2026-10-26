# Official press release feeds

Runtime follow-up (2026-10-26): parent-session Python dry-run with a public-source User-Agent successfully parsed PTEN and RIG feeds, FRED WTI CSV, AOGR US counts, and both basin pages. All ten SEC submissions requests still returned HTTP errors in this environment; verify SEC access in GitHub Actions after Secrets setup. Runtime access can vary by host and must not be inferred from the web fetcher alone.

Checked 2026-10-25. `feeds.json` contains only company-published RSS addresses that were linked from an official investor relations RSS page and returned an RSS/XML content type through the web fetcher.

| Symbol | Company source page | Feed | Check |
| --- | --- | --- | --- |
| PTEN | [Patterson-UTI RSS page](https://investor.patenergy.com/Investors/resources/RSS/default.aspx) | [Press Release RSS Feed](https://investor.patenergy.com/rss/pressrelease.aspx) | The source page explicitly links the feed; the feed URL returned `text/xml` to the web fetcher. |
| RIG | [Transocean RSS Feeds](https://investor.deepwater.com/rss-feeds) | [All Press Releases](https://investor.deepwater.com/rss/news-releases.xml) | The source page explicitly links the feed; the feed URL returned `application/rss+xml` to the web fetcher. |

The following official release pages were located, but a live RSS address could not be confirmed. They are deliberately absent from `feeds.json`: [HP](https://ir.hpinc.com/news/press-releases/default.aspx), [SLB](https://investorcenter.slb.com/news-events/news-releases), [WFRD](https://www.weatherford.com/investor-relations/home/), [NE](https://noblecorp.com/our-investors/investor-news/), [SDRL](https://ir.seadrill.com/news/), [VAL](https://www.valaris.com/news/), and optional [BKR](https://investors.bakerhughes.com/news/press-releases/default.aspx). For the optional subsea/FPSO watchlist, [TechnipFMC](https://www.technipfmc.com/en/services/rss/) advertises RSS but its link target and feed response could not be read; [SBM Offshore](https://www.sbmoffshore.com/investors/press-releases/) and [MODEC](https://www.modec.com/ir/) have public release pages without a confirmed RSS address.

Direct requests from this environment received a Cloudflare 403 challenge, including for official release pages. The web fetcher established the two listed feed content types, but this environment could not parse their XML bodies or confirm live polling from the application runtime. Consumers should report per-feed fetch failures rather than treating a failed poll as no news.

## SEC identifiers

`ciks.json` is a static fallback derived from the SEC's [official company ticker to CIK table](https://www.sec.gov/files/company_tickers.json), fetched by the web fetcher on 2026-10-25. Every symbol below appeared as an exact `ticker` key in that table, with the corresponding `cik_str` value. The SEC's table is the source of truth if an issuer later changes its symbol or identifier.

| Symbol | CIK | SEC company name |
| --- | ---: | --- |
| HP | 46765 | Helmerich & Payne, Inc. |
| PTEN | 889900 | PATTERSON UTI ENERGY INC |
| HAL | 45012 | HALLIBURTON CO |
| SLB | 87347 | SLB LIMITED/NV |
| WFRD | 1603923 | Weatherford International plc |
| RIG | 1451505 | Transocean Ltd. |
| NE | 1895262 | Noble Corp plc |
| SDRL | 1737706 | SEADRILL Ltd |
| VAL | 314808 | Valaris Ltd |
| BKR | 1701605 | Baker Hughes Co |

Direct shell access to `www.sec.gov` returned HTTP 403 from this environment. The official JSON was readable through the web fetcher. Application polling should still handle SEC access failures explicitly.
