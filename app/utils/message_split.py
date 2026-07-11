"""Split Júlia's replies into WhatsApp-sized bubbles.

People read a wall of text worse than a few short messages typed one after
another. We break on sentence punctuation (. ! ?) and line breaks, packing
sentences up to ~250 chars per bubble. A single sentence longer than that
(a genuinely explanatory answer) is kept whole rather than cut mid-idea.
"""

from __future__ import annotations

import re

DEFAULT_MAX_LEN = 250

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")


def split_message(text: str, max_len: int = DEFAULT_MAX_LEN) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= max_len:
        return [text]

    sentences = [s.strip() for s in _SENTENCE_SPLIT.split(text) if s.strip()]

    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        candidate = f"{current} {sentence}".strip() if current else sentence
        if len(candidate) <= max_len:
            current = candidate
            continue

        if current:
            chunks.append(current)

        if len(sentence) <= max_len:
            current = sentence
        else:
            # Longer than max_len even alone — explanatory content, keep whole.
            chunks.append(sentence)
            current = ""

    if current:
        chunks.append(current)

    return chunks
