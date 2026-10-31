from datetime import datetime

from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession
from sqlalchemy.orm import selectinload

from app.allocations import allocated_quantities, allocated_totals
from app.auth import CSRF, DB
from app.catalog import SELLER, no_store
from app.models import Order, OrderItem, Product, Schedule, ScheduleOffer
from app.schemas import (
    OfferInput,
    OfferUpdate,
    OfferView,
    ScheduleArchiveInput,
    ScheduleCreate,
    ScheduleList,
    ScheduleUpdate,
    ScheduleView,
)

public_router = APIRouter(prefix="/api")
seller_router = APIRouter(prefix="/api/seller")

# An archived schedule is history: its orders must already be finished. Only a
# completed handoff or a cancellation keeps quota and recap facts final, so a
# still-live order blocks archiving instead of being hidden.
ARCHIVED_ORDER_STATUSES = ("selesai", "batal")
ARCHIVE_REFUSAL = (
    "Jadwal ini masih memiliki pesanan yang belum selesai atau belum batal. "
    "Selesaikan atau batalkan pesanan lewat alurnya sendiri; arsip tidak "
    "mengubah status atau dana."
)
ARCHIVED_READ_ONLY = (
    "Jadwal ini diarsipkan. Pulihkan dulu sebelum mengubah waktu, penawaran, "
    "atau menghapus jadwal."
)


def _offer_view(offer: ScheduleOffer, allocated: int) -> OfferView:
    return OfferView(
        id=offer.id,
        product_id=offer.product_id,
        product_name=offer.product_name,
        selling_unit=offer.selling_unit,
        price_rupiah=offer.price_rupiah,
        quota=offer.quota,
        allocated_quantity=allocated,
        remaining_quota=offer.quota - allocated,
    )


def _schedule_view(
    schedule: Schedule, now: datetime, allocated: dict[int, int] | None = None
) -> ScheduleView:
    allocated = allocated or {}
    return ScheduleView(
        id=schedule.id,
        pickup_at=schedule.pickup_at,
        order_cutoff_at=schedule.order_cutoff_at,
        # Exact equality is closed: the shared cutoff has passed. An archived
        # schedule never accepts a new checkout, even from a stale client.
        orders_open=now < schedule.order_cutoff_at and not schedule.archived,
        archived=schedule.archived,
        offers=[
            _offer_view(offer, allocated.get(offer.id, 0)) for offer in schedule.offers
        ],
    )


def find_schedule(db: DBSession, schedule_id: int) -> Schedule:
    schedule = db.scalar(
        select(Schedule)
        .options(selectinload(Schedule.offers))
        .where(Schedule.id == schedule_id)
    )
    if schedule is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return schedule


def schedule_has_orders(db: DBSession, schedule_id: int) -> bool:
    """Any order row, including a later cancelled one, keeps history referenced.

    This is a locking read: the seller request may have waited on the schedule
    lock while a checkout committed, and a REPEATABLE READ snapshot from before
    the wait must not hide that new order.
    """
    return (
        db.scalar(
            select(Order.id)
            .where(Order.schedule_id == schedule_id)
            .limit(1)
            .with_for_update()
        )
        is not None
    )


def offer_has_orders(db: DBSession, offer_id: int) -> bool:
    return (
        db.scalar(
            select(OrderItem.id)
            .where(OrderItem.offer_id == offer_id)
            .limit(1)
            .with_for_update()
        )
        is not None
    )


def lock_schedule(db: DBSession, schedule_id: int) -> Schedule:
    """Serialize every checkout-affecting mutation on the same schedule row."""
    schedule = db.scalar(
        select(Schedule).where(Schedule.id == schedule_id).with_for_update()
    )
    if schedule is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return schedule


def lock_offer(db: DBSession, schedule_id: int, offer_id: int) -> ScheduleOffer:
    offer = db.scalar(
        select(ScheduleOffer)
        .where(ScheduleOffer.id == offer_id, ScheduleOffer.schedule_id == schedule_id)
        .with_for_update()
    )
    if offer is None:
        raise HTTPException(status_code=404, detail="Offer not found")
    return offer


def refuse_archived_schedule(schedule: Schedule) -> None:
    """Archived schedules are read-only until the seller restores them."""
    if schedule.archived:
        raise HTTPException(status_code=409, detail=ARCHIVED_READ_ONLY)


def schedule_orders_are_terminal(db: DBSession, schedule_id: int) -> bool:
    """Locking check that every order on this schedule is selesai or batal."""
    blocking = db.scalar(
        select(Order.id)
        .where(
            Order.schedule_id == schedule_id,
            Order.status.not_in(ARCHIVED_ORDER_STATUSES),
        )
        .limit(1)
        .with_for_update()
    )
    return blocking is None


def list_schedules(
    db: DBSession, now: datetime, *, include_archived: bool = False
) -> ScheduleList:
    query = select(Schedule).options(selectinload(Schedule.offers))
    if not include_archived:
        query = query.where(Schedule.archived_at.is_(None))
    rows = db.scalars(query.order_by(Schedule.pickup_at, Schedule.id)).all()
    offer_ids = [offer.id for schedule in rows for offer in schedule.offers]
    allocated = allocated_totals(db, offer_ids)
    return ScheduleList(
        items=[_schedule_view(schedule, now, allocated) for schedule in rows]
    )


def offer_product(db: DBSession, product_id: int) -> Product:
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    if product.archived:
        raise HTTPException(
            status_code=409,
            detail="Produk yang diarsipkan tidak dapat ditawarkan pada jadwal.",
        )
    return product


def _new_offer(product: Product, quota: int) -> ScheduleOffer:
    # Catalog values are copied by the server; clients never send name/unit/price.
    return ScheduleOffer(
        product_id=product.id,
        product_name=product.name,
        selling_unit=product.selling_unit,
        price_rupiah=product.price_rupiah,
        quota=quota,
    )


def _commit(db: DBSession, detail: str) -> None:
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=detail) from None


@public_router.get("/schedules", response_model=ScheduleList)
def list_public_schedules(request: Request, db: DB, response: Response) -> ScheduleList:
    """Visitors see every non-archived schedule, its offers, quotas, and open state.

    Ordinary closed schedules stay visible with their genuine `orders_open`
    value; only an explicit seller archive removes a schedule from this list.
    """
    no_store(response)
    return list_schedules(db, request.app.state.clock())


@seller_router.get("/schedules", response_model=ScheduleList)
def list_managed_schedules(
    _seller: SELLER,
    request: Request,
    db: DB,
    response: Response,
    include_archived: bool = False,
) -> ScheduleList:
    no_store(response)
    return list_schedules(
        db, request.app.state.clock(), include_archived=include_archived
    )


@seller_router.post("/schedules", status_code=201, response_model=ScheduleView)
def create_schedule(
    payload: ScheduleCreate,
    _seller: SELLER,
    _csrf: CSRF,
    request: Request,
    db: DB,
    response: Response,
) -> ScheduleView:
    """Create the schedule and all initial offers in one transaction."""
    products = {offer.product_id: offer_product(db, offer.product_id) for offer in payload.offers}
    schedule = Schedule(
        pickup_at=payload.pickup_at,
        order_cutoff_at=payload.order_cutoff_at,
    )
    for offer_input in payload.offers:
        schedule.offers.append(_new_offer(products[offer_input.product_id], offer_input.quota))
    db.add(schedule)
    _commit(
        db,
        "Jadwal tidak dapat disimpan karena data produk berubah. Muat ulang lalu coba lagi.",
    )
    created = find_schedule(db, schedule.id)
    no_store(response)
    return _schedule_view(created, request.app.state.clock())


@seller_router.patch("/schedules/{schedule_id}", response_model=ScheduleView)
def update_schedule(
    schedule_id: int,
    payload: ScheduleUpdate,
    _seller: SELLER,
    _csrf: CSRF,
    request: Request,
    db: DB,
    response: Response,
) -> ScheduleView:
    schedule = lock_schedule(db, schedule_id)
    refuse_archived_schedule(schedule)
    pickup_at = schedule.pickup_at
    order_cutoff_at = schedule.order_cutoff_at
    if "pickup_at" in payload.model_fields_set:
        assert payload.pickup_at is not None
        pickup_at = payload.pickup_at
    if "order_cutoff_at" in payload.model_fields_set:
        assert payload.order_cutoff_at is not None
        order_cutoff_at = payload.order_cutoff_at
    if order_cutoff_at >= pickup_at:
        raise HTTPException(
            status_code=422,
            detail="Batas PO harus sebelum waktu pengambilan; tepat pada waktu yang sama ditolak.",
        )
    if pickup_at != schedule.pickup_at and schedule_has_orders(db, schedule.id):
        raise HTTPException(
            status_code=409,
            detail=(
                "Waktu pengambilan tidak dapat diubah karena jadwal ini sudah "
                "memiliki pesanan. Batas PO masih boleh diubah."
            ),
        )
    schedule.pickup_at = pickup_at
    schedule.order_cutoff_at = order_cutoff_at
    _commit(db, "Perubahan jadwal bertentangan dengan data lain. Muat ulang lalu coba lagi.")
    updated = find_schedule(db, schedule.id)
    allocated = allocated_totals(db, [offer.id for offer in updated.offers])
    no_store(response)
    return _schedule_view(updated, request.app.state.clock(), allocated)


@seller_router.delete("/schedules/{schedule_id}", status_code=204)
def delete_schedule(
    schedule_id: int, _seller: SELLER, _csrf: CSRF, db: DB
) -> None:
    """Delete is only for schedules no order has referenced yet."""
    schedule = lock_schedule(db, schedule_id)
    refuse_archived_schedule(schedule)
    if schedule_has_orders(db, schedule.id):
        raise HTTPException(
            status_code=409,
            detail=(
                "Jadwal tidak dapat dihapus karena sudah memiliki pesanan. "
                "Riwayat pesanan harus tetap utuh."
            ),
        )
    db.delete(schedule)
    _commit(db, "Jadwal tidak dapat dihapus karena masih dipakai.")


@seller_router.post(
    "/schedules/{schedule_id}/offers", status_code=201, response_model=OfferView
)
def add_offer(
    schedule_id: int,
    payload: OfferInput,
    _seller: SELLER,
    _csrf: CSRF,
    db: DB,
) -> OfferView:
    schedule = lock_schedule(db, schedule_id)
    refuse_archived_schedule(schedule)
    product = offer_product(db, payload.product_id)
    duplicate = db.scalar(
        select(ScheduleOffer.id).where(
            ScheduleOffer.schedule_id == schedule_id,
            ScheduleOffer.product_id == payload.product_id,
        )
    )
    if duplicate is not None:
        raise HTTPException(
            status_code=409, detail="Produk ini sudah ditawarkan pada jadwal tersebut."
        )
    offer = _new_offer(product, payload.quota)
    offer.schedule_id = schedule_id
    db.add(offer)
    _commit(db, "Penawaran tidak dapat disimpan karena produk ganda atau data berubah.")
    return _offer_view(offer, 0)


@seller_router.patch(
    "/schedules/{schedule_id}/offers/{offer_id}", response_model=OfferView
)
def update_offer(
    schedule_id: int,
    offer_id: int,
    payload: OfferUpdate,
    _seller: SELLER,
    _csrf: CSRF,
    db: DB,
) -> OfferView:
    schedule = lock_schedule(db, schedule_id)
    refuse_archived_schedule(schedule)
    offer = lock_offer(db, schedule_id, offer_id)
    if payload.quota is not None:
        allocated = allocated_quantities(db, schedule_id, [offer.id]).get(offer.id, 0)
        if payload.quota < allocated:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Kuota tidak boleh di bawah {allocated} unit yang sudah dipesan. "
                    "Naikkan kuota atau tangani pesanan terlebih dahulu."
                ),
            )
        offer.quota = payload.quota
    if payload.price_rupiah is not None:
        offer.price_rupiah = payload.price_rupiah
    _commit(db, "Penawaran tidak dapat disimpan. Muat ulang lalu coba lagi.")
    db.refresh(offer)
    allocation = allocated_quantities(db, schedule_id, [offer.id])
    return _offer_view(offer, allocation.get(offer.id, 0))


@seller_router.delete(
    "/schedules/{schedule_id}/offers/{offer_id}", status_code=204
)
def delete_offer(
    schedule_id: int, offer_id: int, _seller: SELLER, _csrf: CSRF, db: DB
) -> None:
    """An offer referenced by any order row must keep its history."""
    schedule = lock_schedule(db, schedule_id)
    refuse_archived_schedule(schedule)
    offer = lock_offer(db, schedule_id, offer_id)
    if offer_has_orders(db, offer.id):
        raise HTTPException(
            status_code=409,
            detail=(
                "Penawaran tidak dapat dihapus karena sudah dipesan. "
                "Riwayat pesanan harus tetap utuh."
            ),
        )
    db.delete(offer)
    _commit(db, "Penawaran tidak dapat dihapus karena masih dipakai.")


@seller_router.post("/schedules/{schedule_id}/archive", response_model=ScheduleView)
def archive_schedule(
    schedule_id: int,
    _seller: SELLER,
    _csrf: CSRF,
    request: Request,
    db: DB,
    response: Response,
    _payload: ScheduleArchiveInput | None = None,
) -> ScheduleView:
    """Hide a finished schedule from ordinary lists without touching its history.

    The schedule row is locked first, like every other checkout-affecting
    mutation, so a concurrent checkout cannot slip in between the cutoff check
    and the archive. Repeating the call is a no-op that returns the same view.
    """
    schedule = lock_schedule(db, schedule_id)
    if schedule.archived_at is None:
        now = request.app.state.clock()
        if now < schedule.order_cutoff_at:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Jadwal ini masih dibuka. Arsip hanya untuk jadwal yang batas "
                    "PO-nya sudah lewat."
                ),
            )
        if not schedule_orders_are_terminal(db, schedule.id):
            raise HTTPException(status_code=409, detail=ARCHIVE_REFUSAL)
        schedule.archived_at = now
        db.commit()
    archived = find_schedule(db, schedule.id)
    allocated = allocated_totals(db, [offer.id for offer in archived.offers])
    no_store(response)
    return _schedule_view(archived, request.app.state.clock(), allocated)


@seller_router.post("/schedules/{schedule_id}/restore", response_model=ScheduleView)
def restore_schedule(
    schedule_id: int,
    _seller: SELLER,
    _csrf: CSRF,
    request: Request,
    db: DB,
    response: Response,
    _payload: ScheduleArchiveInput | None = None,
) -> ScheduleView:
    """Clear the archive flag. Cutoff, offers, and order history stay untouched."""
    schedule = lock_schedule(db, schedule_id)
    if schedule.archived_at is not None:
        schedule.archived_at = None
        db.commit()
    restored = find_schedule(db, schedule.id)
    allocated = allocated_totals(db, [offer.id for offer in restored.offers])
    no_store(response)
    return _schedule_view(restored, request.app.state.clock(), allocated)
