"""Writes site/data.sample.json with FAKE apps so the page can be styled before the pipeline runs.
The page shows a demo banner whenever meta.demo is true. Never deploy this file as findings."""
import random
from common import SITE, seed, save, now
from scoring import score, WEIGHTS_FOR_PAGE

rnd = random.Random(3)
pick = lambda xs, w=None: rnd.choices(xs, weights=w)[0]
apps = []
for a in seed():
    f = lambda v, c=None: {"value": v, "confidence": c or pick(["high", "med", "low"], [6, 3, 1]), "source_url": "https://example.com/docs"}
    fields = {
        "one_liner": f("Demo app description"), "auth_methods": f(pick([["oauth2"], ["api_key"], ["oauth2", "api_key"], ["basic"]], [5, 3, 3, 1])),
        "access_path": f(pick(["self_serve_free", "self_serve_trial", "app_review_required", "paid_plan_required", "partner_or_sales_gated", "no_public_api"], [6, 2, 2, 2, 1, 1])),
        "api_type": f(pick(["rest", "graphql", "rest_and_graphql"], [8, 1, 1])), "api_breadth": f(pick(["broad", "narrow", "single_endpoint"], [6, 3, 1])),
        "official_mcp": f(pick(["official", "community_only", "none_found"], [2, 3, 5])),
        "base_url_model": f(pick(["fixed", "per_tenant_subdomain", "self_hosted_or_customer_host"], [7, 2, 1])),
        "toolkit_bucket": f(pick(["remote_api_toolkit", "local_or_sandbox_toolkit", "wrap_existing_mcp"], [16, 1, 1])),
        "docs_quality": f(pick(["full_public_reference", "partial_or_thin", "none_public"], [6, 3, 1])),
        "test_account": f(pick(["free_tier_or_sandbox", "trial_only", "none"], [6, 3, 1])),
        "main_blocker": f("Demo blocker"), "docs_url": f("https://example.com/docs"),
    }
    rec = {"id": a["id"], "name": f"Demo app {a['id']:03d}", "slug": f"demo_{a['id']}", "category": a["category"],
           "in_composio": rnd.random() < .55, "fields": fields, "needs_human": ["demo flag"] if rnd.random() < .15 else [],
           "human_corrected": []}
    rec["score"] = score(rec); apps.append(rec)
missing = [x for x in apps if not x["in_composio"]]
queue = {t: sorted(({"name": x["name"], "score": x["score"]["total"], "in_composio": x["in_composio"]} for x in apps if x["score"]["tier"] == t), key=lambda y: -y["score"])
         for t in ("build_now", "build_with_friction", "needs_outreach", "local_toolkit")}
pats = [("app_review_gate", "App review is the real gate, not auth", "access_path", "app_review_required"),
        ("paid_to_use", "Free to read, paid to call", "access_path", "paid_plan_required"),
        ("per_tenant_host", "Every customer has a different host", "base_url_model", "per_tenant_subdomain"),
        ("official_mcp", "Vendor MCP already exists", "official_mcp", "official")]
fields_list = ["auth_methods", "access_path", "api_type", "api_breadth", "official_mcp", "base_url_model", "toolkit_bucket", "docs_quality", "test_account"]
data = {
  "meta": {"generated_at": now(), "demo": True, "repo": "https://github.com/YOUR_USER/app-research"},
  "headline": {"apps": 100, "in_composio": 100 - len(missing), "not_in_composio": len(missing),
               "buildable_now_not_in_composio": sum(x["score"]["tier"] == "build_now" for x in missing)},
  "patterns": [{"key": k, "headline": h, "so_what": "Demo so-what line.", "apps": [x["name"] for x in apps if x["fields"][fld]["value"] == val],
                "count": sum(x["fields"][fld]["value"] == val for x in apps)} for k, h, fld, val in pats],
  "build_queue": queue, "auth": [], "tier_by_category": {}, "weights": WEIGHTS_FOR_PAGE, "apps": apps,
  "verification": {"by_stratum": {"random": {"pass1": .71, "final": .89, "n": 180}, "targeted": {"pass1": .52, "final": .78, "n": 99}},
                   "by_field": {f: {"pass1": round(rnd.uniform(.5, .9), 2), "final": round(rnd.uniform(.8, .98), 2), "n": 31} for f in fields_list},
                   "misses": [{"app": "Demo app 007", "field": "access_path", "pass1": "self_serve_free", "final": "app_review_required", "truth": "app_review_required", "source": "https://example.com"},
                              {"app": "Demo app 042", "field": "official_mcp", "pass1": "official", "final": "official", "truth": "community_only", "source": "https://example.com"}],
                   "outcomes": {"fixed_by_loops": 21, "still_wrong": 9, "regressed": 2},
                   "oracle": {"pass1": {"n": 55, "exact": .8}, "final": {"n": 55, "exact": .91}},
                   "disagreement": {"auth_methods": 6, "access_path": 14}, "linkcheck": {"checked_urls": 812, "apps_flagged": 11}},
  "human_moments": ["Demo: decided a free tier whose needed endpoint is enterprise-only counts as paid plan required."],
  "failures": [{"app": "Demo app 084", "what_happened": "Agent cited a docs URL that returns 404.", "reality": "No public developer docs found.", "source_url": None}],
}
save(SITE/"data.sample.json", data); print("site/data.sample.json written (fake data)")
