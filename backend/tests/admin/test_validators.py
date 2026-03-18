"""Tests for admin branding validators."""

from __future__ import annotations

from app.domains.admin.validators import (
    strip_exif,
    validate_branding_tokens,
    validate_image_magic_bytes,
)


class TestBrandingTokenValidation:
    """Test validate_branding_tokens()."""

    def test_valid_branding(self):
        data = {
            "primary_color": "#1B365D",
            "secondary_color": "#3A7BD5",
            "font_sans": "'Inter Variable', Inter, system-ui, sans-serif",
            "company_name": "Acme Corp",
        }
        errors = validate_branding_tokens(data)
        assert errors == []

    def test_invalid_hex_color(self):
        data = {"primary_color": "not-a-color"}
        errors = validate_branding_tokens(data)
        assert len(errors) == 1
        assert "hex color" in errors[0]

    def test_hex_with_alpha_rejected(self):
        """Only 6-char hex allowed, not 8-char with alpha."""
        data = {"primary_color": "#1B365DFF"}
        errors = validate_branding_tokens(data)
        assert len(errors) == 1

    def test_css_injection_in_color(self):
        data = {"primary_color": "#1B365D; background: url(evil)"}
        errors = validate_branding_tokens(data)
        assert len(errors) >= 1

    def test_invalid_font(self):
        data = {"font_sans": "Comic Sans MS"}
        errors = validate_branding_tokens(data)
        assert len(errors) == 1
        assert "curated" in errors[0]

    def test_css_injection_in_text(self):
        data = {"company_name": "Acme<script>alert(1)</script>"}
        errors = validate_branding_tokens(data)
        assert len(errors) >= 1
        assert "forbidden" in errors[0]

    def test_text_too_long(self):
        data = {"company_name": "A" * 201}
        errors = validate_branding_tokens(data)
        assert len(errors) == 1
        assert "200" in errors[0]

    def test_css_injection_braces(self):
        data = {"company_name": "evil{color:red}"}
        errors = validate_branding_tokens(data)
        assert len(errors) >= 1

    def test_css_injection_semicolon(self):
        data = {"company_name": "evil;color:red"}
        errors = validate_branding_tokens(data)
        assert len(errors) >= 1

    def test_unknown_fields_ignored(self):
        """Fields not in any known set are silently ignored."""
        data = {"unknown_field": "anything"}
        errors = validate_branding_tokens(data)
        assert errors == []

    def test_non_string_values_ignored(self):
        """Non-string values are skipped by the validator."""
        data = {"primary_color": 12345}
        errors = validate_branding_tokens(data)
        assert errors == []

    def test_multiple_errors(self):
        """Multiple invalid fields produce multiple errors."""
        data = {
            "primary_color": "bad",
            "font_sans": "Comic Sans",
            "company_name": "A" * 201,
        }
        errors = validate_branding_tokens(data)
        assert len(errors) == 3


class TestImageMagicBytes:
    """Test validate_image_magic_bytes()."""

    def test_valid_png(self):
        data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        assert validate_image_magic_bytes(data, "image/png") is True

    def test_valid_jpeg(self):
        data = b"\xff\xd8\xff\xe0" + b"\x00" * 100
        assert validate_image_magic_bytes(data, "image/jpeg") is True

    def test_valid_ico(self):
        data = b"\x00\x00\x01\x00" + b"\x00" * 100
        assert validate_image_magic_bytes(data, "image/x-icon") is True

    def test_valid_ico_cursor_variant(self):
        """ICO cursor variant (0x02) is also valid."""
        data = b"\x00\x00\x02\x00" + b"\x00" * 100
        assert validate_image_magic_bytes(data, "image/x-icon") is True

    def test_mismatched_type(self):
        """PNG data declared as JPEG should fail."""
        data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        assert validate_image_magic_bytes(data, "image/jpeg") is False

    def test_svg_rejected(self):
        """SVG is not in the allowed types."""
        data = b"<svg xmlns="
        assert validate_image_magic_bytes(data, "image/svg+xml") is False

    def test_empty_data(self):
        assert validate_image_magic_bytes(b"", "image/png") is False

    def test_random_bytes(self):
        data = b"\x00\x01\x02\x03\x04\x05"
        assert validate_image_magic_bytes(data, "image/png") is False

    def test_webp_rejected(self):
        """WebP is not in the allowed types."""
        data = b"RIFF\x00\x00\x00\x00WEBP"
        assert validate_image_magic_bytes(data, "image/webp") is False


class TestStripExif:
    """Test strip_exif()."""

    def test_non_jpeg_passthrough(self):
        """Non-JPEG data passes through unchanged."""
        data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        assert strip_exif(data) == data

    def test_empty_passthrough(self):
        assert strip_exif(b"") == b""

    def test_non_image_passthrough(self):
        """Random bytes pass through unchanged."""
        data = b"hello world this is not an image"
        assert strip_exif(data) == data
