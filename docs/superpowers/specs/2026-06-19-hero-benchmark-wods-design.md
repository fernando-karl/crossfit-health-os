# Hero & Benchmark WODs — Design

**Date:** 2026-06-19
**Status:** Approved (brainstorming) — pending spec review
**Author:** Fernando Karl + Claude

## 1. Overview

Add curated, named **Hero** and **benchmark "Girl"** WODs to the platform as
first-class workouts that the adaptive engine can weave into generated programs
— with special emphasis on **competition-prep cycles**, where these WODs are the
training stimulus. Completed benchmarks are logged so athletes can **re-test and
track progression over time**.

### Goals
- A curated catalog (~15–25) of Hero + Girl WODs, expressed in the cfai schema.
- The program generator places benchmark WODs on suitable days, weighted by
  phase/goal (heavy in competition prep, occasional in base/general).
- The daily adaptive layer **selects, never mutates** a named WOD: runs it intact
  (at the athlete's Rx/Scaled/Foundation tier) on adequate-readiness days, and
  defers it for recovery on low-readiness days.
- Athletes log benchmark results (time/rounds) and see history + PRs per tier.

### Non-Goals
- **No "CrossFit Games" branding or official Games programming** (trademark — same
  decision applied to HWPO/Mayhem/CompTrain). Heroes + Girls only.
- No AI-generated "in the style of" benchmarks. The catalog is hand-curated.
- No mutating/rescaling a named WOD by readiness (Murph stays Murph).

## 2. Decisions (locked during brainstorming)

| Topic | Decision |
|---|---|
| Surface | Integrated into the AI-generated program (not a standalone browse-only library) |
| Low readiness | **Select, don't mutate** — run intact at level-tier, or defer to recovery |
| Categories / trademark | **Heroes + Girls**, no "CrossFit Games" name/programming |
| Catalog size | Curated ~15–25, only movements already in the cfai catalog (extend only for an essential missing movement) |
| Competition prep | Competition-prep cycles feature these WODs deliberately/frequently |
| Logging / re-test | **In initial scope** — record results + history/PR |

## 3. Architecture (Approach A)

A named-WOD catalog lives in the **cfai engine** (a seed, parallel to
`movements_seed.py`), so it reuses the cfai schema, equipment derivation, and the
Rx/Scaled/Foundation scaling system. Two integration points bridge
ahead-of-time periodization and same-day readiness:

```
cfai/named_wods.py  (seed: NamedWod catalog, validated against the movement lib)
        │
        ├── program generation (MesocyclePlanner) ── marks "benchmark day" slots,
        │      selects a fitting WOD by phase/goal (heavy in competition prep)
        │
        └── daily adaptive (adaptive.py) ── on the day: readiness ≥ floor → run
               intact at level-tier;  readiness < floor → defer, recovery instead
                        │
                        └── completion → benchmark_results (log) → history/PR
```

- **Program is generated weeks ahead** → it can only mark *which days* are
  benchmark days and *which WOD*. **Readiness is same-day** → the adaptive layer
  makes the run/defer + tier decision. This split is the crux of Approach A and
  the reason B/C were rejected (they handle only one of the two).
- Named-WOD loads are `absolute_kg` / `bodyweight` as published — **never
  `percent_1rm`** (consistent with the recent load fix).

## 4. Data Model

### 4.1 NamedWod (cfai catalog entry — seed, not a DB table)
```
NamedWod
  id                str    "murph" | "fran" | "dt"
  name              str    "Murph"
  category          enum   "hero" | "girl"
  honors            str?   heroes only: "Lt. Michael P. Murphy, USN SEAL — KIA 2005, Afghanistan"
  attribution_note  str?   short respectful line (heroes)
  format            BlockFormat   for_time | for_time_capped | amrap | emom | chipper
  time_cap_minutes  int?
  structure         list[WorkoutBlock]   cfai blocks/movements (movement_id + reps/scheme + LoadSpec)
  scaling           dict[tier → adjustments]   Rx / Scaled / Foundation (reuse MovementScaling)
  stimulus          Stimulus
  tags              list[str]    ["long","grind"] | ["sprint","couplet"]
  cns_demand        int 1-5      drives readiness_floor + placement
  est_duration_min  int
  readiness_floor   float        min readiness to run (heroes high)
  equipment_required list[str]   derived via the existing library.derive_equipment()
  source            str          provenance / attribution
```
**Validation (unit test):** every `movement_id` in `structure` must exist in the
cfai movement library, and every LoadSpec must validate. The seed fails loudly
otherwise — this enforces the "supported movements only" scope.

### 4.2 benchmark_results (new DB table)
```
benchmark_results
  id            uuid pk
  user_id       fk → users
  named_wod_id  str    "murph" (catalog id; not an FK — catalog is code)
  performed_at  date
  tier          enum   "rx" | "scaled" | "foundation"
  score_type    enum   "time" | "rounds_reps" | "reps"
  score_seconds int?       for_time → total seconds (lower is better)
  score_rounds  int?       amrap → rounds
  score_reps    int?       amrap → trailing reps  / reps-based (max reps)
  notes         str?
  session_id    fk?        link to the workout_session if completed in-app
  created_at    timestamptz
```
- **PR is tier-aware**: best within the same `(named_wod_id, tier)` — min seconds
  for `time`, max (rounds, reps) for `rounds_reps`. Never compare Rx to Scaled.
- Alembic migration adds the table (host Postgres + Alembic, per DEPLOYMENT.md).

## 5. Catalog Scope

A curated ~15–25 using movements already in the catalog. Representative
candidates (final list confirmed during implementation against the movement lib):

- **Girls:** Fran, Cindy, Helen, Grace, Isabel, Karen, Jackie, Nancy, Elizabeth.
- **Heroes:** Murph, DT, Chad, Chelsea, Barbara.

Movements needed by these that may be missing (HSPU, double-under, rope climb,
GHD sit-up) → either pick WODs that avoid them, or add **only the few essential
ones** to `movements_seed.py` (with tags/scaling/equipment). A build step audits
each candidate WOD's movement coverage before inclusion.

## 6. Placement Logic (program generation)

- The planner reserves **one benchmark slot per microcycle**, on a competition-sim
  day (HWPO-style late-week), when the cycle calls for it.
- **Phase/goal weighting:**
  - **Competition-prep cycle** (goal=competition / PEAK phase): a benchmark/Hero
    **every week** — it is the competition stimulus.
  - Base/general cycle: **occasional** (≈ every 2–3 weeks) as a test/landmark.
  - **Deload weeks: never.** Respect CNS demand (no high-`cns_demand` Hero the day
    before a heavy test).
- Selection: no repeat of the same WOD within a cycle (unless deliberately
  re-testing), match the day's intended stimulus, respect athlete equipment.
- Re-test: a benchmark may recur **across cycles** to track progression.

## 7. Daily Adaptive Behavior (`adaptive.py`)

On a day flagged as a benchmark day with a selected `NamedWod`:
1. Compute readiness (existing HRV/sleep/stress/soreness logic).
2. `readiness ≥ wod.readiness_floor` → present the WOD **intact** at the tier for
   the athlete's level (Rx / Scaled / Foundation). Volume is **not** scaled by
   readiness — readiness gates *whether* it runs; level picks the tier.
3. `readiness < floor` → **do not mutate** the Hero. Substitute the day for active
   recovery / Z2 (the engine already does recovery substitution), and mark the
   benchmark **deferred** with a note ("Hero deferred — recovery today").

Reuses the existing readiness computation and recovery-substitution path; adds a
"benchmark day" branch.

## 8. Logging & Re-test

- On completion of a benchmark day, the athlete logs the result (time / rounds+reps)
  at the tier performed. Stored in `benchmark_results`.
- The day modal shows **previous best (same tier)** and last result, for motivation.
- A **Benchmarks view** lists logged WODs with progression (e.g., "Murph: 42:15 →
  38:50 Rx") and the current PR per tier.
- API: `POST /api/v1/benchmarks/results` (log), `GET /api/v1/benchmarks/results`
  (history, filter by wod), `GET /api/v1/benchmarks/{id}/pr` (best per tier).

## 9. UI & Attribution

- **Day modal:** a "HERO WOD" / "Benchmark" badge, the name, the prescription
  (movements/format/time-cap via the existing session renderer), the tier, and —
  for heroes — the **honoree line**. Shows previous best/last result.
- **i18n:** proper nouns (Murph, Fran) are not translated; descriptions, honoree
  lines, badges, and the Benchmarks view are localized (pt-BR default + en).
- **Legal/attribution:** heroes display who they honor (the tradition's purpose);
  Girls show names only; a small footnote; **no "CrossFit Games"**. Names used
  factually (nominative reference).

## 10. Testing

- **cfai seed:** every `NamedWod` parses; all `movement_id`s exist; LoadSpecs
  validate; equipment derives; scaling tiers expand. (Fails the build if not.)
- **Placement:** competition-prep cycle features a benchmark weekly; deload weeks
  never get one; no same-WOD repeat within a cycle.
- **Adaptive:** low readiness defers the Hero → recovery; adequate readiness →
  WOD at the level tier, unmutated.
- **Logging:** result persists; PR is tier-aware (min time / max rounds-reps);
  history returns chronologically.
- **i18n:** keys resolve in both locales; honoree lines render.

## 11. Implementation Sequence (for the plan)

1. cfai `NamedWod` schema + `named_wods.py` seed (start with ~6 iconic, then expand
   to ~20) + seed-validation test.
2. `benchmark_results` table + Alembic migration.
3. Placement: planner benchmark-slot + phase/goal weighting.
4. Adaptive: benchmark-day branch (run-at-tier / defer-to-recovery).
5. Logging API + Benchmarks view + day-modal result display.
6. i18n (pt-BR + en) for names/honoree/badges/view.

## 12. Risks / Open Questions

- **Movement coverage:** some classic WODs need movements not yet in the catalog.
  Mitigation: prefer supported WODs; add only a few essential movements.
- **Readiness vs. ahead-of-time plan:** deferral happens at the daily layer; the
  weekly plan view should indicate a day is "benchmark (pending readiness)".
- **Honoree accuracy:** Hero attributions must be factually correct and respectful;
  source each from a reliable reference during seeding.
