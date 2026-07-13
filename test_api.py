#!/usr/bin/env python3
"""
RAGFlow HTTP API end-to-end test (v0.26.4).

O'rnatish:
    pip install ragflow-sdk==0.26.4

Ishlatish:
    1) Web UI -> avatar -> API -> API kalitini oling.
    2) Pastdagi API_KEY va BASE_URL ni to'ldiring.
    3) python test_api.py

Skript quyidagilarni bajaradi:
    dataset yaratadi -> o'zbekcha hujjat yuklaydi -> parse qiladi ->
    chat assistant yaratadi -> savol beradi -> javobni chiqaradi.
"""

import time
import sys

# ------------------------------------------------------------------
# SOZLAMALAR — to'ldiring
# ------------------------------------------------------------------
API_KEY  = "ragflow-XXXXXXXXXXXXXXXXXXXX"      # Web UI -> API bo'limidan
BASE_URL = "http://83.69.136.41:9380"          # RAGFlow SERVER (LLM emas!) :9380
# ------------------------------------------------------------------

try:
    from ragflow_sdk import RAGFlow
except ImportError:
    sys.exit("ragflow-sdk topilmadi. O'rnating:  pip install ragflow-sdk==0.26.4")

SAMPLE_TEXT = (
    "Kompaniya 2024-yilda tashkil etilgan. Bosh ofis Toshkent shahrida joylashgan. "
    "Asosiy faoliyat yo'nalishi — sun'iy intellekt asosidagi hujjat qidiruv tizimlari. "
    "Mijozlarni qo'llab-quvvatlash bo'limi dushanbadan jumagacha, soat 9:00 dan 18:00 gacha ishlaydi. "
    "Bepul sinov muddati 14 kun."
)
QUESTION = "Bosh ofis qayerda joylashgan va qo'llab-quvvatlash qachon ishlaydi?"


def main():
    rag = RAGFlow(api_key=API_KEY, base_url=BASE_URL)

    # 1) Dataset (knowledge base). embedding_model berilmasa tizim default'i ishlatiladi
    #    (System Model Settings da bge-m3 tanlangan bo'lishi kerak).
    name = f"uz-test-{int(time.time())}"
    print(f"[1] Dataset yaratilmoqda: {name}")
    ds = rag.create_dataset(name=name, chunk_method="naive")

    # 2) Hujjat yuklash
    print("[2] Hujjat yuklanmoqda")
    ds.upload_documents([{
        "display_name": "kompaniya.txt",
        "blob": SAMPLE_TEXT.encode("utf-8"),
    }])
    docs = ds.list_documents()
    doc_ids = [d.id for d in docs]

    # 3) Parse (async) va tugashini kutish
    print("[3] Parsing (chunking + embedding)...")
    ds.async_parse_documents(doc_ids)
    for _ in range(60):  # ~5 daqiqagacha kutamiz
        time.sleep(5)
        done = [d for d in ds.list_documents() if getattr(d, "run", "") in ("DONE", "3")]
        print(f"    ... {len(done)}/{len(doc_ids)} tayyor")
        if len(done) == len(doc_ids):
            break
    else:
        print("    OGOHLANTIRISH: parsing kutish vaqti tugadi, davom etamiz")

    # 4) Chat assistant
    print("[4] Chat assistant yaratilmoqda")
    assistant = rag.create_chat(name=f"chat-{name}", dataset_ids=[ds.id])
    session = assistant.create_session("test-session")

    # 5) Savol
    print(f"[5] Savol: {QUESTION}\n")
    answer = ""
    for chunk in session.ask(QUESTION, stream=True):
        answer = chunk.content
    print("JAVOB:\n" + answer)
    print("\n[OK] Test yakunlandi.")


if __name__ == "__main__":
    main()
