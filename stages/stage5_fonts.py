# ============================================================
# STAGE 5 V3 — DESIGN GUARDRAILS
# Gemini is the art director. Python enforces safe geometry.
# Subtitle and Hook line spacing are intentionally frozen.
# ============================================================

# ---------- FONT FILES ----------
CREATOR_FONT = "title.ttf"
HOOK_FONT = "title.ttf"
SUBTITLE_FONT = "subtitle.ttf"

# ---------- CREATOR GUARDRAILS ----------
CREATOR_MIN_SIZE = 80
CREATOR_MAX_SIZE = 150

# ---------- HOOK GUARDRAILS ----------
HOOK_MIN_SIZE = 44
HOOK_MAX_SIZE = 86
HOOK_MAX_LINES = 2
HOOK_LINE_SPACING = -50
HOOK_SHADOW = 4
HOOK_BORDER = 6

# ---------- SUBTITLE (FROZEN) ----------
SUBTITLE_SIZE = 80
SUBTITLE_MAX_WIDTH = 960
SUBTITLE_Y = 1240
SUBTITLE_BORDER = 6
SUBTITLE_SHADOW = 3

SUBTITLE_INACTIVE_SCALE = 0.80
SUBTITLE_ACTIVE_SCALE = 1.00
SUBTITLE_POP_DURATION = 0.18

SUBTITLE_NORMAL_COLOR = "&H00FFFFFF"
SUBTITLE_ACTIVE_COLOR = "&H0000A5FF"

# ---------- CREATOR STYLE ----------
CREATOR_SHADOW = 4
CREATOR_BORDER = 7

# ---------- REFERENCE LAYOUT ----------
# These are guardrails derived from FRAME KDM.png:
# top-left text area, with the upper-right portrait kept clear.
LAYOUT_REFERENCE = "assets/stage5_layout_reference.png"
HEADLINE_LEFT = 45
HEADLINE_RIGHT = 665
HEADLINE_TOP = 55
HEADLINE_BOTTOM = 520

# ---------- GEMINI ----------
GEMINI_DESIGN_ENABLED = True
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_TEMPERATURE = 0.35
GEMINI_HOOK_MAX_LINES = 2
GEMINI_HOOK_MIN_CHARS = 42
GEMINI_HOOK_MAX_CHARS = 72

# ---------- LEGACY COMPATIBILITY ----------
CREATOR_SIZE = 130
CREATOR_X = HEADLINE_LEFT
CREATOR_Y = HEADLINE_TOP
HOOK_SIZE = 60
HOOK_X = HEADLINE_LEFT
HOOK_Y = 250
HOOK_MAX_CHARS = 34
