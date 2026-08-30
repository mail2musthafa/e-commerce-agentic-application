from fastapi.testclient import TestClient

from apps.api.main import app
from services.memory.service import truncate_messages

client = TestClient(app)


def test_session_memory_lifecycle():
    session_id = "test_session_999"

    # 0. Clean session before test
    delete_response = client.delete(f"/memory/session/{session_id}")
    assert delete_response.status_code == 200

    # 1. Verify history starts empty
    get_response = client.get(f"/memory/session/{session_id}")
    assert get_response.status_code == 200
    assert len(get_response.json()["messages"]) == 0

    # 2. Add message 1 (User)
    msg1 = {"role": "user", "content": "Hello! I have a question about my order."}
    response1 = client.post(f"/memory/session/{session_id}/message", json=msg1)
    assert response1.status_code == 201

    # 3. Add message 2 (Assistant)
    msg2 = {
        "role": "assistant",
        "content": "Sure, I can help. What is your order number?",
    }
    response2 = client.post(f"/memory/session/{session_id}/message", json=msg2)
    assert response2.status_code == 201

    # 4. Fetch history and assert order
    history_response = client.get(f"/memory/session/{session_id}")
    assert history_response.status_code == 200
    history = history_response.json()["messages"]
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[0]["content"] == msg1["content"]
    assert history[1]["role"] == "assistant"
    assert history[1]["content"] == msg2["content"]

    # 5. Clear history and verify empty
    clear_response = client.delete(f"/memory/session/{session_id}")
    assert clear_response.status_code == 200

    final_response = client.get(f"/memory/session/{session_id}")
    assert len(final_response.json()["messages"]) == 0


def test_context_truncation_logic():
    # Construct message array exceeding limits
    # Approximate tokens calculation is: characters / 4
    messages = [
        {
            "role": "system",
            "content": "You are a helpful assistant.",
        },  # 28 chars -> ~7 tokens
        {
            "role": "user",
            "content": "A very long message description...",
        },  # 35 chars -> ~8 tokens
        {"role": "assistant", "content": "Short reply."},  # 12 chars -> ~3 tokens
        {"role": "user", "content": "Final question."},  # 15 chars -> ~3 tokens
    ]

    # Prune to max_tokens = 15
    # Total tokens = 7 + 8 + 3 + 3 = 21 tokens
    # Removing oldest (A very long message...): remaining tokens = 7 (system) + 3 + 3 = 13 tokens (<= 15 tokens)
    truncated = truncate_messages(messages, max_tokens=15)

    assert len(truncated) == 3
    # Check that system prompt is preserved at index 0
    assert truncated[0]["role"] == "system"
    # Check that oldest user message was pruned
    assert truncated[1]["role"] == "assistant"
    assert truncated[2]["role"] == "user"
    assert truncated[2]["content"] == "Final question."
