# On-device stocks

`app.ntwrknrd.stocks` runs on official BUSY Bar firmware 1.2.4. It fetches Yahoo
Finance's unofficial chart endpoint directly over HTTPS; no Mac relay or API key
is required. A hardware probe verified HTTPS and JSON parsing before installation.

The app uses the existing CLI's 31-symbol default watchlist, including indices
and mutual funds. Each symbol gets ten seconds in one stable layout: ticker at upper left,
percentage change at bottom left, and an intraday sparkline using all 16 rows
on the right. The front has no separate price or market-status view; those
details remain on the rear. Symbols without enough chart points show `NO CHART`,
or `DAILY NAV` for mutual funds. Change is relative to the
provider's previous close, not the chart's first sample. Prices use Yahoo's
reported currency; quote timestamps on the rear screen are explicitly UTC.

Requests run sequentially, at most one per five-second tick. Each successful
symbol becomes eligible for refresh after five minutes; failures retry after
one minute when the round-robin scheduler reaches that symbol. The first full
watchlist load progresses over several minutes. Each quote is cached separately;
restarts mark cached data stale until that symbol refreshes successfully. Failed
fetches retain the last valid quote. Stale prices and charts use yellow.

`CLOSED` means the current time falls outside the provider's regular session;
extended-hours prices are not requested. During a regular session, quotes older
than 20 minutes show `DELAYED`. These labels are independent of fetch freshness.
Yahoo is an unofficial source and may throttle requests or change its schema.
This prototype supports daily charts only; wheel input and animated transitions
are deferred. The JavaScript heap is 256 KiB and chart samples are capped at 72.

## Installation

With the normal device serial and local connection environment configured:

```sh
uv sync --locked
uv run scripts/install_device_stocks.py
```

The installer checks serial and firmware, reads back all uploads, and refuses to
replace a different existing install. It preserves other apps, including weather.
Reload Apps with the mode switch and select **Stocks**, then **Start**. Stop with
the mode switch; firmware 1.2.4 consumes Back while JavaScript is running.

## Verification

```sh
node --test tests/test_device_stocks.cjs
uv run python -m unittest discover -s tests
```

Host tests cover parsing, fund NAVs, session labels, rendering, rotation, cache
recovery, invalid responses, and refresh scheduling. Hardware checks are still
required for heap limits, Wi-Fi behavior, and the full refresh cycle. Actual
network-outage testing and an extended soak remain follow-up work.

On September 28, 2026, direct Yahoo HTTPS was verified on the serial-checked Bar
running official 1.2.4. The installed script and manifest were read back exactly;
live price/chart pages rendered on both displays and all 31 symbols populated
the persistent cache, including indices and daily fund NAVs. The
separate weather installation remained byte-for-byte unchanged.
The app was stopped and relaunched with all 31 quotes retained, and cached
readings rendered with the stale marker while refreshing. The shipped installer
also verified the matching existing installation without replacing files.
