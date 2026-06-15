"""
Module 6 — Color Analyzer
Analyses brightness, contrast, white balance, skin tones, exposure.
Suggests professional colour-grading settings.
NEVER modifies the original file automatically.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from scripts.core.api_clients import OpenAIClient
from scripts.core.base_module import BaseModule, ModuleResult
from scripts.core.config_manager import ConfigManager


@dataclass
class FrameColorInfo:
    timestamp: float
    brightness: float       # 0–255
    contrast: float         # std-dev of luminance
    saturation: float       # 0–255
    temperature_k: float    # estimated colour temperature
    highlights_clipped: bool
    shadows_clipped: bool


@dataclass
class ColorReport:
    avg_brightness: float
    avg_contrast: float
    avg_saturation: float
    estimated_white_balance: str
    exposure_assessment: str
    skin_tone_found: bool
    histogram_data: Dict = field(default_factory=dict)
    grading_suggestions: List[str] = field(default_factory=list)
    lut_hint: str = ""
    frame_samples: List[FrameColorInfo] = field(default_factory=list)
    report_text: str = ""


class ColorAnalyzer(BaseModule):
    MODULE_NAME = "color_analyzer"

    def __init__(self, config: ConfigManager, openai: OpenAIClient) -> None:
        super().__init__(config)
        self.openai = openai

    def process(self, video_path: Path, context: dict, **kwargs) -> ModuleResult:
        n_frames = self.cfg("sample_frames", 12)
        frames = self._sample_frames(video_path, n_frames)

        if not frames:
            return ModuleResult(success=False, module=self.MODULE_NAME, error="No frames extracted")

        self.log.info(f"  Analysing {len(frames)} frames for colour…")
        samples = [self._analyse_frame(t, f) for t, f in frames]

        report = self._compile_report(samples, frames)
        ai_suggestions = self._ai_grade(report) if self.openai.is_available() else []
        report.grading_suggestions += ai_suggestions

        report.report_text = self._build_text(report, video_path)
        self.log.info(f"  Brightness:{report.avg_brightness:.0f}  Contrast:{report.avg_contrast:.0f}  Sat:{report.avg_saturation:.0f}")

        return ModuleResult(success=True, module=self.MODULE_NAME, data=report)

    # ── Frame sampling ────────────────────────────────────────

    def _sample_frames(self, path: Path, n: int) -> List[Tuple[float, np.ndarray]]:
        cap = cv2.VideoCapture(str(path))
        total = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        fps   = cap.get(cv2.CAP_PROP_FPS) or 30.0
        duration = total / fps
        frames = []
        for i in range(n):
            t = (i + 0.5) / n * duration
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
            ok, frame = cap.read()
            if ok:
                frames.append((t, frame))
        cap.release()
        return frames

    # ── Per-frame analysis ────────────────────────────────────

    def _analyse_frame(self, t: float, frame: np.ndarray) -> FrameColorInfo:
        lab  = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
        hsv  = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        l_ch = lab[:, :, 0].astype(float)
        brightness = float(np.mean(l_ch))
        contrast   = float(np.std(l_ch))
        saturation = float(np.mean(hsv[:, :, 1]))

        b_mean = float(np.mean(frame[:, :, 0]))
        r_mean = float(np.mean(frame[:, :, 2]))
        temp_k = self._estimate_temperature(r_mean, b_mean)

        highlights_clipped = float(np.mean(gray > 250)) > 0.02
        shadows_clipped    = float(np.mean(gray < 5)) > 0.02

        return FrameColorInfo(
            timestamp=t, brightness=brightness, contrast=contrast,
            saturation=saturation, temperature_k=temp_k,
            highlights_clipped=highlights_clipped, shadows_clipped=shadows_clipped,
        )

    @staticmethod
    def _estimate_temperature(r: float, b: float) -> float:
        ratio = r / (b + 1e-8)
        # Rough mapping: ratio > 1 → warm, < 1 → cool
        if ratio > 1.3:   return 3200.0
        if ratio > 1.1:   return 4500.0
        if ratio > 0.9:   return 6500.0
        return 8000.0

    # ── Report compilation ────────────────────────────────────

    def _compile_report(
        self, samples: List[FrameColorInfo], frames: List[Tuple[float, np.ndarray]]
    ) -> ColorReport:
        avg_bright = float(np.mean([s.brightness for s in samples]))
        avg_cont   = float(np.mean([s.contrast for s in samples]))
        avg_sat    = float(np.mean([s.saturation for s in samples]))
        avg_temp   = float(np.mean([s.temperature_k for s in samples]))

        wb = self._classify_wb(avg_temp)
        exposure = self._classify_exposure(avg_bright, any(s.highlights_clipped for s in samples), any(s.shadows_clipped for s in samples))
        skin_found = self._detect_skin_tones(frames)

        suggestions = self._rule_based_suggestions(avg_bright, avg_cont, avg_sat, avg_temp, samples)

        # Build histogram from first frame
        hist_data: Dict = {}
        if frames:
            for i, ch in enumerate(["blue", "green", "red"]):
                h = cv2.calcHist([frames[0][1]], [i], None, [256], [0, 256])
                hist_data[ch] = h.flatten().tolist()

        return ColorReport(
            avg_brightness=round(avg_bright, 1),
            avg_contrast=round(avg_cont, 1),
            avg_saturation=round(avg_sat, 1),
            estimated_white_balance=wb,
            exposure_assessment=exposure,
            skin_tone_found=skin_found,
            histogram_data=hist_data,
            grading_suggestions=suggestions,
            frame_samples=samples,
        )

    @staticmethod
    def _classify_wb(temp: float) -> str:
        if temp < 3500:    return "Very Warm (tungsten/candlelight)"
        if temp < 4500:    return "Warm (golden hour)"
        if temp < 5500:    return "Neutral-Warm (cloudy)"
        if temp < 7000:    return "Neutral (daylight)"
        return "Cool (overcast/shade)"

    @staticmethod
    def _classify_exposure(brightness: float, hi_clip: bool, sh_clip: bool) -> str:
        if hi_clip and sh_clip: return "High contrast — highlights and shadows both clipping"
        if hi_clip:             return "Slightly overexposed — highlights clipping"
        if sh_clip:             return "Slightly underexposed — shadows clipping"
        if brightness > 180:    return "Bright — may appear washed out"
        if brightness < 60:     return "Dark — needs exposure lift"
        if brightness < 100:    return "Slightly underexposed — +0.5 EV recommended"
        return "Well exposed"

    @staticmethod
    def _detect_skin_tones(frames: List[Tuple[float, np.ndarray]]) -> bool:
        for _, frame in frames:
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            mask = cv2.inRange(hsv, np.array([0, 40, 60]), np.array([25, 170, 255]))
            if float(np.mean(mask > 0)) > 0.03:
                return True
        return False

    def _rule_based_suggestions(self, brightness, contrast, saturation, temp, samples) -> List[str]:
        sug = []
        t_bright = self.cfg("analysis.brightness_target", 128)
        t_cont   = self.cfg("analysis.contrast_target", 60)
        t_sat    = self.cfg("analysis.saturation_target", 100)

        if brightness < t_bright - 20:
            delta = round((t_bright - brightness) / 255 * 100, 0)
            sug.append(f"Lift exposure by ~{delta:.0f}% (Brightness {brightness:.0f} → target {t_bright})")
        elif brightness > t_bright + 30:
            sug.append(f"Reduce highlights — brightness {brightness:.0f} is above target {t_bright}")

        if contrast < t_cont:
            sug.append(f"Add contrast — current std-dev {contrast:.0f} is low (S-curve or Contrast slider +{int(t_cont - contrast)})")
        if saturation < t_sat - 20:
            sug.append(f"Boost saturation — current {saturation:.0f} vs target {t_sat}")
        if saturation > t_sat + 40:
            sug.append(f"Reduce saturation — {saturation:.0f} is oversaturated; pull back to ~{t_sat}")

        if temp < 4000:
            sug.append("White balance correction: add -500K or shift blue channel up for neutral whites")
        elif temp > 7500:
            sug.append("White balance correction: add +500K or reduce blue channel for warmer look")

        if any(s.highlights_clipped for s in samples):
            sug.append("Recover highlights — pull Highlights slider to -30 to -50")
        if any(s.shadows_clipped for s in samples):
            sug.append("Lift shadows — push Shadows slider +20 to +40")

        if not sug:
            sug.append("Colour grading looks balanced — minor tweaks only if desired.")
        return sug

    # ── AI grading suggestions ────────────────────────────────

    def _ai_grade(self, report: ColorReport) -> List[str]:
        prompt = f"""You are a professional colorist.

Video colour metrics:
- Average Brightness: {report.avg_brightness:.1f}/255
- Average Contrast: {report.avg_contrast:.1f}
- Average Saturation: {report.avg_saturation:.1f}/255
- White Balance: {report.estimated_white_balance}
- Exposure: {report.exposure_assessment}
- Skin tones present: {report.skin_tone_found}

Current suggestions: {report.grading_suggestions}

Provide 3–5 additional professional colour grading suggestions as a JSON array of strings.
Focus on: LUT recommendations, specific DaVinci Resolve or Premiere settings, cinematic style enhancements.
Return ONLY valid JSON array, no markdown."""

        raw = self.openai.chat([{"role": "user", "content": prompt}], response_format="json")
        if not raw:
            return []
        try:
            result = json.loads(raw)
            if isinstance(result, list):
                return result
            if isinstance(result, dict):
                for v in result.values():
                    if isinstance(v, list):
                        return v
        except Exception:
            pass
        return []

    # ── Text report ───────────────────────────────────────────

    def _build_text(self, r: ColorReport, video: Path) -> str:
        lines = [
            "=" * 60,
            "  COLOUR ANALYSIS REPORT",
            "=" * 60,
            f"  File             : {video.name}",
            f"  Avg Brightness   : {r.avg_brightness:.1f} / 255",
            f"  Avg Contrast     : {r.avg_contrast:.1f}",
            f"  Avg Saturation   : {r.avg_saturation:.1f} / 255",
            f"  White Balance    : {r.estimated_white_balance}",
            f"  Exposure         : {r.exposure_assessment}",
            f"  Skin Tones Found : {'Yes' if r.skin_tone_found else 'No'}",
            "",
            "  GRADING SUGGESTIONS",
        ]
        for s in r.grading_suggestions:
            lines.append(f"  • {s}")
        if r.lut_hint:
            lines.append(f"\n  LUT Hint: {r.lut_hint}")
        lines += [
            "",
            "  ⚠️  Original file NOT modified. Apply changes in your NLE.",
            "=" * 60,
        ]
        return "\n".join(lines)
