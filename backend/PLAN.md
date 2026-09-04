# RAGFlow Wrapper — Agent-based arxitektura

## Asosiy model
```
tenant (tashkilot)
 ├─ collection A = dataset A   (hujjat konteyneri)
 ├─ collection B = dataset B
 └─ collection C = dataset C

 agent "sales"  = [A, B]      + system_prompt_1   (= RAGFlow chat assistant)
 agent "support"= [A, C]      + system_prompt_2
```

- **collection** = RAGFlow dataset (faqat hujjat konteyneri).
- **agent** = tanlangan collectionlar + system prompt = RAGFlow chat assistant + metadata.
- `/ask` faqat `agent_id` + `user_id` + `query` oladi. Agent o'z collection'lari va promptini biladi.

## Qarorlar (tasdiqlangan)
- `/ask` = `agent_id` + `user_id` + `query` (per-user history saqlanadi).
- `agent_id` = server UUID; `agent_name` tenant ichida unikal.
- PUT bilan agent tahrirlanadi (collections/prompt/name); RAGFlow assistant ham yangilanadi.
- History → Postgres `messages` (agent_id, user_id bo'yicha).
- DB = PostgreSQL (asyncpg + pool).

## API surface
| Method | Path | Body / natija |
|--------|------|---------------|
| POST | `/tenants` | `{tenant_name}` |
| POST | `/tenants/{t}/documents` | `collection` + `files` → dataset + parse |
| GET  | `/tenants/{t}/collections` | collectionlar ro'yxati (tanlash uchun) |
| POST | `/tenants/{t}/agents` | `{agent_name, collections:[...], system_prompt}` → `{agent_id}` |
| GET  | `/tenants/{t}/agents` | agentlar ro'yxati |
| PUT  | `/tenants/{t}/agents/{agent_id}` | `{agent_name?, collections?, system_prompt?}` |
| POST | `/ask` | `{agent_id, user_id, query}` |
| POST | `/agents/{agent_id}/users/{user_id}/reset-session` | yangi sessiya |
| GET  | `/agents/{agent_id}/users/{user_id}/history` | user tarixi |

## Postgres sxema
```
tenants(tenant_name PK, created_at)
collections(id PK, tenant_name FK, collection_name, dataset_id, created_at,
            UNIQUE(tenant_name, collection_name))
agents(agent_id PK, tenant_name FK, agent_name, system_prompt, chat_id NULL,
       created_at, UNIQUE(tenant_name, agent_name))
agent_collections(agent_id FK, collection_name, PK(agent_id, collection_name))
sessions(agent_id FK, user_id, session_id, chat_id, PK(agent_id, user_id))
messages(id PK, agent_id, user_id, role, content, reference JSONB, created_at)
```

## RAGFlow mapping
- agent → chat assistant; agent collectionlari → `dataset_ids`; agent prompt → assistant prompt.
- Assistant **lazy** yaratiladi (birinchi `/ask` paytida; bo'sh dataset → 102 → 409).
- PUT'da `update_chat_datasets` / `update_chat_prompt` bilan mavjud assistant yangilanadi.
- System prompt = persona + majburiy `{knowledge}` bloki (ragflow_client.build_system_prompt).

## Texnik nuqtalar
- Dataset nomi global to'qnashuvni oldini olish uchun `{tenant}__{collection}`.
- `ragflow_client._request` — umumiy httpx client + tarmoq retry (ngrok uzilishlari uchun).
