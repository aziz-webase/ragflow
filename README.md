# RAGFlow — Local Enterprise RAG deployment

O'zbekcha hujjatlar uchun to'liq lokal RAG tizimi. Chat uchun sizning mavjud
local LLM'ingiz (gemma), embedding uchun serveringizdagi TEI (bge-m3) ishlatiladi.
Tashqi API'larsiz, hammasi o'z serveringizda.

Bu repo ikki qismdan iborat:
- **Infratuzilma** (shu fayl) — RAGFlow'ning o'zini deploy qilish (`deploy.sh`).
- **Backend** ([backend/README.md](backend/README.md)) — har bir kompaniya (tenant)
  uchun collection/agent yaratib beruvchi FastAPI wrapper, RAGFlow ustida ishlaydi.

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
| Chat LLM | Sizning mavjud OpenAI-mos LLM serveringiz (masalan llama.cpp/vLLM + gemma) — pastga qarang |
| Embedding | **Local TEI** konteyneri → `BAAI/bge-m3` (ko'p tilli, o'zbek uchun) |
| Rerank | **Local TEI** konteyneri → `BAAI/bge-reranker-v2-m3` (qo'lda bir martalik model yuklash kerak — pastga qarang) |
| Doc engine | Elasticsearch |
| API | RAGFlow tayyor HTTP API + Python SDK |

> **Diqqat:** v0.22+ dan boshlab RAGFlow embedding'ni image ichida qadab
> kelmaydi. Buning o'rniga `tei-cpu` profili orqali **local** embedding servisi
> (TEI) ishga tushadi — natija bir xil, hammasi serveringizda offline ishlaydi.

## Server talablari

- Linux (Ubuntu 22.04+ tavsiya)
- **Docker Engine (apt `docker-ce`) + Docker Compose v2 + NVIDIA Container Toolkit**
  (GPU uchun). Snap orqali o'rnatilgan Docker'da GPU konteynerlari (proprietary
  NVIDIA kutubxonalarni ko'ra olmasligi sababli) ishlamaydi — agar sizda snap
  Docker bo'lsa, avval standart apt `docker-ce`ga o'ting:
  [rasmiy qo'llanma](https://docs.docker.com/engine/install/ubuntu/) +
  [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html).
  Tekshirish: `docker run --rm --gpus all --runtime=nvidia nvidia/cuda:12.2.0-base-ubuntu22.04 nvidia-smi`
  GPU'ni ko'rsatsa tayyor.
- `git`, `openssl`
- RAM ≥ 16 GB (Elasticsearch ~8 GB oladi), Disk ≥ 50 GB
- Internet (birinchi ishga tushishda image'lar yuklanadi; embedding/rerank
  modellarini esa **qo'lda** yuklaysiz — pastga qarang)
- **GPU rejimi** (`DEVICE=gpu`) uchun: NVIDIA GPU + drayver. `bge-m3` ~2 GB,
  `bge-reranker-v2-m3` ~2-3 GB VRAM oladi (ikkalasi birga ~4-5 GB).

  > **Muhim — GPU image tegi compute capability'ga mos bo'lishi kerak.**
  > `ragflow/docker/docker-compose.override.yml`dagi `tei-gpu`/`tei-rerank`
  > image tegi (`ghcr.io/huggingface/text-embeddings-inference:<XX>-1.7`)
  > standart holatda **Ampere (compute capability 8.6, masalan RTX 30-seriya)**
  > uchun sozlangan. Boshqa GPU bo'lsa:
  > 1. `nvidia-smi --query-gpu=compute_cap --format=csv` bilan compute
  >    capability'ni aniqlang (masalan `7.5` Turing/RTX 20, `8.9` Ada/RTX 40,
  >    `9.0` Hopper, `12.0` Blackwell/RTX 50).
  > 2. Override fayldagi ikkala `image:` qatorini
  >    `ghcr.io/huggingface/text-embeddings-inference:<compute_cap raqamlari>-1.7`
  >    ga o'zgartiring (masalan `89-1.7`, `120-1.7`).
  > 3. `nvidia-smi`dagi **"CUDA Version"** ustuni drayveringiz qo'llab-quvvatlaydigan
  >    eng yuqori CUDA versiyasini ko'rsatadi. Tegdagi minor versiya (`-1.9` kabi)
  >    undan yangi CUDA talab qilsa, konteyner xato bermay jimgina CPU'ga tushib
  >    qoladi (loglarda `CUDA_ERROR_COMPAT_NOT_SUPPORTED_ON_DEVICE` va
  >    `Using CPU instead` ko'rinadi) — shu holatda pastroq minor versiyani
  >    (`-1.7`, `-1.6`) sinang.
  > 4. `docker compose pull tei-gpu tei-rerank && docker compose up -d tei-gpu tei-rerank`
  >    so'ng `docker compose logs tei-gpu` da `Starting FlashBert model on Cuda(...)`
  >    ko'rinsa — GPU haqiqatan ishlatilyapti.

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

## Backend — kompaniyalar uchun agent API

RAGFlow o'zi ko'targandan va yuqoridagi qo'lda qadamlar (LLM/embedding/rerank
ulash, API kalit olish) bajarilgandan keyin, **har bir kompaniya (tenant) uchun
alohida agent yaratib beruvchi** FastAPI wrapper `backend/` papkasida turadi —
u RAGFlow ustida ishlaydi: tenant → collection (hujjatlar) → agent (collection +
system prompt) → `/ask`.

To'liq qo'llanma: [backend/README.md](backend/README.md). Qisqacha:

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# Wrapper'ning o'z ma'lumotlari (tenant/agent/tarix) uchun alohida Postgres:
sudo -u postgres psql -c "CREATE ROLE ragflow WITH LOGIN PASSWORD 'ragflow';"
sudo -u postgres psql -c "CREATE DATABASE ragflow_wrapper OWNER ragflow;"

cp .env.example .env
# .env ichida to'ldiring: RAGFLOW_BASE_URL, RAGFLOW_API_KEY (yuqoridagi
# "API kalit olish" qadamidan), DATABASE_URL (default qiymat mos keladi)

.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8100
# Swagger UI: http://<server-ip>:8100/docs
```

## Nima avtomatik, nima qo'lda

**Avtomatik (`deploy.sh`):** infratuzilma — ES, MySQL, Redis, MinIO, RAGFlow
server, local embedding (TEI), web UI + HTTP API. Parollar, kernel sozlamasi.

**Qo'lda (bir martalik):** embedding/rerank/LLM modellarini UI'da ulash, API
kalit olish, `backend/`ni sozlab ishga tushirish. Har biri oddiy — connect-llm.md
va yuqoridagi qadamlar bo'yicha.

## Embedding + Rerank modellari (bge-m3, bge-reranker-v2-m3) — yangi serverda sozlash

`docker-compose.override.yml`dagi `tei-gpu` (embedding, `bge-m3`) va
`tei-rerank` (rerank, `bge-reranker-v2-m3`) — **ikkalasi ham** `/data/BAAI/<model>`
yo'lidan modelni docker volume ichidan kutadi, image ichida qadalgan emas va
avtomatik yuklab olmaydi. Shu sabab **ikkalasini ham har bir yangi serverda bir
martalik qo'lda yuklash** kerak — aks holda konteynerlar `404 Not Found` bilan
crash-loop qiladi (loglarda `Could not download model artifacts` ko'rinadi).

> **Nega avtomatik yuklanmaydi:** ba'zi serverlarda docker konteynerlari tashqi
> internetga chiqa olmasligi mumkin (firewall/NAT sozlamasiga qarab) — host
> mashina internetga chiqsa ham. Shu sababli modellarni **host'da** yuklab,
> tayyor holda konteyner volume'iga qo'yish eng ishonchli yo'l.

```bash
# 1. git-lfs kerak (model fayllari Git LFS orqali saqlangan)
git lfs version || sudo apt-get install -y git-lfs

# 2. Docker compose loyiha nomi doim "docker" (papka nomidan olinadi),
#    shuning uchun volume nomlari ham doim shu bo'ladi — repo qayerga
#    klonlanishidan qat'i nazar:
docker volume create docker_tei_data
docker volume create docker_tei_rerank_data

# 3. Volume manzillarini toping va model uchun papka yarating
VOL_DATA=$(docker volume inspect docker_tei_data --format '{{.Mountpoint}}')
VOL_RERANK=$(docker volume inspect docker_tei_rerank_data --format '{{.Mountpoint}}')
sudo mkdir -p "$VOL_DATA/BAAI" "$VOL_RERANK/BAAI"

# 4. Modellarni to'g'ridan-to'g'ri shu papkalarga klonlang (~2.2 GB + ~2.3 GB,
#    tarmoqqa qarab bir necha daqiqadan bir necha o'n daqiqagacha vaqt olishi mumkin)
cd "$VOL_DATA/BAAI"    && sudo git clone https://huggingface.co/BAAI/bge-m3
cd "$VOL_RERANK/BAAI"  && sudo git clone https://huggingface.co/BAAI/bge-reranker-v2-m3

# 5. Xizmatlarni ishga tushiring (agar deploy.sh/docker compose up -d allaqachon
#    ishlagan bo'lsa, shu buyruq yetarli — profil GPU rejimida avtomatik yoqilgan)
cd ragflow/docker
docker compose up -d tei-gpu tei-rerank

# 6. Tekshirish — pastdagidek JSON qaytsa, ishlayapti:
curl -s -X POST http://localhost:6380/embed \
  -H "Content-Type: application/json" -d '{"inputs":"salom dunyo"}'
curl -s -X POST http://localhost:6381/rerank \
  -H "Content-Type: application/json" \
  -d '{"query":"test","texts":["birinchi matn","ikkinchi matn"]}'
```

GPU image tegini qanday tanlash haqida yuqoridagi **Server talablari** bo'limidagi
"Muhim — GPU image tegi" eslatmasiga qarang.

### RAGFlow UI'da default embedding va rerank model qilib ulash

Sozlamalar → **Model providers** → qidiruvda **HuggingFace**ni toping → **Add**:

| Maydon | Embedding uchun | Rerank uchun |
|--------|------------------|--------------|
| Model type | `Embedding` | `Rerank` |
| Model name | `BAAI/bge-m3` | `BAAI/bge-reranker-v2-m3` |
| Base url | `http://tei:80` | `http://tei-rerank:80` |

(RAGFlow konteyneri bilan bir xil docker tarmog'ida bo'lgani uchun ichki
hostname orqali ulanadi — tashqi `6380`/`6381` portlar shart emas.) Saqlangach,
sahifa yuqorisidagi **Set default models**da Embedding va Rerank uchun shu
modellarni default qilib tanlang.

### Chat LLM'ni ulash

[connect-llm.md](connect-llm.md)ga qarang — jarayon xuddi shunga o'xshash
(**OpenAI-API-Compatible** provider, Base url + model nomi), faqat Base url
sizning haqiqiy LLM serveringiz manzili bo'ladi. **Diqqat:** RAGFlow modelni
saqlashdan oldin darhol ulanishni tekshiradi — agar Base url bu serverdan
(yoki RAGFlow konteyneridan) yetib bo'lmasa, saqlash jimgina muvaffaqiyatsiz
tugaydi (interfeys osilib qoladi, "Added models"da ko'rinmaydi). Avval
`curl -X POST <base-url>/chat/completions ...` bilan endpoint shu serverdan
yetib borishini tekshiring.

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
