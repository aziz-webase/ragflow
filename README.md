# RAGFlow — Local Enterprise RAG deployment

O'zbekcha hujjatlar uchun to'liq lokal RAG tizimi. Chat uchun sizning mavjud
local LLM'ingiz (gemma), embedding uchun serveringizdagi TEI (bge-m3) ishlatiladi.
Tashqi API'larsiz, hammasi o'z serveringizda.

##

```
git clone git@github.com:aziz-webase/ragflow.git
cd ragflow/ragflow/docker      # e'tibor bering: papka ichida yana "ragflow" bor
docker compose up -d
docker compose stop
```

## Arxitektura

| Komponent | Tanlov |
|-----------|--------|
| RAGFlow | `v0.26.4`, Docker Compose, alohida Linux server |
| Chat LLM | Mavjud: `http://83.69.136.41:8008/v1` → `gemma-4-31B-it` (OpenAI-mos) |
| Embedding | **Local TEI** konteyneri → `BAAI/bge-m3` (ko'p tilli, o'zbek uchun) |
| Rerank | **Local TEI** konteyneri → `BAAI/bge-reranker-v2-m3` (qo'lda bir martalik model yuklash kerak — pastga qarang) |
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

## Reranker (BAAI/bge-reranker-v2-m3) — yangi serverda sozlash

`ragflow/docker/docker-compose.override.yml` ichida **`tei-rerank`** xizmati allaqachon
tayyor (GPU, port `6381`, profil: `tei-gpu`). Lekin modelning o'zi (~2.3 GB) **git'ga
push qilinmagan** — repo hajmini shishirmaslik uchun. Shu sabab **har bir yangi
serverda bir martalik qo'lda yuklash** kerak.

> **Nega avtomatik yuklanmaydi:** ba'zi serverlarda docker konteynerlari (faqat
> tei-rerank emas, umuman) tashqi internetga chiqa olmasligi mumkin (firewall/NAT
> sozlamasiga qarab) — host mashina internetga chiqsa ham. Shu sababli modelni
> **host'da** yuklab, tayyor holda konteyner volume'iga qo'yish eng ishonchli yo'l.

```bash
# 1. git-lfs kerak (model fayllari Git LFS orqali saqlangan)
git lfs version || sudo apt-get install -y git-lfs

# 2. Docker compose loyiha nomi doim "docker" (papka nomidan olinadi),
#    shuning uchun volume nomi ham doim shu bo'ladi — repo qayerga
#    klonlanishidan qat'i nazar:
docker volume create docker_tei_rerank_data

# 3. Volume manzilini toping va model uchun papka yarating
VOL_DIR=$(docker volume inspect docker_tei_rerank_data --format '{{.Mountpoint}}')
sudo mkdir -p "$VOL_DIR/BAAI"

# 4. Modelni to'g'ridan-to'g'ri shu papkaga klonlang (~2.3 GB, tarmoqqa qarab
#    bir necha daqiqadan bir necha o'n daqiqagacha vaqt olishi mumkin)
cd "$VOL_DIR/BAAI"
sudo git clone https://huggingface.co/BAAI/bge-reranker-v2-m3

# 5. Xizmatni ishga tushiring (agar deploy.sh/docker compose up -d allaqachon
#    ishlagan bo'lsa, shu buyruq yetarli — profil GPU rejimida avtomatik yoqilgan)
cd ragflow/docker
docker compose up -d tei-rerank

# 6. Tekshirish — pastdagidek JSON qaytsa, ishlayapti:
curl -s -X POST http://localhost:6381/rerank \
  -H "Content-Type: application/json" \
  -d '{"query":"test","texts":["birinchi matn","ikkinchi matn"]}'
```

VRAM: modelga taxminan 2-3 GB kerak bo'ladi (`bge-m3` embedding bilan bir qatorda).

### RAGFlow UI'da default rerank modeli qilib ulash

1. Sozlamalar → **Model Providers** → **Add Model**
2. Provider: **HuggingFace**
3. Model turi: **Rerank**
4. Model nomi: `BAAI/bge-reranker-v2-m3`
5. Base URL: `http://tei-rerank:80` (RAGFlow konteyneri bilan bir xil docker
   tarmog'ida bo'lgani uchun ichki hostname orqali ulanadi — tashqi `6381`
   port shart emas)
6. Saqlang, so'ng Knowledge Base (yoki umumiy default model) sozlamalarida
   shu rerank modelni tanlang.

## Boshqaruv

```bash
cd ragflow/docker
docker compose ps                 # holat
docker compose logs -f ragflow    # RAGFlow loglari
docker compose logs -f tei        # embedding (bge-m3 yuklanishi)
docker compose logs -f tei-rerank # reranker (bge-reranker-v2-m3)
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
