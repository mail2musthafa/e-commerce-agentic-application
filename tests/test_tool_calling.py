import json

from fastapi.testclient import TestClient

from apps.api.main import app

client = TestClient(app)


def test_assistant_search_products_flow():
    # 1. Ask assistant to search products
    payload = {"prompt": "I want to search for shoes", "customer_id": 1}
    response = client.post("/llm/assistant", json=payload)
    assert response.status_code == 200

    conversation = response.json()
    assert (
        len(conversation) > 2
    )  # Includes user, assistant tool calls, tool results, final response

    # 2. Assert that the search_products tool was called and executed correctly
    tool_call_msg = next(
        m for m in conversation if m["role"] == "assistant" and "tool_calls" in m
    )
    assert tool_call_msg["tool_calls"][0]["function"]["name"] == "search_products"

    # 3. Assert the tool returned the real category/product information from our Postgres DB
    tool_result_msg = next(
        m
        for m in conversation
        if m["role"] == "tool" and m["name"] == "search_products"
    )
    content_data = json.loads(tool_result_msg["content"])
    assert "result" in content_data
    products_found = content_data["result"]
    assert len(products_found) > 0
    assert any(p["sku"] == "SHOE-RUN-01" for p in products_found)


def test_assistant_add_to_cart_flow():
    # Clear cart for user 1 before starting
    client.delete("/orders/cart/1")

    # 1. Ask assistant to add product to cart
    payload = {
        "prompt": "Please add one running shoe SHOE-RUN-01 to my cart",
        "customer_id": 1,
    }
    response = client.post("/llm/assistant", json=payload)
    assert response.status_code == 200

    # 2. Verify tool execution modified cart in Redis
    get_cart_res = client.get("/orders/cart/1")
    assert get_cart_res.status_code == 200
    cart_data = get_cart_res.json()
    assert len(cart_data["items"]) == 1
    assert cart_data["items"][0]["sku"] == "SHOE-RUN-01"


def test_assistant_checkout_flow():
    # 1. Setup cart with SHOE-RUN-01
    payload_cart = [{"sku": "SHOE-RUN-01", "quantity": 1}]
    client.post("/orders/cart/1", json=payload_cart)

    # 2. Ask assistant to checkout
    payload = {"prompt": "Please checkout my cart now", "customer_id": 1}
    response = client.post("/llm/assistant", json=payload)
    assert response.status_code == 200

    conversation = response.json()
    tool_result_msg = next(
        m for m in conversation if m["role"] == "tool" and m["name"] == "checkout_cart"
    )
    content_data = json.loads(tool_result_msg["content"])
    assert "result" in content_data
    checkout_result = content_data["result"]
    assert checkout_result["status"] == "success"
    assert "order_id" in checkout_result
    assert checkout_result["order_status"] == "PENDING"

    # 3. Verify order was created in Postgres database
    order_id = checkout_result["order_id"]
    get_order_res = client.get(f"/orders/{order_id}")
    assert get_order_res.status_code == 200
    assert get_order_res.json()["status"] == "PENDING"
