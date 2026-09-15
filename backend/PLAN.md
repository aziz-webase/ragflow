# RAGFlow Wrapper — Agent-based arxitektura

## Asosiy model
```
collection A = dataset A   (hujjat konteyneri)
collection B = dataset B
collection C = dataset C

agent "sales"  = [A, B]      + system_prompt_1   (= RAGFlow chat assistant)
agent "support"= [A, C]      + system_prompt_2
```

- **collection** = RAGFlow dataset (faqat hujjat konteyneri), global unikal nom.
- **agent** = tanlangan collectionlar + system prompt = RAGFlow chat assistant + metadata, global unikal nom.
- `/chat` faqat `agent_id` + `user_id` + `query` oladi. Agent o'z collection'lari va promptini biladi.
- Tenant/tashkilot darajasi yo'q — bitta wrapper instansi bitta flat collection/agent
  fazosini boshqaradi. Alohida mijozlar kerak bo'lsa, alohida wrapper deployment
  (alohida Postgres + RAGFlow API key) ishlatiladi.

## Qarorlar (tasdiqlangan)
- `/chat` = `agent_id` + `user_id` + `query` (per-user history saqlanadi).
- `agent_id` = server UUID; `agent_name` global unikal.
- `collection_name` global unikal (dataset nomi ham to'g'ridan-to'g'ri shu nom).
- PUT bilan agent tahrirlanadi (collections/prompt/name); RAGFlow assistant ham yangilanadi.
- History → Postgres `messages` (agent_id, user_id bo'yicha).
- DB = PostgreSQL (asyncpg + pool).

## API surface
| Method | Path | Body / natija |
|--------|------|---------------|
| POST | `/documents` | `collection` + `files` → dataset + parse |
| GET  | `/collections/{collection}/documents` | hujjatlar parse holati (`status`, `progress`, `all_ready`) |
| GET  | `/collections` | collectionlar ro'yxati (tanlash uchun) |
| POST | `/agents` | `{agent_name, collections:[...], system_prompt}` → `{agent_id}` |
| GET  | `/agents` | agentlar ro'yxati |
| PUT  | `/agents/{agent_id}` | `{agent_name?, collections?, system_prompt?}` |
| POST | `/retrieve` | `{agent_id, query, top_k}` → LLM'siz retrieval (embedding+rerank) |
| POST | `/chat` | `{agent_id, user_id, query}` |
| POST | `/agents/{agent_id}/users/{user_id}/reset-session` | yangi sessiya |
| GET  | `/agents/{agent_id}/users/{user_id}/history` | user tarixi |

## Postgres sxema
```
collections(collection_name PK, dataset_id, created_at)
agents(agent_id PK, agent_name UNIQUE, system_prompt, chat_id NULL, created_at)
agent_collections(agent_id FK, collection_name FK, PK(agent_id, collection_name))
sessions(agent_id FK, user_id, session_id, chat_id, PK(agent_id, user_id))
messages(id PK, agent_id, user_id, role, content, reference JSONB, created_at)
```

## RAGFlow mapping
- agent → chat assistant; agent collectionlari → `dataset_ids`; agent prompt → assistant prompt.
- Assistant **lazy** yaratiladi (birinchi `/chat` paytida; bo'sh dataset → 102 → 409).
- PUT'da `update_chat_datasets` / `update_chat_prompt` bilan mavjud assistant yangilanadi.
- System prompt = persona + majburiy `{knowledge}` bloki (ragflow_client.build_system_prompt).
- Dataset nomi = collection nomi to'g'ridan-to'g'ri (global unikal bo'lgani uchun
  prefiks kerak emas).

## Texnik nuqtalar
- `ragflow_client._request` — umumiy httpx client + tarmoq retry (ngrok uzilishlari uchun).
- Embedding modeli har bir dataset yaratilgan paytida qotib qoladi — default
  embedding'ni almashtirish mavjud collection'larga ta'sir qilmaydi.
