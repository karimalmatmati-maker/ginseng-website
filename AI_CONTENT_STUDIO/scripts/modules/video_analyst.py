"""
Module 1 — Video Analyst
Analyses every uploaded video and generates a structured timeline report.
Detects: hooks, boring moments, emotional moments, visual highlights,
         speaking/silent sections, b-roll opportunities.
"""

import base64
import json
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from scripts.core.api_clients import OpenAIClient
from scripts.core.base_module import BaseModule, ModuleResult
from scripts.core.config_manager import ConfigManager


# ── Data models ───────────────────────────────────────────────

@dataclass
class VideoMeta:
    path: Path
    duration: float
    width: int
    height: int
    fps: float
    has_audio: bool
    file_size_mb: float
    aspect_ratio: str


@dataclass
class SceneInfo:
    start_time: float
    end_time: float
    duration: float
    motion_score: float = 0.0
    audio_energy: float = 0.0
    is_speaking: bool = False
    is_highlight: bool = False
    is_boring: bool = False
    is_b_roll: bool = False
    description: str = ""


@dataclass
class VideoAnalysisData:
    meta: VideoMeta
    scenes: List[SceneInfo] = field(default_factory=list)
    transcript: str = ""
    speaking_sections: List[Tuple[float, float]] = field(default_factory=list)
    silent_sections: List[Tuple[float, float]] = field(default_factory=list)
    highlights: List[Tuple[float, float, float]] = field(default_factory=list)  # (start, end, score)
    boring_sections: List[Tuple[float, float]] = field(default_factory=list)
    b_roll_opportunities: List[Tuple[float, float]] = field(default_factory=list)
    emotional_moments: List[Tuple[float, float, str]] = field(default_factory=list)
    ai_analysis: Dict = field(default_factory=dict)
    timeline_report: str = ""


# ── Module ────────────────────────────────────────────────────

class VideoAnalyst(BaseModule):
    MODULE_NAME = "video_analyst"

    def __init__(self, config: ConfigManager, openai: OpenAIClient) -> None:
        super().__init__(config)
        self.openai = openai

    def process(self, video_path: Path, context: dict, **kwargs) -> ModuleResult:
        meta = self._extract_meta(video_path)
        self.log.info(f"  {meta.duration:.1f}s | {meta.width}x{meta.height} @ {meta.fps:.1f}fps | {meta.file_size_mb:.1f}MB")

        frames = self._sample_frames(video_path, meta)
        motion_scores = self._compute_motion(frames)
        audio_energy = self._extract_audio_energy(video_path, meta)

        scenes = self._detect_scenes(motion_scores, audio_energy, meta)
        speaking, silent = self._classify_audio(audio_energy, meta)
        highlights, boring = self._score_scenes(scenes)
        b_roll = self._find_b_roll(scenes, speaking)

        key_frames = self._select_key_frames(frames, motion_scores)
        ai = self._ai_analyze(key_frames, meta) if self.openai.is_available() else {}

        emotional = self._map_emotional_moments(ai, meta)
        timeline = self._build_report(meta, scenes, speaking, silent, highlights, boring, b_roll, emotional, ai)

        data = VideoAnalysisData(
            meta=meta,
            scenes=scenes,
            transcript=ai.get("transcript", ""),
            speaking_sections=speaking,
            silent_sections=silent,
            highlights=highlights,
            boring_sections=boring,
            b_roll_opportunities=b_roll,
            emotional_moments=emotional,
            ai_analysis=ai,
            timeline_report=timeline,
        )
        return ModuleResult(success=True, module=self.MODULE_NAME, data=data)

    # ── Metadata ──────────────────────────────────────────────

    def _extract_meta(self, path: Path) -> VideoMeta:
        cap = cv2.VideoCapture(str(path))
        if not cap.isOpened():
            raise ValueError(f"Cannot open video: {path}")
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        n = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()
        dur = n / fps
        gcd = self._gcd(w, h)
        return VideoMeta(
            path=path, duration=dur, width=w, height=h, fps=fps,
            has_audio=True,
            file_size_mb=path.stat().st_size / 1_048_576,
            aspect_ratio=f"{w // gcd}:{h // gcd}",
        )

    @staticmethod
    def _gcd(a: int, b: int) -> int:
        while b:
            a, b = b, a % b
        return a

    # ── Frame sampling ────────────────────────────────────────

    def _sample_frames(self, path: Path, meta: VideoMeta) -> List[Tuple[float, np.ndarray]]:
        sample_rate = self.cfg("sample_rate", 1)
        cap = cv2.VideoCapture(str(path))
        interval = max(1, int(meta.fps / sample_rate))
        frames: List[Tuple[float, np.ndarray]] = []
        idx = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if idx % interval == 0:
                frames.append((idx / meta.fps, frame.copy()))
            idx += 1
        cap.release()
        self.log.debug(f"  Sampled {len(frames)} frames")
        return frames

    # ── Motion analysis ───────────────────────────────────────

    def _compute_motion(self, frames: List[Tuple[float, np.ndarray]]) -> List[float]:
        scores = [0.0]
        for i in range(1, len(frames)):
            prev = cv2.cvtColor(frames[i - 1][1], cv2.COLOR_BGR2GRAY)
            curr = cv2.cvtColor(frames[i][1], cv2.COLOR_BGR2GRAY)
            diff = cv2.absdiff(prev, curr)
            scores.append(float(np.mean(diff)) / 255.0)
        return scores

    # ── Audio energy ──────────────────────────────────────────

    def _extract_audio_energy(self, path: Path, meta: VideoMeta) -> List[float]:
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = Path(tmp.name)
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(path), "-vn",
                 "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
                 str(tmp_path), "-loglevel", "quiet"],
                check=True, capture_output=True, timeout=120,
            )
            try:
                import librosa
                y, sr = librosa.load(str(tmp_path), sr=None, mono=True)
                hop = sr
                rms = librosa.feature.rms(y=y, frame_length=sr, hop_length=hop)[0]
                energy = [float(v) for v in rms]
            except ImportError:
                energy = self._wave_energy(tmp_path)
            tmp_path.unlink(missing_ok=True)
            return energy
        except Exception as exc:
            self.log.warning(f"  Audio extraction failed: {exc} — using zeros")
            return [0.0] * max(1, int(meta.duration))

    @staticmethod
    def _wave_energy(wav: Path) -> List[float]:
        import struct, wave
        with wave.open(str(wav), "rb") as wf:
            sr = wf.getframerate()
            raw = wf.readframes(wf.getnframes())
            n = len(raw) // 2
            samples = struct.unpack(f"{n}h", raw[:n * 2])
        window = sr
        result = []
        for i in range(0, len(samples), window):
            chunk = samples[i: i + window]
            rms = (sum(s * s for s in chunk) / len(chunk)) ** 0.5 if chunk else 0.0
            result.append(rms / 32768.0)
        return result

    # ── Scene detection ───────────────────────────────────────

    def _detect_scenes(
        self,
        motion: List[float],
        audio: List[float],
        meta: VideoMeta,
    ) -> List[SceneInfo]:
        threshold = self.cfg("motion_threshold", 0.25)
        min_dur = self.cfg("min_scene_duration", 2.0)
        silence_db = self.cfg("silence_threshold_db", -40)
        silence_amp = 10 ** (silence_db / 20)

        starts = [0.0]
        for i in range(1, len(motion)):
            if motion[i] > threshold and float(i) - starts[-1] >= min_dur:
                starts.append(float(i))

        scenes = []
        for i, start in enumerate(starts):
            end = starts[i + 1] if i + 1 < len(starts) else meta.duration
            s, e = int(start), int(end)
            m_slice = motion[s:e] if s < len(motion) else [0.0]
            a_slice = audio[s:e] if s < len(audio) else [0.0]
            avg_m = float(np.mean(m_slice)) if m_slice else 0.0
            avg_a = float(np.mean(a_slice)) if a_slice else 0.0
            scenes.append(SceneInfo(
                start_time=start, end_time=end, duration=end - start,
                motion_score=avg_m, audio_energy=avg_a,
                is_speaking=avg_a > silence_amp,
            ))
        return scenes

    # ── Audio classification ──────────────────────────────────

    def _classify_audio(
        self, audio: List[float], meta: VideoMeta
    ) -> Tuple[List[Tuple[float, float]], List[Tuple[float, float]]]:
        silence_db = self.cfg("silence_threshold_db", -40)
        silence_amp = 10 ** (silence_db / 20)
        speaking, silent = [], []
        if not audio:
            return speaking, silent

        in_speech = audio[0] > silence_amp
        seg_start = 0.0
        for i, e in enumerate(audio):
            is_speech = e > silence_amp
            if is_speech != in_speech:
                target = speaking if in_speech else silent
                target.append((seg_start, float(i)))
                in_speech = is_speech
                seg_start = float(i)
        target = speaking if in_speech else silent
        target.append((seg_start, meta.duration))
        return speaking, silent

    # ── Scene scoring ─────────────────────────────────────────

    def _score_scenes(
        self, scenes: List[SceneInfo]
    ) -> Tuple[List[Tuple[float, float, float]], List[Tuple[float, float]]]:
        highlights, boring = [], []
        for sc in scenes:
            score = sc.motion_score * 0.4 + sc.audio_energy * 0.3 + (0.3 if sc.is_speaking else 0)
            if score > 0.45:
                highlights.append((sc.start_time, sc.end_time, round(score, 3)))
                sc.is_highlight = True
            elif score < 0.08 and sc.duration > 5:
                boring.append((sc.start_time, sc.end_time))
                sc.is_boring = True
        return highlights, boring

    def _find_b_roll(
        self, scenes: List[SceneInfo], speaking: List[Tuple[float, float]]
    ) -> List[Tuple[float, float]]:
        b_roll = []
        for sc in scenes:
            if not sc.is_speaking and sc.motion_score > 0.08 and sc.duration >= 2:
                sc.is_b_roll = True
                b_roll.append((sc.start_time, sc.end_time))
        return b_roll

    # ── Key-frame selection ───────────────────────────────────

    def _select_key_frames(
        self, frames: List[Tuple[float, np.ndarray]], motion: List[float]
    ) -> List[str]:
        if not frames:
            return []
        n = min(self.cfg("max_key_frames", 6), len(frames))
        step = max(1, len(frames) // n)
        selected = [frames[i] for i in range(0, len(frames), step)][:n]

        b64_list = []
        for _, frame in selected:
            h, w = frame.shape[:2]
            scale = min(640 / w, 640 / h)
            small = cv2.resize(frame, (int(w * scale), int(h * scale)))
            _, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 80])
            b64_list.append(base64.b64encode(buf.tobytes()).decode())
        return b64_list

    # ── AI analysis ───────────────────────────────────────────

    def _ai_analyze(self, images_b64: List[str], meta: VideoMeta) -> dict:
        prompt = f"""Analyse these {len(images_b64)} key frames from a {meta.duration:.0f}-second video.
Return ONLY a valid JSON object (no markdown) with:
{{
  "summary": "concise video description",
  "content_type": "interview|product|vlog|tutorial|b-roll|other",
  "visual_quality": <1-10>,
  "emotional_tone": "energetic|calm|dramatic|educational|funny|inspirational",
  "highlights": [{{"position": "early|mid|late", "reason": "string"}}],
  "boring_indicators": ["list"],
  "b_roll_opportunities": ["list"],
  "emotional_moments": [{{"position": "early|mid|late", "emotion": "string", "intensity": <1-10>}}],
  "content_tags": ["tag1","tag2"],
  "target_audience": "string"
}}"""
        raw = self.openai.vision(prompt, images_b64, response_format="json")
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"summary": raw}

    # ── Emotional moment mapping ──────────────────────────────

    def _map_emotional_moments(self, ai: dict, meta: VideoMeta) -> List[Tuple[float, float, str]]:
        result = []
        for em in ai.get("emotional_moments", []):
            pos = em.get("position", "mid")
            t = {"early": 0.15, "mid": 0.5, "late": 0.85}.get(pos, 0.5) * meta.duration
            result.append((max(0, t - 2), min(meta.duration, t + 2), em.get("emotion", "?")))
        return result

    # ── Timeline report ───────────────────────────────────────

    def _build_report(self, meta, scenes, speaking, silent, highlights, boring, b_roll, emotional, ai) -> str:
        ft = self.fmt_time
        lines = [
            "=" * 64,
            "  VIDEO ANALYSIS REPORT",
            "=" * 64,
            f"  File      : {meta.path.name}",
            f"  Duration  : {meta.duration:.1f}s",
            f"  Resolution: {meta.width}x{meta.height}  FPS: {meta.fps:.2f}  Aspect: {meta.aspect_ratio}",
            f"  Size      : {meta.file_size_mb:.1f} MB",
            "=" * 64,
            "",
            f"  SUMMARY       : {ai.get('summary', 'N/A')}",
            f"  Content Type  : {ai.get('content_type', 'N/A')}",
            f"  Visual Quality: {ai.get('visual_quality', 'N/A')}/10",
            f"  Emotional Tone: {ai.get('emotional_tone', 'N/A')}",
            f"  Target Audience: {ai.get('target_audience', 'N/A')}",
            f"  Tags          : {', '.join(ai.get('content_tags', []))}",
            "",
            f"  SCENES ({len(scenes)} detected)",
            "  " + "-" * 58,
        ]
        for sc in scenes[:30]:
            flags = [f for f, v in [("HIGHLIGHT", sc.is_highlight), ("BORING", sc.is_boring), ("B-ROLL", sc.is_b_roll), ("SPEECH", sc.is_speaking)] if v]
            flag_str = f"  [{' | '.join(flags)}]" if flags else ""
            lines.append(f"  [{ft(sc.start_time)} → {ft(sc.end_time)}] motion:{sc.motion_score:.2f} audio:{sc.audio_energy:.3f}{flag_str}")
        if len(scenes) > 30:
            lines.append(f"  … {len(scenes) - 30} more scenes")

        def section(title, items, fmt):
            lines.append(f"\n  {title} ({len(items)})")
            lines.append("  " + "-" * 40)
            for it in items[:15]:
                lines.append("  " + fmt(it))

        section("HIGHLIGHTS", highlights, lambda x: f"{ft(x[0])} → {ft(x[1])}  score:{x[2]:.3f}")
        section("BORING SECTIONS", boring, lambda x: f"{ft(x[0])} → {ft(x[1])}")
        section("B-ROLL OPPORTUNITIES", b_roll, lambda x: f"{ft(x[0])} → {ft(x[1])}")
        section("EMOTIONAL MOMENTS", emotional, lambda x: f"{ft(x[0])} → {ft(x[1])}  [{x[2]}]")
        section("SPEAKING SECTIONS", speaking, lambda x: f"{ft(x[0])} → {ft(x[1])}")

        lines += ["", "=" * 64]
        return "\n".join(lines)
