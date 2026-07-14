"""
RAGFlow ustidan yupqa wrapper — FastAPI backend.

Ishga tushirish:
    uvicorn main:app --host 0.0.0.0 --port 8100 --reload

Swagger UI:
    http://localhost:8100/docs
"""
import os
import shutil
import tempfile
import uuid

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse

import db
import ragflow_client as rf
from ragflow_client import RAGFlowError
from schemas import (
    AskRequest,
    AskResponse,
    CreateTenantRequest,
    CreateTenantResponse,
)

app = FastAPI(title="RAGFlow Wrapper API", version="1.0.0")


@app.on_event("startup")
def on_startup() -> None:
    db.init_db()


def _tenant_or_404(tenant_name: str):
    tenant = db.get_tenant(tenant_name)
    if not tenant:
        raise HTTPException(
            status_code=404,
            detail=f"Tenant '{tenant_name}' topilmadi. Avval /tenants orqali yarating.",
        )
    return tenant


async def _ensure_chat(tenant) -> str:
    """
    Chat assistant'ni lazy yaratadi.

    RAGFlow bo'sh (parse qilinmagan hujjatsiz) datasetga chat assistant
    ulashga ruxsat bermaydi (code 102). Shuning uchun chat assistant
    tenant yaratilganda emas, balki hujjat(lar) parse bo'lgandan keyin —
    birinchi savol paytida yaratiladi.
    """
    if tenant["chat_id"]:
        return tenant["chat_id"]

    tenant_name = tenant["tenant_name"]
    try:
        chat_resp = await rf.create_chat_assistant(
            name=f"{tenant_name}_assistant",
            dataset_ids=[tenant["dataset_id"]],
        )
    except RAGFlowError as e:
        payload = e.payload or {}
        if payload.get("code") == 102:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Chat assistant hali yaratib bo'lmaydi: datasetda parse qilingan "
                    "hujjat yo'q. Avval /tenants/{tenant}/documents orqali hujjat "
                    "yuklang va parse tugashini kuting, keyin savol bering."
                ),
            )
        raise HTTPException(status_code=502, detail=str(e))

    chat_id = chat_resp["data"]["id"]
    db.set_tenant_chat(tenant_name, chat_id)
    return chat_id


# ---------------------------------------------------------------------
# TENANT (dataset + chat assistant birgalikda yaratiladi)
# ---------------------------------------------------------------------

@app.post("/tenants", response_model=CreateTenantResponse)
async def create_tenant(req: CreateTenantRequest):
    """
    Yangi tenant uchun alohida dataset (knowledge base) yaratadi.

    Chat assistant esa keyinroq — birinchi hujjat parse bo'lgandan so'ng,
    birinchi savol paytida (lazy) yaratiladi, chunki RAGFlow bo'sh datasetga
    chat assistant ulashga ruxsat bermaydi.
    """
    existing = db.get_tenant(req.tenant_name)
    if existing:
        raise HTTPException(status_code=409, detail="Bu tenant nomi allaqachon mavjud")

    try:
        dataset_resp = await rf.create_dataset(
            name=req.tenant_name, description=req.description or ""
        )
        dataset_id = dataset_resp["data"]["id"]
    except RAGFlowError as e:
        raise HTTPException(status_code=502, detail=str(e))

    db.save_tenant(req.tenant_name, dataset_id, "")
    return CreateTenantResponse(
        tenant_name=req.tenant_name, dataset_id=dataset_id, chat_id=None
    )


@app.get("/tenants/{tenant_name}")
async def get_tenant(tenant_name: str):
    tenant = _tenant_or_404(tenant_name)
    return dict(tenant)


# ---------------------------------------------------------------------
# DOCUMENT INGEST
# ---------------------------------------------------------------------

@app.post("/tenants/{tenant_name}/documents")
async def upload_documents(tenant_name: str, files: list[UploadFile] = File(...)):
    """Fayl(lar)ni yuklaydi va avtomatik parse (ingest) qiladi."""
    tenant = _tenant_or_404(tenant_name)
    dataset_id = tenant["dataset_id"]

    tmp_dir = tempfile.mkdtemp(prefix="ragflow_upload_")
    saved_paths = []
    try:
        for f in files:
            dest = os.path.join(tmp_dir, f.filename)
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
        "dataset_id": dataset_id,
        "document_ids": document_ids,
        "parse_triggered": True,
        "parse_response": parse_resp,
    }


@app.get("/tenants/{tenant_name}/documents")
async def list_documents(tenant_name: str):
    tenant = _tenant_or_404(tenant_name)
    try:
        resp = await rf.list_documents(tenant["dataset_id"])
    except RAGFlowError as e:
        raise HTTPException(status_code=502, detail=str(e))
    data = resp["data"]
    # RAGFlow {"docs": [...], "total": N} shaklida qaytaradi
    if isinstance(data, dict):
        return data.get("docs", [])
    return data


# ---------------------------------------------------------------------
# ASK — session avtomatik boshqariladi (user_id bo'yicha)
# ---------------------------------------------------------------------

@app.post("/ask", response_model=AskResponse)
async def ask(req: AskRequest):
    tenant = _tenant_or_404(req.tenant_name)
    chat_id = await _ensure_chat(tenant)

    session_id = db.get_session(req.tenant_name, req.user_id)

    try:
        if not session_id:
            session_resp = await rf.create_session(
                chat_id, session_name=f"user:{req.user_id}"
            )
            session_id = session_resp["data"]["id"]
            db.save_session(req.tenant_name, req.user_id, session_id)

        answer_resp = await rf.ask(chat_id, session_id, req.question, stream=False)
    except RAGFlowError as e:
        raise HTTPException(status_code=502, detail=str(e))

    answer_text = answer_resp.get("data", {}).get("answer", "")

    return AskResponse(session_id=session_id, answer=answer_text, raw=answer_resp)


@app.post("/tenants/{tenant_name}/users/{user_id}/reset-session")
async def reset_session(tenant_name: str, user_id: str):
    """Foydalanuvchi uchun yangi (bo'sh) suhbat sessiyasini boshlaydi."""
    tenant = _tenant_or_404(tenant_name)
    chat_id = await _ensure_chat(tenant)
    try:
        session_resp = await rf.create_session(
            chat_id, session_name=f"user:{user_id}:{uuid.uuid4().hex[:6]}"
        )
    except RAGFlowError as e:
        raise HTTPException(status_code=502, detail=str(e))

    session_id = session_resp["data"]["id"]
    db.save_session(tenant_name, user_id, session_id)
    return {"session_id": session_id}


@app.exception_handler(RAGFlowError)
async def ragflow_error_handler(request, exc: RAGFlowError):
    return JSONResponse(status_code=502, content={"error": str(exc), "payload": exc.payload})


@app.get("/health")
async def health():
    return {"status": "ok"}
