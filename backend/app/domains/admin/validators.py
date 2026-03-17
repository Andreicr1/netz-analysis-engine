"""Branding validation — prevents CSS injection via admin config."""

from __future__ import annotations

import re

_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_CSS_INJECTION_RE = re.compile(r"[{}<>;]")

_CURATED_FONTS: frozenset[str] = frozenset({
    "Inter, system-ui, sans-serif",
    "'Inter Variable', Inter, system-ui, sans-serif",
    "'JetBrains Mono', monospace",
    "'IBM Plex Sans', system-ui, sans-serif",
    "'DM Sans', system-ui, sans-serif",
    "system-ui, sans-serif",
})

_COLOR_FIELDS: frozenset[str] = frozenset({
    "primary_color", "secondary_color", "accent_color", "light_color",
    "highlight_color", "surface_color", "surface_alt_color",
    "surface_elevated_color", "surface_inset_color",
    "border_color", "text_primary", "text_secondary", "text_muted",
})

_FONT_FIELDS: frozenset[str] = frozenset({"font_sans", "font_mono", "font_family"})

_TEXT_FIELDS: frozenset[str] = frozenset({
    "company_name", "tagline", "org_name", "org_slug",
    "report_header", "report_footer", "email_from_name",
})

_TEXT_MAX_LEN = 200


def validate_branding_tokens(data: dict) -> list[str]:
    """Validate branding config fields. Returns list of error messages."""
    errors: list[str] = []

    for key, value in data.items():
        if not isinstance(value, str):
            continue

        if key in _COLOR_FIELDS:
            if not _HEX_COLOR_RE.match(value):
                errors.append(f"{key}: must be 6-char hex color (e.g. #1B365D)")
        elif key in _FONT_FIELDS:
            if value not in _CURATED_FONTS:
                errors.append(f"{key}: must be one of the curated fonts")
        elif key in _TEXT_FIELDS:
            if len(value) > _TEXT_MAX_LEN:
                errors.append(f"{key}: must be {_TEXT_MAX_LEN} chars or fewer")
            if _CSS_INJECTION_RE.search(value):
                errors.append(f"{key}: contains forbidden characters")

    return errors


# Magic bytes for image validation
_MAGIC_BYTES: dict[str, list[bytes]] = {
    "image/png": [b"\x89PNG"],
    "image/jpeg": [b"\xff\xd8\xff"],
    "image/x-icon": [b"\x00\x00\x01\x00", b"\x00\x00\x02\x00"],
    "image/vnd.microsoft.icon": [b"\x00\x00\x01\x00", b"\x00\x00\x02\x00"],
}


def validate_image_magic_bytes(data: bytes, content_type: str) -> bool:
    """Validate image content matches declared type via magic bytes."""
    expected = _MAGIC_BYTES.get(content_type)
    if expected is None:
        return False
    return any(data.startswith(magic) for magic in expected)


def strip_exif(data: bytes) -> bytes:
    """Strip EXIF metadata from JPEG uploads. Returns original if not JPEG or Pillow unavailable."""
    if not data.startswith(b"\xff\xd8\xff"):
        return data
    try:
        from io import BytesIO

        from PIL import Image

        img = Image.open(BytesIO(data))
        clean = BytesIO()
        img.save(clean, format="JPEG", exif=b"")
        return clean.getvalue()
    except Exception:
        return data
