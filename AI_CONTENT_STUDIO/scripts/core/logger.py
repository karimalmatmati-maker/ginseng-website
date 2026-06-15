"""Centralised logging for AI Content Studio."""

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional


_ROOT_LOGGER = "ai_content_studio"


def setup_logger(
    log_dir: Path,
    level: int = logging.INFO,
    name: str = _ROOT_LOGGER,
) -> logging.Logger:
    """Configure and return the root logger. Safe to call multiple times."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(level)
    logger.propagate = False

    fmt = logging.Formatter(
        fmt="[%(asctime)s] %(levelname)-8s %(name)-35s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"studio_{datetime.now().strftime('%Y%m%d')}.log"

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(level)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(level)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    return logger


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Return a child logger under the root studio namespace."""
    if name is None:
        return logging.getLogger(_ROOT_LOGGER)
    if name.startswith(_ROOT_LOGGER):
        return logging.getLogger(name)
    short = name.rsplit(".", 1)[-1]
    return logging.getLogger(f"{_ROOT_LOGGER}.{short}")
