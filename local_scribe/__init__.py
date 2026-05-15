"""local-scribe — local Whisper transcription, ElevenLabs Scribe-compatible JSON.

Drop-in replacement for the ElevenLabs Scribe step in browser-use/video-use.
"""

from local_scribe.transcribe import transcribe_one, load_api_key  # noqa: F401

__version__ = "0.1.0"
