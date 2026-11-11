"""Capture the local React preview after `npm run dev -- --port 5173`."""
from pathlib import Path
from PIL import Image
import subprocess
import tempfile
import time
import sys

from render import browser

HERE = Path(__file__).resolve().parent
SCENES = [
    ("15-chat-running-1440", "?chat", 1440, 900),
    ("10-implemented-overview", "", 1850, 670),
    ("11-implemented-selected", "?selected", 1850, 670),
    ("12-implemented-dark", "?selected&dark", 1850, 670),
    ("13-implemented-narrow", "?selected", 1024, 670),
    ("14-implemented-1440", "?selected", 1440, 900),
]


def main():
    executable = browser()
    if not executable:
        raise RuntimeError("Chromium browser not found")
    with tempfile.TemporaryDirectory(prefix="twa-actual-", ignore_cleanup_errors=True) as profile:
        for name, query, width, height in SCENES:
            if len(sys.argv) > 1 and name not in sys.argv[1:]:
                continue
            output = HERE / f"{name}.png"
            pending = HERE / f"{name}.rendering.png"
            pending.unlink(missing_ok=True)
            # Chrome reserves about 100px for the headless window frame on Windows.
            command = [executable, "--headless=new", "--disable-gpu", "--no-first-run", "--disable-breakpad", "--disable-crash-reporter", "--disable-background-networking", "--virtual-time-budget=2000", f"--user-data-dir={Path(profile) / name}", f"--window-size={width},{height + 100}", f"--screenshot={pending}", f"http://127.0.0.1:5173/trajectory-preview.html{query}"]
            process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline and (not pending.exists() or pending.stat().st_size < 1024):
                    time.sleep(.2)
                if not pending.exists() or pending.stat().st_size < 1024:
                    raise RuntimeError(f"Screenshot not produced: {name}")
                with Image.open(pending) as shot:
                    shot.crop((0, 0, width, height)).save(output)
                pending.unlink(missing_ok=True)
                print(f"{name}.png: {output.stat().st_size} bytes", flush=True)
            finally:
                if process.poll() is None:
                    process.kill()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass


if __name__ == "__main__":
    main()
