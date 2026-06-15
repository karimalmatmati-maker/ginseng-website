"""
Module 10 — Content Report
Generates a professional PDF report after every project.
Includes: Video Summary, Best Hooks, Shorts List, Audio Issues,
          Colour Analysis, SEO, Thumbnail Suggestions, Publishing Strategy.
Uses ReportLab for PDF generation.
"""

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, TYPE_CHECKING

from scripts.core.base_module import BaseModule, ModuleResult
from scripts.core.config_manager import ConfigManager

if TYPE_CHECKING:
    from scripts.modules.video_analyst import VideoAnalysisData
    from scripts.modules.hook_detector import HookReport
    from scripts.modules.auto_editor import AutoEditorData
    from scripts.modules.subtitle_generator import SubtitleData
    from scripts.modules.audio_engineer import AudioReport
    from scripts.modules.color_analyzer import ColorReport
    from scripts.modules.seo_writer import SEOReport
    from scripts.modules.thumbnail_generator import ThumbnailData
    from scripts.modules.higgsfield_generator import HiggsData


@dataclass
class ReportData:
    pdf_path: Path
    generated_at: str


class ContentReport(BaseModule):
    MODULE_NAME = "content_report"

    # Colours (RGB tuples)
    C_DARK   = (26, 26, 46)
    C_ACCENT = (0, 212, 255)
    C_WHITE  = (255, 255, 255)
    C_GREY   = (180, 180, 180)
    C_WARN   = (255, 165, 0)
    C_OK     = (0, 200, 100)

    def process(self, video_path: Path, context: dict, **kwargs) -> ModuleResult:
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.units import cm
        except ImportError:
            return ModuleResult(
                success=False, module=self.MODULE_NAME,
                error="reportlab not installed — pip install reportlab",
            )

        out_dir = Path(self.config.get("paths.reports", "output/reports"))
        out_dir.mkdir(parents=True, exist_ok=True)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = out_dir / f"content_report_{video_path.stem}_{ts}.pdf"

        self.log.info(f"  Building PDF report → {out_path.name}")
        self._build_pdf(out_path, video_path, context)
        self.log.info(f"  PDF written: {out_path.stat().st_size / 1024:.0f} KB")

        return ModuleResult(
            success=True, module=self.MODULE_NAME,
            data=ReportData(pdf_path=out_path, generated_at=ts),
        )

    # ── PDF construction ──────────────────────────────────────

    def _build_pdf(self, out_path: Path, video_path: Path, ctx: dict) -> None:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
            HRFlowable, KeepTogether, PageBreak,
        )
        from reportlab.lib.enums import TA_CENTER, TA_LEFT

        W, H = A4
        doc = SimpleDocTemplate(
            str(out_path), pagesize=A4,
            leftMargin=1.5*cm, rightMargin=1.5*cm,
            topMargin=1.5*cm, bottomMargin=1.5*cm,
        )

        styles = getSampleStyleSheet()

        def rgb(t): return colors.Color(t[0]/255, t[1]/255, t[2]/255)

        h1 = ParagraphStyle("h1", parent=styles["Heading1"],
                             fontSize=20, textColor=rgb(self.C_ACCENT),
                             spaceAfter=6, fontName="Helvetica-Bold")
        h2 = ParagraphStyle("h2", parent=styles["Heading2"],
                             fontSize=14, textColor=rgb(self.C_DARK),
                             spaceAfter=4, fontName="Helvetica-Bold",
                             borderPad=4)
        body = ParagraphStyle("body", parent=styles["Normal"],
                               fontSize=9, textColor=colors.black,
                               spaceAfter=3, leading=14)
        mono = ParagraphStyle("mono", parent=styles["Code"],
                               fontSize=8, textColor=colors.darkgrey,
                               spaceAfter=2, leading=12, leftIndent=12)

        story = []

        # ── Cover ─────────────────────────────────────────────
        story += [
            Spacer(1, 1*cm),
            Paragraph("AI CONTENT STUDIO", ParagraphStyle("cover_title",
                fontSize=28, textColor=rgb(self.C_ACCENT),
                alignment=TA_CENTER, fontName="Helvetica-Bold")),
            Paragraph("Content Analysis & Production Report", ParagraphStyle("cover_sub",
                fontSize=14, textColor=colors.grey,
                alignment=TA_CENTER)),
            Spacer(1, 0.4*cm),
            HRFlowable(width="100%", thickness=2, color=rgb(self.C_ACCENT)),
            Spacer(1, 0.3*cm),
            Paragraph(f"<b>File:</b> {video_path.name}", body),
            Paragraph(f"<b>Generated:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", body),
            Spacer(1, 0.5*cm),
        ]

        # ── Section 1: Video Summary ──────────────────────────
        analysis = ctx.get("video_analyst")
        story.append(Paragraph("1. VIDEO SUMMARY", h1))
        story.append(HRFlowable(width="100%", thickness=1, color=rgb(self.C_ACCENT)))
        story.append(Spacer(1, 0.2*cm))
        if analysis:
            m = analysis.meta
            ai = analysis.ai_analysis
            data = [
                ["Duration", f"{m.duration:.1f}s", "Resolution", f"{m.width}×{m.height}"],
                ["FPS", f"{m.fps:.2f}", "Aspect Ratio", m.aspect_ratio],
                ["File Size", f"{m.file_size_mb:.1f} MB", "Content Type", ai.get("content_type","N/A")],
                ["Visual Quality", f"{ai.get('visual_quality','N/A')}/10", "Emotional Tone", ai.get("emotional_tone","N/A")],
            ]
            story.append(self._make_table(data, styles))
            story.append(Spacer(1, 0.2*cm))
            if ai.get("summary"):
                story.append(Paragraph(f"<b>Summary:</b> {ai['summary']}", body))
            if ai.get("target_audience"):
                story.append(Paragraph(f"<b>Target Audience:</b> {ai['target_audience']}", body))
            story.append(Spacer(1, 0.3*cm))
        else:
            story.append(Paragraph("Video analysis not available.", body))

        # ── Section 2: Best Hooks ─────────────────────────────
        hook_report = ctx.get("hook_detector")
        story.append(Paragraph("2. BEST HOOKS", h1))
        story.append(HRFlowable(width="100%", thickness=1, color=rgb(self.C_ACCENT)))
        story.append(Spacer(1, 0.2*cm))
        if hook_report:
            for platform, hook in [("TikTok", hook_report.tiktok),
                                    ("Instagram", hook_report.instagram),
                                    ("YouTube", hook_report.youtube)]:
                if hook:
                    story.append(Paragraph(f"<b>{platform} Hook</b>  [t={hook.start_time:.1f}s  score={hook.score:.3f}]", h2))
                    if hook.hook_text:
                        story.append(Paragraph(f'"{hook.hook_text}"', mono))
                    if hook.reason:
                        story.append(Paragraph(f"Reason: {hook.reason}", body))
                    story.append(Spacer(1, 0.2*cm))
            if hook_report.summary:
                story.append(Paragraph(f"<b>Strategy:</b> {hook_report.summary}", body))
        else:
            story.append(Paragraph("Hook analysis not available.", body))
        story.append(Spacer(1, 0.3*cm))

        # ── Section 3: Suggested Shorts ───────────────────────
        editor_data = ctx.get("auto_editor")
        story.append(Paragraph("3. SUGGESTED SHORTS", h1))
        story.append(HRFlowable(width="100%", thickness=1, color=rgb(self.C_ACCENT)))
        story.append(Spacer(1, 0.2*cm))
        if editor_data and editor_data.shorts:
            headers = ["#", "Platform", "Duration", "Start → End", "Quality", "File"]
            rows = [headers]
            for i, s in enumerate(editor_data.shorts[:20], 1):
                rows.append([
                    str(i), s.platform, f"{s.duration:.0f}s",
                    f"{self.fmt_time(s.start_time)} → {self.fmt_time(s.end_time)}",
                    f"{s.quality_score:.3f}", s.path.name,
                ])
            story.append(self._make_table(rows, styles, has_header=True))
            story.append(Paragraph(f"Total generated: {editor_data.total_generated} shorts", body))
        else:
            story.append(Paragraph("Auto editor not available or no shorts generated.", body))
        story.append(Spacer(1, 0.3*cm))

        # ── Section 4: Audio Issues ───────────────────────────
        audio: Optional["AudioReport"] = ctx.get("audio_engineer")
        story.append(Paragraph("4. AUDIO ANALYSIS", h1))
        story.append(HRFlowable(width="100%", thickness=1, color=rgb(self.C_ACCENT)))
        story.append(Spacer(1, 0.2*cm))
        if audio:
            from reportlab.lib import colors as rl_colors
            data = [
                ["RMS Level", f"{audio.rms_db:.1f} dB", "Peak Level", f"{audio.peak_db:.1f} dB"],
                ["Noise Floor", f"{audio.noise_floor_db:.1f} dB", "Dynamic Range", f"{audio.dynamic_range_db:.1f} dB"],
                ["Mic Quality Score", f"{audio.mic_quality_score:.1f}/10", "Enhancement", audio.enhancement_method],
            ]
            story.append(self._make_table(data, styles))
            story.append(Spacer(1, 0.2*cm))
            if audio.issues:
                story.append(Paragraph("<b>Issues Detected:</b>", h2))
                for iss in audio.issues:
                    story.append(Paragraph(f"⚠ [{iss.severity.upper()}] {iss.issue} — {iss.description}", body))
            if audio.recommendations:
                story.append(Paragraph("<b>Recommendations:</b>", h2))
                for rec in audio.recommendations:
                    story.append(Paragraph(f"• {rec}", body))
        else:
            story.append(Paragraph("Audio analysis not available.", body))
        story.append(Spacer(1, 0.3*cm))

        # ── Section 5: Colour Analysis ────────────────────────
        color: Optional["ColorReport"] = ctx.get("color_analyzer")
        story.append(Paragraph("5. COLOUR ANALYSIS", h1))
        story.append(HRFlowable(width="100%", thickness=1, color=rgb(self.C_ACCENT)))
        story.append(Spacer(1, 0.2*cm))
        if color:
            data = [
                ["Avg Brightness", f"{color.avg_brightness:.1f}/255", "Avg Contrast", f"{color.avg_contrast:.1f}"],
                ["Avg Saturation", f"{color.avg_saturation:.1f}/255", "White Balance", color.estimated_white_balance],
                ["Exposure", color.exposure_assessment, "Skin Tones", "Yes" if color.skin_tone_found else "No"],
            ]
            story.append(self._make_table(data, styles))
            story.append(Spacer(1, 0.2*cm))
            story.append(Paragraph("<b>Grading Suggestions:</b>", h2))
            for s in color.grading_suggestions:
                story.append(Paragraph(f"• {s}", body))
        else:
            story.append(Paragraph("Colour analysis not available.", body))
        story.append(Spacer(1, 0.3*cm))

        # ── Section 6: SEO ────────────────────────────────────
        seo: Optional["SEOReport"] = ctx.get("seo_writer")
        story.append(PageBreak())
        story.append(Paragraph("6. SEO & CONTENT STRATEGY", h1))
        story.append(HRFlowable(width="100%", thickness=1, color=rgb(self.C_ACCENT)))
        story.append(Spacer(1, 0.2*cm))
        if seo:
            for platform_seo, label in [(seo.youtube, "YouTube"), (seo.tiktok, "TikTok"), (seo.instagram, "Instagram")]:
                if platform_seo:
                    story.append(Paragraph(f"<b>{label}</b>", h2))
                    story.append(Paragraph(f"<b>Title:</b> {platform_seo.title}", body))
                    cap = (platform_seo.caption or platform_seo.description or "")[:300]
                    story.append(Paragraph(f"<b>Caption:</b> {cap}{'…' if len(cap) == 300 else ''}", body))
                    if platform_seo.hashtags:
                        ht = " ".join(f"#{h}" for h in platform_seo.hashtags[:15])
                        story.append(Paragraph(f"<b>Hashtags:</b> {ht}", body))
                    if platform_seo.publishing_tip:
                        story.append(Paragraph(f"<b>Publishing tip:</b> {platform_seo.publishing_tip}", body))
                    story.append(Spacer(1, 0.2*cm))
        else:
            story.append(Paragraph("SEO writer not available.", body))

        # ── Section 7: Thumbnail Suggestions ─────────────────
        thumbs: Optional["ThumbnailData"] = ctx.get("thumbnail_generator")
        story.append(Paragraph("7. THUMBNAIL SUGGESTIONS", h1))
        story.append(HRFlowable(width="100%", thickness=1, color=rgb(self.C_ACCENT)))
        story.append(Spacer(1, 0.2*cm))
        if thumbs and thumbs.candidates:
            headers = ["Rank", "Timestamp", "Sharpness", "Faces", "Composition", "AI Score", "Total"]
            rows = [headers]
            for i, c in enumerate(thumbs.candidates[:6], 1):
                rows.append([
                    str(i), f"{c.timestamp:.1f}s",
                    f"{c.sharpness_score:.0f}", str(c.face_count),
                    f"{c.composition_score:.3f}", f"{c.ai_score:.2f}",
                    f"{c.total_score:.3f}",
                ])
            story.append(self._make_table(rows, styles, has_header=True))
            if thumbs.best:
                story.append(Paragraph(
                    f"<b>Best candidate:</b> {thumbs.best.path.name} at t={thumbs.best.timestamp:.1f}s", body))
                if thumbs.best.ai_description:
                    story.append(Paragraph(f"<b>AI assessment:</b> {thumbs.best.ai_description}", body))
        else:
            story.append(Paragraph("Thumbnail generator not available.", body))
        story.append(Spacer(1, 0.3*cm))

        # ── Section 8: Higgsfield Prompts ─────────────────────
        higgs: Optional["HiggsData"] = ctx.get("higgsfield_generator")
        story.append(Paragraph("8. HIGGSFIELD AI PROMPTS", h1))
        story.append(HRFlowable(width="100%", thickness=1, color=rgb(self.C_ACCENT)))
        story.append(Spacer(1, 0.2*cm))
        if higgs and higgs.prompts:
            if higgs.style_analysis:
                story.append(Paragraph(f"<b>Style Analysis:</b> {higgs.style_analysis}", body))
                story.append(Spacer(1, 0.2*cm))
            for p in higgs.prompts:
                story.append(Paragraph(f"<b>Style: {p.style}</b>", h2))
                story.append(Paragraph(f"<b>Prompt:</b>", body))
                story.append(Paragraph(p.prompt, mono))
                story.append(Paragraph(f"<b>Negative:</b> {p.negative_prompt}", mono))
                if p.tags:
                    story.append(Paragraph(f"<b>Tags:</b> {', '.join(p.tags)}", body))
                story.append(Spacer(1, 0.3*cm))
        else:
            story.append(Paragraph("Higgsfield generator not available.", body))

        # ── Section 9: Publishing Strategy ───────────────────
        story.append(PageBreak())
        story.append(Paragraph("9. PUBLISHING STRATEGY", h1))
        story.append(HRFlowable(width="100%", thickness=1, color=rgb(self.C_ACCENT)))
        story.append(Spacer(1, 0.2*cm))
        strategy = self._build_publishing_strategy(ctx)
        for line in strategy:
            story.append(Paragraph(line, body))

        doc.build(story)

    # ── Helpers ───────────────────────────────────────────────

    def _make_table(self, data: list, styles, has_header: bool = False):
        from reportlab.platypus import Table, TableStyle
        from reportlab.lib import colors

        def rgb(t): return colors.Color(t[0]/255, t[1]/255, t[2]/255)

        col_widths = None
        t = Table(data, colWidths=col_widths, repeatRows=1 if has_header else 0)
        ts_cmds = [
            ("BACKGROUND", (0, 0), (-1, 0 if has_header else -1), rgb(self.C_DARK)),
            ("TEXTCOLOR",  (0, 0), (-1, 0 if has_header else -1), rgb(self.C_WHITE)),
            ("FONTNAME",   (0, 0), (-1, 0 if has_header else -1), "Helvetica-Bold"),
            ("FONTSIZE",   (0, 0), (-1, -1), 8),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.Color(0.95, 0.95, 0.97)]),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING",    (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]
        if has_header:
            ts_cmds.append(("BACKGROUND", (0, 0), (-1, 0), rgb(self.C_DARK)))
        t.setStyle(TableStyle(ts_cmds))
        return t

    def _build_publishing_strategy(self, ctx: dict) -> List[str]:
        lines = []
        seo = ctx.get("seo_writer")
        if seo:
            for platform_seo, label in [(seo.youtube, "YouTube"), (seo.tiktok, "TikTok"), (seo.instagram, "Instagram")]:
                if platform_seo and platform_seo.publishing_tip:
                    lines.append(f"<b>{label}:</b> {platform_seo.publishing_tip}")
        if not lines:
            lines = [
                "<b>YouTube:</b> Upload Tuesday–Thursday 14:00–16:00 local time. Use all custom thumbnail candidates A/B tested.",
                "<b>TikTok:</b> Post Tuesday, Thursday, Friday between 07:00–09:00 or 19:00–21:00. Use trending sounds.",
                "<b>Instagram:</b> Post Wednesday and Friday at 11:00 or 13:00. Use Reels for max reach. Story cross-promote.",
                "• Repurpose one long-form video into 5–10 platform-specific shorts.",
                "• Respond to comments within first 60 minutes to maximise algorithm boost.",
                "• Pin the best comment to guide audience engagement.",
            ]
        return lines
