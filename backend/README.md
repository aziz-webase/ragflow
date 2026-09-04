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
- PostgreSQL (wrapper'ning o'z tenant/agent/tarix ma'lumotlari uchun —
  RAGFlow'ning ichki MySQL'idan mustaqil, alohida DB)
- Ishlayotgan RAGFlow server (repo ildizidagi `deploy.sh` bilan ko'tarilgan),
  unda kamida bitta **Embedding** default model sozlangan (RAGFlow API kalit
  yaratish uchun UI'dan admin akkaunt kerak — repo ildizidagi README.md'ga qarang)

## Sozlash

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

PostgreSQL'da wrapper uchun rol va baza yarating (bir martalik):

```bash
sudo -u postgres psql -c "CREATE ROLE ragflow WITH LOGIN PASSWORD 'ragflow';"
sudo -u postgres psql -c "CREATE DATABASE ragflow_wrapper OWNER ragflow;"
```

`.env`ni tayyorlang:

```bash
cp .env.example .env
```

```
RAGFLOW_BASE_URL=http://127.0.0.1:9380
RAGFLOW_API_KEY=ragflow-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx   # RAGFlow UI -> avatar -> API -> API KEY -> Create new key
DEFAULT_LLM_ID=<model-nomi>@<instance-nomi>                # Model providers'da ulagan chat LLM'ingiz nomi
DATABASE_URL=postgresql://ragflow:ragflow@127.0.0.1:5432/ragflow_wrapper
RAG_RERANK_ID=BAAI/bge-reranker-v2-m3@HuggingFace           # ulamagan bo'lsangiz bo'sh qoldiring
```

> `DEFAULT_LLM_ID` faqat `create_chat_assistant` chaqirilganda aniq LLM
> ko'rsatish uchun ishlatiladi; agar RAGFlow'da tizim darajasida default chat
> model allaqachon tanlangan bo'lsa (Model providers -> Set default models),
> bu qiymat unchalik muhim emas — RAGFlow o'zi shu defaultni ishlataveradi.

## Ishga tushirish

```bash
.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8100
```

Swagger UI: http://<server-ip>:8100/docs

Fonda ishlatish uchun: `nohup .venv/bin/uvicorn main:app --host 0.0.0.0 --port 8100 > backend.log 2>&1 &`

## Tezkor sinov (curl)

```bash
T=webase   # tenant nomi (istalgan)

# 1) Hujjat yuklash (yangi collection avtomatik yaratiladi + parse boshlanadi)
curl -s -X POST http://localhost:8100/tenants/$T/documents \
  -F "collection=hujjatlar" -F "files=@/path/to/fayl.txt"

# 2) Parse tugashini kutib, collectionni tekshiring (document_count > 0 bo'lishi kerak)
curl -s http://localhost:8100/tenants/$T/collections

# 3) Agent yaratish (bir yoki bir nechta collection + system prompt)
curl -s -X POST http://localhost:8100/tenants/$T/agents \
  -H "Content-Type: application/json" \
  -d '{"agent_name":"yordamchi","collections":["hujjatlar"],"system_prompt":"Sen yordamchisan."}'
# -> {"agent_id": "...", ...}

# 4) Savol berish (chat assistant shu yerda RAGFlow tomonida lazy yaratiladi)
curl -s -X POST http://localhost:8100/ask \
  -H "Content-Type: application/json" \
  -d '{"agent_id":"<yuqoridagi agent_id>","user_id":"foydalanuvchi-1","query":"..."}'

# 5) Tarixni ko'rish
curl -s http://localhost:8100/agents/<agent_id>/users/foydalanuvchi-1/history
```

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
