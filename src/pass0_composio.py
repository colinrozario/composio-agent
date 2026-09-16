"""Pass 0: pull Composio's toolkit catalog and match it to the 100 seed apps.

Gives two things: (1) the gap analysis (already shipped vs not) and
(2) an authoritative auth oracle for every overlapping app.

Endpoints (verify against current docs at docs.composio.dev before running):
  GET  {BASE}/api/v3.1/toolkits          paginated catalog (falls back to /api/v3/toolkits)
Header: x-api-key: $COMPOSIO_API_KEY
"""
import os, re, httpx
from common import DATA, seed, save, load, now

BASE = os.getenv("COMPOSIO_BASE_URL", "https://backend.composio.dev")
KEY = os.getenv("COMPOSIO_API_KEY")
# Seed slug -> Composio slug, where naive slugify will not match. Fill in after first run
# by looking at data/composio_unmatched.json. Human step, logged on the page.
SLUG_OVERRIDES = load(DATA/"composio_slug_overrides.json", {})

def squash(s): return re.sub(r"[^a-z0-9]", "", s.lower())

def fetch_catalog():
    with httpx.Client(base_url=BASE, headers={"x-api-key": KEY}, timeout=60) as c:
        for path in ("/api/v3.1/toolkits", "/api/v3/toolkits"):
            if c.get(path, params={"limit": 1}).status_code != 404: break
        items, cursor, seen = [], None, set()
        while True:
            params = {"limit": 500}
            if cursor: params["cursor"] = cursor
            r = c.get(path, params=params); r.raise_for_status()
            body = r.json()
            items += body.get("items", body if isinstance(body, list) else [])
            cursor = body.get("next_cursor") if isinstance(body, dict) else None
            if not cursor or cursor in seen: break
            seen.add(cursor)
    return items

def main():
    if not KEY: raise SystemExit("Set COMPOSIO_API_KEY (free project key)")
    catalog = fetch_catalog()
    save(DATA/"composio_catalog.json", {"fetched_at": now(), "count": len(catalog), "items": catalog})
    by_slug = {squash(t["slug"]): t for t in catalog}
    by_name = {squash(t.get("name", "")): t for t in catalog}
    matches, unmatched = {}, []
    for app in seed():
        key = SLUG_OVERRIDES.get(app["slug"], app["slug"])
        t = by_slug.get(squash(key)) or by_name.get(squash(app["name"]))
        if t:
            matches[app["slug"]] = {
                "composio_slug": t["slug"],
                "auth_schemes": t.get("auth_schemes", []),
                "composio_managed_auth_schemes": t.get("composio_managed_auth_schemes", []),
                "is_local_toolkit": t.get("is_local_toolkit"),
                "tools_count": t.get("meta", {}).get("tools_count", t.get("tools_count")),
                "triggers_count": t.get("meta", {}).get("triggers_count", t.get("triggers_count")),
            }
        else:
            unmatched.append({"slug": app["slug"], "name": app["name"]})
    save(DATA/"composio_matches.json", matches)
    save(DATA/"composio_unmatched.json", unmatched)
    print(f"catalog={len(catalog)} matched={len(matches)}/100 unmatched={len(unmatched)}")
    print("Review data/composio_unmatched.json by hand; add real matches to data/composio_slug_overrides.json and rerun.")

if __name__ == "__main__": main()
