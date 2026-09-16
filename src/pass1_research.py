"""Pass 1: wide and cheap. One web-search agent call per app. Raw output is never overwritten."""
import asyncio, sys
from common import (RAW, MODEL_PRIMARY, seed, prompt, ask, extract_json, validate_fields,
                    searched_urls, save, now, gather_limited)

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
                              if isinstance(x, dict) and x.get("source_url") and x["source_url"] not in seen]
    rec["search_urls"] = sorted(seen)
    # Append-only: timestamped file per run, plus a raw transcript for audit.
    stamp = rec["researched_at"].replace(":", "")
    save(OUT/app["slug"]/f"{stamp}.json", rec)
    save(OUT/app["slug"]/f"{stamp}.raw.json", {"prompt": p, "response": raw})
    print(f"[pass1] {app['name']:<28} problems={len(rec['schema_problems'])} uncited={len(rec['uncited_sources'])}")
    return rec

async def main(only: list[str] | None):
    apps = [a for a in seed() if not only or a["slug"] in only]
    await gather_limited([research_one(a) for a in apps])

if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:] or None))
