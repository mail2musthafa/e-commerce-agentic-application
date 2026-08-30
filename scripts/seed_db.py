import asyncio
from decimal import Decimal

from sqlalchemy.future import select

from services.catalog.models import Category, Product
from services.customers.models import Customer
from services.database import async_session
from services.inventory.models import InventoryItem


async def seed():
    async with async_session() as session:
        print("Seeding database...")

        # 1. Seed Categories
        categories_data = [
            {"name": "Electronics", "slug": "electronics"},
            {"name": "Apparel", "slug": "apparel"},
            {"name": "Footwear", "slug": "footwear"},
            {"name": "Home & Living", "slug": "home-living"},
        ]

        categories = {}
        for cat_data in categories_data:
            q = select(Category).where(Category.slug == cat_data["slug"])
            res = await session.execute(q)
            category = res.scalar_one_or_none()
            if not category:
                category = Category(name=cat_data["name"], slug=cat_data["slug"])
                session.add(category)
                await session.flush()  # To populate category.id
            categories[cat_data["slug"]] = category

        # 2. Seed Products & Warehouse Inventory levels
        products_data = [
            {
                "sku": "SHOE-RUN-01",
                "name": "Running Shoes",
                "description": "High performance lightweight running shoes",
                "price": Decimal("89.99"),
                "category_slug": "footwear",
            },
            {
                "sku": "ELEC-WHD-02",
                "name": "Wireless Headphones",
                "description": "Noise-cancelling over-ear wireless headphones",
                "price": Decimal("129.99"),
                "category_slug": "electronics",
            },
            {
                "sku": "APPR-TEE-03",
                "name": "Cotton T-Shirt",
                "description": "Comfortable 100% organic cotton daily wear t-shirt",
                "price": Decimal("19.99"),
                "category_slug": "apparel",
            },
            {
                "sku": "ELEC-SWA-04",
                "name": "Smart Watch",
                "description": "Sleek smart watch with health tracking sensors",
                "price": Decimal("199.99"),
                "category_slug": "electronics",
            },
        ]

        for prod_data in products_data:
            q = select(Product).where(Product.sku == prod_data["sku"])
            res = await session.execute(q)
            product = res.scalar_one_or_none()

            category = categories[prod_data["category_slug"]]

            if not product:
                product = Product(
                    sku=prod_data["sku"],
                    name=prod_data["name"],
                    description=prod_data["description"],
                    price=prod_data["price"],
                    category_id=category.id,
                )
                session.add(product)
                await session.flush()  # To populate product.id

            # Seed stock levels (50 units per item, 0 reserved)
            inv_q = select(InventoryItem).where(InventoryItem.product_id == product.id)
            inv_res = await session.execute(inv_q)
            inventory = inv_res.scalar_one_or_none()
            if not inventory:
                inventory = InventoryItem(
                    product_id=product.id,
                    sku=product.sku,
                    quantity=50,
                    reserved_quantity=0,
                    warehouse="Main Warehouse",
                )
                session.add(inventory)

        # 3. Seed Sample Customer profile
        cust_email = "musthafa@example.com"
        cust_q = select(Customer).where(Customer.email == cust_email)
        cust_res = await session.execute(cust_q)
        customer = cust_res.scalar_one_or_none()
        if not customer:
            customer = Customer(
                name="Musthafa Abeed",
                email=cust_email,
                shipping_address="123 Agentic Way, Silicon Valley, CA 94025",
            )
            session.add(customer)

        await session.commit()
        print("Database seeded successfully!")


if __name__ == "__main__":
    asyncio.run(seed())
