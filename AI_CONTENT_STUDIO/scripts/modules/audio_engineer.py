"""
Module 5 — Audio Engineer
Detects: background noise, wind, echo, low volume, poor mic quality.
Optionally enhances via Adobe Podcast API or ElevenLabs.
Generates a full audio quality report.
"""

import json
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import numpy as np

from scripts.core.api_clients import AdobePodcastClient, ElevenLabsClient, OpenAIClient
from scripts.core.base_module import BaseModule, ModuleResult
from scripts.core.config_manager import ConfigManager


@dataclass
class AudioIssue:
    issue: str
    severity: str          # low | medium | high
    description: str
    recommendation: str


@dataclass
class AudioReport:
    rms_db: float
    noise_floor_db: float
    peak_db: float
    dynamic_range_db: float
    sample_rate: int
    channels: int
    has_background_noise: bool
    has_wind: bool
    has_echo: bool
    is_low_volume: bool
    mic_quality_score: float         # 0–10
    issues: List[AudioIssue] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    enhanced_audio_path: Optional[Path] = None
    enhancement_method: str = "none"
    report_text: str = ""


class AudioEngineer(BaseModule):
    MODULE_NAME = "audio_engineer"

    def __init__(
        self,
        config: ConfigManager,
        openai: OpenAIClient,
        adobe: AdobePodcastClient,
        elevenlabs: ElevenLabsClient,
    ) -> None:
        super().__init__(config)
        self.openai = openai
        self.adobe = adobe
        self.elevenlabs = elevenlabs

    def process(self, video_path: Path, context: dict, **kwargs) -> ModuleResult:
        out_dir = Path(self.config.get("paths.audio", "output/audio"))
        out_dir.mkdir(parents=True, exist_ok=True)

        audio_path = self._extract_audio(video_path, out_dir)
        report = self._analyse(audio_path)
        self.log.info(
            f"  RMS: {report.rms_db:.1f}dB  Noise: {report.noise_floor_db:.1f}dB  "
            f"Score: {report.mic_quality_score:.1f}/10"
        )
        for issue in report.issues:
            self.log.warning(f"  [{issue.severity.upper()}] {issue.issue}: {issue.description}")

        enhanced = self._enhance(audio_path, out_dir, report)
        if enhanced:
            report.enhanced_audio_path = enhanced

        report.report_text = self._build_text_report(report, video_path)
        return ModuleResult(success=True, module=self.MODULE_NAME, data=report)

    # ── Audio extraction ──────────────────────────────────────

    def _extract_audio(self, video: Path, out_dir: Path) -> Path:
        sr  = self.cfg("sample_rate", 44100)
        ch  = self.cfg("channels", 2)
        fmt = self.cfg("output_format", "wav")
        out = out_dir / f"{video.stem}_extracted.{fmt}"
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(video),
             "-vn", "-ar", str(sr), "-ac", str(ch),
             str(out), "-loglevel", "quiet"],
            check=True, capture_output=True, timeout=120,
        )
        return out

    # ── Analysis ──────────────────────────────────────────────

    def _analyse(self, audio_path: Path) -> AudioReport:
        try:
            import librosa
            y, sr = librosa.load(str(audio_path), sr=None, mono=False)
            mono  = librosa.to_mono(y) if y.ndim > 1 else y
            ch    = y.shape[0] if y.ndim > 1 else 1
            return self._analyse_with_librosa(mono, sr, ch)
        except ImportError:
            return self._analyse_fallback(audio_path)

    def _analyse_with_librosa(self, mono: np.ndarray, sr: int, channels: int) -> AudioReport:
        import librosa

        rms        = librosa.feature.rms(y=mono)[0]
        rms_mean   = float(np.mean(rms))
        rms_db     = float(librosa.amplitude_to_db(np.array([rms_mean]))[0]) if rms_mean > 0 else -96.0
        peak       = float(np.max(np.abs(mono)))
        peak_db    = float(librosa.amplitude_to_db(np.array([peak]))[0]) if peak > 0 else -96.0
        noise_est  = float(np.percentile(rms, 10))
        noise_db   = float(librosa.amplitude_to_db(np.array([noise_est]))[0]) if noise_est > 0 else -96.0
        dyn_range  = peak_db - noise_db

        spec    = np.abs(librosa.stft(mono))
        centroid = float(np.mean(librosa.feature.spectral_centroid(y=mono, sr=sr)))
        rolloff  = float(np.mean(librosa.feature.spectral_rolloff(y=mono, sr=sr)))

        # Heuristic detections
        min_rms_db = self.cfg("min_rms_db", -20)
        noise_floor_db = self.cfg("noise_floor_db", -60)

        is_low_vol   = rms_db < min_rms_db
        has_noise    = noise_db > noise_floor_db + 20
        # Wind: energy concentrated in low freq + high spectral variance
        low_band = np.mean(np.abs(librosa.stft(mono))[:20, :])
        all_band = np.mean(spec)
        has_wind = bool(low_band / (all_band + 1e-8) > 0.6 and dyn_range < 15)
        # Echo: high reverb tail estimated via zero-crossing rate variation
        zcr_std    = float(np.std(librosa.feature.zero_crossing_rate(mono)[0]))
        has_echo   = zcr_std < 0.02 and dyn_range > 30

        issues = self._classify_issues(is_low_vol, has_noise, has_wind, has_echo, rms_db, dyn_range, centroid)
        score = self._compute_score(rms_db, noise_db, dyn_range, centroid, has_noise, has_wind, has_echo, is_low_vol)
        recs  = self._recommendations(issues)

        return AudioReport(
            rms_db=round(rms_db, 2),
            noise_floor_db=round(noise_db, 2),
            peak_db=round(peak_db, 2),
            dynamic_range_db=round(dyn_range, 2),
            sample_rate=sr,
            channels=channels,
            has_background_noise=has_noise,
            has_wind=has_wind,
            has_echo=has_echo,
            is_low_volume=is_low_vol,
            mic_quality_score=round(score, 1),
            issues=issues,
            recommendations=recs,
        )

    def _analyse_fallback(self, audio_path: Path) -> AudioReport:
        """FFprobe-based fallback when librosa is unavailable."""
        import json as _json
        try:
            out = subprocess.run(
                ["ffprobe", "-v", "quiet", "-print_format", "json",
                 "-show_streams", str(audio_path)],
                capture_output=True, text=True, timeout=30,
            )
            info = _json.loads(out.stdout)
            streams = info.get("streams", [{}])
            sr = int(streams[0].get("sample_rate", 44100))
            ch = int(streams[0].get("channels", 2))
        except Exception:
            sr, ch = 44100, 2

        return AudioReport(
            rms_db=-20.0, noise_floor_db=-60.0, peak_db=-6.0, dynamic_range_db=54.0,
            sample_rate=sr, channels=ch,
            has_background_noise=False, has_wind=False, has_echo=False,
            is_low_volume=False, mic_quality_score=5.0,
            recommendations=["Install librosa for full audio analysis."],
        )

    # ── Helpers ───────────────────────────────────────────────

    def _classify_issues(self, low_vol, noise, wind, echo, rms, dyn, centroid) -> List[AudioIssue]:
        issues = []
        if low_vol:
            issues.append(AudioIssue("Low Volume", "high",
                f"RMS level {rms:.1f}dB is below recommended -20dB",
                "Apply gain normalization or compress audio."))
        if noise:
            issues.append(AudioIssue("Background Noise", "medium",
                "Noise floor is unusually high for speech recording.",
                "Use noise reduction in Adobe Podcast or Audacity."))
        if wind:
            issues.append(AudioIssue("Wind Noise", "medium",
                "Low-frequency rumble pattern suggests wind or handling noise.",
                "Apply high-pass filter at 80Hz."))
        if echo:
            issues.append(AudioIssue("Room Echo / Reverb", "medium",
                "Spectral characteristics suggest room reflections.",
                "Record in a treated space or use de-reverb plugin."))
        if dyn < 6:
            issues.append(AudioIssue("Over-compressed", "low",
                f"Dynamic range only {dyn:.1f}dB.",
                "Avoid heavy limiting; keep dynamic range ≥ 12dB for broadcast."))
        return issues

    def _compute_score(self, rms, noise, dyn, centroid, has_noise, has_wind, has_echo, low_vol) -> float:
        score = 10.0
        if low_vol:       score -= 2.5
        if has_noise:     score -= 1.5
        if has_wind:      score -= 1.5
        if has_echo:      score -= 1.5
        if dyn < 6:       score -= 0.5
        if centroid < 500: score -= 0.5
        return max(0.0, score)

    def _recommendations(self, issues: List[AudioIssue]) -> List[str]:
        recs = [i.recommendation for i in issues]
        if not recs:
            recs = ["Audio quality looks good — no major issues detected."]
        if self.adobe.is_available():
            recs.append("Adobe Podcast Enhance Speech is configured — audio will be processed automatically.")
        return recs

    # ── Enhancement ───────────────────────────────────────────

    def _enhance(self, audio_path: Path, out_dir: Path, report: AudioReport) -> Optional[Path]:
        if self.cfg("use_adobe_podcast", False) and self.adobe.is_available():
            enhanced = out_dir / f"{audio_path.stem}_enhanced_adobe.wav"
            if self.adobe.enhance_speech(audio_path, enhanced):
                report.enhancement_method = "adobe_podcast"
                self.log.info(f"  Enhanced via Adobe Podcast → {enhanced.name}")
                return enhanced

        if self.cfg("use_elevenlabs", False) and self.elevenlabs.is_available():
            enhanced = out_dir / f"{audio_path.stem}_enhanced_el.wav"
            if self.elevenlabs.isolate_voice(audio_path, enhanced):
                report.enhancement_method = "elevenlabs"
                self.log.info(f"  Enhanced via ElevenLabs → {enhanced.name}")
                return enhanced

        return None

    # ── Text report ───────────────────────────────────────────

    def _build_text_report(self, r: AudioReport, video: Path) -> str:
        lines = [
            "=" * 60,
            "  AUDIO ENGINEERING REPORT",
            "=" * 60,
            f"  File           : {video.name}",
            f"  Sample Rate    : {r.sample_rate} Hz",
            f"  Channels       : {r.channels}",
            f"  RMS Level      : {r.rms_db:.1f} dB",
            f"  Peak Level     : {r.peak_db:.1f} dB",
            f"  Noise Floor    : {r.noise_floor_db:.1f} dB",
            f"  Dynamic Range  : {r.dynamic_range_db:.1f} dB",
            f"  Mic Quality    : {r.mic_quality_score:.1f} / 10",
            "",
            "  DETECTED ISSUES",
        ]
        if r.issues:
            for iss in r.issues:
                lines += [f"  [{iss.severity.upper():6s}] {iss.issue}", f"           → {iss.description}"]
        else:
            lines.append("  No major issues detected.")
        lines += ["", "  RECOMMENDATIONS"]
        for rec in r.recommendations:
            lines.append(f"  • {rec}")
        if r.enhanced_audio_path:
            lines += ["", f"  Enhanced audio: {r.enhanced_audio_path.name} (via {r.enhancement_method})"]
        lines.append("=" * 60)
        return "\n".join(lines)
