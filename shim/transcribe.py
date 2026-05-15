"""Drop-in replacement for browser-use/video-use's helpers/transcribe.py.

Re-exports `transcribe_one` and `load_api_key` from the locally installed
`local-scribe` package, so video-use's transcribe_batch.py — which does
`from transcribe import load_api_key, transcribe_one` — works without changes.

Installation (one-time, per machine):
    uv tool install git+https://github.com/nekelpatrick/local-scribe

Then copy this shim over video-use's helper:
    # Linux/macOS
    cp ~/Developer/local-scribe/shim/transcribe.py ~/Developer/video-use/helpers/transcribe.py
    # Windows (PowerShell)
    Copy-Item -Force "$env:USERPROFILE\\Developer\\local-scribe\\shim\\transcribe.py" `
                     "$env:USERPROFILE\\Developer\\video-use\\helpers\\transcribe.py"

After every `git pull` in the video-use repo, re-apply the shim if upstream
ever changes its transcribe.py contract.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    # Imported lazily inside transcribe_one to keep `--help` fast and to give a
    # clean error if the user hasn't installed local-scribe yet.
    from local_scribe.transcribe import transcribe_one as _lc_transcribe_one  # type: ignore  # noqa: F401
    _HAVE_LOCAL_SCRIBE = True
except Exception as _import_err:  # pragma: no cover
    _HAVE_LOCAL_SCRIBE = False
    _IMPORT_ERR = _import_err


def _require_local_scribe() -> None:
    if _HAVE_LOCAL_SCRIBE:
        return
    sys.exit(
        "local-scribe is not importable in this Python environment.\n"
        "Install it once with:\n"
        "    uv tool install git+https://github.com/nekelpatrick/local-scribe\n"
        "Or add it as a project dep:\n"
        "    uv add git+https://github.com/nekelpatrick/local-scribe\n"
        f"(Import error: {_IMPORT_ERR})"
    )


def load_api_key() -> str:
    """No-op: local Whisper needs no API key. Kept for upstream compatibility."""
    return ""


def transcribe_one(
    video: Path,
    edit_dir: Path,
    api_key: str = "",
    language: str | None = None,
    num_speakers: int | None = None,
    verbose: bool = True,
) -> Path:
    """Shim → local_scribe.transcribe_one. `api_key` is accepted and ignored."""
    _require_local_scribe()
    from local_scribe.transcribe import transcribe_one as _lc

    return _lc(
        video=Path(video),
        edit_dir=Path(edit_dir),
        language=language,
        num_speakers=num_speakers,
        verbose=verbose,
    )


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Transcribe a video with local Whisper (drop-in replacement "
                    "for video-use's transcribe.py).",
    )
    ap.add_argument("video", type=Path, help="Path to video file")
    ap.add_argument("--edit-dir", type=Path, default=None,
                    help="Output directory (default: <video_parent>/edit)")
    ap.add_argument("--language", type=str, default=None,
                    help="Optional ISO language code (e.g., 'pt', 'en'). Omit to auto-detect.")
    ap.add_argument("--num-speakers", type=int, default=None,
                    help="Reserved for v2 (diarization). Currently ignored.")
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
