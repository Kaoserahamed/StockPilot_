from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.deps import Context, get_current_context
from app.core.logging_config import get_logger
from app.db.session import get_db
from app.models.party import Customer
from app.models.product import Product
from app.models.sales import Sale, SaleItem
from app.schemas.schemas import CheckoutRequest, SaleCancelRequest, SaleItemOut, SaleOut
from app.services.serializers import sale_to_out, sales_to_out

logger = get_logger(__name__)

router = APIRouter(tags=["sales"])
pos = APIRouter(prefix="/pos", tags=["pos"])
sales = APIRouter(prefix="/sales", tags=["sales"])


@pos.get("/search")
def pos_search(
    q: str,
    ctx: Context = Depends(get_current_context),
    db: Session = Depends(get_db),
    limit: int = Query(30, ge=1, le=100),
):
    """FR-11.2/11.3: POS product search by name/SKU/barcode (light columns)."""
    from sqlalchemy import or_

    like = f"%{q}%"
    rows = (
        db.query(
            Product.id,
            Product.name,
            Product.sku,
            Product.barcode,
            Product.selling_price,
            Product.quantity_on_hand,
        )
        .filter(
            Product.business_id == ctx.business_id,
            Product.is_active.is_(True),
            or_(Product.name.like(like), Product.sku.like(like), Product.barcode.like(like)),
        )
        .order_by(Product.name.asc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r[0],
            "name": r[1],
            "sku": r[2],
            "barcode": r[3],
            "selling_price": r[4],
            "quantity": r[5],
        }
        for r in rows
    ]


ALLOWED_METHODS = {"cash", "card", "mobile", "bank", "credit"}


@sales.post("/checkout", response_model=SaleOut, status_code=201)
def checkout(
    payload: CheckoutRequest,
    ctx: Context = Depends(get_current_context),
    db: Session = Depends(get_db),
):
    """FR-11 + FR-12: cart checkout -> sale + stock reduction + invoice number."""
    from datetime import datetime  # noqa
    from app.models.inventory import InventoryTransaction
    from app.services.audit import write_audit
    from app.services.invoice_service import next_invoice_no

    logger.info(
        "Processing checkout",
        extra={
            "business_id": ctx.business_id,
            "user_id": ctx.user.id,
            "items_count": len(payload.items),
            "payment_method": payload.payment_method,
        },
    )

    if ctx.role not in ("Owner", "Manager", "Cashier"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    method = (payload.payment_method or "cash").lower()
    if method not in ALLOWED_METHODS:
        raise HTTPException(status_code=422, detail=f"Invalid payment_method {method}")
    customer = None
    if payload.customer_id:
        customer = (
            db.query(Customer)
            .filter(Customer.id == payload.customer_id, Customer.business_id == ctx.business_id)
            .first()
        )
        if not customer:
            raise HTTPException(status_code=400, detail="Invalid customer")
    pids = [i.product_id for i in payload.items]
    products = {
        p.id: p
        for p in db.query(Product)
        .filter(Product.id.in_(pids), Product.business_id == ctx.business_id)
        .all()
    }
    if len(products) != len(set(pids)):
        raise HTTPException(status_code=400, detail="Invalid product in cart")
    lines = []
    subtotal = 0.0
    for i in payload.items:
        prod = products[i.product_id]
        if not prod.is_active:
            raise HTTPException(status_code=400, detail=f"Product inactive: {prod.name}")
        if (prod.quantity_on_hand or 0) < i.quantity:  # FR-11.7
            raise HTTPException(status_code=400, detail=f"Insufficient stock for {prod.name}")
        price = i.unit_price if i.unit_price is not None else (prod.selling_price or 0)
        if price < 0 or i.discount < 0:
            raise HTTPException(status_code=422, detail="Negative price/discount")
        line_total = i.quantity * price - i.discount
        if line_total < 0:
            raise HTTPException(status_code=422, detail="Line total negative")
        subtotal += line_total
        lines.append((prod, i.quantity, price, i.discount, line_total))
    disc = payload.discount_amount or 0
    taxable = max(0, subtotal - disc)
    tax = taxable * (payload.tax_percent or 0) / 100.0
    total = round(taxable + tax, 2)
    paid = total if payload.paid_amount is None else payload.paid_amount
    if paid < 0 or paid > total + 1e-9:
        raise HTTPException(status_code=422, detail="paid_amount must be 0..total")
    if method == "credit" and customer is None:
        raise HTTPException(status_code=422, detail="Credit sale needs a customer")
    pay_status = "paid" if paid >= total - 1e-9 else ("unpaid" if paid == 0 else "partial")
    inv = next_invoice_no(db, business_id=ctx.business_id)
    sale = Sale(
        business_id=ctx.business_id,
        invoice_no=inv,
        customer_id=customer.id if customer else None,
        subtotal=round(subtotal, 2),
        discount_amount=disc,
        tax_percent=payload.tax_percent or 0,
        tax_amount=round(tax, 2),
        total_amount=total,
        paid_amount=paid,
        payment_method=method,
        payment_status=pay_status,
        status="completed",
        sold_by=ctx.user.id,
    )
    db.add(sale)
    db.flush()
    for prod, qty, price, disc_i, line_total in lines:
        db.add(
            SaleItem(
                sale_id=sale.id,
                product_id=prod.id,
                quantity=qty,
                unit_price=price,
                discount=disc_i,
                line_total=round(line_total, 2),
            )
        )
        prod.quantity_on_hand -= qty
        db.add(
            InventoryTransaction(
                business_id=ctx.business_id,
                product_id=prod.id,
                quantity_change=-qty,
                tx_type="sale",
                reason=f"sale {inv}",
                user_id=ctx.user.id,
                related_id=f"sale:{sale.id}",
            )
        )
    if customer and total > paid:  # FR-7.5 customer outstanding on credit/partial
        customer.outstanding_balance = (customer.outstanding_balance or 0) + (total - paid)
    write_audit(
        db,
        business_id=ctx.business_id,
        user_id=ctx.user.id,
        action="sale.checkout",
        resource="sale",
        resource_id=str(sale.id),
        new_value=str(total),
    )
    db.commit()
    db.refresh(sale)
    
    logger.info(
        "Checkout completed",
        extra={
            "sale_id": sale.id,
            "invoice_no": sale.invoice_no,
            "total_amount": float(sale.total_amount),
            "business_id": ctx.business_id,
        },
    )
    
    return sale_to_out(db, sale)


@sales.get("", response_model=list[SaleOut])
def list_sales(
    ctx: Context = Depends(get_current_context),
    db: Session = Depends(get_db),
    customer_id: int | None = None,
    payment_status: str | None = None,
    limit: int = Query(50, ge=1, le=200),
):
    """FR-12.8: search/filter sales (batched, default 50 — not 200)."""
    from datetime import datetime  # noqa

    q = db.query(Sale).filter(Sale.business_id == ctx.business_id)
    if customer_id:
        q = q.filter(Sale.customer_id == customer_id)
    if payment_status:
        q = q.filter(Sale.payment_status == payment_status)
    rows = q.order_by(Sale.id.desc()).limit(limit).all()
    return sales_to_out(db, rows)


@sales.get("/{sale_id}", response_model=SaleOut)
def get_sale(
    sale_id: int, ctx: Context = Depends(get_current_context), db: Session = Depends(get_db)
):
    s = db.query(Sale).filter(Sale.id == sale_id, Sale.business_id == ctx.business_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Not found")
    return sale_to_out(db, s)


@sales.post("/{sale_id}/cancel", response_model=SaleOut)
def cancel_sale(
    sale_id: int,
    payload: SaleCancelRequest,
    ctx: Context = Depends(get_current_context),
    db: Session = Depends(get_db),
):
    """FR-27.3: cancel a sale -> restock non-returned qty, fix customer balance, audit."""
    from app.models.inventory import InventoryTransaction
    from app.models.party import Customer as _Customer
    from app.models.product import Product as _Product
    from app.services.audit import write_audit

    logger.info(
        "Cancelling sale",
        extra={
            "sale_id": sale_id,
            "reason": payload.reason,
            "business_id": ctx.business_id,
            "user_id": ctx.user.id,
        },
    )

    if ctx.role not in ("Owner", "Manager"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    s = db.query(Sale).filter(Sale.id == sale_id, Sale.business_id == ctx.business_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Not found")
    if s.status == "cancelled":
        return sale_to_out(db, s)
    items = db.query(SaleItem).filter(SaleItem.sale_id == s.id).all()
    net_paid = (s.total_amount or 0) - (s.refunded_amount or 0)
    for si in items:
        left = (si.quantity or 0) - (si.returned_qty or 0)
        if left > 0:
            prod = db.query(_Product).filter(_Product.id == si.product_id).first()
            if prod:
                prod.quantity_on_hand = (prod.quantity_on_hand or 0) + left
            db.add(
                InventoryTransaction(
                    business_id=ctx.business_id,
                    product_id=si.product_id,
                    quantity_change=left,
                    tx_type="sale",
                    reason=f"sale #{s.id} cancelled: {payload.reason}",
                    user_id=ctx.user.id,
                    related_id=f"sale:{s.id}",
                )
            )
            si.returned_qty = si.quantity
    if s.customer_id and net_paid > 0:
        cust = db.query(_Customer).filter(_Customer.id == s.customer_id).first()
        if cust:
            cust.outstanding_balance = max(0, (cust.outstanding_balance or 0) - net_paid)
    s.status = "cancelled"
    write_audit(
        db,
        business_id=ctx.business_id,
        user_id=ctx.user.id,
        action="sale.cancel",
        resource="sale",
        resource_id=str(s.id),
        new_value=payload.reason,
    )
    db.commit()
    db.refresh(s)
    return sale_to_out(db, s)


router.include_router(pos)
router.include_router(sales)
