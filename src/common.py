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

MODEL_PRIMARY = os.getenv("MODEL_PRIMARY", "gemini-3.5-flash-lite,gemini-3.1-flash-lite")  # brain: Gemini free tier; hands: Composio
MODEL_SECONDARY = os.getenv("MODEL_SECONDARY", "sonnet")  # second opinion: Claude Code CLI on a subscription
CONCURRENCY = int(os.getenv("CONCURRENCY", "3"))

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

NEGATIVE_VALUES = {"unknown", "none", "none_public", "none_found", "no_public_api", "not_applicable"}

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
        # Absence can't be cited: negative findings (no docs, no API, no MCP) may have a null source.
        if not x.get("source_url") and not set(map(str, vals)) <= NEGATIVE_VALUES and f != "main_blocker":
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
# Three interchangeable backends, picked from the model name:
#   gemini-*                          Gemini brain + Composio SDK hands (agent.py), both free tier
#   claude-* AND ANTHROPIC_API_KEY    Anthropic API with the server-side web_search tool (paid credits)
#   anything else (sonnet, opus)      Claude Code CLI in headless mode (`claude -p`), runs on a Claude subscription
from agent import RateLimited, QuotaExhausted  # noqa: E402  (agent.py has no import-time side effects)

def backend(model: str) -> str:
    if model.startswith("gemini"): return "gemini"
    if model.startswith("claude-") and os.getenv("ANTHROPIC_API_KEY"): return "anthropic_api"
    return "claude_cli"

EXHAUSTED_MODELS: set[str] = set()  # models whose free daily quota ran out during this run

async def ask(prompt_text: str, model: str, web_search: bool, max_uses: int = 6, retries: int = 4) -> tuple[str, dict]:
    """Call the model. Returns (final text, raw transcript dict with `search_urls` = URLs search really returned).
    `model` may be a comma-separated pool (e.g. two Gemini Flash-Lite models with separate daily quotas):
    when one hits its daily cap the whole call restarts on the next, so a transcript never mixes models."""
    pool = [m.strip() for m in model.split(",") if m.strip()]
    for m in pool:
        if m in EXHAUSTED_MODELS: continue
        b = backend(m)
        fn = {"gemini": _ask_gemini, "anthropic_api": _ask_anthropic_api, "claude_cli": _ask_claude_cli}[b]
        try:
            for attempt in range(retries):
                try:
                    text, raw = await fn(prompt_text, m, web_search, max_uses)
                    raw.update(backend=b, model=m)
                    return text, raw
                except (QuotaExhausted, SystemExit):
                    raise
                except RateLimited as e:  # per-minute limits and overload: back off hard
                    if attempt == retries - 1: raise
                    wait = 30 * (attempt + 1)
                    print(f"[{m}] busy ({str(e)[:60]}); retry in {wait}s", flush=True)
                    await asyncio.sleep(wait)
                except Exception:
                    if attempt == retries - 1: raise
                    await asyncio.sleep(2 ** attempt * 5)
        except QuotaExhausted:
            if m not in EXHAUSTED_MODELS: print(f"[{m}] daily free quota used up; switching model", flush=True)
            EXHAUSTED_MODELS.add(m)
    raise QuotaExhausted(f"every model in the pool is out of daily quota: {pool}")

# --- Claude Code CLI (subscription, no API credits) ---
CLI_BLOCKED_TOOLS = ["Bash", "PowerShell", "Edit", "Write", "Read", "Glob", "Grep", "Agent", "Task",
                     "NotebookEdit", "TodoWrite", "Skill"]
CLI_SYSTEM = ("You are a non-interactive research worker inside a batch pipeline. Never ask questions. "
              "Use at most {n} web searches. Your final message must contain only the requested JSON.")
CLI_SLOTS = asyncio.Semaphore(int(os.getenv("CLI_CONCURRENCY", "3")))

def _links_from_search_result(text: str) -> list[str]:
    """Claude Code's WebSearch result embeds `Links: [{"title":..,"url":..}, ...]`."""
    urls = []
    for m in re.finditer(r"Links:\s*(\[.*?\])\s*(?:\n|$)", text):
        try: urls += [x["url"] for x in json.loads(m.group(1)) if x.get("url")]
        except (json.JSONDecodeError, TypeError): pass
    return urls

async def _ask_claude_cli(prompt_text, model, web_search, max_uses):
    import shutil, tempfile
    exe = os.getenv("CLAUDE_BIN") or shutil.which("claude")
    if not exe: raise SystemExit("`claude` CLI not found. Install Claude Code and run `claude` once to log in.")
    if exe.lower().endswith(".cmd"):  # npm shim: cmd.exe re-parses args and breaks quoting; call the real binary
        real = Path(exe).parent/"node_modules"/"@anthropic-ai"/"claude-code"/"bin"/"claude.exe"
        if real.exists(): exe = str(real)
    blocked = CLI_BLOCKED_TOOLS + ([] if web_search else ["WebSearch", "WebFetch"])
    args = [exe, "-p", "--model", model, "--output-format", "stream-json", "--verbose", "--no-session-persistence",
            "--append-system-prompt", CLI_SYSTEM.format(n=max_uses if web_search else 0)]
    if web_search: args += ["--allowedTools", "WebSearch", "WebFetch"]
    args += ["--disallowedTools", *blocked]
    # Strip API credentials so the CLI uses the logged-in subscription, never paid API credits.
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
    async with CLI_SLOTS:
        proc = await asyncio.create_subprocess_exec(*args, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.PIPE, cwd=tempfile.gettempdir(), env=env)
        try:
            out, err = await asyncio.wait_for(proc.communicate(prompt_text.encode("utf-8")), timeout=900)
        except asyncio.TimeoutError:
            proc.kill(); raise RuntimeError("claude CLI timed out")
    events, search_urls, fetched_urls, final = [], [], [], None
    for line in out.decode("utf-8", errors="replace").splitlines():
        try: e = json.loads(line)
        except json.JSONDecodeError: continue
        events.append(e)
        content = (e.get("message") or {}).get("content")
        if e.get("type") == "assistant" and isinstance(content, list):
            fetched_urls += [b["input"]["url"] for b in content
                             if b.get("type") == "tool_use" and b.get("name") == "WebFetch" and b.get("input", {}).get("url")]
        if e.get("type") == "user" and isinstance(content, list):
            for b in content:
                if b.get("type") == "tool_result":
                    c = b.get("content")
                    text = c if isinstance(c, str) else " ".join(x.get("text", "") for x in c or [] if isinstance(x, dict))
                    search_urls += _links_from_search_result(text)
        if e.get("type") == "result": final = e
    if not final:
        msg = err.decode("utf-8", errors="replace")[-500:]
        if re.search(r"rate.?limit|usage limit|429", msg, re.I): raise RateLimited(msg.strip()[:120])
        raise RuntimeError(f"claude CLI produced no result: {msg}")
    if final.get("is_error"):
        detail = str(final.get("result") or final.get("api_error_status"))
        if re.search(r"rate.?limit|usage limit|429", detail, re.I): raise RateLimited(detail[:120])
        raise RuntimeError(f"claude CLI error: {detail[:300]}")
    return final.get("result") or "", {"search_urls": sorted(set(search_urls)), "fetched_urls": sorted(set(fetched_urls)),
                                       "num_turns": final.get("num_turns"), "events": events}

# --- Gemini brain + Composio hands (free tier): see agent.py ---
async def _ask_gemini(prompt_text, model, web_search, max_uses):
    import agent
    return await agent.run(prompt_text, model, use_tools=web_search, max_searches=max_uses)

# --- Anthropic API (paid; only used if a key is set and a full claude-* model id is given) ---
async def _ask_anthropic_api(prompt_text, model, web_search, max_uses):
    from anthropic import AsyncAnthropic
    version = "web_search_20250305" if "haiku" in model else "web_search_20260209"
    kw = dict(model=model, max_tokens=16000, messages=[{"role": "user", "content": prompt_text}])
    if web_search: kw["tools"] = [{"type": version, "name": "web_search", "max_uses": max_uses}]
    blocks = []
    for _ in range(5):  # server tools can stop with pause_turn; resend the partial turn
        r = await AsyncAnthropic().messages.create(**kw)
        blocks += r.model_dump()["content"]
        if r.stop_reason != "pause_turn": break
        kw["messages"] = [kw["messages"][0], {"role": "assistant", "content": r.content}]
    urls = [x.get("url") for b in blocks if b.get("type") == "web_search_tool_result" and isinstance(b.get("content"), list)
            for x in b["content"] if x.get("url")]
    return "".join(b.get("text", "") for b in blocks if b.get("type") == "text"), {"search_urls": urls, "content": blocks}

def url_key(u: str) -> str:
    """Compare URLs loosely: scheme, www, trailing slash and #fragment don't matter."""
    u = re.sub(r"^https?://(www\.)?", "", (u or "").strip().lower()).split("#")[0]
    return u.rstrip("/")

def searched_urls(raw: dict) -> set[str]:
    """URL keys the search tool actually returned (or the agent actually fetched). Citing anything else = likely invented."""
    return {url_key(u) for u in list(raw.get("search_urls", [])) + list(raw.get("fetched_urls", []))}

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
