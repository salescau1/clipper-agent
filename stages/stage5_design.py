from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

try:
    from google import genai
    from google.genai import types
except Exception:
    genai = None
    types = None


@dataclass
class GeminiDesign:
    hook: str
    emphasis: str = "strong"
    hook_lines: int = 2
    density: str = "balanced"
    rationale: str = ""
    source: str = "fallback"
    schema_version: int = 3

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = str(text or "").strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if match:
        cleaned = match.group(0)
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError("Gemini response is not a JSON object.")
    return data


def _clean_hook(text: str, max_chars: int) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    text = text.replace("!!!", "?!").replace("!!", "!")
    if len(text) <= max_chars:
        return text
    words: list[str] = []
    for word in text.split():
        candidate = word if not words else " ".join(words + [word])
        if len(candidate) > max_chars:
            break
        words.append(word)
    return " ".join(words) or text[:max_chars].rstrip()


def fallback_design(current_hook: str, title: str, max_chars: int) -> GeminiDesign:
    hook = _clean_hook(current_hook or title or "TOPIK MENARIK", max_chars)
    return GeminiDesign(
        hook=hook,
        hook_lines=2 if len(hook) >= 42 else 1,
        density="balanced",
        rationale="Deterministic fallback",
        source="fallback",
    )


def load_cached(path: Path) -> GeminiDesign | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        design = data.get("design", data)
        if int(design.get("schema_version", 0)) != 3:
            return None
        hook = str(design.get("hook") or "").strip()
        if not hook:
            return None
        return GeminiDesign(
            hook=hook,
            emphasis=str(design.get("emphasis") or "strong"),
            hook_lines=1 if int(design.get("hook_lines") or 2) == 1 else 2,
            density=str(design.get("density") or "balanced"),
            rationale=str(design.get("rationale") or ""),
            source=str(design.get("source") or "cache"),
            schema_version=3,
        )
    except Exception:
        return None


def save_cached(path: Path, design: GeminiDesign, layout_context: dict[str, Any]) -> None:
    payload = {
        "design": design.to_dict(),
        "layout_context": layout_context,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def refine_hook(
    *,
    creator: str,
    title: str,
    current_hook: str,
    cache_path: Path,
    reference_path: Path,
    enabled: bool,
    model: str,
    temperature: float,
    max_lines: int,
    min_chars: int,
    max_chars: int,
    layout_context: dict[str, Any],
    subtitle_sample: str = "",
) -> GeminiDesign:
    cached = load_cached(cache_path)
    if cached is not None:
        return cached

    fallback = fallback_design(current_hook, title, max_chars)
    api_key = os.getenv("GEMINI_API_KEY")

    if not enabled or genai is None or types is None or not api_key:
        save_cached(cache_path, fallback, layout_context)
        return fallback

    prompt = f"""
You are the art director and news-headline editor for an Indonesian short-form vertical video.

A PNG image is attached as the visual layout reference. Study its composition:
- portrait 1080x1920
- upper-right portrait/decorative subject occupies visual space
- headline belongs primarily in the upper-left paper area
- the middle is reserved for the video window
- lower area contains decorative artwork
- the layout should feel filled and intentional, not sparse

Return ONLY valid JSON:
{{
  "hook": "string",
  "hook_lines": 1 or 2,
  "emphasis": "strong" | "medium" | "soft",
  "density": "full" | "balanced" | "compact",
  "rationale": "brief string"
}}

HEADLINE RULES:
- Write like a concise news headline, not advertising copy.
- Preserve the actual meaning and facts from the supplied material.
- Preserve useful context: subject + event + action/consequence/important number when available.
- Do NOT reduce a meaningful story to a tiny phrase.
- Target approximately {min_chars}–{max_chars} characters.
- Maximum {max_lines} lines.
- Remove spoken filler, repetition, and conversational clutter.
- Avoid unsupported sensationalism: do not invent "viral", "heboh", "langsung", "geger",
  "drama", "terbongkar", etc. unless supported by the source.
- Names and monetary amounts are valuable when they are explicitly supported.
- Prefer natural Indonesian newsroom/headline language.
- Do not repeat the subtitle verbatim.
- The goal is a visually substantial headline that fits the provided layout.

CONTENT:
Creator: {creator}
Video title: {title}
Current hook: {current_hook}
Subtitle sample: {subtitle_sample}

LAYOUT CONSTRAINTS:
{json.dumps(layout_context, ensure_ascii=False)}
""".strip()

    try:
        image_bytes = reference_path.read_bytes()
        mime = "image/png"
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model,
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type=mime),
                prompt,
            ],
            config=types.GenerateContentConfig(
                temperature=temperature,
                response_mime_type="application/json",
                max_output_tokens=350,
            ),
        )
        data = _extract_json(response.text)
        hook = _clean_hook(str(data.get("hook") or ""), max_chars)
        if not hook:
            raise ValueError("Gemini returned empty hook")
        design = GeminiDesign(
            hook=hook,
            hook_lines=1 if int(data.get("hook_lines") or 2) == 1 else 2,
            emphasis=str(data.get("emphasis") or "strong"),
            density=str(data.get("density") or "balanced"),
            rationale=str(data.get("rationale") or "").strip(),
            source="gemini",
        )
    except Exception as exc:
        design = fallback
        design.rationale = f"Gemini fallback: {type(exc).__name__}"

    save_cached(cache_path, design, layout_context)
    return design
