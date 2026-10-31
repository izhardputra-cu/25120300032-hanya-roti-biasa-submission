"""Quota allocation reads shared by checkout and seller quota edits.

Cancelled orders release their units, so every read excludes status `batal`.
Checkout-affecting paths use the locking variant: InnoDB locking reads return the
latest committed rows, which avoids computing availability from a REPEATABLE READ
snapshot taken before the caller waited on the schedule lock.
"""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.models import Order, OrderItem


def _totals(rows: Sequence[tuple[int, int]]) -> dict[int, int]:
    totals: dict[int, int] = {}
    for offer_id, quantity in rows:
        totals[offer_id] = totals.get(offer_id, 0) + quantity
    return totals


def allocated_quantities(
    db: DBSession, schedule_id: int, offer_ids: Sequence[int]
) -> dict[int, int]:
    """Locking, latest-committed allocation per offer for one schedule."""
    if not offer_ids:
        return {}
    rows = db.execute(
        select(OrderItem.offer_id, OrderItem.quantity)
        .join(Order, Order.id == OrderItem.order_id)
        .where(
            Order.schedule_id == schedule_id,
            Order.status != "batal",
            OrderItem.offer_id.in_(offer_ids),
        )
        .with_for_update()
    ).all()
    return _totals([(row[0], row[1]) for row in rows])


def allocated_totals(db: DBSession, offer_ids: Sequence[int]) -> dict[int, int]:
    """Read-only allocation map for schedule lists; checkout locks authoritatively."""
    if not offer_ids:
        return {}
    rows = db.execute(
        select(OrderItem.offer_id, OrderItem.quantity)
        .join(Order, Order.id == OrderItem.order_id)
        .where(Order.status != "batal", OrderItem.offer_id.in_(offer_ids))
    ).all()
    return _totals([(row[0], row[1]) for row in rows])
