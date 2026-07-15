# RAGFlow Wrapper API

RAGFlow ustidan collection-based yupqa wrapper (FastAPI).

- **tenant** → ko'p **collection** (har biri alohida RAGFlow dataset)
- **`all`** → tenantning barcha collectionlari ustidan combined RAG
- Har collection (va `all`) o'z **system prompt**iga ega
- User tarixi PostgreSQL'da saqlanadi

To'liq arxitektura: [PLAN.md](PLAN.md)

## Talablar

- Python 3.10+
- PostgreSQL (ulanish `DATABASE_URL` orqali)
- Ishlayotgan RAGFlow server + API key

## Sozlash

```bash
pip install -r requirements.txt
cp .env.example .env   # va qiymatlarni to'ldiring
```

`.env`:
```
RAGFLOW_BASE_URL=...
RAGFLOW_API_KEY=...
DEFAULT_LLM_ID=...
DATABASE_URL=postgresql://user:password@host:5432/ragflow_wrapper
```

## Ishga tushirish

```bash
uvicorn main:app --port 8100 --reload
```

Swagger UI: http://localhost:8100/docs

## Asosiy endpointlar

| Method | Path | Tavsif |
|--------|------|--------|
| POST | `/tenants/{tenant}/documents` | `collection` + `files` — hujjat yuklash + parse |
| POST | `/tenants/{tenant}/collections/prompt` | `collection`/`collections` + `system_prompt` |
| GET  | `/tenants/{tenant}/collections` | collectionlar ro'yxati (+ `all`) |
| POST | `/ask` | `tenant_name`, `collection`, `user_id`, `question` |
| GET  | `/tenants/{tenant}/users/{user_id}/history` | user tarixi (`?collection=` ixtiyoriy) |

**Tartib:** hujjat yuklash → parse tugashini kutish → (ixtiyoriy) prompt o'rnatish → `/ask`.
