# TODO

## Interactive Stock Navigation

- [ ] Build and flash an unchanged firmware 1.1.1 image; prove rollback first.
- [ ] Capture clockwise and counterclockwise encoder events on-device.
- [ ] Publish authenticated physical-input events over WebSocket.
- [ ] Add typed event subscription, reconnect, and deduplication to `busylib`.
- [ ] Generate forward and reverse stock transition sections.
- [ ] Switch pages without clearing the display or exposing the Apps screen.
- [ ] Coalesce rapid wheel movement and preserve the selected symbol.
- [ ] Resume automatic rotation after 30 seconds without input.
- [ ] Preserve automatic-only behavior on unmodified firmware.
- [ ] Complete USB and Wi-Fi latency, failover, and soak tests.

The detailed architecture, phases, risks, and acceptance criteria are in
[the interactive navigation plan](docs/2026-08-13-interactive-stock-navigation.md).
