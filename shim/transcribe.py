"""Drop-in replacement for browser-use/video-use's helpers/transcribe.py.

Routes transcription through the `local-scribe` CLI installed as a uv tool
(`uv tool install git+https://github.com/nekelpatrick/local-scribe`). The CLI
lives in its own isolated venv on PATH; this shim shell-executes it. That
keeps video-use's venv totally clean — no faster-whisper / ctranslate2 / torch
deps leaking into helpers' import graph.

Why a subprocess instead of `import local_scribe`?
  - `uv tool install` puts local-scribe in an isolated venv. The CLI is on
    PATH, but the package is NOT importable from video-use's venv.
  - Subprocess decouples the two venvs completely. video-use stays minimal.
  - stdout/stderr stream through in real-time so the user still sees progress.

What video-use's transcribe_batch.py needs from this module:
  - `from transcribe import load_api_key, transcribe_one`
  - both are re-exported here with matching signatures.

Installation (one-time, per machine):
    uv tool install git+https://github.com/nekelpatrick/local-scribe
    # then copy this file over video-use/helpers/transcribe.py

Re-apply after every `git pull` in the video-use repo — upstream pulls
overwrite the shim with the original ElevenLabs implementation.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


CLI_NAME = "local-scribe"
INSTALL_HINT = (
    f"`{CLI_NAME}` CLI not found on PATH.\n"
    "Install it once with:\n"
    "    uv tool install git+https://github.com/nekelpatrick/local-scribe\n"
    "Then re-run."
)


def _resolve_cli() -> str:
    path = shutil.which(CLI_NAME)
    if not path:
        sys.exit(INSTALL_HINT)
    return path


def load_api_key() -> str:
    """No-op: local Whisper needs no API key. Kept for upstream compatibility
    so `from transcribe import load_api_key` in transcribe_batch.py still works."""
    return ""


def transcribe_one(
    video,
    edit_dir,
    api_key: str = "",
    language: str | None = None,
    num_speakers: int | None = None,
    verbose: bool = True,
):
    """Shim → `local-scribe` CLI. Signature matches video-use's transcribe_one.

    Output path matches the original contract:
        <edit_dir>/transcripts/<video_stem>.json

    `api_key` is accepted (so transcribe_batch.py can keep passing it) and
    ignored. `num_speakers` is forwarded; local-scribe v1 ignores it, future
    versions may use it for diarization.
    """
    cli = _resolve_cli()
    video = Path(video)
    edit_dir = Path(edit_dir)

    out_path = edit_dir / "transcripts" / f"{video.stem}.json"
    if out_path.exists():
        if verbose:
            print(f"cached: {out_path.name}")
        return out_path

    cmd: list[str] = [cli, str(video), "--edit-dir", str(edit_dir)]
    if language:
        cmd += ["--language", language]
    if num_speakers:
        cmd += ["--num-speakers", str(num_speakers)]

    # stdout/stderr inherited from parent so the user sees model load + progress.
    subprocess.run(cmd, check=True)
    return out_path


def main() -> None:
    """CLI entry for `python helpers/transcribe.py <video>` invocations."""
    ap = argparse.ArgumentParser(
        description="Transcribe a video with local Whisper (drop-in replacement "
                    "for video-use's transcribe.py -- routes to local-scribe).",
    )
    ap.add_argument("video", type=Path, help="Path to video file")
    ap.add_argument(
        "--edit-dir",
        type=Path,
        default=None,
        help="Edit output directory (default: <video_parent>/edit)",
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
        help="Reserved for v2 (diarization). Currently ignored by local-scribe.",
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
    )


if __name__ == "__main__":
    main()
