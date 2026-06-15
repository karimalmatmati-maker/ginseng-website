"""
Module 4 — Subtitle Generator
Transcribes with Whisper, outputs SRT / ASS / burned-in captions
with word-level highlighting and animated modern style.
"""

import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from scripts.core.api_clients import OpenAIClient
from scripts.core.base_module import BaseModule, ModuleResult
from scripts.core.config_manager import ConfigManager


@dataclass
class WordSegment:
    word: str
    start: float
    end: float
    probability: float = 1.0


@dataclass
class Segment:
    id: int
    start: float
    end: float
    text: str
    words: List[WordSegment] = field(default_factory=list)


@dataclass
class SubtitleData:
    segments: List[Segment]
    language: str
    word_count: int
    srt_path: Optional[Path] = None
    ass_path: Optional[Path] = None
    burned_path: Optional[Path] = None


class SubtitleGenerator(BaseModule):
    MODULE_NAME = "subtitle_generator"

    def __init__(self, config: ConfigManager, openai: OpenAIClient) -> None:
        super().__init__(config)
        self.openai = openai

    def process(self, video_path: Path, context: dict, **kwargs) -> ModuleResult:
        out_dir = Path(self.config.get("paths.subtitles", "output/subtitles"))
        out_dir.mkdir(parents=True, exist_ok=True)

        audio_path = self._extract_audio(video_path)
        segments, language = self._transcribe(audio_path, video_path)

        if not segments:
            return ModuleResult(success=False, module=self.MODULE_NAME, error="Transcription returned no segments")

        word_count = sum(len(s.text.split()) for s in segments)
        self.log.info(f"  {len(segments)} segments | {word_count} words | lang={language}")

        formats = self.cfg("formats", ["srt", "ass", "burned"])
        stem = video_path.stem
        data = SubtitleData(segments=segments, language=language, word_count=word_count)

        if "srt" in formats:
            data.srt_path = self._write_srt(segments, out_dir / f"{stem}.srt")

        if "ass" in formats:
            data.ass_path = self._write_ass(segments, out_dir / f"{stem}.ass")

        if "burned" in formats and data.ass_path:
            burned = out_dir / f"{stem}_subtitled.mp4"
            data.burned_path = self._burn_subtitles(video_path, data.ass_path, burned)

        if audio_path.exists():
            audio_path.unlink()

        return ModuleResult(success=True, module=self.MODULE_NAME, data=data)

    # ── Audio extraction ──────────────────────────────────────

    def _extract_audio(self, video_path: Path) -> Path:
        tmp = Path(tempfile.mktemp(suffix=".wav"))
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(video_path),
             "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
             str(tmp), "-loglevel", "quiet"],
            check=True, capture_output=True, timeout=120,
        )
        return tmp

    # ── Transcription ─────────────────────────────────────────

    def _transcribe(self, audio_path: Path, video_path: Path):
        model_name = self.cfg("whisper_model", "base")
        language   = self.cfg("language", None)
        if language == "auto":
            language = None

        # Try local Whisper first, fall back to API
        segments, lang = self._whisper_local(audio_path, model_name, language)
        if not segments and self.openai.is_available():
            self.log.info("  Falling back to Whisper API")
            segments, lang = self._whisper_api(audio_path)
        return segments, lang

    def _whisper_local(self, audio: Path, model_name: str, language):
        try:
            import whisper
            self.log.info(f"  Loading Whisper model '{model_name}'…")
            model = whisper.load_model(model_name)
            opts: Dict = {"word_timestamps": True, "verbose": False}
            if language:
                opts["language"] = language
            result = model.transcribe(str(audio), **opts)
            lang = result.get("language", "unknown")
            segments = self._parse_whisper_result(result)
            return segments, lang
        except ImportError:
            self.log.warning("  whisper not installed — trying stable-ts")
        try:
            import stable_whisper
            model = stable_whisper.load_model(model_name)
            result = model.transcribe(str(audio), word_timestamps=True)
            lang = getattr(result, "language", "unknown")
            segments = self._parse_stable_ts(result)
            return segments, lang
        except ImportError:
            self.log.warning("  stable-ts not installed either")
        return [], "unknown"

    def _parse_whisper_result(self, result: dict) -> List[Segment]:
        segs = []
        for i, s in enumerate(result.get("segments", [])):
            words = [
                WordSegment(w["word"].strip(), w["start"], w["end"], w.get("probability", 1.0))
                for w in s.get("words", [])
            ]
            segs.append(Segment(id=i, start=s["start"], end=s["end"], text=s["text"].strip(), words=words))
        return segs

    def _parse_stable_ts(self, result) -> List[Segment]:
        segs = []
        for i, s in enumerate(result.segments):
            words = [WordSegment(w.word.strip(), w.start, w.end) for w in (s.words or [])]
            segs.append(Segment(id=i, start=s.start, end=s.end, text=s.text.strip(), words=words))
        return segs

    def _whisper_api(self, audio: Path):
        data = self.openai.whisper_transcribe(audio)
        if not data:
            return [], "unknown"
        lang = data.get("language", "unknown")
        segs = []
        for i, s in enumerate(data.get("segments", [])):
            words = [WordSegment(w["word"].strip(), w["start"], w["end"]) for w in s.get("words", [])]
            segs.append(Segment(id=i, start=s["start"], end=s["end"], text=s["text"].strip(), words=words))
        return segs, lang

    # ── SRT output ────────────────────────────────────────────

    def _write_srt(self, segments: List[Segment], out: Path) -> Path:
        def ts(s: float) -> str:
            h = int(s // 3600); m = int((s % 3600) // 60); sec = int(s % 60); ms = int((s % 1) * 1000)
            return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"

        lines = []
        for seg in segments:
            lines += [str(seg.id + 1), f"{ts(seg.start)} --> {ts(seg.end)}", seg.text, ""]
        out.write_text("\n".join(lines), encoding="utf-8")
        self.log.info(f"  SRT → {out.name}")
        return out

    # ── ASS output ────────────────────────────────────────────

    def _write_ass(self, segments: List[Segment], out: Path) -> Path:
        font      = self.cfg("style.font", "Arial")
        font_size = self.cfg("style.font_size", 52)
        fc        = self.cfg("style.font_color", "&H00FFFFFF")
        oc        = self.cfg("style.outline_color", "&H00000000")
        ow        = self.cfg("style.outline_width", 2)
        hc        = self.cfg("style.highlight_color", "&H0000FFFF")
        shadow    = 1 if self.cfg("style.shadow", True) else 0
        position  = self.cfg("style.position", "bottom")
        alignment = 2 if position == "bottom" else (8 if position == "top" else 5)

        def ts(s: float) -> str:
            h = int(s // 3600); m = int((s % 3600) // 60); sec = s % 60
            return f"{h}:{m:02d}:{sec:05.2f}"

        header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font},{font_size},{fc},&H000000FF,{oc},&H80000000,-1,0,0,0,100,100,0,0,1,{ow},{shadow},{alignment},80,80,80,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"""

        events = []
        use_highlights = self.cfg("word_highlighting", True)
        for seg in segments:
            if use_highlights and seg.words and len(seg.words) > 1:
                # Word-by-word karaoke highlighting
                for wi, w in enumerate(seg.words):
                    highlighted_text = ""
                    for j, ww in enumerate(seg.words):
                        word = ww.word
                        if j == wi:
                            highlighted_text += f"{{\\c{hc}}}{word}{{\\c{fc}}} "
                        else:
                            highlighted_text += word + " "
                    events.append(
                        f"Dialogue: 0,{ts(w.start)},{ts(w.end)},Default,,0,0,0,,{highlighted_text.strip()}"
                    )
            else:
                events.append(
                    f"Dialogue: 0,{ts(seg.start)},{ts(seg.end)},Default,,0,0,0,,{seg.text}"
                )

        out.write_text(header + "\n" + "\n".join(events), encoding="utf-8")
        self.log.info(f"  ASS → {out.name}")
        return out

    # ── Burn into video ───────────────────────────────────────

    def _burn_subtitles(self, video: Path, ass: Path, out: Path) -> Optional[Path]:
        cmd = [
            "ffmpeg", "-y", "-i", str(video),
            "-vf", f"ass={ass}",
            "-c:v", "libx264", "-crf", "18", "-preset", "slow",
            "-c:a", "copy",
            str(out), "-loglevel", "quiet",
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=600)
            self.log.info(f"  Burned → {out.name}")
            return out
        except Exception as exc:
            self.log.error(f"  Burn failed: {exc}")
            return None
