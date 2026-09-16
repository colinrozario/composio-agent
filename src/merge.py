"""Build two outputs:
  raw/final/<slug>/*.json   AUTO final = pass1 + grounded re-ask. No human edits. This is what gets graded.
  data/published.json       AUTO final + human corrections from ground_truth/corrections.json. This is what ships.
Keeping them separate stops human fixes from inflating the measured accuracy."""
import copy
from common import DATA, RAW, GT, seed, first, latest, load, save, now
from scoring import score

def main():
    linkcheck = load(DATA/"linkcheck.json", {})
    oracle = load(DATA/"oracle.json", {})
    disagree = load(DATA/"disagreements.json", {}).get("by_app", {})
    matches = load(DATA/"composio_matches.json", {})
    corrections = load(GT/"corrections.json", {})  # {slug: {field: {"value":..,"source_url":..,"why":..}}}
    published = []
    for app in seed():
        p1 = first("pass1", app["slug"])
        if not p1: continue
        auto = copy.deepcopy(p1); auto["pass"] = "final"; auto["researched_at"] = now()
        g = latest("pass2_grounded", app["slug"])
        changed = []
        if g:
            for f, x in (g.get("result") or {}).items():
                if f in g.get("regraded_fields", []) and f in auto["fields"] and isinstance(x, dict) and "value" in x:
                    if x["value"] != auto["fields"][f].get("value"): changed.append(f)
                    auto["fields"][f] = {k: x.get(k) for k in ("value", "confidence", "source_url", "evidence_quote")}
        auto["grounded_changed"] = changed
        needs = []
        if app["slug"] in linkcheck.get("flagged", {}): needs.append("dead_or_redirected_citation")
        if app["slug"] in oracle.get("needs_human", []): needs.append("composio_auth_disagreement")
        if app["slug"] in disagree: needs.append("second_model_disagreement:" + ",".join(disagree[app["slug"]]))
        if g and not g.get("pages_usable") and g.get("regraded_fields"): needs.append("docs_not_fetchable")
        auto["needs_human"] = needs
        save(RAW/"final"/app["slug"]/f"{auto['researched_at'].replace(':','')}.json", auto)

        pub = copy.deepcopy(auto)
        pub["human_corrected"] = []
        for f, fix in corrections.get(app["slug"], {}).items():
            pub["fields"][f] = {"value": fix["value"], "confidence": "high",
                                "source_url": fix.get("source_url"), "evidence_quote": fix.get("why")}
            pub["human_corrected"].append(f)
        pub.update(category=app["category"], category_id=app["category_id"], hint=app["hint"],
                   in_composio=app["slug"] in matches, composio=matches.get(app["slug"]),
                   score=score(pub))
        published.append(pub)
    save(DATA/"published.json", published)
    print(f"merged {len(published)} apps; {sum(bool(p['needs_human']) for p in published)} still need a human look")

if __name__ == "__main__": main()
