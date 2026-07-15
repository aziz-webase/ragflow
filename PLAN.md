# RAGFlow Wrapper — Collection-based arxitektura rejasi

## Asosiy model
**`collection` = RAGFlow `dataset`.** Har bir collection alohida dataset (KB).

```
tenant (tashkilot)
 ├─ collection A  = dataset A + system_prompt A + chat assistant A
 ├─ collection B  = dataset B + system_prompt B + chat assistant B
 └─ "all"         = datasets [A,B] + "all" system_prompt + combined assistant
```

- `collection` maydoni **hamma joyda majburiy**.
- `"all"` — zahiralangan (reserved) nom: barcha collectionlar ustidan RAG (combined assistant).
- Har collection, jumladan `"all"`, o'z system_promptiga ega.
- Combined assistant yangi collection qo'shilganda avtomatik `dataset_ids`ini yangilaydi.

## Qarorlar (tasdiqlangan)
- History → Postgres `messages` jadvaliga nusxalanadi; history API shundan o'qiydi.
- `/ask`da `collection` majburiy — berilmasa 400.
- `"all"` = reserved collection; unga hujjat yuklab bo'lmaydi.
- GET `/collections` = ko'rsatish/boshqarish uchun (ask uchun majburiy emas).
- DB = Postgres (asyncpg + pool).

## API surface
1. `POST /tenants/{tenant_name}/documents` — `collection` (majburiy, ≠ "all"), `files`. Dataset lazy-yaratadi, parse.
2. `POST /tenants/{tenant_name}/collections/prompt` — `collection` yoki `collections:[...]` (jumladan "all"), `system_prompt`.
3. `GET /tenants/{tenant_name}/collections` — ro'yxat (nom, hujjat soni, prompt bor/yo'q, holat).
4. `POST /ask` — `tenant_name`, `collection` (majburiy), `user_id`, `question`. Javob `messages`ga yoziladi.
5. `GET /tenants/{tenant_name}/users/{user_id}/history` (`?collection=` ixtiyoriy).

## Postgres sxema
```
tenants(tenant_name PK, created_at)
collections(id PK, tenant_name FK, collection_name, dataset_id,
            chat_id NULL, system_prompt NULL, created_at,
            UNIQUE(tenant_name, collection_name))
tenant_assistants(tenant_name PK, chat_id NULL, system_prompt NULL)   -- "all"
sessions(tenant_name, user_id, scope, session_id, chat_id,
         PK(tenant_name, user_id, scope))       -- scope = collection_name | 'all'
messages(id PK, tenant_name, user_id, scope, role, content, reference JSONB, created_at)
```

## Texnik nuqtalar
- System prompt + majburiy `{knowledge}` bloki avtomatik birlashtiriladi.
- RAGFlow bo'sh datasetga assistant ulamaydi (code 102) → assistant lazy (parse bo'lgach).
- Dataset nomi global to'qnashuvni oldini olish uchun `{tenant}__{collection}`.
- `_request`ga retry + umumiy httpx client (connection pool).

## Fazalar
1. **Infra:** SQLite → Postgres (asyncpg pool), config `DATABASE_URL`, sxema init, requirements.
2. **Collection ingest:** documents endpointiga `collection`, dataset lazy-yaratish, "all" rad etish.
3. **Prompt endpoint:** collections/prompt (single/list/"all"), prompt merge, assistant PUT update.
4. **Ask (collection-aware):** scope routing, lazy assistant (single/combined), session (tenant,user,scope).
5. **History:** messages'ga yozish + GET history.
6. **Collections list** endpoint.
7. **Robustness + cleanup:** _request retry, umumiy httpx client, eski test datasetlarni tozalash.
