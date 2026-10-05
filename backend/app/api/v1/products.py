import os
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import Context, get_current_context
from app.db.session import get_db
from app.models.category import Category
from app.models.product import Product
from app.schemas.schemas import ProductCreate, ProductOut, ProductUpdate
from app.services.audit import write_audit
from app.services.authorization import require_write_access

router = APIRouter(prefix="/products", tags=["products"])


@router.get("", response_model=list[ProductOut])
def list_products(
    ctx: Context = Depends(get_current_context),
    db: Session = Depends(get_db),
    q: str | None = None,
    category_id: int | None = None,
    brand: str | None = None,
    low_stock: bool = False,
    out_of_stock: bool = False,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    query = db.query(Product).filter(Product.business_id == ctx.business_id)
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                Product.name.like(like),
                Product.sku.like(like),
                Product.barcode.like(like),
                Product.brand.like(like),
            )
        )
    if category_id:
        query = query.filter(Product.category_id == category_id)
    if brand:
        query = query.filter(Product.brand == brand)
    rows = query.order_by(Product.id.desc()).offset(offset).limit(limit).all()
    if out_of_stock:
        rows = [p for p in rows if (p.quantity_on_hand or 0) <= 0]
    elif low_stock:
        rows = [p for p in rows if (p.quantity_on_hand or 0) < (p.min_stock or 0)]
    return rows


@router.post("", response_model=ProductOut, status_code=201)
def create(
    payload: ProductCreate,
    ctx: Context = Depends(get_current_context),
    db: Session = Depends(get_db),
):
    require_write_access(ctx)
    from app.services import subscription_service as _subs

    _subs.check_can_add_product(db, ctx.business_id)
    if payload.category_id:
        cat = (
            db.query(Category)
            .filter(Category.id == payload.category_id, Category.business_id == ctx.business_id)
            .first()
        )
        if not cat:
            raise HTTPException(status_code=400, detail="Invalid category")
    data = payload.model_dump()
    # FR-5.7: treat empty barcode as NULL so multiple products without barcode
    # don't collide on the unique (business_id, barcode) constraint in MySQL.
    if not data.get("barcode"):
        data["barcode"] = None
    p = Product(business_id=ctx.business_id, **data)
    db.add(p)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Duplicate SKU or barcode in this business"
        ) from None
    db.refresh(p)
    return p


@router.get("/{pid}", response_model=ProductOut)
def get_one(pid: int, ctx: Context = Depends(get_current_context), db: Session = Depends(get_db)):
    p = db.query(Product).filter(Product.id == pid, Product.business_id == ctx.business_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Not found")
    return p


@router.patch("/{pid}", response_model=ProductOut)
def update(
    pid: int,
    payload: ProductUpdate,
    ctx: Context = Depends(get_current_context),
    db: Session = Depends(get_db),
):
    require_write_access(ctx)
    p = db.query(Product).filter(Product.id == pid, Product.business_id == ctx.business_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Not found")
    old_price = p.selling_price
    data = payload.model_dump(exclude_unset=True)
    if data.get("category_id"):
        cat = (
            db.query(Category)
            .filter(Category.id == data["category_id"], Category.business_id == ctx.business_id)
            .first()
        )
        if not cat:
            raise HTTPException(status_code=400, detail="Invalid category")
    for k, v in data.items():
        setattr(p, k, v)
    if "selling_price" in data and data["selling_price"] != old_price:
        write_audit(
            db,
            business_id=ctx.business_id,
            user_id=ctx.user.id,
            action="product.price_change",
            resource="product",
            resource_id=str(p.id),
            old_value=str(old_price),
            new_value=str(p.selling_price),
        )
    db.commit()
    db.refresh(p)
    return p


@router.post("/{pid}/deactivate", response_model=ProductOut)
def deactivate(
    pid: int, ctx: Context = Depends(get_current_context), db: Session = Depends(get_db)
):
    require_write_access(ctx)
    p = db.query(Product).filter(Product.id == pid, Product.business_id == ctx.business_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Not found")
    p.is_active = False
    write_audit(
        db,
        business_id=ctx.business_id,
        user_id=ctx.user.id,
        action="product.deactivate",
        resource="product",
        resource_id=str(p.id),
    )
    db.commit()
    db.refresh(p)
    return p


@router.post("/{pid}/activate", response_model=ProductOut)
def activate(pid: int, ctx: Context = Depends(get_current_context), db: Session = Depends(get_db)):
    """Re-activate a deactivated product (idempotent — activating an active
    product simply returns it unchanged)."""
    require_write_access(ctx)
    p = db.query(Product).filter(Product.id == pid, Product.business_id == ctx.business_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Not found")
    p.is_active = True
    write_audit(
        db,
        business_id=ctx.business_id,
        user_id=ctx.user.id,
        action="product.activate",
        resource="product",
        resource_id=str(p.id),
    )
    db.commit()
    db.refresh(p)
    return p


@router.post("/{pid}/image", response_model=ProductOut)
def upload_image(
    pid: int,
    file: UploadFile = File(...),
    ctx: Context = Depends(get_current_context),
    db: Session = Depends(get_db),
):
    require_write_access(ctx)
    p = db.query(Product).filter(Product.id == pid, Product.business_id == ctx.business_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Not found")
    dest_dir = os.path.join(settings.upload_dir, "products")
    os.makedirs(dest_dir, exist_ok=True)
    ext = os.path.splitext(file.filename or "")[1][:10]
    fname = f"{p.id}_{uuid.uuid4().hex}{ext}"
    path = os.path.join(dest_dir, fname)
    with open(path, "wb") as f:
        f.write(file.file.read())
    p.image_path = path
    db.commit()
    db.refresh(p)
    return p
