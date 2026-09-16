"""Pass 0: read Composio's own toolkit catalog through the Composio Python SDK and match it to the 100 seed apps.

Gives two things: (1) the gap analysis (already shipped vs not) and
(2) an auth answer key for every overlapping app (auth_schemes Composio actually implements).
"""
import re
from common import DATA, seed, save, load, now
from agent import composio

# Seed slug -> Composio slug, where name matching fails. Filled by hand after reading
# data/composio_unmatched.json (a human step, logged on the page).
SLUG_OVERRIDES = {k: v for k, v in load(DATA/"composio_slug_overrides.json", {}).items() if not k.startswith("_")}

def squash(s): return re.sub(r"[^a-z0-9]", "", (s or "").lower())

def fetch_catalog() -> list[dict]:
    """All toolkits, paginated with the SDK's typed client (`composio.client.toolkits.list`)."""
    items, cursor, seen = [], None, set()
    while True:
        kw = {"limit": 1000, "include_deprecated": False}
        if cursor: kw["cursor"] = cursor
        page = composio().client.toolkits.list(**kw)
        items += [t.model_dump() for t in page.items]
        cursor = getattr(page, "next_cursor", None)
        if not cursor or cursor in seen: break
        seen.add(cursor)
    return items

def lookup(slug: str):
    """Direct retrieve. The list endpoint omits some toolkits (e.g. ones with 0 tools) that retrieve still returns."""
    try:
        t = composio().toolkits.get(slug=slug).model_dump()
    except Exception:
        return None
    t["auth_schemes"] = [a.get("mode") for a in t.get("auth_config_details") or [] if a.get("mode")]
    return t

def main():
    catalog = fetch_catalog()
    save(DATA/"composio_catalog.json", {"fetched_at": now(), "via": "composio SDK client.toolkits.list",
                                        "count": len(catalog), "items": catalog})
    by_slug = {squash(t["slug"]): t for t in catalog}
    by_name = {squash(t.get("name")): t for t in catalog}
    matches, unmatched = {}, []
    for app in seed():
        override = SLUG_OVERRIDES.get(app["slug"])
        if override is None and app["slug"] in SLUG_OVERRIDES: override = False
        if override is False:  # human decided: not in Composio (e.g. a name collision with a different product)
            unmatched.append({"slug": app["slug"], "name": app["name"], "human": "confirmed absent"}); continue
        t = by_slug.get(squash(override or app["slug"])) or by_name.get(squash(app["name"]))
        via_lookup = False
        if not t:
            for cand in dict.fromkeys([override or app["slug"], (override or app["slug"]).replace("_", "")]):
                t = lookup(cand)
                if t: via_lookup = True; break
        if t:
            meta = t.get("meta") or {}
            matches[app["slug"]] = {
                "composio_slug": t["slug"], "composio_name": t.get("name"),
                "matched_by": "human_override" if override else ("slug" if squash(app["slug"]) == squash(t["slug"]) else "name"),
                "found_via": "direct_lookup" if via_lookup else "catalog_list",
                "auth_schemes": t.get("auth_schemes") or [],
                "composio_managed_auth_schemes": t.get("composio_managed_auth_schemes") or [],
                "no_auth": t.get("no_auth"), "is_local_toolkit": t.get("is_local_toolkit"),
                "tools_count": meta.get("tools_count"), "triggers_count": meta.get("triggers_count"),
                "categories": [c.get("name") for c in meta.get("categories") or []],
            }
        else:
            unmatched.append({"slug": app["slug"], "name": app["name"],
                              "candidates": [x["slug"] for x in catalog
                                             if squash(app["name"])[:5] and squash(app["name"])[:5] in squash(x["slug"] + x.get("name", ""))][:5]})
    # Composio also wraps vendor MCP servers as `<app>_mcp` toolkits: reachable even without a native toolkit.
    mcp_wrapped = {}
    for app in seed():
        base = SLUG_OVERRIDES.get(app["slug"]) or app["slug"]
        for key in (squash(base) + "mcp", squash(base.split("_")[0]) + "mcp"):
            if key in by_slug:
                t = by_slug[key]
                mcp_wrapped[app["slug"]] = {"composio_slug": t["slug"], "tools_count": (t.get("meta") or {}).get("tools_count"),
                                            "auth_schemes": t.get("auth_schemes") or []}
                break
    save(DATA/"composio_mcp_wrapped.json", mcp_wrapped)
    save(DATA/"composio_matches.json", matches)
    save(DATA/"composio_unmatched.json", unmatched)
    print(f"catalog={len(catalog)} matched={len(matches)}/100 unmatched={len(unmatched)} "
          f"mcp_wrapped={len(mcp_wrapped)} (of which not native: {len(set(mcp_wrapped) - set(matches))})")
    print("Check data/composio_unmatched.json by hand: add real matches (or false) to data/composio_slug_overrides.json and rerun.")

if __name__ == "__main__": main()
