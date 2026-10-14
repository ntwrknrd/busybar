"""Build a full-workload diagnostic script without modifying Stocks or a device."""

import argparse
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "device-apps/app.ntwrknrd.stocks/scripts/main.js"


def build_control(mode: str) -> str:
    if mode not in {"full", "nowrite", "fixedfront"}:
        raise ValueError("Unknown control mode")
    source = SOURCE.read_text()

    def replace(old: str, new: str) -> None:
        nonlocal source
        if source.count(old) != 1:
            raise ValueError(f"Stocks source changed; review diagnostic transformation: {old}")
        source = source.replace(old, new)

    replace('const APP_ID = "app.ntwrknrd.stocks";', 'const APP_ID = "app.ntwrknrd.repro";')
    replace("const ENABLE_REVEAL = false;", "const ENABLE_REVEAL = true;")
    replace('path:"scripts/reveal.anim"', 'path:"scripts/reveal24.anim"')
    replace('console.info("Stocks 0.3.5 started");', f'console.info("REPRO STOCKS {mode} started");')
    if mode == "nowrite":
        replace(
            'try{localStorage.setItem("quote-v1-"+symbol,JSON.stringify(q));}'
            'catch(error){console.error("Cache write failed: "+String(error));}',
            "// Cache writes disabled for isolation.",
        )
    if mode == "fixedfront":
        replace("function front(symbol, q, now) {", "function computeFront(symbol, q, now) {")
        replace(
            "function text(id,value,y)",
            "let fixedFront=null;\nfunction front(symbol,q,now) {\n"
            "    if(!fixedFront && q)fixedFront=computeFront(symbol,q,now);\n"
            "    return fixedFront || computeFront(symbol,q,now);\n}\n"
            "function text(id,value,y)",
        )
    replace(
        "currentIndex=index;sceneSymbol=symbol;",
        'console.info("REPRO page "+symbol);currentIndex=index;sceneSymbol=symbol;',
    )
    replace(
        "const q=parse(body,symbol,Date.now());",
        'console.info("REPRO quote "+symbol);const q=parse(body,symbol,Date.now());',
    )
    return source


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("full", "nowrite", "fixedfront"))
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    script = build_control(args.mode)
    with args.output.open("x") as output:
        output.write(script)
