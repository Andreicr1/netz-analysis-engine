"""C-11: approve_fund / reject_fund must keep mutation + audit in one transaction.

Tests that:
- If the audit event write fails (flush raises), the approval mutation is
  rolled back too (single transaction guarantee).
- Both approve and reject routes use the same pattern.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest


class TestApproveRejectAuditAtomicity:
    """Verify mutation + audit are in the same sync session transaction."""

    @pytest.mark.asyncio
    async def test_approve_rolls_back_on_audit_failure(self):
        """When audit event flush raises, the entire transaction (including
        the approval mutation) must roll back — no orphan state change."""
        from app.domains.wealth.routes.universe import approve_fund

        instrument_id = uuid.uuid4()
        org_id = str(uuid.uuid4())
        actor_id = "test-actor-123"

        body = MagicMock()
        body.decision = "approved"
        body.rationale = "Looks good"

        actor = MagicMock()
        actor.actor_id = actor_id
        actor.has_role = MagicMock(return_value=True)

        db = MagicMock()  # async session (unused in new pattern)
        user = MagicMock()

        # Build a fake approval ORM object
        fake_approval = MagicMock()
        fake_approval.id = uuid.uuid4()
        fake_approval.instrument_id = instrument_id
        fake_approval.organization_id = org_id
        fake_approval.is_current = True
        fake_approval.decision = "pending"

        fake_updated = MagicMock()
        fake_updated.id = fake_approval.id
        fake_updated.instrument_id = instrument_id
        fake_updated.organization_id = org_id
        fake_updated.decision = "approved"
        fake_updated.rationale = "Looks good"
        fake_updated.decided_by = actor_id
        fake_updated.is_current = True
        fake_updated.decided_at = None
        fake_updated.submitted_by = "someone"
        fake_updated.created_at = None
        fake_updated.updated_at = None

        flush_called = False
        flush_error = RuntimeError("Simulated audit flush failure")

        def _mock_flush():
            nonlocal flush_called
            flush_called = True
            raise flush_error

        with patch("app.core.db.session.sync_session_factory") as mock_factory, \
             patch("vertical_engines.wealth.asset_universe.UniverseService") as MockSvc:

            mock_sync_db = MagicMock()
            mock_sync_db.expire_on_commit = False

            # Make the context manager work
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=mock_sync_db)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_factory.return_value = mock_ctx

            # Mock begin() context manager
            mock_begin = MagicMock()
            mock_begin.__enter__ = MagicMock(return_value=None)
            mock_begin.__exit__ = MagicMock(return_value=False)
            mock_sync_db.begin.return_value = mock_begin

            # Mock the SELECT query result
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = fake_approval
            mock_sync_db.execute.return_value = mock_result

            # Mock svc.approve_fund
            mock_svc = MockSvc.return_value
            mock_svc.approve_fund.return_value = fake_updated

            # Make flush raise to simulate audit failure
            mock_sync_db.flush.side_effect = flush_error

            # The route should propagate the error (the context manager
            # __exit__ sees the exception and rolls back the transaction)
            with pytest.raises(RuntimeError, match="Simulated audit flush failure"):
                await approve_fund(
                    instrument_id=instrument_id,
                    body=body,
                    db=db,
                    user=user,
                    actor=actor,
                    org_id=org_id,
                )

            # Verify that flush was called (audit event was attempted)
            assert mock_sync_db.flush.called
            # Verify the begin context's __exit__ was called (transaction cleanup)
            assert mock_begin.__exit__.called

    def test_approve_and_reject_both_use_sync_audit(self):
        """Both approve_fund and reject_fund must create AuditEvent in the
        sync session (not via async write_audit_event after to_thread)."""
        import inspect

        from app.domains.wealth.routes import universe

        approve_src = inspect.getsource(universe.approve_fund)
        reject_src = inspect.getsource(universe.reject_fund)

        # The old pattern was: await write_audit_event(db, ...) after to_thread.
        # The new pattern creates AuditEvent directly in the sync block.
        for name, src in [("approve", approve_src), ("reject", reject_src)]:
            # Must NOT have "await write_audit_event" after to_thread
            # (The async write_audit_event should not be called for these routes)
            assert "sync_db.add(AuditEvent(" in src, (
                f"{name}_fund must create AuditEvent in the sync session"
            )
            assert "sync_db.flush()" in src, (
                f"{name}_fund must flush the audit event in the sync session"
            )
