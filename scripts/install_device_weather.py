"""Install the experimental weather app without replacing existing device files."""

from pathlib import Path

from busybar.device import resolve


APP_ID = "app.ntwrknrd.weather"
ROOT = Path(__file__).resolve().parents[1] / "device-apps" / APP_ID
REMOTE = f"/ext/user_assets/{APP_ID}"
FLAG_DIR = "/ext/apps_data/apps_menu"


def main() -> None:
    bar, route = resolve()
    try:
        if bar.is_cloud:
            raise RuntimeError("Installation requires a local USB or Wi-Fi connection")
        version = bar.status_firmware().version
        if version != "1.2.4":
            raise RuntimeError(f"This prototype is verified only for 1.2.4, got {version}")
        files = sorted(p for p in ROOT.rglob("*") if p.is_file())
        installed = {entry.name for entry in bar.storage_list("/ext/user_assets").list}
        if APP_ID in installed:
            for source in files:
                target = f"{REMOTE}/{source.relative_to(ROOT).as_posix()}"
                if bar.storage_read(target) != source.read_bytes():
                    raise RuntimeError(
                        "An existing weather installation differs; preserve it before updating"
                    )
        else:
            bar.storage_mkdir(REMOTE)
            for name in ("appmeta", "scripts"):
                bar.storage_mkdir(f"{REMOTE}/{name}")
            # Publish the manifest last so an incomplete upload cannot be launched.
            for source in sorted(files, key=lambda p: p.name == "manifest.json"):
                target = f"{REMOTE}/{source.relative_to(ROOT).as_posix()}"
                data = source.read_bytes()
                bar.storage_write(target, data)
                if bar.storage_read(target) != data:
                    raise RuntimeError(f"Upload verification failed: {source.name}")
        existing = {entry.name for entry in bar.storage_list(FLAG_DIR).list}
        if "js_apps_enabled" not in existing:
            bar.storage_write(f"{FLAG_DIR}/js_apps_enabled", b"")
        if "js_apps_enabled" not in {
            entry.name for entry in bar.storage_list(FLAG_DIR).list
        }:
            raise RuntimeError("Experimental Apps-menu flag was not created")
        print(f"Verified Carmel Weather installation via {route.name} on firmware {version}.")
        print("Reload Apps with the mode switch, then select Carmel Weather > Start.")
    finally:
        bar.close()


if __name__ == "__main__":
    main()
