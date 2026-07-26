import httpx
from fastapi import APIRouter, HTTPException, status
from pydantic import ValidationError

from app.ai.providers import get_ai_provider
from app.api.dependencies import CurrentUser
from app.api.schemas import DealSuggestionIn, DealSuggestionOut

router = APIRouter(prefix="/ai", tags=["ai"])


@router.post("/deal-suggestion", response_model=DealSuggestionOut)
async def suggest_deal(payload: DealSuggestionIn, user: CurrentUser) -> DealSuggestionOut:
    del user
    system = (
        "You are an agreement-structuring assistant. Produce clear milestone-based terms. "
        "Percentages must total exactly 100. If the user states a price, return "
        "suggested_total_amount in USDC base units (six decimals); otherwise return null. "
        "Suggestions never constitute party consent."
    )
    prompt = payload.prompt
    if payload.total_amount:
        prompt += f"\nThe proposed total is {payload.total_amount} base units of USDC."
    try:
        result = await get_ai_provider().generate_structured(
            system=system,
            prompt=prompt,
            schema=DealSuggestionOut,
        )
        suggestion = DealSuggestionOut.model_validate(result)
    except httpx.HTTPError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "The configured AI provider could not complete the suggestion",
        ) from exc
    except (ValidationError, ValueError, KeyError) as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "AI provider returned an invalid deal suggestion",
        ) from exc
    if sum(item.percentage for item in suggestion.milestones) != 100:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "AI milestone percentages must total 100",
        )
    return suggestion
