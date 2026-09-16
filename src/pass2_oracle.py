"""Pass 2b: Composio oracle. Compare agent auth_methods to Composio's own auth_schemes.

Honesty rule: we do NOT copy oracle values into the final answer automatically. Disagreements
go to a human, who decides. Otherwise 'accuracy vs oracle' would be measuring a copy of itself.
Note the oracle is authoritative for what Composio *implements*, which can be a subset of what
the vendor offers (e.g. vendor supports api_key and oauth2, toolkit ships oauth2 only)."""
from common import DATA, seed, first, latest, load, save, norm

MAP = {"oauth2": "oauth2", "oauth1": "oauth2", "api_key": "api_key", "basic": "basic",
       "basic_with_jwt": "basic", "bearer_token": "bearer_token", "no_auth": "none",
       "google_service_account": "jwt", "service_account": "jwt"}

def to_ours(schemes):
    return tuple(sorted({MAP.get(str(s).lower(), str(s).lower()) for s in schemes}))

def compare(rec, oracle):
    ours = set(norm("auth_methods", rec["fields"].get("auth_methods", {}).get("value", [])))
    theirs = set(to_ours(oracle["auth_schemes"]))
    return {"agent": sorted(ours), "composio": sorted(theirs),
            "exact": ours == theirs, "overlap": bool(ours & theirs),
            "composio_subset_of_agent": theirs <= ours}

def main():
    matches = load(DATA/"composio_matches.json", {})
    out = {}
    for app in seed():
        o = matches.get(app["slug"])
        p1 = first("pass1", app["slug"])
        if not (o and p1): continue
        row = {"pass1": compare(p1, o)}
        final = latest("final", app["slug"])
        if final: row["final"] = compare(final, o)
        out[app["slug"]] = row
    summary = {}
    for k in ("pass1", "final"):
        rows = [r[k] for r in out.values() if k in r]
        n = len(rows)
        summary[k] = {"n": n, **({m: round(sum(r[f] for r in rows) / n, 3) for m, f in
                     [("exact", "exact"), ("overlap", "overlap"), ("oracle_subset", "composio_subset_of_agent")]} if n else {})}
    disagreements = [s for s, r in out.items() if not r["pass1"]["overlap"]]
    save(DATA/"oracle.json", {"summary": summary, "by_app": out, "needs_human": disagreements})
    print(summary); print("no-overlap disagreements -> human:", disagreements)

if __name__ == "__main__": main()
