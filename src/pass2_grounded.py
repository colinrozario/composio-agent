"""Pass 2c: grounded re-ask. For flagged fields, fetch real page text and re-decide with NO search
and NO memory allowed. Kills memory-based guessing.

A row is flagged if: any low-confidence field, a hard-failing citation, an uncited source,
a schema problem, or a no-overlap disagreement with the Composio oracle."""
import asyncio, json, re, sys
import httpx
from bs4 import BeautifulSoup
from common import (DATA, RAW, MODEL_PRIMARY, GRADED_FIELDS, seed, first, load, save, prompt,
                    ask, extract_json, enum_text, now, gather_limited)

MAX_CHARS_PER_PAGE = 12000

def flagged_fields(slug, rec, linkcheck, oracle) -> list[str]:
    f = {k for k, x in rec["fields"].items() if isinstance(x, dict) and x.get("confidence") == "low"}
    f |= set(linkcheck.get("flagged", {}).get(slug, {}).keys())
    f |= set(rec.get("uncited_sources", []))
    f |= {p.split(":")[0] for p in rec.get("schema_problems", []) if ":" in p and not p.startswith("parse_error")}
    if slug in oracle.get("needs_human", []): f.add("auth_methods")
    if any(p.startswith("parse_error") for p in rec.get("schema_problems", [])): f |= set(GRADED_FIELDS)
    return sorted(f)

def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "nav", "footer", "svg"]): t.decompose()
    return re.sub(r"\s+", " ", soup.get_text(" ")).strip()

_browser, _browser_lock = None, asyncio.Lock()
BROWSER_SLOTS = asyncio.Semaphore(3)

async def browser():
    """Lazily start one headless Chromium; None if Playwright isn't installed."""
    global _browser
    async with _browser_lock:
        if _browser is None:
            try:
                from playwright.async_api import async_playwright
                _browser = await (await async_playwright().start()).chromium.launch()
            except Exception as e:
                print(f"[grounded] no headless browser ({type(e).__name__}); JS-rendered docs go to a human")
                _browser = False
    return _browser or None

async def rendered_text(url):
    b = await browser()
    if not b: return None
    async with BROWSER_SLOTS:
        page = await b.new_page()
        try:
            resp = await page.goto(url, wait_until="networkidle", timeout=30000)
            if resp and resp.status >= 400: return None
            return html_to_text(await page.content())
        except Exception:
            return None
        finally:
            await page.close()

FETCH_MODE = {}  # url -> "http" | "browser", reported on the page

async def page_text(c, url):
    """Plain HTTP first; if the page is JS-rendered (near-empty text) or blocks bots, render it in Chromium."""
    text = None
    try:
        r = await c.get(url, follow_redirects=True)
        if r.status_code < 400: text = html_to_text(r.text)
    except Exception:
        pass
    if text and len(text) > 400:
        FETCH_MODE[url] = "http"; return text[:MAX_CHARS_PER_PAGE]
    text = await rendered_text(url)
    if text and len(text) > 400:
        FETCH_MODE[url] = "browser"; return text[:MAX_CHARS_PER_PAGE]
    return None  # still nothing: a human-needed case

async def regrade(c, app, rec, fields):
    urls = {x["source_url"] for x in rec["fields"].values() if isinstance(x, dict) and x.get("source_url")}
    hint = app["hint"].split(" ")[0]
    urls.add(hint if hint.startswith("http") else f"https://{hint}")
    pages = {u: await page_text(c, u) for u in sorted(urls)}
    usable = {u: t for u, t in pages.items() if t}
    out = {"id": app["id"], "slug": app["slug"], "name": app["name"], "pass": "pass2_grounded",
           "model": MODEL_PRIMARY, "researched_at": now(), "regraded_fields": fields,
           "pages_tried": list(pages), "pages_usable": list(usable)}
    if not usable:
        out["result"], out["note"] = {}, "no fetchable page text (JS-rendered, blocked, or invented URLs) -> human"
    else:
        p = prompt("pass2_grounded.md").format(
            name=app["name"], fields=", ".join(fields),
            previous=json.dumps({f: rec["fields"].get(f) for f in fields}, indent=1),
            pages="\n\n".join(f"### {u}\n{t}" for u, t in usable.items()), enums=enum_text())
        text, _ = await ask(p, MODEL_PRIMARY, web_search=False)
        try: out["result"] = extract_json(text)
        except Exception as e: out["result"], out["note"] = {}, f"parse_error {e}"
    save(RAW/"pass2_grounded"/app["slug"]/f"{out['researched_at'].replace(':','')}.json", out)
    print(f"[grounded] {app['name']:<28} fields={len(fields)} pages={len(usable)}")
    return out

async def main(only):
    linkcheck, oracle = load(DATA/"linkcheck.json", {}), load(DATA/"oracle.json", {})
    async with httpx.AsyncClient(timeout=25, headers={"User-Agent": "Mozilla/5.0"}) as c:
        jobs = []
        for app in seed():
            if only and app["slug"] not in only: continue
            rec = first("pass1", app["slug"])
            if not rec: continue
            fields = flagged_fields(app["slug"], rec, linkcheck, oracle)
            if fields: jobs.append(regrade(c, app, rec, fields))
        print(f"{len(jobs)} apps flagged for grounded re-ask")
        await gather_limited(jobs)
    modes = list(FETCH_MODE.values())
    save(DATA/"fetch_modes.json", {"http": modes.count("http"), "browser": modes.count("browser"), "by_url": FETCH_MODE})
    print(f"pages read: {modes.count('http')} via http, {modes.count('browser')} needed the headless browser")
    if _browser: await _browser.close()

if __name__ == "__main__": asyncio.run(main(sys.argv[1:] or None))
