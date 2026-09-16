"""Compute pattern counts from published data. Numbers come from here; the 'so what' lines are
written by a human in data/pattern_notes.json (judgment, not aggregation)."""
from collections import Counter, defaultdict
from common import DATA, load, save

def val(p, f): return p["fields"].get(f, {}).get("value")

def main():
    pub = load(DATA/"published.json")
    notes = load(DATA/"pattern_notes.json", {})
    names = lambda xs: sorted(p["name"] for p in xs)
    auth = Counter(a for p in pub for a in (val(p, "auth_methods") or []))
    tiers = Counter(p["score"]["tier"] for p in pub)
    by_cat = defaultdict(Counter)
    for p in pub: by_cat[p["category"]][p["score"]["tier"]] += 1
    blockers = Counter(val(p, "access_path") for p in pub)

    groups = {
        "app_review_gate": [p for p in pub if val(p, "access_path") == "app_review_required"],
        "paid_to_use": [p for p in pub if val(p, "access_path") == "paid_plan_required"],
        "per_tenant_host": [p for p in pub if val(p, "base_url_model") in ("per_tenant_subdomain", "self_hosted_or_customer_host")],
        "graphql_only": [p for p in pub if val(p, "api_type") == "graphql"],
        "official_mcp": [p for p in pub if val(p, "official_mcp") == "official"],
        "local_toolkit": [p for p in pub if val(p, "toolkit_bucket") == "local_or_sandbox_toolkit"],
        "dark": [p for p in pub if val(p, "access_path") in ("no_public_api", "partner_or_sales_gated")
                 or val(p, "docs_quality") == "none_public"],
    }
    patterns = [{"key": k, "count": len(v), "apps": names(v),
                 "headline": notes.get(k, {}).get("headline", k.replace("_", " ")),
                 "so_what": notes.get(k, {}).get("so_what", "TODO: write the so-what")} for k, v in groups.items()]
    missing = [p for p in pub if not p["in_composio"]]
    queue = {t: sorted(({"name": p["name"], "score": p["score"]["total"], "in_composio": p["in_composio"]}
                        for p in pub if p["score"]["tier"] == t), key=lambda x: -x["score"])
             for t in ("build_now", "build_with_friction", "needs_outreach", "local_toolkit")}
    out = {
        "totals": {"apps": len(pub), "in_composio": len(pub) - len(missing), "not_in_composio": len(missing),
                   "buildable_now_not_in_composio": sum(p["score"]["tier"] == "build_now" for p in missing)},
        "auth": auth.most_common(), "tiers": dict(tiers), "access_path": blockers.most_common(),
        "tier_by_category": {c: dict(t) for c, t in by_cat.items()},
        "patterns": patterns, "build_queue": queue,
    }
    save(DATA/"patterns.json", out)
    print(out["totals"]); [print(f"  {p['key']:<18} {p['count']:>3}  {', '.join(p['apps'][:6])}") for p in patterns]

if __name__ == "__main__": main()
