"""Buyer checkout, order history, and order detail for T5."""

import hashlib
import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import selectinload

from app.allocations import allocated_quantities
from app.auth import CSRF, DB, USER
from app.catalog import SELLER, no_store
from app.models import Order, OrderItem, Schedule, ScheduleOffer, User
from app.schedules import lock_schedule
from app.schemas import (
    BuyerCancelInput,
    CheckoutInput,
    OrderList,
    OrderView,
    SellerCancelInput,
    SellerOrderList,
    SellerOrderView,
    TransferReportInput,
    VerifyPaymentInput,
)

router = APIRouter(prefix="/api")


def current_buyer(user: USER) -> User:
    """Sellers manage orders; ordering is a buyer action in this MVP."""
    if user.role != "buyer":
        raise HTTPException(status_code=403, detail="Buyer access required")
    return user


BUYER = Annotated[User, Depends(current_buyer)]


def checkout_fingerprint(payload: CheckoutInput) -> str:
    """Canonical payload hash so a repeated key can be compared, not re-validated."""
    normalized = {
        "schedule_id": payload.schedule_id,
        "items": sorted(
            (
                {
                    "offer_id": item.offer_id,
                    "quantity": item.quantity,
                    "quoted_price_rupiah": item.quoted_price_rupiah,
                }
                for item in payload.items
            ),
            key=lambda item: item["offer_id"],
        ),
    }
    encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def existing_order(
    db: DB, buyer_id: int, checkout_key: str, *, lock: bool = False
) -> Order | None:
    query = select(Order).where(
        Order.user_id == buyer_id, Order.checkout_key == checkout_key
    )
    if lock:
        # Locking reads use the latest committed row even after waiting, which is
        # required for two simultaneous requests that carry the same key.
        query = query.with_for_update()
    return db.scalar(query)


def is_deadlock(exc: OperationalError) -> bool:
    """MySQL 1213 means the transaction was chosen as a deadlock victim."""
    original = exc.orig
    return bool(original is not None and original.args and original.args[0] == 1213)


def replay_order(
    db: DB, order: Order, fingerprint: str, response: Response
) -> OrderView:
    """Return the original order for an identical retry; reject a reused key."""
    if order.checkout_fingerprint != fingerprint:
        raise HTTPException(
            status_code=409,
            detail=(
                "Kunci checkout ini sudah dipakai untuk isi pesanan yang berbeda. "
                "Muat ulang keranjang lalu coba lagi."
            ),
        )
    order_id = order.id
    # A locking read can see a winner that this transaction's old read view cannot.
    # Replay is read-only: release its locks/snapshot before loading the response.
    db.rollback()
    created = find_order(db, order_id)
    response.status_code = 200
    no_store(response)
    return OrderView.model_validate(created)


@router.post("/orders", status_code=201, response_model=OrderView)
def checkout(
    payload: CheckoutInput,
    buyer: BUYER,
    _csrf: CSRF,
    request: Request,
    db: DB,
    response: Response,
) -> OrderView:
    """Create one order for one schedule.

    The idempotency key is checked before fresh business validation so a retry
    still returns the original order after the cutoff, price, or quota changed.
    """
    fingerprint = checkout_fingerprint(payload)
    found = existing_order(db, buyer.id, payload.checkout_key)
    if found is not None:
        return replay_order(db, found, fingerprint, response)

    schedule = db.scalar(
        select(Schedule).where(Schedule.id == payload.schedule_id).with_for_update()
    )
    if schedule is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    # A committed retry wins over fresh cutoff checks, including after a lock wait.
    found = existing_order(db, buyer.id, payload.checkout_key, lock=True)
    if found is not None:
        return replay_order(db, found, fingerprint, response)
    if schedule.archived:
        raise HTTPException(
            status_code=409,
            detail=(
                "Jadwal ini sudah diarsipkan penjual dan tidak menerima pesanan "
                "baru. Pilih jadwal lain yang masih dibuka."
            ),
        )
    # Read the server clock after the lock so a request that waited is judged by
    # the time the decision is actually made.
    if not request.app.state.clock() < schedule.order_cutoff_at:
        raise HTTPException(
            status_code=409,
            detail=(
                "Batas PO jadwal ini sudah lewat. Pilih jadwal lain yang masih dibuka."
            ),
        )
    offer_ids = [item.offer_id for item in payload.items]
    offers = {
        offer.id: offer
        for offer in db.scalars(
            select(ScheduleOffer)
            .where(
                ScheduleOffer.schedule_id == schedule.id,
                ScheduleOffer.id.in_(offer_ids),
            )
            .order_by(ScheduleOffer.id)
            .with_for_update()
        ).all()
    }
    if len(offers) != len(offer_ids):
        raise HTTPException(
            status_code=422,
            detail="Ada penawaran yang tidak tersedia pada jadwal ini.",
        )
    allocated = allocated_quantities(db, schedule.id, offer_ids)
    for item in payload.items:
        offer = offers[item.offer_id]
        if item.quoted_price_rupiah != offer.price_rupiah:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Harga penawaran berubah. Tinjau ulang harga sebelum memesan."
                ),
            )
        remaining = offer.quota - allocated.get(offer.id, 0)
        if item.quantity > remaining:
            raise HTTPException(
                status_code=409,
                detail=(
                    f'Kuota "{offer.product_name}" tidak cukup. '
                    f"Sisa {max(remaining, 0)} unit."
                ),
            )
    order = Order(
        user_id=buyer.id,
        schedule_id=schedule.id,
        order_number="",
        checkout_key=payload.checkout_key,
        checkout_fingerprint=fingerprint,
        status="menunggu_pembayaran",
        total_rupiah=0,
        pickup_at=schedule.pickup_at,
    )
    total = 0
    for item in payload.items:
        offer = offers[item.offer_id]
        line_total = offer.price_rupiah * item.quantity
        total += line_total
        order.items.append(
            OrderItem(
                offer_id=offer.id,
                product_id=offer.product_id,
                product_name=offer.product_name,
                selling_unit=offer.selling_unit,
                unit_price_rupiah=offer.price_rupiah,
                quantity=item.quantity,
                line_total_rupiah=line_total,
            )
        )
    order.total_rupiah = total
    db.add(order)
    try:
        db.flush()
        order.order_number = f"PO-{request.app.state.clock():%Y%m%d}-{order.id:06d}"
        db.commit()
    except IntegrityError:
        # The unique (user_id, checkout_key) index lost a race against another
        # request with the same key. The whole failed transaction rolled back,
        # so no allocation leaked; compare the committed payload now.
        db.rollback()
        found = existing_order(db, buyer.id, payload.checkout_key)
        if found is None:
            raise
        return replay_order(db, found, fingerprint, response)
    except OperationalError as exc:
        # Two conflicting payloads for one key can meet on the same unique-index
        # gap and be chosen as a deadlock victim. Nothing was committed; the
        # client can retry and will then receive the original order or a key
        # conflict. Other operational errors keep propagating.
        if not is_deadlock(exc):
            raise
        db.rollback()
        found = existing_order(db, buyer.id, payload.checkout_key)
        if found is not None:
            return replay_order(db, found, fingerprint, response)
        raise HTTPException(
            status_code=409,
            detail=(
                "Pesanan sedang diproses bersamaan. Coba lagi sebentar; "
                "kunci checkout yang sama akan memakai pesanan semula."
            ),
        ) from None
    created = find_order(db, order.id)
    no_store(response)
    return OrderView.model_validate(created)


def find_order(db: DB, order_id: int) -> Order:
    order = db.scalar(
        select(Order)
        .where(Order.id == order_id)
        .options(
            selectinload(Order.items),
            selectinload(Order.schedule),
            selectinload(Order.buyer),
            selectinload(Order.cancelled_by),
        )
    )
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


@router.get("/orders/{order_id}", response_model=OrderView)
def read_order(user: USER, order_id: int, db: DB, response: Response) -> OrderView:
    """Owner buyers see their order; other buyers must not learn it exists."""
    order = find_order(db, order_id)
    if user.role != "seller" and order.user_id != user.id:
        raise HTTPException(status_code=404, detail="Order not found")
    no_store(response)
    return OrderView.model_validate(order)


@router.get("/orders", response_model=OrderList)
def list_my_orders(buyer: BUYER, db: DB, response: Response) -> OrderList:
    """The buyer's own history, newest first. Other buyers' orders never appear."""
    rows = db.scalars(
        select(Order)
        .where(Order.user_id == buyer.id)
        .options(
            selectinload(Order.items),
            selectinload(Order.schedule),
            selectinload(Order.buyer),
            selectinload(Order.cancelled_by),
        )
        .order_by(Order.created_at.desc(), Order.id.desc())
    ).all()
    no_store(response)
    return OrderList(items=[OrderView.model_validate(order) for order in rows])


def order_for_payment_action(db: DB, order_id: int) -> Order:
    """Lock the schedule first, then re-read the order with a current read."""
    schedule_id = db.scalar(select(Order.schedule_id).where(Order.id == order_id))
    if schedule_id is None:
        raise HTTPException(status_code=404, detail="Order not found")
    lock_schedule(db, schedule_id)
    order = db.scalar(select(Order).where(Order.id == order_id).with_for_update())
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


@router.post("/orders/{order_id}/transfer-report", response_model=OrderView)
def report_transfer(
    order_id: int,
    payload: TransferReportInput,
    buyer: BUYER,
    _csrf: CSRF,
    request: Request,
    db: DB,
    response: Response,
) -> OrderView:
    """The buyer's matching note moves the order to manual review, not to paid."""
    order = order_for_payment_action(db, order_id)
    if order.user_id != buyer.id:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.status != "menunggu_pembayaran":
        raise HTTPException(
            status_code=409,
            detail=(
                "Konfirmasi transfer hanya dapat dikirim saat pesanan masih "
                "menunggu pembayaran. Status atau riwayat pesanan tidak ditimpa."
            ),
        )
    order.transfer_note = payload.note
    order.transfer_reported_at = request.app.state.clock()
    order.transfer_reported_by_id = buyer.id
    order.status = "menunggu_pemeriksaan"
    db.commit()
    reported = find_order(db, order_id)
    no_store(response)
    return OrderView.model_validate(reported)


@router.post("/seller/orders/{order_id}/verify", response_model=OrderView)
def verify_payment(
    order_id: int,
    payload: VerifyPaymentInput,
    seller: SELLER,
    _csrf: CSRF,
    request: Request,
    db: DB,
    response: Response,
) -> OrderView:
    """The seller records a manual fund check, from either pre-confirmation state."""
    order = order_for_payment_action(db, order_id)
    if order.status not in ("menunggu_pembayaran", "menunggu_pemeriksaan"):
        raise HTTPException(
            status_code=409,
            detail=(
                "Pembayaran hanya dapat diverifikasi pada pesanan yang menunggu "
                "pembayaran atau menunggu pemeriksaan."
            ),
        )
    if payload.received_total_rupiah != order.total_rupiah:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Nominal dana yang diterima Rp{payload.received_total_rupiah:,} tidak "
                f"sama dengan total pesanan Rp{order.total_rupiah:,}. Pesanan tidak "
                "ditandai lunas; cocokkan dana terlebih dahulu."
            ).replace(",", "."),
        )
    order.status = "terkonfirmasi"
    order.verified_at = request.app.state.clock()
    order.verified_by_id = seller.id
    order.payment_received_rupiah = payload.received_total_rupiah
    db.commit()
    verified = find_order(db, order_id)
    no_store(response)
    return OrderView.model_validate(verified)


@router.post("/orders/{order_id}/cancel", response_model=OrderView)
def buyer_cancel(
    order_id: int,
    _payload: BuyerCancelInput | None,
    buyer: BUYER,
    _csrf: CSRF,
    request: Request,
    db: DB,
    response: Response,
) -> OrderView:
    """Only the owner may cancel, and only before a transfer has been reported."""
    order = order_for_payment_action(db, order_id)
    if order.user_id != buyer.id:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.status != "menunggu_pembayaran":
        raise HTTPException(
            status_code=409,
            detail=(
                "Pembeli hanya dapat membatalkan pesanan sebelum konfirmasi transfer. "
                "Setelah itu penjual yang memeriksa dana dan menangani pembatalan."
            ),
        )
    order.status = "batal"
    order.cancelled_at = request.app.state.clock()
    order.cancelled_by_id = buyer.id
    order.cancellation_reason = "Dibatalkan pembeli sebelum konfirmasi transfer."
    db.commit()
    cancelled = find_order(db, order_id)
    no_store(response)
    return OrderView.model_validate(cancelled)


@router.post("/seller/orders/{order_id}/cancel", response_model=OrderView)
def seller_cancel(
    order_id: int,
    payload: SellerCancelInput,
    seller: SELLER,
    _csrf: CSRF,
    request: Request,
    db: DB,
    response: Response,
) -> OrderView:
    """Record the seller's cancellation reason and manual funds declaration.

    Ready orders may still be cancelled after the seller settles funds manually;
    completed orders stay final. Either way the derived allocation is released by
    the `batal` status exactly once.
    """
    order = order_for_payment_action(db, order_id)
    if order.status == "selesai":
        raise HTTPException(
            status_code=409,
            detail=(
                "Pesanan ini sudah selesai dan tidak dapat dibatalkan atau dibuka "
                "kembali. Fakta penyelesaian tetap tercatat."
            ),
        )
    if order.status == "batal":
        raise HTTPException(
            status_code=409,
            detail=(
                "Pesanan ini sudah batal. Alasan dan riwayat pembatalan asli tidak "
                "dapat ditimpa."
            ),
        )
    if order.verified_at is not None and payload.refund_outcome == "no_funds_received":
        raise HTTPException(
            status_code=409,
            detail=(
                "Pembayaran pesanan ini sudah diverifikasi, jadi dana tidak dapat "
                "dinyatakan belum diterima. Kembalikan dana secara manual lalu pilih "
                "pernyataan refund sudah selesai."
            ),
        )
    order.status = "batal"
    order.cancelled_at = request.app.state.clock()
    order.cancelled_by_id = seller.id
    order.cancellation_reason = payload.reason
    order.refund_outcome = payload.refund_outcome
    db.commit()
    cancelled = find_order(db, order_id)
    no_store(response)
    return OrderView.model_validate(cancelled)


SELLER_WORKLIST_PRIORITY = {
    "menunggu_pemeriksaan": 0,
    "menunggu_pembayaran": 1,
    "terkonfirmasi": 2,
    "siap_diambil": 3,
    "selesai": 4,
    "batal": 5,
}


@router.get("/seller/orders", response_model=SellerOrderList)
def list_seller_orders(
    _seller: SELLER, db: DB, response: Response, include_archived: bool = False
) -> SellerOrderList:
    """A simple order worklist: action-needed statuses first, newest first within each.

    Orders on archived schedules are historical, so they are hidden by default
    and returned only when the seller explicitly asks for archived data.
    """
    query = (
        select(Order)
        .join(Schedule, Schedule.id == Order.schedule_id)
        .options(
            selectinload(Order.items),
            selectinload(Order.schedule),
            selectinload(Order.buyer),
            selectinload(Order.cancelled_by),
        )
        .order_by(Order.created_at.desc(), Order.id.desc())
    )
    if not include_archived:
        query = query.where(Schedule.archived_at.is_(None))
    rows = db.scalars(query).all()
    ordered = sorted(rows, key=lambda order: SELLER_WORKLIST_PRIORITY[order.status])
    no_store(response)
    return SellerOrderList(
        items=[SellerOrderView.model_validate(order) for order in ordered]
    )


@router.get("/seller/orders/{order_id}", response_model=SellerOrderView)
def read_seller_order(
    order_id: int, _seller: SELLER, db: DB, response: Response
) -> SellerOrderView:
    order = find_order(db, order_id)
    no_store(response)
    return SellerOrderView.model_validate(order)
