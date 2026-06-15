"""
Module 9 — Higgsfield Prompt Generator
Analyses the uploaded footage and generates Higgsfield AI prompts
that match the visual style, lighting, and subject matter.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from scripts.core.api_clients import OpenAIClient
from scripts.core.base_module import BaseModule, ModuleResult
from scripts.core.config_manager import ConfigManager
from scripts.modules.video_analyst import VideoAnalysisData
from scripts.modules.color_analyzer import ColorReport


@dataclass
class HiggsPrompt:
    style: str
    prompt: str
    negative_prompt: str
    motion_keywords: List[str]
    lighting_keywords: List[str]
    camera_keywords: List[str]
    tags: List[str]


@dataclass
class HiggsData:
    prompts: List[HiggsPrompt] = field(default_factory=list)
    style_analysis: str = ""
    recommended_styles: List[str] = field(default_factory=list)


# Style template library
STYLE_TEMPLATES = {
    "Luxury Product Shot": {
        "base_prompt": "ultra-luxury commercial product shot, flawless studio lighting, 8K resolution",
        "negative": "amateur, noisy, low quality, cluttered background",
        "motion": ["slow push-in", "subtle rotation", "floating"],
        "lighting": ["rim lighting", "softbox diffusion", "reflective surface"],
        "camera": ["macro lens", "shallow depth of field", "bokeh"],
    },
    "Macro Honey": {
        "base_prompt": "extreme close-up macro photography, golden honey dripping, viscous liquid",
        "negative": "wide shot, artificial, dull colours",
        "motion": ["ultra slow motion", "4K 240fps", "drip cascade"],
        "lighting": ["backlit translucent", "warm golden hour", "amber glow"],
        "camera": ["macro 100mm", "f/2.8", "razor thin focus"],
    },
    "Cinematic Slow Motion": {
        "base_prompt": "cinematic slow motion footage, 4K 120fps, Hollywood blockbuster quality",
        "negative": "fast motion, blurry, amateur footage",
        "motion": ["phantom flex", "240fps ultra slow", "time dilation"],
        "lighting": ["dramatic side lighting", "volumetric rays", "motivated light"],
        "camera": ["anamorphic 2.39:1", "lens flare", "cinematic grading"],
    },
    "Natural Light": {
        "base_prompt": "soft natural light documentary style, authentic human moments, organic texture",
        "negative": "harsh flash, artificial studio, staged",
        "motion": ["handheld gentle", "observational", "natural camera movement"],
        "lighting": ["window light", "diffused daylight", "soft shadows"],
        "camera": ["35mm prime", "available light", "documentary"],
    },
    "Golden Hour": {
        "base_prompt": "magical golden hour footage, warm sun rays, long shadows, cinematic warmth",
        "negative": "midday harsh light, cold tones, overcast flat light",
        "motion": ["sun flare sweep", "silhouette reveal", "slow pan"],
        "lighting": ["3200K warm", "golden ratio", "lens flare"],
        "camera": ["85mm portrait", "sun behind subject", "warm LUT"],
    },
    "Apple Style": {
        "base_prompt": "Apple Inc. commercial aesthetic, minimalist perfection, product floating in white void",
        "negative": "clutter, imperfection, low budget, outdated design",
        "motion": ["product reveal spin", "floating assembly", "precision movement"],
        "lighting": ["pure white infinity wall", "specular highlights", "edge highlights"],
        "camera": ["centred composition", "product hero shot", "clinical perfection"],
    },
    "Premium Commercial": {
        "base_prompt": "premium brand commercial, aspirational lifestyle, polished production value",
        "negative": "amateur, generic, stock footage feel",
        "motion": ["confident subject movement", "brand reveal", "lifestyle montage"],
        "lighting": ["three-point lighting", "brand colour integration"],
        "camera": ["versatile commercial", "brand identity reinforcement"],
    },
    "Documentary Realism": {
        "base_prompt": "raw authentic documentary, verité style, real human stories, journalistic truth",
        "negative": "staged, artificial, over-produced, Hollywood",
        "motion": ["reactive handheld", "follow action", "natural"],
        "lighting": ["practical lights", "available light", "real environment"],
        "camera": ["wide angle observational", "zoom documentary"],
    },
    "Fashion Editorial": {
        "base_prompt": "high-fashion editorial photography turned motion, Vogue aesthetic, haute couture energy",
        "negative": "casual, unstylised, commercial generic",
        "motion": ["model walk slow motion", "fabric movement", "editorial pose"],
        "lighting": ["fashion strobe", "colour gel accent", "dramatic shadows"],
        "camera": ["70-200mm editorial", "compressed background", "luxury feel"],
    },
    "Food Photography": {
        "base_prompt": "mouth-watering food cinematography, steam rising, fresh ingredients, culinary art",
        "negative": "unappetising, poor styling, wrong colour temperature",
        "motion": ["fork reveal slow motion", "steam wisps", "sauce pour"],
        "lighting": ["backlit steam", "warm food tones", "controlled reflections"],
        "camera": ["50mm macro", "shallow DOF on food", "plated composition"],
    },
}


class HighgsfieldGenerator(BaseModule):
    MODULE_NAME = "higgsfield_generator"

    def __init__(self, config: ConfigManager, openai: OpenAIClient) -> None:
        super().__init__(config)
        self.openai = openai

    def process(self, video_path: Path, context: dict, **kwargs) -> ModuleResult:
        if not self.openai.is_available():
            return ModuleResult(success=False, module=self.MODULE_NAME,
                                error="OpenAI API required for Higgsfield prompt generation")

        analysis: Optional[VideoAnalysisData] = context.get("video_analyst")
        color: Optional[ColorReport] = context.get("color_analyzer")

        style_analysis, recommended = self._analyse_style(analysis, color)
        self.log.info(f"  Detected styles: {', '.join(recommended[:3])}")

        num = self.cfg("num_prompts", 5)
        available = self.cfg("available_styles", list(STYLE_TEMPLATES.keys()))
        target_styles = [s for s in recommended if s in available][:num]
        while len(target_styles) < num:
            for s in available:
                if s not in target_styles:
                    target_styles.append(s)
                    break
            else:
                break
        target_styles = target_styles[:num]

        prompts = [self._build_prompt(style, analysis, color, style_analysis) for style in target_styles]

        data = HiggsData(prompts=prompts, style_analysis=style_analysis, recommended_styles=recommended)
        return ModuleResult(success=True, module=self.MODULE_NAME, data=data)

    # ── Style analysis ────────────────────────────────────────

    def _analyse_style(
        self,
        analysis: Optional[VideoAnalysisData],
        color: Optional[ColorReport],
    ):
        summary       = analysis.ai_analysis.get("summary", "N/A") if analysis else "N/A"
        content_type  = analysis.ai_analysis.get("content_type", "N/A") if analysis else "N/A"
        tone          = analysis.ai_analysis.get("emotional_tone", "N/A") if analysis else "N/A"
        brightness    = f"{color.avg_brightness:.0f}/255" if color else "N/A"
        wb            = color.estimated_white_balance if color else "N/A"

        prompt = f"""You are a Higgsfield AI prompt specialist and creative director.

Analyse this video:
- Summary: {summary}
- Content type: {content_type}
- Emotional tone: {tone}
- Brightness: {brightness}
- White balance: {wb}

Available styles: {', '.join(STYLE_TEMPLATES.keys())}

Return ONLY valid JSON:
{{
  "style_analysis": "2-sentence description of the footage's visual character",
  "recommended_styles": ["style1", "style2", "style3", "style4", "style5"],
  "reasoning": "why these styles match the footage"
}}"""

        raw = self.openai.chat([{"role": "user", "content": prompt}], response_format="json")
        if not raw:
            return "No analysis available", list(STYLE_TEMPLATES.keys())[:5]
        try:
            data = json.loads(raw)
            return data.get("style_analysis", ""), data.get("recommended_styles", [])
        except Exception:
            return "", list(STYLE_TEMPLATES.keys())[:5]

    # ── Prompt building ───────────────────────────────────────

    def _build_prompt(
        self,
        style: str,
        analysis: Optional[VideoAnalysisData],
        color: Optional[ColorReport],
        style_analysis: str,
    ) -> HiggsPrompt:
        template = STYLE_TEMPLATES.get(style, {})
        summary = analysis.ai_analysis.get("summary", "") if analysis else ""
        tone    = analysis.ai_analysis.get("emotional_tone", "") if analysis else ""

        gpt_prompt = f"""You are a Higgsfield AI expert prompt engineer.

Create a detailed Higgsfield AI video prompt for style: "{style}"

Video context:
- Summary: {summary}
- Tone: {tone}
- Style analysis: {style_analysis}

Base style template:
- Base prompt: {template.get('base_prompt', '')}
- Motion: {', '.join(template.get('motion', []))}
- Lighting: {', '.join(template.get('lighting', []))}
- Camera: {', '.join(template.get('camera', []))}

Return ONLY valid JSON:
{{
  "prompt": "Full Higgsfield prompt (150-250 words) that incorporates the video's subject with this style's aesthetics. Be specific, cinematic, and technical.",
  "negative_prompt": "What to avoid (50-80 words)",
  "motion_keywords": ["keyword1", "keyword2", "keyword3"],
  "lighting_keywords": ["keyword1", "keyword2", "keyword3"],
  "camera_keywords": ["keyword1", "keyword2", "keyword3"],
  "tags": ["tag1", "tag2", "tag3", "tag4", "tag5"]
}}"""

        raw = self.openai.chat([{"role": "user", "content": gpt_prompt}], response_format="json")
        if not raw:
            return HiggsPrompt(
                style=style,
                prompt=template.get("base_prompt", ""),
                negative_prompt=template.get("negative", ""),
                motion_keywords=template.get("motion", []),
                lighting_keywords=template.get("lighting", []),
                camera_keywords=template.get("camera", []),
                tags=[style.lower().replace(" ", "_")],
            )
        try:
            d = json.loads(raw)
            return HiggsPrompt(
                style=style,
                prompt=d.get("prompt", template.get("base_prompt", "")),
                negative_prompt=d.get("negative_prompt", template.get("negative", "")),
                motion_keywords=d.get("motion_keywords", []),
                lighting_keywords=d.get("lighting_keywords", []),
                camera_keywords=d.get("camera_keywords", []),
                tags=d.get("tags", []),
            )
        except Exception:
            return HiggsPrompt(
                style=style,
                prompt=template.get("base_prompt", ""),
                negative_prompt=template.get("negative", ""),
                motion_keywords=template.get("motion", []),
                lighting_keywords=template.get("lighting", []),
                camera_keywords=template.get("camera", []),
                tags=[],
            )
