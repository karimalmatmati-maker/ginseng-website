"""
AI Content Studio — Main Entry Point

Usage:
  # Watch input/ folder (drop-and-process mode)
  python main.py watch

  # Process a single file
  python main.py process path/to/video.mp4

  # Process with options
  python main.py process video.mp4 --shorts 10 --duration 30

  # List generated outputs
  python main.py status
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.core.config_manager import ConfigManager
from scripts.core.file_manager import FileManager
from scripts.core.logger import setup_logger, get_logger
from scripts.pipeline import Pipeline
from scripts.watcher import Watcher


def _bootstrap() -> tuple[ConfigManager, FileManager]:
    config_path = ROOT / "config" / "settings.yaml"
    env_path    = ROOT / "config" / ".env"

    config = ConfigManager(config_path=config_path, env_path=env_path)
    fm = FileManager(studio_root=ROOT, config=config)
    setup_logger(log_dir=fm.logs_dir())

    return config, fm


def cmd_watch(args, config: ConfigManager, fm: FileManager) -> None:
    logger = get_logger("main")
    pipeline = Pipeline(config, fm)

    def on_video(path: Path) -> None:
        logger.info(f"[Watch] Triggered for: {path.name}")
        result = pipeline.run(
            path,
            num_shorts=args.shorts,
            duration=args.duration,
        )
        if result.report_path:
            logger.info(f"[Watch] Report: {result.report_path}")

    watcher = Watcher(input_dir=fm.input_dir(), on_video=on_video)
    print(f"\n  AI Content Studio is watching: {fm.input_dir()}")
    print(f"  Drop any video into that folder and processing starts automatically.")
    print(f"  Press Ctrl+C to stop.\n")
    watcher.start()


def cmd_process(args, config: ConfigManager, fm: FileManager) -> None:
    logger = get_logger("main")
    video_path = Path(args.video).resolve()

    if not video_path.exists():
        print(f"Error: file not found: {video_path}")
        sys.exit(1)

    pipeline = Pipeline(config, fm)
    result = pipeline.run(
        video_path,
        num_shorts=args.shorts,
        duration=args.duration,
    )

    if result.report_path:
        print(f"\n  PDF Report: {result.report_path}")

    sys.exit(0 if result.success else 1)


def cmd_status(args, config: ConfigManager, fm: FileManager) -> None:
    from rich.console import Console
    from rich.table import Table

    console = Console()
    table = Table(title="AI Content Studio — Output Status")
    table.add_column("Directory", style="cyan")
    table.add_column("Files", justify="right")
    table.add_column("Size", justify="right")

    dirs = {
        "input":      fm.input_dir(),
        "reports":    fm.reports_dir(),
        "audio":      fm.audio_dir(),
        "subtitles":  fm.subtitles_dir(),
        "thumbnails": fm.thumbnails_dir(),
        "metadata":   fm.metadata_dir(),
        "shorts/youtube":    fm.shorts_dir("youtube"),
        "shorts/instagram":  fm.shorts_dir("instagram"),
        "shorts/tiktok":     fm.shorts_dir("tiktok"),
    }
    for label, d in dirs.items():
        files = list(d.rglob("*")) if d.exists() else []
        files = [f for f in files if f.is_file()]
        size = sum(f.stat().st_size for f in files)
        size_str = f"{size / 1024 / 1024:.1f} MB" if size > 1024 * 1024 else f"{size / 1024:.0f} KB"
        table.add_row(label, str(len(files)), size_str)

    console.print(table)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="ai-content-studio",
        description="AI Content Studio — automated video production pipeline",
    )
    sub = parser.add_subparsers(dest="command")

    # watch
    watch_p = sub.add_parser("watch", help="Watch input/ folder and auto-process new videos")
    watch_p.add_argument("--shorts", type=int, default=5, choices=[5, 10, 20], help="Number of shorts to generate")
    watch_p.add_argument("--duration", type=int, default=30, choices=[15, 30, 45, 60], help="Short duration in seconds")

    # process
    proc_p = sub.add_parser("process", help="Process a single video file")
    proc_p.add_argument("video", help="Path to the input video file")
    proc_p.add_argument("--shorts", type=int, default=5, choices=[5, 10, 20])
    proc_p.add_argument("--duration", type=int, default=30, choices=[15, 30, 45, 60])

    # status
    sub.add_parser("status", help="Show output directory status")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(0)

    config, fm = _bootstrap()

    {
        "watch":   cmd_watch,
        "process": cmd_process,
        "status":  cmd_status,
    }[args.command](args, config, fm)


if __name__ == "__main__":
    main()
