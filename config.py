import os
from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # RAGFlow serveringizning manzili (ngrok yoki to'g'ridan-to'g'ri IP:9380)
    ragflow_base_url: str = os.getenv("RAGFLOW_BASE_URL", "http://83.69.136.41:9380")

    # RAGFlow'dan olingan API key (Bearer token)
    ragflow_api_key: str = os.getenv("RAGFLOW_API_KEY", "")

    # Default LLM model nomi (Model Providers'da ko'rgan nom bilan bir xil)
    default_llm_id: str = os.getenv("DEFAULT_LLM_ID", "gemma-4-31B-it@rag-llm@OpenAI-API-Compatible")

    # PostgreSQL ulanish satri (asyncpg drayveri uchun)
    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql://ragflow:ragflow@127.0.0.1:5432/ragflow_wrapper",
    )

    # RAG retrieval sozlamalari (RAGFlow chat assistant prompt_config)
    # top_n past bo'lsa kerakli chunk kesilib qoladi; keyword og'irligi past bo'lsa
    # cross-lingual (savol bir tilda, hujjat boshqa tilda) qidiruv yaxshilanadi.
    rag_top_n: int = int(os.getenv("RAG_TOP_N", "12"))
    rag_similarity_threshold: float = float(os.getenv("RAG_SIMILARITY_THRESHOLD", "0.1"))
    rag_keywords_weight: float = float(os.getenv("RAG_KEYWORDS_WEIGHT", "0.2"))

    # Rerank model (RAGFlow'da sozlangan). Bo'sh bo'lsa rerank ishlatilmaydi.
    # Masalan: "BAAI/bge-reranker-v2-m3@HuggingFace"
    rag_rerank_id: str = os.getenv("RAG_RERANK_ID", "")

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()
