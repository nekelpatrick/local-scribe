"""Local Whisper transcription producing ElevenLabs Scribe-compatible JSON.

Extracts mono 16kHz audio via ffmpeg, runs faster-whisper with word-level
timestamps, and serializes the output to the same schema video-use's
helpers/pack_transcripts.py and helpers/render.py already consume:

    {
      "language_code": "pt",
      "words": [
        {"type": "word",    "text": "Olá", "start": 0.00, "end": 0.30, "speaker_id": "speaker_0"},
        {"type": "spacing", "text": " ",   "start": 0.30, "end": 0.45, "speaker_id": "speaker_0"},
        ...
      ]
    }

Cached per source: if `<edit_dir>/transcripts/<video_stem>.json` already
exists, the upload-equivalent (model run) is skipped — matching the upstream
helpers/transcribe.py contract.

Usage (CLI):
    local-scribe <video> [--edit-dir DIR] [--language LANG]
                         [--num-speakers N] [--model NAME]
                         [--device auto|cpu|cuda]
                         [--compute-type auto|int8|float16|float32]

Usage (library — what the video-use shim imports):
    from local_scribe.transcribe import transcribe_one, load_api_key
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


# -------- Audio extraction (identical to upstream transcribe.py) ------------


def _extract_audio(video: Path, dest: Path) -> None:
    cmd = [
        "ffmpeg", "-y", "-i", str(video),
        "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
        str(dest),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# -------- Device + compute_type detection -----------------------------------


def _detect_device() -> str:
    """Prefer CUDA if available, else CPU. (MPS is not yet supported by ctranslate2.)"""
    try:
        import ctranslate2  # type: ignore

        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda"
    except Exception:
        pass
    return "cpu"


def _default_compute_type(device: str) -> str:
    # float16 is the standard for CUDA; int8 is the practical default on CPU
    # (8-bit quantization, ~2x faster than float32 with negligible quality loss).
    return "float16" if device == "cuda" else "int8"


# -------- Whisper → Scribe JSON conversion ----------------------------------


def _segments_to_scribe(segments, language_code: str) -> dict:
    """Convert a faster-whisper segment iterable to Scribe-compatible JSON.

    A single `speaker_id` ("speaker_0") is used everywhere — local-scribe v1
    does not run diarization. The packed-transcript and render pipelines
    handle missing speakers cleanly (they just see one speaker throughout).
    """
    words_out: list[dict] = []
    prev_end: float | None = None
    speaker = "speaker_0"

    for seg in segments:
        seg_words = getattr(seg, "words", None) or []
        for w in seg_words:
            ws = float(w.start) if w.start is not None else None
            we = float(w.end) if w.end is not None else None
            text = (w.word or "").strip()
            if ws is None or we is None or not text:
                continue

            # Spacing entry for the gap between words. pack_transcripts.py uses
            # these to detect ≥ 0.5s silences and split phrases on them.
            if prev_end is not None and ws > prev_end:
                words_out.append({
                    "type": "spacing",
                    "text": " ",
                    "start": prev_end,
                    "end": ws,
                    "speaker_id": speaker,
                })

            words_out.append({
                "type": "word",
                "text": text,
                "start": ws,
                "end": we,
                "speaker_id": speaker,
            })
            prev_end = we

    return {"language_code": language_code, "words": words_out}


# -------- Public API (video-use compatibility) ------------------------------


def load_api_key() -> str:
    """No-op for local Whisper. Provided so video-use's transcribe_batch.py
    (which does `from transcribe import load_api_key`) keeps working."""
    return ""


def transcribe_one(
    video: Path,
    edit_dir: Path,
    api_key: str = "",
    language: str | None = None,
    num_speakers: int | None = None,
    model_name: str | None = None,
    device: str = "auto",
    compute_type: str = "auto",
    verbose: bool = True,
) -> Path:
    """Transcribe a single video, writing Scribe-compatible JSON. Cached.

    Signature mirrors video-use's `transcribe_one` so the shim can re-export
    this function without adapters. `api_key` is accepted and ignored.
    `num_speakers` is reserved for v2 (diarization) and currently ignored.
    """
    video = Path(video)
    edit_dir = Path(edit_dir)

    transcripts_dir = edit_dir / "transcripts"
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    out_path = transcripts_dir / f"{video.stem}.json"

    if out_path.exists():
        if verbose:
            print(f"cached: {out_path.name}")
        return out_path

    if model_name is None:
        model_name = os.environ.get("LOCAL_SCRIBE_MODEL", "large-v3-turbo")
    if device == "auto":
        device = _detect_device()
    if compute_type == "auto":
        compute_type = _default_compute_type(device)

    if verbose:
        print(f"  extracting audio from {video.name}", flush=True)

    t0 = time.time()
    with tempfile.TemporaryDirectory() as tmp:
        audio = Path(tmp) / f"{video.stem}.wav"
        _extract_audio(video, audio)
        size_mb = audio.stat().st_size / (1024 * 1024)

        if verbose:
            print(
                f"  loading whisper={model_name}  device={device}  "
                f"compute_type={compute_type}  (audio {size_mb:.1f} MB)",
                flush=True,
            )

        # Imported here so the CLI parser + cached-file fast path don't pay
        # the cost of loading torch/ctranslate2 on every invocation.
        from faster_whisper import WhisperModel  # type: ignore

        model = WhisperModel(model_name, device=device, compute_type=compute_type)

        if verbose:
            print(f"  transcribing…", flush=True)
        segments_gen, info = model.transcribe(
            str(audio),
            language=language,
            word_timestamps=True,
            vad_filter=False,
            condition_on_previous_text=False,
        )
        # faster-whisper returns a generator — materialize so we can iterate
        # twice (once for serialization, once for the verbose count).
        segments = list(segments_gen)

        payload = _segments_to_scribe(segments, language_code=info.language or (language or "unknown"))

    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    dt = time.time() - t0

    if verbose:
        kb = out_path.stat().st_size / 1024
        word_count = sum(1 for w in payload["words"] if w["type"] == "word")
        rtf = dt / max(0.001, size_mb / (16000 * 2 / (1024 * 1024)))  # rough
        print(f"  saved: {out_path.name} ({kb:.1f} KB) in {dt:.1f}s — {word_count} words")

    return out_path


# -------- CLI ---------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Transcribe a video locally with faster-whisper, "
                    "writing ElevenLabs Scribe-compatible JSON.",
    )
    ap.add_argument("video", type=Path, help="Path to video file")
    ap.add_argument(
        "--edit-dir",
        type=Path,
        default=None,
        help="Output directory (default: <video_parent>/edit). "
             "Transcript lands in <edit_dir>/transcripts/<video_stem>.json.",
    )
    ap.add_argument(
        "--language",
        type=str,
        default=None,
        help="Optional ISO language code (e.g., 'pt', 'en'). Omit to auto-detect.",
    )
    ap.add_argument(
        "--num-speakers",
        type=int,
        default=None,
        help="Reserved for v2 (diarization). Currently ignored — all speakers "
             "are tagged 'speaker_0'.",
    )
    ap.add_argument(
        "--model",
        type=str,
        default=None,
        help="Whisper model name. Default: $LOCAL_SCRIBE_MODEL or 'large-v3-turbo'. "
             "Options: tiny, base, small, medium, large-v3, large-v3-turbo, "
             "distil-large-v3.",
    )
    ap.add_argument(
        "--device",
        type=str,
        default="auto",
        choices=["auto", "cpu", "cuda"],
        help="auto-detects CUDA, falls back to CPU.",
    )
    ap.add_argument(
        "--compute-type",
        type=str,
        default="auto",
        choices=["auto", "int8", "int8_float16", "float16", "float32"],
        help="auto → float16 on CUDA, int8 on CPU.",
    )
    args = ap.parse_args()

    video = args.video.resolve()
    if not video.exists():
        sys.exit(f"video not found: {video}")
    edit_dir = (args.edit_dir or (video.parent / "edit")).resolve()

    transcribe_one(
        video=video,
        edit_dir=edit_dir,
        language=args.language,
        num_speakers=args.num_speakers,
        model_name=args.model,
        device=args.device,
        compute_type=args.compute_type,
    )


if __name__ == "__main__":
    main()
