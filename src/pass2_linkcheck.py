"""Pass 2a: fetch every cited URL. Flags 4xx/5xx, dead hosts, and redirects to marketing homepages.
Catches the #1 failure mode on obscure apps: invented documentation URLs."""
import asyncio
from urllib.parse import urlparse
import httpx
from common import DATA, seed, first, save, gather_limited

DOCSY = ("api", "developer", "docs", "reference", "dev.", "github.com", "help", "support", "pricing")

async def check(c: httpx.AsyncClient, url: str) -> dict:
    try:
        r = await c.get(url, follow_redirects=True)
        final = str(r.url)
        path = urlparse(final).path.strip("/")
        flags = []
        if r.status_code >= 400: flags.append(f"http_{r.status_code}")
        if urlparse(final).netloc.split(":")[0].removeprefix("www.") != urlparse(url).netloc.removeprefix("www."):
            flags.append("cross_domain_redirect")
        if final != url and path == "": flags.append("redirect_to_homepage")
        if not any(k in final.lower() for k in DOCSY): flags.append("not_docs_like")
        return {"url": url, "status": r.status_code, "final_url": final, "flags": flags}
    except Exception as e:
        return {"url": url, "status": None, "final_url": None, "flags": [f"fetch_error:{type(e).__name__}"]}

BOT_WALL = {401, 403, 405, 429, 503}

async def browser_status(url: str):
    """Re-check a bot-walled URL in headless Chromium. Returns (status, final_url) or None."""
    global _pw, _browser
    try:
        if _browser is None:
            from playwright.async_api import async_playwright
            _pw = await async_playwright().start(); _browser = await _pw.chromium.launch()
        async with BROWSER_SLOTS:
            page = await _browser.new_page()
            try:
                r = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                return (r.status if r else None), page.url
            finally:
                await page.close()
    except Exception:
        return None

_pw = _browser = None
BROWSER_SLOTS = asyncio.Semaphore(3)

async def check_with_fallback(c, url):
    res = await check(c, url)
    if res["status"] in BOT_WALL or any(f.startswith("fetch_error") for f in res["flags"]):
        b = await browser_status(url)
        if b and b[0] and b[0] < 400:
            res.update(status=b[0], final_url=b[1], via="browser",
                       flags=[f for f in res["flags"] if not f.startswith(("http_", "fetch_error"))])
    return res

async def main():
    headers = {"User-Agent": "Mozilla/5.0 (research-agent linkcheck)"}
    results = {}
    async with httpx.AsyncClient(timeout=20, headers=headers) as c:
        jobs = []
        for app in seed():
            rec = first("pass1", app["slug"])
            if not rec: continue
            for f, x in rec["fields"].items():
                if isinstance(x, dict) and x.get("source_url"):
                    jobs.append((app["slug"], f, x["source_url"]))
        uniq = sorted({u for _, _, u in jobs})
        checked = dict(zip(uniq, await gather_limited([check_with_fallback(c, u) for u in uniq], limit=12)))
    for slug, f, u in jobs:
        results.setdefault(slug, {})[f] = checked[u]
    bad = {s: {f: r for f, r in fs.items() if set(r["flags"]) - {"not_docs_like"}} for s, fs in results.items()}
    bad = {s: fs for s, fs in bad.items() if fs}
    if _browser: await _browser.close(); await _pw.stop()
    save(DATA/"linkcheck.json", {"checked_urls": len(checked), "needed_browser": sum(r.get("via") == "browser" for r in checked.values()), "by_app": results, "flagged": bad})
    print(f"checked {len(checked)} urls, {len(bad)} apps have a hard-failing citation")

if __name__ == "__main__": asyncio.run(main())
