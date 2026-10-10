"""Generic serialization helpers for API endpoints.

This module provides reusable batch-fetch-and-map helpers that eliminate N+1
query patterns in list endpoints while keeping single-object endpoints simple.

The pattern used here:
1. Single-object serializer: accepts one model, performs minimal queries
2. Batch serializer: accepts multiple models, batches all queries upfront

Why this matters: ``_sale_to_out`` in sales.py and ``_to_out`` in purchases.py
both performed N+1 queries on Product and Customer/Supplier. When an endpoint
returns 50 sales, that was 1 + 50 + 50 = 101 queries. The batch converters
reduce it to 1 + 3 = 4 fixed queries regardless of list size.

DataFactor flagged this as copy-paste logic that belongs in a shared layer.
"""

from __future__ import annotations

from typing import Generic, TypeVar

from sqlalchemy.orm import Session

from app.models.party import Customer, Supplier
from app.models.product import Product
from app.models.sales import Sale, SaleItem
from app.models.transactions import Purchase, PurchaseItem
from app.schemas.schemas import PurchaseItemOut, PurchaseOut, SaleItemOut, SaleOut

T = TypeVar("T")


class BatchFetcher(Generic[T]):
    """Helper to batch-fetch related entities and avoid N+1 queries."""

    def __init__(self, db: Session):
        self.db = db

    def fetch_products(self, product_ids: list[int]) -> dict[int, str]:
        """Return {product_id: product_name} for the given IDs."""
        if not product_ids:
            return {}
        products = self.db.query(Product).filter(Product.id.in_(product_ids)).all()
        return {p.id: p.name for p in products}

    def fetch_customers(self, customer_ids: list[int]) -> dict[int, str]:
        """Return {customer_id: customer_name} for the given IDs."""
        if not customer_ids:
            return {}
        customers = self.db.query(Customer).filter(Customer.id.in_(customer_ids)).all()
        return {c.id: c.name for c in customers}

    def fetch_suppliers(self, supplier_ids: list[int]) -> dict[int, Supplier]:
        """Return {supplier_id: Supplier} for the given IDs."""
        if not supplier_ids:
            return {}
        suppliers = self.db.query(Supplier).filter(Supplier.id.in_(supplier_ids)).all()
        return {s.id: s for s in suppliers}


def sale_to_out(db: Session, sale: Sale) -> SaleOut:
    """Convert a single Sale to SaleOut (may perform N+1 queries by design).

    Single-object endpoints reuse this; list endpoints should use
    ``sales_to_out`` instead to batch queries.
    """
    items = db.query(SaleItem).filter(SaleItem.sale_id == sale.id).all()
    product_ids = [i.product_id for i in items] or [0]
    product_names = {
        p.id: p.name for p in db.query(Product).filter(Product.id.in_(product_ids)).all()
    }

    customer_name = None
    if sale.customer_id:
        customer = db.query(Customer).filter(Customer.id == sale.customer_id).first()
        customer_name = customer.name if customer else None

    return SaleOut(
        id=sale.id,
        invoice_no=sale.invoice_no,
        customer_id=sale.customer_id,
        customer_name=customer_name,
        subtotal=sale.subtotal,
        discount_amount=sale.discount_amount,
        tax_percent=sale.tax_percent,
        tax_amount=sale.tax_amount,
        total_amount=sale.total_amount,
        paid_amount=sale.paid_amount,
        payment_method=sale.payment_method,
        payment_status=sale.payment_status,
        status=sale.status,
        created_at=sale.created_at,
        items=[
            SaleItemOut(
                id=item.id,
                product_id=item.product_id,
                product_name=product_names.get(item.product_id),
                quantity=item.quantity,
                unit_price=item.unit_price,
                discount=item.discount,
                line_total=item.line_total,
                returned_qty=item.returned_qty,
            )
            for item in items
        ],
    )


def sales_to_out(db: Session, sales: list[Sale]) -> list[SaleOut]:
    """Batch converter: fixed ~4 queries no matter how many sales are listed.

    This is the anti-N+1 pattern: fetch all items, products, and customers
    upfront, then assemble each SaleOut from the pre-fetched maps.
    """
    if not sales:
        return []

    sale_ids = [s.id for s in sales]
    items = (
        db.query(SaleItem)
        .filter(SaleItem.sale_id.in_(sale_ids))
        .order_by(SaleItem.sale_id, SaleItem.id)
        .all()
    )

    product_ids = list({i.product_id for i in items}) or [0]
    product_names = {
        p.id: p.name for p in db.query(Product).filter(Product.id.in_(product_ids)).all()
    }

    customer_ids = [s.customer_id for s in sales if s.customer_id] or [0]
    customer_names = {
        c.id: c.name for c in db.query(Customer).filter(Customer.id.in_(customer_ids)).all()
    }

    items_by_sale: dict[int, list[SaleItem]] = {}
    for item in items:
        items_by_sale.setdefault(item.sale_id, []).append(item)

    return [
        SaleOut(
            id=sale.id,
            invoice_no=sale.invoice_no,
            customer_id=sale.customer_id,
            customer_name=customer_names.get(sale.customer_id) if sale.customer_id else None,
            subtotal=sale.subtotal,
            discount_amount=sale.discount_amount,
            tax_percent=sale.tax_percent,
            tax_amount=sale.tax_amount,
            total_amount=sale.total_amount,
            paid_amount=sale.paid_amount,
            payment_method=sale.payment_method,
            payment_status=sale.payment_status,
            status=sale.status,
            created_at=sale.created_at,
            items=[
                SaleItemOut(
                    id=item.id,
                    product_id=item.product_id,
                    product_name=product_names.get(item.product_id),
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                    discount=item.discount,
                    line_total=item.line_total,
                    returned_qty=item.returned_qty,
                )
                for item in items_by_sale.get(sale.id, [])
            ],
        )
        for sale in sales
    ]


def purchase_to_out(db: Session, purchase: Purchase) -> PurchaseOut:
    """Convert a single Purchase to PurchaseOut (may perform N+1 queries by design).

    Single-object endpoints reuse this; list endpoints should use
    ``purchases_to_out`` instead to batch queries.
    """
    items = db.query(PurchaseItem).filter(PurchaseItem.purchase_id == purchase.id).all()
    product_ids = [i.product_id for i in items] or [0]
    product_names = {
        p.id: p.name for p in db.query(Product).filter(Product.id.in_(product_ids)).all()
    }

    supplier = db.query(Supplier).filter(Supplier.id == purchase.supplier_id).first()
    supplier_name = supplier.company_name if supplier else None

    return PurchaseOut(
        id=purchase.id,
        supplier_id=purchase.supplier_id,
        supplier_name=supplier_name,
        purchase_date=purchase.purchase_date,
        subtotal=purchase.subtotal,
        discount_amount=purchase.discount_amount,
        tax_amount=purchase.tax_amount,
        total_amount=purchase.total_amount,
        paid_amount=purchase.paid_amount,
        payment_status=purchase.payment_status,
        status=purchase.status,
        note=purchase.note,
        items=[
            PurchaseItemOut(
                id=item.id,
                product_id=item.product_id,
                product_name=product_names.get(item.product_id),
                quantity=item.quantity,
                unit_cost=item.unit_cost,
                line_total=item.line_total,
            )
            for item in items
        ],
    )


def purchases_to_out(db: Session, purchases: list[Purchase]) -> list[PurchaseOut]:
    """Batch converter: fixed ~4 queries regardless of list size.

    This is the anti-N+1 pattern: fetch all items, products, and suppliers
    upfront, then assemble each PurchaseOut from the pre-fetched maps.
    """
    if not purchases:
        return []

    purchase_ids = [p.id for p in purchases]
    items = (
        db.query(PurchaseItem)
        .filter(PurchaseItem.purchase_id.in_(purchase_ids))
        .order_by(PurchaseItem.purchase_id, PurchaseItem.id)
        .all()
    )

    product_ids = list({i.product_id for i in items}) or [0]
    product_names = {
        p.id: p.name for p in db.query(Product).filter(Product.id.in_(product_ids)).all()
    }

    supplier_ids = [p.supplier_id for p in purchases] or [0]
    suppliers = {s.id: s for s in db.query(Supplier).filter(Supplier.id.in_(supplier_ids)).all()}

    items_by_purchase: dict[int, list[PurchaseItem]] = {}
    for item in items:
        items_by_purchase.setdefault(item.purchase_id, []).append(item)

    return [
        PurchaseOut(
            id=purchase.id,
            supplier_id=purchase.supplier_id,
            supplier_name=(
                suppliers[purchase.supplier_id].company_name
                if purchase.supplier_id in suppliers
                else None
            ),
            purchase_date=purchase.purchase_date,
            subtotal=purchase.subtotal,
            discount_amount=purchase.discount_amount,
            tax_amount=purchase.tax_amount,
            total_amount=purchase.total_amount,
            paid_amount=purchase.paid_amount,
            payment_status=purchase.payment_status,
            status=purchase.status,
            note=purchase.note,
            items=[
                PurchaseItemOut(
                    id=item.id,
                    product_id=item.product_id,
                    product_name=product_names.get(item.product_id),
                    quantity=item.quantity,
                    unit_cost=item.unit_cost,
                    line_total=item.line_total,
                )
                for item in items_by_purchase.get(purchase.id, [])
            ],
        )
        for purchase in purchases
    ]
