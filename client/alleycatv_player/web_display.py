"""Display a web page fullscreen via Chromium kiosk mode."""
from __future__ import annotations

import logging
import shutil
import subprocess
import time
from typing import Optional

_LOGGER = logging.getLogger(__name__)

_CHROMIUM_CANDIDATES = (
    "chromium-browser",
    "chromium",
    "google-chrome-stable",
    "google-chrome",
)


def _find_chromium() -> Optional[str]:
    for name in _CHROMIUM_CANDIDATES:
        path = shutil.which(name)
        if path:
            return path
    return None


class WebDisplay:
    """Launch Chromium in kiosk mode for scoreboard / webpage playlist items."""

    def __init__(self) -> None:
        self._proc: Optional[subprocess.Popen] = None
        self._binary = _find_chromium()

    @property
    def available(self) -> bool:
        return self._binary is not None

    def show(self, url: str, duration: int) -> bool:
        """Open URL fullscreen for duration seconds. Returns True if displayed."""
        if not self.open(url):
            return False
        try:
            time.sleep(max(1, duration))
            return True
        finally:
            self.close()

    def open(self, url: str) -> bool:
        """Open URL fullscreen until close() is called."""
        if not self._binary:
            _LOGGER.warning("Chromium not installed — skipping webpage: %s", url)
            return False

        self.close()

        cmd = [
            self._binary,
            "--kiosk",
            "--noerrdialogs",
            "--disable-infobars",
            "--no-first-run",
            "--disable-session-crashed-bubble",
            f"--app={url}",
        ]
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            _LOGGER.info("Webpage display: %s", url)
            return True
        except Exception as exc:
            _LOGGER.error("Failed to open webpage %s: %s", url, exc)
            return False

    def close(self) -> None:
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=5)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
        self._proc = None
