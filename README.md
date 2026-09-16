# App buildability research agent

Researches 100 apps for agent-toolkit buildability (auth, access gate, API surface, MCP, hosting model),
verifies its own answers with four independent loops plus a human sample, and publishes one static page
that humans and agents can both read (`/`, `/data.json`, `/data.md`, `/llms.txt`).

## Run it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env && export $(grep -v '^#' .env | xargs)   # ANTHROPIC_API_KEY, COMPOSIO_API_KEY

make catalog   # pass 0: Composio toolkit catalog -> gap analysis + auth oracle
make pass1     # pass 1: one web-search agent call per app (append-only raw outputs)
make verify    # pass 2: link check, oracle, grounded re-ask, second-model diff, merge
make sample    # pass 3 prep: stratified sample -> ground_truth/human_review.csv
#              # ...fill truth_value + truth_source_url by hand...
make grade     # pass 1 vs automated final, graded on the same human truth
make site      # patterns, build queue, site/data.json, data.md, llms.txt
make serve     # http://localhost:8000
```

One app only: `cd src && python pass1_research.py salesforce` (slugs are in `data/seed.json`).
Preview the page before any research: `cd src && python make_demo_data.py && make serve` (shows a demo banner).

## Pipeline

| Step | File | What it does | Output |
|---|---|---|---|
| 0 | `pass0_composio.py` | Pulls `GET /api/v3/toolkits`, matches the 100 by slug/name | `data/composio_matches.json`, `composio_unmatched.json` |
| 1 | `pass1_research.py` | Claude + server-side web search fills the schema; records which URLs search actually returned | `data/raw/pass1/<slug>/<timestamp>.json` (+ `.raw.json` transcript) |
| 2a | `pass2_linkcheck.py` | Fetches every cited URL; flags 4xx, dead hosts, redirects to homepages | `data/linkcheck.json` |
| 2b | `pass2_oracle.py` | Compares agent auth to Composio `auth_schemes`; no-overlap goes to a human | `data/oracle.json` |
| 2c | `pass2_grounded.py` | For flagged fields only: fetch page text, re-decide with no search and no memory, require a quote | `data/raw/pass2_grounded/` |
| 2d | `pass2_rephrased.py` | Different model, rephrased prompt; field disagreements are flagged | `data/disagreements.json` |
| merge | `merge.py` | Automated final = pass 1 + grounded. Published = final + human corrections | `data/raw/final/`, `data/published.json` |
| 3 | `sample.py`, `grade.py` | 2 random apps per category + up to 15 targeted hard apps; per-field, per-stratum accuracy | `ground_truth/human_review.csv`, `data/verification.json` |
| out | `cluster.py`, `build_site.py` | Pattern counts, build queue, page data | `data/patterns.json`, `site/*` |

## Design decisions worth defending

- **Confidence and source per field, not per app.** Auth is usually easy, access gates are not; one app-level score hides that.
- **`unknown` is rewarded in the prompt.** For apps with no public surface, an invented answer is the worst outcome.
- **Citation grounding.** A `source_url` not returned by the search tool is flagged as likely invented, before any fetch.
- **Pass 1 is never overwritten.** `first()` reads the earliest run so the before/after number is real.
- **Human corrections are not graded.** `raw/final` (automated) is graded; `published.json` (with fixes) ships. Otherwise accuracy measures my own edits.
- **Oracle is not copied into answers.** Composio's catalog is used to grade and flag, not to overwrite, or oracle accuracy is circular. It is also a subset signal: a toolkit may ship only one of the vendor's auth schemes.
- **Two strata, reported separately.** The random stratum is the honest estimate; the targeted stratum is deliberately hard.
- **`review_flags.json` never reaches the agent.** Priors about trap apps only force those apps into human review.
- **Score, not verdict.** Credential access 0-3, docs 0-2, breadth 0-2, test account 0-2 (`src/scoring.py`). CLI tools go to a separate local-toolkit tier instead of scoring 0.

## Human steps (log them in `ground_truth/human_log.md` as they happen)

Matching unmatched seed apps to Composio slugs (`data/composio_slug_overrides.json`), filling ground truth, adjudicating
oracle and second-model disagreements (`ground_truth/corrections.json`), writing the so-what for each pattern
(`data/pattern_notes.json`), and filling `data/failures.json`.

## Check before running

- Composio endpoint paths, pagination fields, and base URL in `pass0_composio.py` were written from the public API reference; confirm against current docs and adjust `COMPOSIO_BASE_URL` if needed.
- Model names are env vars (`MODEL_PRIMARY`, `MODEL_SECONDARY`). Web search must be enabled for your Anthropic org.
- JS-rendered docs return little text to `httpx`; those rows are marked `docs_not_fetchable`. Swap in a headless browser there if you have time.

## Deploy

Vercel: `vercel.json` serves `site/` and runs `api/research.py` (live "try it" box, same pass 1 agent, cached, 5 runs/IP/hour best effort).
Set `ANTHROPIC_API_KEY` in the project env. Delete `site/data.sample.json` once `site/data.json` exists.

## Layout

```
schema/app_record.schema.json   strict output schema (enums drive prompts and validation)
prompts/                        pass1_research.md, pass2_grounded.md, pass2_rephrased.md
data/seed.json                  the 100 apps
src/                            pipeline
ground_truth/                   human review CSV, corrections, human log
site/index.html                 the page (reads data.json only)
api/research.py                 live trigger
```
