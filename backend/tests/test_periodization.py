"""
Unit tests for periodization (macrocycles, microcycles, planned sessions).

Covers:
- Block plan resolution (which block is week N in?)
- Methodology default plans (HWPO is 12 weeks)
- datetime utilities (snap_to_monday, week_bounds)
- Pydantic model validation
- API endpoints (macrocycle + planned_session CRUD)
"""
from datetime import date, timedelta, time
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from app.core.datetime_utils import snap_to_monday, week_bounds
from app.core.engine.periodization import (
    METHODOLOGY_BLOCK_PLANS,
    default_block_plan_for,
    next_block_after,
    resolve_block_and_week_in_block,
    total_weeks,
)
from app.models.training import (
    BlockPlanItem,
    BlockType,
    MacrocycleCreate,
    Methodology,
    PlannedSessionCreate,
    Shift,
    WorkoutType,
)


# ==========================================================
# datetime_utils
# ==========================================================

class TestDatetimeUtils:
    def test_snap_to_monday_from_any_weekday(self):
        # Wednesday 2026-04-22
        d = date(2026, 4, 22)
        assert snap_to_monday(d) == date(2026, 4, 20)

    def test_snap_to_monday_is_idempotent_on_monday(self):
        d = date(2026, 4, 20)
        assert snap_to_monday(d) == d

    def test_snap_to_monday_from_sunday(self):
        d = date(2026, 4, 26)  # Sunday
        assert snap_to_monday(d) == date(2026, 4, 20)

    def test_week_bounds_returns_mon_sun(self):
        mon, sun = week_bounds(date(2026, 4, 22))
        assert mon == date(2026, 4, 20)
        assert sun == date(2026, 4, 26)


# ==========================================================
# periodization helpers
# ==========================================================

class TestBlockPlans:
    def test_hwpo_default_plan_is_12_weeks(self):
        plan = METHODOLOGY_BLOCK_PLANS[Methodology.HWPO]
        assert total_weeks(plan) == 12

    def test_comptrain_default_plan_is_12_weeks(self):
        plan = METHODOLOGY_BLOCK_PLANS[Methodology.COMPTRAIN]
        assert total_weeks(plan) == 12

    def test_mayhem_default_plan_is_43_weeks(self):
        plan = METHODOLOGY_BLOCK_PLANS[Methodology.MAYHEM]
        assert total_weeks(plan) == 43

    def test_custom_default_plan_is_empty(self):
        assert METHODOLOGY_BLOCK_PLANS[Methodology.CUSTOM] == []

    def test_default_block_plan_returns_copy(self):
        a = default_block_plan_for(Methodology.HWPO)
        b = default_block_plan_for(Methodology.HWPO)
        assert a == b
        assert a is not b  # different instances

    def test_resolve_block_and_week_in_block_hwpo(self):
        plan = METHODOLOGY_BLOCK_PLANS[Methodology.HWPO]
        # Weeks 1-3 = accumulation
        assert resolve_block_and_week_in_block(plan, 1)[0] == BlockType.ACCUMULATION
        assert resolve_block_and_week_in_block(plan, 3) == (BlockType.ACCUMULATION, 3, 3)
        # Week 4 = deload (1 week)
        assert resolve_block_and_week_in_block(plan, 4) == (BlockType.DELOAD, 1, 1)
        # Weeks 5-7 = intensification (3 weeks, so week_in_block = 1..3)
        assert resolve_block_and_week_in_block(plan, 5) == (BlockType.INTENSIFICATION, 1, 3)
        assert resolve_block_and_week_in_block(plan, 7) == (BlockType.INTENSIFICATION, 3, 3)
        # Week 8 = deload
        assert resolve_block_and_week_in_block(plan, 8) == (BlockType.DELOAD, 1, 1)
        # Weeks 9-10 = realization
        assert resolve_block_and_week_in_block(plan, 9)[0] == BlockType.REALIZATION
        assert resolve_block_and_week_in_block(plan, 10)[0] == BlockType.REALIZATION
        # Week 11 = test
        assert resolve_block_and_week_in_block(plan, 11) == (BlockType.TEST, 1, 1)
        # Week 12 = transition
        assert resolve_block_and_week_in_block(plan, 12) == (BlockType.TRANSITION, 1, 1)

    def test_resolve_beyond_plan_returns_none(self):
        plan = METHODOLOGY_BLOCK_PLANS[Methodology.HWPO]
        assert resolve_block_and_week_in_block(plan, 13) == (None, None, None)

    def test_resolve_zero_or_negative_returns_none(self):
        plan = METHODOLOGY_BLOCK_PLANS[Methodology.HWPO]
        assert resolve_block_and_week_in_block(plan, 0) == (None, None, None)
        assert resolve_block_and_week_in_block(plan, -3) == (None, None, None)

    def test_next_block_after(self):
        plan = METHODOLOGY_BLOCK_PLANS[Methodology.HWPO]
        # In week 3 (accumulation), next should be deload
        nxt = next_block_after(plan, 3)
        assert nxt is not None
        assert nxt.type == BlockType.DELOAD
        # In the final block (transition, week 12), no next block
        assert next_block_after(plan, 12) is None


# ==========================================================
# Pydantic model validation
# ==========================================================

class TestPeriodizationModels:
    def test_block_plan_item_weeks_constraint(self):
        BlockPlanItem(type=BlockType.ACCUMULATION, weeks=4)  # ok
        with pytest.raises(ValidationError):
            BlockPlanItem(type=BlockType.ACCUMULATION, weeks=0)
        with pytest.raises(ValidationError):
            BlockPlanItem(type=BlockType.ACCUMULATION, weeks=20)

    def test_macrocycle_create_minimal(self):
        m = MacrocycleCreate(
            name="HWPO Cycle",
            methodology=Methodology.HWPO,
            start_date=date(2026, 4, 20),
        )
        assert m.block_plan is None  # server fills default
        assert m.methodology == Methodology.HWPO

    def test_macrocycle_create_with_custom_plan(self):
        m = MacrocycleCreate(
            name="Custom",
            methodology=Methodology.CUSTOM,
            start_date=date(2026, 4, 20),
            block_plan=[
                BlockPlanItem(type=BlockType.ACCUMULATION, weeks=2),
                BlockPlanItem(type=BlockType.DELOAD, weeks=1),
            ],
        )
        assert total_weeks(m.block_plan) == 3

    def test_planned_session_order_in_day_range(self):
        PlannedSessionCreate(
            date=date(2026, 4, 22),
            order_in_day=1,
            workout_type=WorkoutType.STRENGTH,
        )
        # 5 sessions allowed
        PlannedSessionCreate(
            date=date(2026, 4, 22),
            order_in_day=5,
            workout_type=WorkoutType.METCON,
        )
        with pytest.raises(ValidationError):
            PlannedSessionCreate(
                date=date(2026, 4, 22),
                order_in_day=6,
                workout_type=WorkoutType.METCON,
            )
        with pytest.raises(ValidationError):
            PlannedSessionCreate(
                date=date(2026, 4, 22),
                order_in_day=0,
                workout_type=WorkoutType.METCON,
            )

    def test_planned_session_duration_range(self):
        PlannedSessionCreate(
            date=date(2026, 4, 22), order_in_day=1,
            duration_minutes=240, workout_type=WorkoutType.MIXED,
        )
        with pytest.raises(ValidationError):
            PlannedSessionCreate(
                date=date(2026, 4, 22), order_in_day=1,
                duration_minutes=10, workout_type=WorkoutType.MIXED,
            )
        with pytest.raises(ValidationError):
            PlannedSessionCreate(
                date=date(2026, 4, 22), order_in_day=1,
                duration_minutes=300, workout_type=WorkoutType.MIXED,
            )

    def test_planned_session_accepts_shift_and_time(self):
        ps = PlannedSessionCreate(
            date=date(2026, 4, 22),
            order_in_day=2,
            shift=Shift.EVENING,
            start_time=time(18, 30),
            duration_minutes=60,
            workout_type=WorkoutType.METCON,
        )
        assert ps.shift == Shift.EVENING
        assert ps.start_time == time(18, 30)


# ==========================================================
# API endpoints
# ==========================================================

class TestMacrocycleEndpoints:
    @pytest.mark.asyncio
    async def test_create_macrocycle_hwpo_default(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        """Creating an HWPO macrocycle generates 12 microcycles."""
        resp = await authenticated_client.post(
            "/api/v1/schedule/macrocycles",
            json={
                "name": "HWPO Prep",
                "methodology": "hwpo",
                "start_date": "2026-04-22",  # Wednesday — should snap to Monday 04-20
                "goal": "Compete",
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["methodology"] == "hwpo"
        assert body["start_date"] == "2026-04-20"  # snapped to Monday
        # HWPO = 12 weeks
        assert len(body["microcycles"]) == 12
        # First microcycle spans Mon 20/04 to Sun 26/04
        assert body["microcycles"][0]["start_date"] == "2026-04-20"
        assert body["microcycles"][0]["end_date"] == "2026-04-26"
        assert body["microcycles"][0]["week_index_in_macro"] == 1
        # Block plan sums to 12
        assert sum(b["weeks"] for b in body["block_plan"]) == 12

    @pytest.mark.asyncio
    async def test_create_macrocycle_custom_requires_block_plan(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        resp = await authenticated_client.post(
            "/api/v1/schedule/macrocycles",
            json={
                "name": "Custom",
                "methodology": "custom",
                "start_date": "2026-04-20",
            },
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_create_macrocycle_with_custom_block_plan(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        resp = await authenticated_client.post(
            "/api/v1/schedule/macrocycles",
            json={
                "name": "Short custom",
                "methodology": "custom",
                "start_date": "2026-04-20",
                "block_plan": [
                    {"type": "accumulation", "weeks": 2},
                    {"type": "deload", "weeks": 1},
                ],
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert len(body["microcycles"]) == 3

    @pytest.mark.asyncio
    async def test_add_two_sessions_same_day(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        """Adding AM strength + PM metcon on the same day persists both."""
        # First create a macrocycle to get a microcycle
        create = await authenticated_client.post(
            "/api/v1/schedule/macrocycles",
            json={
                "name": "Two-a-day test",
                "methodology": "hwpo",
                "start_date": "2026-04-20",
            },
        )
        assert create.status_code == 201, create.text
        micro_id = create.json()["microcycles"][0]["id"]

        # Session 1: AM Strength
        r1 = await authenticated_client.post(
            f"/api/v1/schedule/microcycles/{micro_id}/sessions",
            json={
                "date": "2026-04-22",
                "order_in_day": 1,
                "shift": "morning",
                "start_time": "06:00",
                "duration_minutes": 60,
                "workout_type": "strength",
            },
        )
        assert r1.status_code == 201, r1.text

        # Session 2: PM MetCon same day
        r2 = await authenticated_client.post(
            f"/api/v1/schedule/microcycles/{micro_id}/sessions",
            json={
                "date": "2026-04-22",
                "order_in_day": 2,
                "shift": "evening",
                "start_time": "18:30",
                "duration_minutes": 45,
                "workout_type": "metcon",
            },
        )
        assert r2.status_code == 201, r2.text
        assert r1.json()["id"] != r2.json()["id"]
        assert r1.json()["order_in_day"] == 1
        assert r2.json()["order_in_day"] == 2

    @pytest.mark.asyncio
    async def test_add_session_outside_microcycle_rejects(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        """Session date must be inside the microcycle bounds."""
        create = await authenticated_client.post(
            "/api/v1/schedule/macrocycles",
            json={
                "name": "Boundary",
                "methodology": "hwpo",
                "start_date": "2026-04-20",
            },
        )
        micro_id = create.json()["microcycles"][0]["id"]
        # First micro is 04-20..04-26; 04-27 is outside
        bad = await authenticated_client.post(
            f"/api/v1/schedule/microcycles/{micro_id}/sessions",
            json={
                "date": "2026-04-27",
                "order_in_day": 1,
                "duration_minutes": 60,
                "workout_type": "strength",
            },
        )
        assert bad.status_code == 400

    @pytest.mark.asyncio
    async def test_microcycle_marks_planned_session_completed(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        """Completed workout on a planned day surfaces completed=true on the session."""
        from datetime import datetime

        from app.db.models import WorkoutSession as WorkoutSessionDB

        create = await authenticated_client.post(
            "/api/v1/schedule/macrocycles",
            json={"name": "Done week", "methodology": "hwpo", "start_date": "2026-04-20"},
        )
        assert create.status_code == 201, create.text
        micro_id = create.json()["microcycles"][0]["id"]

        listed = await authenticated_client.get(f"/api/v1/schedule/microcycles/{micro_id}")
        mon = next(s for s in listed.json()["sessions"] if s["date"] == "2026-04-20")
        assert mon["completed"] is False

        db_session.add(
            WorkoutSessionDB(
                user_id=seeded_user.id,
                planned_session_id=UUID(str(mon["id"])),
                workout_type="strength",
                started_at=datetime(2026, 4, 20, 8, 0, 0),
                completed_at=datetime(2026, 4, 20, 9, 0, 0),
            )
        )
        db_session.commit()

        refreshed = await authenticated_client.get(f"/api/v1/schedule/microcycles/{micro_id}")
        done = next(s for s in refreshed.json()["sessions"] if s["id"] == mon["id"])
        assert done["completed"] is True


# ==========================================================
# Swap planned sessions
# ==========================================================

class TestSwapPlannedSessions:
    """End-to-end tests for the drag-and-drop swap endpoint."""

    async def _create_macro(self, client: AsyncClient) -> str:
        resp = await client.post(
            "/api/v1/schedule/macrocycles",
            json={"name": "Swap test", "methodology": "hwpo", "start_date": "2026-04-20"},
        )
        assert resp.status_code == 201, resp.text
        return resp.json()["microcycles"][0]["id"]

    async def _list_sessions(self, client: AsyncClient, micro_id: str) -> list[dict]:
        resp = await client.get(f"/api/v1/schedule/microcycles/{micro_id}")
        assert resp.status_code == 200, resp.text
        return resp.json()["sessions"]

    @pytest.mark.asyncio
    async def test_swap_two_training_days(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        """Drag a training session from Monday onto another training session on Wednesday."""
        micro_id = await self._create_macro(authenticated_client)
        sessions = await self._list_sessions(authenticated_client, micro_id)
        # Default HWPO 5-day plan seeds Mon..Fri. Pick Mon (source) and Wed (target).
        mon = next(s for s in sessions if s["date"] == "2026-04-20")
        wed = next(s for s in sessions if s["date"] == "2026-04-22")

        resp = await authenticated_client.post(
            f"/api/v1/schedule/microcycles/{micro_id}/sessions/swap",
            json={"source_id": mon["id"], "target_date": "2026-04-22", "target_id": wed["id"]},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert len(body) == 2
        # Source is now on Wednesday, target moved back to Monday.
        src_after = next(b for b in body if b["id"] == mon["id"])
        tgt_after = next(b for b in body if b["id"] == wed["id"])
        assert src_after["date"] == "2026-04-22"
        assert tgt_after["date"] == "2026-04-20"

        # No row should be left parked at order_in_day=99.
        all_after = await self._list_sessions(authenticated_client, micro_id)
        assert all(s["order_in_day"] != 99 for s in all_after)

    @pytest.mark.asyncio
    async def test_swap_training_with_rest_day(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        """Drag a training session onto a rest-day marker (status=skipped)."""
        micro_id = await self._create_macro(authenticated_client)
        # Saturday (2026-04-25) is a rest day in the default HWPO 5-day seed —
        # add a rest marker explicitly so the swap has a target row.
        rest = await authenticated_client.post(
            f"/api/v1/schedule/microcycles/{micro_id}/sessions",
            json={
                "date": "2026-04-25",
                "order_in_day": 1,
                "shift": "morning",
                "duration_minutes": 15,
                "focus": "Descanso",
                "status": "skipped",
            },
        )
        assert rest.status_code == 201, rest.text
        rest_id = rest.json()["id"]

        sessions = await self._list_sessions(authenticated_client, micro_id)
        mon = next(s for s in sessions if s["date"] == "2026-04-20")

        resp = await authenticated_client.post(
            f"/api/v1/schedule/microcycles/{micro_id}/sessions/swap",
            json={"source_id": mon["id"], "target_date": "2026-04-25", "target_id": rest_id},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        src_after = next(b for b in body if b["id"] == mon["id"])
        tgt_after = next(b for b in body if b["id"] == rest_id)
        assert src_after["date"] == "2026-04-25"
        assert tgt_after["date"] == "2026-04-20"
        assert tgt_after["status"] == "skipped"

    @pytest.mark.asyncio
    async def test_move_to_empty_day(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        """Drop on an empty day moves the source there with order_in_day=1."""
        micro_id = await self._create_macro(authenticated_client)
        sessions = await self._list_sessions(authenticated_client, micro_id)
        mon = next(s for s in sessions if s["date"] == "2026-04-20")

        # 2026-04-26 (Sunday) has no session in the default 5-day plan.
        resp = await authenticated_client.post(
            f"/api/v1/schedule/microcycles/{micro_id}/sessions/swap",
            json={"source_id": mon["id"], "target_date": "2026-04-26"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert len(body) == 1
        assert body[0]["id"] == mon["id"]
        assert body[0]["date"] == "2026-04-26"
        assert body[0]["order_in_day"] == 1

    @pytest.mark.asyncio
    async def test_move_to_occupied_day_without_target_id_rejects(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        """Move-only path refuses if the target slot is already taken."""
        micro_id = await self._create_macro(authenticated_client)
        sessions = await self._list_sessions(authenticated_client, micro_id)
        mon = next(s for s in sessions if s["date"] == "2026-04-20")

        # Tuesday already has a session in the default 5-day plan — sending no
        # target_id should fail with 409 rather than violating the unique
        # constraint.
        resp = await authenticated_client.post(
            f"/api/v1/schedule/microcycles/{micro_id}/sessions/swap",
            json={"source_id": mon["id"], "target_date": "2026-04-21"},
        )
        assert resp.status_code == 409, resp.text

    @pytest.mark.asyncio
    async def test_swap_target_outside_microcycle_rejects(
        self, authenticated_client: AsyncClient, db_session, seeded_user
    ):
        micro_id = await self._create_macro(authenticated_client)
        sessions = await self._list_sessions(authenticated_client, micro_id)
        mon = next(s for s in sessions if s["date"] == "2026-04-20")

        resp = await authenticated_client.post(
            f"/api/v1/schedule/microcycles/{micro_id}/sessions/swap",
            json={"source_id": mon["id"], "target_date": "2026-04-30"},
        )
        assert resp.status_code == 400, resp.text
