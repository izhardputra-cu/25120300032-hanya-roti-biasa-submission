import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.exc import OperationalError

from app.config import Settings
from app.db import make_engine


def test_initial_migration_upgrades_and_downgrades_safely(settings: Settings) -> None:
    engine = make_engine(settings.database_url.get_secret_value())
    config = Config("alembic.ini")
    try:
        with engine.connect() as connection:
            config.attributes["connection"] = connection
            command.downgrade(config, "base")
            connection.commit()
            assert "users" not in inspect(connection).get_table_names()
            assert "sessions" not in inspect(connection).get_table_names()

            command.upgrade(config, "head")
            connection.commit()
            tables = inspect(connection).get_table_names()
            assert {"users", "sessions"} <= set(tables)
            user_columns = {column["name"] for column in inspect(connection).get_columns("users")}
            session_columns = {
                column["name"] for column in inspect(connection).get_columns("sessions")
            }
            assert {"id", "name", "email", "password_hash", "role"} <= user_columns
            assert {"token_digest", "csrf_token", "user_id", "expires_at"} <= session_columns
    finally:
        engine.dispose()


def test_product_migration_keeps_existing_accounts_and_repeats_cleanly(
    settings: Settings,
) -> None:
    import sqlalchemy as sa

    engine = make_engine(settings.database_url.get_secret_value())
    config = Config("alembic.ini")
    try:
        with engine.connect() as connection:
            config.attributes["connection"] = connection
            command.downgrade(config, "0001")
            connection.commit()
            connection.execute(
                sa.text(
                    "INSERT INTO users (name, email, password_hash, role) "
                    "VALUES (:name, :email, :hash, 'buyer')"
                ),
                {"name": "Kept Buyer", "email": "kept@example.com", "hash": "not-a-real-hash"},
            )
            command.upgrade(config, "head")
            command.upgrade(config, "head")

            connection.commit()
            assert (
                connection.scalar(
                    sa.text("SELECT COUNT(*) FROM users WHERE email = 'kept@example.com'")
                )
                == 1
            )
            inspector = inspect(connection)
            assert "products" in inspector.get_table_names()
            columns = {column["name"] for column in inspector.get_columns("products")}
            assert {
                "id",
                "name",
                "selling_unit",
                "price_rupiah",
                "description",
                "is_demo",
                "archived_at",
                "created_at",
            } <= columns
            checks = {check["name"] for check in inspector.get_check_constraints("products")}
            assert {
                "ck_products_price_rupiah",
                "ck_products_name_length",
                "ck_products_unit_length",
            } <= checks
            assert connection.scalar(sa.text("SELECT version_num FROM alembic_version")) == "0007"
    finally:
        engine.dispose()


def test_schedule_migration_keeps_existing_rows_and_repeats_cleanly(
    settings: Settings,
) -> None:
    import sqlalchemy as sa

    engine = make_engine(settings.database_url.get_secret_value())
    config = Config("alembic.ini")
    try:
        with engine.connect() as connection:
            config.attributes["connection"] = connection
            command.downgrade(config, "0002")
            connection.commit()
            connection.execute(
                sa.text(
                    "INSERT INTO users (name, email, password_hash, role) "
                    "VALUES (:name, :email, :hash, 'buyer')"
                ),
                {"name": "Kept Schedule Buyer", "email": "kept-schedule@example.com", "hash": "x"},
            )
            connection.execute(
                sa.text(
                    "INSERT INTO products "
                    "(name, selling_unit, price_rupiah, description, is_demo) "
                    "VALUES (:name, :unit, 65000, 'demo', 1)"
                ),
                {"name": "Kept Product", "unit": "1 loaf 500 gram"},
            )
            command.upgrade(config, "head")
            command.upgrade(config, "head")

            connection.commit()
            assert (
                connection.scalar(
                    sa.text("SELECT COUNT(*) FROM users WHERE email = 'kept-schedule@example.com'")
                )
                == 1
            )
            assert (
                connection.scalar(
                    sa.text("SELECT COUNT(*) FROM products WHERE name = 'Kept Product'")
                )
                == 1
            )
            inspector = inspect(connection)
            assert {"schedules", "schedule_offers"} <= set(inspector.get_table_names())
            schedule_columns = {column["name"] for column in inspector.get_columns("schedules")}
            assert {
                "id",
                "pickup_at",
                "order_cutoff_at",
                "archived_at",
                "created_at",
            } <= schedule_columns
            offer_columns = {column["name"] for column in inspector.get_columns("schedule_offers")}
            assert {
                "id",
                "schedule_id",
                "product_id",
                "product_name",
                "selling_unit",
                "price_rupiah",
                "quota",
                "created_at",
            } <= offer_columns
            assert "ck_schedules_cutoff_before_pickup" in {
                check["name"] for check in inspector.get_check_constraints("schedules")
            }
            assert {
                "ck_schedule_offers_quota",
                "ck_schedule_offers_price_rupiah",
                "ck_schedule_offers_unit_length",
            } <= {check["name"] for check in inspector.get_check_constraints("schedule_offers")}
            unique_names = {
                index["name"]
                for index in inspector.get_indexes("schedule_offers")
                if index.get("unique")
            }
            assert "uq_schedule_offers_schedule_product" in unique_names
            schedule_fk = next(
                key
                for key in inspector.get_foreign_keys("schedule_offers")
                if key["constrained_columns"] == ["schedule_id"]
            )
            assert schedule_fk["referred_table"] == "schedules"
            assert schedule_fk["options"]["ondelete"] == "CASCADE"
            assert connection.scalar(sa.text("SELECT version_num FROM alembic_version")) == "0007"
    finally:
        engine.dispose()


def test_order_migration_keeps_existing_data_and_repeats_cleanly(
    settings: Settings,
) -> None:
    import sqlalchemy as sa

    engine = make_engine(settings.database_url.get_secret_value())
    config = Config("alembic.ini")
    try:
        with engine.connect() as connection:
            config.attributes["connection"] = connection
            command.downgrade(config, "0003")
            connection.commit()
            connection.execute(
                sa.text(
                    "INSERT INTO users (name, email, password_hash, role) "
                    "VALUES (:name, :email, :hash, 'buyer')"
                ),
                {"name": "Kept Order Buyer", "email": "kept-order@example.com", "hash": "x"},
            )
            connection.execute(
                sa.text(
                    "INSERT INTO products "
                    "(name, selling_unit, price_rupiah, description, is_demo) "
                    "VALUES (:name, :unit, 65000, 'demo', 1)"
                ),
                {"name": "Kept Order Product", "unit": "1 loaf 500 gram"},
            )
            connection.execute(
                sa.text(
                    "INSERT INTO schedules (pickup_at, order_cutoff_at) "
                    "VALUES ('2035-11-08 11:00:00', '2035-11-06 13:00:00')"
                )
            )
            connection.execute(
                sa.text(
                    "INSERT INTO schedule_offers (schedule_id, product_id, product_name, "
                    "selling_unit, price_rupiah, quota) "
                    "SELECT s.id, p.id, p.name, p.selling_unit, p.price_rupiah, 6 "
                    "FROM schedules AS s, products AS p "
                    "WHERE p.name = 'Kept Order Product'"
                )
            )
            command.upgrade(config, "head")
            command.upgrade(config, "head")

            connection.commit()
            assert (
                connection.scalar(
                    sa.text("SELECT COUNT(*) FROM users WHERE email = 'kept-order@example.com'")
                )
                == 1
            )
            assert (
                connection.scalar(
                    sa.text("SELECT COUNT(*) FROM products WHERE name = 'Kept Order Product'")
                )
                == 1
            )
            assert connection.scalar(sa.text("SELECT COUNT(*) FROM schedules")) == 1
            assert connection.scalar(sa.text("SELECT COUNT(*) FROM schedule_offers")) == 1

            inspector = inspect(connection)
            assert {"orders", "order_items"} <= set(inspector.get_table_names())
            order_columns = {column["name"] for column in inspector.get_columns("orders")}
            assert {
                "id",
                "user_id",
                "schedule_id",
                "order_number",
                "checkout_key",
                "checkout_fingerprint",
                "status",
                "total_rupiah",
                "pickup_at",
                "created_at",
            } <= order_columns
            item_columns = {column["name"] for column in inspector.get_columns("order_items")}
            assert {
                "id",
                "order_id",
                "offer_id",
                "product_id",
                "product_name",
                "selling_unit",
                "unit_price_rupiah",
                "quantity",
                "line_total_rupiah",
            } <= item_columns
            order_checks = {check["name"] for check in inspector.get_check_constraints("orders")}
            assert {
                "ck_orders_status",
                "ck_orders_total_rupiah",
                "ck_orders_checkout_key_length",
            } <= order_checks
            item_checks = {
                check["name"] for check in inspector.get_check_constraints("order_items")
            }
            assert {
                "ck_order_items_unit_price",
                "ck_order_items_quantity",
                "ck_order_items_line_total",
            } <= item_checks
            order_uniques = {
                index["name"] for index in inspector.get_indexes("orders") if index.get("unique")
            }
            assert "uq_orders_user_checkout_key" in order_uniques
            item_uniques = {
                index["name"]
                for index in inspector.get_indexes("order_items")
                if index.get("unique")
            }
            assert "uq_order_items_order_offer" in item_uniques
            order_fk = next(
                key
                for key in inspector.get_foreign_keys("orders")
                if key["constrained_columns"] == ["schedule_id"]
            )
            assert order_fk["referred_table"] == "schedules"
            assert order_fk["options"]["ondelete"] == "RESTRICT"
            item_fk = next(
                key
                for key in inspector.get_foreign_keys("order_items")
                if key["constrained_columns"] == ["order_id"]
            )
            assert item_fk["referred_table"] == "orders"
            assert item_fk["options"]["ondelete"] == "CASCADE"
            assert connection.scalar(sa.text("SELECT version_num FROM alembic_version")) == "0007"
    finally:
        engine.dispose()


def test_payment_migration_keeps_existing_orders_and_repeats_cleanly(
    settings: Settings,
) -> None:
    import sqlalchemy as sa

    engine = make_engine(settings.database_url.get_secret_value())
    config = Config("alembic.ini")
    try:
        with engine.connect() as connection:
            config.attributes["connection"] = connection
            command.downgrade(config, "0004")
            connection.commit()
            connection.execute(
                sa.text(
                    "INSERT INTO users (name, email, password_hash, role) "
                    "VALUES (:name, :email, :hash, 'buyer')"
                ),
                {"name": "Kept Payment Buyer", "email": "kept-payment@example.com", "hash": "x"},
            )
            connection.execute(
                sa.text(
                    "INSERT INTO products "
                    "(name, selling_unit, price_rupiah, description, is_demo) "
                    "VALUES ('Kept Payment Product', '1 loaf 500 gram', 65000, 'demo', 1)"
                )
            )
            connection.execute(
                sa.text(
                    "INSERT INTO schedules (pickup_at, order_cutoff_at) "
                    "VALUES ('2035-11-08 11:00:00', '2035-11-06 13:00:00')"
                )
            )
            connection.execute(
                sa.text(
                    "INSERT INTO schedule_offers (schedule_id, product_id, product_name, "
                    "selling_unit, price_rupiah, quota) "
                    "SELECT s.id, p.id, p.name, p.selling_unit, p.price_rupiah, 6 "
                    "FROM schedules AS s, products AS p "
                    "WHERE p.name = 'Kept Payment Product'"
                )
            )
            connection.execute(
                sa.text(
                    "INSERT INTO orders (user_id, schedule_id, order_number, checkout_key, "
                    "checkout_fingerprint, status, total_rupiah, pickup_at) "
                    "SELECT u.id, s.id, 'PO-20351108-000001', 'kept-key-1', "
                    "'fingerprint', 'menunggu_pembayaran', 130000, s.pickup_at "
                    "FROM users AS u, schedules AS s "
                    "WHERE u.email = 'kept-payment@example.com'"
                )
            )
            command.upgrade(config, "head")
            command.upgrade(config, "head")
            connection.commit()

            assert connection.scalar(sa.text("SELECT COUNT(*) FROM orders")) == 1
            assert connection.scalar(sa.text("SELECT total_rupiah FROM orders")) == 130000
            inspector = inspect(connection)
            order_columns = {column["name"] for column in inspector.get_columns("orders")}
            assert {
                "transfer_note",
                "transfer_reported_at",
                "transfer_reported_by_id",
                "verified_at",
                "verified_by_id",
                "payment_received_rupiah",
                "cancelled_at",
                "cancelled_by_id",
                "cancellation_reason",
                "refund_outcome",
            } <= order_columns
            checks = {check["name"] for check in inspector.get_check_constraints("orders")}
            assert {
                "ck_orders_transfer_note_length",
                "ck_orders_transfer_report_complete",
                "ck_orders_verification_complete",
                "ck_orders_cancellation_complete",
                "ck_orders_cancellation_reason_length",
                "ck_orders_refund_outcome",
                "ck_orders_cancelled_status",
            } <= checks
            actor_fks = {
                key["constrained_columns"][0]: key
                for key in inspector.get_foreign_keys("orders")
                if key["constrained_columns"][0].endswith("_by_id")
            }
            assert set(actor_fks) == {
                "transfer_reported_by_id",
                "verified_by_id",
                "cancelled_by_id",
            }
            for foreign_key in actor_fks.values():
                assert foreign_key["referred_table"] == "users"
                assert foreign_key["options"]["ondelete"] == "RESTRICT"
            assert connection.scalar(sa.text("SELECT version_num FROM alembic_version")) == "0007"

            # Test actual enforcement, not just the presence of a CHECK name.
            with pytest.raises(
                OperationalError, match="ck_orders_verified_amount_present"
            ) as refused:
                with connection.begin_nested():
                    connection.execute(
                        sa.text(
                            "UPDATE orders SET verified_at = '2026-10-31 02:00:00', "
                            "verified_by_id = user_id, payment_received_rupiah = NULL"
                        )
                    )
            assert refused.value.orig is not None and refused.value.orig.args[0] == 3819
            assert connection.scalar(sa.text("SELECT verified_at FROM orders")) is None

            command.downgrade(config, "0004")
            connection.commit()
            assert "transfer_note" not in {
                column["name"] for column in inspect(connection).get_columns("orders")
            }
            assert connection.scalar(sa.text("SELECT COUNT(*) FROM orders")) == 1
            command.upgrade(config, "head")
            connection.commit()
            assert connection.scalar(sa.text("SELECT version_num FROM alembic_version")) == "0007"
    finally:
        engine.dispose()


def test_schedule_archive_migration_keeps_schedules_and_repeats_cleanly(
    settings: Settings,
) -> None:
    """0007 is a forward-only nullable column; existing schedules keep working."""
    import sqlalchemy as sa

    engine = make_engine(settings.database_url.get_secret_value())
    config = Config("alembic.ini")
    try:
        with engine.connect() as connection:
            config.attributes["connection"] = connection
            command.downgrade(config, "0006")
            connection.commit()
            assert "archived_at" not in {
                column["name"] for column in inspect(connection).get_columns("schedules")
            }
            connection.execute(
                sa.text(
                    "INSERT INTO schedules (pickup_at, order_cutoff_at) "
                    "VALUES ('2035-11-08 11:00:00', '2035-11-06 13:00:00')"
                )
            )
            command.upgrade(config, "head")
            command.upgrade(config, "head")
            connection.commit()

            assert connection.scalar(sa.text("SELECT COUNT(*) FROM schedules")) == 1
            assert connection.scalar(sa.text("SELECT archived_at FROM schedules")) is None
            columns = {
                column["name"]: column
                for column in inspect(connection).get_columns("schedules")
            }
            assert columns["archived_at"]["nullable"] is True
            assert connection.scalar(sa.text("SELECT version_num FROM alembic_version")) == "0007"

            # Downgrade drops only the archive marker; the schedule row survives.
            command.downgrade(config, "0006")
            connection.commit()
            assert "archived_at" not in {
                column["name"] for column in inspect(connection).get_columns("schedules")
            }
            assert connection.scalar(sa.text("SELECT COUNT(*) FROM schedules")) == 1
            command.upgrade(config, "head")
            connection.commit()
            assert connection.scalar(sa.text("SELECT version_num FROM alembic_version")) == "0007"
    finally:
        engine.dispose()


def test_migration_revision_survives_a_later_assertion_failure(settings: Settings) -> None:
    """A failed assertion must not undo the version of already-persistent MySQL DDL."""
    import sqlalchemy as sa

    engine = make_engine(settings.database_url.get_secret_value())
    config = Config("alembic.ini")
    try:
        with pytest.raises(AssertionError, match="simulated post-migration assertion"):
            with engine.connect() as connection:
                config.attributes["connection"] = connection
                command.downgrade(config, "0005")
                connection.commit()
                command.upgrade(config, "head")
                connection.commit()
                # Exercise connection rollback/close after a test assertion fails.
                connection.execute(sa.text("SELECT version_num FROM alembic_version"))
                raise AssertionError("simulated post-migration assertion")
        with engine.connect() as connection:
            assert connection.scalar(sa.text("SELECT version_num FROM alembic_version")) == "0007"
            assert "ck_orders_verified_amount_present" in {
                check["name"] for check in inspect(connection).get_check_constraints("orders")
            }
    finally:
        engine.dispose()
