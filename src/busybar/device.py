from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass

from busylib import BusyBar, BusyBarDevices, exceptions

USB_ADDRESS = "10.0.4.20"
BETTER_CONNECTION_POLL_SECONDS = 30
RECONNECT_DELAYS = (1, 2, 5, 10, 30)


@dataclass(frozen=True)
class Candidate:
    name: str
    address: str | None
    token: str | None
    rank: int

    def connect(self) -> BusyBar:
        if self.name == "cloud":
            return BusyBar(token=self.token, timeout=3, max_retries=0)
        return BusyBar(self.address, token=self.token, timeout=2, max_retries=0)


def candidates() -> Iterator[Candidate]:
    lan_token = os.getenv("BUSYBAR_LAN_TOKEN") or None
    seen: set[str] = set()
    found: list[Candidate] = []

    try:
        devices = BusyBarDevices.discover()
    except Exception:
        devices = []

    for device in devices:
        for affinity, token, rank in (
            ("over_usb", None, 0),
            ("over_wifi", lan_token, 1),
        ):
            address = device.get_address(affinity)
            if address and address not in seen:
                seen.add(address)
                found.append(
                    Candidate(
                        f"mDNS {affinity.removeprefix('over_')}", address, token, rank
                    )
                )

    if USB_ADDRESS not in seen:
        seen.add(USB_ADDRESS)
        found.append(Candidate("USB", USB_ADDRESS, None, 0))

    home_address = os.getenv("BUSYBAR_HOME_IP")
    if home_address and home_address not in seen:
        seen.add(home_address)
        found.append(Candidate("home LAN", home_address, lan_token, 1))

    cloud_token = os.getenv("BUSYBAR_CLOUD_TOKEN")
    if cloud_token:
        found.append(Candidate("cloud", None, cloud_token, 2))

    yield from sorted(found, key=lambda candidate: candidate.rank)


def resolve() -> tuple[BusyBar, Candidate]:
    expected_serial = os.getenv("BUSYBAR_SERIAL_NUMBER")
    if not expected_serial:
        raise RuntimeError("BUSYBAR_SERIAL_NUMBER is not set")

    failures: list[str] = []
    for candidate in candidates():
        bar = candidate.connect()
        try:
            status = bar.status()
            serial = status.device.serial_number if status.device else None
            if serial != expected_serial:
                failures.append(f"{candidate.name}: serial mismatch")
                bar.close()
                continue
            return bar, candidate
        except Exception as exc:
            failures.append(f"{candidate.name}: {type(exc).__name__}")
            bar.close()

    detail = "; ".join(failures) or "no connection candidates"
    raise RuntimeError(f"BUSY Bar not reachable ({detail})")


def reconnect_delay(attempt: int) -> int:
    return RECONNECT_DELAYS[min(attempt, len(RECONNECT_DELAYS) - 1)]


def same_route(left: Candidate, right: Candidate) -> bool:
    return left.address == right.address and left.rank == right.rank


def is_better(new: Candidate, current: Candidate) -> bool:
    return new.rank < current.rank


def display_is_busy(exc: Exception) -> bool:
    return isinstance(exc, exceptions.BusyBarAPIError) and exc.status_code == 409
