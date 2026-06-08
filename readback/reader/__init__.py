"""Reader: fetch a URL → extract the article → (optionally summarize) → speak.

The project pivoted from a real-time voice assistant to an offline article
reader in v0.8.0. Offline synthesis removes the real-time constraint that caused
the audio-underrun problems — we synthesize the whole piece, then play/download.
"""
from readback.reader.extract import Article, ExtractError, fetch_article

__all__ = ["Article", "ExtractError", "fetch_article"]
