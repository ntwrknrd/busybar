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

## Deferred: Custom Firmware and On-Device Apps

Start from the official
[`busybar-firmware`](https://github.com/busy-app/busybar-firmware) `1.1.1` tag,
which matches the firmware currently installed on the BUSY Bar. Do not base the
first attempt on `dev`, unsigned presets, or the full wireless-firmware flashing
path.

- [ ] Clone firmware recursively at tag `1.1.1` and create a feature branch.
- [ ] Build the unchanged target-22 firmware with `./fbt TARGET_HW=22`.
- [ ] Reflash the unchanged image with `./fbt flash_usb` to prove the build,
      update, and rollback paths before modifying anything.
- [ ] Add a minimal C debug app under `applications/debug/`, register it in
      `debug_apps.provides`, and launch it through Developer Mode.
- [ ] Verify wheel and button input plus rendering on both displays.
- [ ] Inspect the generated update bundle before flashing the custom image.
- [ ] Promote a stable app to `applications/main/` and the Apps menu only after
      the debug-app prototype works.
- [ ] Optionally map the physical CUSTOM selector position directly to the app
      in `applications/services/desktop/desktop.c`.
- [ ] Design a narrow HTTP or WebSocket contract if an on-device app needs to
      exchange events or data with the macOS CLI.
- [ ] Reimplement any selected Python host-mode behavior in firmware C; host
      modes cannot run on-device unchanged.
- [ ] Document and test rollback to a clean `1.1.1` checkout.

Current firmware contains external-app build scaffolding, but its Apps menu and
loader use compiled-in application lists. Treat custom apps as firmware builds,
not runtime-installable packages, until the loader gains that capability.

Use only the normal signed `flash_usb` path for the first prototype. Avoid
`flash_usb_full`: it also updates the SiWG917 wireless firmware and needs Flipper
signing configuration. If a custom image no longer boots far enough to expose
the USB updater, recovery requires SWD access, partial disassembly, and the BSB
debug board.
