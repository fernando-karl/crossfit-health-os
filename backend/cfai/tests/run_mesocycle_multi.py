"""
Multi-scenario mesocycle harness — Sprint 5i.

Roda cada composer disponível sobre N cenários do fixture
tests/fixtures/mesocycle_scenarios.json. Para cada (composer × scenario):
- L1 multi-week (overload, deload, variety, acwr)
- L1 per-session aggregates (prilepin, inol)
- L2 progression_logic

Aggregations across scenarios: mean ± std de cada métrica por composer.
Cenário-específicas também impressas pra detectar context-dependent winners.

Cost-cuidadoso: cada cenário roda 1 mesocycle por composer (9 composers se
todos providers ativos). 3 cenários × 9 composers = 27 mesocycles ≈ \$2.

Uso:
    cd backend/cfai
    ../venv/bin/python tests/run_mesocycle_multi.py                    # 3 scenarios
    ../venv/bin/python tests/run_mesocycle_multi.py --max-scenarios 5  # full
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import date, timedelta
from pathlib import Path
from statistics import mean, stdev

try:
    from dotenv import load_dotenv
    load_dotenv("../.env")
except ImportError:
    pass

from cfai.composer_hybrid import HybridComposer
from cfai.composer_llm import LLMComposer
from cfai.cost_tracker import cost_tracker
from cfai.evaluation import evaluate_mesocycle, summary_score
from cfai.evaluation_judge import LLMProviderJudge
from cfai.examples import karl
from cfai.llm_providers import PROVIDER_CLASSES
from cfai.mesocycle_planner import MesocyclePlanner, MesocycleSpec
from cfai.movements_seed import load_default_library
from cfai.programmer import HeuristicComposer
from cfai.workout_schema import Phase

FIXTURE = Path(__file__).parent / "fixtures" / "mesocycle_scenarios.json"
JUDGE_PROVIDER_NAME = os.getenv("JUDGE_PROVIDER", "openai")


# ============================================================
# CLI
# ============================================================

parser = argparse.ArgumentParser()
parser.add_argument("--max-scenarios", "--max", type=int, default=3)
parser.add_argument("--out", default="run_mesocycle_multi_results.json")
parser.add_argument("--no-confirm", action="store_true")
parser.add_argument("--exclude-providers", default="",
                    help="lista CSV pra excluir do pool, ex: 'minimax,groq'")
parser.add_argument("--scenario", default="",
                    help="CSV de scenario ids específicos (override de --max-scenarios), "
                         "ex: 'scen_base_aerobic'")
args = parser.parse_args()
EXCLUDED_PROVIDERS = frozenset(
    p.strip() for p in args.exclude_providers.split(",") if p.strip()
)


# ============================================================
# 1. Load fixture
# ============================================================

print("=" * 80)
print("MULTI-SCENARIO MESOCYCLE HARNESS (Sprint 5i)")
print("=" * 80)

with open(FIXTURE) as f:
    fixture = json.load(f)

if args.scenario:
    _wanted = {s.strip() for s in args.scenario.split(",") if s.strip()}
    scenarios_raw = [s for s in fixture["scenarios"] if s["id"] in _wanted]
    if not scenarios_raw:
        raise SystemExit(
            f"No scenarios matched {sorted(_wanted)}. "
            f"Available: {[s['id'] for s in fixture['scenarios']]}"
        )
else:
    scenarios_raw = fixture["scenarios"][: args.max_scenarios]
print(f"\n📋 Scenarios: {len(scenarios_raw)} de {len(fixture['scenarios'])}")
for s in scenarios_raw:
    print(f"   - {s['id']}: {s['name']}")


# ============================================================
# 2. Init providers + judge
# ============================================================

print("\n🔌 Inicializando providers...")
providers = {}
for name, cls in PROVIDER_CLASSES.items():
    if name in ("ollama", "unsloth"):
        continue  # local providers — escopo separado
    if name in EXCLUDED_PROVIDERS:
        print(f"   ⛔ {name:10s} excluído via --exclude-providers")
        continue
    try:
        providers[name] = cls()
        print(f"   ✅ {name:10s} → {providers[name].name}")
    except (ValueError, ImportError) as e:
        print(f"   ⚪ {name:10s} skipped — {e}")

if JUDGE_PROVIDER_NAME not in providers:
    print(f"\n❌ JUDGE_PROVIDER={JUDGE_PROVIDER_NAME!r} indisponível.")
    raise SystemExit(1)
judge = LLMProviderJudge(providers[JUDGE_PROVIDER_NAME], max_retries=2)
print(f"\n⚖️  Judge: {providers[JUDGE_PROVIDER_NAME].name}")


# ============================================================
# 3. Composers
# ============================================================

library = load_default_library()
composers: dict[str, object] = {"heuristic": HeuristicComposer(library)}
for name, provider in providers.items():
    composers[f"llm_{name}"] = LLMComposer(provider, library, max_retries=2)
for name, provider in providers.items():
    composers[f"hybrid_{name}"] = HybridComposer(provider, library, max_retries=2)
print(f"\n🎼 Composers: {len(composers)} total → {list(composers)}")


# ============================================================
# 4. Cost prelude
# ============================================================

n_meso = len(scenarios_raw) * len(composers)
est_cost = n_meso * 0.07  # ~\$0.07 per mesocycle observed in Sprint 5h
print(f"\n💵 Estimated cost: ~${est_cost:.2f} ({n_meso} mesocycles)")
if not args.no_confirm and est_cost > 1.5:
    if input("   Continuar? [y/N] ").strip().lower() != "y":
        raise SystemExit(0)


# ============================================================
# 5. Helpers
# ============================================================

def build_spec(scenario: dict) -> MesocycleSpec:
    return MesocycleSpec(
        weeks=[Phase(p) for p in scenario["weeks"]],
        deload_weeks=set(scenario.get("deload_weeks", [])),
    )


# ============================================================
# 6. Main loop
# ============================================================

# results[composer][scenario_id] = {l1_*, l2_*, costs}
results: dict[str, dict[str, dict]] = {c: {} for c in composers}

start_date = date(2026, 5, 4)

for s_idx, scen in enumerate(scenarios_raw, 1):
    print(f"\n{'='*80}")
    print(f"[{s_idx}/{len(scenarios_raw)}] {scen['id']}: {scen['name']}")
    print(f"{'='*80}")

    spec = build_spec(scen)
    judge_context = {
        "athlete_id": karl.id,
        "scenario": scen["id"],
        "phases": scen["weeks"],
        "primary_focus": scen["primary_focus"],
    }

    for cname, composer in composers.items():
        cost_before = sum(r.cost_usd for r in cost_tracker.records)
        planner = MesocyclePlanner(library, composer, sessions_per_week=5)
        try:
            meso = planner.plan_mesocycle(
                athlete=karl, spec=spec,
                start_date=start_date + timedelta(days=s_idx * 28),
                primary_focus=scen["primary_focus"],
                weekly_focus=scen["weekly_focus"],
                meso_id=f"{scen['id']}__{cname}",
                meso_name=f"{cname} {scen['name']}",
            )
        except Exception as e:
            print(f"   ❌ {cname:18s} GEN FAIL — {type(e).__name__}: {e}")
            results[cname][scen["id"]] = {"error": f"gen: {e}"}
            continue

        # L1
        eval_res = evaluate_mesocycle(meso, karl, library)
        meso_metrics = {m["name"]: m for m in eval_res["mesocycle_metrics"]}
        sess_avg: dict[str, float] = {}
        for sm in eval_res["session_metrics"]:
            for m in sm["metrics"]:
                sess_avg.setdefault(m["name"], []).append(m["score"])
        sess_avg = {k: mean(v) for k, v in sess_avg.items()}
        cat_summary = {
            str(k).split(".")[-1].lower(): v
            for k, v in summary_score(eval_res).items()
        }

        # L2
        try:
            l2 = judge.score_mesocycle_progression(meso, judge_context)
            l2_score = l2.score
            l2_reason = l2.reasoning[:200]
        except Exception as e:
            l2_score = 0
            l2_reason = f"ERR: {e}"

        cost_delta = sum(r.cost_usd for r in cost_tracker.records) - cost_before

        results[cname][scen["id"]] = {
            "l1_overload": meso_metrics["progressive_overload"]["score"],
            "l1_deload": meso_metrics["deload_presence"]["score"],
            "l1_variety": meso_metrics["movement_variety"]["score"],
            "l1_acwr": meso_metrics["acwr"]["score"],
            "l1_period_cat": cat_summary.get("periodization", 0),
            "l1_validity_cat": cat_summary.get("validity", 0),
            "l1_prilepin": sess_avg.get("prilepin_compliance", 0),
            "l1_inol": sess_avg.get("inol_per_session", 0),
            "l1_equip": sess_avg.get("equipment_feasibility", 0),
            "l2_progression": l2_score,
            "l2_reason": l2_reason,
            "cost_usd": cost_delta,
        }
        print(f"   ✅ {cname:18s} overload={meso_metrics['progressive_overload']['score']:.2f} "
              f"prilepin={sess_avg.get('prilepin_compliance', 0):.2f} "
              f"inol={sess_avg.get('inol_per_session', 0):.2f} "
              f"L2={l2_score} cost=${cost_delta:.4f}")


# ============================================================
# 7. Aggregations
# ============================================================

print(f"\n{'='*80}\nAGGREGATIONS (across {len(scenarios_raw)} scenarios)\n{'='*80}")

metrics = ["l1_overload", "l1_prilepin", "l1_inol", "l1_period_cat",
           "l2_progression"]
short_names = ["overload", "prilepin", "inol", "period", "L2_prog"]

# Per-composer mean ± std for each metric
print(f"\n📊 Mean ± std per composer:")
hdr = f"   {'composer':<18s} " + " ".join(
    f"{n:<14s}" for n in short_names
)
print(hdr)
print(f"   {'-'*18} " + " ".join("-"*14 for _ in short_names))

agg: dict[str, dict[str, dict]] = {}
for cname in composers:
    agg[cname] = {}
    cells = []
    for m in metrics:
        vals = [r[m] for r in results[cname].values() if isinstance(r, dict) and m in r]
        if not vals:
            cells.append(f"{'N/A':<14s}")
            agg[cname][m] = None
            continue
        mu = round(mean(vals), 2)
        sd = round(stdev(vals), 2) if len(vals) > 1 else 0.0
        agg[cname][m] = {"mean": mu, "std": sd, "values": vals}
        cells.append(f"{mu:.2f}±{sd:.2f}    "[:14].ljust(14))
    print(f"   {cname:<18s} {' '.join(cells)}")


# Per-scenario per-composer breakdown for L2 progression
print(f"\n🎬 L2 progression_logic per scenario × composer:")
hdr = f"   {'composer':<18s} " + " ".join(f"{s['id'][-12:]:<14s}" for s in scenarios_raw)
print(hdr)
print(f"   {'-'*18} " + " ".join("-"*14 for _ in scenarios_raw))
for cname in composers:
    cells = []
    for scen in scenarios_raw:
        r = results[cname].get(scen["id"], {})
        cells.append(f"{r.get('l2_progression', 0):<14d}")
    print(f"   {cname:<18s} {' '.join(cells)}")


# Per-scenario winner
print(f"\n🏆 Best L2_progression per scenario:")
for scen in scenarios_raw:
    best = max(
        composers, key=lambda c: results[c].get(scen["id"], {}).get("l2_progression", 0)
    )
    bv = results[best].get(scen["id"], {}).get("l2_progression", 0)
    print(f"   {scen['id']:<22s} → {best} ({bv})")


# Best L1 prilepin per scenario
print(f"\n🥇 Best L1_prilepin per scenario:")
for scen in scenarios_raw:
    best = max(
        composers, key=lambda c: results[c].get(scen["id"], {}).get("l1_prilepin", 0)
    )
    bv = results[best].get(scen["id"], {}).get("l1_prilepin", 0)
    print(f"   {scen['id']:<22s} → {best} ({bv:.2f})")


# ============================================================
# 8. Cost
# ============================================================

print(f"\n💰 Cost summary:")
report = cost_tracker.report()
print(f"   Total calls: {report['n_calls']}")
print(f"   Total cost:  ${report['total_cost_usd']:.4f}")
for prov, b in report["by_provider"].items():
    print(f"     {prov:12s} calls={b['n_calls']:<3d} cost=${b['cost_usd']:.4f} "
          f"avg_lat={b['latency_ms_avg']}ms schema_fail={b['schema_failure_rate']*100:.0f}%")


# ============================================================
# 9. Export
# ============================================================

export = {
    "fixture_version": fixture["version"],
    "scenarios": [s["id"] for s in scenarios_raw],
    "judge_provider": JUDGE_PROVIDER_NAME,
    "composers": list(composers),
    "results": results,
    "aggregations": agg,
    "cost_report": report,
}
with open(args.out, "w") as f:
    json.dump(export, f, indent=2, default=str)
print(f"\n💾 JSON saved → {args.out}")

print(f"\n{'='*80}\nDONE\n{'='*80}")
