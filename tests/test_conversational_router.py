from fastapi.testclient import TestClient

from apps.api.main import app

client = TestClient(app)


def test_conversational_route_rag():
    payload = {"prompt": "What is your refund policy?", "customer_id": 1}
    response = client.post("/llm/conversational_route", json=payload)
    assert response.status_code == 200

    data = response.json()
    assert data["intent"] == "RAG"
    assert "answer" in data["response"]
    assert "used_chunks" in data["response"]


def test_conversational_route_catalog():
    payload = {"prompt": "Show me catalog product details", "customer_id": 1}
    response = client.post("/llm/conversational_route", json=payload)
    assert response.status_code == 200

    data = response.json()
    assert data["intent"] == "CATALOG"
    assert "products" in data["response"]


def test_conversational_route_transactional():
    payload = {"prompt": "Add this to my cart and checkout", "customer_id": 1}
    response = client.post("/llm/conversational_route", json=payload)
    assert response.status_code == 200

    data = response.json()
    assert data["intent"] == "TRANSACTIONAL"
    assert "tool_execution_history" in data["response"]
