# On-device stocks

`app.ntwrknrd.stocks` runs on official BUSY Bar firmware 1.2.4. It fetches Yahoo
Finance's unofficial chart endpoint directly over HTTPS; no Mac relay or API key
is required. A hardware probe verified HTTPS and JSON parsing before installation.

The app uses the existing CLI's 31-symbol default watchlist, including indices
and mutual funds. Each symbol stays visible for at least ten seconds in one
stable layout: ticker at upper left,
percentage change at bottom left, and an intraday sparkline using all 16 rows
on the right. At each transition the graph draws from left to right while the
ticker and percentage remain visible. The front has no separate price or
market-status view; those
details remain on the rear. Symbols without enough chart points show `NO CHART`,
or `DAILY NAV` for mutual funds. Change is relative to the
provider's previous close, not the chart's first sample. The dotted gray line marks
that previous close, and the chart scale includes it. The final point uses the
same quoted price as the percentage. A stock can rise from its opening level
while remaining below yesterday's close. Prices use Yahoo's
reported currency; quote timestamps on the rear screen are explicitly UTC.

Requests run sequentially, at most one per five-second tick. The next symbol is
prefetched while the current chart is visible. Rotation waits until a valid
quote for that next symbol is available; delayed or failed requests keep the
current chart visible. Valid cached quotes can be shown with the stale color.
Each successful
symbol becomes eligible for refresh after five minutes; failures retry after
one minute when the scheduler retries that symbol. The first full
watchlist load progresses over several minutes. Each quote is cached separately;
restarts mark cached data stale until that symbol refreshes successfully. Failed
fetches retain the last valid quote. Stale prices and charts use yellow.

`CLOSED` means the current time falls outside the provider's regular session;
extended-hours prices are not requested. During a regular session, quotes older
than 20 minutes show `DELAYED`. These labels are independent of fetch freshness.
Yahoo is an unofficial source and may throttle requests or change its schema.
The display loop is independent of quote refresh. A reusable transparent animation
reveals the live chart over about one second using the native player, avoiding
slow per-frame HTTP requests. Completed frames are renewed every five seconds.
A 60-second frame lifetime tolerates short stalls without blanking the screen.
This prototype supports daily charts only; wheel input remains deferred. The
JavaScript heap is 256 KiB and chart samples are capped at 72.

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

The bundled reveal asset can be regenerated with
`uv run scripts/build_stock_reveal.py`. It masks only the chart region and ends
fully transparent; it contains no quote data.

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

On September 28, a 0.3.2 soak reproduced a spontaneous device reboot near the end
of loading the 31-symbol watchlist. The saved `/ext/intercom_failure_log.txt`
reported `Other side is not responding`, `Unrecoverable error encountered`,
`Intercom error received: 0x4`, and Wi-Fi deinitialization. Both processors logged
lost synchronization. This establishes an internal communication failure;
it does not establish whether app traffic, firmware, or hardware triggered it.
No JavaScript out-of-memory error appeared in the saved report. The reboot
remains unresolved; the graph/prefetch changes are not a claimed crash fix.

Firmware logs are available through `/api/log_dump` and storage. Version 0.3.2
logs its startup and underlying quote/display/cache error details. Preserve the
intercom failure report before another failure overwrites it. Post-reboot menu
screens are nonblank, so a nonblank-screen check alone cannot prove app health.
