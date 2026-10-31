"""Schedule archiving: a forward-only, non-destructive hide for finished schedules.

Every assertion here runs against real MySQL through the public API. The tests
cover the operator's cleanup need (a finished schedule leaves the storefront)
without weakening history: offers, allocations, order rows, and production
totals stay exactly as they were, and restoring brings the same data back.
"""

from collections.abc import Iterator
from typing import Any

import pytest
from conftest import ORIGIN, MutableClock
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as DBSession

from app.config import Settings
from app.db import make_engine
from app.main import create_app
from app.seed import DEMO_SELLER_EMAIL, DEMO_SELLER_PASSWORD, seed_seller

BUYER_NAME = "Pembeli Arsip"
BUYER_EMAIL = "archive-buyer@example.com"
BUYER_PASSWORD = "Synthetic-archive-buyer-2026!"
PRODUCT = {
    "name": "Sourdough Arsip",
    "selling_unit": "1 loaf 500 gram",
    "price_rupiah": 65000,
    "description": "Roti uji untuk arsip jadwal.",
}
PICKUP_WIB = "2035-11-08T18:00:00+07:00"
CUTOFF_WIB = "2035-11-06T20:00:00+07:00"
PAST_CUTOFF_WIB = "2026-01-01T05:00:00+07:00"


def csrf_headers(client: TestClient) -> dict[str, str]:
    token = client.get("/api/auth/session").json()["csrf_token"]
    return {"Origin": ORIGIN, "X-CSRF-Token": token}


def login(client: TestClient, email: str, password: str) -> None:
    response = client.post(
        "/api/auth/login", json={"email": email, "password": password}, headers=csrf_headers(client)
    )
    assert response.status_code == 200, response.text


def seed_demo_seller(settings: Settings) -> None:
    engine = make_engine(settings.database_url.get_secret_value())
    try:
        with DBSession(engine) as db:
            seed_seller(db, email=DEMO_SELLER_EMAIL, password=DEMO_SELLER_PASSWORD)
    finally:
        engine.dispose()


def register_buyer(client: TestClient) -> None:
    response = client.post(
        "/api/auth/register",
        json={"name": BUYER_NAME, "email": BUYER_EMAIL, "password": BUYER_PASSWORD},
        headers=csrf_headers(client),
    )
    assert response.status_code == 201, response.text
    login(client, BUYER_EMAIL, BUYER_PASSWORD)


@pytest.fixture
def actors(settings: Settings) -> Iterator[tuple[TestClient, TestClient]]:
    # A fixed clock keeps the "cutoff has passed" rule deterministic: the real
    # wall clock would make these dates future or past depending on the day.
    app = create_app(settings, clock=MutableClock())
    with TestClient(app) as buyer, TestClient(app) as seller:
        seed_demo_seller(settings)
        login(seller, DEMO_SELLER_EMAIL, DEMO_SELLER_PASSWORD)
        register_buyer(buyer)
        yield buyer, seller


def create_product(seller: TestClient, **overrides: object) -> dict[str, Any]:
    response = seller.post(
        "/api/seller/products", json={**PRODUCT, **overrides}, headers=csrf_headers(seller)
    )
    assert response.status_code == 201, response.text
    return response.json()


def open_schedule(
    seller: TestClient, product_ids: list[int], **overrides: object
) -> dict[str, Any]:
    payload = {
        "pickup_at": PICKUP_WIB,
        "order_cutoff_at": CUTOFF_WIB,
        "offers": [{"product_id": product_id, "quota": 6} for product_id in product_ids],
        **overrides,
    }
    response = seller.post(
        "/api/seller/schedules", json=payload, headers=csrf_headers(seller)
    )
    assert response.status_code == 201, response.text
    return response.json()


def close_cutoff(seller: TestClient, schedule: dict[str, Any]) -> dict[str, Any]:
    """A normal seller time edit; no test-only database access."""
    response = seller.patch(
        f"/api/seller/schedules/{schedule['id']}",
        json={"order_cutoff_at": PAST_CUTOFF_WIB},
        headers=csrf_headers(seller),
    )
    assert response.status_code == 200, response.text
    return response.json()


def checkout(
    buyer: TestClient, schedule: dict[str, Any], quantity: int, key: str
) -> dict[str, Any]:
    offer = schedule["offers"][0]
    response = buyer.post(
        "/api/orders",
        json={
            "checkout_key": key,
            "schedule_id": schedule["id"],
            "items": [
                {
                    "offer_id": offer["id"],
                    "quantity": quantity,
                    "quoted_price_rupiah": offer["price_rupiah"],
                }
            ],
        },
        headers=csrf_headers(buyer),
    )
    assert response.status_code == 201, response.text
    return response.json()


def complete_order(buyer: TestClient, seller: TestClient, order: dict[str, Any]) -> None:
    reported = buyer.post(
        f"/api/orders/{order['id']}/transfer-report",
        json={"note": "Transfer uji arsip, nominal pas."},
        headers=csrf_headers(buyer),
    )
    assert reported.status_code == 200, reported.text
    verified = seller.post(
        f"/api/seller/orders/{order['id']}/verify",
        json={"received_total_rupiah": order["total_rupiah"]},
        headers=csrf_headers(seller),
    )
    assert verified.status_code == 200, verified.text
    ready = seller.post(
        f"/api/seller/orders/{order['id']}/ready", headers=csrf_headers(seller)
    )
    assert ready.status_code == 200, ready.text
    done = seller.post(
        f"/api/seller/orders/{order['id']}/complete", headers=csrf_headers(seller)
    )
    assert done.status_code == 200, done.text


def archive(seller: TestClient, schedule: dict[str, Any]) -> Any:
    return seller.post(
        f"/api/seller/schedules/{schedule['id']}/archive", headers=csrf_headers(seller)
    )


def restore(seller: TestClient, schedule: dict[str, Any]) -> Any:
    return seller.post(
        f"/api/seller/schedules/{schedule['id']}/restore", headers=csrf_headers(seller)
    )


def recap(seller: TestClient, *, include_archived: bool = False) -> dict[str, Any]:
    query = "?include_archived=true" if include_archived else ""
    response = seller.get(f"/api/seller/production-recap{query}")
    assert response.status_code == 200, response.text
    return response.json()


def recap_item(recap_payload: dict[str, Any], schedule_id: int) -> dict[str, Any]:
    return next(
        item for item in recap_payload["items"] if item["schedule_id"] == schedule_id
    )


def test_archive_refuses_a_schedule_that_is_still_open(actors) -> None:
    _buyer, seller = actors
    product = create_product(seller)
    schedule = open_schedule(seller, [product["id"]])

    response = archive(seller, schedule)

    assert response.status_code == 409
    assert "sudah lewat" in response.json()["detail"]
    listing = seller.get("/api/seller/schedules").json()["items"]
    assert listing[0]["archived"] is False
    assert listing[0]["orders_open"] is True
    assert seller.get("/api/schedules").json()["items"][0]["archived"] is False


def test_archive_refuses_a_live_order_and_keeps_the_closed_schedule_visible(
    actors,
) -> None:
    buyer, seller = actors
    product = create_product(seller)
    schedule = open_schedule(seller, [product["id"]])
    order = checkout(buyer, schedule, 2, "archive-live-01")
    closed = close_cutoff(seller, schedule)

    response = archive(seller, closed)

    assert response.status_code == 409
    assert "belum selesai atau belum batal" in response.json()["detail"]
    # A legitimately closed schedule with an unpaid order keeps its real status.
    public = seller.get("/api/schedules").json()["items"]
    assert [item["id"] for item in public] == [schedule["id"]]
    assert public[0]["orders_open"] is False
    assert public[0]["archived"] is False
    assert public[0]["offers"][0]["allocated_quantity"] == 2
    detail = seller.get(f"/api/seller/orders/{order['id']}")
    assert detail.status_code == 200
    assert detail.json()["status"] == "menunggu_pembayaran"


def test_archived_fixture_leaves_public_and_default_seller_lists(actors) -> None:
    buyer, seller = actors
    product = create_product(seller)
    leftover = open_schedule(seller, [product["id"]])
    closed_only = open_schedule(
        seller,
        [product["id"]],
        pickup_at="2035-12-08T18:00:00+07:00",
        order_cutoff_at="2035-12-06T20:00:00+07:00",
    )
    order = checkout(buyer, leftover, 2, "archive-hide-01")
    complete_order(buyer, seller, order)
    closed = close_cutoff(seller, leftover)
    assert close_cutoff(seller, closed_only)["orders_open"] is False

    archived = archive(seller, closed)

    assert archived.status_code == 200, archived.text
    view = archived.json()
    assert view["archived"] is True
    assert view["orders_open"] is False
    assert view["pickup_at"] == closed["pickup_at"]
    assert view["order_cutoff_at"] == closed["order_cutoff_at"]
    assert view["offers"][0]["product_name"] == PRODUCT["name"]
    assert view["offers"][0]["allocated_quantity"] == 2

    # Public and default seller lists drop only the archived schedule.
    public_ids = [item["id"] for item in seller.get("/api/schedules").json()["items"]]
    assert public_ids == [closed_only["id"]]
    assert seller.get("/api/schedules").json()["items"][0]["orders_open"] is False
    default_ids = [
        item["id"] for item in seller.get("/api/seller/schedules").json()["items"]
    ]
    assert default_ids == [closed_only["id"]]

    opted_in = seller.get("/api/seller/schedules?include_archived=true").json()["items"]
    assert [item["id"] for item in opted_in] == [leftover["id"], closed_only["id"]]
    archived_view = next(item for item in opted_in if item["id"] == leftover["id"])
    assert archived_view == view

    # Buyer history and seller detail stay readable, with unchanged items.
    buyer_orders = buyer.get("/api/orders").json()["items"]
    assert [item["id"] for item in buyer_orders] == [order["id"]]
    assert buyer_orders[0]["items"][0]["quantity"] == 2
    buyer_detail = buyer.get(f"/api/orders/{order['id']}")
    assert buyer_detail.status_code == 200
    assert buyer_detail.json()["status"] == "selesai"
    seller_detail = seller.get(f"/api/seller/orders/{order['id']}")
    assert seller_detail.status_code == 200
    assert seller_detail.json()["status"] == "selesai"
    assert seller_detail.json()["items"] == buyer_detail.json()["items"]

    # Seller worklists hide the historical order by default and expose it on demand.
    default_seller_orders = seller.get("/api/seller/orders").json()["items"]
    assert default_seller_orders == []
    opted_orders = seller.get("/api/seller/orders?include_archived=true").json()["items"]
    assert [item["id"] for item in opted_orders] == [order["id"]]
    assert opted_orders[0]["status"] == "selesai"


def test_restore_returns_the_identical_schedule_and_recap(actors) -> None:
    buyer, seller = actors
    product = create_product(seller)
    schedule = open_schedule(seller, [product["id"]])
    order = checkout(buyer, schedule, 3, "archive-restore-01")
    complete_order(buyer, seller, order)
    closed = close_cutoff(seller, schedule)
    before_recap = recap(seller)
    before_item = recap_item(before_recap, schedule["id"])
    assert before_item["total_quantity"] == 3

    assert archive(seller, closed).status_code == 200
    assert recap(seller)["items"] == []
    archived_recap = recap(seller, include_archived=True)
    assert recap_item(archived_recap, schedule["id"])["lines"] == before_item["lines"]
    assert recap_item(archived_recap, schedule["id"])["total_quantity"] == 3
    assert recap_item(archived_recap, schedule["id"])["archived"] is True

    restored = restore(seller, closed)

    assert restored.status_code == 200, restored.text
    assert restored.json()["archived"] is False
    assert restored.json()["offers"] == closed["offers"]
    assert restored.json()["pickup_at"] == closed["pickup_at"]
    assert restored.json()["order_cutoff_at"] == closed["order_cutoff_at"]
    assert recap(seller)["items"] == before_recap["items"]
    assert [item["id"] for item in seller.get("/api/schedules").json()["items"]] == [
        schedule["id"]
    ]
    # The original cutoff is preserved, so the restored schedule stays closed.
    assert seller.get("/api/schedules").json()["items"][0]["orders_open"] is False


def test_archived_schedule_refuses_new_checkout_but_replays_the_original_key(
    actors,
) -> None:
    buyer, seller = actors
    product = create_product(seller)
    schedule = open_schedule(seller, [product["id"]])
    order = checkout(buyer, schedule, 2, "archive-replay-01")
    complete_order(buyer, seller, order)
    closed = close_cutoff(seller, schedule)
    assert archive(seller, closed).status_code == 200

    offer = closed["offers"][0]
    fresh = buyer.post(
        "/api/orders",
        json={
            "checkout_key": "archive-new-01",
            "schedule_id": schedule["id"],
            "items": [
                {
                    "offer_id": offer["id"],
                    "quantity": 1,
                    "quoted_price_rupiah": offer["price_rupiah"],
                }
            ],
        },
        headers=csrf_headers(buyer),
    )
    assert fresh.status_code == 409
    assert "diarsipkan" in fresh.json()["detail"]

    replay = buyer.post(
        "/api/orders",
        json={
            "checkout_key": "archive-replay-01",
            "schedule_id": schedule["id"],
            "items": [
                {
                    "offer_id": offer["id"],
                    "quantity": 2,
                    "quoted_price_rupiah": offer["price_rupiah"],
                }
            ],
        },
        headers=csrf_headers(buyer),
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["id"] == order["id"]
    assert replay.json()["order_number"] == order["order_number"]


def test_archived_schedule_is_read_only_until_restored(actors) -> None:
    _buyer, seller = actors
    product = create_product(seller)
    extra = create_product(seller, name="Sourdough Arsip Kedua")
    schedule = open_schedule(seller, [product["id"]])
    closed = close_cutoff(seller, schedule)
    offer_id = closed["offers"][0]["id"]

    assert archive(seller, closed).status_code == 200
    # Idempotent, matching the product archive convention.
    repeated = archive(seller, closed)
    assert repeated.status_code == 200
    assert repeated.json()["archived"] is True

    headers = csrf_headers(seller)
    refused = [
        seller.patch(
            f"/api/seller/schedules/{schedule['id']}",
            json={"pickup_at": "2035-11-09T18:00:00+07:00"},
            headers=headers,
        ),
        seller.post(
            f"/api/seller/schedules/{schedule['id']}/offers",
            json={"product_id": extra["id"], "quota": 2},
            headers=headers,
        ),
        seller.patch(
            f"/api/seller/schedules/{schedule['id']}/offers/{offer_id}",
            json={"quota": 8},
            headers=headers,
        ),
        seller.delete(
            f"/api/seller/schedules/{schedule['id']}/offers/{offer_id}", headers=headers
        ),
        seller.delete(f"/api/seller/schedules/{schedule['id']}", headers=headers),
    ]
    for response in refused:
        assert response.status_code == 409
        assert "diarsipkan" in response.json()["detail"]

    assert restore(seller, closed).status_code == 200
    # Restore is idempotent too, and ordinary edits work again.
    assert restore(seller, closed).json()["archived"] is False
    edited = seller.patch(
        f"/api/seller/schedules/{schedule['id']}",
        json={"pickup_at": "2035-11-09T18:00:00+07:00"},
        headers=headers,
    )
    assert edited.status_code == 200
    assert edited.json()["archived"] is False


def test_archive_requires_seller_role_and_csrf(actors) -> None:
    buyer, seller = actors
    product = create_product(seller)
    schedule = open_schedule(seller, [product["id"]])
    closed = close_cutoff(seller, schedule)
    url = f"/api/seller/schedules/{schedule['id']}/archive"

    assert buyer.post(url, headers=csrf_headers(buyer)).status_code == 403
    headers = csrf_headers(seller)
    for broken in (
        {key: value for key, value in headers.items() if key != "Origin"},
        {key: value for key, value in headers.items() if key != "X-CSRF-Token"},
        {**headers, "Origin": "https://evil.example"},
        {**headers, "X-CSRF-Token": "0" * 64},
    ):
        assert seller.post(url, headers=broken).status_code == 403
    assert seller.get("/api/schedules").json()["items"][0]["archived"] is False

    assert archive(seller, closed).status_code == 200
    restore_url = f"/api/seller/schedules/{schedule['id']}/restore"
    assert buyer.post(restore_url, headers=csrf_headers(buyer)).status_code == 403
    assert (
        seller.post(
            restore_url,
            headers={key: value for key, value in headers.items() if key != "X-CSRF-Token"},
        ).status_code
        == 403
    )
    assert seller.get("/api/seller/schedules?include_archived=true").json()["items"][0][
        "archived"
    ] is True


def test_archive_and_restore_reject_unexpected_fields(actors) -> None:
    _buyer, seller = actors
    product = create_product(seller)
    closed = close_cutoff(seller, open_schedule(seller, [product["id"]]))
    headers = csrf_headers(seller)

    extra = seller.post(
        f"/api/seller/schedules/{closed['id']}/archive",
        json={"archived": True},
        headers=headers,
    )
    assert extra.status_code == 422

    empty = seller.post(
        f"/api/seller/schedules/{closed['id']}/archive", json={}, headers=headers
    )
    assert empty.status_code == 200
    assert empty.json()["archived"] is True

    restore_extra = seller.post(
        f"/api/seller/schedules/{closed['id']}/restore",
        json={"archived": False},
        headers=headers,
    )
    assert restore_extra.status_code == 422
    assert seller.get("/api/seller/schedules?include_archived=true").json()["items"][0][
        "archived"
    ] is True


def test_cancelled_only_schedule_can_be_archived_without_touching_the_order(
    actors,
) -> None:
    buyer, seller = actors
    product = create_product(seller)
    schedule = open_schedule(seller, [product["id"]])
    order = checkout(buyer, schedule, 1, "archive-cancel-01")
    cancelled = buyer.post(
        f"/api/orders/{order['id']}/cancel",
        json={},
        headers=csrf_headers(buyer),
    )
    assert cancelled.status_code == 200, cancelled.text
    closed = close_cutoff(seller, schedule)
    before = seller.get(f"/api/seller/orders/{order['id']}").json()

    response = archive(seller, closed)

    assert response.status_code == 200
    after = seller.get(f"/api/seller/orders/{order['id']}").json()
    assert after == before
    assert after["status"] == "batal"
    assert after["cancellation_reason"] == before["cancellation_reason"]
    assert after["items"][0]["quantity"] == 1
    assert recap(seller, include_archived=True)["items"][0]["total_quantity"] == 0
