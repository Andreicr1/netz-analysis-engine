"""Tests for admin asset upload validation — size, content type, magic bytes."""

from __future__ import annotations

from app.domains.admin.routes.asset_admin import (
    _ALLOWED_CONTENT_TYPES,
    _MAX_ASSET_SIZE,
    _VALID_ASSET_TYPES,
    _detect_content_type,
)


class TestAssetTypeValidation:
    def test_valid_asset_types(self):
        assert "logo_light" in _VALID_ASSET_TYPES
        assert "logo_dark" in _VALID_ASSET_TYPES
        assert "favicon" in _VALID_ASSET_TYPES

    def test_svg_not_allowed(self):
        assert "image/svg+xml" not in _ALLOWED_CONTENT_TYPES

    def test_max_size_is_512kb(self):
        assert _MAX_ASSET_SIZE == 512 * 1024


class TestMagicByteDetection:
    def test_png_detection(self):
        png_header = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        assert _detect_content_type(png_header) == "image/png"

    def test_jpeg_detection(self):
        jpeg_header = b"\xff\xd8\xff\xe0" + b"\x00" * 100
        assert _detect_content_type(jpeg_header) == "image/jpeg"

    def test_ico_detection(self):
        ico_header = b"\x00\x00\x01\x00" + b"\x00" * 100
        assert _detect_content_type(ico_header) == "image/x-icon"

    def test_svg_not_detected(self):
        svg_header = b"<svg xmlns='http://www.w3.org/2000/svg'>"
        assert _detect_content_type(svg_header) is None

    def test_unknown_format_returns_none(self):
        random_bytes = b"\x01\x02\x03\x04\x05"
        assert _detect_content_type(random_bytes) is None

    def test_empty_bytes_returns_none(self):
        assert _detect_content_type(b"") is None

    def test_short_bytes_returns_none(self):
        assert _detect_content_type(b"\x89") is None
