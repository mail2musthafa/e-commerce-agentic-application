import logging
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from services.catalog.models import Product
from services.llm.client import LLMClient
from services.llm.moderation import SAFETY_BLOCKED_RESPONSE, check_moderation

logger = logging.getLogger("supervisor")


class SupervisorDecision(BaseModel):
    next_agent: Literal["SUPPORT", "SHOPPING", "ORDER", "FINISH"] = Field(
        ...,
        description="Specialized worker agent to delegate to, or FINISH if query resolved.",
    )
    reasoning: str = Field(
        ..., description="Explanation of why this routing choice was made."
    )


class MultiAgentCoordinatorResponse(BaseModel):
    agent_selected: str
    reasoning: str
    response: dict[str, Any]
    trajectory: list[str]


class MultiAgentCoordinator:
    def __init__(self):
        self.llm = LLMClient()

    async def coordinate(
        self, query: str, customer_id: int | None = None, db: AsyncSession = None
    ) -> MultiAgentCoordinatorResponse:
        """Evaluates query safety, runs supervisor routing selection, and delegates task to worker agents."""
        trajectory = []
        trajectory.append("Initiated Supervisor coordination check.")

        # 1. Run Input Safety Screening Guardrail
        safety = await check_moderation(query)
        if not safety.is_safe:
            trajectory.append("Input flagged unsafe by safety guardrails.")
            return MultiAgentCoordinatorResponse(
                agent_selected="SAFETY_BLOCKED",
                reasoning=f"Safety check blocked: {safety.reasoning}",
                response={"answer": SAFETY_BLOCKED_RESPONSE},
                trajectory=trajectory,
            )
        trajectory.append("Input verified safe by safety guardrails.")

        # 2. Select Specialized Worker Agent via Supervisor LLM step
        system_prompt = (
            "You are the Commerce Supervisor Coordinator. Choose the specialized worker agent to route to:\n"
            "- 'SUPPORT': Resolves return rules, shipping FAQ, cancellation and general policies (calls Agentic RAG).\n"
            "- 'SHOPPING': Handles browsing inventory, product details, comparing items, or cart inspection.\n"
            "- 'ORDER': Performs transactional cart checkouts, orders, or checking order details.\n"
            "- 'FINISH': Choose this if the request is already resolved, or needs a simple friendly answer.\n"
            "Analyze the conversation and output structured JSON."
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query},
        ]

        decision = await self.llm.generate(
            messages=messages, response_model=SupervisorDecision
        )
        agent = decision.content.next_agent
        reasoning = decision.content.reasoning
        trajectory.append(
            f"Supervisor routed query to specialized worker: {agent} (Reasoning: {reasoning})"
        )

        # 3. Delegate to worker agent execution
        exec_res = {}
        if agent == "SUPPORT":
            from services.knowledge.agentic_rag import AgenticRAGPipeline

            pipeline = AgenticRAGPipeline()
            rag_res = await pipeline.execute(query, db)
            exec_res = {
                "answer": rag_res.answer,
                "used_chunks": rag_res.used_chunks,
                "steps": rag_res.steps,
            }
            trajectory.append(
                "Support agent completed policy FAQ search via Agentic RAG."
            )

        elif agent == "SHOPPING":
            # Search catalog database
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
            trajectory.append(
                f"Shopping agent resolved catalog details matching keywords. Found {len(products)} products."
            )

        elif agent == "ORDER":
            from services.llm.tools import run_tool_agent

            cid = customer_id or 1
            tool_history = await run_tool_agent(query, customer_id=cid)
            exec_res = {"tool_execution_history": tool_history}
            trajectory.append(
                "Order agent executed e-commerce cart/checkout tool-calling workflow."
            )

        else:  # FINISH
            exec_res = {
                "answer": "I have processed your query. Let me know if you need anything else!"
            }
            trajectory.append(
                "Supervisor terminated routing loop with friendly response."
            )

        return MultiAgentCoordinatorResponse(
            agent_selected=agent,
            reasoning=reasoning,
            response=exec_res,
            trajectory=trajectory,
        )
