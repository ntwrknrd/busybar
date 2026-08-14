from __future__ import annotations

import sys
from datetime import datetime


def status(message: str, *, timestamp: bool = False) -> None:
    prefix = ""
    if timestamp:
        now = datetime.now().astimezone().isoformat(timespec="milliseconds")
        prefix = f"[{now}] "
    print(f"{prefix}{message}", file=sys.stderr)
