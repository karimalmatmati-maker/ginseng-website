"""
Pipeline Orchestrator
Runs all 10 modules in sequence, passes context between them,
and returns a complete PipelineResult.
"""

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.panel import Panel
from rich.text import Text

from scripts.core.api_clients import AdobePodcastClient, ElevenLabsClient, OpenAIClient
from scripts.core.base_module import ModuleResult
from scripts.core.config_manager import ConfigManager
from scripts.core.file_manager import FileManager
from scripts.core.logger import get_logger
from scripts.modules.auto_editor import AutoEditor
from scripts.modules.audio_engineer import AudioEngineer
from scripts.modules.color_analyzer import ColorAnalyzer
from scripts.modules.content_report import ContentReport
from scripts.modules.higgsfield_generator import HighgsfieldGenerator
from scripts.modules.hook_detector import HookDetector
from scripts.modules.seo_writer import SEOWriter
from scripts.modules.subtitle_generator import SubtitleGenerator
from scripts.modules.thumbnail_generator import ThumbnailGenerator
from scripts.modules.video_analyst import VideoAnalyst

logger = get_logger(__name__)
console = Console()


@dataclass
class PipelineResult:
    video_path: Path
    context: Dict[str, Any]
    results: Dict[str, ModuleResult] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    total_time: float = 0.0
    success: bool = False
    report_path: Optional[Path] = None


class Pipeline:
    """
    Orchestrates all modules for a single video.
    Context is a shared dict passed to every module so each module
    can read the outputs of earlier modules.
    """

    def __init__(self, config: ConfigManager, file_manager: FileManager) -> None:
        self.config = config
        self.fm = file_manager

        # Shared API clients
        self._openai     = OpenAIClient(config)
        self._elevenlabs = ElevenLabsClient(config)
        self._adobe      = AdobePodcastClient(config)

        # Module registry — order matters
        self._modules = {
            "video_analyst":      VideoAnalyst(config, self._openai),
            "hook_detector":      HookDetector(config, self._openai),
            "audio_engineer":     AudioEngineer(config, self._openai, self._adobe, self._elevenlabs),
            "color_analyzer":     ColorAnalyzer(config, self._openai),
            "subtitle_generator": SubtitleGenerator(config, self._openai),
            "auto_editor":        AutoEditor(config),
            "seo_writer":         SEOWriter(config, self._openai),
            "thumbnail_generator": ThumbnailGenerator(config, self._openai),
            "higgsfield_generator": HighgsfieldGenerator(config, self._openai),
            "content_report":     ContentReport(config),
        }

    # ── Public API ─────────────────────────────────────────────

    def run(
        self,
        video_path: Path,
        num_shorts: int = 5,
        duration: int = 30,
        **kwargs,
    ) -> PipelineResult:
        t0 = time.perf_counter()
        result = PipelineResult(video_path=video_path, context={})

        console.print(Panel(
            Text(f"Processing: {video_path.name}", style="bold cyan"),
            title="[bold]AI Content Studio[/bold]",
            border_style="cyan",
        ))

        enabled = self.config.get("pipeline.enabled_modules", list(self._modules.keys()))
        fail_fast = self.config.get("pipeline.fail_fast", False)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            for name, module in self._modules.items():
                if name not in enabled:
                    continue

                task = progress.add_task(f"[cyan]{name}[/cyan]", total=None)
                mod_result = module.run(
                    video_path,
                    context=result.context,
                    num_shorts=num_shorts,
                    duration=duration,
                    **kwargs,
                )
                progress.remove_task(task)

                result.results[name] = mod_result

                if mod_result.success and mod_result.data is not None:
                    result.context[name] = mod_result.data
                    console.print(f"  ✓ [green]{name}[/green]  ({mod_result.processing_time:.1f}s)")
                else:
                    err = mod_result.error or "unknown error"
                    result.errors.append(f"{name}: {err}")
                    console.print(f"  ✗ [red]{name}[/red]  {err}")
                    if fail_fast:
                        logger.error(f"Pipeline aborted (fail_fast=true) at module '{name}'")
                        break

        # Extract report path if content_report ran
        cr = result.results.get("content_report")
        if cr and cr.success and cr.data:
            result.report_path = cr.data.pdf_path

        result.total_time = time.perf_counter() - t0
        result.success = len(result.errors) == 0

        self._print_summary(result)
        self._save_manifest(result)

        return result

    # ── Internal ───────────────────────────────────────────────

    def _print_summary(self, result: PipelineResult) -> None:
        status = "[bold green]COMPLETE[/bold green]" if result.success else "[bold yellow]COMPLETE WITH ERRORS[/bold yellow]"
        console.print()
        console.print(Panel(
            f"{status}\n"
            f"Total time: {result.total_time:.1f}s\n"
            f"Modules run: {len(result.results)}\n"
            f"Errors: {len(result.errors)}\n"
            + (f"Report: {result.report_path}" if result.report_path else ""),
            title="Pipeline Summary",
            border_style="green" if result.success else "yellow",
        ))
        if result.errors:
            console.print("[yellow]Errors:[/yellow]")
            for e in result.errors:
                console.print(f"  • {e}", style="yellow")

    def _save_manifest(self, result: PipelineResult) -> None:
        """Save a JSON manifest next to the report for downstream tooling."""
        try:
            manifest = {
                "video": str(result.video_path),
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "total_time_s": round(result.total_time, 2),
                "success": result.success,
                "errors": result.errors,
                "modules_run": list(result.results.keys()),
                "report_pdf": str(result.report_path) if result.report_path else None,
            }

            # Add key outputs
            if "video_analyst" in result.context:
                a = result.context["video_analyst"]
                manifest["video_duration_s"] = a.meta.duration
                manifest["video_resolution"] = f"{a.meta.width}x{a.meta.height}"
                manifest["summary"] = a.ai_analysis.get("summary", "")

            if "seo_writer" in result.context:
                s = result.context["seo_writer"]
                manifest["seo"] = {
                    "youtube_title":    s.youtube.title if s.youtube else "",
                    "tiktok_caption":   (s.tiktok.caption or "")[:200] if s.tiktok else "",
                    "instagram_caption": (s.instagram.caption or "")[:200] if s.instagram else "",
                }

            if "auto_editor" in result.context:
                e = result.context["auto_editor"]
                manifest["shorts_generated"] = e.total_generated
                manifest["shorts"] = [
                    {"path": str(s.path), "platform": s.platform, "duration": s.duration}
                    for s in e.shorts
                ]

            out_dir = Path(self.config.get("paths.metadata", "output/metadata"))
            out_dir.mkdir(parents=True, exist_ok=True)
            ts = time.strftime("%Y%m%d_%H%M%S")
            manifest_path = out_dir / f"manifest_{result.video_path.stem}_{ts}.json"
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            logger.info(f"Manifest → {manifest_path.name}")

        except Exception as exc:
            logger.warning(f"Could not save manifest: {exc}")
