"""
Tests for /api/v1/programs — cfai mesocycle generation + persistence.

Uses heuristic composer (no LLM calls / no API keys / fast).
"""
from datetime import date, timedelta
from uuid import UUID

import pytest

from app.api.v1.programs import _build_athlete, _next_monday, _parse_phases
from app.core.program_projection import (
    _build_block_plan,
    _flatten_movements,
    _phase_targets,
    _workout_type_for,
)
from app.db.models import Injury as InjuryDB, PersonalRecord as PersonalRecordDB
from cfai.workout_schema import Phase


# ==========================================================
# Unit — helpers
# ==========================================================

class TestNextMonday:
    def test_monday_returns_next_monday(self):
        # 2026-04-20 is a Monday → next Monday is 2026-04-27
        assert _next_monday(date(2026, 4, 20)) == date(2026, 4, 27)

    def test_wednesday_returns_following_monday(self):
        assert _next_monday(date(2026, 4, 22)) == date(2026, 4, 27)

    def test_sunday_returns_next_day(self):
        assert _next_monday(date(2026, 4, 26)) == date(2026, 4, 27)


class TestParsePhases:
    def test_valid_phases(self):
        out = _parse_phases(["build", "build", "deload"])
        assert out == [Phase.BUILD, Phase.BUILD, Phase.DELOAD]

    def test_invalid_phase_raises_400(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            _parse_phases(["build", "garbage"])
        assert exc.value.status_code == 400


class TestProjectionHelpers:
    def test_workout_type_mapping(self):
        assert _workout_type_for("strength_max") == "strength"
        assert _workout_type_for("aerobic_threshold") == "conditioning"
        assert _workout_type_for("vo2_max") == "metcon"
        assert _workout_type_for("skill_acquisition") == "skill"
        assert _workout_type_for(None) == "mixed"

    def test_phase_targets_deload_overrides(self):
        assert _phase_targets("build", deload=True) == ("low", "low")
        assert _phase_targets("build", deload=False) == ("moderate", "high")
        assert _phase_targets("test", deload=False) == ("max", "low")

    def test_block_plan_groups_consecutive_phases(self):
        spec = {"weeks": ["build", "build", "build", "deload"], "deload_weeks": [4]}
        plan = _build_block_plan(spec)
        # cfai phases map to backend BlockType: build → intensification
        assert plan == [
            {"type": "intensification", "weeks": 3},
            {"type": "deload", "weeks": 1},
        ]

    def test_block_plan_handles_alternating_phases(self):
        spec = {"weeks": ["base", "build", "base", "deload"], "deload_weeks": [4]}
        plan = _build_block_plan(spec)
        assert plan == [
            {"type": "accumulation", "weeks": 1},
            {"type": "intensification", "weeks": 1},
            {"type": "accumulation", "weeks": 1},
            {"type": "deload", "weeks": 1},
        ]

    def test_flatten_movements_preserves_block_label(self):
        blocks = [{
            "order": 1, "type": "strength_primary", "format": "sets_reps",
            "movements": [{
                "movement_id": "back_squat", "reps": 5,
                "load": {"type": "percent_1rm", "value": 80, "reference_lift": "back_squat"},
            }],
        }]
        flat = _flatten_movements(blocks)
        assert len(flat) == 1
        assert flat[0]["movement"] == "back_squat"
        assert flat[0]["reps"] == 5
        assert flat[0]["intensity"] == "80% back_squat"
        assert flat[0]["block_label"] == "strength_primary"

    def test_flatten_movements_handles_calories_and_distance(self):
        blocks = [{
            "order": 1, "type": "metcon", "format": "amrap",
            "movements": [
                {"movement_id": "row", "calories": 20},
                {"movement_id": "run", "distance_meters": 400},
                {"movement_id": "plank", "time_seconds": 60},
            ],
        }]
        flat = _flatten_movements(blocks)
        assert flat[0]["reps"] == 20 and flat[0]["reps_unit"] == "cal"
        assert flat[1]["distance_meters"] == 400.0
        assert flat[2]["duration_seconds"] == 60.0

    def test_flatten_movements_amrap_emits_block_prescription(self):
        """AMRAP is time-bound; the timer goes on the block_prescription
        field so the drawer can render it once as a group header."""
        blocks = [{
            "order": 1, "type": "metcon", "format": "amrap",
            "duration_minutes": 10,
            "movements": [
                {"movement_id": "thruster", "reps": 10},
                {"movement_id": "pull_up", "reps": 15},
            ],
        }]
        flat = _flatten_movements(blocks)
        assert flat[0]["block_prescription"] == "AMRAP 10:00"
        assert flat[1]["block_prescription"] == "AMRAP 10:00"
        # Both movements share the same block — same block_id
        assert flat[0]["block_id"] == flat[1]["block_id"]

    def test_flatten_movements_for_time_capped_includes_cap(self):
        blocks = [{
            "order": 1, "type": "metcon", "format": "for_time_capped",
            "time_cap_minutes": 12,
            "movements": [{"movement_id": "thruster", "reps": 21}],
        }]
        flat = _flatten_movements(blocks)
        assert flat[0]["block_prescription"] == "For Time (cap 12:00)"

    def test_flatten_movements_emom_includes_duration(self):
        blocks = [{
            "order": 1, "type": "metcon", "format": "emom",
            "duration_minutes": 12,
            "movements": [{"movement_id": "clean", "reps": 3}],
        }]
        flat = _flatten_movements(blocks)
        assert flat[0]["block_prescription"] == "EMOM 12:00"

    def test_flatten_movements_propagates_block_rest(self):
        """rest_seconds (block-level) gets denormalized so the drawer
        can render 'Rest between sets: 1:00' beneath the group."""
        blocks = [{
            "order": 1, "type": "strength_primary", "format": "sets_reps",
            "rest_seconds": 60,
            "movements": [{"movement_id": "back_squat", "reps": 5}],
        }]
        flat = _flatten_movements(blocks)
        assert flat[0]["block_rest_seconds"] == 60

    def test_flatten_movements_sets_reps_format_omits_label(self):
        """sets_reps is implied by per-movement chips (e.g. 5×3 already
        shows in the chip) — block_prescription stays None."""
        blocks = [{
            "order": 1, "type": "strength_primary", "format": "sets_reps",
            "movements": [{"movement_id": "back_squat", "reps": 5}],
        }]
        flat = _flatten_movements(blocks)
        assert flat[0]["block_label"] == "strength_primary"
        assert flat[0]["block_prescription"] is None

    def test_flatten_movements_keeps_movement_notes_only(self):
        """`notes` field carries movement-specific text only — block
        prefix moved to dedicated block_* fields."""
        blocks = [{
            "order": 1, "type": "metcon", "format": "amrap",
            "duration_minutes": 10,
            "intent": "Mixed modal triplet",
            "movements": [{"movement_id": "thruster", "reps": 10, "notes": "scale to DB"}],
        }]
        flat = _flatten_movements(blocks)
        assert flat[0]["notes"] == "scale to DB"
        assert flat[0]["block_intent"] == "Mixed modal triplet"


class TestBuildAthlete:
    def test_pulls_1rms_and_injuries(self, db_session, seeded_user):
        # Seed PRs
        db_session.add(PersonalRecordDB(
            user_id=seeded_user.id,
            movement_name="Back Squat",
            record_type="1rm",
            value=160.0,
            unit="kg",
        ))
        db_session.add(PersonalRecordDB(
            user_id=seeded_user.id,
            movement_name="Deadlift",
            record_type="1rm",
            value=190.0,
            unit="kg",
        ))
        # Seed an active injury
        db_session.add(InjuryDB(
            user_id=seeded_user.id,
            body_part="left_shoulder",
            description="rotator cuff strain",
            restriction_tags=["overhead"],
            severity="moderate",
            started_at=date(2026, 4, 1),
        ))
        db_session.commit()

        athlete = _build_athlete(db_session, seeded_user)

        assert "back_squat" in athlete.one_rep_maxes
        assert athlete.one_rep_maxes["back_squat"].value_kg == 160.0
        assert "deadlift" in athlete.one_rep_maxes
        assert len(athlete.active_injuries) == 1
        assert "overhead" in athlete.active_injuries[0].affected_patterns
        assert athlete.body_weight_kg == seeded_user.weight_kg

    def test_no_prs_yields_empty_orm(self, db_session, seeded_user):
        athlete = _build_athlete(db_session, seeded_user)
        assert athlete.one_rep_maxes == {}
        assert athlete.active_injuries == []


# ==========================================================
# Integration — POST /generate
# ==========================================================

@pytest.mark.asyncio
class TestGenerateProgramEndpoint:

    async def test_generates_with_heuristic_composer(
        self, authenticated_client, seeded_user, db_session
    ):
        body = {
            "composer": "heuristic",
            "weeks": ["build", "build", "build", "deload"],
            "deload_weeks": [4],
            "primary_focus": ["squat_volume", "aerobic_threshold"],
            "sessions_per_week": 5,
        }
        r = await authenticated_client.post("/api/v1/programs/generate", json=body)
        assert r.status_code == 201, r.text
        data = r.json()
        assert data["composer_used"] == "heuristic"
        assert data["duration_weeks"] == 4
        assert data["sessions_per_week"] == 5
        assert data["persisted"] is True
        # Mesocycle structure
        meso = data["mesocycle"]
        assert len(meso["weeks"]) == 4
        # Each week should have 5 sessions
        for w in meso["weeks"]:
            assert len(w["sessions"]) == 5
        # generation_metadata captures cost + timing
        gm = data["generation_metadata"]
        assert "elapsed_seconds" in gm
        assert gm["n_sessions"] == 20

    async def test_persisted_program_is_retrievable(
        self, authenticated_client, seeded_user
    ):
        body = {
            "composer": "heuristic",
            "weeks": ["build", "deload"],
            "deload_weeks": [2],
            "primary_focus": ["aerobic_threshold"],
            "sessions_per_week": 3,
        }
        r = await authenticated_client.post("/api/v1/programs/generate", json=body)
        assert r.status_code == 201
        program_id = r.json()["id"]
        assert program_id is not None

        # GET by id
        r2 = await authenticated_client.get(f"/api/v1/programs/{program_id}")
        assert r2.status_code == 200
        assert r2.json()["id"] == program_id
        assert r2.json()["composer_used"] == "heuristic"

        # List
        r3 = await authenticated_client.get("/api/v1/programs/")
        assert r3.status_code == 200
        ids = [p["id"] for p in r3.json()]
        assert program_id in ids

    async def test_persist_false_does_not_write(
        self, authenticated_client, seeded_user
    ):
        body = {
            "composer": "heuristic",
            "weeks": ["build", "deload"],
            "deload_weeks": [2],
            "primary_focus": ["aerobic_threshold"],
            "sessions_per_week": 3,
            "persist": False,
        }
        r = await authenticated_client.post("/api/v1/programs/generate", json=body)
        assert r.status_code == 201
        assert r.json()["id"] is None
        assert r.json()["persisted"] is False

    async def test_invalid_phase_returns_400(
        self, authenticated_client, seeded_user
    ):
        body = {
            "composer": "heuristic",
            "weeks": ["build", "nonsense"],
            "deload_weeks": [],
            "primary_focus": ["x"],
        }
        r = await authenticated_client.post("/api/v1/programs/generate", json=body)
        assert r.status_code == 400

    async def test_unknown_composer_returns_400(
        self, authenticated_client, seeded_user
    ):
        body = {
            "composer": "magic_wand",
            "weeks": ["build"],
            "deload_weeks": [],
            "primary_focus": ["x"],
        }
        r = await authenticated_client.post("/api/v1/programs/generate", json=body)
        assert r.status_code == 400

    async def test_unknown_provider_returns_400(
        self, authenticated_client, seeded_user
    ):
        body = {
            "composer": "hybrid_doesnotexist",
            "weeks": ["build"],
            "deload_weeks": [],
            "primary_focus": ["x"],
        }
        r = await authenticated_client.post("/api/v1/programs/generate", json=body)
        assert r.status_code == 400

    async def test_deload_out_of_range_returns_400(
        self, authenticated_client, seeded_user
    ):
        body = {
            "composer": "heuristic",
            "weeks": ["build", "build"],
            "deload_weeks": [5],
            "primary_focus": ["x"],
        }
        r = await authenticated_client.post("/api/v1/programs/generate", json=body)
        assert r.status_code == 400

    async def _generate_program(self, client) -> str:
        body = {
            "composer": "heuristic",
            "weeks": ["build", "build", "deload"],
            "deload_weeks": [3],
            "primary_focus": ["squat_volume"],
            "sessions_per_week": 3,
        }
        r = await client.post("/api/v1/programs/generate", json=body)
        assert r.status_code == 201, r.text
        return r.json()["id"]

    async def test_activate_creates_periodization_rows(
        self, authenticated_client, seeded_user, db_session
    ):
        from app.db.models import (
            Macrocycle as MacrocycleDB,
            Microcycle as MicrocycleDB,
            PlannedSession as PlannedSessionDB,
            WorkoutTemplate as WorkoutTemplateDB,
        )
        from sqlalchemy import select

        program_id = await self._generate_program(authenticated_client)

        r = await authenticated_client.post(f"/api/v1/programs/{program_id}/activate")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["program_id"] == program_id
        assert data["microcycles"] == 3              # 3 weeks
        assert data["planned_sessions"] == 9         # 3 weeks × 3 sessions
        assert data["workout_templates"] == 9

        # Verify DB rows
        macros = db_session.execute(
            select(MacrocycleDB).where(MacrocycleDB.user_id == seeded_user.id)
        ).scalars().all()
        active = [m for m in macros if m.active]
        assert len(active) == 1
        assert active[0].id == UUID(data["macrocycle_id"])

        micros = db_session.execute(
            select(MicrocycleDB).where(MicrocycleDB.macrocycle_id == active[0].id)
        ).scalars().all()
        assert len(micros) == 3
        # Deload week 3
        deload_micro = next(m for m in micros if m.week_index_in_macro == 3)
        assert deload_micro.intensity_target == "low"
        assert deload_micro.volume_target == "low"

        planned = db_session.execute(
            select(PlannedSessionDB).where(PlannedSessionDB.user_id == seeded_user.id)
        ).scalars().all()
        assert len(planned) == 9
        # All planned sessions should be linked to a generated template
        assert all(p.generated_template_id is not None for p in planned)
        assert all(p.status == "planned" for p in planned)

        templates = db_session.execute(
            select(WorkoutTemplateDB).where(WorkoutTemplateDB.owner_user_id == seeded_user.id)
        ).scalars().all()
        assert len(templates) == 9
        # Movements were flattened
        assert all(len(t.movements) > 0 for t in templates)

    async def test_activate_deactivates_prior_macrocycles(
        self, authenticated_client, seeded_user, db_session
    ):
        from app.db.models import Macrocycle as MacrocycleDB
        from sqlalchemy import select

        program_id_1 = await self._generate_program(authenticated_client)
        await authenticated_client.post(f"/api/v1/programs/{program_id_1}/activate")

        program_id_2 = await self._generate_program(authenticated_client)
        r = await authenticated_client.post(f"/api/v1/programs/{program_id_2}/activate")
        assert r.status_code == 200

        macros = db_session.execute(
            select(MacrocycleDB).where(MacrocycleDB.user_id == seeded_user.id)
        ).scalars().all()
        assert len(macros) == 2
        active = [m for m in macros if m.active]
        assert len(active) == 1, "Only the latest activation should remain active"

    async def test_activate_makes_today_endpoint_return_workout(
        self, authenticated_client, seeded_user
    ):
        """End-to-end: activating a program → /training/today returns the workout."""
        from datetime import date as _Date, timedelta

        # Generate with start_date=today so we have a session for today
        today = _Date.today()
        body = {
            "composer": "heuristic",
            "weeks": ["build"],
            "deload_weeks": [],
            "primary_focus": ["squat_volume"],
            "sessions_per_week": 5,
            "start_date": today.isoformat(),
        }
        r = await authenticated_client.post("/api/v1/programs/generate", json=body)
        program_id = r.json()["id"]
        await authenticated_client.post(f"/api/v1/programs/{program_id}/activate")

        r = await authenticated_client.get("/api/v1/training/today")
        assert r.status_code == 200
        data = r.json()
        assert data["workout"] is not None
        assert "movements" in data["workout"]

    async def test_activate_other_users_program_is_403(
        self, authenticated_client, seeded_user, db_session
    ):
        from app.db.models import Program as ProgramDB, User as UserDB

        other = UserDB(
            id=999,
            email="other@example.com",
            password_hash="x",
            name="Other",
        )
        db_session.add(other)
        db_session.commit()
        prog = ProgramDB(
            user_id=999,
            name="other's program",
            composer_used="heuristic",
            phase="build",
            start_date=date(2026, 5, 4),
            duration_weeks=1,
            sessions_per_week=3,
            primary_focus=["x"],
            spec={"weeks": ["build"], "deload_weeks": []},
            athlete_snapshot={},
            mesocycle={"weeks": []},
            generation_metadata={},
        )
        db_session.add(prog)
        db_session.commit()
        db_session.refresh(prog)

        r = await authenticated_client.post(f"/api/v1/programs/{prog.id}/activate")
        assert r.status_code == 403

    async def test_activate_unknown_program_is_404(
        self, authenticated_client, seeded_user
    ):
        from uuid import uuid4
        r = await authenticated_client.post(f"/api/v1/programs/{uuid4()}/activate")
        assert r.status_code == 404

    async def test_other_users_program_is_403(
        self, authenticated_client, seeded_user, db_session
    ):
        from app.db.models import Program as ProgramDB, User as UserDB

        # Insert a program owned by a different user
        other = UserDB(
            id=999,
            email="other@example.com",
            password_hash="x",
            name="Other",
        )
        db_session.add(other)
        db_session.commit()

        prog = ProgramDB(
            user_id=999,
            name="other's program",
            composer_used="heuristic",
            phase="build",
            start_date=date(2026, 5, 4),
            duration_weeks=1,
            sessions_per_week=3,
            primary_focus=["x"],
            spec={"weeks": ["build"], "deload_weeks": []},
            athlete_snapshot={},
            mesocycle={},
            generation_metadata={},
        )
        db_session.add(prog)
        db_session.commit()
        db_session.refresh(prog)

        r = await authenticated_client.get(f"/api/v1/programs/{prog.id}")
        assert r.status_code == 403
