import asyncio
import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import Any

import redis.asyncio as redis
from sqlalchemy.future import select

from services.catalog.models import Category, Product
from services.customers.models import Customer
from services.database import async_session, redis_client
from services.inventory.models import InventoryItem
from services.llm.client import LLMClient
from services.orders.models import Order, OrderItem

logger = logging.getLogger("llm_tools")


# Helper context manager to get isolated redis connections during testing
@asynccontextmanager
async def get_redis_ctx():
    is_testing = "pytest" in sys.modules or os.getenv("TESTING") == "1"
    if is_testing:
        client = redis.from_url(
            os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True
        )
        try:
            yield client
        finally:
            await client.aclose()
    else:
        yield redis_client


# Helper to format redis cart keys
def get_cart_key(customer_id: int) -> str:
    return f"cart:{customer_id}"


# 1. LiteLLM/OpenAI-compatible tool definitions
tools_schema = [
    {
        "type": "function",
        "function": {
            "name": "search_products",
            "description": "Search the product catalog for items matching a text query or category slug.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search term or keyword (e.g. 'shoes')",
                    },
                    "category_slug": {
                        "type": "string",
                        "description": "Optional category slug (e.g. 'footwear')",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_product_details",
            "description": "Get detailed pricing and warehouse stock levels for a product by its unique SKU.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sku": {
                        "type": "string",
                        "description": "The unique product SKU (e.g. 'SHOE-RUN-01')",
                    }
                },
                "required": ["sku"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_cart",
            "description": "Retrieve the current shopping cart items for a customer.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_id": {
                        "type": "integer",
                        "description": "The unique customer ID",
                    }
                },
                "required": ["customer_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_to_cart",
            "description": "Add one or more units of a product to a customer's shopping cart.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_id": {
                        "type": "integer",
                        "description": "The unique customer ID",
                    },
                    "sku": {"type": "string", "description": "The product SKU to add"},
                    "quantity": {
                        "type": "integer",
                        "description": "The quantity of items to add",
                    },
                },
                "required": ["customer_id", "sku", "quantity"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "checkout_cart",
            "description": "Submit a checkout request to convert the customer's cart into a pending order.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_id": {
                        "type": "integer",
                        "description": "The unique customer ID",
                    },
                    "shipping_address": {
                        "type": "string",
                        "description": "The shipping address for delivery",
                    },
                },
                "required": ["customer_id", "shipping_address"],
            },
        },
    },
]


# 2. Database implementation logic for each tool
async def search_products(
    query: str | None = None, category_slug: str | None = None
) -> list[dict]:
    async with async_session() as db:
        stmt = select(Product)
        if category_slug:
            stmt = stmt.join(Category).where(Category.slug == category_slug)
        if query:
            stmt = stmt.where(
                Product.name.ilike(f"%{query}%")
                | Product.description.ilike(f"%{query}%")
            )

        res = await db.execute(stmt)
        products = res.scalars().all()
        return [
            {
                "sku": p.sku,
                "name": p.name,
                "price": float(p.price),
                "description": p.description,
            }
            for p in products
        ]


async def get_product_details(sku: str) -> dict:
    async with async_session() as db:
        stmt = select(Product).where(Product.sku == sku)
        res = await db.execute(stmt)
        product = res.scalar_one_or_none()
        if not product:
            return {"error": f"Product with SKU '{sku}' not found."}

        inv_stmt = select(InventoryItem).where(InventoryItem.product_id == product.id)
        inv_res = await db.execute(inv_stmt)
        inventory = inv_res.scalar_one_or_none()

        return {
            "sku": product.sku,
            "name": product.name,
            "price": float(product.price),
            "description": product.description,
            "stock_quantity": inventory.quantity if inventory else 0,
            "reserved_quantity": inventory.reserved_quantity if inventory else 0,
            "available_quantity": inventory.available_quantity if inventory else 0,
        }


async def get_cart(customer_id: int) -> dict:
    async with get_redis_ctx() as r:
        raw_cart = await r.get(get_cart_key(customer_id))
        if not raw_cart:
            return {"customer_id": customer_id, "items": []}
        return {"customer_id": customer_id, "items": json.loads(raw_cart)}


async def add_to_cart(customer_id: int, sku: str, quantity: int) -> dict:
    async with async_session() as db:
        stmt = select(Product).where(Product.sku == sku)
        res = await db.execute(stmt)
        product = res.scalar_one_or_none()
        if not product:
            return {"error": f"Product with SKU '{sku}' not found."}

    cart = await get_cart(customer_id)
    items = cart["items"]

    found = False
    for item in items:
        if item["sku"] == sku:
            item["quantity"] += quantity
            found = True
            break
    if not found:
        items.append({"sku": sku, "quantity": quantity})

    async with get_redis_ctx() as r:
        await r.set(get_cart_key(customer_id), json.dumps(items))
    return {"status": "success", "cart": items}


async def checkout_cart(customer_id: int, shipping_address: str) -> dict:
    async with async_session() as db:
        # Verify Customer
        cust_query = select(Customer).where(Customer.id == customer_id)
        cust_res = await db.execute(cust_query)
        customer = cust_res.scalar_one_or_none()
        if not customer:
            return {"error": f"Customer with ID {customer_id} not found."}

        cart = await get_cart(customer_id)
        cart_items = cart["items"]
        if not cart_items:
            return {"error": "Shopping cart is empty."}

        order_items_to_create = []
        total_amount = 0

        for item in cart_items:
            prod_query = select(Product).where(Product.sku == item["sku"])
            prod_res = await db.execute(prod_query)
            product = prod_res.scalar_one_or_none()
            if not product:
                return {"error": f"Product with SKU '{item['sku']}' not found."}

            inv_query = select(InventoryItem).where(
                InventoryItem.product_id == product.id
            )
            inv_res = await db.execute(inv_query)
            inventory = inv_res.scalar_one_or_none()
            if not inventory or inventory.available_quantity < item["quantity"]:
                available = inventory.available_quantity if inventory else 0
                return {
                    "error": f"Insufficient inventory for SKU '{item['sku']}'. Available: {available}."
                }

            inventory.reserved_quantity += item["quantity"]

            item_total = product.price * item["quantity"]
            total_amount += item_total

            order_items_to_create.append(
                OrderItem(
                    product_id=product.id,
                    quantity=item["quantity"],
                    unit_price=product.price,
                )
            )

        order = Order(
            customer_id=customer_id,
            status="PENDING",
            total_amount=total_amount,
            shipping_address=shipping_address,
            items=order_items_to_create,
        )
        db.add(order)
        await db.commit()

        async with get_redis_ctx() as r:
            await r.delete(get_cart_key(customer_id))

        return {
            "status": "success",
            "order_id": str(order.id),
            "total_amount": float(total_amount),
            "order_status": order.status,
        }


# 3. Execution dispatcher
async def execute_tool(name: str, args: dict) -> dict:
    try:
        if name == "search_products":
            return {
                "result": await search_products(
                    query=args.get("query"), category_slug=args.get("category_slug")
                )
            }
        elif name == "get_product_details":
            return {"result": await get_product_details(sku=args["sku"])}
        elif name == "get_cart":
            return {"result": await get_cart(customer_id=int(args["customer_id"]))}
        elif name == "add_to_cart":
            return {
                "result": await add_to_cart(
                    customer_id=int(args["customer_id"]),
                    sku=args["sku"],
                    quantity=int(args["quantity"]),
                )
            }
        elif name == "checkout_cart":
            return {
                "result": await checkout_cart(
                    customer_id=int(args["customer_id"]),
                    shipping_address=args["shipping_address"],
                )
            }
        else:
            return {"error": f"Tool '{name}' is not supported."}
    except KeyError as e:
        return {"error": f"Missing required parameter '{e.args[0]}' for tool '{name}'."}
    except Exception as e:
        return {"error": f"Tool execution failed: {str(e)}"}


# 4. Multi-turn Agentic tool calling loop runner
async def run_tool_agent(
    prompt: str, customer_id: int | None = None
) -> list[dict[str, Any]]:
    client = LLMClient()
    messages = [
        {
            "role": "system",
            "content": (
                "You are an intelligent shopping assistant for the Agentic Commerce Platform. "
                "You can search products, manage the cart, and checkout orders using tools. "
                "Always run tools in parallel when applicable."
            ),
        },
        {"role": "user", "content": prompt},
    ]

    for _ in range(5):  # Loop max 5 turns to prevent infinite tool call loops
        response = await client.generate_raw(
            messages=messages, tools=tools_schema, tool_choice="auto"
        )

        message = response.choices[0].message
        tool_calls = getattr(message, "tool_calls", None)

        # If no tool calls, the model returned a final text response
        if not tool_calls:
            messages.append({"role": "assistant", "content": message.content})
            break

        # Append the assistant message containing the tool calls
        messages.append(message.model_dump(exclude_none=True))

        # Dispatch and execute tools in parallel
        tasks = []
        for tc in tool_calls:
            func_name = tc.function.name
            try:
                args = json.loads(tc.function.arguments)
            except Exception:
                args = {}

            # Authorise using context customer_id if parameter calls for it
            if "customer_id" in args and customer_id is not None:
                args["customer_id"] = customer_id

            tasks.append((tc.id, func_name, execute_tool(func_name, args)))

        # Gather parallel tool executions
        results = await asyncio.gather(*(task[2] for task in tasks))

        # Append each tool result back to the conversation logs
        for (tc_id, func_name, _), result in zip(tasks, results, strict=False):
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "name": func_name,
                    "content": json.dumps(result),
                }
            )

    return messages
