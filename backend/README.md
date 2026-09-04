# RAGFlow Wrapper API

RAGFlow ustidan agent-based yupqa wrapper (FastAPI). RAGFlow'ning o'zini deploy
qilish uchun repo ildizidagi [README.md](../README.md) va `../deploy.sh`ga qarang.

- **tenant** → ko'p **collection** (har biri RAGFlow dataset, hujjat konteyneri)
- **agent** = tanlangan collectionlar + system prompt (= RAGFlow chat assistant)
- **`/ask`** faqat `agent_id` + `user_id` + `query` oladi
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
| POST | `/tenants/{t}/documents` | `collection` + `files` — hujjat yuklash + parse |
| GET  | `/tenants/{t}/collections` | collectionlar ro'yxati (tanlash uchun) |
| POST | `/tenants/{t}/agents` | `agent_name` + `collections[]` + `system_prompt` → `agent_id` |
| GET  | `/tenants/{t}/agents` | agentlar ro'yxati |
| PUT  | `/tenants/{t}/agents/{agent_id}` | agentni tahrirlash |
| POST | `/ask` | `agent_id`, `user_id`, `query` |
| GET  | `/agents/{agent_id}/users/{user_id}/history` | user tarixi |

**Tartib:** hujjat yuklash (collection) → parse kutish → agent yaratish (collections tanlab) → `/ask` (agent_id bilan).
