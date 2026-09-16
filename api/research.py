"""Vercel Python function: POST {"name": "..."} -> pass 1 schema for an app not in the 100.
Same prompt, schema and validation as the batch agent, but on the Gemini free tier (LIVE_MODEL):
a serverless function can't run the Claude Code CLI that the batch run used. In-memory cache + crude per-IP rate limit
(best effort on serverless; put Upstash/KV behind it if you need it to be strict)."""
import asyncio, json, os, re, sys, time
os.environ.setdefault("ASK_RETRIES", "2")  # fail fast: a serverless request can't sit through long backoffs
from http.server import BaseHTTPRequestHandler
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"src"))

CACHE, HITS, LIMIT, WINDOW = {}, {}, 5, 3600

class handler(BaseHTTPRequestHandler):
    def _send(self, code, body):
        self.send_response(code); self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def do_POST(self):
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))) or b"{}")
            name = re.sub(r"[^\w .&()+-]", "", str(body.get("name", "")))[:60].strip()
            if not name: return self._send(400, {"error": "name required"})
            key = name.lower()
            if key in CACHE: return self._send(200, {**CACHE[key], "cached": True})
            ip = self.headers.get("x-forwarded-for", "anon").split(",")[0]
            recent = [t for t in HITS.get(ip, []) if time.time() - t < WINDOW]
            if len(recent) >= LIMIT: return self._send(429, {"error": "rate limit, try later"})
            HITS[ip] = recent + [time.time()]
            import common
            common.RAW = Path("/tmp/raw")  # serverless filesystem is read-only except /tmp
            import pass1_research
            pass1_research.OUT = common.RAW/"pass1"
            app = {"id": 0, "slug": re.sub(r"[^a-z0-9]+", "_", key).strip("_"), "name": name,
                   "category": "unknown (live request)", "hint": "none given"}
            # A pool: when one free-tier model is out of daily quota the call moves to the next one.
            model = os.getenv("LIVE_MODEL") or "gemini-3.1-flash-lite,gemini-3.5-flash-lite"
            rec = asyncio.run(pass1_research.research_one(app, model=model))
            out = {k: rec.get(k) for k in ("name", "model", "backend", "researched_at", "fields", "schema_problems", "uncited_sources")}
            CACHE[key] = out
            self._send(200, out)
        except BaseException as e:  # SystemExit is raised for missing API keys; it must still produce a response
            name, msg = type(e).__name__, str(e)
            if "Set GEMINI_API_KEY" in msg or "Set COMPOSIO_API_KEY" in msg:
                return self._send(503, {"error": "not_configured", "detail": msg[:200]})
            if name in ("QuotaExhausted", "RateLimited") or "429" in msg:
                return self._send(503, {"error": "model_busy", "detail": "The free model quota is used up or busy. Try again later."})
            self._send(500, {"error": name, "detail": msg[:200]})
