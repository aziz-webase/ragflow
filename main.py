"""
RAGFlow ustidan collection-based wrapper — FastAPI backend.

Model:
  tenant -> ko'p collection (har biri RAGFlow dataset)
  "all"  -> tenantning barcha collectionlari ustidan combined assistant

Ishga tushirish:
    uvicorn main:app --host 0.0.0.0 --port 8100 --reload
Swagger UI:
    http://localhost:8100/docs
"""
import json
import os
import shutil
import tempfile
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Form, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse

import db
import ragflow_client as rf
from db import ALL_SCOPE
from ragflow_client import RAGFlowError
from schemas import (
    AskRequest,
    AskResponse,
    CreateTenantRequest,
    CreateTenantResponse,
    SetPromptRequest,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()
    yield
    await db.disconnect()
    await rf.close_client()


app = FastAPI(title="RAGFlow Wrapper API", version="2.0.0", lifespan=lifespan)


def _reject_reserved(collection: str) -> None:
    if collection == ALL_SCOPE:
        raise HTTPException(
            status_code=400,
            detail=f"'{ALL_SCOPE}' zahiralangan nom — unga hujjat yuklab bo'lmaydi.",
        )


async def _require_tenant(tenant_name: str) -> None:
    if not await db.tenant_exists(tenant_name):
        raise HTTPException(
            status_code=404,
            detail=f"Tenant '{tenant_name}' topilmadi. Avval hujjat yuklang yoki /tenants orqali yarating.",
        )


def _empty_dataset_error() -> HTTPException:
    return HTTPException(
        status_code=409,
        detail=(
            "Chat hali tayyor emas: tegishli collection(lar)da parse qilingan hujjat yo'q. "
            "Avval hujjat yuklang va parse tugashini kuting."
        ),
    )


async def _ensure_collection_chat(tenant_name: str, col) -> str:
    """Berilgan collection uchun RAGFlow chat assistant'ni lazy yaratadi."""
    if col["chat_id"]:
        return col["chat_id"]
    try:
        resp = await rf.create_chat_assistant(
            name=f"{tenant_name}__{col['collection_name']}__{uuid.uuid4().hex[:6]}",
            dataset_ids=[col["dataset_id"]],
            persona=col["system_prompt"],
        )
    except RAGFlowError as e:
        if (e.payload or {}).get("code") == 102:
            raise _empty_dataset_error()
        raise HTTPException(status_code=502, detail=str(e))
    chat_id = resp["data"]["id"]
    await db.set_collection_chat(tenant_name, col["collection_name"], chat_id)
    return chat_id


async def _ensure_combined_chat(tenant_name: str) -> str:
    """Tenantning barcha collectionlari ustidan combined assistant'ni lazy yaratadi."""
    ta = await db.get_tenant_assistant(tenant_name)
    if ta and ta["chat_id"]:
        return ta["chat_id"]

    dataset_ids = await db.all_dataset_ids(tenant_name)
    if not dataset_ids:
        raise HTTPException(
            status_code=409,
            detail="Tenantda hech qanday collection yo'q. Avval hujjat yuklang.",
        )
    persona = ta["system_prompt"] if ta else None
    try:
        resp = await rf.create_chat_assistant(
            name=f"{tenant_name}__all__{uuid.uuid4().hex[:6]}",
            dataset_ids=dataset_ids,
            persona=persona,
        )
    except RAGFlowError as e:
        if (e.payload or {}).get("code") == 102:
            raise _empty_dataset_error()
        raise HTTPException(status_code=502, detail=str(e))
    chat_id = resp["data"]["id"]
    await db.set_tenant_assistant_chat(tenant_name, chat_id)
    return chat_id


# ---------------------------------------------------------------------
# TENANT
# ---------------------------------------------------------------------

@app.post("/tenants", response_model=CreateTenantResponse)
async def create_tenant(req: CreateTenantRequest):
    """Tenantni ro'yxatga oladi (hujjat yuklashda ham avtomatik yaratiladi)."""
    await db.ensure_tenant(req.tenant_name)
    return CreateTenantResponse(tenant_name=req.tenant_name)


# ---------------------------------------------------------------------
# DOCUMENT INGEST (collection bo'yicha)
# ---------------------------------------------------------------------

@app.post("/tenants/{tenant_name}/documents")
async def upload_documents(
    tenant_name: str,
    collection: str = Form(..., description="Collection nomi (majburiy, 'all' bo'lmasin)"),
    files: list[UploadFile] = File(...),
):
    """Fayl(lar)ni berilgan collectionga yuklaydi va parse qiladi.

    Collection yangi bo'lsa — yangi RAGFlow dataset yaratiladi.
    """
    _reject_reserved(collection)
    await db.ensure_tenant(tenant_name)

    col = await db.get_collection(tenant_name, collection)
    new_collection = col is None
    if new_collection:
        try:
            ds_resp = await rf.create_dataset(name=f"{tenant_name}__{collection}")
        except RAGFlowError as e:
            raise HTTPException(status_code=502, detail=str(e))
        dataset_id = ds_resp["data"]["id"]
        col = await db.create_collection(tenant_name, collection, dataset_id)
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

    # Yangi collection qo'shildi — agar combined "all" assistant mavjud bo'lsa,
    # uning dataset_ids'ini yangilab qo'yamiz.
    if new_collection:
        ta = await db.get_tenant_assistant(tenant_name)
        if ta and ta["chat_id"]:
            try:
                await rf.update_chat_datasets(
                    ta["chat_id"], await db.all_dataset_ids(tenant_name)
                )
            except RAGFlowError:
                pass  # keyingi /ask paytida ham tuzatilishi mumkin

    return {
        "tenant_name": tenant_name,
        "collection": collection,
        "dataset_id": dataset_id,
        "document_ids": document_ids,
        "parse_triggered": True,
        "parse_response": parse_resp,
    }


@app.get("/tenants/{tenant_name}/collections")
async def list_collections(tenant_name: str):
    """Tenantning barcha collectionlari + 'all' pseudo-yozuvi."""
    await _require_tenant(tenant_name)
    cols = await db.list_collections(tenant_name)

    # hujjat sonini RAGFlow datasets ro'yxatidan olamiz
    doc_counts: dict[str, int] = {}
    try:
        ds = await rf.list_datasets()
        for d in ds.get("data", []) or []:
            doc_counts[d["id"]] = d.get("document_count", 0)
    except RAGFlowError:
        pass

    result = [
        {
            "collection": c["collection_name"],
            "dataset_id": c["dataset_id"],
            "document_count": doc_counts.get(c["dataset_id"]),
            "has_system_prompt": c["system_prompt"] is not None,
            "chat_ready": c["chat_id"] is not None,
        }
        for c in cols
    ]

    ta = await db.get_tenant_assistant(tenant_name)
    tenant_total = (
        sum(doc_counts.get(c["dataset_id"], 0) for c in cols) if doc_counts else None
    )
    result.append(
        {
            "collection": ALL_SCOPE,
            "dataset_id": None,
            "document_count": tenant_total,
            "has_system_prompt": bool(ta and ta["system_prompt"]),
            "chat_ready": bool(ta and ta["chat_id"]),
        }
    )
    return result


# ---------------------------------------------------------------------
# COLLECTION SYSTEM PROMPT
# ---------------------------------------------------------------------

@app.post("/tenants/{tenant_name}/collections/prompt")
async def set_prompt(tenant_name: str, req: SetPromptRequest):
    """Bir yoki bir nechta collection (jumladan 'all') uchun system prompt o'rnatadi."""
    await _require_tenant(tenant_name)
    updated = []
    for target in req.targets():
        if target == ALL_SCOPE:
            await db.set_tenant_assistant_prompt(tenant_name, req.system_prompt)
            ta = await db.get_tenant_assistant(tenant_name)
            if ta and ta["chat_id"]:
                try:
                    await rf.update_chat_prompt(ta["chat_id"], req.system_prompt)
                except RAGFlowError as e:
                    raise HTTPException(status_code=502, detail=str(e))
        else:
            col = await db.get_collection(tenant_name, target)
            if not col:
                raise HTTPException(
                    status_code=404,
                    detail=f"Collection '{target}' topilmadi. Avval unga hujjat yuklang.",
                )
            await db.set_collection_prompt(tenant_name, target, req.system_prompt)
            if col["chat_id"]:
                try:
                    await rf.update_chat_prompt(col["chat_id"], req.system_prompt)
                except RAGFlowError as e:
                    raise HTTPException(status_code=502, detail=str(e))
        updated.append(target)
    return {"tenant_name": tenant_name, "updated": updated}


# ---------------------------------------------------------------------
# ASK
# ---------------------------------------------------------------------

@app.post("/ask", response_model=AskResponse)
async def ask(req: AskRequest):
    await _require_tenant(req.tenant_name)
    scope = req.collection

    if scope == ALL_SCOPE:
        chat_id = await _ensure_combined_chat(req.tenant_name)
    else:
        col = await db.get_collection(req.tenant_name, scope)
        if not col:
            raise HTTPException(
                status_code=404,
                detail=f"Collection '{scope}' topilmadi. Avval unga hujjat yuklang.",
            )
        chat_id = await _ensure_collection_chat(req.tenant_name, col)

    session_id = await db.get_session(req.tenant_name, req.user_id, scope)
    try:
        if not session_id:
            sess = await rf.create_session(chat_id, session_name=f"{req.user_id}:{scope}")
            session_id = sess["data"]["id"]
            await db.save_session(req.tenant_name, req.user_id, scope, session_id, chat_id)

        answer_resp = await rf.ask(chat_id, session_id, req.question, stream=False)
    except RAGFlowError as e:
        raise HTTPException(status_code=502, detail=str(e))

    data = answer_resp.get("data", {})
    answer_text = data.get("answer", "") if isinstance(data, dict) else ""
    reference = data.get("reference") if isinstance(data, dict) else None

    # tarixni Postgresga nusxalaymiz
    await db.add_message(req.tenant_name, req.user_id, scope, "user", req.question)
    await db.add_message(
        req.tenant_name, req.user_id, scope, "assistant", answer_text, reference
    )

    return AskResponse(
        session_id=session_id, scope=scope, answer=answer_text, raw=answer_resp
    )


@app.post("/tenants/{tenant_name}/users/{user_id}/reset-session")
async def reset_session(tenant_name: str, user_id: str, collection: str = ALL_SCOPE):
    """Foydalanuvchi uchun berilgan scope'da yangi (bo'sh) sessiya boshlaydi."""
    await _require_tenant(tenant_name)
    scope = collection
    if scope == ALL_SCOPE:
        chat_id = await _ensure_combined_chat(tenant_name)
    else:
        col = await db.get_collection(tenant_name, scope)
        if not col:
            raise HTTPException(status_code=404, detail=f"Collection '{scope}' topilmadi.")
        chat_id = await _ensure_collection_chat(tenant_name, col)
    try:
        sess = await rf.create_session(
            chat_id, session_name=f"{user_id}:{scope}:{uuid.uuid4().hex[:6]}"
        )
    except RAGFlowError as e:
        raise HTTPException(status_code=502, detail=str(e))
    session_id = sess["data"]["id"]
    await db.save_session(tenant_name, user_id, scope, session_id, chat_id)
    return {"session_id": session_id, "scope": scope}


# ---------------------------------------------------------------------
# HISTORY
# ---------------------------------------------------------------------

@app.get("/tenants/{tenant_name}/users/{user_id}/history")
async def get_history(tenant_name: str, user_id: str, collection: str | None = None):
    """Foydalanuvchi tarixini Postgres'dan qaytaradi (ixtiyoriy collection filtri)."""
    await _require_tenant(tenant_name)
    rows = await db.get_history(tenant_name, user_id, collection)
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
                "scope": r["scope"],
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
