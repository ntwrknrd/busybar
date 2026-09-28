# Stocks reboot investigation

## Confirmed failure

On September 28, 2026, Stocks 0.3.4 on official firmware 1.2.4 reproduced a
whole-device reboot while connected over USB Ethernet. This is more than an app
exception or loss of Wi-Fi access. The firmware supervisor deliberately rebooted
after its internal link to the Si917 processor failed.

A main-processor Telnet trace captured this sequence (milliseconds of uptime):

```text
288691 Stocks 0.3.4 started
315223 LogStorage: Remote log overrun occurred
316956 CliIntercom: Intercom lost sync, signaling death
316959 Intercom: Other side is not responding
316961 Intercom: Unrecoverable error encountered. Suspending service...
316972 Supervisor: Intercom error received: 0x4
317010 LogStorage: Log dump saved to /ext/intercom_failure_log.txt
317014 Supervisor: Rebooting...
```

A subsequent USB uptime query reported eight seconds. The saved report also
contains Si917 packet drops and intercom desynchronization. It contains no
JavaScript out-of-memory fatal, DHCP failure, or Wi-Fi response-queue overrun
before this failure. `Remote log overrun` is not the same error as
`WifiSrv BUG: response queue overrun`.

An earlier 0.3.2 failure occurred after an update check at about 600 seconds of
uptime. This reproduction failed at about 317 seconds, so that scheduled update
check is not necessary to trigger the failure. No firmware or network settings
were changed.

## Related upstream reports

All reports below remained open when checked on September 28. The latest
[official release](https://github.com/busy-app/busybar-firmware/releases/tag/1.2.4)
was still 1.2.4, released September 11.

- [Issue 949](https://github.com/busy-app/busybar-firmware/issues/949): firmware
  1.1.1, DHCP reconnect loop and Wi-Fi response-queue overrun ending in intercom
  timeout `0x4` and reboot. Same terminal failure, different observed precursor.
  The device reportedly failed while idle, without application API traffic.
- [Issue 940](https://github.com/busy-app/busybar-firmware/issues/940): host/radio
  connection-state disagreement and loss of API access. One comment describes an
  app updating the display once per minute and failing after about three hours.
  Maintainer guidance is USB Telnet, `sl_cli`, then `log debug` before reproducing.
- [Issue 1042](https://github.com/busy-app/busybar-firmware/issues/1042): firmware
  1.2.4, host file updates and an on-device JS reader; storage errors followed by
  HTTP service failure over both USB and Wi-Fi. Related reliability concern,
  but not evidence of the same reboot mechanism.
- [Issue 1045](https://github.com/busy-app/busybar-firmware/issues/1045): firmware
  1.2.4 and development builds, native C fetch/display freeze. The report explicitly
  distinguishes JavaScript apps, so this is an adjacent report, not a match.

The 1.2.4 source still has the four-entry Wi-Fi response queue and 200 ms enqueue
wait described in issue 949. This makes the report relevant, but does not prove
that our failure uses that path. The radio's packet-drop message incorrectly
prints its transmit-drop counter for a receive drop; repeated `(0 total)` lines
therefore do not mean no receive packets were dropped.

## Isolation tests

Temporary device scripts preserve the production script and use the same
manifest, heap limit, quote parsing, and graphics unless explicitly disabled.
Raw reports remain local because they contain device and network identifiers.

| Build | Observation | Limit |
| --- | --- | --- |
| Production 0.3.4 | Reboot after about 28 seconds from startup log | Full firmware intercom trace captured |
| Cached rendering and animation, no Yahoo fetches | About 170 seconds without reboot; five cached charts rendered | Short control; stops advancing at the last cached symbol |
| Quote-only, no rendering | About 170 seconds of successful AAPL/AMZN HTTPS fetches and cache writes | Repeats two symbols; refresh eligibility shortened to ten seconds |
| Serialized quote and display requests | Reboot after about 32 seconds | No overlapping app requests in trace; serialization alone is insufficient |
| Full app with reveal disabled | Over nine minutes; all 31 symbols rendered, then AAPL/AMZN refreshed and rendered again; no reboot or quote/display errors | One bounded run, not proof of long-term stability |

The serialized test rebooted at uptime 497 seconds, again with supervisor error
`0x4`. Its last quote response completed at 476 seconds, followed by multiple
successful display requests before the failure. The radio reported lost sync
around 489 seconds. This weakens the simple concurrent-request explanation.
The no-animation combined run logged successful AAPL rendering at uptime
69.505 seconds and AMZN on the second rotation at 611.686 seconds. All 31 symbols
had successful display acknowledgements. The firmware update parser also logged
its scheduled check at 602.887 seconds, without an immediate reboot.

## Mitigation and limits

Version 0.3.5 disables only the native reveal through `ENABLE_REVEAL = false`.
The asset is retained for future isolated tests. Layout, quote source, previous-
close baseline, ready-only rotation, and next-chart prefetch are preserved.
No speculative serialization or heap-size changes are included.

The controls point toward an interaction involving animation and the combined
workload. They do not prove an animation-library defect: timing, workload, and
logging can influence reproduction. The short rendering-only and fetch-only
passes do not establish that either path can never fail alone. No C stack trace
identifies the original blocked operation. Longer runs and repeat comparisons
remain necessary; the draft PR should remain open pending stability confidence.

The JavaScript transition regression and all existing behavior checks pass:
19 JavaScript tests and 54 Python tests. Raw device reports and temporary test
scripts remain local; the excerpts here omit device and network identifiers.

## Further debugging

- Preserve `/ext/intercom_failure_log.txt` immediately after each failure;
  subsequent failures overwrite it. Capture USB Telnet logs before the failure.
- Use uptime to distinguish device reboots from app exits. A nonblank screenshot
  may simply be Start/Setup and is not an app-health check.
- Compare cached rendering, quote-only fetches, and serialized rendering/fetching.
  Keep animation in the cached control to test whether it can run independently.
- Repeat any promising mitigation across the entire watchlist and refresh cycles;
  a short pass cannot establish stability.
- If network-only requests reproduce the failure, compare a small local HTTP
  fixture with Yahoo HTTPS to separate transport, TLS, payload size, and parsing.
- If failures persist with reduced application traffic, correlate access-point
  disconnect/DHCP logs with device timestamps and compare another access point.
  Do not change several router settings at once.
- Prefer read-only uptime, heap, and thread snapshots at low frequency. Heavy
  logging or frequent screenshot polling can change timing and add load.
- Avoid the firmware's persistent debug flag during normal use: upstream reports
  say it suppresses automatic recovery and can leave the device wedged.

No upstream issue or comment has been posted from this investigation.

## Separate minimal test app

The user reported roughly an hour of stable use with the reveal disabled. Before
the separate experiment, USB uptime was 1 hour 4 minutes and the installed
Stocks 0.3.5 files matched the repository.

`app.ntwrknrd.repro` uses the same 256 KiB heap limit and a separate application
ID. It has a fixed diagonal chart, four rear counter labels, the original reveal
asset, and repeated AAPL Yahoo HTTPS requests. It removes the watchlist, cache,
price formatting, and repeated bitmap calculation from the first four phases.
All phases update the display every five seconds; animation, when enabled,
replays every ten seconds. A short USB front-screen capture confirmed that the
reveal actually played, with four distinct partial/full chart frames.

The original four-phase build runs each phase for three minutes, draining
in-flight requests at transitions. Follow-up phases add test-app cache access
and repeated bitmap allocation separately. The six fps asset differs only in
its frame-rate byte and uses a longer expiry to permit complete playback.
The [test app guide](../device-apps/REPRO.md) describes the reproducible setup.

| Phase | Successful display updates | Valid HTTPS responses | Errors | Reboot |
| --- | --- | --- | --- | --- |
| BOTH 24FPS | 36 | 36 | 0 | No |
| ANIM ONLY | 36 | 0 | 0 | No |
| FETCH ONLY (static display) | 36 | 36 | 0 | No |
| BOTH 6FPS | 36 | 36 | 0 | No |
| CACHE 24FPS | 36 | 36 | 0 | No |
| REBUILD 24FPS | 36 | 36 | 0 | No |

These four phases ran for about twelve minutes total. The source also confirms
that raw-image updates allocate and copy a new native buffer, even when image
content is unchanged. A fixed chart is therefore not a no-op at the native image
layer. The follow-up cache and bitmap-rebuild phases also passed. Across the six
approximately three-minute phases there were 216 successful display updates and
180 valid HTTPS responses. The cache phase used one diagnostic quote entry,
not a full watchlist-sized database. The rebuild phase used a simple fixed
bitmap, not Stocks' full chart and typography workload. These limits matter.

A short follow-up full-workload control copies the full animated Stocks workload into
the test app's namespace and seeds only that namespace with a read-only copy of
Stocks' saved quotes. Production Stocks remains unchanged. This full-workload control reproduced the
same reboot after approximately 170 seconds, despite the minimal controls
passing beforehand:

```text
5200096 REPRO STOCKS full started
5357710 REPRO quote DELL
5364345 REPRO page DELL
5368908 LogStorage: Remote log overrun occurred
5370388 CliIntercom: Intercom lost sync, signaling death
5370401 Supervisor: Intercom error received: 0x4
5370473 Supervisor: Rebooting...
```

A subsequent USB query reported 1 minute 24 seconds of uptime, confirming the
reset. The saved report includes a radio receive drop roughly 73 seconds before
the supervisor failure, then a burst of drops and radio desynchronization near
the failure. There is no corresponding JavaScript heap fatal or DHCP-failure
sequence in the captured report.

A follow-up full-workload control disables only `localStorage.setItem` writes.
Reads, the seeded quote fixture, chart generation, animation, and request
scheduling are retained. This control also rebooted: startup at 138.965 seconds, supervisor `0x4` at
255.355 seconds, or about 116 seconds later. Its crash report was preserved
separately, and a later uptime query reported 1 minute 51 seconds. Cache writes
are therefore not necessary for this failure.

One final control retains the complete animated workload and cache writes but
computes its front bitmap only once, from the first available quote. The rear
labels, watchlist, prefetch, cache reads/writes, and reveal continue to run. The
front deliberately stays on the first quote: it is a diagnostic comparison,
not a proposed production UI. This control ran from startup at 127.773 seconds through successful page
acknowledgements at 442.371 seconds: over five minutes, advancing the rear
watchlist through 27 symbols, with no quote/display error or reboot. The front
remained intentionally fixed. Cache writes were enabled throughout.

| Full-workload control | Result |
| --- | --- |
| Original animated workload in test namespace | Reboot after about 170 seconds |
| Same workload, cache writes disabled | Reboot after about 116 seconds |
| Same workload, first front bitmap reused | Over five minutes without reboot; 27 rear symbols |

This makes repeated front bitmap generation and its interaction with the wider
workload the strongest remaining lead. It does not identify the underlying
firmware defect: reusing the image also changes timing, allocation pressure,
and rendered content. The five-minute pass is not proof of long-term stability.
Cache writes are not required for the failure. Animation, HTTPS, a small cache,
and a simpler bitmap rebuild each passed the minimal combined tests.

The diagnostic app was restored to its canonical six-phase script and its own
single-entry probe cache. Readback verified all four diagnostic files and all
three stable Stocks files. Stocks' original saved-quote file still matched the
pre-test fixture byte-for-byte before Stocks was restarted. No production
rendering changes were made and no upstream issue was opened.

Next investigation: measure front-generation duration and allocation behavior;
compare caching the current page's rendered bitmap against fresh rendering on
each five-second renewal, with repeated A/B runs and a longer soak. Preserve
correct live updates by invalidating on symbol, quote, or status changes. Keep
the stable no-reveal Stocks build until a real dynamic-chart version passes.

`scripts/build_stock_repro.py` reproduces all three full-workload control scripts
exactly, checks the expected source before transforming it, and never installs
or overwrites output files. The small app's three automated tests cover phase
handoff, workload isolation, and asset frame-rate differences. The existing
19 Stocks JavaScript tests and 54 Python tests also pass.

A successful phase means only that the specific
workload did not reproduce the fault during its bounded observation window.
It does not establish that animation, storage, or networking is fault-free.
