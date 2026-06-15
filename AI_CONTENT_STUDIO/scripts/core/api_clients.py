"""
API client wrappers for OpenAI, ElevenLabs, Adobe Podcast.
Each client is independently replaceable.
"""

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config_manager import ConfigManager
from .logger import get_logger

logger = get_logger(__name__)


# ── OpenAI ────────────────────────────────────────────────────

class OpenAIClient:
    """Thin wrapper around the OpenAI Python SDK."""

    def __init__(self, config: ConfigManager) -> None:
        self._config = config
        self._client = None
        self._model = config.get("api.openai.model", "gpt-4o")
        self._vision_model = config.get("api.openai.vision_model", "gpt-4o")
        self._max_tokens = config.get("api.openai.max_tokens", 4096)
        self._temperature = config.get("api.openai.temperature", 0.7)
        self._init_client()

    def _init_client(self) -> None:
        api_key = self._config.get_api_key("openai")
        if not api_key:
            logger.warning("OPENAI_API_KEY not set — AI features disabled")
            return
        try:
            import openai
            self._client = openai.OpenAI(api_key=api_key)
            logger.info(f"OpenAI client ready (model={self._model})")
        except ImportError:
            logger.error("openai package not installed: pip install openai")

    def is_available(self) -> bool:
        return self._client is not None

    def chat(
        self,
        messages: List[Dict],
        response_format: str = "text",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> Optional[str]:
        if not self.is_available():
            return None
        try:
            kwargs: Dict[str, Any] = {
                "model": self._model,
                "messages": messages,
                "max_tokens": max_tokens or self._max_tokens,
                "temperature": temperature if temperature is not None else self._temperature,
            }
            if response_format == "json":
                kwargs["response_format"] = {"type": "json_object"}

            resp = self._client.chat.completions.create(**kwargs)
            return resp.choices[0].message.content
        except Exception as exc:
            logger.error(f"OpenAI chat error: {exc}")
            return None

    def vision(
        self,
        prompt: str,
        images_b64: List[str],
        response_format: str = "text",
    ) -> Optional[str]:
        """Send text + base64 images to GPT-4 Vision."""
        if not self.is_available():
            return None

        content: List[Dict] = [{"type": "text", "text": prompt}]
        for b64 in images_b64:
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{b64}",
                    "detail": "low",
                },
            })

        messages = [
            {
                "role": "system",
                "content": "You are a professional video editor and content strategist.",
            },
            {"role": "user", "content": content},
        ]
        try:
            kwargs: Dict[str, Any] = {
                "model": self._vision_model,
                "messages": messages,
                "max_tokens": self._max_tokens,
            }
            if response_format == "json":
                kwargs["response_format"] = {"type": "json_object"}
            resp = self._client.chat.completions.create(**kwargs)
            return resp.choices[0].message.content
        except Exception as exc:
            logger.error(f"OpenAI vision error: {exc}")
            return None

    def whisper_transcribe(self, audio_path: Path) -> Optional[Dict]:
        """Transcribe audio with Whisper API (word-level timestamps)."""
        if not self.is_available():
            return None
        try:
            with open(audio_path, "rb") as fh:
                resp = self._client.audio.transcriptions.create(
                    model="whisper-1",
                    file=fh,
                    response_format="verbose_json",
                    timestamp_granularities=["word", "segment"],
                )
            return resp.model_dump() if hasattr(resp, "model_dump") else dict(resp)
        except Exception as exc:
            logger.error(f"Whisper API error: {exc}")
            return None


# ── ElevenLabs ────────────────────────────────────────────────

class ElevenLabsClient:
    """ElevenLabs voice enhancement client."""

    def __init__(self, config: ConfigManager) -> None:
        self._api_key = config.get_api_key("elevenlabs")
        self._voice_id = config.get("api.elevenlabs.voice_id", "21m00Tcm4TlvDq8ikWAM")
        if self._api_key:
            logger.info("ElevenLabs client ready")
        else:
            logger.info("ELEVENLABS_API_KEY not set — ElevenLabs disabled")

    def is_available(self) -> bool:
        return bool(self._api_key)

    def isolate_voice(self, audio_path: Path, output_path: Path) -> bool:
        """Use ElevenLabs Audio Isolation API (if available)."""
        if not self.is_available():
            return False
        try:
            import requests
            with open(audio_path, "rb") as fh:
                resp = requests.post(
                    "https://api.elevenlabs.io/v1/audio-isolation",
                    headers={"xi-api-key": self._api_key},
                    files={"audio": fh},
                    timeout=120,
                )
            if resp.status_code == 200:
                output_path.write_bytes(resp.content)
                logger.info(f"ElevenLabs voice isolation → {output_path.name}")
                return True
            logger.warning(f"ElevenLabs isolation failed: {resp.status_code} {resp.text[:200]}")
            return False
        except Exception as exc:
            logger.error(f"ElevenLabs error: {exc}")
            return False


# ── Adobe Podcast ─────────────────────────────────────────────

class AdobePodcastClient:
    """Adobe Podcast Enhance Speech client."""

    _POLL_INTERVAL = 5   # seconds
    _POLL_TIMEOUT  = 300 # seconds

    def __init__(self, config: ConfigManager) -> None:
        self._api_key = config.get_api_key("adobe_podcast")
        self._base_url = config.get("api.adobe_podcast.base_url", "https://podcast.adobe.com/api/v1")
        self._enabled  = config.get("api.adobe_podcast.enabled", False)

        if self._api_key and self._enabled:
            logger.info("Adobe Podcast client ready")
        else:
            logger.info("Adobe Podcast disabled (set ADOBE_PODCAST_API_KEY + enabled: true)")

    def is_available(self) -> bool:
        return bool(self._api_key) and self._enabled

    def enhance_speech(self, audio_path: Path, output_path: Path) -> bool:
        """Upload audio, poll for completion, download result."""
        if not self.is_available():
            return False
        try:
            import requests

            with open(audio_path, "rb") as fh:
                upload = requests.post(
                    f"{self._base_url}/enhance",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    files={"file": fh},
                    timeout=60,
                )
            if upload.status_code not in (200, 201, 202):
                logger.error(f"Adobe Podcast upload failed: {upload.status_code}")
                return False

            job_id = upload.json().get("jobId") or upload.json().get("id")
            if not job_id:
                logger.error("Adobe Podcast: no jobId returned")
                return False

            deadline = time.time() + self._POLL_TIMEOUT
            while time.time() < deadline:
                time.sleep(self._POLL_INTERVAL)
                poll = requests.get(
                    f"{self._base_url}/enhance/{job_id}",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    timeout=30,
                )
                status = poll.json().get("status", "")
                if status == "done":
                    url = poll.json().get("url") or poll.json().get("downloadUrl")
                    audio_bytes = requests.get(url, timeout=120).content
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    output_path.write_bytes(audio_bytes)
                    logger.info(f"Adobe Podcast enhanced audio → {output_path.name}")
                    return True
                if status == "error":
                    logger.error("Adobe Podcast processing error")
                    return False

            logger.error("Adobe Podcast: timed out waiting for job")
            return False

        except Exception as exc:
            logger.error(f"Adobe Podcast client error: {exc}")
            return False
