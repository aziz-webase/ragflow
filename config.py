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

    # Har bir tenant uchun mapping ma'lumotlarini saqlaydigan sqlite fayl
    db_path: str = os.getenv("DB_PATH", "./ragflow_mapping.db")

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()
