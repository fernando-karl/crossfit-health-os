# Hero & Benchmark WODs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add curated Hero + benchmark "Girl" WODs as first-class workouts the adaptive engine weaves into generated programs (heavy in competition-prep cycles), run-not-mutated by daily readiness, with tier-aware result logging and re-test history.

**Architecture:** A `NamedWod` catalog lives in the cfai engine as a validated seed (parallel to `movements_seed.py`), reusing the cfai schema, `derive_equipment`, and Rx/Scaled/Foundation tiers. Program generation marks benchmark-day slots and selects a WOD by phase/goal; the daily adaptive layer runs it intact at the athlete's tier or defers it to recovery by readiness. A `benchmark_results` table stores logged scores with tier-aware PRs.

**Tech Stack:** Python 3.12, Pydantic v2 (cfai), FastAPI + SQLModel/SQLAlchemy, Alembic (host Postgres), Jinja2 + vanilla JS frontend, catalog-based i18n (pt-BR default + en).

## Global Constraints

- **No "CrossFit Games" branding or official Games programming.** Heroes + benchmark "Girls" only. (Trademark — consistent with the HWPO/Mayhem/CompTrain genericization.)
- **Named-WOD loads are `absolute_kg` or `bodyweight` only — never `percent_1rm`.**
- **Catalog uses only `movement_id`s present in the cfai movement library.** A movement may be added to `movements_seed.py` only if essential and missing.
- **Select, don't mutate:** never rescale a named WOD's volume by readiness. Readiness gates whether it runs; athlete level picks the Rx/Scaled/Foundation tier.
- **Hero attributions must be factually correct and respectful.** Source each from a reliable reference.
- **i18n:** proper nouns (Murph, Fran) are not translated; descriptions/honoree lines/badges/Benchmarks-view strings are localized in both `en.json` and `pt-BR.json`.
- Run cfai tests from `backend/cfai` with `../venv/bin/python -m pytest`. Run backend tests from `backend` with `./venv/bin/python -m pytest`.

---

### Task 1: `NamedWod` schema + validated seed (pilot of 3)

**Files:**
- Create: `backend/cfai/src/cfai/named_wods.py`
- Test: `backend/cfai/tests/test_named_wods.py`

**Interfaces:**
- Consumes: `cfai.workout_schema` (`WorkoutBlock`, `MovementPrescription`, `LoadSpec`, `BlockType`, `BlockFormat`, `Stimulus`, `ScalingTier`); `cfai.movements_seed.load_default_library`; `cfai.movements.MovementLibrary.derive_equipment`.
- Produces:
  - `class NamedWod(BaseModel)` with fields: `id: str`, `name: str`, `category: Literal["hero","girl"]`, `honors: Optional[str]`, `attribution_note: Optional[str]`, `format: BlockFormat`, `time_cap_minutes: Optional[int]`, `structure: list[WorkoutBlock]`, `tags: list[str]`, `stimulus: Stimulus`, `cns_demand: int` (1-5), `est_duration_min: int`, `readiness_floor: float` (0-100), `source: str`.
  - `def movement_ids(self) -> list[str]` — flat list of all `movement_id`s in `structure`.
  - `def equipment_required(self, library) -> list[str]` — `library.derive_equipment(self.movement_ids())`.
  - `NAMED_WODS: list[NamedWod]` — the seed list (3 entries in this task).
  - `def load_named_wods() -> dict[str, NamedWod]` — `{w.id: w for w in NAMED_WODS}`.

- [ ] **Step 1: Write the failing test**

```python
# backend/cfai/tests/test_named_wods.py
from cfai.named_wods import load_named_wods, NamedWod
from cfai.movements_seed import load_default_library

def test_seed_loads_and_is_nonempty():
    wods = load_named_wods()
    assert len(wods) >= 3
    assert all(isinstance(w, NamedWod) for w in wods.values())

def test_every_movement_id_exists_in_library():
    lib = load_default_library()
    known = {m.id for m in lib.movements.values()}
    for w in load_named_wods().values():
        for mid in w.movement_ids():
            assert mid in known, f"{w.id}: unknown movement {mid!r}"

def test_no_percent_1rm_loads():
    for w in load_named_wods().values():
        for b in w.structure:
            for mp in b.movements:
                if mp.load:
                    assert mp.load.type in ("absolute_kg", "bodyweight"), \
                        f"{w.id}: {mp.movement_id} uses {mp.load.type}"

def test_heroes_have_honors():
    for w in load_named_wods().values():
        if w.category == "hero":
            assert w.honors, f"hero {w.id} missing honors attribution"

def test_equipment_derives():
    lib = load_default_library()
    murph = load_named_wods()["murph"]
    assert "pull_up_bar" in murph.equipment_required(lib) or murph.equipment_required(lib) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend/cfai && ../venv/bin/python -m pytest tests/test_named_wods.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cfai.named_wods'`

- [ ] **Step 3: Write `named_wods.py` (schema + 3 pilot WODs)**

Use only movement_ids confirmed present in `movements_seed.py` (verify with `grep '_m("' backend/cfai/src/cfai/movements_seed.py`). Pilot: Murph, Cindy, Fran (all use run/pull_up/push_up/air_squat/thruster — confirm each id; substitute the catalog's actual ids, e.g. `air_squat`, `pull_up`, `push_up`, `thruster`, `run`).

```python
# backend/cfai/src/cfai/named_wods.py
from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel, Field
from .workout_schema import (
    WorkoutBlock, MovementPrescription, LoadSpec, BlockType, BlockFormat, Stimulus,
)

class NamedWod(BaseModel):
    id: str
    name: str
    category: Literal["hero", "girl"]
    honors: Optional[str] = None
    attribution_note: Optional[str] = None
    format: BlockFormat
    time_cap_minutes: Optional[int] = None
    structure: list[WorkoutBlock]
    tags: list[str] = Field(default_factory=list)
    stimulus: Stimulus
    cns_demand: int = Field(ge=1, le=5)
    est_duration_min: int
    readiness_floor: float = Field(ge=0, le=100)
    source: str = ""

    def movement_ids(self) -> list[str]:
        return [mp.movement_id for b in self.structure for mp in b.movements]

    def equipment_required(self, library) -> list[str]:
        return library.derive_equipment(self.movement_ids())

def _metcon(fmt, movements, *, time_cap=None, stimulus=Stimulus.MIXED_MODAL, rounds=None):
    return WorkoutBlock(
        order=1, type=BlockType.METCON, format=fmt, stimulus=stimulus,
        duration_minutes=time_cap or 20, intent="benchmark", movements=movements,
        time_cap_minutes=time_cap, rounds=rounds,
    )

NAMED_WODS: list[NamedWod] = [
    NamedWod(
        id="fran", name="Fran", category="girl", format=BlockFormat.FOR_TIME,
        stimulus=Stimulus.MIXED_MODAL, cns_demand=4, est_duration_min=6, readiness_floor=55,
        tags=["sprint", "couplet"], source="CrossFit benchmark",
        structure=[_metcon(BlockFormat.FOR_TIME, [
            MovementPrescription(movement_id="thruster", reps=21, load=LoadSpec(type="absolute_kg", value=43.0)),
            MovementPrescription(movement_id="pull_up", reps=21, load=LoadSpec(type="bodyweight")),
            # 21-15-9 expressed as repeated prescriptions or a notes-encoded scheme;
            # keep it one block with the 21/15/9 split encoded in notes per the renderer.
        ])],
    ),
    # ... Cindy (AMRAP 20: 5 pull_up / 10 push_up / 15 air_squat), Murph (hero, run+pull/push/squat+run)
]

def load_named_wods() -> dict[str, NamedWod]:
    return {w.id: w for w in NAMED_WODS}
```

Note: encode rep schemes (21-15-9, AMRAP rounds) the way the existing session renderer expects — check `_load_to_intensity` / `renderMovements` in `calendar.js` and mirror the per-movement reps + block_prescription convention. If a clean representation needs a `scheme`/`notes` field, add it to `MovementPrescription` usage consistently.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend/cfai && ../venv/bin/python -m pytest tests/test_named_wods.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/cfai/src/cfai/named_wods.py backend/cfai/tests/test_named_wods.py
git commit -m "feat(cfai): NamedWod schema + validated benchmark seed (pilot)"
```

---

### Task 2: Expand the seed to ~15–20 WODs

**Files:**
- Modify: `backend/cfai/src/cfai/named_wods.py` (extend `NAMED_WODS`)
- Test: `backend/cfai/tests/test_named_wods.py` (add coverage assertion)

**Interfaces:** Consumes/produces same as Task 1.

- [ ] **Step 1: Add the catalog-size + category test**

```python
def test_catalog_size_and_categories():
    wods = load_named_wods()
    assert len(wods) >= 15
    assert any(w.category == "hero" for w in wods.values())
    assert any(w.category == "girl" for w in wods.values())
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend/cfai && ../venv/bin/python -m pytest tests/test_named_wods.py::test_catalog_size_and_categories -v`
Expected: FAIL (`assert len(wods) >= 15`)

- [ ] **Step 3: Add WODs using only supported movements**

For each candidate (Helen, Grace, Isabel, Karen, Jackie, Nancy, Elizabeth, DT, Chad, Chelsea, Barbara), first audit movement coverage:
`grep -oE '_m\("([a-z_]+)"' backend/cfai/src/cfai/movements_seed.py` → the allowed id set. Only include a WOD whose every movement is in that set. If a near-iconic WOD needs exactly one missing movement that is reasonable to add (e.g. `double_under`), add it to `movements_seed.py` with proper `category`, `modalities`, `equipment`, `tags`, and a `scaling` default — but prefer WODs that need nothing new. Heroes MUST set `honors` with a sourced, factual attribution.

- [ ] **Step 4: Run the full named-WOD suite**

Run: `cd backend/cfai && ../venv/bin/python -m pytest tests/test_named_wods.py -v`
Expected: PASS (all, including coverage + no-%1RM + heroes-have-honors)

- [ ] **Step 5: Commit**

```bash
git add backend/cfai/src/cfai/named_wods.py backend/cfai/tests/test_named_wods.py
git commit -m "feat(cfai): expand benchmark catalog to ~20 Heroes + Girls"
```

---

### Task 3: `benchmark_results` table + Alembic migration

**Files:**
- Modify: `backend/app/db/models.py` (add `BenchmarkResult`)
- Create: `backend/alembic/versions/<rev>_0007_add_benchmark_results.py`
- Test: `backend/tests/test_benchmark_results_model.py`

**Interfaces:**
- Produces: `class BenchmarkResult(SQLModel, table=True)` — columns: `id: UUID pk`, `user_id: int fk users.id`, `named_wod_id: str`, `performed_at: date`, `tier: str` (rx|scaled|foundation), `score_type: str` (time|rounds_reps|reps), `score_seconds: Optional[int]`, `score_rounds: Optional[int]`, `score_reps: Optional[int]`, `notes: Optional[str]`, `session_id: Optional[UUID]`, `created_at: datetime`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_benchmark_results_model.py
from app.db.models import BenchmarkResult

def test_benchmark_result_columns():
    cols = BenchmarkResult.__table__.columns.keys()
    for c in ["user_id","named_wod_id","performed_at","tier","score_type",
              "score_seconds","score_rounds","score_reps"]:
        assert c in cols
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && ./venv/bin/python -m pytest tests/test_benchmark_results_model.py -v`
Expected: FAIL — `ImportError: cannot import name 'BenchmarkResult'`

- [ ] **Step 3: Add the model**

Follow the existing SQLModel pattern in `models.py` (see `WorkoutTemplate`/`PersonalRecord`). Add:

```python
class BenchmarkResult(SQLModel, table=True):
    __tablename__ = "benchmark_results"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    named_wod_id: str = Field(max_length=40, index=True)
    performed_at: date
    tier: str = Field(default="rx", max_length=20)
    score_type: str = Field(max_length=20)
    score_seconds: Optional[int] = None
    score_rounds: Optional[int] = None
    score_reps: Optional[int] = None
    notes: Optional[str] = None
    session_id: Optional[UUID] = Field(default=None, foreign_key="workout_sessions.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

- [ ] **Step 4: Run to verify model test passes**

Run: `cd backend && ./venv/bin/python -m pytest tests/test_benchmark_results_model.py -v`
Expected: PASS

- [ ] **Step 5: Generate + edit the migration**

Run: `cd backend && ./venv/bin/python -m alembic revision -m "0007 add benchmark_results"`
Edit the new file's `upgrade()`/`downgrade()` to create/drop `benchmark_results` mirroring an existing migration (e.g. `..._0006_...py`). Columns + the two indexes + FKs to `users.id` and `workout_sessions.id`.

- [ ] **Step 6: Apply + verify, then commit**

Run: `cd backend && ./venv/bin/python -m alembic upgrade head`
Run: `./venv/bin/python -c "from sqlalchemy import inspect; from app.db.session import engine; print('benchmark_results' in inspect(engine).get_table_names())"`
Expected: `True`

```bash
git add backend/app/db/models.py backend/alembic/versions/*0007*.py
git commit -m "feat(db): benchmark_results table + migration 0007"
```

---

### Task 4: Placement — benchmark-day slot, phase/goal-weighted

**Files:**
- Create: `backend/cfai/src/cfai/benchmark_placement.py`
- Test: `backend/cfai/tests/test_benchmark_placement.py`

**Interfaces:**
- Consumes: `load_named_wods`, `cfai.workout_schema.Phase`, the program's per-week phase + goal.
- Produces:
  - `def should_place_benchmark(phase, week_number, *, is_competition_prep: bool) -> bool` — True on a competition-prep week (every non-deload week) or every 3rd non-deload week otherwise; always False for `Phase.DELOAD`.
  - `def select_benchmark(*, phase, used_ids: set[str], equipment_available: set[str], rng_seed: int) -> Optional[NamedWod]` — picks a WOD not in `used_ids`, whose `equipment_required ⊆ equipment_available`, deterministic by `rng_seed` (no `random`/`Date.now`).

- [ ] **Step 1: Write the failing tests**

```python
# backend/cfai/tests/test_benchmark_placement.py
from cfai.benchmark_placement import should_place_benchmark, select_benchmark
from cfai.workout_schema import Phase

def test_no_benchmark_in_deload():
    assert should_place_benchmark(Phase.DELOAD, 4, is_competition_prep=True) is False

def test_competition_prep_every_week():
    assert should_place_benchmark(Phase.PEAK, 1, is_competition_prep=True) is True
    assert should_place_benchmark(Phase.PEAK, 2, is_competition_prep=True) is True

def test_general_is_occasional():
    weeks = [should_place_benchmark(Phase.BUILD, w, is_competition_prep=False) for w in range(1,7)]
    assert sum(weeks) <= 2  # ~every 3rd week

def test_select_respects_used_and_equipment():
    from cfai.movements_seed import load_default_library
    eq = {"pull_up_bar","barbell","plates","rower","kettlebell","dumbbells","box","rack","bike"}
    w = select_benchmark(phase=Phase.PEAK, used_ids=set(), equipment_available=eq, rng_seed=1)
    assert w is not None
    w2 = select_benchmark(phase=Phase.PEAK, used_ids={w.id}, equipment_available=eq, rng_seed=1)
    assert w2 is None or w2.id != w.id
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend/cfai && ../venv/bin/python -m pytest tests/test_benchmark_placement.py -v`
Expected: FAIL — module missing

- [ ] **Step 3: Implement `benchmark_placement.py`**

```python
from __future__ import annotations
from typing import Optional
from .workout_schema import Phase
from .named_wods import load_named_wods, NamedWod
from .movements_seed import load_default_library

def should_place_benchmark(phase, week_number, *, is_competition_prep: bool) -> bool:
    if phase == Phase.DELOAD:
        return False
    if is_competition_prep:
        return True
    return week_number % 3 == 0

def select_benchmark(*, phase, used_ids, equipment_available, rng_seed) -> Optional[NamedWod]:
    lib = load_default_library()
    pool = [
        w for w in load_named_wods().values()
        if w.id not in used_ids
        and set(w.equipment_required(lib)).issubset(equipment_available)
    ]
    if not pool:
        return None
    pool.sort(key=lambda w: w.id)               # deterministic order
    return pool[rng_seed % len(pool)]            # deterministic pick, no RNG module
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend/cfai && ../venv/bin/python -m pytest tests/test_benchmark_placement.py -v`
Expected: PASS

- [ ] **Step 5: Wire into MesocyclePlanner**

In `mesocycle_planner.py` `plan_mesocycle`, after a week's sessions are built, if `should_place_benchmark(phase, week_number, is_competition_prep=...)` and not deload, replace the designated competition-sim day's session with the selected `NamedWod`'s `structure` (build a `Session` from its blocks via `session_builder.build_session`), tagging the session `is_benchmark=True` and `named_wod_id=w.id`. Thread `is_competition_prep` from the spec/primary_focus. Add a test in `tests/test_benchmark_placement.py` asserting a competition-prep mesocycle contains ≥1 session with `named_wod_id` set and a deload week contains none.

- [ ] **Step 6: Run cfai regression + commit**

Run: `cd backend/cfai && ../venv/bin/python -m pytest -q`
Expected: PASS (existing 8 + new)

```bash
git add backend/cfai/src/cfai/benchmark_placement.py backend/cfai/src/cfai/mesocycle_planner.py backend/cfai/tests/test_benchmark_placement.py
git commit -m "feat(cfai): phase/goal-weighted benchmark placement in mesocycles"
```

---

### Task 5: Adaptive — run-at-tier vs defer-to-recovery

**Files:**
- Modify: `backend/app/core/engine/adaptive.py`
- Test: `backend/tests/test_adaptive_benchmark.py`

**Interfaces:**
- Consumes: `AdaptiveTrainingEngine.generate_workout`, readiness score, the planned session's `named_wod_id`/`is_benchmark` flag, `load_named_wods`, athlete level → tier.
- Produces: a branch such that when the planned day is a benchmark: `readiness >= wod.readiness_floor` → return the named WOD intact with the level-appropriate tier; else → return the recovery/Z2 substitution with a `deferred_benchmark` note.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_adaptive_benchmark.py  (use existing adaptive test fixtures/mocks)
# Low readiness defers the hero; adequate readiness runs it at tier.
# Assert: result.is_benchmark + result.named_wod_id when readiness >= floor;
#         result.deferred_benchmark True + recovery stimulus when readiness < floor.
```

Write concrete assertions modeled on `tests/test_adaptive_engine.py` (reuse its recovery-metric fixtures and the engine entry point).

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && ./venv/bin/python -m pytest tests/test_adaptive_benchmark.py -v`
Expected: FAIL

- [ ] **Step 3: Add the benchmark branch in `generate_workout`**

After readiness is computed and the planned session loaded, if the planned session is a benchmark: look up the `NamedWod`, choose tier by athlete experience level (advanced→rx, intermediate→scaled, beginner→foundation), and either return it intact (readiness ≥ floor) or return the existing low-readiness recovery path with `deferred_benchmark=True` and a note. Do **not** apply `volume_multiplier` to a benchmark that runs.

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && ./venv/bin/python -m pytest tests/test_adaptive_benchmark.py -v`
Expected: PASS

- [ ] **Step 5: Run adaptive regression + commit**

Run: `cd backend && ./venv/bin/python -m pytest tests/test_adaptive_engine.py -v`
Expected: PASS

```bash
git add backend/app/core/engine/adaptive.py backend/tests/test_adaptive_benchmark.py
git commit -m "feat(adaptive): run benchmark at tier or defer to recovery by readiness"
```

---

### Task 6: Benchmarks API (log result + history + PR)

**Files:**
- Create: `backend/app/api/v1/benchmarks.py`
- Modify: `backend/app/main.py` (include router)
- Test: `backend/tests/test_benchmarks_api.py`

**Interfaces:**
- `POST /api/v1/benchmarks/results` body `{named_wod_id, performed_at, tier, score_type, score_seconds?, score_rounds?, score_reps?, notes?}` → 201 with the stored row.
- `GET /api/v1/benchmarks/results?named_wod_id=` → list (newest first).
- `GET /api/v1/benchmarks/{named_wod_id}/pr` → `{tier: best}` map (min seconds for `time`; max `(rounds,reps)` for `rounds_reps`).

- [ ] **Step 1: Write the failing API tests** (model on `tests/test_integrations_api.py` auth + client fixtures): log a result → 201; list returns it; PR returns the best per tier; PR never mixes tiers.

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && ./venv/bin/python -m pytest tests/test_benchmarks_api.py -v`
Expected: FAIL — router missing

- [ ] **Step 3: Implement the router** following `training.py` patterns (`APIRouter`, `require_active_subscription`, `get_session`, SQLAlchemy `select`). PR logic: `min(score_seconds)` per tier for `time`; `max((score_rounds, score_reps))` per tier for `rounds_reps`. Register in `main.py`: `app.include_router(benchmarks.router, prefix="/api/v1/benchmarks", tags=["Benchmarks"])`.

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && ./venv/bin/python -m pytest tests/test_benchmarks_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/v1/benchmarks.py backend/app/main.py backend/tests/test_benchmarks_api.py
git commit -m "feat(api): benchmark result logging + tier-aware PR endpoints"
```

---

### Task 7: UI — benchmark badge, honoree line, result logging + history

**Files:**
- Modify: `backend/app/static/js/calendar.js` (`renderWorkoutDetail`: benchmark badge + honoree + previous best + a "log result" affordance)
- Create: `backend/app/templates/benchmarks.html` (Benchmarks view — list of logged WODs + progression/PR)
- Modify: `backend/app/web/routes.py` (add `/dashboard/benchmarks` route) and `partials/navbar.html` (menu link)
- Test: `backend/tests/test_web_routes.py` (route renders 200)

**Interfaces:** Consumes the benchmarks API from Task 6; the planned session's `named_wod_id`/`honors` from Tasks 4–5.

- [ ] **Step 1: Add the route test** (model on existing `test_web_routes.py`): `GET /dashboard/benchmarks` returns 200 and contains the page title key.
- [ ] **Step 2: Run to verify it fails.** Run: `cd backend && ./venv/bin/python -m pytest tests/test_web_routes.py -k benchmarks -v` → FAIL.
- [ ] **Step 3: Add the route** in `routes.py` (`templates.TemplateResponse("benchmarks.html", {"request": request, "active_page": "benchmarks"})`), create `benchmarks.html` extending `base.html` with `chos-card` markup, and add the navbar link. In `calendar.js renderWorkoutDetail`, when `template.named_wod_id`, render a `HERO WOD`/`Benchmark` badge, the honoree line (heroes), the previous best (fetch from the PR endpoint), and a "Registrar resultado" button that POSTs to the results endpoint.
- [ ] **Step 4: Run to verify it passes.** Run: `cd backend && ./venv/bin/python -m pytest tests/test_web_routes.py -k benchmarks -v` → PASS. Manually verify the day modal + Benchmarks view render (cache-bust query).
- [ ] **Step 5: Commit**

```bash
git add backend/app/static/js/calendar.js backend/app/templates/benchmarks.html backend/app/web/routes.py backend/app/templates/partials/navbar.html backend/tests/test_web_routes.py
git commit -m "feat(ui): benchmark badge, honoree, result logging + Benchmarks view"
```

---

### Task 8: i18n (pt-BR + en)

**Files:**
- Modify: `backend/app/i18n/en.json`, `backend/app/i18n/pt-BR.json`
- Test: `backend/tests/test_i18n_benchmarks.py`

**Interfaces:** Consumes the keys referenced in Tasks 7's templates/JS.

- [ ] **Step 1: Write the failing test** — assert every `benchmarks.*` and `schedule.drawer.benchmark*` key referenced by the templates resolves in both catalogs and that the catalogs have identical key sets for the `benchmarks` group.
- [ ] **Step 2: Run to verify it fails.** Run: `cd backend && ./venv/bin/python -m pytest tests/test_i18n_benchmarks.py -v` → FAIL.
- [ ] **Step 3: Add keys** to both catalogs (idempotent script, `ensure_ascii=False, indent=2`): page title, view headings, badge labels ("HERO WOD"/"Benchmark"), "honra"/"honors" prefix, "Registrar resultado"/"Log result", "Recorde"/"PR", "tempo"/"time", "rounds", tier labels, "Hero adiado — recovery hoje" / "Hero deferred — recovery today". Proper nouns stay untranslated.
- [ ] **Step 4: Run to verify it passes.** Run: `cd backend && ./venv/bin/python -m pytest tests/test_i18n_benchmarks.py -v` → PASS. Live-check `/dashboard/benchmarks?lang=en` and default pt-BR.
- [ ] **Step 5: Commit**

```bash
git add backend/app/i18n/en.json backend/app/i18n/pt-BR.json backend/tests/test_i18n_benchmarks.py
git commit -m "feat(i18n): benchmark WOD strings (pt-BR + en)"
```

---

## Self-Review

**Spec coverage:** Catalog (T1–T2) · NamedWod data model (T1) · benchmark_results table (T3) · placement by phase/goal incl. competition prep + never-deload (T4) · adaptive select/defer/tier (T5) · logging + tier-aware PR (T6) · UI badge/honoree/history + attribution (T7) · i18n + legal no-Games (T7/T8 + Global Constraints). All spec sections map to a task.

**Placeholder scan:** Task 5's test step intentionally references the existing adaptive fixtures rather than reproducing them — the implementer must mirror `test_adaptive_engine.py`. Tasks 7–8 give exact files/keys/steps. No "TBD/add error handling/similar to Task N".

**Type consistency:** `NamedWod` fields, `movement_ids()`, `equipment_required(library)`, `load_named_wods()`, `should_place_benchmark(...)`, `select_benchmark(...)`, `BenchmarkResult` columns, and the API/PR shapes are used consistently across tasks.

## Open follow-ups (not blocking)
- Confirm the final ~20-WOD list against the live movement catalog during Task 2.
- Decide exact `readiness_floor`/`cns_demand` per WOD during seeding (sensible defaults: hero 60–70, heavy girl 55, light girl 45).
