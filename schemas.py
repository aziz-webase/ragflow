from typing import Optional

from pydantic import BaseModel, Field


class CreateTenantRequest(BaseModel):
    tenant_name: str = Field(..., description="Tenant/mijoz uchun unikal nom, masalan 'acme_corp'")
    description: Optional[str] = ""


class CreateTenantResponse(BaseModel):
    tenant_name: str
    dataset_id: str
    chat_id: Optional[str] = None


class ParseStatusResponse(BaseModel):
    document_id: str
    status: str


class AskRequest(BaseModel):
    tenant_name: str = Field(..., description="Qaysi tenant ostida savol berilyapti")
    user_id: str = Field(..., description="Foydalanuvchi identifikatori — shu bo'yicha session saqlanadi")
    question: str


class AskResponse(BaseModel):
    session_id: str
    answer: str
    raw: dict
