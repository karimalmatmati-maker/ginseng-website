"""
Module 7 — SEO Writer
Uses GPT-4 to generate platform-optimised titles, descriptions,
captions, keywords, and hashtags for YouTube, TikTok, Instagram.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from scripts.core.api_clients import OpenAIClient
from scripts.core.base_module import BaseModule, ModuleResult
from scripts.core.config_manager import ConfigManager
from scripts.modules.video_analyst import VideoAnalysisData


@dataclass
class PlatformSEO:
    platform: str
    title: str
    description: str
    caption: str
    hashtags: List[str]
    keywords: List[str]
    call_to_action: str
    publishing_tip: str


@dataclass
class SEOReport:
    youtube: Optional[PlatformSEO] = None
    tiktok: Optional[PlatformSEO] = None
    instagram: Optional[PlatformSEO] = None
    raw_response: Dict = field(default_factory=dict)


class SEOWriter(BaseModule):
    MODULE_NAME = "seo_writer"

    def __init__(self, config: ConfigManager, openai: OpenAIClient) -> None:
        super().__init__(config)
        self.openai = openai

    def process(self, video_path: Path, context: dict, **kwargs) -> ModuleResult:
        if not self.openai.is_available():
            return ModuleResult(success=False, module=self.MODULE_NAME,
                                error="OpenAI API not available — SEO generation requires GPT-4")

        analysis: Optional[VideoAnalysisData] = context.get("video_analyst")
        transcript = ""
        summary    = ""
        tags       = []
        if analysis:
            transcript = analysis.transcript[:3000]
            summary    = analysis.ai_analysis.get("summary", "")
            tags       = analysis.ai_analysis.get("content_tags", [])

        raw = self._generate(video_path, transcript, summary, tags)
        report = self._parse(raw)

        self.log.info(f"  YouTube title: {report.youtube.title[:60] if report.youtube else 'N/A'}")
        self.log.info(f"  TikTok caption: {(report.tiktok.caption or '')[:60] if report.tiktok else 'N/A'}")

        return ModuleResult(success=True, module=self.MODULE_NAME, data=report)

    # ── Generation ────────────────────────────────────────────

    def _generate(self, video: Path, transcript: str, summary: str, tags: List[str]) -> dict:
        limits = self.config.get("seo_writer.limits", {})
        yt_title_max   = limits.get("youtube", {}).get("title_max", 100)
        yt_desc_max    = limits.get("youtube", {}).get("description_max", 5000)
        yt_hash_max    = limits.get("youtube", {}).get("hashtags_max", 10)
        tt_cap_max     = limits.get("tiktok", {}).get("caption_max", 2200)
        tt_hash_max    = limits.get("tiktok", {}).get("hashtags_max", 30)
        ig_cap_max     = limits.get("instagram", {}).get("caption_max", 2200)
        ig_hash_max    = limits.get("instagram", {}).get("hashtags_max", 30)

        system = (
            "You are a senior social media strategist and SEO specialist. "
            "You create viral, platform-native content that drives maximum reach. "
            "Your language is clear, engaging, and audience-specific."
        )

        user = f"""Create complete SEO content for a video with these details:

File: {video.name}
Summary: {summary or 'Not available'}
Tags: {', '.join(tags) or 'Not available'}
Transcript excerpt: {transcript[:1500] or 'Not available'}

Return ONLY valid JSON (no markdown) with this structure:
{{
  "youtube": {{
    "title": "Compelling YouTube title (max {yt_title_max} chars, include primary keyword)",
    "description": "Full SEO-optimised YouTube description (max {yt_desc_max} chars). Include: hook paragraph, timestamps placeholder, value propositions, links section, keyword-rich content)",
    "hashtags": ["up to {yt_hash_max} hashtags without #"],
    "keywords": ["8-12 search keywords"],
    "call_to_action": "Subscribe CTA text",
    "publishing_tip": "Best time and strategy to publish on YouTube"
  }},
  "tiktok": {{
    "title": "TikTok video title (max 150 chars)",
    "caption": "Full TikTok caption with hook (max {tt_cap_max} chars). Start with a hook, add value, end with CTA)",
    "hashtags": ["up to {tt_hash_max} hashtags — mix niche, trending, and broad"],
    "keywords": ["5-8 search terms"],
    "call_to_action": "Follow/save CTA",
    "publishing_tip": "Best posting time and TikTok-specific strategy"
  }},
  "instagram": {{
    "title": "Instagram Reels title",
    "caption": "Instagram caption (max {ig_cap_max} chars). Hook + story + CTA + line breaks for readability)",
    "hashtags": ["up to {ig_hash_max} hashtags — 3 buckets: niche/medium/broad"],
    "keywords": ["5-8 keywords"],
    "call_to_action": "Save/share CTA",
    "publishing_tip": "Best posting time and Instagram-specific strategy"
  }}
}}"""

        raw = self.openai.chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format="json",
        )
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"raw": raw}

    # ── Parsing ───────────────────────────────────────────────

    def _parse(self, data: dict) -> SEOReport:
        def make(platform: str) -> Optional[PlatformSEO]:
            d = data.get(platform)
            if not d:
                return None
            return PlatformSEO(
                platform=platform,
                title=d.get("title", ""),
                description=d.get("description", ""),
                caption=d.get("caption", d.get("description", "")),
                hashtags=d.get("hashtags", []),
                keywords=d.get("keywords", []),
                call_to_action=d.get("call_to_action", ""),
                publishing_tip=d.get("publishing_tip", ""),
            )

        return SEOReport(
            youtube=make("youtube"),
            tiktok=make("tiktok"),
            instagram=make("instagram"),
            raw_response=data,
        )
