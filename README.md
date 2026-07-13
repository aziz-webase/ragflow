# RAGFlow — Local Enterprise RAG deployment

O'zbekcha hujjatlar uchun to'liq lokal RAG tizimi. Chat uchun sizning mavjud
local LLM'ingiz (gemma), embedding uchun serveringizdagi TEI (bge-m3) ishlatiladi.
Tashqi API'larsiz, hammasi o'z serveringizda.

## Arxitektura

| Komponent | Tanlov |
|-----------|--------|
| RAGFlow | `v0.26.4`, Docker Compose, alohida Linux server |
| Chat LLM | Mavjud: `http://83.69.136.41:8008/v1` → `gemma-4-31B-it` (OpenAI-mos) |
| Embedding | **Local TEI** konteyneri → `BAAI/bge-m3` (ko'p tilli, o'zbek uchun) |
| Doc engine | Elasticsearch |
| API | RAGFlow tayyor HTTP API + Python SDK |

> **Diqqat:** v0.22+ dan boshlab RAGFlow embedding'ni image ichida qadab
> kelmaydi. Buning o'rniga `tei-cpu` profili orqali **local** embedding servisi
> (TEI) ishga tushadi — natija bir xil, hammasi serveringizda offline ishlaydi.

## Server talablari

- Linux (Ubuntu 22.04+ tavsiya)
- Docker Engine + Docker Compose v2
- `git`, `openssl`
- RAM ≥ 16 GB (Elasticsearch ~8 GB oladi), Disk ≥ 50 GB
- Internet (birinchi ishga tushishda image + bge-m3 modeli yuklanadi)
- **GPU rejimi** (`DEVICE=gpu`) uchun qo'shimcha: NVIDIA GPU + drayver +
  [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html).
  Tekshirish: `docker run --rm --gpus all ubuntu nvidia-smi` GPU'ni ko'rsatsa tayyor.
  `bge-m3` ~2 GB VRAM oladi.

## Fayllar

| Fayl | Vazifasi |
|------|----------|
| `ragflow.conf` | Sizning sozlamalaringiz (versiya, TZ, model, xotira) — **shu yerni tahrirlang** |
| `deploy.sh` | Avtomatik deploy skripti (serverda ishga tushiring) |
| `connect-llm.md` | gemma LLM'ni RAGFlow UI'ga ulash bo'yicha qadamlar |
| `test_api.py` | HTTP API'ni uchidan-uchiga sinash skripti |

## Ishga tushirish (Linux serverda)

Shu papkani serverga ko'chiring (masalan `scp -r` yoki `git`), so'ng:

```bash
# 1. Sozlamalarni ko'rib chiqing (ixtiyoriy)
nano ragflow.conf

# 2. Deploy
chmod +x deploy.sh
./deploy.sh
```

Skript avtomatik: talablarni tekshiradi → `vm.max_map_count` ni sozlaydi →
RAGFlow'ni klonlaydi → `.env`ni sozlab **random parollar** generatsiya qiladi →
konteynerlarni ko'taradi.

> **Windows'dan ko'chirsangiz** qator oxirlari (CRLF) muammo bermasligi uchun
> serverda bir marta: `sed -i 's/\r$//' deploy.sh ragflow.conf`

## Deploy'dan keyin (qo'lda, bir martalik)

1. **Web UI** → `http://<server-ip>` → akkaunt yarating (birinchi = admin).
2. **LLM ulash** → [connect-llm.md](connect-llm.md) bo'yicha gemma'ni qo'shing va
   default chat + embedding modellarni tanlang.
3. **Knowledge base** yarating → o'zbekcha hujjatlarni yuklang → **Parse** bosing.
   - Chunk method: matnli hujjatlar uchun **General/Naive**; jadval/skaner ko'p
     bo'lsa boshqa metodlarni sinang.
4. **API** → avatar menyusidan API kalit oling → `test_api.py`ni sinang:
   ```bash
   pip install ragflow-sdk==0.26.4
   # test_api.py ichida API_KEY va BASE_URL ni to'ldiring
   python test_api.py
   ```

## Nima avtomatik, nima qo'lda

**Avtomatik (`deploy.sh`):** infratuzilma — ES, MySQL, Redis, MinIO, RAGFlow
server, local embedding (TEI), web UI + HTTP API. Parollar, kernel sozlamasi.

**Qo'lda (bir martalik):** LLM'ni UI'da ulash, hujjat yuklash, retrieval sozlash,
API kalit olish. Har biri oddiy — connect-llm.md va yuqoridagi qadamlar bo'yicha.

## Boshqaruv

```bash
cd ragflow/docker
docker compose ps                 # holat
docker compose logs -f ragflow    # RAGFlow loglari
docker compose logs -f tei        # embedding (bge-m3 yuklanishi)
docker compose down               # to'xtatish
docker compose up -d              # qayta ishga tushirish
```

## Enterprise eslatmalari

- **Parollar:** `ragflow/docker/.env` ichида random generatsiya qilingan — zaxira qiling.
- **Ro'yxatdan o'tishni yopish:** faqat ichki foydalanuvchilar uchun bo'lsa,
  `.env`da `REGISTER_ENABLED=0` qo'ying (birinchi admin yaratilgach).
- **Backup:** `docker` volume'lari (ES, MySQL, MinIO) va `.env`ni muntazam backup qiling.
- **LLM endpoint xavfsizligi:** connect-llm.md dagi ⚠️ bo'limiga qarang
  (hozir ochiq/HTTP — TLS + auth tavsiya etiladi).
