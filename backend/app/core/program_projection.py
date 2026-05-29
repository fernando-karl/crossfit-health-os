"""
Project a cfai Mesocycle into the backend's periodization tables.

cfai produces a Pydantic Mesocycle (Week → Session → WorkoutBlock →
MovementPrescription). The dashboard surfaces work via the existing
Macrocycle → Microcycle → PlannedSession (+ WorkoutTemplate) tables —
filtered on `active=True` macrocycles and `status in (planned, generated)`
sessions with a non-null `generated_template_id`.

`project_program_to_periodization` walks the cfai Mesocycle and creates
one row per cfai entity, atomically. Any prior active macrocycle for the
user is flipped to active=False so the dashboard query stays unambiguous.
"""
from __future__ import annotations

from datetime import date as _Date, timedelta
from typing import Optional
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.db.models import (
    Macrocycle as MacrocycleDB,
    Microcycle as MicrocycleDB,
    PlannedSession as PlannedSessionDB,
    Program as ProgramDB,
    WorkoutTemplate as WorkoutTemplateDB,
)


# ==========================================================
# Stimulus → workout_type
# ==========================================================

_STIMULUS_TO_WORKOUT_TYPE: dict[str, str] = {
    "strength_max": "strength",
    "strength_volume": "strength",
    "hypertrophy": "strength",
    "power": "strength",
    "aerobic_z2": "conditioning",
    "aerobic_threshold": "conditioning",
    "vo2_max": "metcon",
    "lactic_tolerance": "metcon",
    "alactic_power": "metcon",
    "mixed_modal": "metcon",
    "gymnastic_capacity": "skill",
    "skill_acquisition": "skill",
    "midline_endurance": "skill",
    "recovery": "conditioning",
}


def _workout_type_for(stimulus: Optional[str]) -> str:
    return _STIMULUS_TO_WORKOUT_TYPE.get((stimulus or "").lower(), "mixed")


# ==========================================================
# Phase → intensity/volume targets
# ==========================================================

_PHASE_TARGETS: dict[str, tuple[str, str]] = {
    # phase: (intensity_target, volume_target)
    "base": ("low", "high"),
    "build": ("moderate", "high"),
    "peak": ("high", "moderate"),
    "deload": ("low", "low"),
    "test": ("max", "low"),
}


def _phase_targets(phase: str, deload: bool) -> tuple[str, str]:
    if deload:
        return ("low", "low")
    return _PHASE_TARGETS.get(phase.lower(), ("moderate", "moderate"))


# ==========================================================
# Movement flattening
# ==========================================================

def _load_to_intensity(load: Optional[dict]) -> Optional[str]:
    """Render a cfai LoadSpec dict as a short human string for the flat schema."""
    if not load:
        return None
    t = load.get("type")
    val = load.get("value")
    if t == "absolute_kg" and val is not None:
        return f"{val}kg"
    if t == "percent_1rm" and val is not None:
        ref = load.get("reference_lift") or "1rm"
        return f"{val}% {ref}"
    if t == "percent_bw" and val is not None:
        return f"{val}% BW"
    if t == "rpe" and val is not None:
        return f"RPE {val}"
    if t == "ahap":
        return "AHAP"
    if t == "bodyweight":
        return "BW"
    return None


# Block types whose movements feed `WorkoutTemplate.warm_up` instead of the
# flat movement list — keeps the main MOVEMENTS section focused on the work
# of the day. (Cooldown/mobility stay in the flat list for now.)
_WARMUP_BLOCK_TYPES: frozenset[str] = frozenset({"warm_up", "activation"})


def _humanize(s: str) -> str:
    return s.replace("_", " ").title() if s else ""


def _format_warmup_movement(mp: dict) -> str:
    """Render a single MovementPrescription as a short readable line."""
    name = _humanize(mp.get("movement_id", ""))
    reps = mp.get("reps")
    cals = mp.get("calories")
    dist = mp.get("distance_meters")
    secs = mp.get("time_seconds")

    if reps is not None:
        vol = f"x{reps}"
    elif cals is not None:
        vol = f"{cals} cal"
    elif dist is not None:
        vol = f"{dist}m"
    elif secs is not None:
        vol = f"{secs // 60}:{secs % 60:02d}" if secs >= 60 else f"{secs}s"
    else:
        vol = ""

    pacing = f" {mp['pacing']}" if mp.get("pacing") else ""
    base = f"{name} {vol}".strip()
    return (base + pacing).strip()


def _build_warmup_text(blocks: list[dict]) -> Optional[str]:
    """Concatenate warm-up + activation block movements into a single line.

    Format: 'Row 4:00 easy · World'S Greatest Stretch x10 · Goblet Squat x10'
    Returns None when neither block type is present.
    """
    warm_blocks = [
        b for b in sorted(blocks, key=lambda b: b.get("order", 0))
        if b.get("type") in _WARMUP_BLOCK_TYPES
    ]
    if not warm_blocks:
        return None
    parts: list[str] = []
    for b in warm_blocks:
        for mp in b.get("movements", []):
            line = _format_warmup_movement(mp)
            if line:
                parts.append(line)
    return " · ".join(parts) if parts else None


def _format_block_prescription(block: dict) -> Optional[str]:
    """Render a block's structural prescription as a short readable label.

    Examples:
        AMRAP 10:00, For Time (cap 15:00), EMOM 12:00, 4 × 3:00, Tabata
    Returns None when the format is implied by the per-movement chips
    (e.g. SETS_REPS — "5×3" already shows in the chip), so the caller
    can omit the prefix and avoid noise.
    """
    fmt = (block.get("format") or "").lower()
    dur = block.get("duration_minutes")
    cap = block.get("time_cap_minutes")
    rounds = block.get("rounds")

    def mmss(minutes):
        try:
            m = int(minutes)
            return f"{m}:00"
        except (TypeError, ValueError):
            return str(minutes)

    if fmt == "amrap":
        return f"AMRAP {mmss(dur)}" if dur else "AMRAP"
    if fmt == "for_time_capped":
        return f"For Time (cap {mmss(cap)})" if cap else "For Time (capped)"
    if fmt == "for_time":
        return "For Time"
    if fmt == "emom":
        return f"EMOM {mmss(dur)}" if dur else (
            f"EMOM × {rounds}" if rounds else "EMOM"
        )
    if fmt == "e2mom":
        return f"E2MOM {mmss(dur)}" if dur else "E2MOM"
    if fmt == "e3mom":
        return f"E3MOM {mmss(dur)}" if dur else "E3MOM"
    if fmt == "tabata":
        return "Tabata 8 × :20/:10"
    if fmt == "intervals":
        if rounds and dur:
            try:
                per = int(dur) // int(rounds)
                return f"{rounds} × {per}:00"
            except (TypeError, ValueError, ZeroDivisionError):
                pass
        return "Intervals"
    if fmt == "steady":
        return f"Steady {mmss(dur)}" if dur else "Steady"
    if fmt == "death_by":
        return "Death By"
    if fmt == "chipper":
        return "Chipper"
    if fmt == "ladder":
        return "Ladder"
    if fmt == "repeats":
        return f"{rounds} rounds" if rounds else "Repeats"
    if fmt == "sets_reps":
        return None  # implied by per-movement chips
    if fmt == "not_for_time":
        return "Not For Time"
    if fmt == "quality":
        return "Quality"
    return fmt.upper() if fmt else None


def _flatten_movements(blocks: list[dict]) -> list[dict]:
    """Flatten cfai blocks into the dashboard's flat Movement[] schema.

    Warm-up and activation blocks are excluded — they're rendered as text
    in `WorkoutTemplate.warm_up` instead, so the main MOVEMENTS section
    only shows the actual work of the day.

    Block grouping metadata (block_id, block_label, block_prescription,
    block_intent, block_rest_seconds) is denormalized onto each movement
    so the drawer can re-group them and render a single block header
    instead of repeating "metcon | AMRAP 10:00 | …" on every line. The
    `notes` field carries only movement-specific notes — block prefix
    moved to dedicated fields. Lossless copy stays in `Program.mesocycle`.
    """
    out: list[dict] = []
    for block in sorted(blocks, key=lambda b: b.get("order", 0)):
        if block.get("type") in _WARMUP_BLOCK_TYPES:
            continue
        block_label = block.get("type", "block")
        # Replace raw enum (e.g. "amrap") with a structural label that
        # carries the timer / cap / rounds — otherwise "AMRAP" with no
        # duration looks like a rep-bound prescription.
        block_fmt_label = _format_block_prescription(block)
        block_intent = block.get("intent")
        block_rest = block.get("rest_seconds")
        # Stable per-block id derived from order + type. Same input → same
        # id, so re-flattening doesn't churn the value.
        block_id = f"b{block.get('order', 0)}_{block_label}"
        for mp in block.get("movements", []):
            reps = mp.get("reps")
            time_seconds = mp.get("time_seconds")
            distance = mp.get("distance_meters")
            cals = mp.get("calories")

            reps_value: Optional[int | str] = None
            reps_unit = "reps"
            duration: Optional[float] = None
            if reps is not None:
                reps_value = int(reps)
                reps_unit = "reps"
            elif cals is not None:
                reps_value = int(cals)
                reps_unit = "cal"
            elif distance is not None:
                reps_unit = "m"
                # distance lives in distance_meters, not reps
            elif time_seconds is not None:
                duration = float(time_seconds)

            # Movement-specific notes only — block prefix lives in
            # dedicated block_* fields below so the renderer can group.
            mov_notes = mp.get("notes") or None

            out.append({
                "movement": mp.get("movement_id", "unknown"),
                "sets": None,
                "reps": reps_value,
                "reps_unit": reps_unit,
                "weight_kg": None,
                "distance_meters": float(distance) if distance is not None else None,
                "duration_seconds": duration,
                "rest": None,
                "intensity": _load_to_intensity(mp.get("load")),
                "notes": mov_notes,
                "block_id": block_id,
                "block_label": block_label,
                "block_prescription": block_fmt_label,
                "block_intent": block_intent,
                "block_rest_seconds": block_rest,
            })
    return out


# ==========================================================
# Build block_plan from the cfai spec
# ==========================================================

# cfai Phase → backend BlockType. The backend's BlockPlanItem uses
# Tudor-Bompa block types; cfai uses HWPO-style phase names. Mapping below.
_CFAI_PHASE_TO_BLOCK_TYPE: dict[str, str] = {
    "base":   "accumulation",
    "build":  "intensification",
    "peak":   "realization",
    "deload": "deload",
    "test":   "test",
}


def _block_type_for_phase(phase: str) -> str:
    return _CFAI_PHASE_TO_BLOCK_TYPE.get(phase.lower(), "accumulation")


def _build_block_plan(spec: dict) -> list[dict]:
    """Group consecutive same-phase weeks into block_plan entries.

    Output shape matches the backend's BlockPlanItem ({"type", "weeks"})
    so the schedule API can deserialize macrocycles created by program
    activation without a special case.
    """
    weeks = spec.get("weeks", [])
    out: list[dict] = []
    if not weeks:
        return out
    current_phase = weeks[0]
    count = 0
    for phase in weeks:
        if phase == current_phase:
            count += 1
        else:
            out.append({
                "type": _block_type_for_phase(current_phase),
                "weeks": count,
            })
            current_phase = phase
            count = 1
    out.append({
        "type": _block_type_for_phase(current_phase),
        "weeks": count,
    })
    return out


# ==========================================================
# Main projection
# ==========================================================

def project_program_to_periodization(db: Session, program: ProgramDB) -> dict:
    """Create Macrocycle/Microcycle/PlannedSession/WorkoutTemplate rows.

    Returns a dict with the new IDs + counts. Caller is responsible for
    committing — this function flushes only.
    """
    user_id = program.user_id
    spec = program.spec or {}
    meso = program.mesocycle or {}
    weeks_data = meso.get("weeks", [])
    deload_set = set(spec.get("deload_weeks", []))

    # Deactivate prior macrocycles for this user
    db.execute(
        update(MacrocycleDB)
        .where(MacrocycleDB.user_id == user_id, MacrocycleDB.active.is_(True))
        .values(active=False)
    )

    # Macrocycle
    duration = program.duration_weeks
    end_date = program.start_date + timedelta(days=duration * 7 - 1)
    macro = MacrocycleDB(
        user_id=user_id,
        name=program.name,
        methodology="custom",
        start_date=program.start_date,
        end_date=end_date,
        block_plan=_build_block_plan(spec),
        goal=", ".join(program.primary_focus or []) or None,
        training_days_per_week=program.sessions_per_week,
        active=True,
    )
    db.add(macro)
    db.flush()  # populate macro.id

    micro_count = 0
    template_count = 0
    planned_count = 0

    for week_data in weeks_data:
        wnum = week_data.get("week_number", 1)
        week_start = program.start_date + timedelta(days=(wnum - 1) * 7)
        week_end = week_start + timedelta(days=6)
        deload_flag = bool(week_data.get("deload")) or wnum in deload_set
        intensity_target, volume_target = _phase_targets(program.phase, deload_flag)

        micro = MicrocycleDB(
            macrocycle_id=macro.id,
            user_id=user_id,
            start_date=week_start,
            end_date=week_end,
            week_index_in_macro=wnum,
            intensity_target=intensity_target,
            volume_target=volume_target,
            notes=week_data.get("theme"),
        )
        db.add(micro)
        db.flush()
        micro_count += 1

        # Group sessions by date so order_in_day stays unique on the same day
        sessions = week_data.get("sessions", [])
        per_day_count: dict[str, int] = {}
        for sess in sessions:
            sess_date_raw = sess.get("date")
            sess_date = (
                _Date.fromisoformat(sess_date_raw)
                if isinstance(sess_date_raw, str)
                else sess_date_raw
            )
            day_key = sess_date.isoformat() if sess_date else "x"
            per_day_count[day_key] = per_day_count.get(day_key, 0) + 1
            order_in_day = per_day_count[day_key]

            stimulus = sess.get("primary_stimulus")
            wtype = _workout_type_for(stimulus)
            template_label = sess.get("template", "session")

            blocks = sess.get("blocks", [])
            equipment = sess.get("equipment_required", []) or []
            duration_min = sess.get("estimated_duration_minutes") or 60
            title = sess.get("title") or f"{template_label} W{wnum}D{order_in_day}"

            tpl = WorkoutTemplateDB(
                owner_user_id=user_id,
                name=title,
                description=f"cfai program {program.id} · week {wnum} · day {order_in_day}",
                methodology="custom",
                difficulty_level="rx",
                workout_type=wtype,
                duration_minutes=duration_min,
                movements=_flatten_movements(blocks),
                target_stimulus=stimulus,
                rep_scheme=None,
                warm_up=_build_warmup_text(blocks),
                tags=[t for t in [stimulus, template_label] if t],
                equipment_required=equipment,
                is_public=False,
            )
            db.add(tpl)
            db.flush()
            template_count += 1

            ps = PlannedSessionDB(
                microcycle_id=micro.id,
                user_id=user_id,
                date=sess_date,
                order_in_day=order_in_day,
                duration_minutes=duration_min,
                workout_type=wtype,
                focus=stimulus,
                notes=title,
                status="planned",
                generated_template_id=tpl.id,
            )
            db.add(ps)
            db.flush()
            planned_count += 1

    return {
        "macrocycle_id": macro.id,
        "microcycles": micro_count,
        "workout_templates": template_count,
        "planned_sessions": planned_count,
    }
