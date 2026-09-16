"""Pass 3 prep: stratified human-review sample -> ground_truth/human_review.csv.

Strata (recorded per row so grading can report them separately):
  random    2 per category, seeded -> unbiased estimate of accuracy
  targeted  every app still low-confidence / needing a human, plus review_flags.json priors
The targeted stratum is deliberately hard, so never blend it into the headline number unlabelled."""
import csv, random
from common import DATA, GT, GRADED_FIELDS, seed, first, latest, load

def main(seed_value=7, per_cat=2, max_targeted=15):
    rnd = random.Random(seed_value)
    apps = seed()
    flags = load(DATA/"review_flags.json", {})
    prior = {s for k, v in flags.items() if not k.startswith("_") for s in v}
    strata = {}
    for cid in sorted({a["category_id"] for a in apps}):
        for a in rnd.sample([a for a in apps if a["category_id"] == cid], per_cat):
            strata[a["slug"]] = "random"
    # Targeted: priors and machine-flagged apps first, then the lowest-confidence apps up to a cap.
    def n_low(a):
        fin = latest("final", a["slug"]) or {}
        return sum(isinstance(x, dict) and x.get("confidence") == "low"
                   for f, x in fin.get("fields", {}).items() if f in GRADED_FIELDS)
    rest = [a for a in apps if a["slug"] not in strata]
    must = [a for a in rest if a["slug"] in prior or (latest("final", a["slug"]) or {}).get("needs_human")]
    lowc = sorted((a for a in rest if a not in must and n_low(a) > 0), key=n_low, reverse=True)
    for a in (must + lowc)[:max(max_targeted, len(must))]:
        strata[a["slug"]] = "targeted"
    GT.mkdir(exist_ok=True)
    path = GT/"human_review.csv"
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["stratum", "slug", "app", "field", "pass1_value", "final_value", "final_source_url",
                    "truth_value", "truth_source_url", "human_note"])
        for a in apps:
            if a["slug"] not in strata: continue
            p1, fin = first("pass1", a["slug"]) or {"fields": {}}, latest("final", a["slug"]) or {"fields": {}}
            for f in GRADED_FIELDS:
                pv, fv = p1["fields"].get(f, {}), fin["fields"].get(f, {})
                fmt = lambda x: ",".join(x) if isinstance(x, list) else (x or "")
                w.writerow([strata[a["slug"]], a["slug"], a["name"], f, fmt(pv.get("value")), fmt(fv.get("value")),
                            fv.get("source_url") or "", "", "", ""])
    n_r = sum(v == "random" for v in strata.values())
    print(f"{len(strata)} apps ({n_r} random, {len(strata)-n_r} targeted) -> {path}")
    print("Fill truth_value (same enums; lists comma-separated) + truth_source_url for every row. "
          "Open the CSV in a sheet so URLs are clickable.")

if __name__ == "__main__": main()
