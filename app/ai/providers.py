from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, Field

from app.core.config import get_settings


class CriterionResult(BaseModel):
    criterion: str
    passed: bool | None
    evidence: list[str] = Field(default_factory=list)
    note: str


class VerificationReport(BaseModel):
    summary: str
    recommendation: str
    criteria: list[CriterionResult]
    missing_evidence: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    limitations: list[str]
    false_positive_risks: list[str]
    false_negative_risks: list[str]
    provider: str
    model: str
    policy_version: str = "verification-v1"


class AIProvider(Protocol):
    async def generate_structured(
        self, *, system: str, prompt: str, schema: type[BaseModel]
    ) -> BaseModel: ...


@dataclass
class DevelopmentAIProvider:
    """Deterministic local adapter; output is always labelled as development simulation."""

    async def generate_structured(
        self, *, system: str, prompt: str, schema: type[BaseModel]
    ) -> BaseModel:
        del system, prompt
        if schema is VerificationReport:
            return VerificationReport(
                summary="Development verification completed against supplied metadata.",
                recommendation="manual_review",
                criteria=[],
                confidence=0.35,
                limitations=["No external AI provider or file-analysis worker is configured."],
                false_positive_risks=["Metadata may not represent the actual deliverable."],
                false_negative_risks=["Valid evidence may require human interpretation."],
                provider="development-simulation",
                model="deterministic-stub",
            )
        if schema.__name__ == "DealSuggestionOut":
            return schema.model_validate(
                {
                    "title": "Structured service agreement",
                    "description": (
                        "Deliver the requested work through objective milestones with explicit "
                        "buyer acceptance and Arc testnet settlement."
                    ),
                    "suggested_total_amount": None,
                    "milestones": [
                        {
                            "title": "Plan and initial delivery",
                            "description": "Confirm scope and provide the first reviewable delivery.",
                            "percentage": 40,
                            "acceptance_criteria": [
                                "Scope is documented",
                                "Initial delivery is available for review",
                            ],
                        },
                        {
                            "title": "Final delivery",
                            "description": "Complete revisions and provide all final deliverables.",
                            "percentage": 60,
                            "acceptance_criteria": [
                                "All agreed deliverables are supplied",
                                "Buyer confirms the final acceptance criteria",
                            ],
                        },
                    ],
                    "assumptions": [
                        "Milestone values can be adjusted before the agreement is accepted.",
                        "AI suggestions are proposals and require explicit party approval.",
                    ],
                }
            )
        raise ValueError(f"Development adapter has no fixture for {schema.__name__}")


@dataclass
class OpenAIProvider:
    api_key: str
    model: str

    async def generate_structured(
        self, *, system: str, prompt: str, schema: type[BaseModel]
    ) -> BaseModel:
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(
                "https://api.openai.com/v1/responses",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "instructions": system,
                    "input": prompt,
                    "text": {
                        "format": {
                            "type": "json_schema",
                            "name": schema.__name__,
                            "strict": True,
                            "schema": schema.model_json_schema(),
                        }
                    },
                },
            )
            response.raise_for_status()
            body: dict[str, Any] = response.json()
            return schema.model_validate_json(body["output"][0]["content"][0]["text"])


@dataclass
class GeminiProvider:
    api_key: str
    model: str

    async def generate_structured(
        self, *, system: str, prompt: str, schema: type[BaseModel]
    ) -> BaseModel:
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent",
                headers={"x-goog-api-key": self.api_key},
                json={
                    "systemInstruction": {"parts": [{"text": system}]},
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "responseMimeType": "application/json",
                        "responseJsonSchema": schema.model_json_schema(),
                    },
                },
            )
            response.raise_for_status()
            body: dict[str, Any] = response.json()
            text = body["candidates"][0]["content"]["parts"][0]["text"]
            return schema.model_validate_json(text)


def get_ai_provider() -> AIProvider:
    settings = get_settings()
    if settings.ai_provider == "openai" and settings.openai_api_key:
        return OpenAIProvider(settings.openai_api_key, settings.openai_model)
    if settings.ai_provider == "gemini" and settings.gemini_api_key:
        return GeminiProvider(settings.gemini_api_key, settings.gemini_model)
    return DevelopmentAIProvider()
