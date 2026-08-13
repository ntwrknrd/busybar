from __future__ import annotations

import argparse
import sys

from busybar import stocks, system


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="busybar",
        description="BUSY Bar applications",
        epilog="modes: system, stocks",
    )
    result.add_argument("mode", choices=("system", "stocks"))
    return result


def main(argv: list[str] | None = None) -> None:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments or arguments[0] in ("-h", "--help"):
        parser().parse_args(arguments)
        return
    mode = arguments.pop(0)
    if mode == "system":
        system.main(arguments)
    elif mode == "stocks":
        stocks.main(arguments)
    else:
        parser().error(f"invalid mode: {mode}")
