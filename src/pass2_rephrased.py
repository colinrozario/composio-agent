"""Pass 2d: disagreement diff. Independent run with a different model and rephrased prompt.
Agreement is weak evidence of correctness; disagreement is strong evidence of a problem."""
import asyncio
from common import (DATA, RAW, MODEL_SECONDARY, seed, first, prompt, ask, extract_json, enum_text,
                    save, now, norm, gather_limited)

DIFF_FIELDS = ["auth_methods", "access_path", "api_type", "official_mcp", "base_url_model", "test_account"]

async def second_opinion(app):
    p = prompt("pass2_rephrased.md").format(name=app["name"], hint=app["hint"], enums=enum_text())
    text, raw = await ask(p, MODEL_SECONDARY, web_search=True, max_uses=4)
    try: fields = extract_json(text)
    except Exception as e: fields = {"_error": str(e)}
    rec = {"id": app["id"], "slug": app["slug"], "name": app["name"], "pass": "pass2_rephrased",
           "model": MODEL_SECONDARY, "researched_at": now(), "fields": fields}
    save(RAW/"pass2_rephrased"/app["slug"]/f"{rec['researched_at'].replace(':','')}.json", rec)
    return rec

async def main():
    apps = seed()
    seconds = await gather_limited([second_opinion(a) for a in apps])
    diffs = {}
    for app, s in zip(apps, seconds):
        p1 = first("pass1", app["slug"])
        if not p1: continue
        d = {}
        for f in DIFF_FIELDS:
            a = norm(f, p1["fields"].get(f, {}).get("value"))
            b = norm(f, s["fields"].get(f, {}).get("value") if isinstance(s["fields"].get(f), dict) else None)
            if a != b: d[f] = {"pass1": a, "second": b}
        if d: diffs[app["slug"]] = d
    per_field = {f: sum(f in d for d in diffs.values()) for f in DIFF_FIELDS}
    save(DATA/"disagreements.json", {"apps_with_disagreement": len(diffs), "per_field": per_field, "by_app": diffs})
    print(f"{len(diffs)} apps disagree; per field: {per_field}")

if __name__ == "__main__": asyncio.run(main())
