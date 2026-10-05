from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import Context, get_current_context
from app.db.session import get_db
from app.models.party import Customer, Supplier
from app.schemas.schemas import CustomerCreate, CustomerOut, SupplierCreate, SupplierOut
from app.services.authorization import require_write_or_cashier

router = APIRouter(tags=["parties"])


# ---- Suppliers FR-6 ----
sup = APIRouter(prefix="/suppliers", tags=["suppliers"])


@sup.get("", response_model=list[SupplierOut])
def list_sup(ctx: Context = Depends(get_current_context), db: Session = Depends(get_db)):
    return db.query(Supplier).filter(Supplier.business_id == ctx.business_id).all()


@sup.post("", response_model=SupplierOut, status_code=201)
def create_sup(
    payload: SupplierCreate,
    ctx: Context = Depends(get_current_context),
    db: Session = Depends(get_db),
):
    require_write_or_cashier(ctx)
    s = Supplier(business_id=ctx.business_id, **payload.model_dump())
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


@sup.patch("/{sid}", response_model=SupplierOut)
def update_sup(
    sid: int,
    payload: SupplierCreate,
    ctx: Context = Depends(get_current_context),
    db: Session = Depends(get_db),
):
    require_write_or_cashier(ctx)
    s = (
        db.query(Supplier)
        .filter(Supplier.id == sid, Supplier.business_id == ctx.business_id)
        .first()
    )
    if not s:
        raise HTTPException(status_code=404, detail="Not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(s, k, v)
    db.commit()
    db.refresh(s)
    return s


@sup.post("/{sid}/deactivate", response_model=SupplierOut)
def deact_sup(sid: int, ctx: Context = Depends(get_current_context), db: Session = Depends(get_db)):
    require_write_or_cashier(ctx)
    s = (
        db.query(Supplier)
        .filter(Supplier.id == sid, Supplier.business_id == ctx.business_id)
        .first()
    )
    if not s:
        raise HTTPException(status_code=404, detail="Not found")
    s.is_active = False
    db.commit()
    db.refresh(s)
    return s


@sup.get("/{sid}/purchases")
def sup_history(
    sid: int, ctx: Context = Depends(get_current_context), db: Session = Depends(get_db)
):
    from app.models.transactions import Purchase

    s = (
        db.query(Supplier)
        .filter(Supplier.id == sid, Supplier.business_id == ctx.business_id)
        .first()
    )
    if not s:
        raise HTTPException(status_code=404, detail="Not found")
    rows = (
        db.query(Purchase)
        .filter(Purchase.supplier_id == sid, Purchase.business_id == ctx.business_id)
        .order_by(Purchase.id.desc())
        .limit(200)
        .all()
    )
    return {
        "supplier_id": sid,
        "outstanding_balance": s.outstanding_balance,
        "purchases": [
            {
                "id": p.id,
                "total_amount": p.total_amount,
                "paid_amount": p.paid_amount,
                "payment_status": p.payment_status,
                "status": p.status,
                "purchase_date": p.purchase_date,
            }
            for p in rows
        ],
    }


# ---- Customers FR-7 ----
cust = APIRouter(prefix="/customers", tags=["customers"])


@cust.get("", response_model=list[CustomerOut])
def list_cust(ctx: Context = Depends(get_current_context), db: Session = Depends(get_db)):
    return db.query(Customer).filter(Customer.business_id == ctx.business_id).all()


@cust.post("", response_model=CustomerOut, status_code=201)
def create_cust(
    payload: CustomerCreate,
    ctx: Context = Depends(get_current_context),
    db: Session = Depends(get_db),
):
    require_write_or_cashier(ctx)
    c = Customer(business_id=ctx.business_id, **payload.model_dump())
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


@cust.patch("/{cid}", response_model=CustomerOut)
def update_cust(
    cid: int,
    payload: CustomerCreate,
    ctx: Context = Depends(get_current_context),
    db: Session = Depends(get_db),
):
    require_write_or_cashier(ctx)
    c = (
        db.query(Customer)
        .filter(Customer.id == cid, Customer.business_id == ctx.business_id)
        .first()
    )
    if not c:
        raise HTTPException(status_code=404, detail="Not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(c, k, v)
    db.commit()
    db.refresh(c)
    return c


@cust.get("/{cid}/sales")
def cust_history(
    cid: int, ctx: Context = Depends(get_current_context), db: Session = Depends(get_db)
):
    from app.models.sales import Sale

    c = (
        db.query(Customer)
        .filter(Customer.id == cid, Customer.business_id == ctx.business_id)
        .first()
    )
    if not c:
        raise HTTPException(status_code=404, detail="Not found")
    rows = (
        db.query(Sale)
        .filter(Sale.customer_id == cid, Sale.business_id == ctx.business_id)
        .order_by(Sale.id.desc())
        .limit(200)
        .all()
    )
    return {
        "customer_id": cid,
        "outstanding_balance": c.outstanding_balance,
        "sales": [
            {
                "id": s.id,
                "invoice_no": s.invoice_no,
                "total_amount": s.total_amount,
                "paid_amount": s.paid_amount,
                "payment_status": s.payment_status,
                "status": s.status,
                "created_at": s.created_at,
            }
            for s in rows
        ],
    }


router.include_router(sup)
router.include_router(cust)
