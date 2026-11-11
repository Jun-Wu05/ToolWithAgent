"""Render the deterministic HTML design states with a local Chromium browser."""

from pathlib import Path
import subprocess
import tempfile
import time
import sys
from PIL import Image


HERE = Path(__file__).resolve().parent
SCENES = [
    ("01-chat-running", "chat-running", 1850, 670),
    ("02-chat-confirm", "chat-confirm", 1850, 670),
    ("03-chat-complete", "chat-complete", 1850, 670),
    ("04-trace-overview", "trace-overview", 1850, 670),
    ("05-trace-selected", "trace-selected", 1850, 670),
    ("06-trace-failure", "trace-failure", 1850, 670),
    ("07-dark", "dark", 1850, 670),
    ("08-narrow-1024", "narrow", 1024, 670),
    ("09-trace-1440", "trace-selected", 1440, 900),
]


def browser():
    options = [
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    ]
    return next((str(path) for path in options if path.exists()), None)


def render():
    executable = browser()
    if not executable:
        raise RuntimeError("Chromium browser not found")
    with tempfile.TemporaryDirectory(prefix="twa-design-", ignore_cleanup_errors=True) as profile:
        for filename, scene, width, height in SCENES:
            if len(sys.argv) > 1 and filename not in sys.argv[1:]:
                continue
            output = HERE / f"{filename}.png"
            pending = HERE / f"{filename}.rendering.png"
            pending.unlink(missing_ok=True)
            for attempt in range(1, 4):
                command = [
                    executable, "--headless=new", "--disable-gpu", "--no-first-run",
                    "--disable-breakpad", "--disable-crash-reporter", "--disable-background-networking",
                    f"--user-data-dir={Path(profile) / f'{scene}-{attempt}'}", f"--window-size={width},{height + 100}",
                    f"--screenshot={pending}", f"{(HERE / 'index.html').as_uri()}?scene={scene}",
                ]
                process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                try:
                    deadline = time.monotonic() + 45
                    while time.monotonic() < deadline and (not pending.exists() or pending.stat().st_size < 1024):
                        time.sleep(0.2)
                    if pending.exists() and pending.stat().st_size >= 1024:
                        with Image.open(pending) as screenshot:
                            screenshot.crop((0, 0, width, height)).save(output)
                        pending.unlink(missing_ok=True)
                        print(f"{filename}.png: {output.stat().st_size} bytes", flush=True)
                        break
                    if attempt == 3:
                        raise RuntimeError(f"Screenshot not produced: {filename}")
                finally:
                    if process.poll() is None:
                        try:
                            subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, check=False)
                        except subprocess.TimeoutExpired:
                            process.kill()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)


if __name__ == "__main__":
    render()
