from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator


class CreateTenantRequest(BaseModel):
    tenant_name: str = Field(..., description="Tenant/mijoz uchun unikal nom, masalan 'acme_corp'")


class CreateTenantResponse(BaseModel):
    tenant_name: str


class SetPromptRequest(BaseModel):
    collection: Optional[str] = Field(
        None, description="Bitta collection nomi (yoki 'all')"
    )
    collections: Optional[list[str]] = Field(
        None, description="Bir nechta collection nomi (yoki ['all', ...])"
    )
    system_prompt: str = Field(..., description="Shu collection(lar) uchun system prompt")

    @model_validator(mode="after")
    def _one_target(self):
        if not self.collection and not self.collections:
            raise ValueError("collection yoki collections dan biri berilishi shart")
        if self.collection and self.collections:
            raise ValueError("collection va collections birga berilmasin")
        return self

    def targets(self) -> list[str]:
        return self.collections if self.collections else [self.collection]  # type: ignore


class AskRequest(BaseModel):
    tenant_name: str = Field(..., description="Qaysi tenant ostida savol berilyapti")
    collection: str = Field(..., description="Collection nomi yoki 'all' (majburiy)")
    user_id: str = Field(..., description="Foydalanuvchi identifikatori — session shu bo'yicha")
    question: str


class AskResponse(BaseModel):
    session_id: str
    scope: str
    answer: str
    raw: dict


class HistoryMessage(BaseModel):
    scope: str
    role: str
    content: str
    reference: Optional[Any] = None
    created_at: str
