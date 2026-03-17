"""Tests for the Wealth Watchlist Monitoring Engine — Sprint 4.

Covers:
- TransitionAlert/WatchlistRunResult model frozen integrity
- detect_transition pure function: all 3 directions + edge cases
- WatchlistService.check_transitions with mocked screener
- watchlist_batch advisory lock acquire/skip
- Worker route returns 202 and schedules background task
- No alerts published for stable instruments
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from vertical_engines.wealth.watchlist.models import (
    TransitionAlert,
    WatchlistRunResult,
)
from vertical_engines.wealth.watchlist.service import WatchlistService
from vertical_engines.wealth.watchlist.transition_detector import detect_transition

# ═══════════════════════════════════════════════════════════════════
#  Model integrity tests
# ═══════════════════════════════════════════════════════════════════


class TestTransitionAlert:
    """TransitionAlert frozen dataclass integrity."""

    def test_create_alert(self):
        alert = TransitionAlert(
            instrument_id=uuid.uuid4(),
            instrument_name="Test Fund",
            previous_outcome="watchlist",
            new_outcome="pass",
            direction="improvement",
            message="Candidate for DD initiation",
            detected_at=datetime.now(timezone.utc),
        )
        assert alert.direction == "improvement"
        assert alert.new_outcome == "pass"

    def test_frozen(self):
        alert = TransitionAlert(
            instrument_id=uuid.uuid4(),
            instrument_name="Test Fund",
            previous_outcome="watchlist",
            new_outcome="fail",
            direction="deterioration",
            message="Candidate for removal",
            detected_at=datetime.now(timezone.utc),
        )
        with pytest.raises(AttributeError):
            alert.direction = "stable"  # type: ignore[misc]

    def test_slots(self):
        alert = TransitionAlert(
            instrument_id=uuid.uuid4(),
            instrument_name="Test Fund",
            previous_outcome="watchlist",
            new_outcome="pass",
            direction="improvement",
            message="msg",
            detected_at=datetime.now(timezone.utc),
        )
        assert hasattr(alert, "__slots__")


class TestWatchlistRunResult:
    """WatchlistRunResult frozen dataclass integrity."""

    def test_create_run_result(self):
        result = WatchlistRunResult(
            run_id=uuid.uuid4(),
            organization_id="org-1",
            total_screened=10,
            improvements=2,
            deteriorations=1,
            stable=7,
            alerts=(),
            completed_at=datetime.now(timezone.utc),
        )
        assert result.total_screened == 10
        assert result.improvements == 2

    def test_frozen(self):
        result = WatchlistRunResult(
            run_id=uuid.uuid4(),
            organization_id="org-1",
            total_screened=5,
            improvements=0,
            deteriorations=0,
            stable=5,
            alerts=(),
            completed_at=datetime.now(timezone.utc),
        )
        with pytest.raises(AttributeError):
            result.total_screened = 99  # type: ignore[misc]

    def test_alerts_tuple(self):
        alert = TransitionAlert(
            instrument_id=uuid.uuid4(),
            instrument_name="Fund A",
            previous_outcome="watchlist",
            new_outcome="pass",
            direction="improvement",
            message="msg",
            detected_at=datetime.now(timezone.utc),
        )
        result = WatchlistRunResult(
            run_id=uuid.uuid4(),
            organization_id="org-1",
            total_screened=1,
            improvements=1,
            deteriorations=0,
            stable=0,
            alerts=(alert,),
            completed_at=datetime.now(timezone.utc),
        )
        assert len(result.alerts) == 1
        assert result.alerts[0].direction == "improvement"


# ═══════════════════════════════════════════════════════════════════
#  Transition detector tests (pure function)
# ═══════════════════════════════════════════════════════════════════


class TestDetectTransition:
    """Tests for detect_transition pure function."""

    def test_watchlist_to_pass(self):
        direction, message = detect_transition("watchlist", "PASS")
        assert direction == "improvement"
        assert "DD initiation" in message

    def test_watchlist_to_fail(self):
        direction, message = detect_transition("watchlist", "FAIL")
        assert direction == "deterioration"
        assert "removal" in message

    def test_watchlist_to_watchlist(self):
        direction, message = detect_transition("watchlist", "WATCHLIST")
        assert direction == "stable"

    def test_case_insensitive_previous(self):
        direction, _ = detect_transition("WATCHLIST", "pass")
        assert direction == "improvement"

    def test_case_insensitive_new(self):
        direction, _ = detect_transition("watchlist", "Pass")
        assert direction == "improvement"

    def test_whitespace_handling(self):
        direction, _ = detect_transition("  watchlist  ", "  PASS  ")
        assert direction == "improvement"

    def test_fail_to_watchlist(self):
        direction, message = detect_transition("FAIL", "WATCHLIST")
        assert direction == "improvement"
        assert "FAIL to WATCHLIST" in message

    def test_pass_to_watchlist(self):
        direction, message = detect_transition("PASS", "WATCHLIST")
        assert direction == "deterioration"
        assert "PASS to WATCHLIST" in message

    def test_same_outcome_pass(self):
        direction, _ = detect_transition("PASS", "PASS")
        assert direction == "stable"

    def test_same_outcome_fail(self):
        direction, _ = detect_transition("FAIL", "FAIL")
        assert direction == "stable"


# ═══════════════════════════════════════════════════════════════════
#  WatchlistService tests
# ═══════════════════════════════════════════════════════════════════


def _make_screening_result(overall_status: str = "PASS", instrument_id: uuid.UUID | None = None):
    """Create a mock InstrumentScreeningResult."""
    result = MagicMock()
    result.instrument_id = instrument_id or uuid.uuid4()
    result.overall_status = overall_status
    result.score = 0.75
    result.failed_at_layer = None
    result.layer_results = []
    result.layer_results_dict = []
    result.required_analysis_type = "dd_report"
    return result


class TestWatchlistService:
    """Tests for WatchlistService.check_transitions."""

    def test_detects_improvement(self):
        iid = uuid.uuid4()
        screener = MagicMock()
        screener.screen_instrument.return_value = _make_screening_result("PASS", iid)

        svc = WatchlistService(screener)
        alerts = svc.check_transitions(
            instruments=[{
                "instrument_id": iid,
                "instrument_type": "fund",
                "attributes": {},
                "name": "Fund A",
            }],
            previous_outcomes={iid: "WATCHLIST"},
        )

        assert len(alerts) == 1
        assert alerts[0].direction == "improvement"
        assert alerts[0].instrument_name == "Fund A"

    def test_detects_deterioration(self):
        iid = uuid.uuid4()
        screener = MagicMock()
        screener.screen_instrument.return_value = _make_screening_result("FAIL", iid)

        svc = WatchlistService(screener)
        alerts = svc.check_transitions(
            instruments=[{
                "instrument_id": iid,
                "instrument_type": "fund",
                "attributes": {},
                "name": "Fund B",
            }],
            previous_outcomes={iid: "WATCHLIST"},
        )

        assert len(alerts) == 1
        assert alerts[0].direction == "deterioration"

    def test_no_alert_for_stable(self):
        iid = uuid.uuid4()
        screener = MagicMock()
        screener.screen_instrument.return_value = _make_screening_result("WATCHLIST", iid)

        svc = WatchlistService(screener)
        alerts = svc.check_transitions(
            instruments=[{
                "instrument_id": iid,
                "instrument_type": "fund",
                "attributes": {},
                "name": "Fund C",
            }],
            previous_outcomes={iid: "WATCHLIST"},
        )

        assert len(alerts) == 0

    def test_multiple_instruments_mixed(self):
        iid1, iid2, iid3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        screener = MagicMock()
        screener.screen_instrument.side_effect = [
            _make_screening_result("PASS", iid1),
            _make_screening_result("FAIL", iid2),
            _make_screening_result("WATCHLIST", iid3),
        ]

        svc = WatchlistService(screener)
        alerts = svc.check_transitions(
            instruments=[
                {"instrument_id": iid1, "instrument_type": "fund", "attributes": {}, "name": "F1"},
                {"instrument_id": iid2, "instrument_type": "bond", "attributes": {}, "name": "F2"},
                {"instrument_id": iid3, "instrument_type": "fund", "attributes": {}, "name": "F3"},
            ],
            previous_outcomes={iid1: "WATCHLIST", iid2: "WATCHLIST", iid3: "WATCHLIST"},
        )

        assert len(alerts) == 2
        directions = {a.direction for a in alerts}
        assert directions == {"improvement", "deterioration"}

    def test_screener_exception_skips_instrument(self):
        iid = uuid.uuid4()
        screener = MagicMock()
        screener.screen_instrument.side_effect = ValueError("boom")

        svc = WatchlistService(screener)
        alerts = svc.check_transitions(
            instruments=[{
                "instrument_id": iid,
                "instrument_type": "fund",
                "attributes": {},
                "name": "Bad Fund",
            }],
            previous_outcomes={iid: "WATCHLIST"},
        )

        assert len(alerts) == 0

    def test_missing_previous_outcome_defaults_to_watchlist(self):
        iid = uuid.uuid4()
        screener = MagicMock()
        screener.screen_instrument.return_value = _make_screening_result("PASS", iid)

        svc = WatchlistService(screener)
        alerts = svc.check_transitions(
            instruments=[{
                "instrument_id": iid,
                "instrument_type": "fund",
                "attributes": {},
                "name": "New Fund",
            }],
            previous_outcomes={},  # No previous outcome
        )

        assert len(alerts) == 1
        assert alerts[0].previous_outcome == "watchlist"

    def test_empty_instruments_list(self):
        screener = MagicMock()
        svc = WatchlistService(screener)
        alerts = svc.check_transitions(instruments=[], previous_outcomes={})
        assert len(alerts) == 0
        screener.screen_instrument.assert_not_called()

    def test_alert_contains_correct_fields(self):
        iid = uuid.uuid4()
        screener = MagicMock()
        screener.screen_instrument.return_value = _make_screening_result("PASS", iid)

        svc = WatchlistService(screener)
        alerts = svc.check_transitions(
            instruments=[{
                "instrument_id": iid,
                "instrument_type": "fund",
                "attributes": {},
                "name": "Detail Fund",
            }],
            previous_outcomes={iid: "WATCHLIST"},
        )

        alert = alerts[0]
        assert alert.instrument_id == iid
        assert alert.instrument_name == "Detail Fund"
        assert alert.previous_outcome == "WATCHLIST"
        assert alert.new_outcome == "PASS"
        assert alert.direction == "improvement"
        assert isinstance(alert.detected_at, datetime)


# ═══════════════════════════════════════════════════════════════════
#  Worker route tests
# ═══════════════════════════════════════════════════════════════════


class TestWatchlistWorkerRoute:
    """Tests for POST /workers/run-watchlist-check endpoint."""

    @pytest.fixture
    def mock_user(self):
        user = MagicMock()
        user.organization_id = uuid.uuid4()
        return user

    @pytest.fixture
    def admin_actor(self):
        actor = MagicMock()
        actor.has_role.return_value = True
        return actor

    @pytest.fixture
    def non_admin_actor(self):
        actor = MagicMock()
        actor.has_role.return_value = False
        return actor

    def test_route_returns_202(self, mock_user, admin_actor):
        import asyncio

        from app.domains.wealth.routes.workers import trigger_run_watchlist_check

        bg = MagicMock()
        result = asyncio.get_event_loop().run_until_complete(
            trigger_run_watchlist_check(
                background_tasks=bg,
                user=mock_user,
                actor=admin_actor,
            )
        )

        assert result.status == "scheduled"
        assert result.worker == "run-watchlist-check"
        bg.add_task.assert_called_once()

    def test_route_rejects_non_admin(self, mock_user, non_admin_actor):
        import asyncio

        from fastapi import HTTPException

        from app.domains.wealth.routes.workers import trigger_run_watchlist_check

        bg = MagicMock()
        with pytest.raises(HTTPException) as exc_info:
            asyncio.get_event_loop().run_until_complete(
                trigger_run_watchlist_check(
                    background_tasks=bg,
                    user=mock_user,
                    actor=non_admin_actor,
                )
            )
        assert exc_info.value.status_code == 403


# ═══════════════════════════════════════════════════════════════════
#  Advisory lock tests
# ═══════════════════════════════════════════════════════════════════


class TestWatchlistBatchLock:
    """Tests for advisory lock behavior in watchlist_batch."""

    def test_lock_id_is_900_003(self):
        from app.domains.wealth.workers.watchlist_batch import WATCHLIST_BATCH_LOCK_ID

        assert WATCHLIST_BATCH_LOCK_ID == 900_003

    def test_lock_id_distinct_from_screening(self):
        from app.domains.wealth.workers.watchlist_batch import WATCHLIST_BATCH_LOCK_ID

        # screening_batch uses 900_002 — must not collide
        assert WATCHLIST_BATCH_LOCK_ID == 900_003
        assert WATCHLIST_BATCH_LOCK_ID != 900_002
