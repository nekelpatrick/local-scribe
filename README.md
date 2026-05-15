# local-scribe

Local Whisper transcription producing **ElevenLabs Scribe-compatible JSON**. Drop-in replacement for the transcribe step in [`browser-use/video-use`](https://github.com/browser-use/video-use) — same file path, same output schema, **no API key, no per-minute cost**.

```
              ┌───────────────────────────────────┐
              │  video-use  (helpers/transcribe)  │
              │     ↓ (reads ELEVENLABS_API_KEY)  │
   BEFORE:    │     ElevenLabs Scribe API         │   $$$
              │     ↓                             │
              │  transcripts/<stem>.json          │
              └───────────────────────────────────┘

              ┌───────────────────────────────────┐
              │  video-use  (helpers/transcribe)  │  ← thin shim
              │     ↓                             │
   AFTER:     │   local-scribe (faster-whisper)   │   free
              │     ↓                             │
              │  transcripts/<stem>.json          │   same schema
              └───────────────────────────────────┘
```

This README is the **LLM bootstrap script** — any agent (Claude Code, Codex, Cursor) should be able to take a fresh Windows or macOS machine, with nothing installed beyond the agent, to a working `local-scribe` + patched `video-use` setup by following the numbered steps. Don't skip steps.

---

## Why

The upstream `video-use/SKILL.md` lists "Running Whisper locally on CPU" as an anti-pattern (slow, normalizes fillers, hosted Scribe is better). Those concerns are real but addressable:

| Concern | local-scribe response |
|---|---|
| **Speed** | Uses `faster-whisper` (CTranslate2 backend) — 4× faster than `openai-whisper` for the same model. Defaults to `large-v3-turbo` (809M params, much faster than `large-v3`). Auto-detects CUDA on Windows. |
| **Word-timestamp drift** | Faster-whisper's word timestamps drift ~50–150ms, comparable to hosted Scribe. The video-use Hard Rule 7 ("pad every cut edge by 30–200ms") already absorbs this. |
| **Filler normalization** | We run with `condition_on_previous_text=False` and `vad_filter=False` to preserve more verbatim output. Whisper still drops some "uh"/"um", which loses some editorial signal. v2 will switch to WhisperX for better word boundaries + optional pyannote diarization. |
| **Cost** | Zero, after one-time model download (~800 MB for `large-v3-turbo`). |

If you can swallow those tradeoffs, you save the ElevenLabs API bill while keeping the rest of `video-use` unchanged.

---

## What's in this repo

```
local-scribe/
├── README.md                       ← this file; the bootstrap guide
├── pyproject.toml                  ← faster-whisper, Python 3.11–3.12
├── LICENSE                         ← MIT
├── .gitignore
├── local_scribe/
│   ├── __init__.py                 ← exports transcribe_one, load_api_key
│   └── transcribe.py               ← CLI + library entry point
└── shim/
    └── transcribe.py               ← drop-in for video-use's helpers/transcribe.py
```

**Output schema** — identical to `helpers/pack_transcripts.py`'s input contract:

```json
{
  "language_code": "pt",
  "words": [
    {"type": "word",    "text": "Olá", "start": 0.00, "end": 0.30, "speaker_id": "speaker_0"},
    {"type": "spacing", "text": " ",   "start": 0.30, "end": 0.45, "speaker_id": "speaker_0"},
    {"type": "word",    "text": "mundo", "start": 0.45, "end": 0.85, "speaker_id": "speaker_0"}
  ]
}
```

`speaker_id` is always `"speaker_0"` in v1 — no diarization yet. `audio_event` entries (laughs, sighs) are not emitted yet. Both gaps `pack_transcripts.py` handles gracefully.

---

## Bootstrap from zero

Goal: from a fresh Windows 11 or macOS machine with nothing installed (except your agent), get `local-scribe` working and wired into `video-use` so transcription happens locally without an API key.

### Step 0 — Detect OS

```bash
uname -s    # Darwin → macOS, Linux → Linux
```

```powershell
[System.Environment]::OSVersion.Platform    # PowerShell, prints "Win32NT" on Windows
```

### Step 1 — Install prerequisites

You need: **git**, **uv** (Python manager), **ffmpeg** (audio extraction). See the [claude-config README](https://github.com/nekelpatrick/claude-config) for the full prereq install if you haven't done it yet. Quick version:

#### Windows 11

```powershell
winget install --id Git.Git        -e --scope user --silent --accept-package-agreements --accept-source-agreements
winget install --id astral-sh.uv   -e --scope user --silent --accept-package-agreements --accept-source-agreements
winget install --id Gyan.FFmpeg    -e --scope user --silent --accept-package-agreements --accept-source-agreements
$env:Path = [System.Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [System.Environment]::GetEnvironmentVariable('Path','User')
```

#### macOS

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"   # Homebrew, if not present
brew install git uv ffmpeg
```

### Step 2 — Install `local-scribe` as a global CLI

`uv tool install` puts the `local-scribe` command on PATH in its own isolated venv. The video-use shim invokes it via subprocess or imports it — either way, it must be installed.

```bash
uv tool install git+https://github.com/nekelpatrick/local-scribe
```

Verify:

```bash
local-scribe --help
```

The first real transcription call downloads the Whisper model (~800 MB for `large-v3-turbo`) into `~/.cache/huggingface/`. Subsequent calls are cache hits — instant.

### Step 3 — Wire the shim into `video-use`

Replace `~/Developer/video-use/helpers/transcribe.py` with the shim. After this swap, **every existing video-use script** (`transcribe_batch.py`, the editor sub-agent, SKILL.md flows) routes through `local-scribe` automatically.

#### Windows

```powershell
# Back up the original (one-time)
$bak = "$env:USERPROFILE\Developer\video-use\helpers\transcribe.elevenlabs.py.bak"
if (-not (Test-Path $bak)) {
    Copy-Item "$env:USERPROFILE\Developer\video-use\helpers\transcribe.py" $bak
}
# Apply the shim
Copy-Item -Force "$env:USERPROFILE\Developer\local-scribe\shim\transcribe.py" `
                 "$env:USERPROFILE\Developer\video-use\helpers\transcribe.py"
```

#### macOS

```bash
# Back up the original (one-time)
[ -f ~/Developer/video-use/helpers/transcribe.elevenlabs.py.bak ] || \
    cp ~/Developer/video-use/helpers/transcribe.py \
       ~/Developer/video-use/helpers/transcribe.elevenlabs.py.bak

# Apply the shim
cp -f ~/Developer/local-scribe/shim/transcribe.py \
      ~/Developer/video-use/helpers/transcribe.py
```

**Re-run Step 3 after every `git pull` in `~/Developer/video-use/`** — upstream pulls overwrite the shim.

### Step 4 — Smoke-test the pipeline

The cheapest correctness check is a 5–10s clip. Don't use a feature-length take.

```bash
mkdir -p ~/footage/smoketest
# Drop one short .mp4 into ~/footage/smoketest/
cd ~/Developer/video-use
uv run python helpers/transcribe.py ~/footage/smoketest/<your_clip>.mp4
cat ~/footage/smoketest/edit/transcripts/<your_clip>.json | head -30
```

A working pipeline prints something like:

```
  extracting audio from your_clip.mp4
  loading whisper=large-v3-turbo  device=cuda  compute_type=float16  (audio 1.2 MB)
  transcribing…
  saved: your_clip.json (5.4 KB) in 12.3s — 47 words
```

If `device=cpu` and it's painfully slow, see [GPU acceleration](#gpu-acceleration) below.

---

## CLI reference

```text
local-scribe <video> [options]

  --edit-dir DIR        output dir (default: <video_parent>/edit)
                        transcript written to <edit_dir>/transcripts/<stem>.json
  --language LANG       ISO code: 'pt', 'en', 'es', … (default: auto-detect)
  --num-speakers N      reserved for v2 (diarization); currently ignored
  --model NAME          Whisper model. Default: $LOCAL_SCRIBE_MODEL or large-v3-turbo
                        options: tiny, base, small, medium,
                                 large-v3, large-v3-turbo, distil-large-v3
  --device auto|cpu|cuda          default: auto (cuda if available, else cpu)
  --compute-type auto|int8|int8_float16|float16|float32
                        default: auto (float16 on cuda, int8 on cpu)
```

Examples:

```bash
# Default: large-v3-turbo, auto device, auto compute_type
local-scribe ~/footage/launch/C0103.MP4

# Pin language for slightly faster first-token + better accuracy on short clips
local-scribe ~/footage/launch/C0103.MP4 --language pt

# Use a smaller model on a slow machine
local-scribe ~/footage/launch/C0103.MP4 --model small

# Force CPU even with a GPU present (e.g., GPU is busy with rendering)
local-scribe ~/footage/launch/C0103.MP4 --device cpu --compute-type int8
```

---

## Model picking

| Model | Size | Speed (CPU)¹ | Speed (CUDA)¹ | Notes |
|---|---|---|---|---|
| `tiny` | 39 M | 8–10× RT | 50× RT | Bad for any serious use. |
| `base` | 74 M | 5–7× RT | 30× RT | Same. |
| `small` | 244 M | 3–5× RT | 20× RT | Acceptable for English short-form. PT‑BR drops accuracy noticeably. |
| `medium` | 769 M | 1.5–2× RT | 10× RT | Good PT‑BR floor. |
| **`large-v3-turbo`** | 809 M | 1.5–2× RT | 12× RT | **Default.** Same architecture as large-v3 but pruned for speed. |
| `large-v3` | 1550 M | 0.5–1× RT | 5–7× RT | Highest accuracy, slowest. Use when transcript will be re-used many times. |
| `distil-large-v3` | 756 M | 2× RT | 15× RT | Distilled large-v3; English-focused. Skip for PT‑BR. |

¹ RT = real-time. "1× RT" means 1 minute of audio takes ~1 minute to transcribe. Highly variable by hardware.

Override the default per session:

```bash
export LOCAL_SCRIBE_MODEL=medium    # or set in ~/.claude/settings.local.json under env
```

---

## GPU acceleration

`faster-whisper` uses CTranslate2, which supports CUDA out of the box. Installing `local-scribe` via `uv tool install` does **not** pull CUDA libraries — they piggyback on a system CUDA install.

- **Windows + NVIDIA**: install the NVIDIA CUDA Toolkit 12.x and cuDNN 9.x for CUDA 12. `local-scribe --device cuda` should then work. If `device=auto` keeps falling back to CPU, run `python -c "import ctranslate2; print(ctranslate2.get_cuda_device_count())"`; a `0` means CTranslate2 isn't finding CUDA.
- **macOS**: CTranslate2 does **not** support Apple MPS yet. CPU only. `int8` compute on Apple Silicon is reasonable for short clips. For long footage on Macs, the practical answer is `large-v3-turbo --compute-type int8` and a coffee.
- **WSL2 + NVIDIA**: same as Windows native; ensure WSL CUDA runtime is installed.

---

## Updating

```bash
uv tool upgrade local-scribe
# or, to install from a branch / commit:
uv tool install --reinstall git+https://github.com/nekelpatrick/local-scribe@<ref>
```

After upgrading, re-apply the shim **only if** this repo's `shim/transcribe.py` changed (rare; the shim is intentionally thin).

---

## Roadmap

- **v0.1 (this release):** faster-whisper, no diarization, no audio-event tags, drop-in JSON.
- **v0.2:** WhisperX backend — wav2vec2 forced alignment → tighter word boundaries.
- **v0.3:** optional pyannote diarization (gated behind HF token; degrades to `speaker_0` if not set).
- **v0.4:** lightweight audio-event detector (laughs, applause) so `pack_transcripts.py` gets the editorial signals back.

Issues / PRs welcome.

---

## License

MIT. See `LICENSE`.
