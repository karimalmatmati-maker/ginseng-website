"""File and directory helpers for AI Content Studio."""

import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from .logger import get_logger

logger = get_logger(__name__)

VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".mts"}


class FileManager:
    """Resolves paths and manages project output directories."""

    def __init__(self, studio_root: Path, config: "ConfigManager") -> None:  # noqa: F821
        self.root = studio_root.resolve()
        self._cfg = config

    # ── Directory resolution ───────────────────────────────────

    def dir(self, key: str) -> Path:
        rel = self._cfg.get(f"paths.{key}", key)
        path = self.root / rel
        path.mkdir(parents=True, exist_ok=True)
        return path

    def input_dir(self) -> Path:
        return self.dir("input")

    def output_dir(self) -> Path:
        return self.dir("output")

    def shorts_dir(self, platform: str = "youtube") -> Path:
        return self.dir(f"shorts_{platform}")

    def audio_dir(self) -> Path:
        return self.dir("audio")

    def subtitles_dir(self) -> Path:
        return self.dir("subtitles")

    def thumbnails_dir(self) -> Path:
        return self.dir("thumbnails")

    def metadata_dir(self) -> Path:
        return self.dir("metadata")

    def reports_dir(self) -> Path:
        return self.dir("reports")

    def logs_dir(self) -> Path:
        return self.dir("logs")

    # ── Per-video project folder ───────────────────────────────

    def project_dir(self, video_path: Path) -> Path:
        slug = video_path.stem
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        folder = self.output_dir() / f"{slug}_{ts}"
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    # ── Scan helpers ───────────────────────────────────────────

    def scan_input(self) -> List[Path]:
        folder = self.input_dir()
        found = [p for p in folder.iterdir() if p.suffix.lower() in VIDEO_EXTENSIONS]
        logger.debug(f"Input scan: {len(found)} video(s) found")
        return found

    # ── Generic utilities ──────────────────────────────────────

    @staticmethod
    def ensure_dir(path: Path) -> Path:
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def safe_copy(src: Path, dst: Path) -> Path:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return dst

    @staticmethod
    def stem_with_suffix(path: Path, suffix: str) -> str:
        return f"{path.stem}{suffix}"

    @staticmethod
    def timestamp_str() -> str:
        return datetime.now().strftime("%Y%m%d_%H%M%S")
