# App Buildability Research Agent

**An AI research agent that looks at 100 SaaS apps and works out how hard it would be to build an AI-agent integration for each one. It then checks its own answers and publishes the results as a single page that people and other AI agents can both read.**

> 100 apps researched · 60 already in Composio, 40 not · **20 apps that could be built today and aren't in Composio yet** · every answer has a confidence level and a source link

---

## Why this exists

Teams that build agent toolkits, like [Composio](https://composio.dev), all hit the same question before writing any code: **can we actually build an integration for this app, and what's in the way?**

You can't answer that from a vendor's marketing page. The real blockers are usually hidden in the docs:

- **Auth:** does the app use OAuth2, API keys, JWT or HMAC signatures?
- **Access gates:** can a developer get credentials on their own, or does it take an app review, a paid plan or a partner deal?
- **API surface:** is there a full REST API, only GraphQL, a single endpoint, or no public API at all?
- **Hosting model:** is it a multi-tenant cloud app, one host per customer, or a local CLI tool?

Finding this by hand takes about 20–40 minutes per app, so 100 apps is roughly a week of work. Language models can do it much faster, but they tend to make up plausible answers, especially for apps with little public documentation.

**This project automates the research without trusting it blindly.** An agent fills in a strict schema for every app. Four independent checks then try to catch its mistakes, and people review a stratified sample so the accuracy estimate is honest. The output is a ranked build queue:

| Tier | Score | Apps |
|---|---|---|
| `build_now` | 7–9 | 72 |
| `build_with_friction` | 4–6 | 25 |
| `needs_outreach` | 0–3 | 1 |
| `local_toolkit` (CLI, no hosted API) | n/a | 2 |

It also finds patterns across all 100 apps. For example: *for 9 apps the real gate is app review, not auth* (Meta Ads, Shopify, WhatsApp Business…); *23 apps require payment before you can use the API*; and it flags which apps are GraphQL-only, need one host per tenant, or already ship an official MCP server.

### What this project demonstrates

- **Agentic system design:** a tool-using agent (Gemini as the brain, the Composio SDK as the hands) with a hand-written loop, so every tool call is logged, budgeted and throttled.
- **LLM reliability engineering:** citation grounding, a second model that answers the same questions independently, a check against Composio's catalog, and quote-backed re-verification.
- **Honest evaluation:** accuracy is graded against human ground truth, and random and hard samples are reported separately.
- **Shipping:** a static site plus a serverless "research any app live" endpoint, deployed on Vercel, with machine-readable outputs (`data.json`, `data.md`, `llms.txt`) for other agents.
- **Cost discipline:** runs entirely on free tiers (Gemini free tier, Composio Hobby plan, Claude Code CLI on a subscription).

**Tech stack:** Python (asyncio) · Google Gemini · Composio SDK · Claude (second-opinion model) · httpx / BeautifulSoup / Playwright · JSON Schema · Vercel serverless · static HTML

---

## Quick start: running the agents

### 1. Set up

```bash
git clone https://github.com/colinrozario/composio-agent.git
cd composio-agent
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # Windows: copy .env.example .env
```

Fill in `.env`:

| Variable | Where to get it |
|---|---|
| `GEMINI_API_KEY` | Free at [aistudio.google.com/apikey](https://aistudio.google.com/apikey) (the research agent's brain) |
| `COMPOSIO_API_KEY` | Free at platform.composio.dev → Settings → API keys (search and page-reading tools) |
| `MODEL_SECONDARY` | Defaults to `sonnet` through the Claude Code CLI (`claude -p`), used for the second-opinion check |

### 2. Try it on a few apps (smoke test)

```bash
python run.py smoke                     # researches Salesforce, Sherlock and Paygent Connect
python run.py pass1 hubspot stripe      # or pick any slugs from data/seed.json
```

### 3. Run the full pipeline

`run.py` works on every OS. On macOS or Linux, `make <step>` does the same thing.

```bash
python run.py catalog   # pass 0: pull Composio's toolkit catalog -> gap analysis + auth oracle
python run.py pass1     # pass 1: research agent runs once per app (resumable, append-only)
python run.py verify    # pass 2: link check, oracle, grounded re-ask, second-model diff, merge
python run.py sample    # pass 3 prep: stratified sample -> ground_truth/human_review.csv
#                       # ...fill truth_value + truth_source_url by hand...
python run.py grade     # grade pass 1 and the automated final against the same human truth
python run.py site      # patterns, build queue, site/data.json, data.md, llms.txt
python run.py serve     # open http://localhost:8000
```

`python run.py all` runs catalog → pass1 → verify → sample in one go. Pass 1 skips apps it has already researched, so an interrupted run picks up where it stopped (add `--redo` to force a fresh run).

**Preview the page before doing any research:** `cd src && python make_demo_data.py`, then `python run.py serve` (the page shows a demo banner).

---

## Pipeline

| Step | File | What it does | Output |
|---|---|---|---|
| 0 | `pass0_composio.py` | Pulls Composio's toolkit catalog and matches the 100 apps by slug or name | `data/composio_matches.json`, `composio_unmatched.json` |
| 1 | `pass1_research.py` + `agent.py` | The Gemini agent searches and reads docs through Composio tools, fills the schema, and records which URLs the tools actually returned | `data/raw/pass1/<slug>/<timestamp>.json` (+ `.raw.json` transcript) |
| 2a | `pass2_linkcheck.py` | Fetches every cited URL and flags 4xx errors, dead hosts, and redirects to homepages | `data/linkcheck.json` |
| 2b | `pass2_oracle.py` | Compares the agent's auth answer with Composio's `auth_schemes`; if they don't overlap, a human reviews it | `data/oracle.json` |
| 2c | `pass2_grounded.py` | For flagged fields only: fetches the page text and decides again with no search and no memory, backed by a required quote | `data/raw/pass2_grounded/` |
| 2d | `pass2_rephrased.py` | A different model answers a rephrased prompt; any field where the two disagree is flagged | `data/disagreements.json` |
| merge | `merge.py` | Automated final = pass 1 + grounded. Published = final + human corrections | `data/raw/final/`, `data/published.json` |
| 3 | `sample.py`, `grade.py` | Takes 2 random apps per category plus up to 15 deliberately hard apps and measures accuracy per field and per stratum | `ground_truth/human_review.csv`, `data/verification.json` |
| out | `cluster.py`, `build_site.py` | Counts patterns, builds the build queue and the page data | `data/patterns.json`, `site/*`, `web/*` |

## Design decisions worth defending

- **Confidence and source per field, not per app.** Auth is usually easy to find and access gates are not, so a single app-level score would hide that difference.
- **The prompt rewards `unknown`.** For apps with no public API, a made-up answer is the worst possible outcome.
- **Citation grounding.** If a `source_url` wasn't returned by the search tool, it's flagged as likely invented before anything is fetched.
- **Pass 1 is never overwritten.** `first()` reads the earliest run, so the before/after accuracy comparison is real.
- **Human corrections are not graded.** Grading uses `raw/final` (automated only), while `published.json` (with fixes) is what ships. Otherwise the accuracy number would just measure my own edits.
- **The oracle is never copied into answers.** Composio's catalog is used to grade and flag answers, not to overwrite them; otherwise the oracle's accuracy would be circular. It's also only a partial signal, because a toolkit may support only one of the vendor's auth schemes.
- **Two strata, reported separately.** The random stratum gives the honest estimate. The targeted stratum is deliberately hard.
- **The agent never sees `review_flags.json`.** Known trap apps are only used to force those apps into human review.
- **Scores, not verdicts.** Credential access 0–3, docs 0–2, breadth 0–2, test account 0–2 (`src/scoring.py`). CLI tools go into a separate local-toolkit tier instead of scoring 0.

## Human steps (log them in `ground_truth/human_log.md` as they happen)

- Matching unmatched seed apps to Composio slugs (`data/composio_slug_overrides.json`)
- Filling in ground truth
- Settling oracle and second-model disagreements (`ground_truth/corrections.json`)
- Writing the "so what" for each pattern (`data/pattern_notes.json`)
- Filling in `data/failures.json`

## Check before running

- Model names are env vars (`MODEL_PRIMARY`, `MODEL_SECONDARY`). `MODEL_PRIMARY` accepts a comma-separated pool, so when one free-tier model hits its daily quota, calls move to the next.
- Composio's free plan includes a small allowance for premium tools (Exa-backed search and page reads). `agent.py` keeps a conservative ledger and stops using premium tools before the allowance runs out. Tune the throttling with `CONCURRENCY`, `COMPOSIO_RPS` and `GEMINI_CONCURRENCY`.
- Docs pages that render with JavaScript return little text to `httpx`. Those rows are marked `docs_not_fetchable`, and Playwright is available as a headless-browser fallback.

## Deploy

On Vercel, `vercel.json` serves `web/` and runs `api/research.py`, the live "try it" box. It uses the same pass 1 prompt, schema and validation on the Gemini free tier, with caching and a best-effort limit of 5 runs per IP per hour.
Set `GEMINI_API_KEY` and `COMPOSIO_API_KEY` in the project env. Delete `site/data.sample.json` once `site/data.json` exists.

## Layout

```
schema/app_record.schema.json   strict output schema (enums drive prompts and validation)
prompts/                        pass1_research.md, pass2_grounded.md, pass2_rephrased.md
data/seed.json                  the 100 apps
src/                            pipeline (agent.py = Gemini brain + Composio hands)
run.py / Makefile               step runner (cross-platform / make)
ground_truth/                   human review CSV, corrections, human log
site/index.html                 the page (reads data.json only)
web/                            deployable copy of the page + data (Vercel output)
api/research.py                 live trigger
```
