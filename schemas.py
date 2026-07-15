from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator


class CreateTenantRequest(BaseModel):
    tenant_name: str = Field(..., description="Tenant/mijoz uchun unikal nom, masalan 'acme_corp'")


class CreateTenantResponse(BaseModel):
    tenant_name: str


class CreateAgentRequest(BaseModel):
    agent_name: str = Field(..., description="Agent nomi (tenant ichida unikal)")
    collections: list[str] = Field(
        ..., min_length=1, description="Agent foydalanadigan collection nomlari"
    )
    system_prompt: Optional[str] = Field(
        None, description="Agent uchun system prompt (persona)"
    )


class UpdateAgentRequest(BaseModel):
    agent_name: Optional[str] = None
    collections: Optional[list[str]] = Field(None, min_length=1)
    system_prompt: Optional[str] = None

    @model_validator(mode="after")
    def _at_least_one(self):
        if self.agent_name is None and self.collections is None and self.system_prompt is None:
            raise ValueError("kamida bitta maydon (agent_name/collections/system_prompt) berilishi kerak")
        return self


class AgentResponse(BaseModel):
    agent_id: str
    agent_name: str
    collections: list[str]
    system_prompt: Optional[str] = None
    ready: bool = False


class AskRequest(BaseModel):
    agent_id: str = Field(..., description="Qaysi agent bilan suhbat")
    user_id: str = Field(..., description="Foydalanuvchi identifikatori — session shu bo'yicha")
    query: str = Field(..., description="Foydalanuvchi savoli")


class AskResponse(BaseModel):
    agent_id: str
    session_id: str
    answer: str
    raw: dict


class HistoryMessage(BaseModel):
    role: str
    content: str
    reference: Optional[Any] = None
    created_at: str
