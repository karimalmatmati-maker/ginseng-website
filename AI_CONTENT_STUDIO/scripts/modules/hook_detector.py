"""
Module 2 — Hook Detector
Scores every candidate hook in the first N seconds and returns
platform-specific hook recommendations (TikTok / Instagram / YouTube).
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import cv2
import numpy as np

from scripts.core.api_clients import OpenAIClient
from scripts.core.base_module import BaseModule, ModuleResult
from scripts.core.config_manager import ConfigManager
from scripts.modules.video_analyst import VideoAnalysisData


@dataclass
class HookCandidate:
    platform: str
    start_time: float
    end_time: float
    score: float
    motion_score: float
    audio_energy: float
    hook_text: str = ""
    reason: str = ""


@dataclass
class HookReport:
    all_candidates: List[HookCandidate] = field(default_factory=list)
    tiktok: Optional[HookCandidate] = None
    instagram: Optional[HookCandidate] = None
    youtube: Optional[HookCandidate] = None
    summary: str = ""


class HookDetector(BaseModule):
    MODULE_NAME = "hook_detector"

    def __init__(self, config: ConfigManager, openai: OpenAIClient) -> None:
        super().__init__(config)
        self.openai = openai

    def process(self, video_path: Path, context: dict, **kwargs) -> ModuleResult:
        analysis: Optional[VideoAnalysisData] = context.get("video_analyst")
        if analysis is None:
            return ModuleResult(success=False, module=self.MODULE_NAME,
                                error="video_analyst result missing from context")

        window = self.cfg("analysis_window", 60)
        hook_dur = self.cfg("hook_duration", 3)
        window = min(window, analysis.meta.duration)

        candidates = self._score_candidates(video_path, analysis, window, hook_dur)
        candidates.sort(key=lambda c: c.score, reverse=True)

        ai_hooks = self._ai_recommend(video_path, candidates[:5], analysis) if self.openai.is_available() else {}

        report = self._build_report(candidates, ai_hooks)
        self.log.info(f"  {len(candidates)} hook candidates | best score: {candidates[0].score:.3f}" if candidates else "  No candidates found")

        return ModuleResult(success=True, module=self.MODULE_NAME, data=report)

    # ── Scoring ───────────────────────────────────────────────

    def _score_candidates(
        self,
        video_path: Path,
        analysis: VideoAnalysisData,
        window: float,
        hook_dur: float,
    ) -> List[HookCandidate]:
        w_motion = self.cfg("scoring.motion_weight", 0.30)
        w_audio  = self.cfg("scoring.audio_energy_weight", 0.20)
        w_visual = self.cfg("scoring.visual_interest_weight", 0.30)
        w_ai     = self.cfg("scoring.ai_score_weight", 0.20)

        candidates = []
        step = 1.0
        t = 0.0
        while t + hook_dur <= window:
            motion = self._measure_motion(video_path, t, t + hook_dur, analysis.meta.fps)
            audio  = self._measure_audio(analysis, t, t + hook_dur)
            visual = self._measure_visual_interest(video_path, t, analysis.meta.fps)

            score = (
                motion * w_motion
                + audio * w_audio
                + visual * w_visual
            )
            # AI weight is applied after AI scoring; set to 0 now
            candidates.append(HookCandidate(
                platform="all",
                start_time=t,
                end_time=t + hook_dur,
                score=round(score, 4),
                motion_score=round(motion, 4),
                audio_energy=round(audio, 4),
            ))
            t += step

        return candidates

    def _measure_motion(self, path: Path, t_start: float, t_end: float, fps: float) -> float:
        cap = cv2.VideoCapture(str(path))
        cap.set(cv2.CAP_PROP_POS_MSEC, t_start * 1000)
        frames = []
        while cap.get(cv2.CAP_PROP_POS_MSEC) < t_end * 1000:
            ok, f = cap.read()
            if not ok:
                break
            frames.append(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY))
        cap.release()
        if len(frames) < 2:
            return 0.0
        diffs = [float(np.mean(cv2.absdiff(frames[i], frames[i + 1]))) for i in range(len(frames) - 1)]
        return min(1.0, float(np.mean(diffs)) / 255.0 * 4)

    def _measure_audio(self, analysis: VideoAnalysisData, t_start: float, t_end: float) -> float:
        """Average audio energy in the time window from pre-computed data."""
        energies = []
        for sc in analysis.scenes:
            if sc.start_time < t_end and sc.end_time > t_start:
                energies.append(sc.audio_energy)
        return float(np.mean(energies)) if energies else 0.0

    def _measure_visual_interest(self, path: Path, t: float, fps: float) -> float:
        cap = cv2.VideoCapture(str(path))
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = cap.read()
        cap.release()
        if not ok:
            return 0.0
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        # Laplacian variance = sharpness
        lap_var = cv2.Laplacian(gray, cv2.CV_64F).var()
        # Colour saturation
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        saturation = float(np.mean(hsv[:, :, 1])) / 255.0
        return min(1.0, (lap_var / 500.0) * 0.6 + saturation * 0.4)

    # ── AI recommendation ─────────────────────────────────────

    def _ai_recommend(
        self,
        video_path: Path,
        top_candidates: List[HookCandidate],
        analysis: VideoAnalysisData,
    ) -> dict:
        candidate_list = "\n".join(
            f"- t={c.start_time:.1f}s  score={c.score:.3f}  motion={c.motion_score:.3f}  audio={c.audio_energy:.3f}"
            for c in top_candidates
        )
        prompt = f"""You are a viral content strategist.

Video summary: {analysis.ai_analysis.get('summary', 'N/A')}
Duration: {analysis.meta.duration:.0f}s
Content type: {analysis.ai_analysis.get('content_type', 'N/A')}

Top hook candidates (timestamp, scores):
{candidate_list}

Return ONLY valid JSON:
{{
  "tiktok": {{
    "best_start_time": <float>,
    "hook_text": "compelling first-line text for TikTok (max 15 words)",
    "reason": "why this hook works on TikTok"
  }},
  "instagram": {{
    "best_start_time": <float>,
    "hook_text": "compelling first-line text for Instagram Reels (max 15 words)",
    "reason": "why this hook works on Instagram"
  }},
  "youtube": {{
    "best_start_time": <float>,
    "hook_text": "compelling first-line text for YouTube Shorts (max 15 words)",
    "reason": "why this hook works on YouTube"
  }},
  "overall_summary": "one paragraph on best hooks and strategy"
}}"""
        raw = self.openai.chat(
            [{"role": "user", "content": prompt}],
            response_format="json",
        )
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    # ── Report assembly ───────────────────────────────────────

    def _build_report(self, candidates: List[HookCandidate], ai: dict) -> HookReport:
        hook_dur = self.cfg("hook_duration", 3)

        def make_hook(platform: str, ai_data: dict) -> Optional[HookCandidate]:
            if not ai_data:
                return candidates[0] if candidates else None
            t = float(ai_data.get("best_start_time", 0.0))
            closest = min(candidates, key=lambda c: abs(c.start_time - t)) if candidates else None
            if closest is None:
                return None
            return HookCandidate(
                platform=platform,
                start_time=t,
                end_time=t + hook_dur,
                score=closest.score,
                motion_score=closest.motion_score,
                audio_energy=closest.audio_energy,
                hook_text=ai_data.get("hook_text", ""),
                reason=ai_data.get("reason", ""),
            )

        return HookReport(
            all_candidates=candidates,
            tiktok=make_hook("tiktok", ai.get("tiktok", {})),
            instagram=make_hook("instagram", ai.get("instagram", {})),
            youtube=make_hook("youtube", ai.get("youtube", {})),
            summary=ai.get("overall_summary", ""),
        )
