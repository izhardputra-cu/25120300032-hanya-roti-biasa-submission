"""T6 payment reporting, manual verification, and cancellation through the API.

Every assertion reads a public API response from real MySQL. Concurrency cases
use separate HTTP clients/threads and a real InnoDB schedule lock.
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
CUTOFF_UTC = "2035-11-06T13:00:00Z"
REPORT_NOTE = "Transfer simulasi 31 Okt, pengirim A***, nominal pas."


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
        json={"name": "Pembeli Uji", "email": email, "password": BUYER_PASSWORD},
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


def open_schedule(client: TestClient, product_ids: list[int]) -> dict:
    payload = {
        "pickup_at": PICKUP_WIB,
        "order_cutoff_at": CUTOFF_WIB,
        "offers": [{"product_id": product_id, "quota": 6} for product_id in product_ids],
    }
    response = client.post("/api/seller/schedules", json=payload, headers=csrf_headers(client))
    assert response.status_code == 201, response.text
    return response.json()


def offer_for(schedule: dict, product_name: str = PRODUCT["name"]) -> dict:
    return next(offer for offer in schedule["offers"] if offer["product_name"] == product_name)


def place_order(
    client: TestClient, schedule: dict, quantity: int = 1, key: str = "key-t6001"
) -> dict:
    offer = offer_for(schedule)
    response = client.post(
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
        headers=csrf_headers(client),
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def clients(
    settings: Settings,
) -> Iterator[tuple[TestClient, TestClient, MutableClock]]:
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


def test_buyer_reports_a_transfer_note_without_marking_the_order_paid(
    client: TestClient, seller: TestClient
) -> None:
    product = create_product(seller)
    schedule = open_schedule(seller, [product["id"]])
    order = place_order(client, schedule, quantity=2)

    response = client.post(
        f"/api/orders/{order['id']}/transfer-report",
        json={"note": REPORT_NOTE},
        headers=csrf_headers(client),
    )

    assert response.status_code == 200, response.text
    reported = response.json()
    assert reported["status"] == "menunggu_pemeriksaan"
    assert reported["transfer_note"] == REPORT_NOTE
    assert reported["transfer_reported_at"] == "2026-01-01T08:00:00Z"
    assert reported["order_cutoff_at"] == CUTOFF_UTC
    assert reported["total_rupiah"] == 130000
    assert reported["verified_at"] is None
    assert reported["payment_received_rupiah"] is None
    assert reported["cancelled_at"] is None

    assert client.get(f"/api/orders/{order['id']}").json() == reported
    seller_view = seller.get(f"/api/orders/{order['id']}")
    assert seller_view.status_code == 200, seller_view.text
    assert seller_view.json() == reported


def test_seller_can_verify_a_checked_direct_transfer_without_a_buyer_report(
    client: TestClient, seller: TestClient
) -> None:
    product = create_product(seller)
    schedule = open_schedule(seller, [product["id"]])
    order = place_order(client, schedule, quantity=2)

    response = seller.post(
        f"/api/seller/orders/{order['id']}/verify",
        json={"received_total_rupiah": order["total_rupiah"]},
        headers=csrf_headers(seller),
    )

    assert response.status_code == 200, response.text
    verified = response.json()
    assert verified["status"] == "terkonfirmasi"
    assert verified["payment_received_rupiah"] == 130000
    assert verified["verified_at"] == "2026-01-01T08:00:00Z"
    assert verified["transfer_note"] is None
    assert verified["transfer_reported_at"] is None
    assert verified["cancelled_at"] is None
    assert client.get(f"/api/orders/{order['id']}").json() == verified


def test_a_mismatched_amount_never_marks_the_order_paid(
    client: TestClient, seller: TestClient
) -> None:
    product = create_product(seller)
    schedule = open_schedule(seller, [product["id"]])
    order = place_order(client, schedule, quantity=2)
    report = client.post(
        f"/api/orders/{order['id']}/transfer-report",
        json={"note": REPORT_NOTE},
        headers=csrf_headers(client),
    )
    assert report.status_code == 200, report.text

    for received in (order["total_rupiah"] - 1, order["total_rupiah"] + 1):
        response = seller.post(
            f"/api/seller/orders/{order['id']}/verify",
            json={"received_total_rupiah": received},
            headers=csrf_headers(seller),
        )
        assert response.status_code == 409, response.text
        current = client.get(f"/api/orders/{order['id']}").json()
        assert current["status"] == "menunggu_pemeriksaan"
        assert current["payment_received_rupiah"] is None
        assert current["verified_at"] is None
        assert current["transfer_note"] == REPORT_NOTE

    exact = seller.post(
        f"/api/seller/orders/{order['id']}/verify",
        json={"received_total_rupiah": order["total_rupiah"]},
        headers=csrf_headers(seller),
    )
    assert exact.status_code == 200, exact.text
    assert exact.json()["status"] == "terkonfirmasi"
    assert exact.json()["payment_received_rupiah"] == order["total_rupiah"]


def test_buyer_cancel_before_transfer_report_is_terminal_and_releases_quota_once(
    client: TestClient, seller: TestClient
) -> None:
    product = create_product(seller)
    schedule = open_schedule(seller, [product["id"]])
    order = place_order(client, schedule, quantity=2)
    allocated_before = next(
        item
        for item in client.get("/api/schedules").json()["items"]
        if item["id"] == schedule["id"]
    )["offers"][0]["allocated_quantity"]
    assert allocated_before == 2

    response = client.post(
        f"/api/orders/{order['id']}/cancel",
        json={},
        headers=csrf_headers(client),
    )

    assert response.status_code == 200, response.text
    cancelled = response.json()
    assert cancelled["status"] == "batal"
    assert cancelled["cancelled_at"] == "2026-01-01T08:00:00Z"
    assert cancelled["cancelled_by_role"] == "buyer"
    assert cancelled["cancellation_reason"] == ("Dibatalkan pembeli sebelum konfirmasi transfer.")
    assert cancelled["refund_outcome"] is None
    assert cancelled["verified_at"] is None
    after = next(
        item
        for item in client.get("/api/schedules").json()["items"]
        if item["id"] == schedule["id"]
    )["offers"][0]
    assert after["allocated_quantity"] == 0
    assert after["remaining_quota"] == after["quota"]

    repeated = client.post(
        f"/api/orders/{order['id']}/cancel",
        json={},
        headers=csrf_headers(client),
    )
    assert repeated.status_code == 409, repeated.text
    still = client.get(f"/api/orders/{order['id']}").json()
    assert still == cancelled
    after_repeat = next(
        item
        for item in client.get("/api/schedules").json()["items"]
        if item["id"] == schedule["id"]
    )["offers"][0]
    assert after_repeat["allocated_quantity"] == 0


def test_seller_cancel_records_reason_and_refund_declaration_and_is_terminal(
    client: TestClient, seller: TestClient
) -> None:
    product = create_product(seller)
    schedule = open_schedule(seller, [product["id"]])
    order = place_order(client, schedule, quantity=1)
    reason = "Batas kemampuan produksi berubah; pesanan tidak dapat dipenuhi."

    response = seller.post(
        f"/api/seller/orders/{order['id']}/cancel",
        json={"reason": reason, "refund_outcome": "no_funds_received"},
        headers=csrf_headers(seller),
    )

    assert response.status_code == 200, response.text
    cancelled = response.json()
    assert cancelled["status"] == "batal"
    assert cancelled["cancelled_by_role"] == "seller"
    assert cancelled["cancellation_reason"] == reason
    assert cancelled["refund_outcome"] == "no_funds_received"
    assert cancelled["cancelled_at"] == "2026-01-01T08:00:00Z"
    assert cancelled["verified_at"] is None
    after = next(
        item
        for item in client.get("/api/schedules").json()["items"]
        if item["id"] == schedule["id"]
    )["offers"][0]
    assert after["allocated_quantity"] == 0
    assert after["remaining_quota"] == after["quota"]

    repeated = seller.post(
        f"/api/seller/orders/{order['id']}/cancel",
        json={"reason": "Alasan kedua tidak boleh menimpa.", "refund_outcome": "refunded_manually"},
        headers=csrf_headers(seller),
    )
    assert repeated.status_code == 409, repeated.text
    assert client.get(f"/api/orders/{order['id']}").json() == cancelled


def test_a_verified_payment_cannot_be_cancelled_as_never_received(
    client: TestClient, seller: TestClient
) -> None:
    product = create_product(seller)
    schedule = open_schedule(seller, [product["id"]])
    order = place_order(client, schedule, quantity=2)
    verified = seller.post(
        f"/api/seller/orders/{order['id']}/verify",
        json={"received_total_rupiah": order["total_rupiah"]},
        headers=csrf_headers(seller),
    )
    assert verified.status_code == 200, verified.text

    refused = seller.post(
        f"/api/seller/orders/{order['id']}/cancel",
        json={
            "reason": "Pesanan tidak dapat dipenuhi karena jadwal berubah.",
            "refund_outcome": "no_funds_received",
        },
        headers=csrf_headers(seller),
    )
    assert refused.status_code == 409, refused.text
    current = client.get(f"/api/orders/{order['id']}").json()
    assert current["status"] == "terkonfirmasi"
    assert current["verified_at"] == "2026-01-01T08:00:00Z"
    assert current["payment_received_rupiah"] == order["total_rupiah"]
    assert current["cancelled_at"] is None

    reason = "Dana sudah dikembalikan manual di luar aplikasi sebelum pembatalan."
    cancelled = seller.post(
        f"/api/seller/orders/{order['id']}/cancel",
        json={"reason": reason, "refund_outcome": "refunded_manually"},
        headers=csrf_headers(seller),
    )
    assert cancelled.status_code == 200, cancelled.text
    final = cancelled.json()
    assert final["status"] == "batal"
    assert final["verified_at"] == "2026-01-01T08:00:00Z"
    assert final["payment_received_rupiah"] == order["total_rupiah"]
    assert final["refund_outcome"] == "refunded_manually"
    assert final["cancellation_reason"] == reason
    assert final["cancelled_by_role"] == "seller"
    after = next(
        item
        for item in client.get("/api/schedules").json()["items"]
        if item["id"] == schedule["id"]
    )["offers"][0]
    assert after["allocated_quantity"] == 0


def test_seller_worklist_and_detail_expose_buyer_contact_only_to_the_seller(
    client: TestClient, seller: TestClient
) -> None:
    product = create_product(seller)
    schedule = open_schedule(seller, [product["id"]])
    first = place_order(client, schedule, quantity=1, key="key-t6001")
    second = place_order(client, schedule, quantity=2, key="key-t6002")
    cancel = client.post(f"/api/orders/{first['id']}/cancel", json={}, headers=csrf_headers(client))
    assert cancel.status_code == 200, cancel.text

    worklist = seller.get("/api/seller/orders")

    assert worklist.status_code == 200, worklist.text
    items = worklist.json()["items"]
    assert [item["id"] for item in items] == [second["id"], first["id"]]
    assert all(item["buyer"]["email"] == "pembeli@example.com" for item in items)
    assert [item["status"] for item in items] == ["menunggu_pembayaran", "batal"]

    detail = seller.get(f"/api/seller/orders/{second['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["buyer"] == {
        "id": client.get("/api/me").json()["id"],
        "name": "Pembeli Uji",
        "email": "pembeli@example.com",
    }
    assert detail.json()["items"] == second["items"]

    assert client.get("/api/seller/orders").status_code == 403
    assert client.get(f"/api/seller/orders/{second['id']}").status_code == 403
    with TestClient(client.app) as anonymous:
        assert anonymous.get("/api/seller/orders").status_code == 401
        assert anonymous.get(f"/api/seller/orders/{second['id']}").status_code == 401
    assert seller.get("/api/seller/orders/999999").status_code == 404


@pytest.mark.parametrize(
    "note",
    ["", "   ", "ab", "x" * 201, None, 123, ["not", "text"]],
)
def test_transfer_report_rejects_unbounded_or_missing_notes(
    client: TestClient, seller: TestClient, note: object
) -> None:
    product = create_product(seller)
    schedule = open_schedule(seller, [product["id"]])
    order = place_order(client, schedule)

    response = client.post(
        f"/api/orders/{order['id']}/transfer-report",
        json={"note": note},
        headers=csrf_headers(client),
    )

    assert response.status_code == 422, response.text
    assert client.get(f"/api/orders/{order['id']}").json() == order


def test_transfer_report_rejects_extra_fields_and_wrong_access(
    client: TestClient, seller: TestClient
) -> None:
    product = create_product(seller)
    schedule = open_schedule(seller, [product["id"]])
    order = place_order(client, schedule)
    valid = {"note": REPORT_NOTE}

    extra = client.post(
        f"/api/orders/{order['id']}/transfer-report",
        json={**valid, "status": "terkonfirmasi"},
        headers=csrf_headers(client),
    )
    assert extra.status_code == 422, extra.text
    assert client.get(f"/api/orders/{order['id']}").json() == order

    assert client.post(f"/api/orders/{order['id']}/transfer-report", json=valid).status_code == 403
    assert (
        client.post(
            f"/api/orders/{order['id']}/transfer-report",
            json=valid,
            headers={
                "Origin": "https://evil.example",
                "X-CSRF-Token": csrf_headers(client)["X-CSRF-Token"],
            },
        ).status_code
        == 403
    )
    seller_attempt = seller.post(
        f"/api/orders/{order['id']}/transfer-report",
        json=valid,
        headers=csrf_headers(seller),
    )
    assert seller_attempt.status_code == 403, seller_attempt.text
    with TestClient(client.app) as other:
        register_buyer(other, "pembeli-lain@example.com")
        other_attempt = other.post(
            f"/api/orders/{order['id']}/transfer-report",
            json=valid,
            headers=csrf_headers(other),
        )
        assert other_attempt.status_code == 404, other_attempt.text
    with TestClient(client.app) as anonymous:
        assert (
            anonymous.post(f"/api/orders/{order['id']}/transfer-report", json=valid).status_code
            == 401
        )
    assert (
        client.post(
            "/api/orders/999999/transfer-report", json=valid, headers=csrf_headers(client)
        ).status_code
        == 404
    )


@pytest.mark.parametrize(
    "received",
    [0, -1, 999, 49_950_000_001, 130000.0, "130000", True, None],
)
def test_verification_rejects_invalid_received_amounts(
    client: TestClient, seller: TestClient, received: object
) -> None:
    product = create_product(seller)
    schedule = open_schedule(seller, [product["id"]])
    order = place_order(client, schedule, quantity=2)

    response = seller.post(
        f"/api/seller/orders/{order['id']}/verify",
        json={"received_total_rupiah": received},
        headers=csrf_headers(seller),
    )

    assert response.status_code == 422, response.text
    assert client.get(f"/api/orders/{order['id']}").json() == order


def test_verification_rejects_extra_fields_and_wrong_access(
    client: TestClient, seller: TestClient
) -> None:
    product = create_product(seller)
    schedule = open_schedule(seller, [product["id"]])
    order = place_order(client, schedule, quantity=2)
    valid = {"received_total_rupiah": 130000}

    extra = seller.post(
        f"/api/seller/orders/{order['id']}/verify",
        json={**valid, "status": "terkonfirmasi"},
        headers=csrf_headers(seller),
    )
    assert extra.status_code == 422, extra.text

    buyer_attempt = client.post(
        f"/api/seller/orders/{order['id']}/verify",
        json=valid,
        headers=csrf_headers(client),
    )
    assert buyer_attempt.status_code == 403, buyer_attempt.text
    with TestClient(client.app) as anonymous:
        assert (
            anonymous.post(f"/api/seller/orders/{order['id']}/verify", json=valid).status_code
            == 401
        )
    assert (
        seller.post(
            f"/api/seller/orders/{order['id']}/verify",
            json=valid,
            headers={
                "Origin": "https://evil.example",
                "X-CSRF-Token": csrf_headers(seller)["X-CSRF-Token"],
            },
        ).status_code
        == 403
    )
    assert seller.post(f"/api/seller/orders/{order['id']}/verify", json=valid).status_code == 403
    assert (
        seller.post(
            "/api/seller/orders/999999/verify", json=valid, headers=csrf_headers(seller)
        ).status_code
        == 404
    )


def test_cancellation_endpoints_reject_extra_fields_and_wrong_access(
    client: TestClient, seller: TestClient
) -> None:
    product = create_product(seller)
    schedule = open_schedule(seller, [product["id"]])
    order = place_order(client, schedule)

    for body in (None, {"status": "batal"}, {"reason": "diam-diam"}):
        response = client.post(
            f"/api/orders/{order['id']}/cancel",
            json=body,
            headers=csrf_headers(client),
        )
        assert response.status_code == 422, response.text

    assert client.post(f"/api/orders/{order['id']}/cancel", json={}).status_code == 403
    assert (
        client.post(
            f"/api/orders/{order['id']}/cancel",
            json={},
            headers={
                "Origin": "https://evil.example",
                "X-CSRF-Token": csrf_headers(client)["X-CSRF-Token"],
            },
        ).status_code
        == 403
    )
    seller_attempt = seller.post(
        f"/api/orders/{order['id']}/cancel", json={}, headers=csrf_headers(seller)
    )
    assert seller_attempt.status_code == 403, seller_attempt.text
    with TestClient(client.app) as other:
        register_buyer(other, "pembeli-batal-lain@example.com")
        assert (
            other.post(
                f"/api/orders/{order['id']}/cancel", json={}, headers=csrf_headers(other)
            ).status_code
            == 404
        )
    with TestClient(client.app) as anonymous:
        assert anonymous.post(f"/api/orders/{order['id']}/cancel", json={}).status_code == 401
    assert (
        client.post("/api/orders/999999/cancel", json={}, headers=csrf_headers(client)).status_code
        == 404
    )

    bad_bodies = [
        {},
        {"reason": "ab", "refund_outcome": "no_funds_received"},
        {"reason": "x" * 301, "refund_outcome": "no_funds_received"},
        {"reason": "Alasan yang cukup panjang.", "refund_outcome": "partial"},
        {"reason": "Alasan yang cukup panjang."},
        {
            "reason": "Alasan yang cukup panjang.",
            "refund_outcome": "no_funds_received",
            "status": "batal",
        },
    ]
    for body in bad_bodies:
        response = seller.post(
            f"/api/seller/orders/{order['id']}/cancel",
            json=body,
            headers=csrf_headers(seller),
        )
        assert response.status_code == 422, (body, response.text)
    assert (
        seller.post(
            f"/api/seller/orders/{order['id']}/cancel",
            json={"reason": "Alasan yang cukup panjang.", "refund_outcome": "no_funds_received"},
        ).status_code
        == 403
    )
    buyer_attempt = client.post(
        f"/api/seller/orders/{order['id']}/cancel",
        json={"reason": "Alasan yang cukup panjang.", "refund_outcome": "no_funds_received"},
        headers=csrf_headers(client),
    )
    assert buyer_attempt.status_code == 403, buyer_attempt.text
    with TestClient(client.app) as anonymous:
        assert (
            anonymous.post(
                f"/api/seller/orders/{order['id']}/cancel",
                json={
                    "reason": "Alasan yang cukup panjang.",
                    "refund_outcome": "no_funds_received",
                },
            ).status_code
            == 401
        )
    assert (
        seller.post(
            "/api/seller/orders/999999/cancel",
            json={"reason": "Alasan yang cukup panjang.", "refund_outcome": "no_funds_received"},
            headers=csrf_headers(seller),
        ).status_code
        == 404
    )
    assert client.get(f"/api/orders/{order['id']}").json() == order


def test_buyer_cannot_cancel_after_report_or_verification(
    client: TestClient, seller: TestClient
) -> None:
    product = create_product(seller)
    schedule = open_schedule(seller, [product["id"]])
    reported = place_order(client, schedule, key="key-t6101")
    assert (
        client.post(
            f"/api/orders/{reported['id']}/transfer-report",
            json={"note": REPORT_NOTE},
            headers=csrf_headers(client),
        ).status_code
        == 200
    )
    refused = client.post(
        f"/api/orders/{reported['id']}/cancel", json={}, headers=csrf_headers(client)
    )
    assert refused.status_code == 409, refused.text
    assert client.get(f"/api/orders/{reported['id']}").json()["status"] == "menunggu_pemeriksaan"

    verified = place_order(client, schedule, key="key-t6102")
    assert (
        seller.post(
            f"/api/seller/orders/{verified['id']}/verify",
            json={"received_total_rupiah": verified["total_rupiah"]},
            headers=csrf_headers(seller),
        ).status_code
        == 200
    )
    refused = client.post(
        f"/api/orders/{verified['id']}/cancel", json={}, headers=csrf_headers(client)
    )
    assert refused.status_code == 409, refused.text
    assert client.get(f"/api/orders/{verified['id']}").json()["status"] == "terkonfirmasi"


def test_repeated_actions_stabilize_after_verification_and_cancellation(
    client: TestClient, seller: TestClient
) -> None:
    product = create_product(seller)
    schedule = open_schedule(seller, [product["id"]])
    order = place_order(client, schedule, quantity=2)
    assert (
        client.post(
            f"/api/orders/{order['id']}/transfer-report",
            json={"note": REPORT_NOTE},
            headers=csrf_headers(client),
        ).status_code
        == 200
    )
    verified = seller.post(
        f"/api/seller/orders/{order['id']}/verify",
        json={"received_total_rupiah": order["total_rupiah"]},
        headers=csrf_headers(seller),
    )
    assert verified.status_code == 200, verified.text
    verified_facts = verified.json()

    repeated_verify = seller.post(
        f"/api/seller/orders/{order['id']}/verify",
        json={"received_total_rupiah": order["total_rupiah"] - 1},
        headers=csrf_headers(seller),
    )
    assert repeated_verify.status_code == 409, repeated_verify.text
    assert client.get(f"/api/orders/{order['id']}").json() == verified_facts

    reason = "Dana sudah dikembalikan manual; pesanan tidak jadi dipenuhi."
    cancelled = seller.post(
        f"/api/seller/orders/{order['id']}/cancel",
        json={"reason": reason, "refund_outcome": "refunded_manually"},
        headers=csrf_headers(seller),
    )
    assert cancelled.status_code == 200, cancelled.text
    cancelled_facts = cancelled.json()
    assert cancelled_facts["verified_at"] == verified_facts["verified_at"]
    assert cancelled_facts["payment_received_rupiah"] == order["total_rupiah"]
    assert cancelled_facts["refund_outcome"] == "refunded_manually"

    repeated_actions = [
        client.post(
            f"/api/orders/{order['id']}/transfer-report",
            json={"note": REPORT_NOTE},
            headers=csrf_headers(client),
        ),
        client.post(f"/api/orders/{order['id']}/cancel", json={}, headers=csrf_headers(client)),
        seller.post(
            f"/api/seller/orders/{order['id']}/verify",
            json={"received_total_rupiah": order["total_rupiah"]},
            headers=csrf_headers(seller),
        ),
        seller.post(
            f"/api/seller/orders/{order['id']}/cancel",
            json={
                "reason": "Alasan kedua tidak boleh menimpa.",
                "refund_outcome": "no_funds_received",
            },
            headers=csrf_headers(seller),
        ),
    ]
    assert [response.status_code for response in repeated_actions] == [409, 409, 409, 409]
    assert client.get(f"/api/orders/{order['id']}").json() == cancelled_facts
    after = next(
        item
        for item in client.get("/api/schedules").json()["items"]
        if item["id"] == schedule["id"]
    )["offers"][0]
    assert after["allocated_quantity"] == 0


def test_cutoff_only_blocks_new_checkout_and_late_actions_stay_manual(
    client: TestClient, seller: TestClient, clock: MutableClock
) -> None:
    product = create_product(seller)
    schedule = open_schedule(seller, [product["id"]])
    order = place_order(client, schedule, quantity=2)

    clock.now = datetime(2035, 11, 6, 13, 0, 0)  # exactly the shared cutoff
    # The session clock moved years ahead, so sign both accounts in at that time.
    login(client, "pembeli@example.com", BUYER_PASSWORD)
    login(seller, DEMO_SELLER_EMAIL, DEMO_SELLER_PASSWORD)
    still_waiting = client.get(f"/api/orders/{order['id']}")
    assert still_waiting.status_code == 200
    assert still_waiting.json()["status"] == "menunggu_pembayaran"
    assert still_waiting.json()["cancelled_at"] is None
    assert (
        next(
            item
            for item in client.get("/api/schedules").json()["items"]
            if item["id"] == schedule["id"]
        )["orders_open"]
        is False
    )

    offer = offer_for(schedule)
    late_checkout = client.post(
        "/api/orders",
        json={
            "checkout_key": "key-t6-late",
            "schedule_id": schedule["id"],
            "items": [
                {
                    "offer_id": offer["id"],
                    "quantity": 1,
                    "quoted_price_rupiah": offer["price_rupiah"],
                }
            ],
        },
        headers=csrf_headers(client),
    )
    assert late_checkout.status_code == 409, late_checkout.text

    report = client.post(
        f"/api/orders/{order['id']}/transfer-report",
        json={"note": "Transfer terlambat, dikirim setelah batas PO."},
        headers=csrf_headers(client),
    )
    assert report.status_code == 200, report.text
    assert report.json()["status"] == "menunggu_pemeriksaan"

    clock.now = datetime(2035, 11, 6, 14, 0, 0)  # one hour after the cutoff
    assert client.get(f"/api/orders/{order['id']}").json()["status"] == "menunggu_pemeriksaan"
    verified = seller.post(
        f"/api/seller/orders/{order['id']}/verify",
        json={"received_total_rupiah": order["total_rupiah"]},
        headers=csrf_headers(seller),
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["status"] == "terkonfirmasi"
    assert (
        next(
            item
            for item in client.get("/api/schedules").json()["items"]
            if item["id"] == schedule["id"]
        )["offers"][0]["allocated_quantity"]
        == 2
    )

    worklist = seller.get("/api/seller/orders").json()["items"]
    assert [item["id"] for item in worklist] == [order["id"]]
    assert worklist[0]["status"] == "terkonfirmasi"


def run_while_schedule_locked(settings: Settings, schedule_id: int, calls: list[Any]) -> list[Any]:
    """Hold the real MySQL schedule lock, start every call, then release it."""
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


def test_transfer_report_and_buyer_cancel_serialize_to_one_result(
    client: TestClient, seller: TestClient, settings: Settings
) -> None:
    product = create_product(seller)
    schedule = open_schedule(seller, [product["id"]])
    order = place_order(client, schedule, quantity=2)
    token = csrf_headers(client)["X-CSRF-Token"]
    headers = {"Origin": ORIGIN, "X-CSRF-Token": token}

    with TestClient(client.app) as twin:
        twin.cookies.update(client.cookies)
        report_result, cancel_result = run_while_schedule_locked(
            settings,
            schedule["id"],
            [
                lambda: client.post(
                    f"/api/orders/{order['id']}/transfer-report",
                    json={"note": REPORT_NOTE},
                    headers=headers,
                ),
                lambda: twin.post(f"/api/orders/{order['id']}/cancel", json={}, headers=headers),
            ],
        )

    assert sorted([report_result.status_code, cancel_result.status_code]) == [200, 409], [
        report_result.text,
        cancel_result.text,
    ]
    final = client.get(f"/api/orders/{order['id']}").json()
    after = next(
        item
        for item in client.get("/api/schedules").json()["items"]
        if item["id"] == schedule["id"]
    )["offers"][0]
    if report_result.status_code == 200:
        assert final["status"] == "menunggu_pemeriksaan"
        assert final["transfer_note"] == REPORT_NOTE
        assert final["cancelled_at"] is None
        assert after["allocated_quantity"] == 2
    else:
        assert final["status"] == "batal"
        assert final["cancelled_by_role"] == "buyer"
        assert final["transfer_note"] is None
        assert after["allocated_quantity"] == 0


def test_verification_and_buyer_cancel_cannot_both_win(
    client: TestClient, seller: TestClient, settings: Settings
) -> None:
    product = create_product(seller)
    schedule = open_schedule(seller, [product["id"]])
    order = place_order(client, schedule, quantity=2)
    buyer_headers = csrf_headers(client)
    seller_headers = csrf_headers(seller)

    verify_result, cancel_result = run_while_schedule_locked(
        settings,
        schedule["id"],
        [
            lambda: seller.post(
                f"/api/seller/orders/{order['id']}/verify",
                json={"received_total_rupiah": order["total_rupiah"]},
                headers=seller_headers,
            ),
            lambda: client.post(
                f"/api/orders/{order['id']}/cancel", json={}, headers=buyer_headers
            ),
        ],
    )

    assert sorted([verify_result.status_code, cancel_result.status_code]) == [200, 409], [
        verify_result.text,
        cancel_result.text,
    ]
    final = client.get(f"/api/orders/{order['id']}").json()
    after = next(
        item
        for item in client.get("/api/schedules").json()["items"]
        if item["id"] == schedule["id"]
    )["offers"][0]
    if verify_result.status_code == 200:
        assert final["status"] == "terkonfirmasi"
        assert final["payment_received_rupiah"] == order["total_rupiah"]
        assert final["cancelled_at"] is None
        assert after["allocated_quantity"] == 2
    else:
        assert final["status"] == "batal"
        assert final["cancelled_by_role"] == "buyer"
        assert final["verified_at"] is None
        assert after["allocated_quantity"] == 0


def test_verification_and_seller_cancel_follow_a_legal_serial_order(
    client: TestClient, seller: TestClient, settings: Settings
) -> None:
    product = create_product(seller)
    schedule = open_schedule(seller, [product["id"]])
    order = place_order(client, schedule, quantity=2)
    token = csrf_headers(seller)["X-CSRF-Token"]
    headers = {"Origin": ORIGIN, "X-CSRF-Token": token}
    reason = "Dana sudah dikembalikan manual setelah pemeriksaan."

    with TestClient(client.app) as twin:
        twin.cookies.update(seller.cookies)
        verify_result, cancel_result = run_while_schedule_locked(
            settings,
            schedule["id"],
            [
                lambda: seller.post(
                    f"/api/seller/orders/{order['id']}/verify",
                    json={"received_total_rupiah": order["total_rupiah"]},
                    headers=headers,
                ),
                lambda: twin.post(
                    f"/api/seller/orders/{order['id']}/cancel",
                    json={"reason": reason, "refund_outcome": "refunded_manually"},
                    headers=headers,
                ),
            ],
        )

    assert cancel_result.status_code == 200, cancel_result.text
    assert verify_result.status_code in {200, 409}, verify_result.text
    final = client.get(f"/api/orders/{order['id']}").json()
    assert final["status"] == "batal"
    assert final["cancelled_by_role"] == "seller"
    assert final["refund_outcome"] == "refunded_manually"
    if verify_result.status_code == 200:
        assert final["verified_at"] is not None
        assert final["payment_received_rupiah"] == order["total_rupiah"]
    else:
        assert final["verified_at"] is None
        assert final["payment_received_rupiah"] is None
    after = next(
        item
        for item in client.get("/api/schedules").json()["items"]
        if item["id"] == schedule["id"]
    )["offers"][0]
    assert after["allocated_quantity"] == 0
    repeated = seller.post(
        f"/api/seller/orders/{order['id']}/cancel",
        json={"reason": "Alasan kedua tidak boleh menimpa.", "refund_outcome": "no_funds_received"},
        headers=csrf_headers(seller),
    )
    assert repeated.status_code == 409, repeated.text
    assert client.get(f"/api/orders/{order['id']}").json() == final


def test_cancel_and_a_competing_checkout_release_quota_at_most_once(
    client: TestClient, seller: TestClient, settings: Settings
) -> None:
    product = create_product(seller)
    schedule = open_schedule(seller, [product["id"]])
    offer = offer_for(schedule)
    quota = seller.patch(
        f"/api/seller/schedules/{schedule['id']}/offers/{offer['id']}",
        json={"quota": 2},
        headers=csrf_headers(seller),
    )
    assert quota.status_code == 200, quota.text
    schedule = client.get("/api/schedules").json()["items"][0]
    offer = offer_for(schedule)
    order = place_order(client, schedule, quantity=2)
    buyer_headers = csrf_headers(client)

    with TestClient(client.app) as competing_buyer:
        register_buyer(competing_buyer, "pembeli-kuota@example.com")
        competing_headers = csrf_headers(competing_buyer)
        checkout_payload = {
            "checkout_key": "key-t6-quota",
            "schedule_id": schedule["id"],
            "items": [
                {
                    "offer_id": offer["id"],
                    "quantity": 1,
                    "quoted_price_rupiah": offer["price_rupiah"],
                }
            ],
        }
        cancel_result, checkout_result = run_while_schedule_locked(
            settings,
            schedule["id"],
            [
                lambda: client.post(
                    f"/api/orders/{order['id']}/cancel", json={}, headers=buyer_headers
                ),
                lambda: competing_buyer.post(
                    "/api/orders", json=checkout_payload, headers=competing_headers
                ),
            ],
        )

    assert cancel_result.status_code == 200, cancel_result.text
    assert checkout_result.status_code in {201, 409}, checkout_result.text
    after = next(
        item
        for item in client.get("/api/schedules").json()["items"]
        if item["id"] == schedule["id"]
    )["offers"][0]
    if checkout_result.status_code == 201:
        assert after["allocated_quantity"] == 1
    else:
        assert after["allocated_quantity"] == 0
    assert after["allocated_quantity"] <= after["quota"]
    assert client.get(f"/api/orders/{order['id']}").json()["status"] == "batal"


def test_buyer_cancel_is_not_gated_by_the_shared_cutoff(
    client: TestClient, seller: TestClient, clock: MutableClock
) -> None:
    product = create_product(seller)
    schedule = open_schedule(seller, [product["id"]])
    order = place_order(client, schedule, quantity=1)

    clock.now = datetime(2035, 11, 7, 9, 0, 0)  # after the cutoff
    login(client, "pembeli@example.com", BUYER_PASSWORD)
    response = client.post(
        f"/api/orders/{order['id']}/cancel", json={}, headers=csrf_headers(client)
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "batal"
    offer = offer_for(schedule)
    late_checkout = client.post(
        "/api/orders",
        json={
            "checkout_key": "key-t6-after-cutoff",
            "schedule_id": schedule["id"],
            "items": [
                {
                    "offer_id": offer["id"],
                    "quantity": 1,
                    "quoted_price_rupiah": offer["price_rupiah"],
                }
            ],
        },
        headers=csrf_headers(client),
    )
    assert late_checkout.status_code == 409, late_checkout.text


def test_seller_can_cancel_a_reported_order_after_inspecting_the_funds(
    client: TestClient, seller: TestClient
) -> None:
    product = create_product(seller)
    schedule = open_schedule(seller, [product["id"]])
    order = place_order(client, schedule, quantity=1)
    assert (
        client.post(
            f"/api/orders/{order['id']}/transfer-report",
            json={"note": REPORT_NOTE},
            headers=csrf_headers(client),
        ).status_code
        == 200
    )

    reason = "Dana tidak ditemukan pada pemeriksaan, pesanan dibatalkan."
    response = seller.post(
        f"/api/seller/orders/{order['id']}/cancel",
        json={"reason": reason, "refund_outcome": "no_funds_received"},
        headers=csrf_headers(seller),
    )

    assert response.status_code == 200, response.text
    final = response.json()
    assert final["status"] == "batal"
    assert final["transfer_note"] == REPORT_NOTE
    assert final["refund_outcome"] == "no_funds_received"
    assert final["cancelled_by_role"] == "seller"
    assert final["verified_at"] is None
