"""Transparent 0-9 buildability score. Weights are shown on the page.

Why credential access is worth 3 and docs only 2: bad docs cost an engineer a day,
a partnership or app-review gate can cost a quarter.
"""
CREDENTIAL = {  # 0-3
    "self_serve_free": 3, "self_serve_trial": 2, "not_applicable_local": 3,
    "app_review_required": 1, "paid_plan_required": 1,
    "partner_or_sales_gated": 0, "no_public_api": 0, "unknown": 0,
}
DOCS = {"full_public_reference": 2, "partial_or_thin": 1, "none_public": 0, "unknown": 0}   # 0-2
BREADTH = {"broad": 2, "narrow": 1, "single_endpoint": 0, "none": 0, "unknown": 0}          # 0-2
TEST = {"free_tier_or_sandbox": 2, "trial_only": 1, "none": 0, "unknown": 0}               # 0-2

WEIGHTS_FOR_PAGE = [
    ["Credential access", 3, "self-serve key 3 / trial 2 / app review or paid plan 1 / partner, sales or none 0"],
    ["Docs quality", 2, "full public reference 2 / thin 1 / none 0"],
    ["API breadth", 2, "broad CRUD 2 / narrow 1 / single endpoint 0"],
    ["Test account", 2, "free tier or sandbox 2 / trial 1 / none 0"],
]

def v(rec, f):
    return rec["fields"].get(f, {}).get("value", "unknown")

def score(rec: dict) -> dict:
    parts = {
        "credential": CREDENTIAL.get(v(rec, "access_path"), 0),
        "docs": DOCS.get(v(rec, "docs_quality"), 0),
        "breadth": BREADTH.get(v(rec, "api_breadth"), 0),
        "test": TEST.get(v(rec, "test_account"), 0),
    }
    total = sum(parts.values())
    tier = "build_now" if total >= 7 else "build_with_friction" if total >= 4 else "needs_outreach"
    # Local CLI tools are a different product shape, not a low score.
    if v(rec, "toolkit_bucket") == "local_or_sandbox_toolkit": tier = "local_toolkit"
    return {"total": total, "parts": parts, "tier": tier}
