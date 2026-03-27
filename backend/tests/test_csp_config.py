"""CSP configuration tests — prevent nonce/inline regressions.

CSP is set via static/_headers (Cloudflare Pages) in each frontend, NOT via
SvelteKit csp config (which injects nonces that disable unsafe-inline).
SSR-level cspHook was removed because dual CSP headers cause nonce conflicts.

hooks.server.ts provides non-CSP security headers (X-Frame-Options, etc.)
via securityHeadersHook.

These tests enforce:
1. No CSP in svelte.config.js (prevents nonce injection)
2. _headers file has CSP with unsafe-inline + *.clerk.com
3. hooks.server.ts has securityHeadersHook in sequence
4. All frontends have consistent CSP
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTENDS = ["credit", "wealth", "admin"]


class TestSvelteConfigHasNoCsp:
    """SvelteKit must NOT set CSP — it injects nonces that break Clerk."""

    @pytest.mark.parametrize("frontend", FRONTENDS)
    def test_svelte_config_has_no_csp_block(self, frontend: str):
        config_path = REPO_ROOT / "frontends" / frontend / "svelte.config.js"
        assert config_path.exists(), f"Missing {config_path}"
        content = config_path.read_text(encoding="utf-8")
        assert "directives:" not in content, (
            f"frontends/{frontend}/svelte.config.js contains CSP directives. "
            "Remove it — CSP must be set via hooks.server.ts cspHook. "
            "SvelteKit CSP injects nonces that disable unsafe-inline (CSP3 spec)."
        )


class TestCspInHeaders:
    """CSP is set via static/_headers (Cloudflare Pages), not hooks.server.ts.

    SSR-level cspHook was removed from all frontends because dual CSP headers
    cause nonce/unsafe-inline conflicts: Cloudflare may inject nonces which
    per CSP3 spec disable unsafe-inline, blocking the FOUC prevention script.
    """

    @pytest.mark.parametrize("frontend", FRONTENDS)
    def test_headers_csp_has_unsafe_inline(self, frontend: str):
        headers_path = REPO_ROOT / "frontends" / frontend / "static" / "_headers"
        content = headers_path.read_text(encoding="utf-8")
        assert "'unsafe-inline'" in content, (
            f"frontends/{frontend} _headers CSP missing 'unsafe-inline'. "
            "Clerk and FOUC prevention script require inline execution."
        )

    @pytest.mark.parametrize("frontend", FRONTENDS)
    def test_headers_csp_has_clerk_domain(self, frontend: str):
        headers_path = REPO_ROOT / "frontends" / frontend / "static" / "_headers"
        content = headers_path.read_text(encoding="utf-8")
        assert "*.clerk.com" in content, (
            f"frontends/{frontend} _headers CSP missing *.clerk.com."
        )

    @pytest.mark.parametrize("frontend", FRONTENDS)
    def test_hooks_has_security_headers_hook(self, frontend: str):
        """hooks.server.ts must have securityHeadersHook in exported sequence()."""
        hooks_path = REPO_ROOT / "frontends" / frontend / "src" / "hooks.server.ts"
        assert hooks_path.exists(), f"Missing {hooks_path}"
        content = hooks_path.read_text(encoding="utf-8")
        import re
        export_match = re.search(r"export const handle.*=.*sequence\((.+)\);", content)
        assert export_match, f"frontends/{frontend} missing 'export const handle = sequence(...)'"
        assert "securityHeadersHook" in export_match.group(1), (
            f"frontends/{frontend} securityHeadersHook not in exported sequence()."
        )


class TestCloudflareHeadersFallback:
    """_headers files provide CSP fallback for static assets."""

    @pytest.mark.parametrize("frontend", FRONTENDS)
    def test_headers_file_exists(self, frontend: str):
        headers_path = REPO_ROOT / "frontends" / frontend / "static" / "_headers"
        assert headers_path.exists(), (
            f"Missing frontends/{frontend}/static/_headers (static asset fallback)."
        )

    @pytest.mark.parametrize("frontend", FRONTENDS)
    def test_headers_has_csp(self, frontend: str):
        headers_path = REPO_ROOT / "frontends" / frontend / "static" / "_headers"
        content = headers_path.read_text(encoding="utf-8")
        assert "Content-Security-Policy:" in content

    @pytest.mark.parametrize("frontend", FRONTENDS)
    def test_headers_has_no_nonce(self, frontend: str):
        headers_path = REPO_ROOT / "frontends" / frontend / "static" / "_headers"
        content = headers_path.read_text(encoding="utf-8")
        assert "'nonce-" not in content, (
            "Nonces in _headers disable unsafe-inline per CSP3 spec."
        )


class TestSecurityHeadersPresent:
    """All frontends must have security headers."""

    @pytest.mark.parametrize("frontend", FRONTENDS)
    def test_hooks_has_x_frame_options(self, frontend: str):
        hooks_path = REPO_ROOT / "frontends" / frontend / "src" / "hooks.server.ts"
        content = hooks_path.read_text(encoding="utf-8")
        assert "X-Frame-Options" in content

    @pytest.mark.parametrize("frontend", FRONTENDS)
    def test_hooks_has_x_content_type_options(self, frontend: str):
        hooks_path = REPO_ROOT / "frontends" / frontend / "src" / "hooks.server.ts"
        content = hooks_path.read_text(encoding="utf-8")
        assert "X-Content-Type-Options" in content

    @pytest.mark.parametrize("frontend", FRONTENDS)
    def test_hooks_has_referrer_policy(self, frontend: str):
        hooks_path = REPO_ROOT / "frontends" / frontend / "src" / "hooks.server.ts"
        content = hooks_path.read_text(encoding="utf-8")
        assert "Referrer-Policy" in content
