from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from services.catalog.router import router as catalog_router
from services.customers.router import router as customers_router
from services.inventory.router import router as inventory_router
from services.orders.router import router as orders_router
from services.payments.router import router as payments_router
from services.shipping.router import router as shipping_router

app = FastAPI(
    title="Agentic Commerce Platform API",
    description="Deterministic backend modules for modular monolith development",
    version="1.0.0",
)

# Enable CORS for frontend applications integrations
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(catalog_router)
app.include_router(inventory_router)
app.include_router(customers_router)
app.include_router(orders_router)
app.include_router(payments_router)
app.include_router(shipping_router)


@app.get("/health", tags=["Health"])
async def health_check():
    return {
        "status": "healthy",
        "description": "Agentic Commerce Monolith Core is operational",
    }
