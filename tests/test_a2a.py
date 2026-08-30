from fastapi.testclient import TestClient

from apps.api.main import app

client = TestClient(app)


def test_a2a_negotiation_success():
    payload = {
        "sender": "ReturnAgent",
        "receiver": "InventoryAgent",
        "method": "request_restock",
        "params": {"sku": "SHOE-RUN-01", "quantity": 5},
        "id": "req-101",
    }
    response = client.post("/llm/a2a", json=payload)
    assert response.status_code == 200

    data = response.json()
    assert data["id"] == "req-101"
    assert data["result"]["status"] == "success"
    assert data["result"]["sku"] == "SHOE-RUN-01"
    assert data["result"]["new_quantity"] >= 5
    assert data["error"] is None


def test_a2a_negotiation_invalid_receiver():
    payload = {
        "sender": "ReturnAgent",
        "receiver": "ProcurementAgent",
        "method": "request_restock",
        "params": {"sku": "SHOE-RUN-01", "quantity": 5},
        "id": "req-102",
    }
    response = client.post("/llm/a2a", json=payload)
    assert response.status_code == 200

    data = response.json()
    assert data["id"] == "req-102"
    assert data["result"] is None
    assert "not registered" in data["error"]


def test_a2a_negotiation_invalid_method():
    payload = {
        "sender": "ReturnAgent",
        "receiver": "InventoryAgent",
        "method": "unknown_action",
        "params": {"sku": "SHOE-RUN-01", "quantity": 5},
        "id": "req-103",
    }
    response = client.post("/llm/a2a", json=payload)
    assert response.status_code == 200

    data = response.json()
    assert data["id"] == "req-103"
    assert data["result"] is None
    assert "not supported" in data["error"]
