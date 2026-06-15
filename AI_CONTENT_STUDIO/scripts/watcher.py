"""
Folder Watcher
Monitors the input/ directory and triggers the pipeline automatically
when a new video file is detected and fully written.
"""

import time
from pathlib import Path
from threading import Thread
from typing import Callable, Optional, Set

from watchdog.events import FileCreatedEvent, FileSystemEventHandler
from watchdog.observers import Observer

from scripts.core.config_manager import ConfigManager
from scripts.core.file_manager import VIDEO_EXTENSIONS
from scripts.core.logger import get_logger

logger = get_logger(__name__)

# Seconds to wait after last modification before treating a file as stable
STABILITY_DELAY = 5.0


class _VideoHandler(FileSystemEventHandler):
    def __init__(
        self,
        callback: Callable[[Path], None],
        processed: Set[str],
    ) -> None:
        super().__init__()
        self._callback  = callback
        self._processed = processed
        self._pending: dict[str, float] = {}

    def on_created(self, event: FileCreatedEvent) -> None:
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix.lower() in VIDEO_EXTENSIONS:
            logger.info(f"[Watcher] New file detected: {path.name}")
            self._pending[str(path)] = time.time()

    def on_modified(self, event) -> None:
        path = Path(event.src_path)
        if str(path) in self._pending:
            self._pending[str(path)] = time.time()  # reset stability timer

    def check_stable(self) -> None:
        """Called periodically to dispatch stable files."""
        now = time.time()
        to_dispatch = [
            p for p, t in list(self._pending.items())
            if now - t >= STABILITY_DELAY
        ]
        for p_str in to_dispatch:
            del self._pending[p_str]
            path = Path(p_str)
            if str(path) in self._processed:
                logger.debug(f"[Watcher] Already processed: {path.name}")
                continue
            if path.exists() and path.stat().st_size > 0:
                self._processed.add(str(path))
                logger.info(f"[Watcher] Dispatching: {path.name}")
                self._callback(path)
            else:
                logger.warning(f"[Watcher] File disappeared or empty: {path.name}")


class Watcher:
    """
    Watch input_dir for new video files.
    For each stable new file, `on_video` callback is called in a Thread.
    """

    def __init__(
        self,
        input_dir: Path,
        on_video: Callable[[Path], None],
        poll_interval: float = 1.0,
    ) -> None:
        self._dir          = input_dir
        self._on_video     = on_video
        self._poll_interval = poll_interval
        self._processed: Set[str] = set()
        self._handler: Optional[_VideoHandler] = None
        self._observer: Optional[Observer] = None
        self._running = False

    def start(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        self._handler = _VideoHandler(self._dispatch, self._processed)
        self._observer = Observer()
        self._observer.schedule(self._handler, str(self._dir), recursive=False)
        self._observer.start()
        self._running = True
        logger.info(f"[Watcher] Watching: {self._dir}")

        # Stability-check loop
        try:
            while self._running:
                time.sleep(self._poll_interval)
                if self._handler:
                    self._handler.check_stable()
        except KeyboardInterrupt:
            self.stop()

    def stop(self) -> None:
        self._running = False
        if self._observer:
            self._observer.stop()
            self._observer.join()
        logger.info("[Watcher] Stopped.")

    # ── Internal ───────────────────────────────────────────────

    def _dispatch(self, path: Path) -> None:
        """Run pipeline in a daemon thread so watcher stays responsive."""
        t = Thread(target=self._on_video, args=(path,), daemon=True)
        t.start()
