from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from conftest import ORIGIN
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as DBSession

from app.config import Settings
from app.db import make_engine
from app.seed import DEMO_SELLER_EMAIL, DEMO_SELLER_PASSWORD, seed_seller

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


def csrf_headers(client: TestClient) -> dict[str, str]:
    token = client.get("/api/auth/session").json()["csrf_token"]
    return {"Origin": ORIGIN, "X-CSRF-Token": token}


def login(client: TestClient, email: str, password: str) -> None:
    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
        headers=csrf_headers(client),
    )
    assert response.status_code == 200


@pytest.fixture
def seller(client: TestClient, settings: Settings) -> Iterator[None]:
    engine = make_engine(settings.database_url.get_secret_value())
    try:
        with DBSession(engine) as db:
            seed_seller(db, email=DEMO_SELLER_EMAIL, password=DEMO_SELLER_PASSWORD)
    finally:
        engine.dispose()
    login(client, DEMO_SELLER_EMAIL, DEMO_SELLER_PASSWORD)
    yield


def create_product(client: TestClient, **overrides: object) -> dict[str, object]:
    response = client.post(
        "/api/seller/products",
        json={**PRODUCT, **overrides},
        headers=csrf_headers(client),
    )
    assert response.status_code == 201, response.text
    return response.json()


def schedule_payload(product_ids: list[int], **overrides: object) -> dict[str, object]:
    return {
        "pickup_at": PICKUP_WIB,
        "order_cutoff_at": CUTOFF_WIB,
        "offers": [{"product_id": product_id, "quota": 6} for product_id in product_ids],
        **overrides,
    }


def open_schedule(client: TestClient, product_ids: list[int], **overrides: object) -> dict:
    response = client.post(
        "/api/seller/schedules",
        json=schedule_payload(product_ids, **overrides),
        headers=csrf_headers(client),
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_public_schedule_list_is_empty_without_login(client: TestClient) -> None:
    response = client.get("/api/schedules")

    assert response.status_code == 200
    assert response.json() == {"items": []}


def test_seller_opens_a_schedule_with_a_stored_catalog_product(
    client: TestClient, seller: None
) -> None:
    product = create_product(client)

    created = open_schedule(client, [product["id"]])

    assert created["pickup_at"] == PICKUP_UTC
    assert created["order_cutoff_at"] == CUTOFF_UTC
    assert created["orders_open"] is True
    assert isinstance(created["id"], int)
    assert created["offers"] == [
        {
            "id": created["offers"][0]["id"],
            "product_id": product["id"],
            "product_name": PRODUCT["name"],
            "selling_unit": PRODUCT["selling_unit"],
            "price_rupiah": PRODUCT["price_rupiah"],
            "quota": 6,
            "allocated_quantity": 0,
            "remaining_quota": 6,
        }
    ]

    assert client.get("/api/schedules").json() == {"items": [created]}
    assert client.get("/api/seller/schedules").json() == {"items": [created]}


def test_schedule_timestamps_are_unambiguous_utc(client: TestClient, seller: None) -> None:
    product = create_product(client)
    created = open_schedule(client, [product["id"]])

    # The API never returns a naive timestamp for schedule times.
    for field in ("pickup_at", "order_cutoff_at"):
        assert created[field].endswith("Z")
        parsed = datetime.fromisoformat(created[field].replace("Z", "+00:00"))
        assert parsed.tzinfo is not None
        assert parsed.astimezone(UTC).replace(tzinfo=None) == (
            datetime.fromisoformat(
                (PICKUP_UTC if field == "pickup_at" else CUTOFF_UTC).replace("Z", "+00:00")
            ).replace(tzinfo=None)
        )


@pytest.mark.parametrize("method", ["POST", "PATCH"])
@pytest.mark.parametrize("pickup,cutoff", [
    (3000000000, 2000000000),
    (3000000000.5, 2000000000.5),
    ("3000000000", "2000000000"),
])
def test_non_iso_schedule_times_are_rejected_without_changes(
    client: TestClient, seller: None, method: str, pickup: object, cutoff: object
) -> None:
    path = "/api/seller/schedules"
    if method == "PATCH":
        existing = open_schedule(client, [])
        path += f"/{existing['id']}"
    before = client.get("/api/schedules").json()

    response = client.request(
        method, path,
        json={"pickup_at": pickup, "order_cutoff_at": cutoff},
        headers=csrf_headers(client),
    )

    assert response.status_code == 422
    assert client.get("/api/schedules").json() == before


@pytest.mark.parametrize("method", ["POST", "PATCH"])
@pytest.mark.parametrize("pickup,cutoff", [
    ("2035-11-08T11:00:00Z", "0001-01-01T00:00:00+14:00"),
    ("9999-12-31T23:59:59-14:00", "2035-11-06T13:00:00Z"),
])
def test_unrepresentable_utc_schedule_times_are_rejected_without_changes(
    client: TestClient, seller: None, method: str, pickup: str, cutoff: str
) -> None:
    path = "/api/seller/schedules"
    if method == "PATCH":
        existing = open_schedule(client, [])
        path += f"/{existing['id']}"
    before = client.get("/api/schedules").json()

    response = client.request(
        method, path,
        json={"pickup_at": pickup, "order_cutoff_at": cutoff},
        headers=csrf_headers(client),
    )

    assert response.status_code == 422
    assert client.get("/api/schedules").json() == before


@pytest.mark.parametrize("fraction", ["001", "999"])
def test_schedule_fractional_seconds_are_truncated(client: TestClient, seller: None, fraction: str):
    created = open_schedule(
        client, [],
        pickup_at=f"2035-11-08T11:00:00.{fraction}Z",
        order_cutoff_at=f"2035-11-06T13:00:00.{fraction}Z",
    )
    assert created["pickup_at"] == "2035-11-08T11:00:00Z"
    assert created["order_cutoff_at"] == "2035-11-06T13:00:00Z"


@pytest.mark.parametrize("method,path", [
    ("POST", "/api/seller/schedules"),
    ("PATCH", "/api/seller/schedules/1"),
    ("POST", "/api/seller/schedules/1/offers"),
    ("PATCH", "/api/seller/schedules/1/offers/1"),
])
def test_anonymous_invalid_schedule_body_still_requires_authentication(
    client: TestClient, method: str, path: str
) -> None:
    response = client.request(method, path, json={"quota": "invalid"})
    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}


def test_seller_adds_updates_and_removes_an_offer(
    client: TestClient, seller: None
) -> None:
    first = create_product(client)
    second = create_product(client, name="Sourdough Biji", price_rupiah=72000)
    schedule = open_schedule(client, [first["id"]])

    added = client.post(
        f"/api/seller/schedules/{schedule['id']}/offers",
        json={"product_id": second["id"], "quota": 3},
        headers=csrf_headers(client),
    )

    assert added.status_code == 201
    offer = added.json()
    assert offer["product_id"] == second["id"]
    assert offer["product_name"] == "Sourdough Biji"
    assert offer["selling_unit"] == PRODUCT["selling_unit"]
    assert offer["price_rupiah"] == 72000
    assert offer["quota"] == 3
    public_offers = client.get("/api/schedules").json()["items"][0]["offers"]
    assert [item["product_id"] for item in public_offers] == [first["id"], second["id"]]

    updated = client.patch(
        f"/api/seller/schedules/{schedule['id']}/offers/{offer['id']}",
        json={"quota": 9},
        headers=csrf_headers(client),
    )
    assert updated.status_code == 200
    assert updated.json()["quota"] == 9
    assert client.get("/api/schedules").json()["items"][0]["offers"][1]["quota"] == 9

    removed = client.delete(
        f"/api/seller/schedules/{schedule['id']}/offers/{offer['id']}",
        headers=csrf_headers(client),
    )
    assert removed.status_code == 204
    remaining = client.get("/api/schedules").json()["items"][0]["offers"]
    assert [item["product_id"] for item in remaining] == [first["id"]]
    repeated = client.delete(
        f"/api/seller/schedules/{schedule['id']}/offers/{offer['id']}",
        headers=csrf_headers(client),
    )
    assert repeated.status_code == 404


def test_offer_rejects_duplicates_unknown_archived_and_missing_ids(
    client: TestClient, seller: None
) -> None:
    first = create_product(client)
    second = create_product(client, name="Sourdough Biji")
    third = create_product(client, name="Sourdough Arsip")
    client.post(f"/api/seller/products/{third['id']}/archive", headers=csrf_headers(client))
    schedule = open_schedule(client, [first["id"]])
    other = open_schedule(client, [second["id"]])

    duplicate = client.post(
        f"/api/seller/schedules/{schedule['id']}/offers",
        json={"product_id": first["id"], "quota": 2},
        headers=csrf_headers(client),
    )
    assert duplicate.status_code == 409
    unknown_product = client.post(
        f"/api/seller/schedules/{schedule['id']}/offers",
        json={"product_id": 999999, "quota": 2},
        headers=csrf_headers(client),
    )
    assert unknown_product.status_code == 404
    archived = client.post(
        f"/api/seller/schedules/{schedule['id']}/offers",
        json={"product_id": third["id"], "quota": 2},
        headers=csrf_headers(client),
    )
    assert archived.status_code == 409
    unknown_schedule = client.post(
        "/api/seller/schedules/999999/offers",
        json={"product_id": second["id"], "quota": 2},
        headers=csrf_headers(client),
    )
    assert unknown_schedule.status_code == 404

    offer_id = schedule["offers"][0]["id"]
    wrong_schedule = client.patch(
        f"/api/seller/schedules/{other['id']}/offers/{offer_id}",
        json={"quota": 4},
        headers=csrf_headers(client),
    )
    assert wrong_schedule.status_code == 404
    wrong_schedule_delete = client.delete(
        f"/api/seller/schedules/{other['id']}/offers/{offer_id}",
        headers=csrf_headers(client),
    )
    assert wrong_schedule_delete.status_code == 404
    assert len(client.get("/api/schedules").json()["items"][0]["offers"]) == 1


@pytest.mark.parametrize("quota", [0, -1, 1000, 1.5, "3", True])
def test_offer_quota_must_be_an_integer_in_range(
    client: TestClient, seller: None, quota: object
) -> None:
    product = create_product(client)
    schedule = open_schedule(client, [product["id"]])
    offer_id = schedule["offers"][0]["id"]

    added = client.post(
        f"/api/seller/schedules/{schedule['id']}/offers",
        json={"product_id": product["id"], "quota": quota},
        headers=csrf_headers(client),
    )
    updated = client.patch(
        f"/api/seller/schedules/{schedule['id']}/offers/{offer_id}",
        json={"quota": quota},
        headers=csrf_headers(client),
    )

    assert added.status_code == 422
    assert updated.status_code == 422
    listing = client.get("/api/schedules").json()["items"][0]
    assert listing["offers"][0]["quota"] == 6
    assert len(listing["offers"]) == 1


def test_referenced_product_can_be_archived_without_deleting_offer_history(
    client: TestClient, seller: None
) -> None:
    product = create_product(client)
    schedule = open_schedule(client, [product["id"]])

    archived = client.post(
        f"/api/seller/products/{product['id']}/archive", headers=csrf_headers(client)
    )
    deleted = client.delete(
        f"/api/seller/products/{product['id']}", headers=csrf_headers(client)
    )

    assert archived.status_code == 200
    assert archived.json()["archived"] is True
    assert deleted.status_code == 409
    assert client.get(f"/api/products/{product['id']}").status_code == 404
    assert client.get("/api/products").json() == {"items": []}
    assert client.get("/api/schedules").json()["items"][0] == schedule
    repeated = client.post(
        f"/api/seller/products/{product['id']}/archive", headers=csrf_headers(client)
    )
    assert repeated.status_code == 200
    assert repeated.json() == archived.json()
    assert client.get("/api/schedules").json()["items"][0] == schedule

    # T4 has no orders, so removing the schedule is the documented way to free
    # the product. Only then may the product be deleted.
    assert (
        client.delete(
            f"/api/seller/schedules/{schedule['id']}", headers=csrf_headers(client)
        ).status_code
        == 204
    )
    assert (
        client.delete(
            f"/api/seller/products/{product['id']}", headers=csrf_headers(client)
        ).status_code
        == 204
    )


@pytest.mark.parametrize(
    "pickup, cutoff",
    [
        (PICKUP_WIB, PICKUP_WIB),
        (CUTOFF_WIB, "2035-11-09T20:00:00+07:00"),
        ("2035-11-08T18:00:00", CUTOFF_WIB),
        (PICKUP_WIB, "2035-11-06T20:00:00"),
        ("not-a-time", CUTOFF_WIB),
    ],
)
def test_schedule_times_require_explicit_offsets_and_cutoff_before_pickup(
    client: TestClient,
    seller: None,
    pickup: str,
    cutoff: str,
) -> None:
    product = create_product(client)

    response = client.post(
        "/api/seller/schedules",
        json={
            "pickup_at": pickup,
            "order_cutoff_at": cutoff,
            "offers": [{"product_id": product["id"], "quota": 2}],
        },
        headers=csrf_headers(client),
    )

    assert response.status_code == 422
    assert client.get("/api/schedules").json() == {"items": []}


def test_schedule_update_keeps_cutoff_before_pickup_and_can_edit_partially(
    client: TestClient, seller: None
) -> None:
    product = create_product(client)
    schedule = open_schedule(client, [product["id"]])

    rejected = client.patch(
        f"/api/seller/schedules/{schedule['id']}",
        json={"pickup_at": "2035-11-05T18:00:00+07:00"},
        headers=csrf_headers(client),
    )
    null_rejected = client.patch(
        f"/api/seller/schedules/{schedule['id']}",
        json={"pickup_at": None},
        headers=csrf_headers(client),
    )
    unchanged = client.get("/api/schedules").json()["items"][0]

    assert rejected.status_code == 422
    assert null_rejected.status_code == 422
    assert unchanged["pickup_at"] == PICKUP_UTC
    assert unchanged["order_cutoff_at"] == CUTOFF_UTC

    updated = client.patch(
        f"/api/seller/schedules/{schedule['id']}",
        json={"pickup_at": "2035-11-09T18:00:00+07:00"},
        headers=csrf_headers(client),
    )
    assert updated.status_code == 200
    assert updated.json()["pickup_at"] == "2035-11-09T11:00:00Z"
    assert updated.json()["order_cutoff_at"] == CUTOFF_UTC


def test_schedule_open_state_is_decided_by_the_server_clock(
    clocked_client: tuple[TestClient, object], settings: Settings
) -> None:
    client, clock = clocked_client
    engine = make_engine(settings.database_url.get_secret_value())
    try:
        with DBSession(engine) as db:
            seed_seller(db, email=DEMO_SELLER_EMAIL, password=DEMO_SELLER_PASSWORD)
    finally:
        engine.dispose()
    login(client, DEMO_SELLER_EMAIL, DEMO_SELLER_PASSWORD)
    product = create_product(client)
    schedule = open_schedule(
        client,
        [product["id"]],
        pickup_at="2026-01-02T17:00:00+07:00",
        order_cutoff_at="2026-01-01T16:00:00+07:00",
    )

    def public_status() -> bool:
        return client.get("/api/schedules").json()["items"][0]["orders_open"]

    assert schedule["orders_open"] is True
    assert public_status() is True

    clock.now = datetime(2026, 1, 1, 9, 0, 0)  # exact cutoff: closed
    assert public_status() is False

    clock.now = datetime(2026, 1, 1, 9, 0, 1)
    assert public_status() is False


def test_deleting_a_schedule_removes_its_offers(client: TestClient, seller: None) -> None:
    first = create_product(client)
    second = create_product(client, name="Sourdough Biji")
    schedule = open_schedule(client, [first["id"], second["id"]])

    response = client.delete(
        f"/api/seller/schedules/{schedule['id']}", headers=csrf_headers(client)
    )

    assert response.status_code == 204
    assert client.get("/api/schedules").json() == {"items": []}
    repeated = client.delete(
        f"/api/seller/schedules/{schedule['id']}", headers=csrf_headers(client)
    )
    assert repeated.status_code == 404


def test_catalog_edits_do_not_rewrite_existing_offer_snapshots(
    client: TestClient, seller: None
) -> None:
    product = create_product(client)
    open_schedule(client, [product["id"]])

    client.patch(
        f"/api/seller/products/{product['id']}",
        json={"name": "Nama Baru", "price_rupiah": 90000},
        headers=csrf_headers(client),
    )

    offer = client.get("/api/schedules").json()["items"][0]["offers"][0]
    assert offer["product_name"] == PRODUCT["name"]
    assert offer["price_rupiah"] == 65000
    assert offer["product_id"] == product["id"]


def test_creating_a_schedule_with_offers_is_atomic(
    client: TestClient, seller: None
) -> None:
    product = create_product(client)
    archived = create_product(client, name="Sourdough Arsip")
    client.post(f"/api/seller/products/{archived['id']}/archive", headers=csrf_headers(client))

    duplicate = client.post(
        "/api/seller/schedules",
        json=schedule_payload([product["id"], product["id"]]),
        headers=csrf_headers(client),
    )
    unknown = client.post(
        "/api/seller/schedules",
        json=schedule_payload([product["id"], 999999]),
        headers=csrf_headers(client),
    )
    archived_offer = client.post(
        "/api/seller/schedules",
        json=schedule_payload([product["id"], archived["id"]]),
        headers=csrf_headers(client),
    )
    server_owned = client.post(
        "/api/seller/schedules",
        json={
            **schedule_payload([product["id"]]),
            "orders_open": True,
            "offers": [
                {
                    "product_id": product["id"],
                    "quota": 2,
                    "product_name": "Dipaksa klien",
                    "price_rupiah": 1,
                }
            ],
        },
        headers=csrf_headers(client),
    )

    assert duplicate.status_code == 422
    assert unknown.status_code == 404
    assert archived_offer.status_code == 409
    assert server_owned.status_code == 422
    assert client.get("/api/schedules").json() == {"items": []}


BUYER = {
    "name": "Schedule Buyer",
    "email": "schedule-buyer@example.com",
    "password": "Synthetic-buyer-2026!",
}


def login_buyer(client: TestClient) -> None:
    assert (
        client.post("/api/auth/register", json=BUYER, headers=csrf_headers(client)).status_code
        == 201
    )
    login(client, BUYER["email"], BUYER["password"])


def prepare_mutation_targets(client: TestClient) -> dict[str, object]:
    first = create_product(client)
    second = create_product(client, name="Sourdough Biji")
    schedule = open_schedule(client, [first["id"]])
    return {
        "product": first,
        "second_product": second,
        "schedule": schedule,
        "offer_id": schedule["offers"][0]["id"],
    }


def send_mutation(client: TestClient, action: str, targets: dict[str, object]) -> object:
    schedule = targets["schedule"]
    offer_id = targets["offer_id"]
    assert isinstance(schedule, dict)
    assert isinstance(offer_id, int)
    schedule_id = schedule["id"]
    headers = csrf_headers(client)
    if action == "create":
        return client.post(
            "/api/seller/schedules",
            json=schedule_payload([targets["second_product"]["id"]]),
            headers=headers,
        )
    if action == "update_schedule":
        return client.patch(
            f"/api/seller/schedules/{schedule_id}",
            json={"pickup_at": "2035-11-09T18:00:00+07:00"},
            headers=headers,
        )
    if action == "delete_schedule":
        return client.delete(f"/api/seller/schedules/{schedule_id}", headers=headers)
    if action == "add_offer":
        return client.post(
            f"/api/seller/schedules/{schedule_id}/offers",
            json={"product_id": targets["second_product"]["id"], "quota": 2},
            headers=headers,
        )
    if action == "update_offer":
        return client.patch(
            f"/api/seller/schedules/{schedule_id}/offers/{offer_id}",
            json={"quota": 8},
            headers=headers,
        )
    if action == "delete_offer":
        return client.delete(
            f"/api/seller/schedules/{schedule_id}/offers/{offer_id}", headers=headers
        )
    raise AssertionError(action)


MUTATION_ACTIONS = [
    "create",
    "update_schedule",
    "delete_schedule",
    "add_offer",
    "update_offer",
    "delete_offer",
]


@pytest.mark.parametrize("action", MUTATION_ACTIONS)
@pytest.mark.parametrize("who, expected", [("anonymous", 401), ("buyer", 403)])
def test_only_the_seller_can_mutate_schedules_and_offers(
    client: TestClient,
    seller: None,
    action: str,
    who: str,
    expected: int,
) -> None:
    targets = prepare_mutation_targets(client)
    before = client.get("/api/schedules").json()
    client.post("/api/auth/logout", headers=csrf_headers(client))
    if who == "buyer":
        login_buyer(client)

    response = send_mutation(client, action, targets)

    assert response.status_code == expected
    assert client.get("/api/schedules").json() == before


@pytest.mark.parametrize("action", MUTATION_ACTIONS)
def test_schedule_and_offer_mutations_require_csrf_and_registered_origin(
    client: TestClient, seller: None, action: str
) -> None:
    targets = prepare_mutation_targets(client)
    before = client.get("/api/schedules").json()
    headers = csrf_headers(client)
    for broken in (
        {key: value for key, value in headers.items() if key != "Origin"},
        {key: value for key, value in headers.items() if key != "X-CSRF-Token"},
        {**headers, "Origin": "https://evil.example"},
        {**headers, "X-CSRF-Token": "0" * 64},
    ):
        schedule = targets["schedule"]
        offer_id = targets["offer_id"]
        assert isinstance(schedule, dict)
        assert isinstance(offer_id, int)
        url, method, payload = {
            "create": (
                "/api/seller/schedules",
                "POST",
                schedule_payload([targets["second_product"]["id"]]),
            ),
            "update_schedule": (
                f"/api/seller/schedules/{schedule['id']}",
                "PATCH",
                {"pickup_at": "2035-11-09T18:00:00+07:00"},
            ),
            "delete_schedule": (f"/api/seller/schedules/{schedule['id']}", "DELETE", None),
            "add_offer": (
                f"/api/seller/schedules/{schedule['id']}/offers",
                "POST",
                {"product_id": targets["second_product"]["id"], "quota": 2},
            ),
            "update_offer": (
                f"/api/seller/schedules/{schedule['id']}/offers/{offer_id}",
                "PATCH",
                {"quota": 8},
            ),
            "delete_offer": (
                f"/api/seller/schedules/{schedule['id']}/offers/{offer_id}",
                "DELETE",
                None,
            ),
        }[action]
        response = client.request(method, url, json=payload, headers=broken)
        assert response.status_code == 403

    assert client.get("/api/schedules").json() == before


@pytest.mark.parametrize("who, expected", [("anonymous", 401), ("buyer", 403)])
def test_managed_schedule_list_is_seller_only(
    client: TestClient, who: str, expected: int
) -> None:
    if who == "buyer":
        login_buyer(client)

    response = client.get("/api/seller/schedules")

    assert response.status_code == expected


def test_removing_the_last_offer_keeps_an_empty_schedule(
    client: TestClient, seller: None
) -> None:
    product = create_product(client)
    schedule = open_schedule(client, [product["id"]])

    removed = client.delete(
        f"/api/seller/schedules/{schedule['id']}/offers/{schedule['offers'][0]['id']}",
        headers=csrf_headers(client),
    )

    assert removed.status_code == 204
    listing = client.get("/api/schedules").json()
    assert listing["items"][0]["offers"] == []
    assert listing["items"][0]["id"] == schedule["id"]


def test_unknown_schedule_updates_are_not_found(client: TestClient, seller: None) -> None:
    headers = csrf_headers(client)

    assert (
        client.patch(
            "/api/seller/schedules/999999",
            json={"pickup_at": "2035-11-09T18:00:00+07:00"},
            headers=headers,
        ).status_code
        == 404
    )
    assert (
        client.delete("/api/seller/schedules/999999", headers=headers).status_code == 404
    )
