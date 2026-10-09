"""Find source resumes in folders, and watch folders for new or changed ones."""

import threading
import time
from collections.abc import Callable
from pathlib import Path

SUFFIXES = (".html", ".tex")  # the two tools' outputs; other formats are ingested one at a time


def find_sources(folder: Path) -> list[Path]:
    """Every .html and .tex file under the folder, in a stable order."""
    files = (path for path in folder.rglob("*") if path.is_file())
    return sorted(path for path in files if path.suffix.lower() in SUFFIXES)


def _stamps(folders: list[Path]) -> dict[Path, float]:
    stamps = {}
    for folder in folders:
        for path in find_sources(folder):
            try:
                stamps[path] = path.stat().st_mtime
            except OSError:  # deleted between listing and stat
                continue
    return stamps


def watch(
    folders: list[Path],
    handle: Callable[[Path], object],
    stop: threading.Event | None = None,
    interval: float = 1.0,
) -> None:
    """Call handle(path) for each file that appears or changes, until `stop` is set.

    Files already present when watching starts are left alone (use `cvforge batch` for
    those). A file is handled once its timestamp has held still for one interval, so a
    half-written file is never picked up.

    # ponytail: polls modification times with the standard library; fine for a few folders,
    # switch to the watchdog package if a watched tree ever holds thousands of files.
    """
    seen = _stamps(folders)
    settling: dict[Path, float] = {}
    while not (stop and stop.is_set()):
        for path, stamp in _stamps(folders).items():
            if seen.get(path) == stamp:
                continue
            if settling.get(path) == stamp:
                seen[path] = stamp
                del settling[path]
                handle(path)
            else:
                settling[path] = stamp
        if stop:
            stop.wait(interval)
        else:
            time.sleep(interval)
