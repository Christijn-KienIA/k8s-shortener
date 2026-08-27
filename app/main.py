import asyncio
import os
import secrets
import string
from contextlib import asynccontextmanager

from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from psycopg_pool import AsyncConnectionPool

DB_URL = (
    f"postgresql://{os.environ['DB_USER']}:{os.environ['DB_PASSWORD']}"
    f"@{os.environ.get('DB_HOST', 'postgres')}:{os.environ.get('DB_PORT', '5432')}"
    f"/{os.environ.get('DB_NAME', 'shortener')}"
)

POD = os.environ.get("POD_NAME", "lokaal")
VERSION = os.environ.get("APP_VERSION", "dev")
KLEUR = os.environ.get("KLEUR", "#2563eb")
ALFABET = string.ascii_lowercase + string.digits

SCHEMA = """
CREATE TABLE IF NOT EXISTS links (
    code       TEXT PRIMARY KEY,
    url        TEXT NOT NULL,
    hits       INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

pool: AsyncConnectionPool | None = None
db_klaar = False


async def _init_db() -> None:
    """Blijf proberen tot de database bestaat. Tot die tijd is /healthz rood."""
    global db_klaar
    while True:
        try:
            async with pool.connection() as conn:
                await conn.execute(SCHEMA)
            db_klaar = True
            print("[init] database klaar", flush=True)
            return
        except Exception as exc:
            print(f"[init] wacht op database: {exc}", flush=True)
            await asyncio.sleep(2)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global pool
    pool = AsyncConnectionPool(DB_URL, min_size=1, max_size=5, open=False)
    await pool.open(wait=False)
    taak = asyncio.create_task(_init_db())
    yield
    taak.cancel()
    await pool.close()


app = FastAPI(lifespan=lifespan)


@app.get("/livez")
async def livez():
    """Draait het proces nog? Faalt dit, dan herstart Kubernetes de pod."""
    return {"status": "alive", "pod": POD}


@app.get("/healthz")
async def healthz():
    """Kan deze pod verkeer aan? Faalt dit, dan haalt Kubernetes hem uit de Service."""
    if not db_klaar:
        return JSONResponse({"status": "database nog niet klaar"}, status_code=503)
    try:
        async with pool.connection() as conn:
            await conn.execute("SELECT 1")
    except Exception as exc:
        return JSONResponse({"status": f"database weg: {exc}"}, status_code=503)
    return {"status": "ok", "pod": POD, "versie": VERSION}


@app.post("/api/shorten")
async def shorten(url: str = Form(...)):
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    code = "".join(secrets.choice(ALFABET) for _ in range(6))
    async with pool.connection() as conn:
        await conn.execute("INSERT INTO links (code, url) VALUES (%s, %s)", (code, url))
    return RedirectResponse("/", status_code=303)


@app.get("/", response_class=HTMLResponse)
async def index():
    rijen = []
    if db_klaar:
        async with pool.connection() as conn:
            cur = await conn.execute(
                "SELECT code, url, hits FROM links ORDER BY created_at DESC LIMIT 10"
            )
            rijen = await cur.fetchall()

    lijst = "".join(
        f'<tr><td><a href="/{c}">/{c}</a></td>'
        f'<td class="url">{u}</td><td>{h}&times;</td></tr>'
        for c, u, h in rijen
    ) or '<tr><td colspan="3" class="leeg">Nog geen links</td></tr>'

    return f"""<!doctype html><html lang="nl"><head><meta charset="utf-8">
<title>Shortener</title><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
 :root {{ color-scheme: light dark; }}
 body {{ font-family: system-ui, sans-serif; max-width: 44rem; margin: 3rem auto;
        padding: 0 1rem; line-height: 1.5; }}
 h1 {{ color: {KLEUR}; margin-bottom: .2rem; }}
 form {{ display: flex; gap: .5rem; margin: 1.5rem 0; }}
 input {{ flex: 1; padding: .6rem; font-size: 1rem; border: 1px solid #8888;
          border-radius: 6px; background: transparent; color: inherit; }}
 button {{ padding: .6rem 1.2rem; font-size: 1rem; border: 0; border-radius: 6px;
           background: {KLEUR}; color: #fff; cursor: pointer; }}
 table {{ width: 100%; border-collapse: collapse; }}
 td {{ padding: .45rem .3rem; border-bottom: 1px solid #8883; }}
 .url {{ color: #8a8a8a; overflow-wrap: anywhere; font-size: .9rem; }}
 .leeg {{ color: #8a8a8a; text-align: center; padding: 1.5rem; }}
 footer {{ margin-top: 2.5rem; font-size: .85rem; color: #8a8a8a;
           border-top: 1px solid #8883; padding-top: .8rem;
           display: flex; justify-content: space-between; gap: 1rem; flex-wrap: wrap; }}
 code {{ background: #8882; padding: .1rem .35rem; border-radius: 4px; }}
</style></head><body>
<h1>URL Shortener</h1>
<p style="color:#8a8a8a;margin-top:0">Kubernetes-workshop</p>
<form method="post" action="/api/shorten">
  <input name="url" placeholder="https://voorbeeld.nl/hele-lange-url" required autofocus>
  <button type="submit">Inkorten</button>
</form>
<table>{lijst}</table>
<footer><span>pod: <code>{POD}</code></span><span>versie: <code>{VERSION}</code></span></footer>
</body></html>"""


@app.get("/{code}")
async def volg(code: str):
    async with pool.connection() as conn:
        cur = await conn.execute(
            "UPDATE links SET hits = hits + 1 WHERE code = %s RETURNING url", (code,)
        )
        rij = await cur.fetchone()
    if not rij:
        return JSONResponse({"fout": "onbekende code"}, status_code=404)
    return RedirectResponse(rij[0], status_code=307)
