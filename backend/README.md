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

# 2) Parse (embedding) tugashini pollab kutish — all_ready:true bo'lguncha
#    har 2-3 soniyada qayta chaqiring (hujjat yuklashdan keyin darhol
#    agent yaratish/`/ask` chaqirish — "hujjat yo'q" 409 xatosiga olib kelishi mumkin)
curl -s http://localhost:8100/tenants/$T/collections/hujjatlar/documents
# -> {"all_ready": true/false, "any_failed": false, "documents": [{"status": "DONE", "progress": 1.0, ...}]}

# 3) Agent yaratish (bir yoki bir nechta collection + system prompt)
curl -s -X POST http://localhost:8100/tenants/$T/agents \
  -H "Content-Type: application/json" \
  -d '{"agent_name":"yordamchi","collections":["hujjatlar"],"system_prompt":"Sen yordamchisan."}'
# -> {"agent_id": "...", ...}

# 4a) Faqat retrieval'ni sinash (LLM chaqirilmaydi — sifat/latency alohida tekshirish uchun)
curl -s -X POST http://localhost:8100/retrieve \
  -H "Content-Type: application/json" \
  -d '{"agent_id":"<agent_id>","query":"...","top_k":5}'

# 4b) Savol berish (chat assistant shu yerda RAGFlow tomonida lazy yaratiladi)
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
| GET  | `/tenants/{t}/collections/{collection}/documents` | hujjatlarning parse holati (`status`, `progress`, `all_ready`) — upload'dan keyin shuni pollang |
| POST | `/tenants/{t}/agents` | `agent_name` + `collections[]` + `system_prompt` → `agent_id` |
| GET  | `/tenants/{t}/agents` | agentlar ro'yxati |
| PUT  | `/tenants/{t}/agents/{agent_id}` | agentni tahrirlash |
| POST | `/retrieve` | `agent_id` + `query` + `top_k` — faqat retrieval (embedding+rerank), LLM'siz |
| POST | `/ask` | `agent_id`, `user_id`, `query` |
| GET  | `/agents/{agent_id}/users/{user_id}/history` | user tarixi |

**Tartib:** hujjat yuklash (collection) → `/tenants/{t}/collections/{collection}/documents`ni `all_ready:true` bo'lguncha pollash → agent yaratish (collections tanlab) → `/retrieve` (ixtiyoriy, sifat tekshirish) → `/ask` (agent_id bilan).
