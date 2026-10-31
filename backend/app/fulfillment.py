"""Seller production recap and pickup fulfillment for T7.

The recap is derived from order items, not stored separately: paid, non-cancelled
orders keep contributing after they are ready or completed. Exactly one of
completion and cancellation can win because both use the same schedule-first to
order lock order as the payment actions in `app.orders`.
"""

from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import func, select

from app.auth import CSRF, DB
from app.catalog import SELLER, no_store
from app.models import Order, OrderItem, Schedule, ScheduleOffer
from app.orders import find_order, order_for_payment_action
from app.schemas import (
    FulfillmentActionInput,
    OrderStatus,
    ProductionRecap,
    ProductionRecapLine,
    ProductionRecapSchedule,
    SellerOrderView,
)

router = APIRouter(prefix="/api")

# Production keeps counting bread that is already packed or handed over. Waiting
# for payment/review and cancelled orders do not need bread.
RECAP_STATUSES: tuple[OrderStatus, ...] = ("terkonfirmasi", "siap_diambil", "selesai")


def _recap_lines(db: DB) -> dict[int, list[ProductionRecapLine]]:
    rows = db.execute(
        select(
            Order.schedule_id,
            OrderItem.offer_id,
            ScheduleOffer.product_id,
            ScheduleOffer.product_name,
            ScheduleOffer.selling_unit,
            func.sum(OrderItem.quantity).label("quantity"),
        )
        .join(OrderItem, OrderItem.order_id == Order.id)
        .join(ScheduleOffer, ScheduleOffer.id == OrderItem.offer_id)
        .where(Order.status.in_(RECAP_STATUSES))
        .group_by(
            Order.schedule_id,
            OrderItem.offer_id,
            ScheduleOffer.product_id,
            ScheduleOffer.product_name,
            ScheduleOffer.selling_unit,
        )
        .order_by(Order.schedule_id, OrderItem.offer_id)
    ).all()
    lines: dict[int, list[ProductionRecapLine]] = {}
    for row in rows:
        lines.setdefault(row.schedule_id, []).append(
            ProductionRecapLine(
                offer_id=row.offer_id,
                product_id=row.product_id,
                product_name=row.product_name,
                selling_unit=row.selling_unit,
                quantity=int(row.quantity),
            )
        )
    return lines


@router.get("/seller/production-recap", response_model=ProductionRecap)
def production_recap(
    request: Request,
    _seller: SELLER,
    db: DB,
    response: Response,
    include_archived: bool = False,
) -> ProductionRecap:
    """Every schedule with its summed selling units, empty ones included.

    Archived schedules are historical, so they stay out of the default recap
    and reappear with their unchanged totals when explicitly requested or when
    the seller restores them.
    """
    now = request.app.state.clock()
    query = select(Schedule)
    if not include_archived:
        query = query.where(Schedule.archived_at.is_(None))
    schedules = db.scalars(query.order_by(Schedule.pickup_at, Schedule.id)).all()
    lines_by_schedule = _recap_lines(db)
    no_store(response)
    return ProductionRecap(
        included_statuses=list(RECAP_STATUSES),
        items=[
            ProductionRecapSchedule(
                schedule_id=schedule.id,
                pickup_at=schedule.pickup_at,
                order_cutoff_at=schedule.order_cutoff_at,
                orders_open=now < schedule.order_cutoff_at and not schedule.archived,
                archived=schedule.archived,
                lines=lines_by_schedule.get(schedule.id, []),
                total_quantity=sum(
                    line.quantity for line in lines_by_schedule.get(schedule.id, [])
                ),
            )
            for schedule in schedules
        ],
    )


def _advance(
    db: DB, order_id: int, *, allowed_from: str, target: str, refusal: str
) -> SellerOrderView:
    """Lock schedule then order, so a competing action sees the committed status."""
    order = order_for_payment_action(db, order_id)
    if order.status != allowed_from:
        raise HTTPException(status_code=409, detail=refusal)
    order.status = target
    db.commit()
    updated = find_order(db, order_id)
    return SellerOrderView.model_validate(updated)


@router.post("/seller/orders/{order_id}/ready", response_model=SellerOrderView)
def mark_ready(
    order_id: int,
    _seller: SELLER,
    _csrf: CSRF,
    db: DB,
    response: Response,
    _payload: FulfillmentActionInput | None = None,
) -> SellerOrderView:
    """terkonfirmasi -> siap_diambil: the seller declares the order packed."""
    updated = _advance(
        db,
        order_id,
        allowed_from="terkonfirmasi",
        target="siap_diambil",
        refusal=(
            "Hanya pesanan terkonfirmasi yang dapat ditandai siap diambil. "
            "Status saat ini tidak ditimpa."
        ),
    )
    no_store(response)
    return updated


@router.post("/seller/orders/{order_id}/complete", response_model=SellerOrderView)
def mark_complete(
    order_id: int,
    _seller: SELLER,
    _csrf: CSRF,
    db: DB,
    response: Response,
    _payload: FulfillmentActionInput | None = None,
) -> SellerOrderView:
    """siap_diambil -> selesai: the seller declares the physical handoff done."""
    updated = _advance(
        db,
        order_id,
        allowed_from="siap_diambil",
        target="selesai",
        refusal=(
            "Selesai hanya dapat dicatat setelah pesanan ditandai siap diambil. "
            "Status selesai bersifat final."
        ),
    )
    no_store(response)
    return updated
