"""Shared paths, IO, LLM client, JSON extraction, enum helpers."""
from __future__ import annotations
import asyncio, json, os, re, time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys
if hasattr(sys.stdout, "reconfigure"): sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows cp1252 console
try:  # load .env so scripts run without exporting vars (PowerShell has no `export`)
    from dotenv import load_dotenv; load_dotenv(ROOT/".env")
except ImportError:
    pass
DATA, RAW, PROMPTS, GT, SITE = ROOT/"data", ROOT/"data"/"raw", ROOT/"prompts", ROOT/"ground_truth", ROOT/"site"
SCHEMA = json.loads((ROOT/"schema"/"app_record.schema.json").read_text(encoding="utf-8"))
FIELDS = SCHEMA["properties"]["fields"]["required"]
# Fields graded for accuracy (free-text fields are reviewed, not scored)
GRADED_FIELDS = ["auth_methods", "access_path", "api_type", "api_breadth", "official_mcp",
                 "base_url_model", "toolkit_bucket", "docs_quality", "test_account"]

MODEL_PRIMARY = os.getenv("MODEL_PRIMARY", "claude-sonnet-5")
MODEL_SECONDARY = os.getenv("MODEL_SECONDARY", "claude-haiku-4-5")
CONCURRENCY = int(os.getenv("CONCURRENCY", "6"))

def now() -> str: return datetime.now(timezone.utc).isoformat(timespec="seconds")
def load(p: Path, default=None):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default
def save(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps(obj, indent=1, ensure_ascii=False), encoding="utf-8")
def seed() -> list[dict]: return load(DATA/"seed.json")
def prompt(name: str) -> str: return (PROMPTS/name).read_text(encoding="utf-8")

def enum_text() -> str:
    """Render allowed enum values from the schema so prompts and validation never drift."""
    lines = []
    for f, ref in SCHEMA["properties"]["fields"]["properties"].items():
        d = SCHEMA["$defs"][ref["$ref"].split("/")[-1]]
        v = d["allOf"][1]["properties"]["value"]
        allowed = v.get("enum") or v.get("items", {}).get("enum")
        lines.append(f"{f}: {', '.join(allowed)}" if allowed else f"{f}: free text")
    return "\n".join(lines)

def allowed_values(field: str):
    ref = SCHEMA["properties"]["fields"]["properties"][field]["$ref"].split("/")[-1]
    v = SCHEMA["$defs"][ref]["allOf"][1]["properties"]["value"]
    return v.get("enum") or v.get("items", {}).get("enum")

def extract_json(text: str) -> dict:
    """Pull the last top-level JSON object out of a model reply."""
    text = re.sub(r"```(?:json)?", "", text)
    depth, start, last = 0, None, None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0: start = i
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0: last = (start, i + 1)
    if not last: raise ValueError("no JSON object in reply")
    return json.loads(text[last[0]:last[1]])

def validate_fields(fields: dict) -> list[str]:
    """Return a list of schema problems (missing fields, bad enums, missing sources)."""
    problems = []
    for f in FIELDS:
        x = fields.get(f)
        if not isinstance(x, dict) or "value" not in x:
            problems.append(f"{f}: missing"); continue
        allowed = allowed_values(f)
        vals = x["value"] if isinstance(x["value"], list) else [x["value"]]
        if allowed and any(v not in allowed for v in vals):
            problems.append(f"{f}: bad enum {x['value']}")
        if x.get("confidence") not in ("high", "med", "low"):
            problems.append(f"{f}: bad confidence")
        if vals != ["unknown"] and not x.get("source_url"):
            problems.append(f"{f}: no source_url")
    return problems

def norm(field: str, value):
    """Normalise a value for comparison (sets for lists, lowercase strings)."""
    if isinstance(value, list): return tuple(sorted(str(v).strip().lower() for v in value))
    if isinstance(value, str) and "," in value and field == "auth_methods":
        return tuple(sorted(v.strip().lower() for v in value.split(",") if v.strip()))
    if field == "auth_methods" and isinstance(value, str): return (value.strip().lower(),)
    return str(value).strip().lower() if value is not None else ""

# ---------- LLM ----------
_client = None
def client():
    global _client
    if _client is None:
        from anthropic import AsyncAnthropic
        _client = AsyncAnthropic()
    return _client

def search_tool(model: str, max_uses: int) -> dict:
    """Dynamic-filtering web search needs Sonnet/Opus 4.6+; Haiku 4.5 only has the basic variant."""
    version = "web_search_20250305" if "haiku" in model else "web_search_20260209"
    return {"type": version, "name": "web_search", "max_uses": max_uses}

async def ask(prompt_text: str, model: str, web_search: bool, max_uses: int = 6, retries: int = 4) -> tuple[str, dict]:
    """Call the model. Returns (final text, raw response dict). Web search uses the server tool.
    Server tools can stop with pause_turn; we resend the partial turn until it finishes."""
    tools = [search_tool(model, max_uses)] if web_search else None
    messages = [{"role": "user", "content": prompt_text}]
    blocks = []
    for _ in range(5):  # pause_turn continuations
        for attempt in range(retries):
            try:
                kw = dict(model=model, max_tokens=16000, messages=messages)
                if tools: kw["tools"] = tools
                r = await client().messages.create(**kw)
                break
            except Exception:  # rate limits, overloads, transient network (SDK already retried twice)
                if attempt == retries - 1: raise
                await asyncio.sleep(2 ** attempt * 5)
        dump = r.model_dump()
        blocks += dump["content"]
        if r.stop_reason != "pause_turn": break
        messages = [messages[0], {"role": "assistant", "content": r.content}]
    dump["content"] = blocks  # full transcript across continuations, so searched_urls sees every result
    text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
    return text, dump

def searched_urls(raw: dict) -> set[str]:
    """URLs the web_search tool actually returned. Citing anything outside this set = likely invented."""
    urls = set()
    for b in raw.get("content", []):
        if b.get("type") == "web_search_tool_result" and isinstance(b.get("content"), list):
            urls.update(x.get("url") for x in b["content"] if x.get("url"))
    return urls

async def gather_limited(coros, limit=CONCURRENCY):
    sem = asyncio.Semaphore(limit)
    async def run(c):
        async with sem: return await c
    return await asyncio.gather(*(run(c) for c in coros))

def latest(pass_dir: str, slug: str) -> dict | None:
    """Most recent non-raw record for an app in data/raw/<pass_dir>/<slug>/."""
    d = RAW/pass_dir/slug
    files = sorted(p for p in d.glob("*.json") if not p.name.endswith(".raw.json")) if d.exists() else []
    return load(files[-1]) if files else None

def first(pass_dir: str, slug: str) -> dict | None:
    """Earliest record: the true first pass, used for the before/after accuracy number."""
    d = RAW/pass_dir/slug
    files = sorted(p for p in d.glob("*.json") if not p.name.endswith(".raw.json")) if d.exists() else []
    return load(files[0]) if files else None
