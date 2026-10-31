from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from app.auth import CSRF, DB, USER
from app.models import OrderItem, Product, ScheduleOffer, User
from app.schemas import ProductInput, ProductList, ProductUpdate, ProductView
from app.security import utc_now

public_router = APIRouter(prefix="/api")
seller_router = APIRouter(prefix="/api/seller")


def current_seller(user: USER) -> User:
    """Anonymous visitors get 401 from the session check; buyers are refused here."""
    if user.role != "seller":
        raise HTTPException(status_code=403, detail="Seller access required")
    return user


SELLER = Annotated[User, Depends(current_seller)]


def active_products(db: DBSession) -> Sequence[Product]:
    return db.scalars(
        select(Product).where(Product.archived_at.is_(None)).order_by(Product.name, Product.id)
    ).all()


def no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


@public_router.get("/products", response_model=ProductList)
def list_public_products(db: DB, response: Response) -> ProductList:
    """Catalog for visitors. Archived products are not part of the public offer."""
    no_store(response)
    return ProductList(items=[ProductView.model_validate(p) for p in active_products(db)])


@public_router.get("/products/{product_id}", response_model=ProductView)
def read_public_product(product_id: int, db: DB, response: Response) -> ProductView:
    """Archived or missing products are indistinguishable to visitors."""
    product = db.get(Product, product_id)
    if product is None or product.archived:
        raise HTTPException(status_code=404, detail="Product not found")
    no_store(response)
    return ProductView.model_validate(product)


def find_product(db: DBSession, product_id: int) -> Product:
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


def referenced_by_offer(db: DBSession, product_id: int) -> bool:
    """Referenced products cannot be deleted; archiving keeps offers and snapshots."""
    return (
        db.scalar(
            select(ScheduleOffer.id).where(ScheduleOffer.product_id == product_id).limit(1)
        )
        is not None
    )


def referenced_by_order(db: DBSession, product_id: int) -> bool:
    return (
        db.scalar(select(OrderItem.id).where(OrderItem.product_id == product_id).limit(1))
        is not None
    )


def refuse_referenced_product(product_id: int, db: DBSession) -> None:
    if referenced_by_offer(db, product_id) or referenced_by_order(db, product_id):
        raise HTTPException(
            status_code=409,
            detail=(
                "Produk masih dipakai penawaran atau pesanan. Hapus penawaran yang "
                "belum dipesan terlebih dahulu; riwayat pesanan tidak boleh rusak."
            ),
        )


@seller_router.get("/products", response_model=ProductList)
def list_managed_products(_seller: SELLER, db: DB, response: Response) -> ProductList:
    """The seller sees archived rows too, active first, then by name."""
    rows = db.scalars(
        select(Product).order_by(
            Product.archived_at.is_not(None), Product.name, Product.id
        )
    ).all()
    no_store(response)
    return ProductList(items=[ProductView.model_validate(p) for p in rows])


@seller_router.post("/products", status_code=201, response_model=ProductView)
def create_product(
    payload: ProductInput, _seller: SELLER, _csrf: CSRF, db: DB, response: Response
) -> ProductView:
    # is_demo is server-owned: the catalog is synthetic data in this stage.
    product = Product(**payload.model_dump(), is_demo=True)
    db.add(product)
    db.commit()
    db.refresh(product)
    no_store(response)
    return ProductView.model_validate(product)


@seller_router.delete("/products/{product_id}", status_code=204)
def delete_product(
    product_id: int, _seller: SELLER, _csrf: CSRF, db: DB
) -> None:
    """Delete is only for products no schedule offer references. T5 adds the
    order-reference guard on top of this conflict rule."""
    product = find_product(db, product_id)
    refuse_referenced_product(product_id, db)
    db.delete(product)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=(
                "Produk masih dipakai penawaran jadwal. Hapus penawaran atau "
                "jadwalnya terlebih dahulu."
            ),
        ) from None


@seller_router.patch("/products/{product_id}", response_model=ProductView)
def update_product(
    product_id: int,
    payload: ProductUpdate,
    _seller: SELLER,
    _csrf: CSRF,
    db: DB,
    response: Response,
) -> ProductView:
    product = find_product(db, product_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(product, field, value)
    db.commit()
    db.refresh(product)
    no_store(response)
    return ProductView.model_validate(product)


@seller_router.post("/products/{product_id}/archive", response_model=ProductView)
def archive_product(
    product_id: int, _seller: SELLER, _csrf: CSRF, db: DB, response: Response
) -> ProductView:
    """Hide from the catalog without changing published offers or their references."""
    product = find_product(db, product_id)
    if product.archived_at is None:
        product.archived_at = utc_now()
        db.commit()
        db.refresh(product)
    no_store(response)
    return ProductView.model_validate(product)


@seller_router.post("/products/{product_id}/restore", response_model=ProductView)
def restore_product(
    product_id: int, _seller: SELLER, _csrf: CSRF, db: DB, response: Response
) -> ProductView:
    product = find_product(db, product_id)
    if product.archived_at is not None:
        product.archived_at = None
        db.commit()
        db.refresh(product)
    no_store(response)
    return ProductView.model_validate(product)
