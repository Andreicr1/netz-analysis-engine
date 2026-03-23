"""
CSP configuration tests — prevent nonce/inline regressions.

SvelteKit's CSP config injects nonces into script tags. Per CSP3 spec,
when a nonce is present, 'unsafe-inline' is IGNORED by the browser.
This breaks Clerk, which injects inline scripts without nonces.

Solution: CSP is set via static _headers files (Cloudflare Pages),
NOT via SvelteKit csp config. These tests enforce that contract.
"""
from __future__ import annotations

import json
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

        # Must not have csp directives (mode: "auto"|"hash"|"nonce" all inject nonces)
        assert "mode:" not in content or "mode: " not in content.replace("// ", ""), (
            f"frontends/{frontend}/svelte.config.js contains CSP mode config. "
            "Remove it — CSP must be set via static/_headers, not SvelteKit. "
            "SvelteKit injects nonces that disable unsafe-inline (CSP3 spec)."
        )


class TestCloudflareHeadersExist:
    """Each frontend must have a _headers file with CSP."""

    @pytest.mark.parametrize("frontend", FRONTENDS)
    def test_headers_file_exists(self, frontend: str):
        headers_path = REPO_ROOT / "frontends" / frontend / "static" / "_headers"
        assert headers_path.exists(), (
            f"Missing frontends/{frontend}/static/_headers. "
            "CSP must be set via this file for Cloudflare Pages."
        )

    @pytest.mark.parametrize("frontend", FRONTENDS)
    def test_headers_has_csp(self, frontend: str):
        headers_path = REPO_ROOT / "frontends" / frontend / "static" / "_headers"
        content = headers_path.read_text(encoding="utf-8")
        assert "Content-Security-Policy:" in content, (
            f"frontends/{frontend}/static/_headers missing Content-Security-Policy"
        )

    @pytest.mark.parametrize("frontend", FRONTENDS)
    def test_csp_allows_clerk_inline(self, frontend: str):
        """Clerk requires unsafe-inline + *.clerk.com in script-src."""
        headers_path = REPO_ROOT / "frontends" / frontend / "static" / "_headers"
        content = headers_path.read_text(encoding="utf-8")

        # Extract CSP line
        csp_line = ""
        for line in content.splitlines():
            if "Content-Security-Policy:" in line:
                csp_line = line.strip()
                break

        assert "'unsafe-inline'" in csp_line, (
            f"frontends/{frontend} CSP missing 'unsafe-inline' in script-src — "
            "Clerk injects inline scripts that require this."
        )
        assert "https://*.clerk.com" in csp_line, (
            f"frontends/{frontend} CSP missing https://*.clerk.com — "
            "Clerk loads scripts from this domain."
        )

    @pytest.mark.parametrize("frontend", FRONTENDS)
    def test_csp_has_no_nonce(self, frontend: str):
        """Nonces in CSP disable unsafe-inline per CSP3 spec."""
        headers_path = REPO_ROOT / "frontends" / frontend / "static" / "_headers"
        content = headers_path.read_text(encoding="utf-8")
        assert "'nonce-" not in content, (
            f"frontends/{frontend} _headers contains a nonce. "
            "Nonces disable unsafe-inline per CSP3 spec, breaking Clerk."
        )

    @pytest.mark.parametrize("frontend", FRONTENDS)
    def test_security_headers_present(self, frontend: str):
        """Basic security headers must be set."""
        headers_path = REPO_ROOT / "frontends" / frontend / "static" / "_headers"
        content = headers_path.read_text(encoding="utf-8")

        assert "X-Frame-Options:" in content
        assert "X-Content-Type-Options:" in content
        assert "Referrer-Policy:" in content


class TestHeadersConsistency:
    """All frontends must have identical security headers."""

    def test_all_frontends_have_same_csp(self):
        csp_lines = {}
        for frontend in FRONTENDS:
            headers_path = REPO_ROOT / "frontends" / frontend / "static" / "_headers"
            for line in headers_path.read_text(encoding="utf-8").splitlines():
                if "Content-Security-Policy:" in line:
                    csp_lines[frontend] = line.strip()
                    break

        values = list(csp_lines.values())
        assert len(set(values)) == 1, (
            f"CSP headers differ across frontends:\n"
            + "\n".join(f"  {k}: {v}" for k, v in csp_lines.items())
        )
