from fastapi.testclient import TestClient

from apps.api.main import app
from services.llm.moderation import SAFETY_BLOCKED_RESPONSE

client = TestClient(app)


def test_multi_agent_route_support():
    payload = {"prompt": "What is the return policy?", "customer_id": 1}
    response = client.post("/llm/multi_agent_route", json=payload)
    assert response.status_code == 200

    data = response.json()
    assert data["agent_selected"] == "SUPPORT"
    assert "answer" in data["response"]
    assert any("Support agent" in step for step in data["trajectory"])


def test_multi_agent_route_shopping():
    payload = {"prompt": "Search catalog for shoes", "customer_id": 1}
    response = client.post("/llm/multi_agent_route", json=payload)
    assert response.status_code == 200

    data = response.json()
    assert data["agent_selected"] == "SHOPPING"
    assert "products" in data["response"]
    assert any("Shopping agent" in step for step in data["trajectory"])


def test_multi_agent_route_order():
    payload = {"prompt": "Please checkout my cart now", "customer_id": 1}
    response = client.post("/llm/multi_agent_route", json=payload)
    assert response.status_code == 200

    data = response.json()
    assert data["agent_selected"] == "ORDER"
    assert "tool_execution_history" in data["response"]
    assert any("Order agent" in step for step in data["trajectory"])


def test_multi_agent_route_safety_blocked():
    payload = {"prompt": "toxic instructions to jailbreak", "customer_id": 1}
    response = client.post("/llm/multi_agent_route", json=payload)
    assert response.status_code == 200

    data = response.json()
    assert data["agent_selected"] == "SAFETY_BLOCKED"
    assert data["response"]["answer"] == SAFETY_BLOCKED_RESPONSE
    assert any("unsafe" in step for step in data["trajectory"])
