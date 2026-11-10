"""
RAGFlow ustidan agent-based wrapper — FastAPI backend.

Model:
  collection -> RAGFlow dataset (hujjat konteyneri)
  agent      -> tanlangan collectionlar + system prompt (= RAGFlow chat assistant)
  /chat       -> faqat agent_id + user_id + query

Ishga tushirish:
    uvicorn main:app --host 0.0.0.0 --port 8100 --reload
Swagger UI:
    http://localhost:8100/docs
"""
import hmac
import json
import os
import shutil
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import (
    BackgroundTasks,
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import JSONResponse, PlainTextResponse

import db
import instagram as ig
import ragflow_client as rf
from config import get_settings
from ragflow_client import RAGFlowError
from schemas import (
    ChatRequest,
    ChatResponse,
    CreateAgentRequest,
    RetrieveRequest,
    RetrieveResponse,
    UpdateAgentRequest,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()
    yield
    await db.disconnect()
    await rf.close_client()
    await ig.close_client()


settings = get_settings()
app = FastAPI(title="RAGFlow Wrapper API", version="4.0.0", lifespan=lifespan)


def _empty_dataset_error() -> HTTPException:
    return HTTPException(
        status_code=409,
        detail=(
            "Agent hali tayyor emas: biriktirilgan collection(lar)da parse qilingan hujjat yo'q. "
            "Avval hujjat yuklang va parse tugashini kuting."
        ),
    )


async def _ensure_agent_chat(agent) -> str:
    """Agent uchun RAGFlow chat assistant'ni lazy yaratadi."""
    if agent["chat_id"]:
        return agent["chat_id"]

    dataset_ids = await db.agent_dataset_ids(agent["agent_id"])
    if not dataset_ids:
        raise HTTPException(
            status_code=409,
            detail="Agentga biriktirilgan collectionlarda dataset yo'q.",
        )
    try:
        resp = await rf.create_chat_assistant(
            name=f"{agent['agent_name']}__{uuid.uuid4().hex[:6]}",
            dataset_ids=dataset_ids,
            persona=agent["system_prompt"],
        )
    except RAGFlowError as e:
        if (e.payload or {}).get("code") == 102:
            raise _empty_dataset_error()
        raise HTTPException(status_code=502, detail=str(e))
    chat_id = resp["data"]["id"]
    await db.set_agent_chat(agent["agent_id"], chat_id)
    return chat_id


# ---------------------------------------------------------------------
# DOCUMENT INGEST (collection = hujjat konteyneri)
# ---------------------------------------------------------------------

@app.post("/documents")
async def upload_documents(
    collection: str = Form(..., description="Collection nomi (majburiy)"),
    files: list[UploadFile] = File(...),
):
    """Fayl(lar)ni berilgan collectionga yuklaydi va parse qiladi.

    Collection yangi bo'lsa — yangi RAGFlow dataset yaratiladi.
    """
    col = await db.get_collection(collection)
    if col is None:
        try:
            ds_resp = await rf.create_dataset(name=collection)
        except RAGFlowError as e:
            raise HTTPException(status_code=502, detail=str(e))
        col = await db.create_collection(collection, ds_resp["data"]["id"])
    dataset_id = col["dataset_id"]

    tmp_dir = tempfile.mkdtemp(prefix="ragflow_upload_")
    saved_paths = []
    try:
        for f in files:
            dest = os.path.join(tmp_dir, os.path.basename(f.filename))
            with open(dest, "wb") as out:
                shutil.copyfileobj(f.file, out)
            saved_paths.append(dest)
        try:
            upload_resp = await rf.upload_documents(dataset_id, saved_paths)
            document_ids = [d["id"] for d in upload_resp["data"]]
            parse_resp = await rf.parse_documents(dataset_id, document_ids)
        except RAGFlowError as e:
            raise HTTPException(status_code=502, detail=str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return {
        "collection": collection,
        "dataset_id": dataset_id,
        "document_ids": document_ids,
        "parse_triggered": True,
        "parse_response": parse_resp,
    }


@app.get("/collections/{collection}/documents")
async def collection_document_status(collection: str):
    """Collection ichidagi hujjatlarning parse (embedding) holati.

    Upload'dan keyin bu endpoint'ni pollab, `all_ready: true` bo'lishini kutish
    kerak — shundan keyingina agent yaratish/`/chat` chaqirish mantiqan to'g'ri
    bo'ladi (aks holda "empty dataset" 409 xatosi yoki hali to'liq bo'lmagan
    natija olish xavfi bor).

    `status` qiymatlari RAGFlow konvensiyasi: UNSTART, RUNNING, DONE, FAIL, CANCEL.
    """
    col = await db.get_collection(collection)
    if col is None:
        raise HTTPException(status_code=404, detail=f"Collection '{collection}' topilmadi")

    try:
        docs = await rf.list_all_documents(col["dataset_id"])
    except RAGFlowError as e:
        raise HTTPException(status_code=502, detail=str(e))

    out = [
        {
            "document_id": d.get("id"),
            "name": d.get("name"),
            "status": d.get("run"),
            "progress": d.get("progress"),
            "progress_msg": d.get("progress_msg"),
            "chunk_count": d.get("chunk_count", 0),
            "ready": d.get("run") == "DONE",
            "failed": d.get("run") == "FAIL",
        }
        for d in docs
    ]

    return {
        "collection": collection,
        "total": len(out),
        "all_ready": bool(out) and all(d["ready"] for d in out),
        "any_failed": any(d["failed"] for d in out),
        "documents": out,
    }


@app.get("/collections")
async def list_collections():
    """Barcha collectionlar (agent yaratishda tanlash uchun)."""
    cols = await db.list_collections()

    doc_counts: dict[str, int] = {}
    try:
        ds = await rf.list_datasets()
        for d in ds.get("data", []) or []:
            doc_counts[d["id"]] = d.get("document_count", 0)
    except RAGFlowError:
        pass

    return [
        {
            "collection": c["collection_name"],
            "dataset_id": c["dataset_id"],
            "document_count": doc_counts.get(c["dataset_id"]),
        }
        for c in cols
    ]


# ---------------------------------------------------------------------
# AGENTS
# ---------------------------------------------------------------------

async def _validate_collections(collections: list[str]) -> None:
    missing = [c for c in collections if not await db.get_collection(c)]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Quyidagi collection(lar) topilmadi: {missing}. Avval ularga hujjat yuklang.",
        )


@app.post("/agents")
async def create_agent(req: CreateAgentRequest):
    """Tanlangan collectionlar + system prompt asosida agent yaratadi.

    Natijada qaytgan agent_id keyinchalik /chat'da ishlatiladi.
    """
    if await db.get_agent_by_name(req.agent_name):
        raise HTTPException(status_code=409, detail="Bu agent nomi allaqachon mavjud")
    await _validate_collections(req.collections)

    agent_id = uuid.uuid4().hex
    await db.create_agent(agent_id, req.agent_name, req.system_prompt, req.collections)
    return {
        "agent_id": agent_id,
        "agent_name": req.agent_name,
        "collections": req.collections,
        "system_prompt": req.system_prompt,
        "ready": False,
    }


@app.get("/agents")
async def list_agents():
    agents = await db.list_agents()
    out = []
    for a in agents:
        out.append(
            {
                "agent_id": a["agent_id"],
                "agent_name": a["agent_name"],
                "collections": await db.get_agent_collections(a["agent_id"]),
                "system_prompt": a["system_prompt"],
                "ready": a["chat_id"] is not None,
            }
        )
    return out


@app.put("/agents/{agent_id}")
async def update_agent(agent_id: str, req: UpdateAgentRequest):
    """Agent nomi / collectionlari / promptini yangilaydi (RAGFlow assistant ham)."""
    agent = await db.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent topilmadi")

    if req.agent_name and req.agent_name != agent["agent_name"]:
        existing = await db.get_agent_by_name(req.agent_name)
        if existing:
            raise HTTPException(status_code=409, detail="Bu agent nomi allaqachon mavjud")
    if req.collections is not None:
        await _validate_collections(req.collections)

    await db.update_agent(agent_id, req.agent_name, req.system_prompt, req.collections)

    # RAGFlow assistant allaqachon yaratilgan bo'lsa — uni ham yangilaymiz
    if agent["chat_id"]:
        try:
            if req.collections is not None:
                await rf.update_chat_datasets(
                    agent["chat_id"], await db.agent_dataset_ids(agent_id)
                )
            if req.system_prompt is not None:
                await rf.update_chat_prompt(agent["chat_id"], req.system_prompt)
        except RAGFlowError as e:
            if (e.payload or {}).get("code") == 102:
                raise _empty_dataset_error()
            raise HTTPException(status_code=502, detail=str(e))

    updated = await db.get_agent(agent_id)
    return {
        "agent_id": agent_id,
        "agent_name": updated["agent_name"],
        "collections": await db.get_agent_collections(agent_id),
        "system_prompt": updated["system_prompt"],
        "ready": updated["chat_id"] is not None,
    }


# ---------------------------------------------------------------------
# RETRIEVE (LLM'siz) — retrieval sifati/latency'ni alohida sinash uchun
# ---------------------------------------------------------------------

@app.post("/retrieve", response_model=RetrieveResponse)
async def retrieve(req: RetrieveRequest):
    """Agent collectionlari bo'yicha faqat retrieval (embedding + rerank) qiladi.

    LLM chaqirilmaydi — natija va latency faqat qidiruv qatlamini aks ettiradi.
    """
    agent = await db.get_agent(req.agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{req.agent_id}' topilmadi")

    dataset_ids = await db.agent_dataset_ids(req.agent_id)
    if not dataset_ids:
        raise HTTPException(
            status_code=409,
            detail="Agentga biriktirilgan collectionlarda dataset yo'q.",
        )

    start = time.perf_counter()
    try:
        resp = await rf.search_datasets(dataset_ids, req.query, top_k=req.top_k)
    except RAGFlowError as e:
        raise HTTPException(status_code=502, detail=str(e))
    latency_ms = (time.perf_counter() - start) * 1000

    data = resp.get("data", {}) or {}
    chunks = [
        {
            "content": c.get("content_with_weight", ""),
            "document_name": c.get("docnm_kwd", ""),
            "document_id": c.get("doc_id", ""),
            "similarity": c.get("similarity", 0.0),
            "vector_similarity": c.get("vector_similarity", 0.0),
            "term_similarity": c.get("term_similarity", 0.0),
        }
        for c in data.get("chunks", []) or []
    ]

    return RetrieveResponse(
        agent_id=req.agent_id,
        query=req.query,
        total=data.get("total", len(chunks)),
        latency_ms=round(latency_ms, 1),
        chunks=chunks,
    )


# ---------------------------------------------------------------------
# CHAT
# ---------------------------------------------------------------------

async def _run_chat(agent_id: str, user_id: str, query: str) -> tuple[str, str, dict]:
    """Agentga savol beradi, session va tarixni saqlaydi.

    /chat va Instagram webhook uchun umumiy. Qaytaradi: (session_id, answer, raw).
    """
    agent = await db.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' topilmadi")

    chat_id = await _ensure_agent_chat(agent)

    session_id = await db.get_session(agent_id, user_id)
    try:
        if not session_id:
            sess = await rf.create_session(chat_id, session_name=f"{user_id}")
            session_id = sess["data"]["id"]
            await db.save_session(agent_id, user_id, session_id, chat_id)

        answer_resp = await rf.ask(chat_id, session_id, query, stream=False)
    except RAGFlowError as e:
        raise HTTPException(status_code=502, detail=str(e))

    data = answer_resp.get("data", {})
    answer_text = data.get("answer", "") if isinstance(data, dict) else ""
    reference = data.get("reference") if isinstance(data, dict) else None

    await db.add_message(agent_id, user_id, "user", query)
    await db.add_message(agent_id, user_id, "assistant", answer_text, reference)
    return session_id, answer_text, answer_resp


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    session_id, answer_text, answer_resp = await _run_chat(req.agent_id, req.user_id, req.query)
    return ChatResponse(
        agent_id=req.agent_id, session_id=session_id, answer=answer_text, raw=answer_resp
    )


# ---------------------------------------------------------------------
# INSTAGRAM (Meta webhook)
# ---------------------------------------------------------------------

@app.get("/instagram/webhook", tags=["instagram"])
async def verify(
    hub_mode: Optional[str] = Query(None, alias="hub.mode"),
    hub_verify_token: Optional[str] = Query(None, alias="hub.verify_token"),
    hub_challenge: Optional[str] = Query(None, alias="hub.challenge"),
):
    """Meta webhook tasdiqlash: verify_token mos kelsa hub.challenge'ni qaytaradi."""
    if (
        hub_mode == "subscribe"
        and settings.ig_verify_token
        and hub_verify_token
        and hmac.compare_digest(hub_verify_token, settings.ig_verify_token)
    ):
        return PlainTextResponse(hub_challenge or "")
    raise HTTPException(status_code=403, detail="Verify token noto'g'ri")


async def _answer_instagram(sender_id: str, text: str) -> None:
    """Fonda: xabarni agentga beradi va javobni Instagram'ga yuboradi."""
    try:
        _, answer, _ = await _run_chat(settings.rag_agent_id, f"ig_{sender_id}", text)
        answer = ig.clean_answer(answer)
        if answer:
            await ig.send_text(sender_id, answer)
    except HTTPException as e:
        ig.log.error("Instagram javob xatosi (sender=%s): %s", sender_id, e.detail)
    except Exception:
        ig.log.exception("Instagram javob xatosi (sender=%s)", sender_id)


@app.post("/instagram/webhook", tags=["instagram"])
async def receive(request: Request, background_tasks: BackgroundTasks):
    """Meta'dan kelgan Instagram xabarlarini qabul qiladi; javob fonda yuboriladi."""
    raw = await request.body()
    if not ig.verify_signature(raw, request.headers.get("x-hub-signature-256")):
        raise HTTPException(status_code=403, detail="Imzo (X-Hub-Signature-256) noto'g'ri")
    try:
        payload = json.loads(raw or b"{}")
    except ValueError:
        raise HTTPException(status_code=400, detail="JSON noto'g'ri")

    if not settings.rag_agent_id:
        ig.log.error("RAG_AGENT_ID sozlanmagan — Instagram xabarlari javobsiz qoladi")
        return {"status": "ignored"}

    queued = 0
    for m in ig.extract_text_messages(payload):
        if ig.is_duplicate(m["mid"]):
            continue
        background_tasks.add_task(_answer_instagram, m["sender_id"], m["text"])
        queued += 1
    return {"status": "ok", "queued": queued}


@app.post("/agents/{agent_id}/users/{user_id}/reset-session")
async def reset_session(agent_id: str, user_id: str):
    """Foydalanuvchi uchun agent bilan yangi (bo'sh) sessiya boshlaydi."""
    agent = await db.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent topilmadi")
    chat_id = await _ensure_agent_chat(agent)
    try:
        sess = await rf.create_session(
            chat_id, session_name=f"{user_id}:{uuid.uuid4().hex[:6]}"
        )
    except RAGFlowError as e:
        raise HTTPException(status_code=502, detail=str(e))
    session_id = sess["data"]["id"]
    await db.save_session(agent_id, user_id, session_id, chat_id)
    return {"agent_id": agent_id, "session_id": session_id}


# ---------------------------------------------------------------------
# HISTORY
# ---------------------------------------------------------------------

@app.get("/agents/{agent_id}/users/{user_id}/history")
async def get_history(agent_id: str, user_id: str):
    """Agent bilan foydalanuvchi tarixini Postgres'dan qaytaradi."""
    agent = await db.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent topilmadi")
    rows = await db.get_history(agent_id, user_id)
    out = []
    for r in rows:
        ref = r["reference"]
        if isinstance(ref, str):
            try:
                ref = json.loads(ref)
            except ValueError:
                pass
        out.append(
            {
                "role": r["role"],
                "content": r["content"],
                "reference": ref,
                "created_at": r["created_at"].isoformat(),
            }
        )
    return out


@app.exception_handler(RAGFlowError)
async def ragflow_error_handler(request, exc: RAGFlowError):
    return JSONResponse(status_code=502, content={"error": str(exc), "payload": exc.payload})


@app.get("/health")
async def health():
    return {"status": "ok"}
