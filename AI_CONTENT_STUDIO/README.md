# AI Content Studio

**Automated video production pipeline by Luma IT-Solutions.**
Drop a video into `input/` — everything else is automated.

---

## Architecture

```
AI_CONTENT_STUDIO/
├── input/                      ← Drop your videos here
├── output/
│   ├── shorts/
│   │   ├── youtube/            ← 9:16 shorts for YouTube
│   │   ├── instagram/          ← 9:16 shorts for Instagram
│   │   └── tiktok/             ← 9:16 shorts for TikTok
│   ├── audio/                  ← Extracted & enhanced audio
│   ├── subtitles/              ← SRT, ASS, burned-in variants
│   ├── thumbnails/             ← Scored thumbnail candidates
│   ├── metadata/               ← JSON manifests per project
│   └── reports/                ← PDF content reports
├── agents/                     ← AI agent system prompts
├── scripts/
│   ├── core/                   ← Infrastructure (config, logging, API clients)
│   ├── modules/                ← The 10 processing modules
│   ├── pipeline.py             ← Orchestrator
│   ├── watcher.py              ← Folder watcher
│   └── main.py                 ← CLI entry point
├── config/
│   ├── settings.yaml           ← Master configuration
│   └── .env.example            ← API keys template
└── requirements.txt
```

---

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

You also need **FFmpeg** installed and on your PATH:
- Windows: `winget install ffmpeg` or download from ffmpeg.org
- macOS: `brew install ffmpeg`
- Linux: `sudo apt install ffmpeg`

### 2. Configure API keys

```bash
cp config/.env.example config/.env
# Edit config/.env and add your keys
```

| Key | Required | Purpose |
|-----|----------|---------|
| `OPENAI_API_KEY` | Recommended | Video analysis, hooks, SEO, Higgsfield prompts |
| `ELEVENLABS_API_KEY` | Optional | Voice isolation / audio enhancement |
| `ADOBE_PODCAST_API_KEY` | Optional | Speech enhancement API |
| `GEMINI_API_KEY` | Optional | Alternative to GPT-4 |

### 3. Start the watcher (drop-and-process mode)

```bash
cd AI_CONTENT_STUDIO
python scripts/main.py watch
```

Now drop any video into `input/` — processing starts automatically.

### 4. Process a single file

```bash
python scripts/main.py process path/to/video.mp4
python scripts/main.py process video.mp4 --shorts 10 --duration 30
```

### 5. Check output status

```bash
python scripts/main.py status
```

---

## The 10 Modules

| # | Module | What it does |
|---|--------|-------------|
| 1 | **Video Analyst** | Scene detection, highlights, boring moments, b-roll opportunities, timeline report |
| 2 | **Hook Detector** | Scores first 60s, recommends platform-specific hooks (TikTok/Instagram/YouTube) |
| 3 | **Auto Editor** | Generates 5/10/20 shorts at 15/30/45/60s in 9:16 1080×1920 |
| 4 | **Subtitle Generator** | Whisper transcription → SRT + ASS + burned-in with word highlighting |
| 5 | **Audio Engineer** | Noise/wind/echo detection, Adobe Podcast + ElevenLabs integration, audio report |
| 6 | **Color Analyzer** | Brightness/contrast/WB/exposure analysis, grading suggestions (no auto-modify) |
| 7 | **SEO Writer** | GPT-4 generates titles, descriptions, hashtags for YouTube + TikTok + Instagram |
| 8 | **Thumbnail Generator** | Scores frames by sharpness, faces, composition, emotion → best 6 candidates |
| 9 | **Higgsfield Generator** | Creates 5 style-matched Higgsfield AI video prompts |
| 10 | **Content Report** | Compiles everything into a professional PDF report |

---

## Configuration

Edit `config/settings.yaml` to customise every module:

```yaml
# Toggle individual modules
pipeline:
  enabled_modules:
    - video_analyst
    - hook_detector
    - auto_editor
    # comment out modules you don't need

# Whisper model size (speed vs accuracy trade-off)
subtitle_generator:
  whisper_model: "base"    # tiny | base | small | medium | large

# Number of shorts and duration
auto_editor:
  default_num_shorts: 5    # 5 | 10 | 20
  default_duration: 30     # 15 | 30 | 45 | 60

# Enable Adobe Podcast enhancement
audio_engineer:
  use_adobe_podcast: true  # also set ADOBE_PODCAST_API_KEY in .env
```

---

## Module Independence

Every module is a self-contained class that inherits from `BaseModule`.
Removing or replacing a module never breaks others:

```python
# Swap out the SEO writer for your own implementation:
class MyCopySEOWriter(BaseModule):
    MODULE_NAME = "seo_writer"
    def process(self, video_path, context, **kwargs):
        ...
        return ModuleResult(success=True, module=self.MODULE_NAME, data=my_data)
```

Register it in `pipeline.py` and that's it — the rest of the pipeline is unchanged.

---

## Output Files

After processing `my_video.mp4`:

```
output/
├── shorts/
│   ├── youtube/my_video_short01_30s.mp4
│   ├── instagram/my_video_short01_30s.mp4
│   └── tiktok/my_video_short01_30s.mp4
├── audio/
│   ├── my_video_extracted.wav
│   └── my_video_enhanced_adobe.wav   (if Adobe Podcast enabled)
├── subtitles/
│   ├── my_video.srt
│   ├── my_video.ass
│   └── my_video_subtitled.mp4
├── thumbnails/my_video/
│   ├── thumbnail_01_23s.jpg
│   └── thumbnail_02_67s.jpg
├── metadata/manifest_my_video_20240101_120000.json
└── reports/content_report_my_video_20240101_120000.pdf
```

---

## Extending the System

### Add a new module
1. Create `scripts/modules/my_module.py` inheriting `BaseModule`
2. Add it to `scripts/modules/__init__.py`
3. Add it to `pipeline.py` module registry
4. Add `my_module` to `enabled_modules` in `settings.yaml`

### Add a new API client
1. Create a client class in `scripts/core/api_clients.py`
2. Add the API key mapping in `ConfigManager`
3. Inject the client into modules that need it via `pipeline.py`

---

## Requirements

- Python 3.10+
- FFmpeg (CLI, must be on PATH)
- OpenAI API key (recommended for full functionality)
- 4 GB+ RAM for Whisper `base` model
- 8 GB+ RAM for Whisper `medium`/`large`

---

## License

Private — Luma IT-Solutions. All rights reserved.
