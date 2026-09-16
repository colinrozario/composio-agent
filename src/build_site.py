"""Assemble site/data.json (the page reads only this), site/llms.txt and site/data.md for agents."""
from common import DATA, GT, SITE, ROOT, load, save, now
from scoring import WEIGHTS_FOR_PAGE

def cell(x): return x if not isinstance(x, list) else ", ".join(x)

def main():
    pub = load(DATA/"published.json"); pat = load(DATA/"patterns.json"); ver = load(DATA/"verification.json", {})
    moments = [l[2:].strip() for l in (GT/"human_log.md").read_text(encoding="utf-8").splitlines() if l.startswith("- ")] \
        if (GT/"human_log.md").exists() else []
    apps = [{
        "id": p["id"], "name": p["name"], "slug": p["slug"], "category": p["category"],
        "in_composio": p["in_composio"], "score": p["score"], "needs_human": p.get("needs_human", []),
        "human_corrected": p.get("human_corrected", []),
        "fields": {f: {"value": x.get("value"), "confidence": x.get("confidence"), "source_url": x.get("source_url")}
                   for f, x in p["fields"].items()},
    } for p in pub]
    data = {"meta": {"generated_at": now(), "demo": False, "repo": "https://github.com/colinrozario/composio-agent"},
            "headline": pat["totals"], "patterns": pat["patterns"], "build_queue": pat["build_queue"],
            "auth": pat["auth"], "tier_by_category": pat["tier_by_category"],
            "weights": WEIGHTS_FOR_PAGE, "apps": apps, "verification": ver, "human_moments": moments,
            "failures": load(DATA/"failures.json", [])}
    save(SITE/"data.json", data)

    md = ["# App buildability research: 100 apps", "",
          f"Generated {data['meta']['generated_at']}. Machine-readable: /data.json", "",
          "| App | Category | In Composio | Auth | Access | API | MCP | Score | Tier | Docs |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for a in apps:
        f = a["fields"]
        md.append(f"| {a['name']} | {a['category']} | {'yes' if a['in_composio'] else 'no'} | {cell(f['auth_methods']['value'])} | "
                  f"{f['access_path']['value']} | {f['api_type']['value']} | {f['official_mcp']['value']} | "
                  f"{a['score']['total']} | {a['score']['tier']} | {f['docs_url']['value']} |")
    (SITE/"data.md").write_text("\n".join(md), encoding="utf-8")
    (SITE/"llms.txt").write_text("\n".join([
        "# App buildability research (100 apps)",
        "> Auth, access gates, API surface and a 0-9 buildability score for 100 SaaS apps, "
        "verified against docs, a second model, Composio's catalog and a human sample.", "",
        "## Data", "- [data.json](/data.json): full dataset with per-field confidence and source URLs",
        "- [data.md](/data.md): the same matrix as a markdown table", "",
        "## Schema", "- Each field: value, confidence (high|med|low), source_url",
        "- score.total 0-9 = credential(0-3) + docs(0-2) + breadth(0-2) + test account(0-2)",
        "- tiers: build_now 7-9, build_with_friction 4-6, needs_outreach 0-3, local_toolkit (CLI, no hosted API)",
    ]), encoding="utf-8")
    web = ROOT/"web"  # standalone deployable page (web/index.html) reads the same files
    if web.exists():
        for name in ("data.json", "data.md", "llms.txt"): (web/name).write_bytes((SITE/name).read_bytes())
    print(f"site/data.json written ({len(apps)} apps)")

if __name__ == "__main__": main()
