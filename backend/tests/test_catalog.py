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


def test_public_catalog_is_readable_without_login(client: TestClient) -> None:
    response = client.get("/api/products")

    assert response.status_code == 200
    assert response.json() == {"items": []}


def test_seller_creates_product_that_visitors_can_read(
    client: TestClient, seller: None
) -> None:
    before = datetime.now(UTC).replace(tzinfo=None)
    created = client.post("/api/seller/products", json=PRODUCT, headers=csrf_headers(client))
    after = datetime.now(UTC).replace(tzinfo=None)

    assert created.status_code == 201
    product = created.json()
    assert before <= datetime.fromisoformat(product["created_at"]) <= after
    assert product["name"] == PRODUCT["name"]
    assert product["selling_unit"] == PRODUCT["selling_unit"]
    assert product["price_rupiah"] == 65000
    assert product["is_demo"] is True
    assert product["archived"] is False
    assert isinstance(product["id"], int)

    listing = client.get("/api/products")
    assert listing.status_code == 200
    assert listing.json() == {"items": [product]}


BUYER = {
    "name": "Catalog Buyer",
    "email": "catalog-buyer@example.com",
    "password": "Synthetic-buyer-2026!",
}


def buyer(client: TestClient) -> None:
    client.post("/api/auth/register", json=BUYER, headers=csrf_headers(client))
    login(client, BUYER["email"], BUYER["password"])


MUTATIONS = [
    ("POST", "", PRODUCT),
    ("PATCH", "/{id}", {"name": "Perubahan tanpa izin"}),
    ("POST", "/{id}/archive", None),
    ("POST", "/{id}/restore", None),
    ("DELETE", "/{id}", None),
]


@pytest.mark.parametrize("who, expected", [("anonymous", 401), ("buyer", 403)])
@pytest.mark.parametrize("method, suffix, payload", MUTATIONS)
def test_only_the_seller_can_mutate_the_catalog(
    client: TestClient,
    seller: None,
    who: str,
    expected: int,
    method: str,
    suffix: str,
    payload: dict[str, object] | None,
) -> None:
    created = client.post(
        "/api/seller/products", json=PRODUCT, headers=csrf_headers(client)
    ).json()
    client.post("/api/auth/logout", headers=csrf_headers(client))
    if who == "buyer":
        buyer(client)

    response = client.request(
        method,
        f"/api/seller/products{suffix.format(id=created['id'])}",
        json=payload,
        headers=csrf_headers(client),
    )

    assert response.status_code == expected
    assert client.get("/api/products").json() == {"items": [created]}


@pytest.mark.parametrize("method, suffix, payload", MUTATIONS)
def test_mutations_require_csrf_and_registered_origin(
    client: TestClient,
    seller: None,
    method: str,
    suffix: str,
    payload: dict[str, object] | None,
) -> None:
    created = client.post(
        "/api/seller/products", json=PRODUCT, headers=csrf_headers(client)
    ).json()
    headers = csrf_headers(client)
    for broken in (
        {key: value for key, value in headers.items() if key != "Origin"},
        {key: value for key, value in headers.items() if key != "X-CSRF-Token"},
        {**headers, "Origin": "https://evil.example"},
        {**headers, "X-CSRF-Token": "0" * 64},
    ):
        response = client.request(
            method,
            f"/api/seller/products{suffix.format(id=created['id'])}",
            json=payload,
            headers=broken,
        )
        assert response.status_code == 403

    assert client.get("/api/products").json() == {"items": [created]}


@pytest.mark.parametrize(
    "field, value",
    [
        ("name", "a"),
        ("name", "x" * 81),
        ("name", "   "),
        ("selling_unit", "a"),
        ("selling_unit", "x" * 41),
        ("price_rupiah", 999),
        ("price_rupiah", 1_000_001),
        ("price_rupiah", 65000.5),
        ("price_rupiah", "65000"),
        ("description", "x" * 401),
    ],
)
def test_create_validates_server_side_bounds(
    client: TestClient, seller: None, field: str, value: object
) -> None:
    response = client.post(
        "/api/seller/products", json={**PRODUCT, field: value}, headers=csrf_headers(client)
    )

    assert response.status_code == 422
    assert client.get("/api/products").json() == {"items": []}


def test_seller_sees_the_managed_catalog(client: TestClient, seller: None) -> None:
    created = client.post(
        "/api/seller/products", json=PRODUCT, headers=csrf_headers(client)
    ).json()

    response = client.get("/api/seller/products")

    assert response.status_code == 200
    assert response.json() == {"items": [created]}


@pytest.mark.parametrize("who, expected", [("anonymous", 401), ("buyer", 403)])
def test_managed_catalog_is_seller_only(client: TestClient, who: str, expected: int) -> None:
    if who == "buyer":
        buyer(client)

    response = client.get("/api/seller/products")

    assert response.status_code == expected


def test_visit_reads_one_active_product(client: TestClient, seller: None) -> None:
    created = client.post(
        "/api/seller/products", json=PRODUCT, headers=csrf_headers(client)
    ).json()

    response = client.get(f"/api/products/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created
    assert client.get("/api/products/999999").status_code == 404


def test_archive_hides_the_product_and_restore_returns_it(
    client: TestClient, seller: None
) -> None:
    created = client.post(
        "/api/seller/products", json=PRODUCT, headers=csrf_headers(client)
    ).json()

    archived = client.post(
        f"/api/seller/products/{created['id']}/archive", headers=csrf_headers(client)
    )
    assert archived.status_code == 200
    assert archived.json()["archived"] is True
    assert client.get("/api/products").json() == {"items": []}
    assert client.get(f"/api/products/{created['id']}").status_code == 404
    assert client.get("/api/seller/products").json() == {"items": [archived.json()]}

    # Repeating the archive action does not flip state or create a second row.
    again = client.post(
        f"/api/seller/products/{created['id']}/archive", headers=csrf_headers(client)
    )
    assert again.status_code == 200
    assert again.json()["archived"] is True
    assert len(client.get("/api/seller/products").json()["items"]) == 1

    restored = client.post(
        f"/api/seller/products/{created['id']}/restore", headers=csrf_headers(client)
    )
    assert restored.status_code == 200
    assert restored.json()["archived"] is False
    assert client.get("/api/products").json() == {"items": [restored.json()]}
    assert client.get(f"/api/products/{created['id']}").status_code == 200
    restored_again = client.post(
        f"/api/seller/products/{created['id']}/restore", headers=csrf_headers(client)
    )
    assert restored_again.status_code == 200
    assert restored_again.json() == restored.json()
    assert client.get("/api/products").json() == {"items": [restored.json()]}


def test_seller_updates_the_product_visitors_see(client: TestClient, seller: None) -> None:
    created = client.post(
        "/api/seller/products", json=PRODUCT, headers=csrf_headers(client)
    ).json()

    response = client.patch(
        f"/api/seller/products/{created['id']}",
        json={"name": "Sourdough Biji", "price_rupiah": 72000},
        headers=csrf_headers(client),
    )

    assert response.status_code == 200
    updated = response.json()
    assert updated["name"] == "Sourdough Biji"
    assert updated["price_rupiah"] == 72000
    assert updated["selling_unit"] == PRODUCT["selling_unit"]
    assert updated["description"] == PRODUCT["description"]
    assert client.get(f"/api/products/{created['id']}").json() == updated


@pytest.mark.parametrize(
    "payload",
    [
        {"price_rupiah": 500},
        {"name": ""},
        {"name": None},
        {"selling_unit": None},
        {"price_rupiah": None},
        {"description": None},
        {"is_demo": False},
        {"archived": True},
        {"unknown_field": "x"},
    ],
)
def test_update_rejects_invalid_or_server_owned_fields(
    client: TestClient, seller: None, payload: dict[str, object]
) -> None:
    created = client.post(
        "/api/seller/products", json=PRODUCT, headers=csrf_headers(client)
    ).json()

    response = client.patch(
        f"/api/seller/products/{created['id']}", json=payload, headers=csrf_headers(client)
    )

    assert response.status_code == 422
    assert client.get(f"/api/products/{created['id']}").json() == created


def test_update_missing_product_is_not_found(client: TestClient, seller: None) -> None:
    response = client.patch(
        "/api/seller/products/999999", json={"price_rupiah": 72000}, headers=csrf_headers(client)
    )

    assert response.status_code == 404


def test_seller_deletes_an_unused_product(client: TestClient, seller: None) -> None:
    keep = client.post(
        "/api/seller/products",
        json={**PRODUCT, "name": "Sourdough Gandum"},
        headers=csrf_headers(client),
    ).json()
    doomed = client.post(
        "/api/seller/products",
        json={**PRODUCT, "name": "Sourdough Kopi"},
        headers=csrf_headers(client),
    ).json()

    response = client.delete(
        f"/api/seller/products/{doomed['id']}", headers=csrf_headers(client)
    )

    assert response.status_code == 204
    assert client.get("/api/products").json() == {"items": [keep]}
    assert client.get("/api/seller/products").json() == {"items": [keep]}
    assert client.get(f"/api/products/{doomed['id']}").status_code == 404
    repeated = client.delete(
        f"/api/seller/products/{doomed['id']}", headers=csrf_headers(client)
    )
    assert repeated.status_code == 404


def test_product_text_is_stored_and_returned_as_literal_text(
    client: TestClient, seller: None
) -> None:
    markup = '<img src=x onerror="window.__catalogXss=1">'
    created = client.post(
        "/api/seller/products",
        json={**PRODUCT, "name": markup, "description": "<script>alert(1)</script>"},
        headers=csrf_headers(client),
    )

    assert created.status_code == 201
    product = created.json()
    assert product["name"] == markup
    assert product["description"] == "<script>alert(1)</script>"
    read_back = client.get(f"/api/products/{product['id']}")
    assert read_back.json()["name"] == markup
    assert read_back.json()["description"] == "<script>alert(1)</script>"
    assert "<script>" in read_back.text
