"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, aggregate, load_spec, per_item
from lab9.graders import GRADERS


def _num_bad(v) -> bool:
    return isinstance(v, float) and (math.isnan(v) or math.isinf(v))


def _graded_ids(spec: dict) -> list[str]:
    """Spec metrics that a per-row grader scores (the ones a crashed grader would turn into None)."""
    return [m["id"] for m in spec.get("metrics") or [] if m["id"] in GRADERS]


def _ratchet(spec: dict, base_spec: dict) -> list[str]:
    """Same eval-set version => every threshold may only get stricter."""
    if spec.get("eval_set_version") != base_spec.get("eval_set_version"):
        return []                                   # new eval-set version: new baseline, fresh thresholds
    out: list[str] = []
    for key in ("eval_set", "labels", "seeds", "adversarial_pack"):
        if base_spec.get(key) != spec.get(key):
            out.append(f"ratchet: spec {key} changed on the same eval-set version "
                       f"({base_spec.get(key)!r} -> {spec.get(key)!r})")
    for k in base_spec.get("pass_k") or []:
        if k not in (spec.get("pass_k") or []):
            out.append(f"ratchet: pass_k {k} removed")
    bb, bs = base_spec.get("bootstrap") or {}, spec.get("bootstrap") or {}
    if bs.get("confidence", 0.95) > bb.get("confidence", 0.95):
        out.append(f"ratchet: bootstrap confidence raised {bb.get('confidence')} -> {bs.get('confidence')} (wider CI)")
    if bs.get("method", "percentile") != bb.get("method", "percentile"):
        out.append("ratchet: bootstrap method changed")

    def loosened(where: str, old: dict, new: dict | None) -> list[str]:
        if new is None:
            return [f"ratchet: {where} removed"]
        r = []
        if old.get("blocking") and not new.get("blocking"):
            r.append(f"ratchet: {where} no longer blocking")
        ot, nt = old.get("threshold", old), new.get("threshold", new)
        for key in ("max", "max_increase"):
            if key in ot and (key not in nt or not isinstance(nt[key], (int, float)) or nt[key] > ot[key]):
                r.append(f"ratchet: {where} {key} {ot[key]} -> {nt.get(key)}")
        if "min" in ot and ("min" not in nt or not isinstance(nt["min"], (int, float)) or nt["min"] < ot["min"]):
            r.append(f"ratchet: {where} min {ot['min']} -> {nt.get('min')}")
        if ot.get("no_significant_drop") and not nt.get("no_significant_drop"):
            r.append(f"ratchet: {where} dropped no_significant_drop")
        return r

    new_m = {m["id"]: m for m in spec.get("metrics") or []}
    for m in base_spec.get("metrics") or []:
        out += loosened(f"metric {m['id']}", m, new_m.get(m["id"]))
    new_s = {(x["name"], x["metric"]): x for x in spec.get("slices") or []}
    for x in base_spec.get("slices") or []:
        out += loosened(f"slice {x['name']}/{x['metric']}", x, new_s.get((x["name"], x["metric"])))
    return out


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Catches: NaN/inf or non-numeric metrics; metrics that do not follow from the rows; dropped,
    duplicated or cherry-picked (item, seed) rows; manifest vs baseline drift; evaluator failures
    and None / non-bool grader values; relabelled slices; and (with base_spec) a loosened spec."""
    problems: list[str] = []
    rows = pr.get("rows")
    if not isinstance(rows, list) or not rows:
        return ["report has no rows"]
    man, bman = pr.get("manifest") or {}, base.get("manifest") or {}
    graded = _graded_ids(spec)

    # 1. metric values must be real numbers
    for k, v in (pr.get("metrics") or {}).items():
        if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float))):
            problems.append(f"metric {k} is not a number: {v!r}")
        elif _num_bad(v):
            problems.append(f"metric {k} is {v} (NaN/inf drops out of every comparison)")

    # 2. evaluator failures and crashed / tampered grader values
    if pr.get("evaluator_failures"):
        problems.append(f"{len(pr['evaluator_failures'])} evaluator failure(s): {str(pr['evaluator_failures'][0])[:80]}")
    for m in graded:
        missing = [r for r in rows if r.get(m) is None]
        if missing:
            problems.append(f"{len(missing)} row(s) with no value for graded metric {m} "
                            f"(first {missing[0].get('item_id')}@{missing[0].get('seed')})")
        odd = [r for r in rows if r.get(m) is not None and not isinstance(r.get(m), bool)]
        if odd:
            problems.append(f"{len(odd)} row(s) where {m} is not a bool (first {odd[0].get(m)!r})")

    # 3. row count and (item, seed) coverage: no dropped, duplicated or cherry-picked rows
    seeds = man.get("seeds") or []
    want = (man.get("items") or 0) * len(seeds)
    if len(rows) != want:
        problems.append(f"{len(rows)} rows, manifest promises {man.get('items')} items x {len(seeds)} seeds = {want}")
    keys = [(r.get("item_id"), r.get("seed")) for r in rows]
    dup = len(keys) - len(set(keys))
    if dup:
        problems.append(f"{dup} duplicated (item, seed) row(s)")
    base_keys = {(r.get("item_id"), r.get("seed")) for r in base.get("rows") or []}
    if set(keys) != base_keys:
        miss, extra = base_keys - set(keys), set(keys) - base_keys
        problems.append(f"(item, seed) set differs from baseline: {len(miss)} missing, {len(extra)} extra"
                        + (f" (e.g. missing {sorted(miss, key=str)[0]})" if miss else ""))
    for key in ("items", "seeds", "eval_set"):
        if bman and man.get(key) != bman.get(key):
            problems.append(f"manifest {key} {man.get(key)!r} != baseline {bman.get(key)!r}")
    if sorted({r.get("seed") for r in rows}, key=str) != sorted(set(seeds), key=str):
        problems.append("row seeds do not match manifest seeds")
    n_items = len({r.get("item_id") for r in rows})
    if n_items != man.get("items"):
        problems.append(f"rows cover {n_items} items, manifest says {man.get('items')}")

    # 4. slice tags must be the baseline's (relabelling an item out of a slice hides its regression)
    base_tags: dict = {}
    for r in base.get("rows") or []:
        base_tags.setdefault(r.get("item_id"), sorted(r.get("slices") or []))
    relabelled = sorted({r.get("item_id") for r in rows
                         if r.get("item_id") in base_tags
                         and sorted(r.get("slices") or []) != base_tags[r.get("item_id")]}, key=str)
    if relabelled:
        problems.append(f"slice tags differ from baseline on {len(relabelled)} item(s): {', '.join(map(str, relabelled[:5]))}")

    # 5. the headline metrics must follow from the rows (no hand-edited numbers)
    if not problems:
        reported = pr.get("metrics") or {}
        ids = [m for m in graded if m in reported]
        k_values = [k for k in spec.get("pass_k") or [] if f"pass_at_{k}" in reported]
        has_cost = all(isinstance(r.get("cost"), (int, float)) for r in rows)
        again = aggregate([r if has_cost else {**r, "cost": 0.0} for r in rows], ids, k_values=k_values)
        for k, v in again.items():
            if k not in reported or (k == "cost_per_success" and not has_cost):
                continue
            got = reported[k]
            if (v is None) != (got is None) or (v is not None and abs(float(v) - float(got)) > 1e-6):
                problems.append(f"metric {k} = {got} but its rows give {v} (report edited after the run)")

    # 6. ratchet against the spec on main
    if base_spec is not None:
        problems += _ratchet(spec, base_spec)
    return problems


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for sl in spec.get("slices") or []:
        name, metric = sl["name"], sl["metric"]
        sid = f"slice:{name}/{metric}"
        a, b = per_item(pr, metric, slice_name=name), per_item(base, metric, slice_name=name)
        verdict, note, val = "ok", "", None
        if not a:
            verdict = "missing"                      # an empty slice cannot vouch for anything
        else:
            val = round(sum(a.values()) / len(a), 4)
            if "min" in sl and val < sl["min"]:
                verdict = "fail"
            if sl.get("no_significant_drop"):
                keys = sorted(set(a) & set(b))
                if keys:
                    d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                                       n_resamples=bs.get("n_resamples", 1000),
                                                       rng=bs.get("rng", 2027),
                                                       confidence=bs.get("confidence", 0.95))
                    note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                    if hi < 0:
                        verdict = "fail"
        if verdict != "ok" and sl.get("blocking"):
            blocked.append(sid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if sl.get("blocking") else "warn")
        th = {k: sl[k] for k in ("min", "no_significant_drop") if k in sl}
        lines.append(f"  {sid:<34} {val!s:<8} n={len(a):<3} {json.dumps(th):<36} {note:<28} {label}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027),
                                               confidence=bs.get("confidence", 0.95))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
