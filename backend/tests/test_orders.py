"""T5 order behavior through the public API against real MySQL.

Every assertion here reads a response from the public API. Concurrency tests use
separate HTTP clients and threads so the behaviour is observed, not simulated.
"""

from collections.abc import Iterator
from datetime import datetime
from typing import Any

import pytest
from conftest import ORIGIN, MutableClock
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session as DBSession

from app.config import Settings
from app.db import make_engine
from app.main import create_app
from app.seed import DEMO_SELLER_EMAIL, DEMO_SELLER_PASSWORD, seed_seller

BUYER_PASSWORD = "Demo-buyer-2026!"
PRODUCT = {
    "name": "Sourdough Klasik",
    "selling_unit": "1 loaf 500 gram",
    "price_rupiah": 65000,
    "description": "Roti asam sederhana dengan tepung, air, dan garam. Data demo.",
}

PICKUP_WIB = "2035-11-08T18:00:00+07:00"
PICKUP_UTC = "2035-11-08T11:00:00Z"
CUTOFF_WIB = "2035-11-06T20:00:00+07:00"


def csrf_headers(client: TestClient) -> dict[str, str]:
    token = client.get("/api/auth/session").json()["csrf_token"]
    return {"Origin": ORIGIN, "X-CSRF-Token": token}


def login(client: TestClient, email: str, password: str) -> None:
    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
        headers=csrf_headers(client),
    )
    assert response.status_code == 200, response.text


def register_buyer(client: TestClient, email: str = "pembeli@example.com") -> None:
    response = client.post(
        "/api/auth/register",
        json={
            "name": "Pembeli Uji",
            "email": email,
            "password": BUYER_PASSWORD,
        },
        headers=csrf_headers(client),
    )
    assert response.status_code == 201, response.text
    login(client, email, BUYER_PASSWORD)


def seed_demo_seller(settings: Settings) -> None:
    engine = make_engine(settings.database_url.get_secret_value())
    try:
        with DBSession(engine) as db:
            seed_seller(db, email=DEMO_SELLER_EMAIL, password=DEMO_SELLER_PASSWORD)
    finally:
        engine.dispose()


def create_product(client: TestClient, **overrides: object) -> dict[str, Any]:
    response = client.post(
        "/api/seller/products",
        json={**PRODUCT, **overrides},
        headers=csrf_headers(client),
    )
    assert response.status_code == 201, response.text
    return response.json()


def open_schedule(client: TestClient, product_ids: list[int], **overrides: object) -> dict:
    payload = {
        "pickup_at": PICKUP_WIB,
        "order_cutoff_at": CUTOFF_WIB,
        "offers": [{"product_id": product_id, "quota": 6} for product_id in product_ids],
        **overrides,
    }
    response = client.post(
        "/api/seller/schedules", json=payload, headers=csrf_headers(client)
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def clients(
    settings: Settings,
) -> Iterator[tuple[TestClient, TestClient, MutableClock]]:
    """One app and clock, two independent sessions: buyer and seeded seller."""
    clock = MutableClock()
    app = create_app(settings, clock=clock)
    with TestClient(app) as buyer_client, TestClient(app) as seller_client:
        seed_demo_seller(settings)
        login(seller_client, DEMO_SELLER_EMAIL, DEMO_SELLER_PASSWORD)
        register_buyer(buyer_client)
        yield buyer_client, seller_client, clock


@pytest.fixture
def client(clients: tuple[TestClient, TestClient, MutableClock]) -> TestClient:
    return clients[0]


@pytest.fixture
def seller(clients: tuple[TestClient, TestClient, MutableClock]) -> TestClient:
    return clients[1]


@pytest.fixture
def clock(clients: tuple[TestClient, TestClient, MutableClock]) -> MutableClock:
    return clients[2]


def test_buyer_order_history_is_empty_at_first(client: TestClient) -> None:
    response = client.get("/api/orders")

    assert response.status_code == 200
    assert response.json() == {"items": []}


def checkout_payload(schedule: dict, items: list[dict[str, Any]], key: str = "key-b001") -> dict:
    return {"checkout_key": key, "schedule_id": schedule["id"], "items": items}


def offer_for(schedule: dict, product_name: str = PRODUCT["name"]) -> dict:
    return next(offer for offer in schedule["offers"] if offer["product_name"] == product_name)


def test_buyer_checks_out_one_item_with_server_snapshots(
    client: TestClient, seller: TestClient
) -> None:
    product = create_product(seller)
    schedule = open_schedule(seller, [product["id"]])
    offer = offer_for(schedule)

    response = client.post(
        "/api/orders",
        json=checkout_payload(
            schedule,
            [{"offer_id": offer["id"], "quantity": 2, "quoted_price_rupiah": 65000}],
        ),
        headers=csrf_headers(client),
    )

    assert response.status_code == 201, response.text
    order = response.json()
    assert isinstance(order["id"], int)
    assert order["order_number"] == f"PO-20260101-{order['id']:06d}"
    assert order["schedule_id"] == schedule["id"]
    assert order["status"] == "menunggu_pembayaran"
    assert order["pickup_at"] == PICKUP_UTC
    assert order["total_rupiah"] == 130000
    assert order["items"] == [
        {
            "id": order["items"][0]["id"],
            "offer_id": offer["id"],
            "product_id": product["id"],
            "product_name": PRODUCT["name"],
            "selling_unit": PRODUCT["selling_unit"],
            "unit_price_rupiah": 65000,
            "quantity": 2,
            "line_total_rupiah": 130000,
        }
    ]

    history = client.get("/api/orders")
    assert history.status_code == 200
    assert history.json() == {"items": [order]}


def place_order(
    client: TestClient, schedule: dict, quantity: int = 1, key: str = "key-b001"
) -> dict:
    offer = offer_for(schedule)
    response = client.post(
        "/api/orders",
        json=checkout_payload(
            schedule,
            [
                {
                    "offer_id": offer["id"],
                    "quantity": quantity,
                    "quoted_price_rupiah": offer["price_rupiah"],
                }
            ],
            key=key,
        ),
        headers=csrf_headers(client),
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_order_detail_is_owner_or_seller_only(
    client: TestClient, seller: TestClient, settings: Settings
) -> None:
    product = create_product(seller)
    schedule = open_schedule(seller, [product["id"]])
    order = place_order(client, schedule)

    own = client.get(f"/api/orders/{order['id']}")
    assert own.status_code == 200
    assert own.json() == order

    seller_view = seller.get(f"/api/orders/{order['id']}")
    assert seller_view.status_code == 200
    assert seller_view.json() == order

    with TestClient(client.app) as other:
        register_buyer(other, "pembeli-lain@example.com")
        other_view = other.get(f"/api/orders/{order['id']}")
        assert other_view.status_code == 404
        # The shared API 404 handler keeps one generic body, so ownership does not
        # leak through a more specific message.
        assert other_view.json() == {"detail": "Not Found"}
        assert other.get("/api/orders").json() == {"items": []}

    with TestClient(client.app) as anonymous:
        assert anonymous.get(f"/api/orders/{order['id']}").status_code == 401

    assert client.get("/api/orders/999999").status_code == 404


def test_seller_edits_offer_price_without_rewriting_order_snapshots(
    client: TestClient, seller: TestClient
) -> None:
    product = create_product(seller)
    schedule = open_schedule(seller, [product["id"]])
    offer = offer_for(schedule)
    order = place_order(client, schedule)

    response = seller.patch(
        f"/api/seller/schedules/{schedule['id']}/offers/{offer['id']}",
        json={"price_rupiah": 72000},
        headers=csrf_headers(seller),
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        **offer,
        "price_rupiah": 72000,
        "allocated_quantity": 1,
        "remaining_quota": 5,
    }
    public = client.get("/api/schedules").json()["items"][0]
    assert public["offers"][0]["price_rupiah"] == 72000
    # The order keeps the price, name, unit, and total quoted when it was booked.
    assert client.get(f"/api/orders/{order['id']}").json() == order


def test_checkout_rejects_a_changed_price_without_creating_an_order(
    client: TestClient, seller: TestClient
) -> None:
    product = create_product(seller)
    schedule = open_schedule(seller, [product["id"]])
    offer = offer_for(schedule)

    stale = client.post(
        "/api/orders",
        json=checkout_payload(
            schedule,
            [{"offer_id": offer["id"], "quantity": 1, "quoted_price_rupiah": 70000}],
        ),
        headers=csrf_headers(client),
    )

    assert stale.status_code == 409, stale.text
    assert "harga" in stale.json()["detail"].lower()
    assert client.get("/api/orders").json() == {"items": []}


def test_checkout_closes_exactly_at_the_shared_cutoff(
    client: TestClient, seller: TestClient, clock: MutableClock
) -> None:
    product = create_product(seller)
    schedule = open_schedule(seller, [product["id"]])
    offer = offer_for(schedule)

    clock.now = datetime(2035, 11, 6, 13, 0, 0)  # exactly the cutoff in UTC
    # The session clock also moved; sign in again at the controlled time.
    login(client, "pembeli@example.com", BUYER_PASSWORD)
    at_cutoff = client.post(
        "/api/orders",
        json=checkout_payload(
            schedule,
            [
                {
                    "offer_id": offer["id"],
                    "quantity": 1,
                    "quoted_price_rupiah": offer["price_rupiah"],
                }
            ],
            key="key-b002",
        ),
        headers=csrf_headers(client),
    )
    assert at_cutoff.status_code == 409, at_cutoff.text
    assert "batas po" in at_cutoff.json()["detail"].lower()

    clock.now = datetime(2035, 11, 6, 12, 59, 59)
    before = client.post(
        "/api/orders",
        json=checkout_payload(
            schedule,
            [
                {
                    "offer_id": offer["id"],
                    "quantity": 1,
                    "quoted_price_rupiah": offer["price_rupiah"],
                }
            ],
            key="key-b003",
        ),
        headers=csrf_headers(client),
    )
    assert before.status_code == 201, before.text
    assert client.get("/api/orders").json()["items"][0]["id"] == before.json()["id"]


def test_checkout_cannot_exceed_the_offer_quota(
    client: TestClient, seller: TestClient
) -> None:
    product = create_product(seller)
    schedule = open_schedule(seller, [product["id"]])
    offer = offer_for(schedule)

    over = client.post(
        "/api/orders",
        json=checkout_payload(
            schedule,
            [
                {
                    "offer_id": offer["id"],
                    "quantity": 7,
                    "quoted_price_rupiah": offer["price_rupiah"],
                }
            ],
            key="key-b004",
        ),
        headers=csrf_headers(client),
    )
    assert over.status_code == 409, over.text
    assert "kuota" in over.json()["detail"].lower()
    assert client.get("/api/orders").json() == {"items": []}

    exact = place_order(client, schedule, quantity=6, key="key-b005")
    assert exact["total_rupiah"] == 390000

    full = client.post(
        "/api/orders",
        json=checkout_payload(
            schedule,
            [
                {
                    "offer_id": offer["id"],
                    "quantity": 1,
                    "quoted_price_rupiah": offer["price_rupiah"],
                }
            ],
            key="key-b006",
        ),
        headers=csrf_headers(client),
    )
    assert full.status_code == 409, full.text
    assert len(client.get("/api/orders").json()["items"]) == 1


@pytest.mark.parametrize("quantity", [0, -1, 1.5, "2", True, 1000, None, [], {}])
def test_checkout_rejects_invalid_quantities(
    client: TestClient, seller: TestClient, quantity: object
) -> None:
    product = create_product(seller)
    schedule = open_schedule(seller, [product["id"]])
    offer = offer_for(schedule)

    response = client.post(
        "/api/orders",
        json=checkout_payload(
            schedule,
            [
                {
                    "offer_id": offer["id"],
                    "quantity": quantity,
                    "quoted_price_rupiah": offer["price_rupiah"],
                }
            ],
            key="key-b007",
        ),
        headers=csrf_headers(client),
    )

    assert response.status_code == 422, response.text
    assert client.get("/api/orders").json() == {"items": []}


@pytest.mark.parametrize(
    "key",
    ["short", "with space", "x" * 65, "", "kunci/aneh"],
)
def test_checkout_rejects_unbounded_checkout_keys(
    client: TestClient, seller: TestClient, key: str
) -> None:
    product = create_product(seller)
    schedule = open_schedule(seller, [product["id"]])
    offer = offer_for(schedule)

    response = client.post(
        "/api/orders",
        json=checkout_payload(
            schedule,
            [
                {
                    "offer_id": offer["id"],
                    "quantity": 1,
                    "quoted_price_rupiah": offer["price_rupiah"],
                }
            ],
            key=key,
        ),
        headers=csrf_headers(client),
    )

    assert response.status_code == 422, response.text
    assert client.get("/api/orders").json() == {"items": []}


def test_checkout_rejects_offers_outside_the_schedule(
    client: TestClient, seller: TestClient
) -> None:
    first = create_product(seller)
    second = create_product(seller, name="Roti Gandum Utuh")
    schedule_a = open_schedule(seller, [first["id"]])
    schedule_b = open_schedule(
        seller, [second["id"]], pickup_at="2035-12-08T18:00:00+07:00",
        order_cutoff_at="2035-12-06T20:00:00+07:00",
    )
    foreign = offer_for(schedule_b, "Roti Gandum Utuh")

    cross = client.post(
        "/api/orders",
        json=checkout_payload(
            schedule_a,
            [
                {
                    "offer_id": foreign["id"],
                    "quantity": 1,
                    "quoted_price_rupiah": foreign["price_rupiah"],
                }
            ],
            key="key-b008",
        ),
        headers=csrf_headers(client),
    )
    assert cross.status_code == 422, cross.text
    assert "penawaran" in cross.json()["detail"].lower()

    own = offer_for(schedule_a)
    duplicate = client.post(
        "/api/orders",
        json=checkout_payload(
            schedule_a,
            [
                {
                    "offer_id": own["id"],
                    "quantity": 1,
                    "quoted_price_rupiah": own["price_rupiah"],
                },
                {
                    "offer_id": own["id"],
                    "quantity": 2,
                    "quoted_price_rupiah": own["price_rupiah"],
                },
            ],
            key="key-b009",
        ),
        headers=csrf_headers(client),
    )
    assert duplicate.status_code == 422, duplicate.text
    assert client.get("/api/orders").json() == {"items": []}


def test_checkout_rejects_spoofed_owner_role_total_and_status(
    client: TestClient, seller: TestClient
) -> None:
    product = create_product(seller)
    schedule = open_schedule(seller, [product["id"]])
    offer = offer_for(schedule)
    base = checkout_payload(
        schedule,
        [
            {
                "offer_id": offer["id"],
                "quantity": 1,
                "quoted_price_rupiah": offer["price_rupiah"],
            }
        ],
        key="key-b010",
    )
    for field, value in (
        ("user_id", 999),
        ("owner_id", 999),
        ("role", "seller"),
        ("total_rupiah", 1),
        ("status", "selesai"),
        ("order_number", "PO-20260101-999999"),
    ):
        response = client.post(
            "/api/orders",
            json={**base, field: value},
            headers=csrf_headers(client),
        )
        assert response.status_code == 422, (field, response.text)
    assert client.get("/api/orders").json() == {"items": []}


def test_checkout_requires_a_buyer_session_and_csrf(
    client: TestClient, seller: TestClient
) -> None:
    product = create_product(seller)
    schedule = open_schedule(seller, [product["id"]])
    offer = offer_for(schedule)
    payload = checkout_payload(
        schedule,
        [
            {
                "offer_id": offer["id"],
                "quantity": 1,
                "quoted_price_rupiah": offer["price_rupiah"],
            }
        ],
        key="key-b011",
    )

    # Authentication is checked before Origin/CSRF, matching the T4 contract.
    anonymous = client.post("/api/orders", json=payload)
    assert anonymous.status_code == 403

    with TestClient(client.app) as anonymous_client:
        anonymous_client.get("/api/auth/session")
        assert anonymous_client.post("/api/orders", json=payload).status_code == 401

    assert (
        client.post("/api/orders", json=payload, headers={"Origin": ORIGIN}).status_code
        == 403
    )
    assert (
        client.post(
            "/api/orders",
            json=payload,
            headers={
                "Origin": "http://evil.example",
                "X-CSRF-Token": csrf_headers(client)["X-CSRF-Token"],
            },
        ).status_code
        == 403
    )

    assert (
        seller.post("/api/orders", json=payload, headers=csrf_headers(seller)).status_code
        == 403
    )
    assert client.get("/api/orders").json() == {"items": []}


def test_a_failed_item_rolls_back_the_whole_checkout(
    client: TestClient, seller: TestClient
) -> None:
    first = create_product(seller)
    second = create_product(seller, name="Roti Gandum Utuh")
    schedule = open_schedule(seller, [first["id"], second["id"]])
    valid = offer_for(schedule)
    limited = offer_for(schedule, "Roti Gandum Utuh")

    failed = client.post(
        "/api/orders",
        json=checkout_payload(
            schedule,
            [
                {
                    "offer_id": valid["id"],
                    "quantity": 2,
                    "quoted_price_rupiah": valid["price_rupiah"],
                },
                {
                    "offer_id": limited["id"],
                    "quantity": 7,
                    "quoted_price_rupiah": limited["price_rupiah"],
                },
            ],
            key="key-b012",
        ),
        headers=csrf_headers(client),
    )

    assert failed.status_code == 409, failed.text
    assert client.get("/api/orders").json() == {"items": []}

    # The valid line must not have consumed quota or created a partial order.
    retry = place_order(client, schedule, quantity=2, key="key-b013")
    assert retry["items"][0]["quantity"] == 2


def test_schedule_snapshot_shows_allocated_and_remaining_quota(
    client: TestClient, seller: TestClient
) -> None:
    product = create_product(seller)
    schedule = open_schedule(seller, [product["id"]])

    before = client.get("/api/schedules").json()["items"][0]["offers"][0]
    assert before["allocated_quantity"] == 0
    assert before["remaining_quota"] == 6

    place_order(client, schedule, quantity=2)

    after = client.get("/api/schedules").json()["items"][0]["offers"][0]
    assert after["allocated_quantity"] == 2
    assert after["remaining_quota"] == 4
    # The advertised quota stays the seller's maximum; allocation is separate.
    assert after["quota"] == 6


def test_schedule_offer_product_and_pickup_are_protected_after_checkout(
    client: TestClient, seller: TestClient
) -> None:
    product = create_product(seller)
    schedule = open_schedule(seller, [product["id"]])
    offer = offer_for(schedule)
    place_order(client, schedule, quantity=1, key="key-b014")
    headers = csrf_headers(seller)
    base = f"/api/seller/schedules/{schedule['id']}"

    pickup = seller.patch(
        base,
        json={"pickup_at": "2035-11-09T18:00:00+07:00"},
        headers=headers,
    )
    assert pickup.status_code == 409, pickup.text
    assert "pengambilan" in pickup.json()["detail"].lower()

    cutoff_only = seller.patch(
        base,
        json={"order_cutoff_at": "2035-11-07T20:00:00+07:00"},
        headers=headers,
    )
    assert cutoff_only.status_code == 200, cutoff_only.text

    offer_delete = seller.delete(f"{base}/offers/{offer['id']}", headers=headers)
    assert offer_delete.status_code == 409, offer_delete.text

    schedule_delete = seller.delete(base, headers=headers)
    assert schedule_delete.status_code == 409, schedule_delete.text

    product_delete = seller.delete(f"/api/seller/products/{product['id']}", headers=headers)
    assert product_delete.status_code == 409, product_delete.text

    # Archiving is not deletion: it hides the catalog row but keeps offers/orders.
    archived = seller.post(f"/api/seller/products/{product['id']}/archive", headers=headers)
    assert archived.status_code == 200, archived.text
    assert client.get(f"/api/products/{product['id']}").status_code == 404
    assert client.get("/api/orders").json()["items"][0]["items"][0]["product_name"] == (
        product["name"]
    )
    assert client.get("/api/schedules").json()["items"][0]["offers"][0]["product_id"] == (
        product["id"]
    )


def test_quota_cannot_drop_below_allocated_units(
    client: TestClient, seller: TestClient
) -> None:
    product = create_product(seller)
    schedule = open_schedule(seller, [product["id"]])
    offer = offer_for(schedule)
    place_order(client, schedule, quantity=2, key="key-b015")
    path = f"/api/seller/schedules/{schedule['id']}/offers/{offer['id']}"
    headers = csrf_headers(seller)

    too_low = seller.patch(path, json={"quota": 1}, headers=headers)
    assert too_low.status_code == 409, too_low.text
    assert "kuota" in too_low.json()["detail"].lower()

    at_allocation = seller.patch(path, json={"quota": 2}, headers=headers)
    assert at_allocation.status_code == 200, at_allocation.text
    assert at_allocation.json()["remaining_quota"] == 0

    increased = seller.patch(path, json={"quota": 5}, headers=headers)
    assert increased.status_code == 200, increased.text
    assert increased.json()["remaining_quota"] == 3

    assert client.get("/api/orders").json()["items"][0]["items"][0]["quantity"] == 2


def test_identical_checkout_retry_returns_the_original_order_even_after_success(
    client: TestClient, seller: TestClient, clock: MutableClock
) -> None:
    product = create_product(seller)
    schedule = open_schedule(seller, [product["id"]])
    offer = offer_for(schedule)
    payload = checkout_payload(
        schedule,
        [
            {
                "offer_id": offer["id"],
                "quantity": 6,
                "quoted_price_rupiah": offer["price_rupiah"],
            }
        ],
        key="key-b016",
    )
    first = client.post("/api/orders", json=payload, headers=csrf_headers(client))
    assert first.status_code == 201, first.text
    order = first.json()

    # Price changes, quota is exhausted, and the cutoff passes after success.
    price = seller.patch(
        f"/api/seller/schedules/{schedule['id']}/offers/{offer['id']}",
        json={"price_rupiah": 71000},
        headers=csrf_headers(seller),
    )
    assert price.status_code == 200, price.text
    clock.now = datetime(2035, 11, 6, 14, 0, 0)
    login(client, "pembeli@example.com", BUYER_PASSWORD)

    replay = client.post("/api/orders", json=payload, headers=csrf_headers(client))

    assert replay.status_code == 200, replay.text
    assert replay.json() == order
    assert client.get("/api/orders").json() == {"items": [order]}

    fresh_key = client.post(
        "/api/orders",
        json={**payload, "checkout_key": "key-b017"},
        headers=csrf_headers(client),
    )
    assert fresh_key.status_code == 409
    assert "batas po" in fresh_key.json()["detail"].lower()


def test_same_checkout_key_with_a_different_payload_is_rejected(
    client: TestClient, seller: TestClient
) -> None:
    product = create_product(seller)
    schedule = open_schedule(seller, [product["id"]])
    offer = offer_for(schedule)
    first = client.post(
        "/api/orders",
        json=checkout_payload(
            schedule,
            [
                {
                    "offer_id": offer["id"],
                    "quantity": 1,
                    "quoted_price_rupiah": offer["price_rupiah"],
                }
            ],
            key="key-b018",
        ),
        headers=csrf_headers(client),
    )
    assert first.status_code == 201, first.text

    changed = client.post(
        "/api/orders",
        json=checkout_payload(
            schedule,
            [
                {
                    "offer_id": offer["id"],
                    "quantity": 2,
                    "quoted_price_rupiah": offer["price_rupiah"],
                }
            ],
            key="key-b018",
        ),
        headers=csrf_headers(client),
    )

    assert changed.status_code == 409, changed.text
    assert "kunci" in changed.json()["detail"].lower()
    assert len(client.get("/api/orders").json()["items"]) == 1


def test_checkout_keys_are_scoped_per_buyer_and_a_new_key_creates_a_new_order(
    client: TestClient, seller: TestClient
) -> None:
    product = create_product(seller)
    schedule = open_schedule(seller, [product["id"]])
    payload = checkout_payload(
        schedule,
        [
            {
                "offer_id": offer_for(schedule)["id"],
                "quantity": 1,
                "quoted_price_rupiah": offer_for(schedule)["price_rupiah"],
            }
        ],
        key="key-b019",
    )
    first = client.post("/api/orders", json=payload, headers=csrf_headers(client))
    assert first.status_code == 201, first.text

    with TestClient(client.app) as other:
        register_buyer(other, "pembeli-kedua@example.com")
        other_order = other.post(
            "/api/orders", json=payload, headers=csrf_headers(other)
        )
        assert other_order.status_code == 201, other_order.text
        assert other_order.json()["id"] != first.json()["id"]
        assert other.get("/api/orders").json()["items"] == [other_order.json()]

    second_key = client.post(
        "/api/orders",
        json={**payload, "checkout_key": "key-b020"},
        headers=csrf_headers(client),
    )
    assert second_key.status_code == 201, second_key.text
    assert second_key.json()["id"] != first.json()["id"]
    assert len(client.get("/api/orders").json()["items"]) == 2


def run_in_parallel(calls: list[Any]) -> list[Any]:
    """Start real HTTP clients together; no database or business mocks."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    barrier = Barrier(len(calls))

    def run(call: Any) -> Any:
        barrier.wait(timeout=10)
        return call()

    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        futures = [pool.submit(run, call) for call in calls]
        return [future.result(timeout=30) for future in futures]


def test_two_buyers_racing_for_the_last_unit_never_oversell(
    client: TestClient, seller: TestClient
) -> None:
    product = create_product(seller)
    schedule = open_schedule(seller, [product["id"]])
    offer = offer_for(schedule)
    # Tighten the offer to one unit to make the race about the last unit.
    quota = seller.patch(
        f"/api/seller/schedules/{schedule['id']}/offers/{offer['id']}",
        json={"quota": 1},
        headers=csrf_headers(seller),
    )
    assert quota.status_code == 200, quota.text

    with TestClient(client.app) as other:
        register_buyer(other, "pembeli-race@example.com")
        payloads = []
        for index, buyer_client in enumerate((client, other)):
            payloads.append(
                (
                    buyer_client,
                    checkout_payload(
                        schedule,
                        [
                            {
                                "offer_id": offer["id"],
                                "quantity": 1,
                                "quoted_price_rupiah": offer["price_rupiah"],
                            }
                        ],
                        key=f"race-key-{index}",
                    ),
                )
            )
        results = run_in_parallel(
            [
                lambda buyer_client=buyer_client, payload=payload: buyer_client.post(
                    "/api/orders", json=payload, headers=csrf_headers(buyer_client)
                )
                for buyer_client, payload in payloads
            ]
        )

    statuses = sorted(result.status_code for result in results)
    assert statuses == [201, 409], [result.text for result in results]
    histories = [
        len(buyer_client.get("/api/orders").json()["items"])
        for buyer_client in (client, other)
    ]
    assert sorted(histories) == [0, 1]
    schedule_after = next(
        item
        for item in client.get("/api/schedules").json()["items"]
        if item["id"] == schedule["id"]
    )
    assert schedule_after["offers"][0]["allocated_quantity"] == 1
    assert schedule_after["offers"][0]["remaining_quota"] == 0


@pytest.mark.parametrize("wait_on_schedule_lock", [False, True])
def test_same_buyer_and_key_in_parallel_creates_one_order(
    client: TestClient, seller: TestClient, settings: Settings, wait_on_schedule_lock: bool
) -> None:
    product = create_product(seller)
    schedule = open_schedule(seller, [product["id"]])
    offer = offer_for(schedule)
    payload = checkout_payload(
        schedule,
        [
            {
                "offer_id": offer["id"],
                "quantity": 2,
                "quoted_price_rupiah": offer["price_rupiah"],
            }
        ],
        key="key-race-same",
    )
    token = csrf_headers(client)["X-CSRF-Token"]

    with TestClient(client.app) as twin:
        twin.cookies.update(client.cookies)

        def run(calls: list[Any]) -> list[Any]:
            if wait_on_schedule_lock:
                return run_while_schedule_locked(settings, schedule["id"], calls)
            return run_in_parallel(calls)

        results = run(
            [
                lambda c=client: c.post(
                    "/api/orders",
                    json=payload,
                    headers={"Origin": ORIGIN, "X-CSRF-Token": token},
                ),
                lambda c=twin: c.post(
                    "/api/orders",
                    json=payload,
                    headers={"Origin": ORIGIN, "X-CSRF-Token": token},
                ),
            ]
        )

    assert sorted(result.status_code for result in results) == [200, 201], [
        result.text for result in results
    ]
    assert results[0].json()["id"] == results[1].json()["id"]
    history = client.get("/api/orders").json()["items"]
    assert len(history) == 1
    assert history[0]["id"] == results[0].json()["id"]
    after = client.get("/api/schedules").json()["items"][0]["offers"][0]
    assert after["allocated_quantity"] == 2
    assert after["remaining_quota"] == 4


def test_conflicting_payloads_with_one_key_across_schedules_leave_one_order(
    client: TestClient, seller: TestClient
) -> None:
    first = create_product(seller)
    second = create_product(seller, name="Roti Gandum Utuh")
    schedule_a = open_schedule(seller, [first["id"]])
    schedule_b = open_schedule(
        seller,
        [second["id"]],
        pickup_at="2035-12-08T18:00:00+07:00",
        order_cutoff_at="2035-12-06T20:00:00+07:00",
    )
    offer_a = offer_for(schedule_a)
    offer_b = offer_for(schedule_b, "Roti Gandum Utuh")
    key = "key-race-conflict"
    payload_a = checkout_payload(
        schedule_a,
        [
            {
                "offer_id": offer_a["id"],
                "quantity": 1,
                "quoted_price_rupiah": offer_a["price_rupiah"],
            }
        ],
        key=key,
    )
    payload_b = checkout_payload(
        schedule_b,
        [
            {
                "offer_id": offer_b["id"],
                "quantity": 1,
                "quoted_price_rupiah": offer_b["price_rupiah"],
            }
        ],
        key=key,
    )
    token = csrf_headers(client)["X-CSRF-Token"]

    with TestClient(client.app) as twin:
        twin.cookies.update(client.cookies)
        results = run_in_parallel(
            [
                lambda: client.post(
                    "/api/orders",
                    json=payload_a,
                    headers={"Origin": ORIGIN, "X-CSRF-Token": token},
                ),
                lambda: twin.post(
                    "/api/orders",
                    json=payload_b,
                    headers={"Origin": ORIGIN, "X-CSRF-Token": token},
                ),
            ]
        )

    assert sorted(result.status_code for result in results) == [201, 409], [
        result.text for result in results
    ]
    loser_index = next(i for i, result in enumerate(results) if result.status_code == 409)
    retry = client.post(
        "/api/orders",
        json=(payload_a, payload_b)[loser_index],
        headers={"Origin": ORIGIN, "X-CSRF-Token": token},
    )
    assert retry.status_code == 409
    assert "isi pesanan yang berbeda" in retry.json()["detail"]
    assert len(client.get("/api/orders").json()["items"]) == 1
    schedules = {item["id"]: item for item in client.get("/api/schedules").json()["items"]}
    total_allocated = sum(
        offer["allocated_quantity"]
        for schedule in schedules.values()
        for offer in schedule["offers"]
    )
    assert total_allocated == 1


def test_clock_is_read_after_waiting_for_the_schedule_lock(
    client: TestClient, seller: TestClient, clock: MutableClock, settings: Settings
) -> None:
    product = create_product(seller)
    schedule = open_schedule(seller, [product["id"]])
    offer = offer_for(schedule)
    payload = checkout_payload(
        schedule,
        [
            {
                "offer_id": offer["id"],
                "quantity": 1,
                "quoted_price_rupiah": offer["price_rupiah"],
            }
        ],
        key="key-clock-wait",
    )
    clock.now = datetime(2035, 11, 6, 12, 0, 0)
    login(client, "pembeli@example.com", BUYER_PASSWORD)
    headers = csrf_headers(client)

    engine = make_engine(settings.database_url.get_secret_value())
    try:
        with engine.connect() as locker:
            transaction = locker.begin()
            locker.execute(
                text("SELECT id FROM schedules WHERE id = :id FOR UPDATE"),
                {"id": schedule["id"]},
            )

            from concurrent.futures import ThreadPoolExecutor

            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    lambda: client.post("/api/orders", json=payload, headers=headers)
                )
                # Wait until the request has read the early state and is blocked on
                # the schedule lock, then move the server clock past the cutoff.
                import time

                time.sleep(0.6)
                assert not future.done()
                clock.now = datetime(2035, 11, 6, 14, 0, 0)  # after the cutoff
                transaction.commit()
                result = future.result(timeout=20)
    finally:
        engine.dispose()

    assert result.status_code == 409, result.text
    assert "batas po" in result.json()["detail"].lower()
    assert client.get("/api/orders").json() == {"items": []}


def test_order_totals_beyond_32_bit_are_computed_and_stored(
    client: TestClient, seller: TestClient
) -> None:
    product_ids = []
    for index in range(50):
        product = create_product(
            seller,
            name=f"Roti Uji {index:02d}",
            price_rupiah=1_000_000,
        )
        product_ids.append(product["id"])
    schedule = open_schedule(
        seller,
        product_ids,
        offers=[{"product_id": product_id, "quota": 999} for product_id in product_ids],
    )

    response = client.post(
        "/api/orders",
        json=checkout_payload(
            schedule,
            [
                {
                    "offer_id": offer["id"],
                    "quantity": 999,
                    "quoted_price_rupiah": offer["price_rupiah"],
                }
                for offer in schedule["offers"]
            ],
            key="key-big-total",
        ),
        headers=csrf_headers(client),
    )

    assert response.status_code == 201, response.text
    order = response.json()
    expected = 50 * 999 * 1_000_000
    assert expected == 49_950_000_000
    assert order["total_rupiah"] == expected
    assert all(item["line_total_rupiah"] == 999_000_000 for item in order["items"])
    assert client.get(f"/api/orders/{order['id']}").json() == order


def test_last_unit_race_after_both_requests_waited_never_oversells(
    client: TestClient, seller: TestClient, settings: Settings
) -> None:
    """Both requests start, then wait on a real MySQL schedule lock.

    When they resume, every read that decides quota must be current, not the
    REPEATABLE READ snapshot taken before the wait.
    """
    import time
    from concurrent.futures import ThreadPoolExecutor

    product = create_product(seller)
    schedule = open_schedule(seller, [product["id"]])
    offer = offer_for(schedule)
    seller.patch(
        f"/api/seller/schedules/{schedule['id']}/offers/{offer['id']}",
        json={"quota": 1},
        headers=csrf_headers(seller),
    )

    with TestClient(client.app) as other:
        register_buyer(other, "pembeli-race-wait@example.com")
        payloads = [
            (
                buyer_client,
                checkout_payload(
                    schedule,
                    [
                        {
                            "offer_id": offer["id"],
                            "quantity": 1,
                            "quoted_price_rupiah": offer["price_rupiah"],
                        }
                    ],
                    key=f"wait-key-{index}",
                ),
            )
            for index, buyer_client in enumerate((client, other))
        ]
        engine = make_engine(settings.database_url.get_secret_value())
        try:
            with engine.connect() as locker:
                transaction = locker.begin()
                locker.execute(
                    text("SELECT id FROM schedules WHERE id = :id FOR UPDATE"),
                    {"id": schedule["id"]},
                )
                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures = [
                        pool.submit(
                            lambda buyer_client=buyer_client, payload=payload: (
                                buyer_client.post(
                                    "/api/orders",
                                    json=payload,
                                    headers=csrf_headers(buyer_client),
                                )
                            )
                        )
                        for buyer_client, payload in payloads
                    ]
                    time.sleep(0.6)
                    assert all(not future.done() for future in futures)
                    transaction.commit()
                    results = [future.result(timeout=20) for future in futures]
        finally:
            engine.dispose()

        assert sorted(result.status_code for result in results) == [201, 409], [
            result.text for result in results
        ]
        histories = [
            len(buyer_client.get("/api/orders").json()["items"])
            for buyer_client in (client, other)
        ]
        assert sorted(histories) == [0, 1]
        after = next(
            item
            for item in client.get("/api/schedules").json()["items"]
            if item["id"] == schedule["id"]
        )
        assert after["offers"][0]["allocated_quantity"] == 1
        assert after["offers"][0]["remaining_quota"] == 0


def run_while_schedule_locked(
    settings: Settings, schedule_id: int, calls: list[Any]
) -> list[Any]:
    """Hold the real MySQL schedule lock, start both calls, then release it."""
    import time
    from concurrent.futures import ThreadPoolExecutor

    engine = make_engine(settings.database_url.get_secret_value())
    try:
        with engine.connect() as locker:
            transaction = locker.begin()
            locker.execute(
                text("SELECT id FROM schedules WHERE id = :id FOR UPDATE"),
                {"id": schedule_id},
            )
            with ThreadPoolExecutor(max_workers=len(calls)) as pool:
                futures = [pool.submit(call) for call in calls]
                time.sleep(0.6)
                assert all(not future.done() for future in futures)
                transaction.commit()
                return [future.result(timeout=20) for future in futures]
    finally:
        engine.dispose()


def test_checkout_and_quota_reduction_share_one_schedule_lock(
    client: TestClient, seller: TestClient, settings: Settings
) -> None:
    product = create_product(seller)
    schedule = open_schedule(seller, [product["id"]])
    offer = offer_for(schedule)
    payload = checkout_payload(
        schedule,
        [
            {
                "offer_id": offer["id"],
                "quantity": 2,
                "quoted_price_rupiah": offer["price_rupiah"],
            }
        ],
        key="key-race-quota",
    )
    headers = csrf_headers(seller)
    buyer_headers = csrf_headers(client)

    checkout_result, quota_result = run_while_schedule_locked(
        settings,
        schedule["id"],
        [
            lambda: client.post("/api/orders", json=payload, headers=buyer_headers),
            lambda: seller.patch(
                f"/api/seller/schedules/{schedule['id']}/offers/{offer['id']}",
                json={"quota": 1},
                headers=headers,
            ),
        ],
    )

    assert checkout_result.status_code in {201, 409}, checkout_result.text
    assert quota_result.status_code in {200, 409}, quota_result.text
    assert (checkout_result.status_code == 201) != (quota_result.status_code == 200)
    after = next(
        item
        for item in client.get("/api/schedules").json()["items"]
        if item["id"] == schedule["id"]
    )["offers"][0]
    assert after["allocated_quantity"] <= after["quota"]
    if checkout_result.status_code == 201:
        assert after["allocated_quantity"] == 2
        assert after["quota"] == 6
    else:
        assert after["quota"] == 1
        assert after["allocated_quantity"] == 0


def test_checkout_and_schedule_delete_never_orphan_an_order(
    client: TestClient, seller: TestClient, settings: Settings
) -> None:
    product = create_product(seller)
    schedule = open_schedule(seller, [product["id"]])
    offer = offer_for(schedule)
    payload = checkout_payload(
        schedule,
        [
            {
                "offer_id": offer["id"],
                "quantity": 1,
                "quoted_price_rupiah": offer["price_rupiah"],
            }
        ],
        key="key-race-delete",
    )
    headers = csrf_headers(seller)
    buyer_headers = csrf_headers(client)

    checkout_result, delete_result = run_while_schedule_locked(
        settings,
        schedule["id"],
        [
            lambda: client.post("/api/orders", json=payload, headers=buyer_headers),
            lambda: seller.delete(
                f"/api/seller/schedules/{schedule['id']}", headers=headers
            ),
        ],
    )

    assert checkout_result.status_code in {201, 404, 409}, checkout_result.text
    assert delete_result.status_code in {204, 409}, delete_result.text
    assert (checkout_result.status_code == 201) != (delete_result.status_code == 204)
    orders = client.get("/api/orders").json()["items"]
    if checkout_result.status_code == 201:
        assert orders and orders[0]["schedule_id"] == schedule["id"]
        assert client.get("/api/schedules").json()["items"]
    else:
        assert orders == []
        assert client.get("/api/schedules").json() == {"items": []}


def test_checkout_and_pickup_change_keep_the_booked_pickup_consistent(
    client: TestClient, seller: TestClient, settings: Settings
) -> None:
    product = create_product(seller)
    schedule = open_schedule(seller, [product["id"]])
    offer = offer_for(schedule)
    payload = checkout_payload(
        schedule,
        [
            {
                "offer_id": offer["id"],
                "quantity": 1,
                "quoted_price_rupiah": offer["price_rupiah"],
            }
        ],
        key="key-race-pickup",
    )
    new_pickup = "2035-11-09T18:00:00+07:00"
    new_pickup_utc = "2035-11-09T11:00:00Z"
    headers = csrf_headers(seller)
    buyer_headers = csrf_headers(client)

    checkout_result, pickup_result = run_while_schedule_locked(
        settings,
        schedule["id"],
        [
            lambda: client.post("/api/orders", json=payload, headers=buyer_headers),
            lambda: seller.patch(
                f"/api/seller/schedules/{schedule['id']}",
                json={"pickup_at": new_pickup},
                headers=headers,
            ),
        ],
    )

    assert checkout_result.status_code == 201, checkout_result.text
    assert pickup_result.status_code in {200, 409}, pickup_result.text
    final_pickup = next(
        item
        for item in client.get("/api/schedules").json()["items"]
        if item["id"] == schedule["id"]
    )["pickup_at"]
    assert checkout_result.json()["pickup_at"] == final_pickup
    assert final_pickup in {PICKUP_UTC, new_pickup_utc}
    if pickup_result.status_code == 409:
        assert final_pickup == PICKUP_UTC
    else:
        assert final_pickup == new_pickup_utc
