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
        checked = dict(zip(uniq, await gather_limited([check(c, u) for u in uniq], limit=12)))
    for slug, f, u in jobs:
        results.setdefault(slug, {})[f] = checked[u]
    bad = {s: {f: r for f, r in fs.items() if set(r["flags"]) - {"not_docs_like"}} for s, fs in results.items()}
    bad = {s: fs for s, fs in bad.items() if fs}
    save(DATA/"linkcheck.json", {"checked_urls": len(checked), "by_app": results, "flagged": bad})
    print(f"checked {len(checked)} urls, {len(bad)} apps have a hard-failing citation")

if __name__ == "__main__": asyncio.run(main())
