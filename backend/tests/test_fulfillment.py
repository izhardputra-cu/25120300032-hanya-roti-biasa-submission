"""T7 production recap and pickup fulfillment through the real public API.

Every expected recap number below is written by hand from the fixture quantities
described in the test, never computed with the app's own query or helper.
Concurrency cases use two HTTP clients and the real InnoDB schedule lock.
"""

import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
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
BUYER_EMAIL = "pembeli@example.com"
REPORT_NOTE = "Transfer simulasi 31 Okt, pengirim A***, nominal pas."
REFUND_REASON = "Pesanan tidak dapat dipenuhi; dana sudah dikembalikan manual."

CLASSIC = {
    "name": "Sourdough Klasik",
    "selling_unit": "1 loaf 500 gram",
    "price_rupiah": 65000,
    "description": "Roti asam sederhana. Data demo.",
}
WHOLE = {
    "name": "Sourdough Gandum Utuh",
    "selling_unit": "1 pak 4 irisan",
    "price_rupiah": 72000,
    "description": "Roti gandum utuh. Data demo.",
}

FIRST_PICKUP = ("2035-11-08T18:00:00+07:00", "2035-11-08T11:00:00Z")
FIRST_CUTOFF = ("2035-11-06T20:00:00+07:00", "2035-11-06T13:00:00Z")
SECOND_PICKUP = ("2035-11-09T18:00:00+07:00", "2035-11-09T11:00:00Z")
SECOND_CUTOFF = ("2035-11-07T20:00:00+07:00", "2035-11-07T13:00:00Z")
THIRD_PICKUP = ("2035-11-10T18:00:00+07:00", "2035-11-10T11:00:00Z")
THIRD_CUTOFF = ("2035-11-08T20:00:00+07:00", "2035-11-08T13:00:00Z")


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


def register_buyer(client: TestClient, email: str = BUYER_EMAIL) -> None:
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


def create_product(client: TestClient, product: dict[str, Any]) -> dict[str, Any]:
    response = client.post(
        "/api/seller/products", json=product, headers=csrf_headers(client)
    )
    assert response.status_code == 201, response.text
    return response.json()


def open_schedule(
    client: TestClient,
    offers: list[tuple[int, int]],
    pickup: tuple[str, str] = FIRST_PICKUP,
    cutoff: tuple[str, str] = FIRST_CUTOFF,
) -> dict[str, Any]:
    payload = {
        "pickup_at": pickup[0],
        "order_cutoff_at": cutoff[0],
        "offers": [{"product_id": product_id, "quota": quota} for product_id, quota in offers],
    }
    response = client.post(
        "/api/seller/schedules", json=payload, headers=csrf_headers(client)
    )
    assert response.status_code == 201, response.text
    return response.json()


def offer_of(schedule: dict[str, Any], product: dict[str, Any]) -> dict[str, Any]:
    return next(
        offer for offer in schedule["offers"] if offer["product_name"] == product["name"]
    )


def place_order(
    client: TestClient,
    schedule: dict[str, Any],
    items: list[tuple[int, int]],
    key: str,
) -> dict[str, Any]:
    offers = {offer["id"]: offer for offer in schedule["offers"]}
    response = client.post(
        "/api/orders",
        json={
            "checkout_key": key,
            "schedule_id": schedule["id"],
            "items": [
                {
                    "offer_id": offer_id,
                    "quantity": quantity,
                    "quoted_price_rupiah": offers[offer_id]["price_rupiah"],
                }
                for offer_id, quantity in items
            ],
        },
        headers=csrf_headers(client),
    )
    assert response.status_code == 201, response.text
    return response.json()


def report_transfer(client: TestClient, order: dict[str, Any]) -> dict[str, Any]:
    response = client.post(
        f"/api/orders/{order['id']}/transfer-report",
        json={"note": REPORT_NOTE},
        headers=csrf_headers(client),
    )
    assert response.status_code == 200, response.text
    return response.json()


def verify_payment(seller: TestClient, order: dict[str, Any]) -> dict[str, Any]:
    response = seller.post(
        f"/api/seller/orders/{order['id']}/verify",
        json={"received_total_rupiah": order["total_rupiah"]},
        headers=csrf_headers(seller),
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "terkonfirmasi"
    return response.json()


def mark_ready(seller: TestClient, order: dict[str, Any]) -> dict[str, Any]:
    response = seller.post(
        f"/api/seller/orders/{order['id']}/ready",
        json={},
        headers=csrf_headers(seller),
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "siap_diambil"
    return response.json()


def mark_complete(seller: TestClient, order: dict[str, Any]) -> dict[str, Any]:
    response = seller.post(
        f"/api/seller/orders/{order['id']}/complete",
        json={},
        headers=csrf_headers(seller),
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "selesai"
    return response.json()


def seller_cancel(
    seller: TestClient, order: dict[str, Any], refund_outcome: str
) -> Any:
    return seller.post(
        f"/api/seller/orders/{order['id']}/cancel",
        json={"reason": REFUND_REASON, "refund_outcome": refund_outcome},
        headers=csrf_headers(seller),
    )


def recap_of(seller: TestClient, schedule: dict[str, Any]) -> dict[str, Any]:
    response = seller.get("/api/seller/production-recap")
    assert response.status_code == 200, response.text
    return next(
        item for item in response.json()["items"] if item["schedule_id"] == schedule["id"]
    )


def allocated_for(client: TestClient, schedule: dict[str, Any], offer_id: int) -> int:
    schedules = client.get("/api/schedules").json()["items"]
    schedule_view = next(item for item in schedules if item["id"] == schedule["id"])
    offer = next(offer for offer in schedule_view["offers"] if offer["id"] == offer_id)
    return offer["allocated_quantity"]


@pytest.fixture
def actors(
    settings: Settings,
) -> Iterator[tuple[TestClient, TestClient, MutableClock]]:
    clock = MutableClock()
    app = create_app(settings, clock=clock)
    with TestClient(app) as buyer, TestClient(app) as seller:
        seed_demo_seller(settings)
        login(seller, DEMO_SELLER_EMAIL, DEMO_SELLER_PASSWORD)
        register_buyer(buyer)
        yield buyer, seller, clock


def buyer_fields(seller_view: dict[str, Any]) -> dict[str, Any]:
    """Buyer order views intentionally omit the seller-only buyer contact block."""
    return {key: value for key, value in seller_view.items() if key != "buyer"}


def test_recap_sums_paid_live_quantities_per_schedule(actors) -> None:
    buyer, seller, _clock = actors
    classic = create_product(seller, CLASSIC)
    whole = create_product(seller, WHOLE)
    schedule = open_schedule(seller, [(classic["id"], 40), (whole["id"], 40)])
    later = open_schedule(
        seller,
        [(classic["id"], 20)],
        pickup=SECOND_PICKUP,
        cutoff=SECOND_CUTOFF,
    )
    untouched = open_schedule(
        seller,
        [(whole["id"], 20)],
        pickup=THIRD_PICKUP,
        cutoff=THIRD_CUTOFF,
    )
    offers = {
        "classic": offer_of(schedule, classic),
        "whole": offer_of(schedule, whole),
    }

    # Excluded: no verified payment yet.
    place_order(
        buyer,
        schedule,
        [(offers["classic"]["id"], 2), (offers["whole"]["id"], 1)],
        "t7-recap-01",
    )
    reported = place_order(buyer, schedule, [(offers["classic"]["id"], 3)], "t7-recap-02")
    report_transfer(buyer, reported)
    # Included: terkonfirmasi, siap_diambil, and selesai all stay in production.
    confirmed = place_order(
        buyer,
        schedule,
        [(offers["classic"]["id"], 1), (offers["whole"]["id"], 4)],
        "t7-recap-03",
    )
    verify_payment(seller, confirmed)
    ready_order = place_order(
        buyer, schedule, [(offers["classic"]["id"], 2)], "t7-recap-04"
    )
    verify_payment(seller, ready_order)
    mark_ready(seller, ready_order)
    done_order = place_order(
        buyer, schedule, [(offers["whole"]["id"], 3)], "t7-recap-05"
    )
    verify_payment(seller, done_order)
    mark_ready(seller, done_order)
    mark_complete(seller, done_order)
    # Excluded: cancelled before payment, before verification, and after ready.
    buyer_cancelled = place_order(
        buyer, schedule, [(offers["classic"]["id"], 5)], "t7-recap-06"
    )
    assert (
        buyer.post(
            f"/api/orders/{buyer_cancelled['id']}/cancel",
            json={},
            headers=csrf_headers(buyer),
        ).status_code
        == 200
    )
    seller_cancelled = place_order(
        buyer, schedule, [(offers["whole"]["id"], 2)], "t7-recap-07"
    )
    assert seller_cancel(seller, seller_cancelled, "no_funds_received").status_code == 200
    ready_cancelled = place_order(
        buyer, schedule, [(offers["classic"]["id"], 4)], "t7-recap-08"
    )
    verify_payment(seller, ready_cancelled)
    mark_ready(seller, ready_cancelled)
    assert seller_cancel(seller, ready_cancelled, "refunded_manually").status_code == 200
    # A different schedule keeps its own independent quantity.
    later_offers = offer_of(later, classic)
    later_order = place_order(
        buyer, later, [(later_offers["id"], 6)], "t7-recap-09"
    )
    verify_payment(seller, later_order)
    # A schedule holding only an unpaid order shows an explicit empty recap.
    empty_offers = offer_of(untouched, whole)
    place_order(buyer, untouched, [(empty_offers["id"], 2)], "t7-recap-10")

    response = seller.get("/api/seller/production-recap")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["included_statuses"] == ["terkonfirmasi", "siap_diambil", "selesai"]
    items = payload["items"]
    assert [item["schedule_id"] for item in items] == [
        schedule["id"],
        later["id"],
        untouched["id"],
    ]
    main = next(item for item in items if item["schedule_id"] == schedule["id"])
    assert main["pickup_at"] == FIRST_PICKUP[1]
    assert main["order_cutoff_at"] == FIRST_CUTOFF[1]
    assert main["orders_open"] is True
    assert [
        (line["product_name"], line["selling_unit"], line["quantity"])
        for line in main["lines"]
    ] == [
        (CLASSIC["name"], CLASSIC["selling_unit"], 3),
        (WHOLE["name"], WHOLE["selling_unit"], 7),
    ]
    assert main["total_quantity"] == 10
    assert all(line["product_id"] > 0 and line["offer_id"] > 0 for line in main["lines"])

    other = next(item for item in items if item["schedule_id"] == later["id"])
    assert [(line["product_name"], line["quantity"]) for line in other["lines"]] == [
        (CLASSIC["name"], 6)
    ]
    assert other["total_quantity"] == 6

    empty = next(item for item in items if item["schedule_id"] == untouched["id"])
    assert empty["lines"] == []
    assert empty["total_quantity"] == 0


def test_recap_keeps_quantities_after_ready_and_completion(actors) -> None:
    buyer, seller, _clock = actors
    classic = create_product(seller, CLASSIC)
    schedule = open_schedule(seller, [(classic["id"], 9)])
    offer = offer_of(schedule, classic)
    order = place_order(buyer, schedule, [(offer["id"], 4)], "t7-stay-01")
    verify_payment(seller, order)

    before = recap_of(seller, schedule)
    assert before["total_quantity"] == 4
    mark_ready(seller, order)
    ready_recap = recap_of(seller, schedule)
    assert ready_recap == before
    assert allocated_for(buyer, schedule, offer["id"]) == 4

    mark_complete(seller, order)
    after = recap_of(seller, schedule)
    assert after == before
    assert after["lines"][0]["quantity"] == 4
    # Completion never releases the derived quota allocation.
    assert allocated_for(buyer, schedule, offer["id"]) == 4
    buyer_view = buyer.get(f"/api/orders/{order['id']}")
    assert buyer_view.status_code == 200
    assert buyer_view.json()["status"] == "selesai"
    # Verified payment facts stay untouched by fulfillment.
    assert buyer_view.json()["payment_received_rupiah"] == order["total_rupiah"]
    assert buyer_view.json()["verified_at"] == "2026-01-01T08:00:00Z"
    assert buyer_view.json()["cancelled_at"] is None


def test_seller_marks_ready_then_complete_and_the_buyer_only_monitors(
    actors,
) -> None:
    buyer, seller, _clock = actors
    classic = create_product(seller, CLASSIC)
    schedule = open_schedule(seller, [(classic["id"], 6)])
    offer = offer_of(schedule, classic)
    order = place_order(buyer, schedule, [(offer["id"], 2)], "t7-flow-01")
    verify_payment(seller, order)

    ready = seller.post(
        f"/api/seller/orders/{order['id']}/ready",
        json={},
        headers=csrf_headers(seller),
    )
    assert ready.status_code == 200, ready.text
    ready_view = ready.json()
    assert ready_view["status"] == "siap_diambil"
    assert ready_view["order_number"] == order["order_number"]
    assert ready_view["items"] == order["items"]
    assert ready_view["buyer"]["email"] == BUYER_EMAIL
    assert ready_view["cancelled_at"] is None

    buyer_sees = buyer.get(f"/api/orders/{order['id']}")
    assert buyer_sees.status_code == 200
    assert buyer_sees.json() == buyer_fields(ready_view)
    history = buyer.get("/api/orders").json()["items"]
    assert [(item["id"], item["status"]) for item in history] == [
        (order["id"], "siap_diambil")
    ]
    assert buyer.get(f"/api/seller/orders/{order['id']}").status_code == 403

    done = seller.post(
        f"/api/seller/orders/{order['id']}/complete",
        json={},
        headers=csrf_headers(seller),
    )
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "selesai"
    assert buyer.get(f"/api/orders/{order['id']}").json()["status"] == "selesai"
    worklist = seller.get("/api/seller/orders").json()["items"]
    assert [(item["id"], item["status"]) for item in worklist] == [(order["id"], "selesai")]

    # The buyer can never perform a seller transition.
    for path in ("ready", "complete"):
        refused = buyer.post(
            f"/api/seller/orders/{order['id']}/{path}",
            json={},
            headers=csrf_headers(buyer),
        )
        assert refused.status_code == 403, refused.text
    with TestClient(buyer.app) as other:
        register_buyer(other, "pembeli-lain@example.com")
        assert other.get(f"/api/orders/{order['id']}").status_code == 404
    with TestClient(buyer.app) as anonymous:
        assert (
            anonymous.post(f"/api/seller/orders/{order['id']}/ready", json={}).status_code
            == 401
        )
        assert anonymous.get("/api/seller/production-recap").status_code == 401
        assert anonymous.get("/api/seller/orders").status_code == 401
    assert buyer.get("/api/seller/production-recap").status_code == 403
    missing = "/api/seller/orders/999999"
    for path in ("ready", "complete"):
        response = seller.post(
            f"{missing}/{path}", json={}, headers=csrf_headers(seller)
        )
        assert response.status_code == 404, response.text


@pytest.mark.parametrize(
    "body",
    [{"status": "selesai"}, {"note": "x"}, ["ready"], "ready", 7],
)
def test_fulfillment_actions_reject_unexpected_payloads(actors, body: object) -> None:
    buyer, seller, _clock = actors
    classic = create_product(seller, CLASSIC)
    schedule = open_schedule(seller, [(classic["id"], 6)])
    offer = offer_of(schedule, classic)
    order = place_order(buyer, schedule, [(offer["id"], 1)], "t7-strict-01")
    verify_payment(seller, order)

    for path in ("ready", "complete"):
        response = seller.post(
            f"/api/seller/orders/{order['id']}/{path}",
            json=body,
            headers=csrf_headers(seller),
        )
        assert response.status_code == 422, (path, response.text)
    assert buyer.get(f"/api/orders/{order['id']}").json() == order | {
        "status": "terkonfirmasi",
        "verified_at": "2026-01-01T08:00:00Z",
        "payment_received_rupiah": order["total_rupiah"],
    }

    no_csrf = seller.post(f"/api/seller/orders/{order['id']}/ready", json={})
    assert no_csrf.status_code == 403, no_csrf.text
    bad_origin = seller.post(
        f"/api/seller/orders/{order['id']}/ready",
        json={},
        headers={
            "Origin": "https://evil.example",
            "X-CSRF-Token": csrf_headers(seller)["X-CSRF-Token"],
        },
    )
    assert bad_origin.status_code == 403, bad_origin.text


def test_illegal_and_repeated_transitions_leave_facts_untouched(actors) -> None:
    buyer, seller, _clock = actors
    classic = create_product(seller, CLASSIC)
    schedule = open_schedule(seller, [(classic["id"], 10)])
    offer = offer_of(schedule, classic)
    waiting = place_order(buyer, schedule, [(offer["id"], 1)], "t7-illegal-01")
    confirmed = place_order(buyer, schedule, [(offer["id"], 1)], "t7-illegal-02")
    verify_payment(seller, confirmed)
    done = place_order(buyer, schedule, [(offer["id"], 1)], "t7-illegal-03")
    verify_payment(seller, done)
    mark_ready(seller, done)
    mark_complete(seller, done)

    ready_path = f"/api/seller/orders/{waiting['id']}/ready"
    complete_path = f"/api/seller/orders/{confirmed['id']}/complete"
    for path in (ready_path, complete_path):
        response = seller.post(path, json={}, headers=csrf_headers(seller))
        assert response.status_code == 409, (path, response.text)

    facts = buyer.get(f"/api/orders/{waiting['id']}").json()
    assert facts["status"] == "menunggu_pembayaran"
    assert facts["verified_at"] is None
    assert facts["cancelled_at"] is None
    assert buyer.get(f"/api/orders/{confirmed['id']}").json()["status"] == "terkonfirmasi"

    # Repeating a successful step is rejected and does not overwrite anything.
    ready_order = place_order(buyer, schedule, [(offer["id"], 1)], "t7-illegal-04")
    verify_payment(seller, ready_order)
    ready_facts = mark_ready(seller, ready_order)
    repeated_ready = seller.post(
        f"/api/seller/orders/{ready_order['id']}/ready",
        json={},
        headers=csrf_headers(seller),
    )
    assert repeated_ready.status_code == 409, repeated_ready.text
    verify_after_ready = seller.post(
        f"/api/seller/orders/{ready_order['id']}/verify",
        json={"received_total_rupiah": ready_order["total_rupiah"]},
        headers=csrf_headers(seller),
    )
    assert verify_after_ready.status_code == 409, verify_after_ready.text
    assert buyer.get(f"/api/orders/{ready_order['id']}").json() == buyer_fields(
        ready_facts
    )

    done_facts = buyer.get(f"/api/orders/{done['id']}").json()
    repeated_complete = seller.post(
        f"/api/seller/orders/{done['id']}/complete",
        json={},
        headers=csrf_headers(seller),
    )
    assert repeated_complete.status_code == 409, repeated_complete.text
    ready_after_done = seller.post(
        f"/api/seller/orders/{done['id']}/ready",
        json={},
        headers=csrf_headers(seller),
    )
    assert ready_after_done.status_code == 409, ready_after_done.text
    assert buyer.get(f"/api/orders/{done['id']}").json() == done_facts


def test_completed_order_is_terminal_and_keeps_quota_and_recap(actors) -> None:
    buyer, seller, _clock = actors
    classic = create_product(seller, CLASSIC)
    schedule = open_schedule(seller, [(classic["id"], 5)])
    offer = offer_of(schedule, classic)
    order = place_order(buyer, schedule, [(offer["id"], 2)], "t7-final-01")
    verify_payment(seller, order)
    mark_ready(seller, order)
    mark_complete(seller, order)
    final_facts = buyer.get(f"/api/orders/{order['id']}").json()
    assert recap_of(seller, schedule)["total_quantity"] == 2

    for refund_outcome in ("refunded_manually", "no_funds_received"):
        refused = seller_cancel(seller, order, refund_outcome)
        assert refused.status_code == 409, (refund_outcome, refused.text)
    buyer_cancel = buyer.post(
        f"/api/orders/{order['id']}/cancel", json={}, headers=csrf_headers(buyer)
    )
    assert buyer_cancel.status_code == 409, buyer_cancel.text
    for path in ("ready", "complete"):
        again = seller.post(
            f"/api/seller/orders/{order['id']}/{path}",
            json={},
            headers=csrf_headers(seller),
        )
        assert again.status_code == 409, (path, again.text)
    report_after_done = buyer.post(
        f"/api/orders/{order['id']}/transfer-report",
        json={"note": REPORT_NOTE},
        headers=csrf_headers(buyer),
    )
    assert report_after_done.status_code == 409, report_after_done.text

    assert buyer.get(f"/api/orders/{order['id']}").json() == final_facts
    assert final_facts["status"] == "selesai"
    assert final_facts["cancelled_at"] is None
    assert final_facts["cancellation_reason"] is None
    assert final_facts["refund_outcome"] is None
    assert allocated_for(buyer, schedule, offer["id"]) == 2
    recap = recap_of(seller, schedule)
    assert recap["lines"][0]["quantity"] == 2
    assert recap["total_quantity"] == 2


def test_ready_order_can_be_cancelled_with_manual_refund_and_releases_quota_once(
    actors,
) -> None:
    buyer, seller, _clock = actors
    classic = create_product(seller, CLASSIC)
    schedule = open_schedule(seller, [(classic["id"], 5)])
    offer = offer_of(schedule, classic)
    order = place_order(buyer, schedule, [(offer["id"], 3)], "t7-cancel-01")
    verify_payment(seller, order)
    mark_ready(seller, order)
    assert recap_of(seller, schedule)["total_quantity"] == 3

    # A verified payment cannot be declared never received, even when ready.
    refused = seller_cancel(seller, order, "no_funds_received")
    assert refused.status_code == 409, refused.text
    assert buyer.get(f"/api/orders/{order['id']}").json()["status"] == "siap_diambil"
    assert allocated_for(buyer, schedule, offer["id"]) == 3
    assert recap_of(seller, schedule)["total_quantity"] == 3

    cancelled = seller_cancel(seller, order, "refunded_manually")
    assert cancelled.status_code == 200, cancelled.text
    final_facts = cancelled.json()
    assert final_facts["status"] == "batal"
    assert final_facts["cancelled_by_role"] == "seller"
    assert final_facts["cancellation_reason"] == REFUND_REASON
    assert final_facts["refund_outcome"] == "refunded_manually"
    assert final_facts["verified_at"] == "2026-01-01T08:00:00Z"
    assert final_facts["payment_received_rupiah"] == order["total_rupiah"]
    # Cancellation after ready releases the derived allocation exactly once.
    assert allocated_for(buyer, schedule, offer["id"]) == 0
    assert recap_of(seller, schedule)["lines"] == []

    repeated = seller_cancel(seller, order, "refunded_manually")
    assert repeated.status_code == 409, repeated.text
    for path in ("ready", "complete"):
        again = seller.post(
            f"/api/seller/orders/{order['id']}/{path}",
            json={},
            headers=csrf_headers(seller),
        )
        assert again.status_code == 409, (path, again.text)
    assert (
        buyer.post(
            f"/api/orders/{order['id']}/cancel", json={}, headers=csrf_headers(buyer)
        ).status_code
        == 409
    )
    assert buyer.get(f"/api/orders/{order['id']}").json() == final_facts
    assert allocated_for(buyer, schedule, offer["id"]) == 0


def run_while_schedule_locked(
    settings: Settings, schedule_id: int, calls: list[Any]
) -> list[Any]:
    """Hold the real MySQL schedule lock, start every call, then release it."""
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


def test_ready_then_cancel_follows_a_legal_serial_order(
    actors, settings: Settings
) -> None:
    buyer, seller, _clock = actors
    classic = create_product(seller, CLASSIC)
    schedule = open_schedule(seller, [(classic["id"], 5)])
    offer = offer_of(schedule, classic)
    order = place_order(buyer, schedule, [(offer["id"], 2)], "t7-race-01")
    verify_payment(seller, order)
    token = csrf_headers(seller)["X-CSRF-Token"]
    headers = {"Origin": ORIGIN, "X-CSRF-Token": token}

    with TestClient(seller.app) as twin:
        twin.cookies.update(seller.cookies)
        ready_result, cancel_result = run_while_schedule_locked(
            settings,
            schedule["id"],
            [
                lambda: seller.post(
                    f"/api/seller/orders/{order['id']}/ready", json={}, headers=headers
                ),
                lambda: twin.post(
                    f"/api/seller/orders/{order['id']}/cancel",
                    json={"reason": REFUND_REASON, "refund_outcome": "refunded_manually"},
                    headers=headers,
                ),
            ],
        )

    # Ready and cancel are sequential steps when ready wins: both may commit, and
    # the recorded cancellation is final either way. Ready after cancel must lose.
    assert cancel_result.status_code == 200, cancel_result.text
    assert ready_result.status_code in {200, 409}, ready_result.text
    final = buyer.get(f"/api/orders/{order['id']}").json()
    assert final["status"] == "batal"
    assert final["cancelled_by_role"] == "seller"
    assert final["refund_outcome"] == "refunded_manually"
    assert allocated_for(buyer, schedule, offer["id"]) == 0
    assert recap_of(seller, schedule)["lines"] == []
    ready_after_cancel = seller.post(
        f"/api/seller/orders/{order['id']}/ready",
        json={},
        headers=csrf_headers(seller),
    )
    assert ready_after_cancel.status_code == 409, ready_after_cancel.text
    assert buyer.get(f"/api/orders/{order['id']}").json() == final


def test_complete_and_ready_cancel_serialize_to_exactly_one_result(
    actors, settings: Settings
) -> None:
    buyer, seller, _clock = actors
    classic = create_product(seller, CLASSIC)
    schedule = open_schedule(seller, [(classic["id"], 5)])
    offer = offer_of(schedule, classic)
    order = place_order(buyer, schedule, [(offer["id"], 4)], "t7-race-02")
    verify_payment(seller, order)
    mark_ready(seller, order)
    token = csrf_headers(seller)["X-CSRF-Token"]
    headers = {"Origin": ORIGIN, "X-CSRF-Token": token}
    reason = "Penyerahan batal tepat saat pesanan hendak diselesaikan."

    with TestClient(seller.app) as twin:
        twin.cookies.update(seller.cookies)
        complete_result, cancel_result = run_while_schedule_locked(
            settings,
            schedule["id"],
            [
                lambda: seller.post(
                    f"/api/seller/orders/{order['id']}/complete", json={}, headers=headers
                ),
                lambda: twin.post(
                    f"/api/seller/orders/{order['id']}/cancel",
                    json={"reason": reason, "refund_outcome": "refunded_manually"},
                    headers=headers,
                ),
            ],
        )

    assert sorted([complete_result.status_code, cancel_result.status_code]) == [200, 409], [
        complete_result.text,
        cancel_result.text,
    ]
    final = buyer.get(f"/api/orders/{order['id']}").json()
    recap = recap_of(seller, schedule)
    if complete_result.status_code == 200:
        assert final["status"] == "selesai"
        assert final["cancelled_at"] is None
        assert final["cancellation_reason"] is None
        assert final["refund_outcome"] is None
        assert allocated_for(buyer, schedule, offer["id"]) == 4
        assert recap["total_quantity"] == 4
    else:
        assert final["status"] == "batal"
        assert final["cancelled_by_role"] == "seller"
        assert final["cancellation_reason"] == reason
        assert final["refund_outcome"] == "refunded_manually"
        assert allocated_for(buyer, schedule, offer["id"]) == 0
        assert recap["lines"] == []
        # A losing completion never re-adds the quantity or reopens the order.
        assert (
            seller.post(
                f"/api/seller/orders/{order['id']}/complete",
                json={},
                headers=csrf_headers(seller),
            ).status_code
            == 409
        )
        assert buyer.get(f"/api/orders/{order['id']}").json() == final
