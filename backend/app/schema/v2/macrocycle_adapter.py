"""
Adapter: CrossFit Health OS DB schema → schema v2 (Mesocycle).

Converte:
  Macrocycle (DB) → Mesocycle (v2)
  Microcycle (DB) → Week (v2)
  PlannedSession (DB) → Session (v2)
  WorkoutTemplate (DB) → Session.blocks (v2)

Uso:
  adapter = MacrocycleAdapter(library, athlete)
  mesocycle = adapter.from_db_macrocycle(macrocycle_db)
  # mesocycle e uma instancia de schema_v2.Mesocycle validada

Limitation: WorkoutTemplate.movements e uma lista flat de dicionarios.
Blocos sao inferidos do workout_type + heuristic parsing.
"""

from datetime import date as Date
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session as SqlSession

from app.db.models import Macrocycle as MacrocycleDB
from app.db.models import Microcycle as MicrocycleDB
from app.db.models import PlannedSession as PlannedSessionDB
from app.db.models import WorkoutTemplate as WorkoutTemplateDB
from app.db.models import User as UserDB

from cfai.workout_schema import (
    Phase, SessionTemplate, BlockType, BlockFormat, Stimulus,
    LoadSpec, MovementPrescription, WorkoutBlock, Session,
    Week, Mesocycle,
)
from cfai.movements import MovementLibrary


# ============================================================
# Mapeamentos deterministicos
# ============================================================

_METHODOLOGY_TO_PHASE = {
    "base": Phase.BASE,
    "accumulation": Phase.BASE,
    "build": Phase.BUILD,
    "intensification": Phase.BUILD,
    "peak": Phase.PEAK,
    "peak_phase": Phase.PEAK,
    "deload": Phase.DELOAD,
    "recovery": Phase.DELOAD,
    "test": Phase.TEST,
    "competition": Phase.PEAK,
}

_WORKOUT_TYPE_TO_TEMPLATE = {
    "strength": SessionTemplate.STRENGTH_DAY,
    "strength_day": SessionTemplate.STRENGTH_DAY,
    "metcon": SessionTemplate.METCON_ONLY,
    "metcon_only": SessionTemplate.METCON_ONLY,
    "engine": SessionTemplate.ENGINE_DAY,
    "engine_day": SessionTemplate.ENGINE_DAY,
    "gymnastics": SessionTemplate.GYMNASTIC_DAY,
    "gymnastic_day": SessionTemplate.GYMNASTIC_DAY,
    "skill": SessionTemplate.SKILL_DAY,
    "skill_day": SessionTemplate.SKILL_DAY,
    "recovery": SessionTemplate.RECOVERY,
    "recovery_day": SessionTemplate.RECOVERY,
    "open_gym": SessionTemplate.OPEN_GYM,
    "test": SessionTemplate.TEST_DAY,
    "comp_sim": SessionTemplate.COMP_SIM,
}

_WORKOUT_TYPE_TO_STIMULUS = {
    "strength": Stimulus.STRENGTH_VOLUME,
    "metcon": Stimulus.MIXED_MODAL,
    "engine": Stimulus.AEROBIC_THRESHOLD,
    "gymnastics": Stimulus.GYMNASTIC_CAPACITY,
    "skill": Stimulus.SKILL_ACQUISITION,
    "recovery": Stimulus.RECOVERY,
    "test": Stimulus.STRENGTH_MAX,
}


# ============================================================
# Helpers
# ============================================================

def _parse_block_plan(block_plan: list[dict]) -> list[tuple[str, int, int]]:
    """Parse block_plan [{type, weeks}, ...] -> [(phase, start_week, end_week)]."""
    blocks = []
    cursor = 1
    for entry in block_plan:
        phase = entry.get("type", "base")
        weeks = entry.get("weeks", 3)
        blocks.append((phase, cursor, cursor + weeks - 1))
        cursor += weeks
    return blocks


def _phase_from_week(blocks_info: list[tuple[str, int, int]], week: int) -> Phase:
    """Dado week_number, retorna Phase do bloco correspondente."""
    for phase, start, end in blocks_info:
        if start <= week <= end:
            return _METHODOLOGY_TO_PHASE.get(phase, Phase.BASE)
    return Phase.BASE


def _movement_to_mp(m: dict) -> MovementPrescription:
    """Converte dict de movement (do DB) -> MovementPrescription (v2)."""
    volume_key = None
    for vk in ("reps", "time_seconds", "distance_meters", "calories"):
        if vk in m and m[vk] is not None:
            volume_key = vk
            break

    load = None
    if m.get("load_kg"):
        load = LoadSpec(type="absolute_kg", value=float(m["load_kg"]))
    elif m.get("load_percent") and m.get("load_reference"):
        load = LoadSpec(
            type="percent_1rm",
            value=float(str(m["load_percent"]).replace("%","").strip()),
            reference_lift=m["load_reference"],
        )
    elif m.get("intensity"):
        try:
            intensity_str = str(m["intensity"]).strip()
            if intensity_str.endswith('%'):
                intensity_str = intensity_str[:-1]
            load = LoadSpec(type="rpe", value=float(intensity_str))
        except (ValueError, TypeError):
            load = None

    return MovementPrescription(
        movement_id=m.get("movement", m.get("movement_id", "unknown")),
        reps=m["reps"] if volume_key == "reps" else None,
        time_seconds=m["time_seconds"] if volume_key == "time_seconds" else None,
        distance_meters=m["distance_meters"] if volume_key == "distance_meters" else None,
        calories=m["calories"] if volume_key == "calories" else None,
        load=load,
        notes=m.get("notes"),
    )


# ============================================================
# Main Adapter
# ============================================================

class MacrocycleAdapter:
    """Converte Macrocycle DB -> Mesocycle v2."""

    def __init__(self, library: MovementLibrary):
        self.library = library

    def from_db_macrocycle(
        self,
        db: SqlSession,
        macrocycle_db: MacrocycleDB,
        user_db: UserDB,
        athlete_id: str,
    ) -> Mesocycle:
        """Converte Macrocycle DB para Mesocycle v2.

        Args:
            db: SQLAlchemy session
            macrocycle_db: Macrocycle row do DB
            user_db: User row (para equipment_available, etc.)
            athlete_id: ID do atleta (string, ex: "10")
        """
        block_info = _parse_block_plan(macrocycle_db.block_plan or [])

        # Busca todos os microcycles
        micros = (
            db.query(MicrocycleDB)
            .filter(MicrocycleDB.macrocycle_id == macrocycle_db.id)
            .order_by(MicrocycleDB.start_date)
            .all()
        )

        weeks: list[Week] = []
        primary_focus: list[str] = []
        target_benchmarks: list[str] = []

        for micro in micros:
            week_num = micro.week_index_in_macro

            # Planned sessions deste microcycle
            planned = (
                db.query(PlannedSessionDB)
                .filter(PlannedSessionDB.microcycle_id == micro.id)
                .order_by(PlannedSessionDB.date, PlannedSessionDB.order_in_day)
                .all()
            )

            sessions: list[Session] = []
            for ps in planned:
                template = self._resolve_template(db, ps.generated_template_id)
                session = self._planned_to_session(
                    ps, template, athlete_id,
                    workout_type_override=ps.workout_type,
                )
                sessions.append(session)

            phase = _phase_from_week(block_info, week_num)
            is_deload = (phase == Phase.DELOAD)
            theme = f"Week {week_num}" + (" — DELOAD" if is_deload else "")
            if micro.notes:
                theme = micro.notes

            weeks.append(Week(
                week_number=week_num,
                theme=theme,
                sessions=sessions,
                deload=is_deload,
            ))

            # Extrai primary_focus do primeiro microcycle
            if not primary_focus and micro.intensity_target:
                primary_focus = [micro.intensity_target]

        # Duracao em semanas
        if macrocycle_db.start_date and macrocycle_db.end_date:
            duration_weeks = len(weeks)
        phase = _METHODOLOGY_TO_PHASE.get(block_info[0][0], Phase.BASE)

        return Mesocycle(
            id=str(macrocycle_db.id),
            name=macrocycle_db.name or "Training",
            phase=phase,
            start_date=macrocycle_db.start_date or Date.today(),
            duration_weeks=duration_weeks,
            weeks=weeks,
            primary_focus=primary_focus,
            target_benchmarks=target_benchmarks,
        )

    def _resolve_template(
        self, db: SqlSession, template_id: Optional[UUID]
    ) -> Optional[WorkoutTemplateDB]:
        if not template_id:
            return None
        return db.get(WorkoutTemplateDB, template_id)

    def _planned_to_session(
        self,
        ps: PlannedSessionDB,
        template: Optional[WorkoutTemplateDB],
        athlete_id: str,
        workout_type_override: Optional[str] = None,
    ) -> Session:
        workout_type_str = workout_type_override or ps.workout_type or template.workout_type if template else "strength"

        template_enum = _WORKOUT_TYPE_TO_TEMPLATE.get(workout_type_str, SessionTemplate.OPEN_GYM)
        stimulus_enum = _WORKOUT_TYPE_TO_STIMULUS.get(workout_type_str, Stimulus.MIXED_MODAL)

        # Derivar blocos do template
        blocks = self._template_to_blocks(template, stimulus_enum)

        # Equipment derivacao automatica via library
        movement_ids = [
            mp.movement_id
            for b in blocks
            for mp in b.movements
        ]
        equipment = set(self.library.derive_equipment(movement_ids))
        if template and template.equipment_required:
            equipment.update(template.equipment_required)

        # Duration
        duration = ps.duration_minutes
        if duration is None and blocks:
            duration = sum(b.duration_minutes or 0 for b in blocks)
        if not duration:
            duration = 60

        # Fallback: se _template_to_blocks retornou [], gerar bloco padrao pelo workout_type
        if not blocks:
            # First block must be warmup/mobility per Session validator
            blocks.append(WorkoutBlock(
                order=1, type=BlockType.WARM_UP,
                format=BlockFormat.REPEATS, stimulus=Stimulus.MIXED_MODAL,
                duration_minutes=10, intent="Warm-up", movements=[],
            ))
            if stimulus_enum == Stimulus.STRENGTH_VOLUME:
                blocks.append(WorkoutBlock(
                    order=2, type=BlockType.STRENGTH_PRIMARY,
                    format=BlockFormat.SETS_REPS, stimulus=Stimulus.STRENGTH_VOLUME,
                    duration_minutes=20, intent="Strength", movements=[],
                    rest_seconds=180,
                ))
            elif stimulus_enum == Stimulus.MIXED_MODAL:
                blocks.append(WorkoutBlock(
                    order=2, type=BlockType.METCON,
                    format=BlockFormat.AMRAP, stimulus=Stimulus.MIXED_MODAL,
                    duration_minutes=20, intent="Metcon", movements=[],
                ))
            elif stimulus_enum == Stimulus.AEROBIC_THRESHOLD:
                blocks.append(WorkoutBlock(
                    order=2, type=BlockType.ENGINE,
                    format=BlockFormat.INTERVALS, stimulus=Stimulus.AEROBIC_THRESHOLD,
                    duration_minutes=20, intent="Engine", movements=[],
                ))
            elif stimulus_enum == Stimulus.GYMNASTIC_CAPACITY:
                blocks.append(WorkoutBlock(
                    order=2, type=BlockType.GYMNASTICS,
                    format=BlockFormat.EMOM, stimulus=Stimulus.GYMNASTIC_CAPACITY,
                    duration_minutes=15, intent="Gymnastics", movements=[],
                ))
            elif stimulus_enum == Stimulus.RECOVERY:
                blocks.append(WorkoutBlock(
                    order=2, type=BlockType.MOBILITY,
                    format=BlockFormat.REPEATS, stimulus=Stimulus.RECOVERY,
                    duration_minutes=20, intent="Recovery", movements=[],
                ))
            elif stimulus_enum == Stimulus.SKILL_ACQUISITION:
                blocks.append(WorkoutBlock(
                    order=2, type=BlockType.SKILL,
                    format=BlockFormat.QUALITY, stimulus=Stimulus.SKILL_ACQUISITION,
                    duration_minutes=15, intent="Skill", movements=[],
                ))
            elif stimulus_enum == Stimulus.STRENGTH_MAX:
                blocks.append(WorkoutBlock(
                    order=2, type=BlockType.STRENGTH_PRIMARY,
                    format=BlockFormat.SETS_REPS, stimulus=Stimulus.STRENGTH_MAX,
                    duration_minutes=15, intent="Max effort", movements=[],
                ))
            else:
                blocks.append(WorkoutBlock(
                    order=2, type=BlockType.OPEN_GYM,
                    format=BlockFormat.REPEATS, stimulus=stimulus_enum or Stimulus.MIXED_MODAL,
                    duration_minutes=duration or 30, intent="Open gym", movements=[],
                ))

        return Session(
            id=str(ps.id),
            date=ps.date,
            template=template_enum,
            title=ps.focus or (template.name if template else None) or f"Day {ps.order_in_day}",
            blocks=blocks,
            primary_stimulus=stimulus_enum,
            equipment_required=sorted(equipment),
            estimated_duration_minutes=duration,
        )

    def _template_to_blocks(
        self, template: Optional[WorkoutTemplateDB], stimulus: Stimulus
    ) -> list[WorkoutBlock]:
        """Converte WorkoutTemplateDB (flat movement list) -> list[WorkoutBlock]."""
        if not template:
            return []

        blocks: list[WorkoutBlock] = []
        order = 1

        # Warm-up block (string simples)
        if template.warm_up:
            blocks.append(WorkoutBlock(
                order=order, type=BlockType.WARM_UP,
                duration_minutes=10,
                intent=template.warm_up,
                movements=[],
            ))
            order += 1

        # Main movements → deterministico por workout_type
        movements_data = template.movements or []
        wt = template.workout_type or ""

        if wt in ("strength", "strength_day") or stimulus == Stimulus.STRENGTH_VOLUME:
            blocks.extend(self._build_strength_blocks(order, movements_data))
            order += 2

        elif wt in ("metcon", "metcon_only") or stimulus == Stimulus.MIXED_MODAL:
            blocks.extend(self._build_metcon_blocks(order, movements_data))
            order += 2

        elif wt in ("engine", "engine_day") or stimulus == Stimulus.AEROBIC_THRESHOLD:
            blocks.extend(self._build_engine_blocks(order, movements_data))
            order += 2

        elif wt in ("gymnastics", "gymnastic_day"):
            blocks.extend(self._build_gymnastic_blocks(order, movements_data))
            order += 2

        elif wt == "recovery":
            blocks.append(WorkoutBlock(
                order=order, type=BlockType.MOBILITY,
                duration_minutes=20,
                stimulus=Stimulus.RECOVERY,
                movements=[],
            ))
            order += 1

        else:
            # Generic: coloca todos os movimentos num bloco METCON
            if movements_data:
                block = WorkoutBlock(
                    order=order, type=BlockType.METCON,
                    format=BlockFormat.AMRAP,
                    stimulus=stimulus or Stimulus.MIXED_MODAL,
                    duration_minutes=template.duration_minutes or 20,
                    movements=[_movement_to_mp(m) for m in movements_data],
                )
                blocks.append(block)
                order += 1

        # Cooldown (sempre presente se houve bloco principal)
        if len(blocks) > 1:
            blocks.append(WorkoutBlock(
                order=order, type=BlockType.COOLDOWN,
                duration_minutes=5,
                intent="Down-regulation",
                movements=[],
            ))

        if not blocks:
            blocks.append(WorkoutBlock(
                order=1,
                type=BlockType.OPEN_GYM,
                format=BlockFormat.REPEATS,
                duration_minutes=template.duration_minutes or 30,
                intent="Open gym",
                movements=[],
            ))
        return blocks

    def _build_strength_blocks(
        self, order: int, movements: list[dict]
    ) -> list[WorkoutBlock]:
        """Separa movements em strength_primary (primeiro lift) + accessory."""
        primary_mvs, accessory_mvs = [], []
        for m in movements:
            mv_id = m.get("movement", "")
            # Bar奇lim lifts = primary, acessory sao o resto
            if len(primary_mvs) == 0 and any(
                c in mv_id for c in ["squat", "deadlift", "clean", "snatch", "press", "bench"]
            ):
                primary_mvs.append(m)
            else:
                accessory_mvs.append(m)

        blocks = []
        if primary_mvs:
            blocks.append(WorkoutBlock(
                order=order, type=BlockType.STRENGTH_PRIMARY,
                format=BlockFormat.SETS_REPS,
                stimulus=Stimulus.STRENGTH_VOLUME,
                duration_minutes=20,
                intent="Strength volume",
                movements=[_movement_to_mp(m) for m in primary_mvs],
                rest_seconds=180,
            ))

        if accessory_mvs:
            blocks.append(WorkoutBlock(
                order=order + 1, type=BlockType.ACCESSORY,
                format=BlockFormat.SETS_REPS,
                stimulus=Stimulus.HYPERTROPHY,
                duration_minutes=12,
                intent="Volume complementar",
                movements=[_movement_to_mp(m) for m in accessory_mvs],
            ))

        return blocks

    def _build_metcon_blocks(
        self, order: int, movements: list[dict]
    ) -> list[WorkoutBlock]:
        """Monta um bloco METCON com os movements."""
        if not movements:
            return []
        return [
            WorkoutBlock(
                order=order, type=BlockType.METCON,
                format=BlockFormat.FOR_TIME_CAPPED,
                stimulus=Stimulus.MIXED_MODAL,
                duration_minutes=20,
                intent="Mixed modal conditioning",
                movements=[_movement_to_mp(m) for m in movements],
            )
        ]

    def _build_engine_blocks(
        self, order: int, movements: list[dict]
    ) -> list[WorkoutBlock]:
        """Monta blocos ENGINE + AEROBIC_Z2."""
        return [
            WorkoutBlock(
                order=order, type=BlockType.ENGINE,
                format=BlockFormat.INTERVALS,
                stimulus=Stimulus.AEROBIC_THRESHOLD,
                duration_minutes=30,
                intent="Threshold intervals",
                movements=[_movement_to_mp(m) for m in movements] if movements else [
                    MovementPrescription(movement_id="row", distance_meters=1000)
                ],
                rounds=5, work_seconds=240, rest_seconds=120,
            ),
            WorkoutBlock(
                order=order + 1, type=BlockType.AEROBIC_Z2,
                format=BlockFormat.STEADY,
                stimulus=Stimulus.AEROBIC_Z2,
                duration_minutes=20,
                intent="Base Z2",
                movements=[MovementPrescription(movement_id="bike", time_seconds=1200)],
            ),
        ]

    def _build_gymnastic_blocks(
        self, order: int, movements: list[dict]
    ) -> list[WorkoutBlock]:
        """Monta blocos SKILL + GYMNASTICS."""
        return [
            WorkoutBlock(
                order=order, type=BlockType.SKILL,
                format=BlockFormat.QUALITY,
                stimulus=Stimulus.SKILL_ACQUISITION,
                duration_minutes=12,
                intent="Skill practice",
                movements=[_movement_to_mp(m) for m in movements] if movements else [],
            ),
            WorkoutBlock(
                order=order + 1, type=BlockType.GYMNASTICS,
                format=BlockFormat.EMOM,
                stimulus=Stimulus.GYMNASTIC_CAPACITY,
                duration_minutes=15,
                intent="Gymnastic capacity",
                movements=[],
            ),
        ]
