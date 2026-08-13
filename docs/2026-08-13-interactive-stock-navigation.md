# Interactive Stock Navigation Plan

## Goal

Use the BUSY Bar rotary encoder to move through the stock watchlist:

- Clockwise selects the next symbol.
- Counterclockwise selects the previous symbol.
- Automatic rotation resumes after a short idle period.
- Navigation remains responsive without exposing the Apps screen or restarting
  the entire stock animation.

## Current Constraint

Firmware 1.1.1 does not expose physical encoder events through the HTTP API.
`POST /api/input` injects input into the device; it does not report hardware
input to the host. The status WebSocket streams device status and screen frames,
and the USB interface exposes Ethernet rather than HID input.

The feature therefore needs a small on-device component or an upstream firmware
API addition. The Python CLI should remain responsible for market data,
rendering, caching, connectivity, and asset refreshes.

## Proposed Architecture

Use a host-controlled page model with an on-device input bridge:

1. The firmware input bridge subscribes to rotary encoder events.
2. It publishes normalized `previous` and `next` events to the connected host.
3. The `busybar stocks` process maintains the selected symbol index.
4. The host requests the corresponding transition section from the current
   animation asset.
5. The device plays that transition locally at 24 FPS.
6. After an idle timeout, automatic forward rotation resumes from the selected
   symbol.

Do not make the on-device component fetch Yahoo data or own the watchlist. That
would duplicate the existing cache, refresh, and transport logic.

## Phase 1: Firmware Research

- [ ] Obtain the official BUSY Bar firmware source and build toolkit linked by
  Flipper.
- [ ] Pin the source revision matching firmware 1.1.1.
- [ ] Identify the rotary encoder driver and its clockwise, counterclockwise,
  press, and long-press events.
- [ ] Identify how the foreground Apps UI claims or consumes encoder events.
- [ ] Determine whether an external display application can register an input
  owner without replacing the stock launcher.
- [ ] Locate the HTTP and WebSocket status implementations and their existing
  message schemas.
- [ ] Build and flash an unchanged firmware image, then document the recovery
  procedure before making functional changes.

Exit criterion: an unchanged locally built image runs on the bar and encoder
events are visible in device logs.

## Phase 2: Input Transport Prototype

Prefer extending the existing authenticated status WebSocket. Add a message
such as:

```json
{
  "type": "input",
  "control": "encoder",
  "action": "next",
  "sequence": 42
}
```

- [ ] Emit `previous` and `next` once per physical detent.
- [ ] Include a monotonically increasing sequence number for duplicate
  detection after reconnects.
- [ ] Send events only to authenticated API clients.
- [ ] Define what happens when no external application owns encoder input.
- [ ] Preserve normal volume and launcher behavior outside the stocks mode.
- [ ] Confirm events work over USB Ethernet and Wi-Fi.
- [ ] Measure event-to-host latency and dropped events during fast rotation.

If extending the status WebSocket is impractical, add a dedicated authenticated
input-event WebSocket. Do not poll HTTP for encoder state.

Exit criterion: a diagnostic host client prints exactly one ordered event for
each encoder detent without breaking normal device controls.

## Phase 3: Python Client Support

- [ ] Add typed physical-input events to `busylib`, preferably upstream rather
  than as a private protocol implementation in this repository.
- [ ] Add reconnect and resubscription behavior to the BUSY Bar resolver.
- [ ] Reject stale or duplicate sequence numbers.
- [ ] Make input loss non-fatal; stocks must continue automatic rotation.
- [ ] Log input events and navigation decisions with timestamps under
  `--verbose`.
- [ ] Add unit tests using recorded WebSocket messages and reconnect sequences.

Exit criterion: a CLI diagnostic receives ordered encoder events across USB,
Wi-Fi, disconnects, and transport changes.

## Phase 4: Interactive Animation Model

The current animation is one continuously looping cycle. Interactive navigation
needs individually addressable transitions without the firmware 1.1.1 replay
bug or the Apps-screen flash caused by clearing display elements.

- [ ] Create one animation element per page transition, or fix firmware section
  replay so changing a section restarts it atomically.
- [ ] Preserve vertical direction: next swipes down; previous swipes up.
- [ ] Generate both forward and reverse transition sections for every symbol.
- [ ] Keep stable pages available as named sections.
- [ ] Coalesce rapid wheel movement so the display lands on the requested symbol
  without queueing every intermediate animation.
- [ ] Keep the current A/B asset refresh strategy and switch assets only while a
  stable page is displayed.
- [ ] Preserve the selected symbol across quote refreshes and reconnects.
- [ ] If a selected symbol disappears after a failed refresh, select the nearest
  surviving symbol in watchlist order.

Exit criterion: ten rapid detents in either direction land on the correct stock,
with no blank frame, Apps-screen flash, or stale labels.

## Phase 5: Rotation Policy

- [ ] Add an interaction idle timer, initially 30 seconds.
- [ ] Pause automatic rotation on the first encoder event.
- [ ] Reset the idle timer after every additional event.
- [ ] Resume forward automatic rotation from the currently selected symbol.
- [ ] Decide whether pressing the encoder toggles automatic rotation only after
  rotation events are reliable; do not include it in the first release.
- [ ] Add CLI options only if real use shows they are needed. Avoid speculative
  configuration.

Exit criterion: manual navigation is predictable and automatic rotation resumes
without jumping to a different logical index.

## Phase 6: Verification and Release

- [ ] Unit-test index wrapping, forward and reverse navigation, event coalescing,
  idle resume, refresh replacement, and reconnect behavior.
- [ ] Run a 30-minute USB soak test with repeated manual navigation.
- [ ] Run a 30-minute Wi-Fi soak test and force a USB-to-Wi-Fi failover.
- [ ] Test slow and fast encoder rotation.
- [ ] Confirm the wheel retains normal behavior after `busybar stocks` exits or
  crashes.
- [ ] Confirm app-scoped cleanup restores the previous BUSY Bar screen.
- [ ] Document firmware installation, rollback, compatibility, and the exact
  supported firmware revision.
- [ ] Keep non-interactive stock rotation working on unmodified firmware.

## Risks

- A firmware modification expands the maintenance and recovery burden.
- Input ownership could conflict with the launcher, volume control, or mode
  switch.
- Firmware and host clocks can drift; navigation state must not depend on
  matching animation timing.
- A custom firmware protocol may diverge from future official API releases.
- Rapid input can outpace animation playback and requires deterministic
  coalescing.

## Definition of Done

- Turning the wheel one detent changes exactly one stock in the expected
  direction.
- Navigation latency is under 150 milliseconds over USB and remains usable over
  home Wi-Fi.
- Forward and reverse transitions animate smoothly without flashing Apps.
- Automatic rotation resumes after the idle timeout from the selected symbol.
- Quote refreshes, reconnects, and transport failover preserve selection.
- Exiting the CLI restores normal wheel behavior and clears only the stocks
  application display state.
- Stock rotation continues to work on official firmware when interactive input
  support is unavailable.
