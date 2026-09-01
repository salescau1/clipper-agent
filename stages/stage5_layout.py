from __future__ import annotations

from pathlib import Path
from typing import Any
from PIL import ImageFont


def _font(path: Path, size: int):
    return ImageFont.truetype(str(path), max(1, int(size)))


def width(text: str, font_path: Path, size: int) -> float:
    box = _font(font_path, size).getbbox(text or "")
    return float(max(0, box[2] - box[0]))


def wrap_by_width(text: str, font_path: Path, size: int, max_width: int, max_lines: int) -> list[str] | None:
    words = str(text or "").split()
    if not words:
        return []
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        candidate = word if not current else " ".join(current + [word])
        if width(candidate, font_path, size) <= max_width:
            current.append(word)
            continue
        if not current:
            return None
        lines.append(" ".join(current))
        current = [word]
    if current:
        lines.append(" ".join(current))
    return lines if len(lines) <= max_lines else None


def fit_text(text: str, font_path: Path, *, min_size: int, max_size: int, max_width: int, max_lines: int) -> tuple[int, list[str]]:
    for size in range(int(max_size), int(min_size) - 1, -1):
        lines = wrap_by_width(text, font_path, size, max_width, max_lines)
        if lines is not None:
            return size, lines

    size = int(min_size)
    words = str(text or "").split()
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        candidate = word if not current else " ".join(current + [word])
        if current and width(candidate, font_path, size) > max_width:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return size, lines[:max_lines]


def build_layout(
    *,
    creator: str,
    hook: str,
    creator_font: Path,
    hook_font: Path,
    headline_left: int,
    headline_right: int,
    headline_top: int,
    headline_bottom: int,
    creator_min_size: int,
    creator_max_size: int,
    hook_min_size: int,
    hook_max_size: int,
    hook_max_lines: int,
    hook_line_spacing: int,
    density: str = "balanced",
) -> dict[str, Any]:
    max_width = max(100, headline_right - headline_left)

    creator_size, creator_lines = fit_text(
        creator.upper(),
        creator_font,
        min_size=creator_min_size,
        max_size=creator_max_size,
        max_width=max_width,
        max_lines=1,
    )
    creator_text = creator_lines[0] if creator_lines else creator.upper()
    creator_box = _font(creator_font, creator_size).getbbox(creator_text)
    creator_height = max(1, creator_box[3] - creator_box[1])

    # Gemini density influences spacing within a narrow guardrail,
    # but the chosen line-spacing remains fixed at -50.
    hook_max_width = max_width
    hook_size, hook_lines = fit_text(
        hook,
        hook_font,
        min_size=hook_min_size,
        max_size=hook_max_size,
        max_width=hook_max_width,
        max_lines=hook_max_lines,
    )

    hook_y = headline_top + creator_height + 12
    hook_line_height = max(1, _font(hook_font, hook_size).getbbox("Ag")[3] - _font(hook_font, hook_size).getbbox("Ag")[1])
    estimated_hook_height = hook_line_height * len(hook_lines) + hook_line_spacing * max(0, len(hook_lines) - 1)

    # If the headline group would exceed the intended top paper area,
    # reduce Hook size before violating the reference layout.
    while hook_size > hook_min_size and hook_y + estimated_hook_height > headline_bottom:
        hook_size -= 1
        hook_lines = wrap_by_width(hook, hook_font, hook_size, hook_max_width, hook_max_lines) or hook_lines
        hook_line_height = max(1, _font(hook_font, hook_size).getbbox("Ag")[3] - _font(hook_font, hook_size).getbbox("Ag")[1])
        estimated_hook_height = hook_line_height * len(hook_lines) + hook_line_spacing * max(0, len(hook_lines) - 1)

    return {
        "zones": {
            "headline_left": headline_left,
            "headline_right": headline_right,
            "headline_top": headline_top,
            "headline_bottom": headline_bottom,
        },
        "creator": {
            "text": creator_text,
            "size": creator_size,
            "x": headline_left,
            "y": headline_top,
            "width": round(width(creator_text, creator_font, creator_size), 2),
        },
        "hook": {
            "text": "\n".join(hook_lines),
            "size": hook_size,
            "x": headline_left,
            "y": hook_y,
            "line_spacing": hook_line_spacing,
            "lines": len(hook_lines),
            "width": round(max((width(line, hook_font, hook_size) for line in hook_lines), default=0), 2),
            "density": density,
        },
    }
