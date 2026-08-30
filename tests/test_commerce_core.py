from fastapi.testclient import TestClient

from apps.api.main import app

client = TestClient(app)


def test_health_check():
    # Verify server status
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_catalog_retrieval():
    # Fetch seeded categories
    response = client.get("/catalog/categories")
    assert response.status_code == 200
    categories = response.json()
    assert len(categories) > 0
    assert any(c["slug"] == "footwear" for c in categories)

    # Fetch seeded products
    response = client.get("/catalog/products")
    assert response.status_code == 200
    products = response.json()
    assert len(products) > 0
    assert any(p["sku"] == "SHOE-RUN-01" for p in products)


def test_e2e_checkout_flow():
    # 1. Create / Register customer
    customer_email = "test-buyer@example.com"
    customer_payload = {
        "email": customer_email,
        "name": "Integration Tester",
        "shipping_address": "456 Test Lane, QA Town, CO 80001",
    }
    response = client.post("/customers", json=customer_payload)
    if response.status_code == 400:
        # If user already registered by previous test, retrieve profile
        response = client.get(f"/customers/{customer_email}")
    assert response.status_code in [200, 201]
    customer = response.json()
    customer_id = customer["id"]

    # 2. Add SHOE-RUN-01 product to Redis Cart
    cart_payload = [{"sku": "SHOE-RUN-01", "quantity": 2}]
    response = client.post(f"/orders/cart/{customer_id}", json=cart_payload)
    assert response.status_code == 200
    cart = response.json()
    assert len(cart["items"]) == 1

    # 3. Check inventory quantities prior to checkout
    response = client.get("/inventory/SHOE-RUN-01")
    assert response.status_code == 200
    initial_inventory = response.json()
    initial_qty = initial_inventory["quantity"]
    initial_res = initial_inventory["reserved_quantity"]

    # 4. Perform order checkout
    checkout_payload = {
        "customer_id": customer_id,
        "shipping_address": "456 Test Lane, QA Town, CO 80001",
    }
    response = client.post("/orders/checkout", json=checkout_payload)
    assert response.status_code == 201
    order = response.json()
    assert order["status"] == "PENDING"
    assert order["total_amount"] == "179.98"  # 89.99 * 2 units
    order_id = order["id"]

    # 5. Verify inventory reservations (quantity remains, reserved increments)
    response = client.get("/inventory/SHOE-RUN-01")
    assert response.status_code == 200
    post_checkout_inventory = response.json()
    assert post_checkout_inventory["quantity"] == initial_qty
    assert post_checkout_inventory["reserved_quantity"] == initial_res + 2

    # 6. Charge transaction (Card ends with 9999 triggers transaction success)
    payment_payload = {
        "order_id": order_id,
        "payment_method": "Credit Card",
        "card_number": "1111-2222-3333-9999",
    }
    response = client.post("/payments/charge", json=payment_payload)
    assert response.status_code == 200
    txn = response.json()
    assert txn["status"] == "SUCCESS"

    # 7. Verify inventory deductions (physical quantity decreases, reservations return to normal)
    response = client.get("/inventory/SHOE-RUN-01")
    assert response.status_code == 200
    post_payment_inventory = response.json()
    assert post_payment_inventory["quantity"] == initial_qty - 2
    assert post_payment_inventory["reserved_quantity"] == initial_res

    # 8. Create Order shipment
    shipment_payload = {"order_id": order_id, "carrier": "DHL Express"}
    response = client.post("/shipping/ship", json=shipment_payload)
    assert response.status_code == 201
    shipment = response.json()
    assert shipment["status"] == "SHIPPED"
    tracking_number = shipment["tracking_number"]

    # 9. Trigger package delivery status change
    response = client.post(f"/shipping/{tracking_number}/delivery")
    assert response.status_code == 200
    delivered_shipment = response.json()
    assert delivered_shipment["status"] == "DELIVERED"

    # 10. Confirm Order moves to DELIVERED status
    response = client.get(f"/orders/{order_id}")
    assert response.status_code == 200
    final_order = response.json()
    assert final_order["status"] == "DELIVERED"
