"""The research agent: Gemini is the brain, Composio is the hands.

Brain  Gemini API (free tier). Decides what to search, which pages to read, and fills the schema.
Hands  Composio Python SDK. Every web action is a Composio tool call:
         COMPOSIO_SEARCH_WEB                web search (Exa), returns an answer plus cited URLs
         COMPOSIO_SEARCH_FETCH_URL_CONTENT  reads docs pages as clean markdown
       Composio's own toolkit catalog is read with the same SDK in pass0_composio.py.

The loop is manual rather than Gemini's automatic function calling so that every tool call is logged
(the citation check needs the exact URLs the hands returned), budgets are enforced, and search is throttled.
"""
from __future__ import annotations
import asyncio, json, os, time

COMPOSIO_USER = os.getenv("COMPOSIO_USER_ID", "research-agent")
SEARCH, FETCH = "COMPOSIO_SEARCH_WEB", "COMPOSIO_SEARCH_FETCH_URL_CONTENT"
MAX_TURNS = int(os.getenv("AGENT_MAX_TURNS", "6"))
PAGE_CHARS = int(os.getenv("AGENT_PAGE_CHARS", "6000"))

class RateLimited(Exception): pass
class QuotaExhausted(Exception):
    """Daily free-tier quota is gone. Batches stop cleanly and resume tomorrow."""

# ---------------- hands: Composio SDK ----------------
_composio = None
def composio():
    global _composio
    if _composio is None:
        if not os.getenv("COMPOSIO_API_KEY"): raise SystemExit("Set COMPOSIO_API_KEY in .env (free key)")
        from composio import Composio
        _composio = Composio()
    return _composio

class Throttle:
    """Exa-backed Composio search asks for ~1-2 requests/second; bursts get 429s."""
    def __init__(self, per_sec: float): self.gap, self.next, self.lock = 1 / per_sec, 0.0, asyncio.Lock()
    async def wait(self):
        async with self.lock:
            delay = self.next - time.monotonic()
            if delay > 0: await asyncio.sleep(delay)
            self.next = max(time.monotonic(), self.next) + self.gap

HANDS_THROTTLE = Throttle(float(os.getenv("COMPOSIO_RPS", "1.5")))

async def composio_execute(slug: str, arguments: dict, retries: int = 3) -> dict:
    """One Composio tool call (sync SDK, run in a thread). Returns {successful, data, error}."""
    for attempt in range(retries):
        await HANDS_THROTTLE.wait()
        try:
            r = await asyncio.to_thread(composio().tools.execute, slug, user_id=COMPOSIO_USER, arguments=arguments,
                                        dangerously_skip_version_check=True)
        except Exception as e:
            r = {"successful": False, "data": None, "error": f"{type(e).__name__}: {e}"}
        err = str(r.get("error") or "")
        if r.get("successful") or not any(k in err.lower() for k in ("429", "rate", "timeout", "503")):
            return r
        await asyncio.sleep(2 ** attempt * 2)
    return r

async def web_search(query: str) -> tuple[dict, list[str]]:
    """Returns (compact result for the brain, cited URLs for the citation check)."""
    r = await composio_execute(SEARCH, {"query": query})
    if not r.get("successful"): return {"error": str(r.get("error"))[:300]}, []
    d = r.get("data") or {}
    cites = [{"url": c.get("url"), "title": c.get("title")} for c in d.get("citations", []) if c.get("url")]
    for x in d.get("results", []) or []:  # some responses carry raw results instead of / as well as citations
        if isinstance(x, dict) and x.get("url"): cites.append({"url": x["url"], "title": x.get("title")})
    return {"answer": str(d.get("answer", ""))[:2500], "results": cites[:10]}, [c["url"] for c in cites]

async def fetch_pages(urls: list[str]) -> tuple[dict, list[str]]:
    """Returns (compact page texts for the brain, URLs that actually returned text)."""
    urls = [u for u in urls if isinstance(u, str) and u.startswith("http")][:3]
    if not urls: return {"error": "no valid http(s) urls"}, []
    r = await composio_execute(FETCH, {"urls": urls, "text": True, "max_characters": PAGE_CHARS})
    if not r.get("successful"): return {"error": str(r.get("error"))[:300]}, []
    pages, ok = [], []
    for x in (r.get("data") or {}).get("results", []) or []:
        text = (x.get("text") or "").strip()
        url = x.get("url") or x.get("id")
        if url and len(text) > 200: ok.append(url)
        pages.append({"url": url, "title": x.get("title"), "text": text[:PAGE_CHARS] or "(empty page)"})
    return {"pages": pages}, ok

# ---------------- brain: Gemini ----------------
_gemini = None
def gemini():
    global _gemini
    if _gemini is None:
        if not os.getenv("GEMINI_API_KEY"): raise SystemExit("Set GEMINI_API_KEY in .env (free key from aistudio.google.com)")
        os.environ.pop("GOOGLE_API_KEY", None)  # the SDK prefers GOOGLE_API_KEY if both exist
        from google import genai
        _gemini = genai.Client()
    return _gemini

BRAIN_SLOTS = asyncio.Semaphore(int(os.getenv("GEMINI_CONCURRENCY", "2")))

def _declarations():
    from google.genai import types
    return [types.Tool(function_declarations=[
        types.FunctionDeclaration(
            name="web_search",
            description="Search the web through Composio (COMPOSIO_SEARCH_WEB). Returns a short synthesized answer "
                        "plus result URLs. Treat the answer as a lead; confirm important facts by reading the page.",
            parameters_json_schema={"type": "object", "required": ["query"],
                                    "properties": {"query": {"type": "string", "description": "Search query"}}}),
        types.FunctionDeclaration(
            name="read_pages",
            description="Read up to 3 web pages through Composio (COMPOSIO_SEARCH_FETCH_URL_CONTENT). "
                        "Returns clean page text. Use on vendor docs, pricing and app-review pages.",
            parameters_json_schema={"type": "object", "required": ["urls"],
                                    "properties": {"urls": {"type": "array", "items": {"type": "string"}, "maxItems": 3}}}),
    ])]

async def _generate(model, contents, config):
    from google.genai import errors
    async with BRAIN_SLOTS:
        try:
            return await gemini().aio.models.generate_content(model=model, contents=contents, config=config)
        except errors.APIError as e:
            msg = str(e)
            if e.code == 429 and ("PerDay" in msg or "per day" in msg.lower()): raise QuotaExhausted(msg[:200])
            if e.code in (429, 503): raise RateLimited(msg[:160])
            raise

MIN_READS = int(os.getenv("AGENT_MIN_READS", "1"))

async def run(prompt_text: str, model: str, use_tools: bool, max_searches: int = 6, max_reads: int = 4) -> tuple[str, dict]:
    """Agent loop. Returns (final text, transcript with search_urls / fetched_urls / tool log)."""
    from google.genai import types
    system = ("You are a meticulous developer-relations researcher. Prefer calling several tools in parallel in one "
              "turn (e.g. 2-3 searches at once, then read 2-3 pages at once) to finish in few turns. "
              "Your final message must contain only the requested JSON.")
    config = types.GenerateContentConfig(
        system_instruction=system,
        tools=_declarations() if use_tools else None,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True) if use_tools else None)
    contents = [types.Content(role="user", parts=[types.Part(text=prompt_text)])]
    log, search_urls, fetched_urls, used = [], [], [], {"web_search": 0, "read_pages": 0}
    text, pushed_back = "", False
    for turn in range(MAX_TURNS + 1):
        last = turn == MAX_TURNS
        if last:  # out of turns: forbid tools and demand the answer
            contents.append(types.Content(role="user", parts=[types.Part(text="Tool budget exhausted. Return the final JSON now.")]))
            config.tool_config = types.ToolConfig(function_calling_config=types.FunctionCallingConfig(mode="NONE"))
        r = await _generate(model, contents, config)
        cand = r.candidates[0] if r.candidates else None
        if not cand or not cand.content: break
        contents.append(cand.content)  # keeps Gemini's thought signatures intact across turns
        calls = [p.function_call for p in cand.content.parts or [] if p.function_call]
        if not calls and use_tools and not last and used["read_pages"] < MIN_READS and not pushed_back:
            # Search snippets are summaries, not evidence. Make the brain open at least one vendor page.
            pushed_back = True
            log.append({"turn": turn, "tool": "_pushback", "args": {}, "ok": True})
            contents.append(types.Content(role="user", parts=[types.Part(text=
                "Before answering, call read_pages on the most authoritative vendor pages you found "
                "(API auth docs and the pricing or developer-access page). Then return the JSON.")]))
            continue
        if not calls or last:
            text = "".join(p.text or "" for p in cand.content.parts or [] if p.text and not p.thought)
            break

        async def do(call):
            args = dict(call.args or {})
            if call.name == "web_search" and used["web_search"] < max_searches:
                used["web_search"] += 1
                res, urls = await web_search(str(args.get("query", "")))
                search_urls.extend(urls)
            elif call.name == "read_pages" and used["read_pages"] < max_reads:
                used["read_pages"] += 1
                res, urls = await fetch_pages(list(args.get("urls") or []))
                fetched_urls.extend(urls)
            elif call.name in used:
                res = {"error": f"{call.name} budget used up; answer with what you have"}
            else:
                res = {"error": f"unknown tool {call.name}"}
            log.append({"turn": turn, "tool": call.name, "args": args, "ok": "error" not in res})
            return types.Part.from_function_response(name=call.name, response=res)

        parts = await asyncio.gather(*(do(c) for c in calls))
        contents.append(types.Content(role="user", parts=list(parts)))
    return text, {"search_urls": sorted(set(search_urls)), "fetched_urls": sorted(set(fetched_urls)),
                  "tool_calls": log, "tool_counts": used, "turns": len([c for c in contents if c.role == "model"])}
