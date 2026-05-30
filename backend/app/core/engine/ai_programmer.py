"""
AI-Powered Training Programmer (SQLAlchemy).

Generates workouts for a microcycle (one week) using OpenAI GPT, with full
context of the athlete's periodization block, week-in-block, next block, and
real previous-week performance. Also supports single-session regeneration.
"""
from __future__ import annotations

from datetime import date as _Date, datetime as _Datetime, timedelta
from typing import Optional
from uuid import uuid4
import json
import logging

from openai import AsyncOpenAI
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.engine.periodization import (
    next_block_after,
    resolve_block_and_week_in_block,
)
from app.db.models import (
    Macrocycle as MacrocycleDB,
    Microcycle as MicrocycleDB,
    PlannedSession as PlannedSessionDB,
    User as UserDB,
    WorkoutSession as WorkoutSessionDB,
    WorkoutTemplate as WorkoutTemplateDB,
)
from app.models.training import (
    BlockPlanItem,
    BlockType,
    Methodology,
    Movement,
    PlannedSessionStatus,
    WorkoutTemplate,
    WorkoutType,
)

logger = logging.getLogger(__name__)


class AITrainingProgrammer:
    """AI-powered training programmer that generates progressive workouts."""

    def __init__(self):
        self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY) if settings.OPENAI_API_KEY else None

    # ==========================================================
    # Public API — microcycle-based generation
    # ==========================================================

    async def generate_microcycle_program(
        self,
        db: Session,
        microcycle: MicrocycleDB,
        user_id: int,
    ) -> int:
        """
        Generate workouts for every planned_session in the given microcycle.

        Commits per-session template inserts within the caller's transaction.
        Returns the count of sessions generated.
        """
        macro = db.get(MacrocycleDB, microcycle.macrocycle_id)
        if not macro:
            raise RuntimeError("Macrocycle not found for microcycle")

        block_plan = _parse_block_plan(macro.block_plan)
        block_type, week_in_block, block_len = resolve_block_and_week_in_block(
            block_plan, microcycle.week_index_in_macro
        )
        next_block = next_block_after(block_plan, microcycle.week_index_in_macro)

        planned_sessions = db.execute(
            select(PlannedSessionDB)
            .where(PlannedSessionDB.microcycle_id == microcycle.id)
            .order_by(PlannedSessionDB.date, PlannedSessionDB.order_in_day)
        ).scalars().all()

        if not planned_sessions:
            logger.info(f"Microcycle {microcycle.id} has no planned sessions; nothing to generate")
            return 0

        user = db.get(UserDB, user_id)
        previous_week_data = self._fetch_previous_microcycle_stats(
            db=db, user_id=user_id, current_start=microcycle.start_date
        )

        if not self.client:
            logger.warning("OpenAI client unavailable; using fallback generator")
            return self._generate_fallback_for_sessions(db, planned_sessions, user_id)

        context = self._build_microcycle_context(
            user=user,
            macro=macro,
            microcycle=microcycle,
            block_type=block_type,
            week_in_block=week_in_block,
            block_len=block_len,
            next_block=next_block,
            planned_sessions=planned_sessions,
            previous_week_data=previous_week_data,
        )

        try:
            response = await self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": self._get_system_prompt()},
                    {"role": "user", "content": self._build_microcycle_prompt(context)},
                ],
                temperature=0.7,
                response_format={"type": "json_object"},
            )
            program_json = json.loads(response.choices[0].message.content)
            return self._persist_generated_workouts(
                db=db,
                program_json=program_json,
                planned_sessions=planned_sessions,
                methodology=Methodology(macro.methodology),
                user_id=user_id,
            )
        except Exception as e:
            logger.error(f"AI microcycle generation failed: {e}", exc_info=True)
            return self._generate_fallback_for_sessions(db, planned_sessions, user_id)

    async def regenerate_single_session(
        self,
        db: Session,
        planned: PlannedSessionDB,
        user_id: int,
    ) -> PlannedSessionDB:
        """Regenerate the workout for one planned session, keeping the rest of the week as context."""
        micro = db.get(MicrocycleDB, planned.microcycle_id)
        macro = db.get(MacrocycleDB, micro.macrocycle_id)
        block_plan = _parse_block_plan(macro.block_plan)
        block_type, week_in_block, block_len = resolve_block_and_week_in_block(
            block_plan, micro.week_index_in_macro
        )
        next_block = next_block_after(block_plan, micro.week_index_in_macro)

        planned_sessions = db.execute(
            select(PlannedSessionDB)
            .where(PlannedSessionDB.microcycle_id == micro.id)
            .order_by(PlannedSessionDB.date, PlannedSessionDB.order_in_day)
        ).scalars().all()

        user = db.get(UserDB, user_id)
        previous_week_data = self._fetch_previous_microcycle_stats(
            db=db, user_id=user_id, current_start=micro.start_date
        )

        if not self.client:
            template = self._fallback_template_for_session(planned)
            self._attach_template_to_session(db, planned, template, user_id)
            return planned

        context = self._build_microcycle_context(
            user=user,
            macro=macro,
            microcycle=micro,
            block_type=block_type,
            week_in_block=week_in_block,
            block_len=block_len,
            next_block=next_block,
            planned_sessions=planned_sessions,
            previous_week_data=previous_week_data,
        )

        prompt = self._build_single_session_prompt(context, planned)
        try:
            response = await self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": self._get_system_prompt()},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.7,
                response_format={"type": "json_object"},
            )
            workout_data = json.loads(response.choices[0].message.content)
            template = self._parse_single_workout(workout_data, planned, Methodology(macro.methodology))
            self._attach_template_to_session(db, planned, template, user_id)
        except Exception as e:
            logger.error(f"Single-session regeneration failed: {e}", exc_info=True)
            template = self._fallback_template_for_session(planned)
            self._attach_template_to_session(db, planned, template, user_id)

        return planned

    # ==========================================================
    # Prompt building
    # ==========================================================

    def _get_system_prompt(self) -> str:
        return """You are an elite CrossFit programming coach with expertise in HWPO (Mat Fraser), Mayhem (Rich Froning), and CompTrain (Ben Bergeron) methodologies.

Your role is to create intelligent, progressive training programs that:
1. Respect the current periodization block (accumulation, intensification, realization, deload, test, transition) AND the week's position inside that block.
2. Balance strength, metcon, gymnastics, and conditioning across the week.
3. Adapt to the athlete's fitness level, weaknesses, and goals.
4. Respect the user-planned session grid — date, shift, workout_type, duration are fixed. You only fill the workout content.
5. Support multi-session days (e.g., strength AM + metcon PM) and avoid CNS overlap.
6. Apply progressive overload using the previous microcycle's actual performance data.

Block-type programming rules:
- ACCUMULATION: higher volume, moderate intensity (60-75% 1RM), 4-6 sets, RPE 6-7, lots of accessory work.
- INTENSIFICATION: reduced volume, higher intensity (80-90% 1RM), 3-5 sets, RPE 7-8.
- REALIZATION/PEAK: low volume, very high intensity (85-95% 1RM), 2-3 working sets, sharp metcons.
- DELOAD: 50-60% volume of the previous week at moderate intensity, restorative tempo work, technical focus.
- TEST: primarily benchmark lifts or named WODs (Fran, Grace, 1RM attempts).
- TRANSITION: mostly recovery, mobility, aerobic zone-2 work; minimal barbell.

Ergometer / monostructural movement rules:
- Calorie-based (cal_row, cal_bike, cal_ski): reps field = calories, reps_unit = "cal".
- Distance-based (run, row_meters): use distance_meters.
- Time-based: use duration_seconds.
- Always include reps_unit when reps means something other than repetitions.

You must return a valid JSON object with workout details for each requested session."""

    def _build_microcycle_context(
        self,
        user: Optional[UserDB],
        macro: MacrocycleDB,
        microcycle: MicrocycleDB,
        block_type: Optional[BlockType],
        week_in_block: Optional[int],
        block_len: Optional[int],
        next_block: Optional[BlockPlanItem],
        planned_sessions: list[PlannedSessionDB],
        previous_week_data: Optional[dict],
    ) -> dict:
        prefs = (user.preferences or {}) if user else {}
        return {
            "athlete": {
                "fitness_level": (user.fitness_level if user else "intermediate"),
                "weight_kg": (user.weight_kg if user else 80),
                "goals": prefs.get("goals", user.goals if user else ["strength", "conditioning"]),
                "weaknesses": prefs.get("weaknesses", []),
            },
            "macrocycle": {
                "methodology": macro.methodology,
                "start_date": str(macro.start_date),
                "end_date": str(macro.end_date),
                "goal": macro.goal,
            },
            "microcycle": {
                "start_date": str(microcycle.start_date),
                "end_date": str(microcycle.end_date),
                "week_index_in_macro": microcycle.week_index_in_macro,
                "block_type": block_type.value if block_type else None,
                "week_in_block": week_in_block,
                "block_total_weeks": block_len,
                "next_block": {
                    "type": next_block.type.value,
                    "weeks": next_block.weeks,
                } if next_block else None,
                "intensity_target": microcycle.intensity_target,
                "volume_target": microcycle.volume_target,
            },
            "planned_sessions": [
                {
                    "id": str(s.id),
                    "date": str(s.date),
                    "order_in_day": s.order_in_day,
                    "shift": s.shift,
                    "start_time": str(s.start_time) if s.start_time else None,
                    "duration_minutes": s.duration_minutes,
                    "workout_type": s.workout_type,
                    "focus": s.focus,
                } for s in planned_sessions
            ],
            "previous_microcycle": previous_week_data,
        }

    def _build_microcycle_prompt(self, context: dict) -> str:
        athlete = context["athlete"]
        macro = context["macrocycle"]
        micro = context["microcycle"]
        sessions = context["planned_sessions"]
        prev = context.get("previous_microcycle")

        return f"""Generate the workout for every planned session below.

**Athlete**
- Fitness level: {athlete['fitness_level']}
- Bodyweight: {athlete['weight_kg']} kg
- Goals: {', '.join(athlete['goals'] or [])}
- Weaknesses: {', '.join(athlete['weaknesses']) if athlete['weaknesses'] else 'None specified'}

**Macrocycle**
- Methodology: {macro['methodology'].upper()}
- Dates: {macro['start_date']} → {macro['end_date']}
- Goal: {macro.get('goal') or 'General performance'}

**Current Microcycle**
- Dates: {micro['start_date']} → {micro['end_date']}
- Week {micro['week_index_in_macro']} of the macrocycle
- Block: {micro['block_type']} (week {micro['week_in_block']} of {micro['block_total_weeks']})
- Next block: {json.dumps(micro.get('next_block')) if micro.get('next_block') else 'end of macrocycle'}
- Intensity target: {micro.get('intensity_target') or 'auto'}
- Volume target: {micro.get('volume_target') or 'auto'}

**Planned Sessions** (you must generate one workout per session; do NOT change dates, order, type or duration)
{json.dumps(sessions, indent=2)}

**Previous Microcycle Performance**
{json.dumps(prev, indent=2) if prev else 'No prior data (first microcycle)'}

**Output**
Return JSON with the shape:
```
{{
  "microcycle_summary": "High-level focus of the week",
  "workouts": [
    {{
      "session_id": "<planned_session.id>",
      "name": "…",
      "description": "…",
      "workout_type": "strength",
      "duration_minutes": 90,
      "warm_up": "…",
      "movements": [
        {{
          "movement": "back_squat",       // REQUIRED. snake_case identifier (back_squat, deadlift, thruster, pull_up, ...). Never blank or "unknown".
          "sets": 5,                       // optional int
          "reps": 5,                       // optional int OR string like "21-15-9" / "AMRAP"
          "reps_unit": "reps",             // "reps" | "cal" | "m"
          "weight_kg": 100,                // optional number (kg)
          "distance_meters": 400,          // optional
          "duration_seconds": 60,          // optional
          "intensity": "80%",              // optional, e.g. "80%", "RPE 8", "moderate"
          "rest": "2min",                  // optional
          "notes": "…"                     // optional
        }}
      ],
      "target_stimulus": "…",
      "tags": ["…"]
    }}
  ]
}}
```
The "movement" field is REQUIRED on every movement object — use snake_case identifiers, never "unknown".

Each output workout must reference a planned session by its `session_id`. Generate exactly {len(sessions)} workouts."""

    def _build_single_session_prompt(self, context: dict, planned: PlannedSessionDB) -> str:
        target = {
            "session_id": str(planned.id),
            "date": str(planned.date),
            "order_in_day": planned.order_in_day,
            "workout_type": planned.workout_type,
            "duration_minutes": planned.duration_minutes,
            "focus": planned.focus,
        }
        return f"""Regenerate a single training session.

**Full-week context** (other sessions in the same microcycle — do NOT duplicate their stimulus):
{json.dumps(context['planned_sessions'], indent=2)}

**Microcycle block**: {context['microcycle']['block_type']} (week {context['microcycle']['week_in_block']} of {context['microcycle']['block_total_weeks']})

**Target session** (return exactly one workout for this):
{json.dumps(target, indent=2)}

**Previous Microcycle Performance**
{json.dumps(context.get('previous_microcycle'), indent=2) if context.get('previous_microcycle') else 'No prior data'}

Return JSON: {{"session_id":"…","name":"…","description":"…","workout_type":"…","duration_minutes":…,"warm_up":"…","movements":[…],"target_stimulus":"…","tags":[…]}}.
"""

    # ==========================================================
    # Persistence
    # ==========================================================

    def _persist_generated_workouts(
        self,
        db: Session,
        program_json: dict,
        planned_sessions: list[PlannedSessionDB],
        methodology: Methodology,
        user_id: int,
    ) -> int:
        session_by_id = {str(s.id): s for s in planned_sessions}
        workouts = program_json.get("workouts", [])

        count = 0
        for w in workouts:
            sid = str(w.get("session_id"))
            planned = session_by_id.get(sid)
            if not planned:
                logger.warning(f"Generated workout references unknown session_id={sid}")
                continue
            template = self._parse_single_workout(w, planned, methodology)
            self._attach_template_to_session(db, planned, template, user_id)
            count += 1
        db.commit()
        return count

    def _attach_template_to_session(
        self,
        db: Session,
        planned: PlannedSessionDB,
        template: WorkoutTemplate,
        user_id: int,
    ) -> None:
        template_row = WorkoutTemplateDB(
            owner_user_id=user_id,
            name=template.name,
            description=template.description,
            methodology=template.methodology.value,
            difficulty_level=template.difficulty_level,
            workout_type=template.workout_type.value,
            duration_minutes=template.duration_minutes,
            movements=[m.model_dump(mode="json") for m in template.movements],
            target_stimulus=template.target_stimulus,
            warm_up=getattr(template, "warm_up", None),
            tags=(template.tags or []) + ["ai_generated"],
            equipment_required=template.equipment_required or [],
            is_public=False,
        )
        db.add(template_row)
        db.flush()

        planned.generated_template_id = template_row.id
        planned.status = PlannedSessionStatus.GENERATED.value

    # ==========================================================
    # Fetchers
    # ==========================================================

    def _fetch_previous_microcycle_stats(
        self,
        db: Session,
        user_id: int,
        current_start: _Date,
    ) -> Optional[dict]:
        prev_end = current_start - timedelta(days=1)
        prev_start = prev_end - timedelta(days=6)

        rows = db.execute(
            select(WorkoutSessionDB).where(
                and_(
                    WorkoutSessionDB.user_id == user_id,
                    WorkoutSessionDB.started_at >= _Datetime.combine(prev_start, _Datetime.min.time()),
                    WorkoutSessionDB.started_at <= _Datetime.combine(prev_end, _Datetime.max.time()),
                )
            )
        ).scalars().all()

        if not rows:
            return None

        completed = [r for r in rows if r.completed_at]
        rpes = [r.rpe_score for r in completed if r.rpe_score is not None]
        durations = [r.duration_minutes for r in completed if r.duration_minutes is not None]

        return {
            "date_range": f"{prev_start} → {prev_end}",
            "sessions_started": len(rows),
            "sessions_completed": len(completed),
            "avg_rpe": round(sum(rpes) / len(rpes), 1) if rpes else None,
            "avg_duration_min": round(sum(durations) / len(durations), 1) if durations else None,
            "workout_types": [r.workout_type for r in completed],
        }

    # ==========================================================
    # Parsing & fallback
    # ==========================================================

    def _parse_single_workout(
        self,
        workout_data: dict,
        planned: PlannedSessionDB,
        methodology: Methodology,
    ) -> WorkoutTemplate:
        movements = []
        for mov in workout_data.get("movements", []):
            # The model isn't 100% consistent on the field name. Accept the
            # canonical "movement" plus the synonyms it tends to emit when
            # the prompt doesn't pin the schema down (LLM hallucinates
            # "name", "exercise", "movement_name", ...). Falling through
            # to "unknown" was hiding real movement names on the dashboard
            # — see the "unknown · 5 reps" chips.
            mov_name = (
                mov.get("movement")
                or mov.get("name")
                or mov.get("exercise")
                or mov.get("movement_name")
                or mov.get("exercise_name")
                or "unknown"
            )
            movements.append(Movement(
                movement=mov_name,
                sets=mov.get("sets"),
                reps=mov.get("reps"),
                reps_unit=mov.get("reps_unit", "reps"),
                weight_kg=mov.get("weight_kg") or mov.get("weight"),
                distance_meters=mov.get("distance_meters") or mov.get("distance"),
                duration_seconds=mov.get("duration_seconds") or mov.get("duration"),
                intensity=mov.get("intensity"),
                rest=mov.get("rest"),
                notes=mov.get("notes"),
            ))

        workout_type = self._normalize_workout_type(
            workout_data.get("workout_type") or planned.workout_type or "mixed"
        )

        # The model can return warm_up as a string ("5min row + ...") or as
        # a list (["row 5min", "wgs x10"]). Coerce to a single readable string.
        wu_raw = workout_data.get("warm_up") or workout_data.get("warmup")
        if isinstance(wu_raw, list):
            warm_up_text: Optional[str] = " · ".join(str(x) for x in wu_raw if x) or None
        elif isinstance(wu_raw, str) and wu_raw.strip():
            warm_up_text = wu_raw.strip()
        else:
            warm_up_text = None

        return WorkoutTemplate(
            id=uuid4(),
            name=workout_data.get("name", f"Session {planned.date}"),
            description=workout_data.get("description"),
            methodology=methodology,
            difficulty_level="rx",
            workout_type=workout_type,
            duration_minutes=workout_data.get("duration_minutes") or planned.duration_minutes,
            movements=movements,
            warm_up=warm_up_text,
            target_stimulus=workout_data.get("target_stimulus"),
            tags=workout_data.get("tags", []),
            equipment_required=workout_data.get("equipment_required", []),
            created_at=_Datetime.utcnow(),
            is_public=False,
        )

    def _normalize_workout_type(self, raw_type: str) -> WorkoutType:
        raw = (raw_type or "").lower().strip()
        for wt in WorkoutType:
            if wt.value == raw:
                return wt
        if any(k in raw for k in ["strength", "squat", "deadlift", "press", "heavy"]):
            return WorkoutType.MIXED if any(k in raw for k in ["metcon", "wod", "amrap"]) else WorkoutType.STRENGTH
        if any(k in raw for k in ["metcon", "wod", "amrap", "emom", "chipper", "for time"]):
            return WorkoutType.METCON
        if any(k in raw for k in ["skill", "gymnastic", "handstand", "muscle-up"]):
            return WorkoutType.SKILL
        if any(k in raw for k in ["conditioning", "cardio", "aerobic", "run", "row", "bike"]):
            return WorkoutType.CONDITIONING
        if any(k in raw for k in ["mixed", "hybrid", "combo"]):
            return WorkoutType.MIXED
        return WorkoutType.MIXED

    def _generate_fallback_for_sessions(
        self,
        db: Session,
        planned_sessions: list[PlannedSessionDB],
        user_id: int,
    ) -> int:
        count = 0
        for p in planned_sessions:
            template = self._fallback_template_for_session(p)
            self._attach_template_to_session(db, p, template, user_id)
            count += 1
        db.commit()
        return count

    def _fallback_template_for_session(self, planned: PlannedSessionDB) -> WorkoutTemplate:
        wt = self._normalize_workout_type(planned.workout_type or "mixed")
        duration = planned.duration_minutes or 60

        if wt == WorkoutType.STRENGTH:
            movements = [
                Movement(movement="back_squat", sets=5, reps=5, intensity="80%", rest="3min"),
                Movement(movement="bench_press", sets=4, reps=8, intensity="75%", rest="2min"),
            ]
            warmup = "5 min bike/running + 3x5 back squat light + 3x3 bench press at 50%"
            name = "Strength Session (fallback)"
            stimulus = "Build maximal strength"
        elif wt == WorkoutType.METCON:
            movements = [
                Movement(movement="thruster", reps=21, weight_kg=42.5),
                Movement(movement="pull_up", reps=21),
                Movement(movement="thruster", reps=15, weight_kg=42.5),
                Movement(movement="pull_up", reps=15),
                Movement(movement="thruster", reps=9, weight_kg=42.5),
                Movement(movement="pull_up", reps=9),
            ]
            warmup = "500m row easy + 3 rounds: 5 thrusters + 3 pull-ups + 30s hollow hold"
            name = "Metcon Session (fallback)"
            stimulus = "High intensity couplet"
        elif wt == WorkoutType.SKILL:
            movements = [
                Movement(movement="handstand_walk", sets=6, duration_seconds=30, rest="90s"),
                Movement(movement="muscle_up", sets=5, reps=3, rest="2min"),
                Movement(movement="double_under", sets=5, reps=50, rest="60s"),
            ]
            warmup = "4 rounds: 10 cal row + 5 kip swings + 30s handstand hold against wall"
            name = "Skill Session (fallback)"
            stimulus = "Skill acquisition"
        elif wt == WorkoutType.CONDITIONING:
            movements = [
                Movement(movement="run", distance_meters=400, sets=6, rest="90s"),
                Movement(movement="cal_row", sets=5, reps=20, reps_unit="cal", rest="60s"),
            ]
            warmup = "4 rounds: 1 min easy bike + 10 air squats + 5 burpees"
            name = "Conditioning Session (fallback)"
            stimulus = "Aerobic capacity"
        else:
            movements = [
                Movement(movement="deadlift", sets=3, reps=8, intensity="75%", rest="2min"),
                Movement(movement="cal_bike", reps=40, reps_unit="cal"),
            ]
            warmup = "3 rounds: 10 cal row + 5 deadlifts at 50% + 10 wall balls"
            name = "Mixed Modal (fallback)"
            stimulus = "Balanced stimulus"

        return WorkoutTemplate(
            id=uuid4(),
            name=name,
            description="Fallback workout (OpenAI unavailable)",
            methodology=Methodology.CUSTOM,
            difficulty_level="rx",
            workout_type=wt,
            duration_minutes=duration,
            movements=movements,
            warm_up=warmup,
            target_stimulus=stimulus,
            tags=["fallback", "ai_generated"],
            equipment_required=[],
            created_at=_Datetime.utcnow(),
            is_public=False,
        )


def _parse_block_plan(raw: list[dict] | None) -> list[BlockPlanItem]:
    if not raw:
        return []
    return [BlockPlanItem(type=item["type"], weeks=item["weeks"]) for item in raw]


# Global instance
ai_programmer = AITrainingProgrammer()
