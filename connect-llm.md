# Local LLM (gemma) ni RAGFlow ga ulash

Sizning LLM allaqachon ishlab turibdi (OpenAI-mos endpoint):

- **Base URL:** `http://83.69.136.41:8008/v1`
- **Model:** `gemma-4-31B-it`
- **Auth:** yo'q (endpoint ochiq — pastdagi xavfsizlik eslatmasiga qarang)

RAGFlow buni "OpenAI-API-Compatible" provider sifatida qabul qiladi.

---

## 1-qadam — Chat modelini qo'shish

1. Web UI ga kiring → yuqori o'ng burchakdagi **avatar** → **Model providers**
   (yoki **Model Providers** / **Модели** bo'limi).
2. Ro'yxatdan **OpenAI-API-Compatible** ni toping → **Add the model**.
3. Maydonlarni to'ldiring:

   | Maydon | Qiymat |
   |--------|--------|
   | **Model type** | `chat` |
   | **Model name** | `gemma-4-31B-it` |
   | **Base URL** | `http://83.69.136.41:8008/v1` |
   | **API-Key** | `sk-local` *(endpoint auth talab qilmaydi, lekin maydon bo'sh bo'lmasin)* |
   | **Max tokens** | `8192` *(gemma context oynangizga qarab moslang — 32k/128k bo'lsa oshiring)* |

4. **OK** bosing.

> **Eslatma — Max tokens:** context oynasini aniq bilsangiz shuni qo'ying.
> Bilmasangiz `8192` xavfsiz boshlanish. RAG da prompt = savol + qidirilgan
> chunk'lar, shuning uchun bu qiymat javob + kontekstga yetishi kerak.

---

## 2-qadam — Tizim modeli sifatida tanlash

**Model providers** → yuqorida **Set default models** (yoki **System Model Settings**):

- **Chat model:** `gemma-4-31B-it`
- **Embedding model:** `BAAI/bge-m3` — bu local TEI orqali avtomatik keladi.
  Agar ro'yxatда ko'rinmasa: TEI konteyneri hali model yuklab bo'lmagan bo'lishi
  mumkin — `docker compose logs -f tei` bilan tekshiring va bir necha daqiqa kuting.

Saqlang.

---

## 3-qadam — Ulanishni tekshirish

Serverdan (yoki RAGFlow konteyneri tarmog'idan) endpoint yashayotganini tekshiring:

```bash
curl -sS -X POST 'http://83.69.136.41:8008/v1/chat/completions' \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "gemma-4-31B-it",
    "messages": [{"role":"user","content":"Salom, ishlayapsanmi?"}],
    "max_tokens": 64
  }'
```

Javob kelsa — RAGFlow ham ulana oladi. Agar RAGFlow serveri LLM serveridan
alohida bo'lsa, **firewall `8008` portga chiqishga ruxsat berishi** shart.

---

## Xavfsizlik eslatmasi ⚠️

`http://83.69.136.41:8008` — bu **ochiq, autentifikatsiyasiz, HTTP (shifrsiz)**
public IP. Enterprise muhit uchun tavsiya:

- LLM endpointни faqat ichki tarmoqqa cheklang yoki reverse-proxy + API key qo'ying.
- Imkon bo'lsa HTTPS (TLS) qo'ying.
- Agar RAGFlow xuddi shu serverda (83.69.136.41) ko'tarilsa, Base URL'ni
  `http://localhost:8008/v1` qilib, portni tashqariga umuman ochmang.
