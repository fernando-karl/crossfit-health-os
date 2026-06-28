"""
Programmer skeleton — gera Session a partir de Athlete + Phase + contexto.

Arquitetura:
  ProgrammingContext (input)
    → SessionPlanner.plan_session()
        → _select_template()  : determina SessionTemplate (Strength/Engine/...)
        → _scaffold_blocks()  : lista ordenada de (BlockType, BlockHints)
        → composer.compose_block(): preenche cada bloco com movimentos/cargas
    → Session (output, validada)

Composer é um Protocol — HeuristicComposer (rule-based) vem incluso.
ClaudeComposer (chama Anthropic API) é stub documentado para Karl plugar.

Princípio: tudo determinístico no skeleton (template + scaffold + heurística),
IA entra apenas no composer onde criatividade adiciona valor (movement selection,
intent narrativo, scaling contextual).
"""

from dataclasses import dataclass, field
from datetime import date as Date
from typing import Optional, Protocol

from .athlete import Athlete
from .movements import Movement, MovementLibrary
from .session_builder import build_session
from .workout_schema import (
    BlockFormat, BlockType, LoadSpec, MovementPrescription,
    Phase, ScalingTier, Session, SessionTemplate, Stimulus, WorkoutBlock,
)


# ============================================================
# PHASE-AWARE STRENGTH PRESCRIPTION (Sprint 6a)
# ============================================================
#
# Substitui a regra única do MVP (`70 + 2.5*W` em BUILD, 75% senão).
# Tabela baseada em literatura de periodização (Prilepin + block periodization
# clássica de Stone/Issurin). week_number=1..N (1-indexed dentro do mesociclo).
#
# Contrato: cada entry é (pct_1rm, sets, reps, rest_seconds). A função
# strength_primary_prescription() resolve phase × week → entry, lidando com
# (a) deload override, (b) clamping de week_number, (c) test week.

@dataclass(frozen=True)
class StrengthRx:
    """Prescrição de strength block determinística por phase × week."""
    pct_1rm: float       # 0-100
    sets: int            # 3-8 típico
    reps: int            # 1-10 típico
    rest_seconds: int    # 90-300


# Prilepin chart (Sprint 6c): (pct_max_exclusive, sets, reps).
# Total-reps cap por zona mantém INOL ≤ 1.0. Fonte de verdade única para
# dosing baseado em %1RM. BUILD deriva daqui; PEAK/BASE deliberadamente
# divergem (taper / hipertrofia).
_PRILEPIN_SCHEME: tuple[tuple[float, int, int], ...] = (
    (75.0,  5, 5),   # <75%:   25 reps
    (80.0,  5, 4),   # 75-79%: 20 reps
    (85.0,  5, 3),   # 80-84%: 15 reps
    (90.0,  4, 3),   # 85-89%: 12 reps
    (100.0, 4, 2),   # 90%+:    8 reps
)


def _scheme_for(pct: float) -> tuple[int, int]:
    """Resolve (sets, reps) a partir do %1RM via _PRILEPIN_SCHEME."""
    for cutoff, sets, reps in _PRILEPIN_SCHEME:
        if pct < cutoff:
            return sets, reps
    return _PRILEPIN_SCHEME[-1][1:]  # fallback for pct ≥100


def _rx(pct: float, rest: int) -> StrengthRx:
    """Constrói StrengthRx com (sets, reps) derivados da Prilepin chart."""
    s, r = _scheme_for(pct)
    return StrengthRx(pct, s, r, rest)


# BUILD: progressive overload, volume + intensification.
# (sets, reps) derivam de _PRILEPIN_SCHEME. INOL fica em [0.4, 1.0] por
# construção. Legacy 5×5 fixo estourava em W2-W4 (1.00 / 1.11 / 1.25).
_BUILD_RAMP: tuple[StrengthRx, ...] = (
    _rx(72.5, 180),  # W1 — 5×5 (INOL 0.91)
    _rx(75.0, 180),  # W2 — 5×4 (INOL 0.80)
    _rx(77.5, 180),  # W3 — 5×4 (INOL 0.89)
    _rx(80.0, 180),  # W4 — 5×3 (INOL 0.75)
)

# PEAK: alta intensidade, baixo volume, expressão de força.
# Volume cai (sets×reps), intensidade sobe (90%+).
_PEAK_RAMP: tuple[StrengthRx, ...] = (
    StrengthRx(82.5, 5, 3, 240),  # W1
    StrengthRx(85.0, 4, 3, 240),  # W2
    StrengthRx(87.5, 4, 2, 270),  # W3
    StrengthRx(90.0, 3, 2, 300),  # W4 (test segue, mas se ainda peak: top single approach)
)

# BASE: acumulação, volume + técnica. Intensidade baixa-moderada.
# 4-5 séries de 8-10 reps em 65-72%.
_BASE_RAMP: tuple[StrengthRx, ...] = (
    StrengthRx(65.0, 4, 10, 120),  # W1
    StrengthRx(67.5, 5, 8, 120),   # W2
    StrengthRx(70.0, 5, 8, 150),   # W3
    StrengthRx(72.5, 4, 8, 150),   # W4
)

# DELOAD: ~50% do volume típico, intensidade moderada.
_DELOAD_RX = StrengthRx(65.0, 3, 5, 180)

# TEST: top single approach (90% × 1, depois prepara abertura).
_TEST_RX = StrengthRx(90.0, 1, 1, 300)


def strength_primary_prescription(
    phase: Phase, week_number: int, *, deload: bool = False,
) -> StrengthRx:
    """Resolve phase × week → StrengthRx.

    - deload=True override → _DELOAD_RX (independe de phase).
    - week_number é 1-indexed; clampeado a [1, len(ramp)] dentro de cada phase.
    - TEST e DELOAD têm prescrição única (não rampam).
    """
    if deload or phase == Phase.DELOAD:
        return _DELOAD_RX
    if phase == Phase.TEST:
        return _TEST_RX

    ramp_by_phase = {
        Phase.BUILD: _BUILD_RAMP,
        Phase.PEAK: _PEAK_RAMP,
        Phase.BASE: _BASE_RAMP,
    }
    ramp = ramp_by_phase.get(phase, _BUILD_RAMP)  # default razoável
    idx = max(1, min(week_number, len(ramp))) - 1
    return ramp[idx]


# ============================================================
# PHASE-AWARE STRENGTH SECONDARY (Sprint 6b)
# ============================================================
#
# Acessório/complementar — RPE-based (sem %1RM porque movimento varia).
# PEAK: menos volume, mais intensidade subjetiva. BASE: mais volume.

@dataclass(frozen=True)
class SecondaryRx:
    sets: int
    reps: int
    rpe: float
    rest_seconds: int


_SECONDARY_BY_PHASE: dict[Phase, "SecondaryRx"] = {
    Phase.BUILD:  SecondaryRx(sets=4, reps=8,  rpe=7.0, rest_seconds=90),
    Phase.PEAK:   SecondaryRx(sets=3, reps=5,  rpe=8.0, rest_seconds=120),
    Phase.BASE:   SecondaryRx(sets=5, reps=10, rpe=6.5, rest_seconds=75),
    Phase.DELOAD: SecondaryRx(sets=2, reps=8,  rpe=6.0, rest_seconds=120),
    Phase.TEST:   SecondaryRx(sets=3, reps=5,  rpe=8.0, rest_seconds=150),
}


def strength_secondary_prescription(phase: Phase) -> SecondaryRx:
    return _SECONDARY_BY_PHASE.get(phase, _SECONDARY_BY_PHASE[Phase.BUILD])


# ============================================================
# LOAD HELPERS
# ============================================================

def recommended_absolute_load(movement: Movement, athlete) -> LoadSpec:
    """Absolute load for a non-barbell loaded movement, scaled to bodyweight.

    Non-barbell implements (KB/DB) have no 1RM, so percent_1rm is meaningless —
    they take a prescribed absolute weight. Scale it to bodyweight and round to
    a realistic increment: kettlebells come in 4kg steps (~0.30×BW), dumbbells
    in 2.5kg steps per hand (~0.28×BW). Movements without a clear external load
    (odd object / accessory) fall back to RPE.
    """
    bw = athlete.body_weight_kg
    if movement.category == "kettlebell":
        return LoadSpec(type="absolute_kg", value=max(4.0, round(bw * 0.30 / 4.0) * 4.0))
    if movement.category == "dumbbell":
        return LoadSpec(type="absolute_kg", value=round(max(2.5, round(bw * 0.28 / 2.5) * 2.5), 1))
    return LoadSpec(type="rpe", value=7.0)


# ============================================================
# SCALING HELPERS (Sprint 5a)
# ============================================================

def expand_scaling(
    base: MovementPrescription, movement: Movement,
) -> dict[ScalingTier, MovementPrescription]:
    """Expande Movement.default_scaling em MovementPrescription.scaling.

    Para cada tier presente em movement.default_scaling, monta uma
    MovementPrescription derivada do `base` aplicando substituição de
    movimento, load_factor e reps_factor do MovementScaling.

    Movimentos sem default_scaling retornam dict vazio — não força scaling
    artificial. Composers podem complementar manualmente.
    """
    out: dict[ScalingTier, MovementPrescription] = {}
    for tier, ms in movement.default_scaling.items():
        sub_id = ms.substitute_movement_id or base.movement_id
        substituting = sub_id != base.movement_id

        new_load = base.load
        # Substituição de movimento invalida percent_1rm com reference_lift
        # original (ex.: 75% back_squat não traduz pra goblet_squat). Cai pra
        # RPE/AHAP — o atleta calibra pelo RPE alvo.
        if substituting and base.load and base.load.type == "percent_1rm":
            new_load = LoadSpec(type="rpe", value=7.0)
        elif (base.load and ms.load_factor
                and base.load.type in ("absolute_kg", "percent_1rm", "percent_bw")
                and base.load.value is not None):
            new_load = LoadSpec(
                type=base.load.type,
                value=round(base.load.value * ms.load_factor, 1),
                reference_lift=base.load.reference_lift,
            )

        new_reps = base.reps
        if base.reps is not None and ms.reps_factor:
            new_reps = max(1, int(round(base.reps * ms.reps_factor)))

        out[tier] = MovementPrescription(
            movement_id=sub_id,
            reps=new_reps,
            time_seconds=base.time_seconds,
            distance_meters=base.distance_meters,
            calories=base.calories,
            load=new_load,
            pacing=base.pacing,
            tempo=base.tempo,
            notes=ms.notes or base.notes,
        )
    return out


# ============================================================
# CONTEXTO E HINTS
# ============================================================

@dataclass
class ProgrammingContext:
    """Tudo que o programmer precisa para decidir."""
    athlete: Athlete
    library: MovementLibrary
    phase: Phase
    week_number: int                                 # dentro do mesociclo
    day_number: int                                  # 1-7 dentro da semana
    target_date: Date
    weekly_focus: list[str] = field(default_factory=list)  # ["squat_volume"]
    recent_sessions: list[Session] = field(default_factory=list)  # últimos 7-14d
    available_minutes: int = 60


@dataclass
class BlockHints:
    """Pistas para o composer preencher um bloco."""
    target_stimulus: Optional[Stimulus] = None
    target_tags: list[str] = field(default_factory=list)        # ["overhead"]
    target_modalities: list[str] = field(default_factory=list)  # ["W", "G"]
    target_format: Optional[BlockFormat] = None
    duration_minutes: Optional[int] = None
    intent: Optional[str] = None
    rounds: Optional[int] = None
    rpe: Optional[float] = None


# ============================================================
# COMPOSER INTERFACE
# ============================================================

class MovementComposer(Protocol):
    """Interface para preencher um bloco. Plug Claude API aqui."""

    def compose_block(
        self, *, order: int, block_type: BlockType,
        hints: BlockHints, ctx: ProgrammingContext,
    ) -> WorkoutBlock: ...


# ============================================================
# PLANNER
# ============================================================

class SessionPlanner:
    """Skeleton de programmer — determinístico no esqueleto, IA no composer."""

    # Split semanal default (5 dias on, sáb recovery, dom open gym)
    DEFAULT_WEEKLY_PATTERN: dict[int, SessionTemplate] = {
        1: SessionTemplate.STRENGTH_DAY,
        2: SessionTemplate.METCON_ONLY,
        3: SessionTemplate.ENGINE_DAY,
        4: SessionTemplate.STRENGTH_DAY,
        5: SessionTemplate.GYMNASTIC_DAY,
        6: SessionTemplate.RECOVERY,
        7: SessionTemplate.OPEN_GYM,
    }

    def __init__(self, library: MovementLibrary, composer: MovementComposer):
        self.library = library
        self.composer = composer

    # ---------- API pública ----------

    def plan_session(self, ctx: ProgrammingContext) -> Session:
        template = self._select_template(ctx)
        scaffold = self._scaffold_blocks(template, ctx)

        blocks = []
        for order, (block_type, hints) in enumerate(scaffold, start=1):
            block = self.composer.compose_block(
                order=order, block_type=block_type, hints=hints, ctx=ctx,
            )
            blocks.append(block)

        return build_session(
            id=f"sess_w{ctx.week_number}_d{ctx.day_number}",
            date=ctx.target_date,
            template=template,
            title=self._title_for(template, ctx),
            blocks=blocks,
            primary_stimulus=self._primary_stimulus(template, ctx),
            library=self.library,
        )

    # ---------- Decisão de template ----------

    def _select_template(self, ctx: ProgrammingContext) -> SessionTemplate:
        # Deload week → tudo vira recovery/open gym (exceto 1 strength leve)
        if ctx.phase == Phase.DELOAD:
            if ctx.day_number in (1, 4):
                return SessionTemplate.STRENGTH_DAY  # leve, deload table
            if ctx.day_number == 3:
                return SessionTemplate.SKILL_DAY
            if ctx.day_number in (6, 7):
                return SessionTemplate.OPEN_GYM
            return SessionTemplate.RECOVERY

        # Test week
        if ctx.phase == Phase.TEST:
            return SessionTemplate.TEST_DAY if ctx.day_number <= 5 else SessionTemplate.RECOVERY

        # Peak: mais comp_sim no fim de semana
        if ctx.phase == Phase.PEAK and ctx.day_number == 5:
            return SessionTemplate.COMP_SIM

        return self.DEFAULT_WEEKLY_PATTERN.get(
            ctx.day_number, SessionTemplate.OPEN_GYM
        )

    # ---------- Scaffolding ----------

    def _scaffold_blocks(
        self, template: SessionTemplate, ctx: ProgrammingContext
    ) -> list[tuple[BlockType, BlockHints]]:
        """Retorna lista ordenada de (BlockType, BlockHints) para o template."""

        if template == SessionTemplate.STRENGTH_DAY:
            return [
                (BlockType.WARM_UP, BlockHints(duration_minutes=10)),
                (BlockType.ACTIVATION, BlockHints(duration_minutes=5)),
                (BlockType.STRENGTH_PRIMARY, BlockHints(
                    duration_minutes=20,
                    target_stimulus=Stimulus.STRENGTH_VOLUME,
                    target_tags=self._strength_focus_tags(ctx),
                    target_format=BlockFormat.SETS_REPS,
                )),
                (BlockType.STRENGTH_SECONDARY, BlockHints(
                    duration_minutes=12,
                    target_stimulus=Stimulus.HYPERTROPHY,
                    rpe=7.0,
                )),
                (BlockType.METCON, BlockHints(
                    duration_minutes=10,
                    target_stimulus=Stimulus.MIXED_MODAL,
                    target_format=BlockFormat.AMRAP,
                    rpe=7.5,
                )),
                (BlockType.COOLDOWN, BlockHints(duration_minutes=5)),
            ]

        if template == SessionTemplate.METCON_ONLY:
            return [
                (BlockType.WARM_UP, BlockHints(duration_minutes=12)),
                (BlockType.METCON, BlockHints(
                    duration_minutes=20,
                    target_stimulus=Stimulus.MIXED_MODAL,
                    target_format=BlockFormat.FOR_TIME_CAPPED,
                    rpe=8.5,
                )),
                (BlockType.MIDLINE, BlockHints(
                    duration_minutes=8,
                    target_stimulus=Stimulus.MIDLINE_ENDURANCE,
                    rounds=3,
                )),
                (BlockType.COOLDOWN, BlockHints(duration_minutes=5)),
            ]

        if template == SessionTemplate.ENGINE_DAY:
            return [
                (BlockType.WARM_UP, BlockHints(duration_minutes=12)),
                (BlockType.ENGINE, BlockHints(
                    duration_minutes=30,
                    target_stimulus=Stimulus.AEROBIC_THRESHOLD,
                    target_format=BlockFormat.INTERVALS,
                    rounds=5, rpe=8.0,
                )),
                (BlockType.AEROBIC_Z2, BlockHints(
                    duration_minutes=20,
                    target_stimulus=Stimulus.AEROBIC_Z2,
                    target_format=BlockFormat.STEADY,
                )),
                (BlockType.COOLDOWN, BlockHints(duration_minutes=5)),
            ]

        if template == SessionTemplate.GYMNASTIC_DAY:
            return [
                (BlockType.WARM_UP, BlockHints(duration_minutes=10)),
                (BlockType.SKILL, BlockHints(
                    duration_minutes=12,
                    target_stimulus=Stimulus.SKILL_ACQUISITION,
                    target_modalities=["G"],
                )),
                (BlockType.GYMNASTICS, BlockHints(
                    duration_minutes=15,
                    target_stimulus=Stimulus.GYMNASTIC_CAPACITY,
                    target_modalities=["G"],
                    target_format=BlockFormat.EMOM,
                )),
                (BlockType.METCON, BlockHints(
                    duration_minutes=10,
                    target_stimulus=Stimulus.MIXED_MODAL,
                    target_format=BlockFormat.AMRAP,
                )),
                (BlockType.COOLDOWN, BlockHints(duration_minutes=5)),
            ]

        if template == SessionTemplate.RECOVERY:
            return [
                (BlockType.MOBILITY, BlockHints(duration_minutes=20)),
                (BlockType.COOLDOWN, BlockHints(duration_minutes=10)),
            ]

        if template == SessionTemplate.OPEN_GYM:
            return []  # sem blocos pré-definidos

        # TEST_DAY, COMP_SIM, SKILL_DAY → fallback genérico
        return [
            (BlockType.WARM_UP, BlockHints(duration_minutes=10)),
            (BlockType.METCON, BlockHints(duration_minutes=20)),
            (BlockType.COOLDOWN, BlockHints(duration_minutes=5)),
        ]

    # ---------- Decisões auxiliares ----------

    def _strength_focus_tags(self, ctx: ProgrammingContext) -> list[str]:
        """Mapeia weekly_focus → tags de movimento."""
        focus = " ".join(ctx.weekly_focus).lower()
        if "squat" in focus:
            return ["squatting", "knee_dominant"]
        if "pull" in focus or "deadlift" in focus:
            return ["hip_hinge", "pulling_vertical"]
        if "press" in focus or "overhead" in focus:
            return ["pressing_vertical", "overhead"]
        # Default: alterna por dia (ímpar=squat, par=pull)
        return ["squatting"] if ctx.day_number % 2 == 1 else ["hip_hinge"]

    def _primary_stimulus(
        self, template: SessionTemplate, ctx: ProgrammingContext
    ) -> Stimulus:
        mapping = {
            SessionTemplate.STRENGTH_DAY: Stimulus.STRENGTH_VOLUME,
            SessionTemplate.METCON_ONLY: Stimulus.MIXED_MODAL,
            SessionTemplate.ENGINE_DAY: Stimulus.AEROBIC_THRESHOLD,
            SessionTemplate.GYMNASTIC_DAY: Stimulus.GYMNASTIC_CAPACITY,
            SessionTemplate.RECOVERY: Stimulus.RECOVERY,
            SessionTemplate.OPEN_GYM: Stimulus.RECOVERY,
            SessionTemplate.SKILL_DAY: Stimulus.SKILL_ACQUISITION,
            SessionTemplate.TEST_DAY: Stimulus.STRENGTH_MAX,
            SessionTemplate.COMP_SIM: Stimulus.MIXED_MODAL,
        }
        return mapping.get(template, Stimulus.MIXED_MODAL)

    def _title_for(
        self, template: SessionTemplate, ctx: ProgrammingContext
    ) -> str:
        return f"W{ctx.week_number}D{ctx.day_number} — {template.value}"


# ============================================================
# HEURISTIC COMPOSER (MVP rule-based)
# ============================================================

class HeuristicComposer:
    """Composer determinístico baseado em regras + filtros da library.

    Filtra movimentos por (a) equipment do atleta, (b) injuries ativas,
    (c) tags/modalities das hints. Pega primeiro match para reprodutibilidade.
    """

    def __init__(self, library: MovementLibrary):
        self.library = library

    def compose_block(
        self, *, order: int, block_type: BlockType,
        hints: BlockHints, ctx: ProgrammingContext,
    ) -> WorkoutBlock:
        candidates = self._candidate_movements(hints, ctx)

        if block_type == BlockType.WARM_UP:
            return self._warm_up_block(order, hints, ctx)
        if block_type == BlockType.ACTIVATION:
            return self._activation_block(order, hints, ctx)
        if block_type == BlockType.COOLDOWN:
            return self._cooldown_block(order, hints)
        if block_type == BlockType.MOBILITY:
            return self._mobility_block(order, hints)
        if block_type == BlockType.STRENGTH_PRIMARY:
            return self._strength_primary_block(order, hints, ctx, candidates)
        if block_type == BlockType.STRENGTH_SECONDARY:
            return self._strength_secondary_block(order, hints, ctx, candidates)
        if block_type == BlockType.METCON:
            return self._metcon_block(order, hints, ctx, candidates)
        if block_type == BlockType.ENGINE:
            return self._engine_block(order, hints)
        if block_type == BlockType.AEROBIC_Z2:
            return self._z2_block(order, hints)
        if block_type == BlockType.SKILL:
            return self._skill_block(order, hints, ctx)
        if block_type == BlockType.GYMNASTICS:
            return self._gym_capacity_block(order, hints, candidates)
        if block_type == BlockType.MIDLINE:
            return self._midline_block(order, hints)

        # Fallback genérico
        return WorkoutBlock(order=order, type=block_type, duration_minutes=hints.duration_minutes or 5)

    # ---------- Filtragem ----------

    def _candidate_movements(
        self, hints: BlockHints, ctx: ProgrammingContext
    ) -> list[Movement]:
        # Por equipamento
        movs = self.library.filter_by_equipment(ctx.athlete.equipment_available)
        # Por modalidade (se especificado)
        if hints.target_modalities:
            movs = [
                m for m in movs
                if any(mod in hints.target_modalities for mod in m.modalities)
            ]
        # Por tag (se especificado)
        if hints.target_tags:
            movs = [m for m in movs if any(t in m.tags for t in hints.target_tags)]
        # Excluir movimentos restritos por injury
        movs = [m for m in movs if not self._is_restricted(m, ctx.athlete)]
        # Excluir warmup-only
        movs = [m for m in movs if not m.is_warmup_only]
        return movs

    def _is_restricted(self, movement: Movement, athlete: Athlete) -> bool:
        for inj in athlete.active_injuries:
            if inj.resolved_date is not None:
                continue
            if movement.id in inj.affected_movements:
                return True
            if any(p in movement.tags for p in inj.affected_patterns):
                return True
        return False

    # ---------- Builders por tipo ----------

    def _warm_up_block(
        self, order: int, hints: BlockHints, ctx: ProgrammingContext
    ) -> WorkoutBlock:
        cardio = "row" if "rower" in ctx.athlete.equipment_available else "run"
        return WorkoutBlock(
            order=order, type=BlockType.WARM_UP,
            duration_minutes=hints.duration_minutes or 10,
            intent="Elevar temperatura, ROM completo",
            movements=[
                MovementPrescription(movement_id=cardio, time_seconds=240, pacing="easy"),
                MovementPrescription(movement_id="world_greatest_stretch", reps=10),
                MovementPrescription(movement_id="cossack_squat", reps=10),
            ],
        )

    def _activation_block(self, order: int, hints: BlockHints, ctx: ProgrammingContext) -> WorkoutBlock:
        # Sprint 5a: glute_bridge é bodyweight; banded_glute_bridge só se band disponível
        glute_id = (
            "banded_glute_bridge"
            if "band" in ctx.athlete.equipment_available
            else "glute_bridge"
        )
        return WorkoutBlock(
            order=order, type=BlockType.ACTIVATION,
            format=BlockFormat.NOT_FOR_TIME,
            duration_minutes=hints.duration_minutes or 5,
            intent="Ativação posterior + core",
            movements=[
                MovementPrescription(
                    movement_id=glute_id, reps=15,
                    load=LoadSpec(type="bodyweight"),
                ),
                MovementPrescription(
                    movement_id="dead_bug", reps=10,
                    load=LoadSpec(type="bodyweight"),
                ),
            ],
        )

    def _cooldown_block(self, order: int, hints: BlockHints) -> WorkoutBlock:
        return WorkoutBlock(
            order=order, type=BlockType.COOLDOWN,
            duration_minutes=hints.duration_minutes or 5,
            intent="Down-regulation",
            movements=[
                MovementPrescription(movement_id="couch_stretch", time_seconds=120),
                MovementPrescription(movement_id="box_breathing", time_seconds=180),
            ],
        )

    def _mobility_block(self, order: int, hints: BlockHints) -> WorkoutBlock:
        return WorkoutBlock(
            order=order, type=BlockType.MOBILITY,
            duration_minutes=hints.duration_minutes or 20,
            intent="Mobilidade de quadril, tornozelo, ombro",
            movements=[
                MovementPrescription(movement_id="couch_stretch", time_seconds=180),
                MovementPrescription(movement_id="cossack_squat", reps=10),
                MovementPrescription(movement_id="world_greatest_stretch", reps=10),
            ],
        )

    def _strength_primary_block(
        self, order: int, hints: BlockHints, ctx: ProgrammingContext,
        candidates: list[Movement],
    ) -> WorkoutBlock:
        # Pick first candidate em barbell
        barbell_candidates = [m for m in candidates if m.category == "barbell"]
        chosen = barbell_candidates[0] if barbell_candidates else candidates[0]

        # Sprint 6a: phase-aware. BUILD mantém 5x5 ramp; PEAK/BASE/DELOAD/TEST
        # ganham curvas próprias via strength_primary_prescription().
        rx = strength_primary_prescription(ctx.phase, ctx.week_number)
        sets = []
        for _ in range(rx.sets):
            # percent_1rm only makes sense for barbell lifts (a real 1RM). If
            # the primary fell back to a non-barbell movement, prescribe an
            # absolute load scaled to bodyweight instead of "% of KB-swing 1RM".
            load = (
                LoadSpec(type="percent_1rm", value=rx.pct_1rm, reference_lift=chosen.id)
                if chosen.category == "barbell"
                else recommended_absolute_load(chosen, ctx.athlete)
            )
            base = MovementPrescription(
                movement_id=chosen.id, reps=rx.reps, load=load,
            )
            base = base.model_copy(update={"scaling": expand_scaling(base, chosen)})
            sets.append(base)

        # Intent reflete o phase pra LLMs/judges entenderem o estímulo
        intent_by_phase = {
            Phase.BUILD: f"Strength volume — {chosen.name}",
            Phase.PEAK: f"Strength peak (high intensity) — {chosen.name}",
            Phase.BASE: f"Strength base (volume accumulation) — {chosen.name}",
            Phase.DELOAD: f"Deload (active recovery) — {chosen.name}",
            Phase.TEST: f"Strength test (1RM expression) — {chosen.name}",
        }

        return WorkoutBlock(
            order=order, type=BlockType.STRENGTH_PRIMARY,
            format=BlockFormat.SETS_REPS,
            stimulus=hints.target_stimulus,
            duration_minutes=hints.duration_minutes,
            intent=hints.intent or intent_by_phase.get(
                ctx.phase, f"Strength — {chosen.name}",
            ),
            movements=sets,
            rest_seconds=rx.rest_seconds,
        )

    def _strength_secondary_block(
        self, order: int, hints: BlockHints, ctx: ProgrammingContext,
        candidates: list[Movement],
    ) -> WorkoutBlock:
        # Pick algo complementar (RDL se squat, etc.)
        accessories = [m for m in candidates if m.category in ("dumbbell", "kettlebell", "accessory")]
        chosen = accessories[0] if accessories else candidates[-1]

        # Sprint 6b: phase-aware accessory volume.
        rx = strength_secondary_prescription(ctx.phase)
        base = MovementPrescription(
            movement_id=chosen.id, reps=rx.reps,
            load=LoadSpec(type="rpe", value=hints.rpe or rx.rpe),
            notes=f"{rx.sets} sets",
        )
        base = base.model_copy(update={"scaling": expand_scaling(base, chosen)})

        intent_by_phase = {
            Phase.BUILD: "Volume complementar — hypertrophy",
            Phase.PEAK: "Acessório baixo volume — peak prep",
            Phase.BASE: "Volume alto — accumulation phase",
            Phase.DELOAD: "Volume reduzido — active recovery",
            Phase.TEST: "Acessório supportivo — manter padrão motor",
        }
        return WorkoutBlock(
            order=order, type=BlockType.STRENGTH_SECONDARY,
            format=BlockFormat.SETS_REPS,
            stimulus=Stimulus.HYPERTROPHY,
            duration_minutes=hints.duration_minutes,
            intent=intent_by_phase.get(ctx.phase, "Volume complementar"),
            rounds=rx.sets, rest_seconds=rx.rest_seconds,
            movements=[base],
        )

    def _metcon_block(
        self, order: int, hints: BlockHints, ctx: ProgrammingContext,
        candidates: list[Movement],
    ) -> WorkoutBlock:
        # Triplet: 1 weightlifting + 1 gymnastic + 1 monostructural.
        # Phase-aware metcon foi tentado em Sprint 6b mas regrediu L2 do
        # heurístico (judge via "sem progressão semanal" em scenarios mono-phase).
        # Mantém prescrição flat consistente com Sprint 6a.
        wl = next((m for m in candidates if "W" in m.modalities and m.category != "barbell"), None)
        gym = next((m for m in candidates if "G" in m.modalities and not m.equipment), None)
        mono = next((m for m in self.library.find_by_modality("M")
                     if set(m.equipment).issubset(ctx.athlete.equipment_available)), None)

        movements = []
        if wl:
            mp = MovementPrescription(
                movement_id=wl.id, reps=10,
                load=recommended_absolute_load(wl, ctx.athlete),
            )
            movements.append(mp.model_copy(update={"scaling": expand_scaling(mp, wl)}))
        if gym:
            mp = MovementPrescription(movement_id=gym.id, reps=15)
            movements.append(mp.model_copy(update={"scaling": expand_scaling(mp, gym)}))
        if mono:
            if mono.id in ("run",):
                mp = MovementPrescription(
                    movement_id=mono.id, distance_meters=200,
                )
            else:
                mp = MovementPrescription(
                    movement_id=mono.id, calories=15,
                )
            movements.append(mp.model_copy(update={"scaling": expand_scaling(mp, mono)}))

        return WorkoutBlock(
            order=order, type=BlockType.METCON,
            format=hints.target_format or BlockFormat.AMRAP,
            stimulus=hints.target_stimulus or Stimulus.MIXED_MODAL,
            duration_minutes=hints.duration_minutes,
            intent=hints.intent or "Mixed modal triplet",
            intensity_rpe=hints.rpe,
            movements=movements,
        )

    def _engine_block(self, order: int, hints: BlockHints) -> WorkoutBlock:
        return WorkoutBlock(
            order=order, type=BlockType.ENGINE,
            format=BlockFormat.INTERVALS,
            stimulus=Stimulus.AEROBIC_THRESHOLD,
            duration_minutes=hints.duration_minutes or 30,
            rounds=hints.rounds or 5,
            work_seconds=240, rest_seconds=120,
            target_pace="2:00/500m",
            intensity_rpe=hints.rpe or 8.0,
            intent="Threshold sustentável",
            movements=[
                MovementPrescription(
                    movement_id="row", distance_meters=1000,
                    pacing="2:00/500m split",
                ),
            ],
        )

    def _z2_block(self, order: int, hints: BlockHints) -> WorkoutBlock:
        return WorkoutBlock(
            order=order, type=BlockType.AEROBIC_Z2,
            format=BlockFormat.STEADY,
            stimulus=Stimulus.AEROBIC_Z2,
            duration_minutes=hints.duration_minutes or 20,
            target_pace="HR 130-145, nasal breathing",
            intent="Base aeróbica Z2",
            movements=[
                MovementPrescription(
                    movement_id="bike",
                    time_seconds=(hints.duration_minutes or 20) * 60,
                    pacing="zone 2",
                ),
            ],
        )

    def _skill_block(
        self, order: int, hints: BlockHints, ctx: ProgrammingContext
    ) -> WorkoutBlock:
        # Skill = prática técnica de movimento técnico (BMU, HSPU, etc.)
        skills = self.library.find_by_modality("G")
        skills = [m for m in skills if m.skill_level >= 3
                  and not self._is_restricted(m, ctx.athlete)
                  and set(m.equipment).issubset(ctx.athlete.equipment_available)]
        chosen = skills[0] if skills else self.library.get("pull_up")

        return WorkoutBlock(
            order=order, type=BlockType.SKILL,
            format=BlockFormat.QUALITY,
            stimulus=Stimulus.SKILL_ACQUISITION,
            duration_minutes=hints.duration_minutes or 12,
            intent=f"Skill — {chosen.name}, foco em técnica",
            movements=[
                MovementPrescription(movement_id=chosen.id, reps=3,
                                     notes="EMOM 8min, foco em qualidade"),
            ],
        )

    def _gym_capacity_block(
        self, order: int, hints: BlockHints, candidates: list[Movement],
    ) -> WorkoutBlock:
        gym_movs = [m for m in candidates if "G" in m.modalities]
        chosen = gym_movs[0] if gym_movs else self.library.get("pull_up")
        base = MovementPrescription(movement_id=chosen.id, reps=8)
        base = base.model_copy(update={"scaling": expand_scaling(base, chosen)})
        return WorkoutBlock(
            order=order, type=BlockType.GYMNASTICS,
            format=hints.target_format or BlockFormat.EMOM,
            stimulus=Stimulus.GYMNASTIC_CAPACITY,
            duration_minutes=hints.duration_minutes or 15,
            intent="Capacidade gímnica",
            movements=[base],
        )

    def _midline_block(self, order: int, hints: BlockHints) -> WorkoutBlock:
        return WorkoutBlock(
            order=order, type=BlockType.MIDLINE,
            format=BlockFormat.NOT_FOR_TIME,
            stimulus=Stimulus.MIDLINE_ENDURANCE,
            duration_minutes=hints.duration_minutes or 8,
            rounds=hints.rounds or 3,
            intent="Midline endurance",
            movements=[
                MovementPrescription(movement_id="hollow_hold", time_seconds=30),
                MovementPrescription(movement_id="plank", time_seconds=45),
                MovementPrescription(movement_id="dead_bug", reps=10),
            ],
        )


# ============================================================
# CLAUDE COMPOSER — STUB (Karl pluga depois)
# ============================================================

class ClaudeComposer:
    """STUB — Composer que delega seleção de movimentos para Claude API.

    Implementação esperada:
      1. Monta prompt estruturado com (block_type, hints, ctx, library_subset)
      2. Chama Anthropic API com response_format=JSON ou tool_use
      3. Valida resposta contra schema (Pydantic)
      4. Constrói WorkoutBlock validado

    Vantagens vs heurístico:
      - Variedade (não pega sempre o primeiro candidate)
      - Coerência narrativa (intent, coaching_notes ricos)
      - Adaptação contextual (recent_sessions, weekly_focus)
      - Scaling sugerido per-tier baseado em athlete profile
    """

    def __init__(self, library: MovementLibrary, api_key: str):
        self.library = library
        # self.client = anthropic.Anthropic(api_key=api_key)
        raise NotImplementedError("Implementar em sprint dedicada — ver docstring")

    def compose_block(self, *, order, block_type, hints, ctx) -> WorkoutBlock:
        raise NotImplementedError
