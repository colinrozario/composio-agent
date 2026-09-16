"""Pass 1: wide and cheap. One web-search agent call per app. Raw output is never overwritten."""
import asyncio, sys
from common import (RAW, MODEL_PRIMARY, seed, prompt, ask, extract_json, validate_fields,
                    searched_urls, url_key, save, now, gather_limited, first)

OUT = RAW/"pass1"

async def research_one(app: dict, model: str = MODEL_PRIMARY) -> dict:
    p = prompt("pass1_research.md").format(**app)
    text, raw = await ask(p, model, web_search=True)
    rec = {"id": app["id"], "slug": app["slug"], "name": app["name"], "pass": "pass1",
           "model": model, "researched_at": now()}
    try:
        rec["fields"] = extract_json(text)
        rec["schema_problems"] = validate_fields(rec["fields"])
    except Exception as e:
        rec["fields"], rec["schema_problems"] = {}, [f"parse_error: {e}"]
    # Citation grounding check: was each source_url actually returned by search?
    seen = searched_urls(raw)
    rec["uncited_sources"] = [f for f, x in rec["fields"].items()
                              if isinstance(x, dict) and x.get("source_url") and url_key(x["source_url"]) not in seen]
    rec["search_urls"] = sorted(set(raw.get("search_urls", [])))
    rec["backend"] = raw.get("backend")
    # Append-only: timestamped file per run, plus a raw transcript for audit.
    stamp = rec["researched_at"].replace(":", "")
    save(OUT/app["slug"]/f"{stamp}.json", rec)
    save(OUT/app["slug"]/f"{stamp}.raw.json", {"prompt": p, "response": raw})
    print(f"[pass1] {app['name']:<28} problems={len(rec['schema_problems'])} uncited={len(rec['uncited_sources'])}")
    return rec

async def safe(app):
    try: return await research_one(app)
    except (Exception, SystemExit) as e:  # one bad app must not kill the batch; rerun picks it up
        print(f"[pass1] {app['name']:<28} FAILED {type(e).__name__}: {str(e)[:120]}")

async def main(only: list[str] | None, redo: bool):
    apps = [a for a in seed() if not only or a["slug"] in only]
    todo = [a for a in apps if redo or not first("pass1", a["slug"])]  # resumable: skip apps already researched
    print(f"pass1: {len(todo)} to research, {len(apps) - len(todo)} already done")
    await gather_limited([safe(a) for a in todo])

if __name__ == "__main__":
    args = sys.argv[1:]
    asyncio.run(main([a for a in args if not a.startswith("--")] or None, "--redo" in args))
