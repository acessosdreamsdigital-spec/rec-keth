"""Split Júlia's replies into WhatsApp-sized bubbles.

Real people text in short bursts, one thought per message — not a single
wall of text. So every sentence becomes its own bubble by default (split on
. ! ? and line breaks), even when several short sentences together would
still fit under the length cap. The cap only matters for a single sentence
that's genuinely long (explanatory content): that one is kept whole rather
than being cut mid-idea, never merged with neighbors to save bubbles.
"""

from __future__ import annotations

import re

DEFAULT_MAX_LEN = 250

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")


def split_message(text: str, max_len: int = DEFAULT_MAX_LEN) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []

    sentences = [s.strip() for s in _SENTENCE_SPLIT.split(text) if s.strip()]
    if not sentences:
        return []

    chunks: list[str] = []
    for sentence in sentences:
        if len(sentence) <= max_len:
            chunks.append(sentence)
            continue

        # A single sentence longer than max_len — split on commas/semicolons
        # as a softer break so it's not one giant bubble, but never mid-word.
        parts = re.split(r"(?<=[,;])\s+", sentence)
        current = ""
        for part in parts:
            candidate = f"{current} {part}".strip() if current else part
            if len(candidate) <= max_len:
                current = candidate
            else:
                if current:
                    chunks.append(current)
                current = part
        if current:
            chunks.append(current)

    return chunks
