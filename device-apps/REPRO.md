# Isolated animation and HTTPS test

`app.ntwrknrd.repro` is a separate diagnostic app for official firmware 1.2.4.
It does not read or write Stocks' installation, saved quotes, or settings.
Stop Stocks before starting **Repro Test** from the Apps menu.

Six phases run automatically, each for approximately three minutes. An in-flight
operation must finish before the next phase starts. Console lines prefixed
`REPRO` identify phase boundaries and operation counts every 30 seconds.

| Phase | Display | External requests |
| --- | --- | --- |
| BOTH 24FPS | Fixed chart with the original reveal every ten seconds | AAPL Yahoo HTTPS every five seconds |
| ANIM ONLY | Same fixed chart and reveal | None from this app |
| FETCH ONLY | Fixed chart and counters, no animation | Same Yahoo requests |
| BOTH 6FPS | Same reveal frames at six fps | Same Yahoo requests |
| CACHE 24FPS | Original reveal plus diagnostic cache read on each update | Same Yahoo requests; save price and 72 samples in this app's own cache |
| REBUILD 24FPS | Original reveal plus bitmap rebuilding on each update | Same Yahoo requests; no cache access |

All phases renew the display every five seconds. Each request type permits only
one in-flight request; display and quote requests may overlap. HTTPS responses
are consumed and parsed completely, but there is no watchlist or price formatting. Only CACHE 24FPS uses localStorage,
under this test app's ID and a single `probe` key. Only REBUILD 24FPS regenerates
the bitmap; all other phases reuse a prebuilt bitmap.
The 24 fps asset is identical to Stocks' retained reveal; the six fps asset
changes only the frame-rate header byte. Its timeout increases from two to five
seconds so all 23 frames can play.

Upload `scripts/` first and publish `appmeta/manifest.json` last, under
`/ext/user_assets/app.ntwrknrd.repro/`. Read back all four files and compare
against the repository before launching. Refuse to overwrite a differing
installation without first preserving it. Firmware's existing experimental
Apps flag must be enabled, as it is for Stocks.

Connect USB before running. Capture the main CLI's `log info` over Telnet at
`10.0.4.20:23`. A reboot requires an uptime reset or an explicit supervisor log;
a lost connection alone is inconclusive. Preserve
`/ext/intercom_failure_log.txt` immediately after a failure. Logs can contain
private device/network identifiers and must be sanitized before sharing.

For a targeted rerun, set `START_PHASE` to the desired zero-based phase index
before uploading a preserved test copy. The repository default is zero.

`REPRO COMPLETE` marks the end of the sequence. Stop the test and return to
Stocks afterward. No firmware or router setting changes are needed.

Run `node --test tests/test_device_repro.cjs` to validate phase sequencing,
in-flight draining, and the controlled frame-rate asset difference. Hardware
results belong in the [investigation](../plans/2026-09-28-stocks-reboot-investigation.md).
Short successful phases do not establish long-term stability or rule out timing
and combined workload effects.

## Full-workload comparison

For the September 28 comparison, a temporary test script was derived from
Stocks at commit `9c503c5`. Its app ID was changed to `app.ntwrknrd.repro`,
`ENABLE_REVEAL` was set to true, and the asset path was changed to
`scripts/reveal24.anim`. Startup, successful quote, and successful page messages
identified the control in USB logs. Stocks' saved quote file was read and copied
only into the test app's namespace while the test app was stopped. The original
Stocks script, manifest, asset, and saved quotes were not modified.

This comparison has a larger workload than the small app and includes the
watchlist, cached quotes, changing charts, and price/status labels. It remains a
bounded reproduction attempt: logging, warm cache, timing, and the different app
ID can affect results. Restore the six-phase script and its single-entry probe
cache afterward, then return the Bar to the stable Stocks app.

Two additional full-workload comparisons were derived from the same source:
`nowrite` removes only the successful-quote `localStorage.setItem` call;
`fixedfront` retains cache writes but memoizes the first valid front bitmap.
The latter intentionally freezes the front quote while the rear continues to
rotate. Neither is intended as a user-facing Stocks release.

Generate these full-workload controls without editing Stocks:

```sh
uv run scripts/build_stock_repro.py full /tmp/repro-full.js
uv run scripts/build_stock_repro.py nowrite /tmp/repro-nowrite.js
uv run scripts/build_stock_repro.py fixedfront /tmp/repro-fixedfront.js
```

The builder refuses to overwrite an output and fails if its expected Stocks
source has changed. It does not install anything. Preserve the test app's
existing script, stop it, stage and read back the selected control, and publish
it as the test app's `scripts/main.js`. Keep the original Stocks app untouched.
The generated scripts matched the exact scripts used in the recorded controls.
Generated controls should replace only the diagnostic app's entry point, never
the production Stocks script.
