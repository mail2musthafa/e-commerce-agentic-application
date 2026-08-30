from fastapi.testclient import TestClient

from apps.api.main import app

client = TestClient(app)


def test_llm_generate_text():
    # Verify basic text generation endpoint
    payload = {
        "prompt": "Say hello world",
        "system_prompt": "You are a helpful assistant",
        "temperature": 0.5,
    }
    response = client.post("/llm/generate", json=payload)
    assert response.status_code == 200

    data = response.json()
    assert "content" in data
    assert "model_used" in data
    assert data["prompt_tokens"] > 0
    assert data["cost_usd"] >= 0.0
    assert data["latency_sec"] >= 0.0


def test_llm_generate_structured_order():
    # Verify Pydantic structured output mapping for 'order' schema type
    payload = {
        "prompt": "Order received from Musthafa for 2 running shoes and 1 watch. Total is $380.",
        "schema_type": "order",
    }
    response = client.post("/llm/structured", json=payload)
    assert response.status_code == 200

    data = response.json()
    assert "content" in data
    content = data["content"]
    assert "customer_name" in content
    assert "items" in content
    assert "total_price" in content


def test_llm_generate_structured_product():
    # Verify Pydantic structured output mapping for 'product' schema type
    payload = {
        "prompt": "Add product Shoe-Runner-99 named Sporty Shoes costing 79.99.",
        "schema_type": "product",
    }
    response = client.post("/llm/structured", json=payload)
    assert response.status_code == 200

    data = response.json()
    assert "content" in data
    content = data["content"]
    assert "sku" in content
    assert "name" in content
    assert "price" in content


def test_llm_generate_structured_invalid_schema():
    # Verify error validation for unsupported schema type requests
    payload = {"prompt": "Some text", "schema_type": "invalid_schema"}
    response = client.post("/llm/structured", json=payload)
    assert response.status_code == 400
    assert "not supported" in response.json()["detail"]
