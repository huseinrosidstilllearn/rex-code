"""
rex.tui.theme
===========
Professional emerald color system for Rex Code Native TUI.
Supports preset themes + custom accent colors persisted in config.json.
"""

from __future__ import annotations
from typing import Literal
from dataclasses import dataclass
from pathlib import Path
import json

from rex.config import load_config, save_config

# ──────────────────────────────────────────────────────────────────────
# Design tokens (base = zinc neutrals, accent = emerald scale)
# ──────────────────────────────────────────────────────────────────────

ZINC = {
    950: "#09090B",
    900: "#18181B",
    800: "#27272A",
    700: "#3F3F46",
    600: "#52525B",
    500: "#71717A",
    400: "#A1A1AA",
    300: "#D4D4D8",
    200: "#E4E4E7",
    100: "#F4F4F5",
    50:  "#FAFAFA",
}

EMERALD = {
    "bg":      "#022C22",  # deep forest - banner background
    "subtle":  "#0A3D2E",  # surface panel
    "dim":     "#166534",  # dim text, borders
    "mid":     "#16A34A",  # secondary borders
    "primary": "#22C55E",  # BRAND - status bar, prompt, headings
    "bright":  "#4ADE80",  # streaming text, highlights
    "pale":    "#86EFAC",  # selection, subtle emphasis
}

# Built-in presets
@dataclass(frozen=True)
class AccentScale:
    bg: str
    subtle: str
    dim: str
    mid: str
    primary: str
    bright: str
    pale: str

    def to_css(self) -> dict[str, str]:
        """Return CSS custom properties for Textual."""
        return {
            "$rex-bg": self.bg,
            "$rex-subtle": self.subtle,
            "$rex-dim": self.dim,
            "$rex-mid": self.mid,
            "$rex-primary": self.primary,
            "$rex-bright": self.bright,
            "$rex-pale": self.pale,
        }
PRESETS: dict[str, AccentScale] = {
    "rex": AccentScale(**EMERALD),                     # Default emerald
    "mono": AccentScale(                               # Pure B/W
        bg=ZINC[950], subtle=ZINC[900], dim=ZINC[700],
        mid=ZINC[600], primary=ZINC[300], bright=ZINC[100], pale=ZINC[200]
    ),
    "amber": AccentScale(                              # Warm amber
        bg="#2E1A00", subtle="#452A00", dim="#854D0E",
        mid="#CA8A04", primary="#EAB308", bright="#FDE047", pale="#FEF08A"
    ),
    "cyan": AccentScale(                               # Cool cyan
        bg="#052E3B", subtle="#0D4C5C", dim="#155E75",
        mid="#06B6D4", primary="#22D3EE", bright="#67E8F9", pale="#A5F3FC"
    ),
    "violet": AccentScale(                             # Violet/purple
        bg="#2E1A47", subtle="#3D1E5E", dim="#6D28D9",
        mid="#A855F7", primary="#C084FC", bright="#D8B4FE", pale="#E9D5FF"
    ),
    "rose": AccentScale(                               # Rose/red
        bg="#470D1D", subtle="#6D1628", dim="#BE185D",
        mid="#E11D48", primary="#F43F5E", bright="#FDA4AF", pale="#FEC6D6"
    ),
}

DEFAULT_PRESET = "rex"
CUSTOM_KEY = "custom_accent"  # stored in config.json as hex string

# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

def _rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{r:02X}{g:02X}{b:02X}"

def _lerp_color(a: str, b: str, t: float) -> str:
    """Linear interpolation between two hex colors."""
    r1, g1, b1 = _hex_to_rgb(a)
    r2, g2, b2 = _hex_to_rgb(b)
    r = int(r1 + (r2 - r1) * t)
    g = int(g1 + (g2 - g1) * t)
    b = int(b1 + (b2 - b1) * t)
    return _rgb_to_hex(r, g, b)

def _generate_scale_from_primary(primary: str) -> AccentScale:
    """
    Generate a harmonious emerald-like scale from a single custom primary color.
    We keep the ZINC neutrals for bg/subtle, and derive dim/mid/bright/pale
    by mixing the primary with black/white.
    """
    # Use zinc for base backgrounds (always neutral)
    bg = ZINC[950]
    subtle = ZINC[900]

    # Derive scale from custom primary
    dim = _lerp_color(primary, "#000000", 0.55)    # darker
    mid = _lerp_color(primary, "#000000", 0.25)    # slightly darker
    bright = _lerp_color(primary, "#FFFFFF", 0.35) # lighter
    pale = _lerp_color(primary, "#FFFFFF", 0.65)   # much lighter

    return AccentScale(
        bg=bg, subtle=subtle, dim=dim, mid=mid,
        primary=primary, bright=bright, pale=pale
    )

def get_active_theme() -> AccentScale:
    """Get the currently active theme (preset or custom)."""
    cfg = load_config()
    preset = cfg.get("tui_theme", DEFAULT_PRESET)

    # Custom accent stored as hex
    if preset == "custom":
        custom_hex = cfg.get(CUSTOM_KEY)
        if custom_hex and custom_hex.startswith("#") and len(custom_hex) == 7:
            return _generate_scale_from_primary(custom_hex)
        # Fallback to default if invalid
        return PRESETS[DEFAULT_PRESET]

    return PRESETS.get(preset, PRESETS[DEFAULT_PRESET])

def set_theme(preset: str) -> None:
    """Set active theme preset. Use 'custom' with set_custom_accent() for custom colors."""
    if preset not in PRESETS and preset != "custom":
        raise ValueError(f"Unknown theme preset: {preset}. Available: {list(PRESETS.keys()) + ['custom']}")
    cfg = load_config()
    cfg["tui_theme"] = preset
    save_config(cfg)

def set_custom_accent(hex_color: str) -> None:
    """Set a custom accent color (hex format #RRGGBB). Automatically switches to 'custom' theme."""
    if not (hex_color.startswith("#") and len(hex_color) == 7):
        raise ValueError("Color must be in #RRGGBB format")
    # Validate hex
    try:
        int(hex_color[1:], 16)
    except ValueError:
        raise ValueError("Invalid hex color")
    cfg = load_config()
    cfg["tui_theme"] = "custom"
    cfg[CUSTOM_KEY] = hex_color.upper()
    save_config(cfg)

def get_theme_css() -> str:
    """Generate Textual CSS with current theme's CSS custom properties.

    Variables are defined on a top-level rule (before Screen) so that
    every widget in the app can reference them. Defining them inside
    `Screen { ... }` only scopes them to Screen's own property block,
    not to the app CSS that uses `$rex-bg` etc.
    """
    theme = get_active_theme()
    props = theme.to_css()
    lines = [f"  {k}: {v};" for k, v in props.items()]
    # Use a wildcard rule at the top level. Variables declared here are
    # accessible to every widget that descends from App (which is all of them).
    return "App {\n" + "\n".join(lines) + "\n}"

def list_presets() -> list[str]:
    return list(PRESETS.keys()) + ["custom"]
