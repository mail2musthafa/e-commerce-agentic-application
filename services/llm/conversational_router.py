import logging
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from services.catalog.models import Product
from services.llm.client import LLMClient

logger = logging.getLogger("conversational_router")


class IntentClassification(BaseModel):
    intent: Literal["RAG", "CATALOG", "TRANSACTIONAL"] = Field(
        ...,
        description="Categorize query: RAG (policies/FAQ), CATALOG (browsing items), TRANSACTIONAL (cart actions)",
    )
    confidence: float = Field(..., description="Classification confidence (0.0 to 1.0)")
    reasoning: str = Field(
        ..., description="Explanation of why this intent category was chosen"
    )


class ConversationalRouteResponse(BaseModel):
    intent: str
    confidence: float
    reasoning: str
    response: dict[str, Any]


class ConversationalRouter:
    def __init__(self):
        self.llm = LLMClient()

    async def route_query(
        self, query: str, customer_id: int | None = None, db: AsyncSession = None
    ) -> ConversationalRouteResponse:
        """Classifies incoming query intent and dispatches execution logic to the appropriate sub-pipeline."""
        # 1. Classify intent via structured LLM zero-shot prompt
        system_prompt = (
            "You are an e-commerce routing classifier. Classify user queries into one of three categories:\n"
            "1. 'RAG': General questions about company returns, shipping rules, order delays, cancellations, and FAQ policies.\n"
            "2. 'CATALOG': Intentions to search, browse, describe, locate, or view items in the inventory/categories.\n"
            "3. 'TRANSACTIONAL': Actions requesting adding items to cart, viewing cart content, checking out, and making payments.\n"
            "Be precise and output structured JSON."
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query},
        ]

        classification = await self.llm.generate(
            messages=messages, response_model=IntentClassification
        )

        intent = classification.content.intent
        confidence = classification.content.confidence
        reasoning = classification.content.reasoning

        logger.info(
            f"Routed query '{query}' to intent '{intent}' (Confidence: {confidence})"
        )

        # 2. Dispatch execution
        exec_res = {}
        if intent == "RAG":
            from services.knowledge.agentic_rag import AgenticRAGPipeline

            pipeline = AgenticRAGPipeline()
            rag_res = await pipeline.execute(query, db)
            exec_res = {
                "answer": rag_res.answer,
                "used_chunks": rag_res.used_chunks,
                "steps": rag_res.steps,
            }

        elif intent == "CATALOG":
            # Match keywords in product names or descriptions
            words = [w.strip() for w in query.split() if len(w.strip()) > 2]
            filters = []
            if words:
                filters = [
                    or_(
                        Product.name.ilike(f"%{w}%"),
                        Product.description.ilike(f"%{w}%"),
                    )
                    for w in words
                ]

            stmt = select(Product)
            if filters:
                stmt = stmt.where(or_(*filters))
            stmt = stmt.limit(5)

            res = await db.execute(stmt)
            products = res.scalars().all()

            exec_res = {
                "products": [
                    {
                        "id": p.id,
                        "name": p.name,
                        "description": p.description,
                        "price": float(p.price),
                    }
                    for p in products
                ]
            }

        elif intent == "TRANSACTIONAL":
            from services.llm.tools import run_tool_agent

            cid = customer_id or 1  # Default to seeded customer 1
            tool_history = await run_tool_agent(query, customer_id=cid)
            exec_res = {"tool_execution_history": tool_history}

        else:
            exec_res = {"error": "Invalid intent routing output"}

        return ConversationalRouteResponse(
            intent=intent, confidence=confidence, reasoning=reasoning, response=exec_res
        )
