"""Tests for Redis-based rate-limit middleware."""

from __future__ import annotations

from app.core.middleware.rate_limit import (
    _classify_endpoint,
    _extract_org_id_from_jwt_lightweight,
)

# ── Endpoint classification ──────────────────────────────────


class TestClassifyEndpoint:
    def test_health_exempt(self) -> None:
        assert _classify_endpoint("/health") is None
        assert _classify_endpoint("/api/health") is None

    def test_admin_exempt(self) -> None:
        assert _classify_endpoint("/api/v1/admin/configs") is None
        assert _classify_endpoint("/api/v1/admin/tenants") is None

    def test_standard_endpoints(self) -> None:
        assert _classify_endpoint("/api/v1/funds") == "standard"
        assert _classify_endpoint("/api/v1/portfolios") == "standard"

    def test_compute_heavy_ai(self) -> None:
        assert _classify_endpoint("/api/v1/ai/deep-review") == "compute"
        assert _classify_endpoint("/api/v1/ai/extraction") == "compute"

    def test_compute_heavy_dd_reports(self) -> None:
        assert _classify_endpoint("/api/v1/dd-reports/generate") == "compute"

    def test_compute_heavy_ic_memo(self) -> None:
        assert (
            _classify_endpoint(
                "/api/v1/funds/123/deals/456/ic-memo",
            )
            == "compute"
        )

    def test_compute_heavy_deep_review(self) -> None:
        assert (
            _classify_endpoint(
                "/api/v1/funds/123/deals/456/deep-review",
            )
            == "compute"
        )

    def test_compute_heavy_document_reviews(self) -> None:
        assert (
            _classify_endpoint(
                "/api/v1/funds/123/document-reviews",
            )
            == "compute"
        )


# ── Lightweight JWT parsing ──────────────────────────────────


class TestExtractOrgIdFromJwt:
    def test_valid_clerk_jwt_payload(self) -> None:
        """Simulate a Clerk JWT with o.id claim."""
        import base64
        import json

        payload = {"sub": "user_123", "o": {"id": "org_abc", "rol": "org:admin"}}
        encoded = base64.urlsafe_b64encode(
            json.dumps(payload).encode(),
        ).rstrip(b"=").decode()
        fake_jwt = f"header.{encoded}.signature"

        assert _extract_org_id_from_jwt_lightweight(fake_jwt) == "org_abc"

    def test_missing_org_claim(self) -> None:
        import base64
        import json

        payload = {"sub": "user_123"}
        encoded = base64.urlsafe_b64encode(
            json.dumps(payload).encode(),
        ).rstrip(b"=").decode()
        fake_jwt = f"header.{encoded}.signature"

        assert _extract_org_id_from_jwt_lightweight(fake_jwt) is None

    def test_invalid_jwt_format(self) -> None:
        assert _extract_org_id_from_jwt_lightweight("not-a-jwt") is None

    def test_corrupted_base64(self) -> None:
        assert _extract_org_id_from_jwt_lightweight("a.!!!.b") is None
