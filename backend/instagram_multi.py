"""
Instagram ko'p akkauntli integratsiya (Instagram API with Instagram Login).

Ulash (main.py):
    from instagram_multi import router as instagram_router, start_token_refresher
    app.include_router(instagram_router)
    # start_token_refresher() — main.py dagi lifespan ichida chaqiriladi
    # (app lifespan bilan yaratilgan, @app.on_event("startup") u bilan ishlamaydi)

.env backend/.env dan shu modulning o'zi yuklaydi (load_dotenv).

.env:
    IG_APP_ID=1573678341110233            # Instagram app ID (Meta'da "Instagram app ID")
    IG_APP_SECRET=...                     # Instagram app secret (Meta'da "Show" bosib oling)
    IG_VERIFY_TOKEN=...                   # hozirgi verify token (o'zgarmaydi)
    IG_REDIRECT_URI=https://api.doppiai.uz/instagram/callback
    IG_DEFAULT_AGENT_ID=e93fdb14435744eabb00b21fb5ad13dc
    RAG_CHAT_URL=http://127.0.0.1:8110/chat   # shu servisning o'z /chat endpointi
    ADMIN_KEY=uzun-tasodifiy-satr             # /instagram/accounts sahifasi uchun
    IG_DB_PATH=instagram_accounts.db
    GRAPH_VERSION=v23.0

Kerakli paket: pip install httpx
"""

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import sqlite3
import time
from contextlib import closing
from html import escape
from urllib.parse import urlencode

from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse

# config.py (pydantic-settings) .env ni os.environ ga yuklamaydi, systemd unit'da ham
# EnvironmentFile yo'q — shuning uchun shu yerda yuklaymiz. Aks holda IG_APP_SECRET bo'sh
# qolib, webhook imzo tekshiruvi jimgina o'chib qoladi. override=False: haqiqiy env ustun.
load_dotenv(Path(__file__).with_name(".env"), override=False)

log = logging.getLogger("instagram")

IG_APP_ID = os.getenv("IG_APP_ID", "1573678341110233")
IG_APP_SECRET = os.getenv("IG_APP_SECRET", "")
IG_VERIFY_TOKEN = os.getenv("IG_VERIFY_TOKEN", "")
IG_REDIRECT_URI = os.getenv("IG_REDIRECT_URI", "https://api.doppiai.uz/instagram/callback")
IG_DEFAULT_AGENT_ID = os.getenv("IG_DEFAULT_AGENT_ID", "")
RAG_CHAT_URL = os.getenv("RAG_CHAT_URL", "http://127.0.0.1:8110/chat")
ADMIN_KEY = os.getenv("ADMIN_KEY", "")
DB_PATH = os.getenv("IG_DB_PATH", "instagram_accounts.db")
GRAPH_VERSION = os.getenv("GRAPH_VERSION", "v23.0")
GRAPH = f"https://graph.instagram.com/{GRAPH_VERSION}"
SCOPES = "instagram_business_basic,instagram_business_manage_messages"
IG_MAX_TEXT = 1000  # Instagram bitta xabar uchun limit

NO_ANSWER_EN = "No relevant content was found in the knowledge base"
FALLBACK_TEXT = os.getenv(
    "IG_FALLBACK_TEXT",
    "Assalomu alaykum! Savolingizni yozing, bilim bazamdan javob topishga harakat qilaman.",
)

router = APIRouter(prefix="/instagram", tags=["instagram"])
_pending_states: dict[str, tuple[str, float]] = {}  # state -> (agent_id, created_at)


# ---------------------------------------------------------------- DB
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with closing(db()) as c, c:
        c.execute(
            """CREATE TABLE IF NOT EXISTS ig_accounts (
                ig_user_id      TEXT PRIMARY KEY,   -- webhook'dagi entry.id
                username        TEXT,
                name            TEXT,
                picture_url     TEXT,
                access_token    TEXT NOT NULL,
                token_expires_at INTEGER,
                agent_id        TEXT NOT NULL,
                active          INTEGER DEFAULT 1,
                connected_at    INTEGER
            )"""
        )


init_db()


def get_account(ig_user_id: str):
    with closing(db()) as c:
        return c.execute(
            "SELECT * FROM ig_accounts WHERE ig_user_id=? AND active=1", (ig_user_id,)
        ).fetchone()


def upsert_account(**a):
    with closing(db()) as c, c:
        c.execute(
            """INSERT INTO ig_accounts
               (ig_user_id, username, name, picture_url, access_token, token_expires_at,
                agent_id, active, connected_at)
               VALUES (:ig_user_id,:username,:name,:picture_url,:access_token,
                       :token_expires_at,:agent_id,1,:connected_at)
               ON CONFLICT(ig_user_id) DO UPDATE SET
                 username=excluded.username, name=excluded.name,
                 picture_url=excluded.picture_url, access_token=excluded.access_token,
                 token_expires_at=excluded.token_expires_at, agent_id=excluded.agent_id,
                 active=1""",
            a,
        )


def deactivate_account(ig_user_id: str, wipe: bool = False):
    with closing(db()) as c, c:
        if wipe:
            c.execute("DELETE FROM ig_accounts WHERE ig_user_id=?", (ig_user_id,))
        else:
            c.execute("UPDATE ig_accounts SET active=0 WHERE ig_user_id=?", (ig_user_id,))


# ---------------------------------------------------------------- helpers
def _check_admin(key: str | None):
    if not ADMIN_KEY or not key or not hmac.compare_digest(key, ADMIN_KEY):
        raise HTTPException(403, "admin key noto'g'ri")


def _verify_signature(raw: bytes, header: str | None) -> bool:
    if not IG_APP_SECRET:
        return True  # secret qo'yilmagan bo'lsa tekshirmaymiz (faqat test uchun)
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(IG_APP_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header[7:])


def _parse_signed_request(signed_request: str) -> dict:
    sig_b64, payload_b64 = signed_request.split(".", 1)
    pad = lambda s: s + "=" * (-len(s) % 4)
    sig = base64.urlsafe_b64decode(pad(sig_b64))
    expected = hmac.new(IG_APP_SECRET.encode(), payload_b64.encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expected):
        raise HTTPException(400, "signed_request imzosi noto'g'ri")
    return json.loads(base64.urlsafe_b64decode(pad(payload_b64)))


def clean_answer(text: str) -> str:
    text = re.sub(r"\s*\[ID:\s*\d+\]", "", text or "").strip()
    if not text or NO_ANSWER_EN in text:
        return FALLBACK_TEXT
    return text


def split_text(text: str, limit: int = IG_MAX_TEXT) -> list[str]:
    parts = []
    while len(text) > limit:
        cut = text.rfind(" ", 0, limit)
        cut = cut if cut > limit // 2 else limit
        parts.append(text[:cut].strip())
        text = text[cut:].strip()
    if text:
        parts.append(text)
    return parts


async def ask_rag(agent_id: str, user_id: str, query: str) -> str:
    async with httpx.AsyncClient(timeout=120) as cl:
        r = await cl.post(RAG_CHAT_URL, json={"agent_id": agent_id, "user_id": user_id, "query": query})
        r.raise_for_status()
        return r.json().get("answer", "")


async def send_ig_message(token: str, recipient_id: str, text: str):
    async with httpx.AsyncClient(timeout=30) as cl:
        for part in split_text(text):
            r = await cl.post(
                f"{GRAPH}/me/messages",
                headers={"Authorization": f"Bearer {token}"},
                json={"recipient": {"id": recipient_id}, "message": {"text": part}},
            )
            if r.status_code >= 400:
                log.error("IG send xato %s: %s", r.status_code, r.text)
                r.raise_for_status()


# ---------------------------------------------------------------- OAuth (Business Login)
@router.get("/connect")
async def connect(agent_id: str | None = None):
    """Mijoz shu havolani bosadi -> Instagram login -> /instagram/callback"""
    state = secrets.token_urlsafe(24)
    _pending_states[state] = (agent_id or IG_DEFAULT_AGENT_ID, time.time())
    params = {
        "client_id": IG_APP_ID,
        "redirect_uri": IG_REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPES,
        "state": state,
        "force_reauth": "true",
    }
    return RedirectResponse("https://www.instagram.com/oauth/authorize?" + urlencode(params))


@router.get("/callback", response_class=HTMLResponse)
async def oauth_callback(code: str | None = None, state: str | None = None,
                         error: str | None = None, error_description: str | None = None):
    if error:
        return HTMLResponse(f"<h3>Ulash bekor qilindi</h3><p>{escape(error_description or error)}</p>", 400)
    pending = _pending_states.pop(state or "", None)
    if not code or not pending or time.time() - pending[1] > 900:
        return HTMLResponse("<h3>Havola eskirgan, qaytadan urinib ko'ring.</h3>", 400)
    agent_id = pending[0]
    code = code.split("#")[0]

    async with httpx.AsyncClient(timeout=30) as cl:
        # 1) code -> qisqa token
        r = await cl.post("https://api.instagram.com/oauth/access_token", data={
            "client_id": IG_APP_ID, "client_secret": IG_APP_SECRET,
            "grant_type": "authorization_code", "redirect_uri": IG_REDIRECT_URI, "code": code,
        })
        if r.status_code >= 400:
            log.error("token exchange: %s", r.text)
            return HTMLResponse("<h3>Token olishda xato</h3>", 400)
        short_token = r.json()["access_token"]

        # 2) qisqa -> uzoq muddatli (60 kun)
        r = await cl.get("https://graph.instagram.com/access_token", params={
            "grant_type": "ig_exchange_token", "client_secret": IG_APP_SECRET,
            "access_token": short_token,
        })
        r.raise_for_status()
        long = r.json()
        token = long["access_token"]
        expires_at = int(time.time()) + int(long.get("expires_in", 5184000))

        # 3) profil (instagram_business_basic) - user_id webhook'dagi entry.id bilan bir xil
        r = await cl.get(f"{GRAPH}/me", params={
            "fields": "user_id,username,name,profile_picture_url", "access_token": token,
        })
        r.raise_for_status()
        me = r.json()

        # 4) shu akkauntni webhook'ga obuna qilish
        r = await cl.post(f"{GRAPH}/me/subscribed_apps", params={
            "subscribed_fields": "messages", "access_token": token,
        })
        if r.status_code >= 400:
            log.error("subscribe xato: %s", r.text)

    upsert_account(
        ig_user_id=str(me["user_id"]), username=me.get("username"), name=me.get("name"),
        picture_url=me.get("profile_picture_url"), access_token=token,
        token_expires_at=expires_at, agent_id=agent_id, connected_at=int(time.time()),
    )
    pic = escape(me.get("profile_picture_url") or "")
    uname = escape(me.get("username") or "")
    return HTMLResponse(f"""<!doctype html><html><head><meta charset="utf-8">
<title>Connected</title><style>body{{font-family:system-ui;max-width:480px;margin:60px auto;text-align:center}}
img{{width:96px;height:96px;border-radius:50%}}</style></head><body>
<h2>Instagram account connected</h2>
{f'<img src="{pic}" alt="">' if pic else ''}
<p><b>@{uname}</b> is now connected. Incoming Direct messages will be answered automatically
from your knowledge base.</p></body></html>""")


# ---------------------------------------------------------------- Webhook
@router.get("/webhook")
async def verify(mode: str = Query(None, alias="hub.mode"),
                 token: str = Query(None, alias="hub.verify_token"),
                 challenge: str = Query(None, alias="hub.challenge")):
    if mode == "subscribe" and IG_VERIFY_TOKEN and token and hmac.compare_digest(token, IG_VERIFY_TOKEN):
        return PlainTextResponse(challenge or "")
    raise HTTPException(403, "Verify token noto'g'ri")


@router.post("/webhook")
async def receive(request: Request, bg: BackgroundTasks):
    raw = await request.body()
    if not _verify_signature(raw, request.headers.get("X-Hub-Signature-256")):
        raise HTTPException(403, "imzo noto'g'ri")
    body = json.loads(raw or b"{}")
    for entry in body.get("entry", []):
        account_id = str(entry.get("id"))
        for ev in entry.get("messaging", []):
            msg = ev.get("message") or {}
            if msg.get("is_echo") or msg.get("is_deleted"):
                continue  # o'zimiz yuborgan xabarga javob bermaymiz
            text = msg.get("text")
            sender = str(ev.get("sender", {}).get("id", ""))
            if not text or not sender or sender == account_id:
                continue
            bg.add_task(handle_message, account_id, sender, text)
    return {"status": "ok"}  # Meta'ga darhol 200 qaytaramiz


async def handle_message(account_id: str, sender_id: str, text: str):
    acc = get_account(account_id)
    if not acc:
        log.warning("Ulanmagan akkauntga xabar keldi: %s", account_id)
        return
    try:
        answer = await ask_rag(acc["agent_id"], f"ig:{account_id}:{sender_id}", text)
    except Exception:
        log.exception("RAG xato")
        answer = ""
    try:
        await send_ig_message(acc["access_token"], sender_id, clean_answer(answer))
    except Exception:
        log.exception("Instagramga yuborishda xato (akkaunt %s)", account_id)


# ---------------------------------------------------------------- Deauthorize / Data deletion
@router.post("/deauthorize")
async def deauthorize(signed_request: str = Form(...)):
    data = _parse_signed_request(signed_request)
    if uid := data.get("user_id"):
        deactivate_account(str(uid))
    return {"status": "ok"}


@router.post("/data-deletion")
async def data_deletion(signed_request: str = Form(...)):
    data = _parse_signed_request(signed_request)
    uid = str(data.get("user_id", ""))
    if uid:
        deactivate_account(uid, wipe=True)
    code = secrets.token_hex(8)
    return JSONResponse({
        "url": f"https://api.doppiai.uz/instagram/data-deletion/status?code={code}",
        "confirmation_code": code,
    })


@router.get("/data-deletion/status", response_class=HTMLResponse)
async def data_deletion_status(code: str = ""):
    return HTMLResponse(f"<p>Deletion request <b>{escape(code)}</b>: your data has been deleted.</p>")


# ---------------------------------------------------------------- Admin panel (video uchun 3-qadam)
@router.get("/accounts", response_class=HTMLResponse)
async def accounts_page(key: str | None = None):
    _check_admin(key)
    with closing(db()) as c:
        rows = c.execute("SELECT * FROM ig_accounts ORDER BY connected_at DESC").fetchall()
    def row_html(r):
        img = f'<img src="{escape(r["picture_url"])}" alt="">' if r["picture_url"] else ""
        status = "Active" if r["active"] else "Disconnected"
        expires = time.strftime("%Y-%m-%d", time.localtime(r["token_expires_at"] or 0))
        return (f"<tr><td>{img}</td><td>@{escape(r['username'] or '')}</td>"
                f"<td>{escape(r['ig_user_id'])}</td><td>{escape(r['agent_id'])}</td>"
                f"<td>{status}</td><td>{expires}</td></tr>")

    trs = "".join(row_html(r) for r in rows)
    return HTMLResponse(f"""<!doctype html><html><head><meta charset="utf-8"><title>Instagram accounts</title>
<style>body{{font-family:system-ui;max-width:900px;margin:40px auto}}table{{width:100%;border-collapse:collapse}}
td,th{{padding:8px;border-bottom:1px solid #ddd;text-align:left}}img{{width:40px;height:40px;border-radius:50%}}
a.btn{{display:inline-block;background:#d62976;color:#fff;padding:10px 18px;border-radius:8px;text-decoration:none}}</style>
</head><body><h2>Connected Instagram accounts</h2>
<p><a class="btn" href="/instagram/connect">Connect Instagram account</a></p>
<table><tr><th></th><th>Username</th><th>IG user ID</th><th>Agent</th><th>Status</th><th>Token expires</th></tr>
{trs}</table></body></html>""")


@router.post("/accounts/{ig_user_id}/agent")
async def set_agent(ig_user_id: str, agent_id: str = Form(...), key: str | None = None):
    _check_admin(key)
    with closing(db()) as c, c:
        c.execute("UPDATE ig_accounts SET agent_id=? WHERE ig_user_id=?", (agent_id, ig_user_id))
    return {"status": "ok"}


# ---------------------------------------------------------------- Token yangilash
async def _refresh_tokens_once():
    soon = int(time.time()) + 10 * 86400  # 10 kundan kam qolganlarni yangilaymiz
    with closing(db()) as c:
        rows = c.execute(
            "SELECT ig_user_id, access_token FROM ig_accounts WHERE active=1 AND token_expires_at<?",
            (soon,),
        ).fetchall()
    async with httpx.AsyncClient(timeout=30) as cl:
        for r in rows:
            resp = await cl.get("https://graph.instagram.com/refresh_access_token", params={
                "grant_type": "ig_refresh_token", "access_token": r["access_token"],
            })
            if resp.status_code >= 400:
                log.error("token refresh xato %s: %s", r["ig_user_id"], resp.text)
                continue
            d = resp.json()
            with closing(db()) as c, c:
                c.execute(
                    "UPDATE ig_accounts SET access_token=?, token_expires_at=? WHERE ig_user_id=?",
                    (d["access_token"], int(time.time()) + int(d.get("expires_in", 5184000)), r["ig_user_id"]),
                )


def start_token_refresher():
    async def loop():
        while True:
            try:
                await _refresh_tokens_once()
            except Exception:
                log.exception("token refresher")
            await asyncio.sleep(24 * 3600)
    asyncio.get_event_loop().create_task(loop())
