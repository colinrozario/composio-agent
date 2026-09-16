"""Grade pass1 and auto-final against the same human ground truth, per field and per stratum."""
import csv
from collections import defaultdict
from common import DATA, GT, GRADED_FIELDS, load, save, norm

def acc(rows, col):
    ok = [norm(r["field"], r[col]) == norm(r["field"], r["truth_value"]) for r in rows]
    return round(sum(ok) / len(ok), 3) if ok else None

def main():
    rows = [r for r in csv.DictReader((GT/"human_review.csv").open(encoding="utf-8-sig", newline="")) if r["truth_value"].strip()]
    if not rows: raise SystemExit("ground_truth/human_review.csv has no truth_value filled in yet")
    out = {"n_rows": len(rows), "n_apps": len({r["slug"] for r in rows}), "overall": {}, "by_stratum": {}, "by_field": {}}
    block = lambda sub: {"pass1": acc(sub, "pass1_value"), "final": acc(sub, "final_value"), "n": len(sub)}
    out["overall"] = block(rows)
    for st in ("random", "targeted"):
        out["by_stratum"][st] = block([r for r in rows if r["stratum"] == st])
    for f in GRADED_FIELDS:
        sub = [r for r in rows if r["field"] == f]
        out["by_field"][f] = {"pass1": acc(sub, "pass1_value"), "final": acc(sub, "final_value"), "n": len(sub)}
    misses = []
    for r in rows:
        p1_ok = norm(r["field"], r["pass1_value"]) == norm(r["field"], r["truth_value"])
        f_ok = norm(r["field"], r["final_value"]) == norm(r["field"], r["truth_value"])
        if not (p1_ok and f_ok):
            misses.append({"app": r["app"], "field": r["field"], "pass1": r["pass1_value"], "final": r["final_value"],
                           "truth": r["truth_value"], "source": r["truth_source_url"], "note": r["human_note"],
                           "outcome": "fixed_by_loops" if f_ok else "regressed" if p1_ok else "still_wrong"})
    out["misses"] = misses
    out["outcomes"] = {k: sum(m["outcome"] == k for m in misses) for k in ("fixed_by_loops", "still_wrong", "regressed")}
    out["oracle"] = load(DATA/"oracle.json", {}).get("summary")
    out["disagreement"] = load(DATA/"disagreements.json", {}).get("per_field")
    lc = load(DATA/"linkcheck.json", {})
    out["linkcheck"] = {"checked_urls": lc.get("checked_urls"), "apps_flagged": len(lc.get("flagged", {}))}
    save(DATA/"verification.json", out)
    print("overall", out["overall"]); print("by stratum", out["by_stratum"])
    for f, v in out["by_field"].items(): print(f"  {f:<16} {v}")
    print("outcomes", out["outcomes"])

if __name__ == "__main__": main()
