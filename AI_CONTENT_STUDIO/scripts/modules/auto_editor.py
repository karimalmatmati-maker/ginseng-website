"""
Module 3 — Auto Editor
Generates 5 / 10 / 20 Shorts at selectable durations (15/30/45/60 s).
Output: 9:16  1080×1920  H.264  high quality.
Uses MoviePy for composition and FFmpeg for final render.
"""

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from scripts.core.base_module import BaseModule, ModuleResult
from scripts.core.config_manager import ConfigManager
from scripts.modules.video_analyst import VideoAnalysisData


@dataclass
class ShortClip:
    path: Path
    platform: str
    duration: float
    start_time: float
    end_time: float
    quality_score: float
    title: str = ""


@dataclass
class AutoEditorData:
    shorts: List[ShortClip] = field(default_factory=list)
    total_generated: int = 0


class AutoEditor(BaseModule):
    MODULE_NAME = "auto_editor"

    TARGET_W = 1080
    TARGET_H = 1920
    PLATFORMS = ["youtube", "instagram", "tiktok"]

    def process(self, video_path: Path, context: dict, **kwargs) -> ModuleResult:
        analysis: Optional[VideoAnalysisData] = context.get("video_analyst")
        if analysis is None:
            return ModuleResult(success=False, module=self.MODULE_NAME,
                                error="video_analyst result missing")

        num_shorts = kwargs.get("num_shorts", self.cfg("default_num_shorts", 5))
        duration   = kwargs.get("duration",   self.cfg("default_duration",   30))

        if duration not in self.cfg("durations", [15, 30, 45, 60]):
            self.log.warning(f"  Duration {duration}s not in allowed list; using {duration}s anyway")

        segments = self._select_segments(analysis, num_shorts, duration)
        self.log.info(f"  Generating {len(segments)} shorts × {duration}s")

        output_root = Path(self.config.get("paths.output", "output"))
        shorts: List[ShortClip] = []
        for i, (start, end, score) in enumerate(segments):
            for platform in self.PLATFORMS:
                out_dir = output_root / "shorts" / platform
                out_dir.mkdir(parents=True, exist_ok=True)
                stem = f"{video_path.stem}_short{i+1:02d}_{int(duration)}s"
                out_path = out_dir / f"{stem}.mp4"
                ok = self._render_short(video_path, start, end, out_path)
                if ok:
                    shorts.append(ShortClip(
                        path=out_path, platform=platform,
                        duration=end - start,
                        start_time=start, end_time=end,
                        quality_score=score,
                        title=stem,
                    ))
                    self.log.info(f"    [{platform}] → {out_path.name}")
                else:
                    self.log.warning(f"    [{platform}] render failed for segment {i+1}")

        data = AutoEditorData(shorts=shorts, total_generated=len(shorts))
        return ModuleResult(success=True, module=self.MODULE_NAME, data=data)

    # ── Segment selection ─────────────────────────────────────

    def _select_segments(
        self,
        analysis: VideoAnalysisData,
        num_shorts: int,
        duration: float,
    ) -> List[Tuple[float, float, float]]:
        """Pick the best non-overlapping segments of exactly `duration` seconds."""
        highlights = sorted(analysis.highlights, key=lambda h: h[2], reverse=True)
        total_dur = analysis.meta.duration
        chosen: List[Tuple[float, float, float]] = []
        used_times: List[Tuple[float, float]] = []

        for hl_start, hl_end, score in highlights:
            if len(chosen) >= num_shorts:
                break
            # Centre the clip on the highlight
            mid = (hl_start + hl_end) / 2
            start = max(0, mid - duration / 2)
            end   = start + duration
            if end > total_dur:
                end = total_dur
                start = max(0, end - duration)

            # Avoid overlapping already-chosen segments
            overlap = any(s < end and e > start for s, e in used_times)
            if not overlap:
                chosen.append((start, end, score))
                used_times.append((start, end))

        # Pad with sequential segments if not enough highlights
        if len(chosen) < num_shorts and total_dur >= duration:
            t = 0.0
            while len(chosen) < num_shorts and t + duration <= total_dur:
                overlap = any(s < t + duration and e > t for s, e in used_times)
                if not overlap:
                    chosen.append((t, t + duration, 0.0))
                    used_times.append((t, t + duration))
                t += duration

        return chosen[:num_shorts]

    # ── FFmpeg render ─────────────────────────────────────────

    def _render_short(self, src: Path, start: float, end: float, out: Path) -> bool:
        """
        Crop to 9:16 via scale+crop filter, then encode H.264.
        Preserves audio. No Python video library dependency.
        """
        crf     = self.cfg("output_crf", 18)
        preset  = self.cfg("output_preset", "slow")
        a_codec = self.cfg("audio_codec", "aac")
        a_brate = self.cfg("audio_bitrate", "192k")
        fps     = self.cfg("output_fps", 30)
        w, h    = self.TARGET_W, self.TARGET_H

        duration = end - start
        vf = (
            f"scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h}"
        )
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(round(start, 3)),
            "-i", str(src),
            "-t", str(round(duration, 3)),
            "-vf", vf,
            "-r", str(fps),
            "-c:v", self.cfg("output_codec", "libx264"),
            "-preset", preset,
            "-crf", str(crf),
            "-c:a", a_codec,
            "-b:a", a_brate,
            "-movflags", "+faststart",
            str(out),
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if result.returncode != 0:
                self.log.error(f"    FFmpeg error:\n{result.stderr[-800:]}")
                return False
            return out.exists()
        except subprocess.TimeoutExpired:
            self.log.error("    FFmpeg timed out")
            return False
        except FileNotFoundError:
            self.log.error("    FFmpeg not found — install FFmpeg and add to PATH")
            return False
