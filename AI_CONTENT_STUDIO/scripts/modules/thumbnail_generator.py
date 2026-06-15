"""
Module 8 — Thumbnail Generator
Scores frames by sharpness, face presence, composition and emotion.
Extracts the best N candidates as JPEG thumbnails.
"""

import base64
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np

from scripts.core.api_clients import OpenAIClient
from scripts.core.base_module import BaseModule, ModuleResult
from scripts.core.config_manager import ConfigManager
from scripts.modules.video_analyst import VideoAnalysisData


@dataclass
class ThumbnailCandidate:
    path: Path
    timestamp: float
    sharpness_score: float
    face_count: int
    composition_score: float
    ai_score: float
    total_score: float
    ai_description: str = ""


@dataclass
class ThumbnailData:
    candidates: List[ThumbnailCandidate] = field(default_factory=list)
    best: Optional[ThumbnailCandidate] = None


class ThumbnailGenerator(BaseModule):
    MODULE_NAME = "thumbnail_generator"

    OUT_W, OUT_H = 1280, 720

    def __init__(self, config: ConfigManager, openai: OpenAIClient) -> None:
        super().__init__(config)
        self.openai = openai
        self._face_cascade = self._load_face_cascade()

    def process(self, video_path: Path, context: dict, **kwargs) -> ModuleResult:
        out_dir = Path(self.config.get("paths.thumbnails", "output/thumbnails")) / video_path.stem
        out_dir.mkdir(parents=True, exist_ok=True)

        analysis: Optional[VideoAnalysisData] = context.get("video_analyst")
        n = self.cfg("num_candidates", 6)

        frames = self._extract_candidate_frames(video_path, analysis, n * 3)
        self.log.info(f"  Scoring {len(frames)} frames for {n} thumbnail candidates…")

        scored = [self._score_frame(t, f) for t, f in frames]
        scored.sort(key=lambda x: x[2], reverse=True)

        candidates: List[ThumbnailCandidate] = []
        for i, (t, frame, score, face_ct, comp) in enumerate(scored[:n]):
            out_path = out_dir / f"thumbnail_{i+1:02d}_{int(t)}s.jpg"
            resized = cv2.resize(frame, (self.OUT_W, self.OUT_H))
            cv2.imwrite(str(out_path), resized, [cv2.IMWRITE_JPEG_QUALITY, 95])
            sharp = self._sharpness(frame)
            candidates.append(ThumbnailCandidate(
                path=out_path, timestamp=t,
                sharpness_score=sharp, face_count=face_ct,
                composition_score=comp, ai_score=0.0,
                total_score=score,
            ))

        if self.openai.is_available() and candidates:
            self._ai_score(candidates)

        candidates.sort(key=lambda c: c.total_score, reverse=True)
        best = candidates[0] if candidates else None
        if best:
            self.log.info(f"  Best thumbnail: {best.path.name} (t={best.timestamp:.1f}s score={best.total_score:.3f})")

        return ModuleResult(success=True, module=self.MODULE_NAME,
                            data=ThumbnailData(candidates=candidates, best=best))

    # ── Frame extraction ──────────────────────────────────────

    def _extract_candidate_frames(
        self,
        path: Path,
        analysis: Optional[VideoAnalysisData],
        n: int,
    ) -> List[Tuple[float, np.ndarray]]:
        cap = cv2.VideoCapture(str(path))
        total = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        fps   = cap.get(cv2.CAP_PROP_FPS) or 30.0
        duration = total / fps

        # Prefer highlight timestamps
        timestamps = []
        if analysis and analysis.highlights:
            for start, end, _ in analysis.highlights:
                mid = (start + end) / 2
                timestamps.append(mid)

        # Fill with evenly-spaced
        while len(timestamps) < n:
            t = (len(timestamps) + 0.5) / n * duration
            timestamps.append(t)

        frames = []
        for t in timestamps[:n]:
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
            ok, f = cap.read()
            if ok:
                frames.append((t, f))
        cap.release()
        return frames

    # ── Scoring ───────────────────────────────────────────────

    def _score_frame(
        self, t: float, frame: np.ndarray
    ) -> Tuple[float, np.ndarray, float, int, float]:
        min_q = self.cfg("min_frame_quality", 50)
        sharp = self._sharpness(frame)
        if sharp < min_q:
            return t, frame, 0.0, 0, 0.0

        face_ct = self._count_faces(frame)
        comp    = self._composition_score(frame)
        score   = (
            (min(sharp / 500, 1.0)) * 0.35
            + (min(face_ct, 2) / 2)  * 0.40
            + comp                   * 0.25
        )
        return t, frame, score, face_ct, comp

    @staticmethod
    def _sharpness(frame: np.ndarray) -> float:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        return float(cv2.Laplacian(gray, cv2.CV_64F).var())

    def _count_faces(self, frame: np.ndarray) -> int:
        if self._face_cascade is None or not self.cfg("face_detection", True):
            return 0
        gray  = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = self._face_cascade.detectMultiScale(gray, 1.1, 4, minSize=(60, 60))
        return len(faces)

    @staticmethod
    def _composition_score(frame: np.ndarray) -> float:
        h, w = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        # Rule of thirds: high-contrast at third lines gets bonus
        thirds_v = [w // 3, 2 * w // 3]
        thirds_h = [h // 3, 2 * h // 3]
        band = 30
        edge = cv2.Canny(gray, 50, 150)
        score = 0.0
        for x in thirds_v:
            score += float(np.mean(edge[:, max(0, x - band):min(w, x + band)])) / 255
        for y in thirds_h:
            score += float(np.mean(edge[max(0, y - band):min(h, y + band), :])) / 255
        return min(1.0, score / 4)

    @staticmethod
    def _load_face_cascade() -> Optional[cv2.CascadeClassifier]:
        try:
            cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
            return cascade if not cascade.empty() else None
        except Exception:
            return None

    # ── AI scoring ────────────────────────────────────────────

    def _ai_score(self, candidates: List[ThumbnailCandidate]) -> None:
        b64_list = []
        for c in candidates:
            img = cv2.imread(str(c.path))
            if img is None:
                b64_list.append("")
                continue
            _, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 70])
            b64_list.append(base64.b64encode(buf.tobytes()).decode())

        prompt = f"""You are a YouTube thumbnail expert.
Rate each of these {len(candidates)} thumbnail candidates on:
- Emotional impact (1-10)
- Click-through-rate potential (1-10)
- Visual clarity (1-10)
- Professional quality (1-10)

Return ONLY valid JSON array with one object per image:
[{{"rank": 1, "score": <0-10>, "description": "short reason", "strengths": ["s1"], "weaknesses": ["w1"]}}]"""

        raw = self.openai.vision(prompt, [b for b in b64_list if b], response_format="json")
        if not raw:
            return
        try:
            results = json.loads(raw)
            if isinstance(results, list):
                for i, r in enumerate(results[:len(candidates)]):
                    candidates[i].ai_score = float(r.get("score", 0.0)) / 10.0
                    candidates[i].ai_description = r.get("description", "")
                    candidates[i].total_score += candidates[i].ai_score * 0.3
        except Exception as exc:
            self.log.warning(f"  AI thumbnail scoring parse error: {exc}")
