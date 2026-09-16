"""Pass 2d: disagreement diff. Independent run with a different model and rephrased prompt.
Agreement is weak evidence of correctness; disagreement is strong evidence of a problem."""
import asyncio
from common import (DATA, RAW, MODEL_SECONDARY, seed, first, prompt, ask, extract_json, enum_text,
                    save, now, norm, gather_limited, latest)

DIFF_FIELDS = ["auth_methods", "access_path", "api_type", "official_mcp", "base_url_model", "test_account"]

async def second_opinion(app):
    done = latest("pass2_rephrased", app["slug"])
    if done and "_error" not in done["fields"]: return done  # resumable: free-tier quotas run out mid-batch
    p = prompt("pass2_rephrased.md").format(name=app["name"], hint=app["hint"], enums=enum_text())
    try:
        text, raw = await ask(p, MODEL_SECONDARY, web_search=True, max_uses=4)
        fields = extract_json(text)
    except (Exception, SystemExit) as e:
        print(f"[second] {app['name']:<28} FAILED {type(e).__name__}: {str(e)[:120]}")
        return {"fields": {"_error": str(e)}}
    if not isinstance(fields, dict): fields = {"_error": "reply was not a JSON object"}
    rec = {"id": app["id"], "slug": app["slug"], "name": app["name"], "pass": "pass2_rephrased",
           "model": raw.get("model"), "backend": raw.get("backend"), "researched_at": now(), "fields": fields,
           "search_urls": raw.get("search_urls", [])}
    save(RAW/"pass2_rephrased"/app["slug"]/f"{rec['researched_at'].replace(':','')}.json", rec)
    print(f"[second] {app['name']:<28} ok")
    return rec

async def main(only):
    apps = [a for a in seed() if not only or a["slug"] in only]
    seconds = await gather_limited([second_opinion(a) for a in apps])
    diffs = {}
    for app, s in zip(apps, seconds):
        p1 = first("pass1", app["slug"])
        if not p1 or "_error" in s["fields"]: continue
        d = {}
        for f in DIFF_FIELDS:
            a = norm(f, p1["fields"].get(f, {}).get("value"))
            b = norm(f, s["fields"].get(f, {}).get("value") if isinstance(s["fields"].get(f), dict) else None)
            if a != b: d[f] = {"pass1": a, "second": b}
        if d: diffs[app["slug"]] = d
    per_field = {f: sum(f in d for d in diffs.values()) for f in DIFF_FIELDS}
    failed = [a["slug"] for a, s in zip(apps, seconds) if "_error" in s["fields"]]
    save(DATA/"disagreements.json", {"model": MODEL_SECONDARY, "apps_compared": len(apps) - len(failed), "failed": failed,
                                     "apps_with_disagreement": len(diffs), "per_field": per_field, "by_app": diffs})
    print(f"{len(diffs)} apps disagree; per field: {per_field}")

if __name__ == "__main__":
    import sys
    asyncio.run(main(sys.argv[1:] or None))
