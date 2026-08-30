from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from services.database import get_db
from services.llm.client import LLMClient, LLMResponse
from services.llm.conversational_router import (
    ConversationalRouter,
    ConversationalRouteResponse,
)
from services.llm.supervisor import MultiAgentCoordinator, MultiAgentCoordinatorResponse
from services.llm.tools import run_tool_agent

router = APIRouter(prefix="/llm", tags=["LLM Gateway"])


# Request/Response schemas
class GenerateRequest(BaseModel):
    prompt: str = Field(..., description="Prompt message to send to the LLM")
    system_prompt: str | None = Field(None, description="Optional system instruction")
    temperature: float = Field(0.7, ge=0.0, le=2.0)


# Mock models for structured output testing
class MockParsedOrder(BaseModel):
    customer_name: str = Field(..., description="Name of the customer extracted")
    items: list[str] = Field(..., description="List of items in the order")
    total_price: float = Field(..., description="Total price calculated")


class MockParsedProduct(BaseModel):
    sku: str = Field(..., description="SKU identified")
    name: str = Field(..., description="Product name extracted")
    price: float = Field(..., description="Product price parsed")


class StructuredRequest(BaseModel):
    prompt: str = Field(
        ..., description="Prompt description containing the unstructured data to parse"
    )
    schema_type: str = Field(
        ..., description="Target parse schema, options: 'order', 'product'"
    )


llm = LLMClient()


@router.post("/generate", response_model=LLMResponse)
async def generate_text(payload: GenerateRequest):
    messages = []
    if payload.system_prompt:
        messages.append({"role": "system", "content": payload.system_prompt})
    messages.append({"role": "user", "content": payload.prompt})

    try:
        response = await llm.generate(
            messages=messages, temperature=payload.temperature
        )
        return response
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e)
        ) from e


@router.post("/structured", response_model=LLMResponse)
async def generate_structured(payload: StructuredRequest):
    messages = [
        {
            "role": "system",
            "content": "You are a precise data extractor. Extract attributes matching the requested schema format from the user content.",
        },
        {"role": "user", "content": payload.prompt},
    ]

    # Map dynamic target Pydantic schemas based on requested schema type
    if payload.schema_type.lower() == "order":
        response_model = MockParsedOrder
    elif payload.schema_type.lower() == "product":
        response_model = MockParsedProduct
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Schema type '{payload.schema_type}' is not supported. Choose 'order' or 'product'.",
        )

    try:
        response = await llm.generate(messages=messages, response_model=response_model)
        return response
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e)
        ) from e


class AssistantRequest(BaseModel):
    prompt: str = Field(
        ..., description="The user instructions for the shopping assistant"
    )
    customer_id: int | None = Field(
        None, description="Optional customer context ID for cart/checkout authorization"
    )


@router.post("/assistant", response_model=list[dict[str, Any]])
async def run_assistant(payload: AssistantRequest):
    try:
        conversation = await run_tool_agent(
            prompt=payload.prompt, customer_id=payload.customer_id
        )
        return conversation
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e)
        ) from e


@router.post("/conversational_route", response_model=ConversationalRouteResponse)
async def dispatch_conversational_route(
    payload: AssistantRequest, db: AsyncSession = Depends(get_db)
):
    router_agent = ConversationalRouter()
    try:
        response = await router_agent.route_query(
            query=payload.prompt, customer_id=payload.customer_id, db=db
        )
        return response
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e)
        ) from e


@router.post("/multi_agent_route", response_model=MultiAgentCoordinatorResponse)
async def dispatch_multi_agent_route(
    payload: AssistantRequest, db: AsyncSession = Depends(get_db)
):
    coordinator = MultiAgentCoordinator()
    try:
        response = await coordinator.coordinate(
            query=payload.prompt, customer_id=payload.customer_id, db=db
        )
        return response
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e)
        ) from e
