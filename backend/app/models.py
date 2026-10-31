from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, String, UniqueConstraint, text
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('buyer', 'seller')", name="ck_users_role"),
        {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_0900_as_cs"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(10), default="buyer")


class Session(Base):
    __tablename__ = "sessions"
    __table_args__ = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_0900_as_cs"}

    token_digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    expires_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), index=True)
    user: Mapped[User | None] = relationship()


class Product(Base):
    """One sellable bread option. Archived rows stay readable for the seller."""

    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint(
            "price_rupiah BETWEEN 1000 AND 1000000", name="ck_products_price_rupiah"
        ),
        CheckConstraint("CHAR_LENGTH(name) BETWEEN 2 AND 80", name="ck_products_name_length"),
        CheckConstraint(
            "CHAR_LENGTH(selling_unit) BETWEEN 2 AND 40", name="ck_products_unit_length"
        ),
        {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_0900_as_cs"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    selling_unit: Mapped[str] = mapped_column(String(40))
    price_rupiah: Mapped[int] = mapped_column()
    description: Mapped[str] = mapped_column(String(400), default="")
    # Every catalog row in this stage is synthetic demo data. The flag is set by
    # the server and is not accepted from clients.
    is_demo: Mapped[bool] = mapped_column(default=True)
    archived_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6), server_default=text("CURRENT_TIMESTAMP(6)")
    )

    @property
    def archived(self) -> bool:
        return self.archived_at is not None


class Schedule(Base):
    """One bake schedule: shared order/payment cutoff and one pickup time.

    Times are naive UTC, like every other timestamp written by the app. The API
    converts them to explicit UTC (`Z`) on the way out and accepts offsets only.
    """

    __tablename__ = "schedules"
    __table_args__ = (
        CheckConstraint(
            "order_cutoff_at < pickup_at", name="ck_schedules_cutoff_before_pickup"
        ),
        {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_0900_as_cs"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    pickup_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    order_cutoff_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    # Set by the server only (`POST /api/seller/schedules/{id}/archive`) and
    # cleared by the matching restore. Archived schedules keep every offer,
    # allocation, and order row; only the seller's default lists hide them.
    archived_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6), server_default=text("CURRENT_TIMESTAMP(6)")
    )

    offers: Mapped[list["ScheduleOffer"]] = relationship(
        back_populates="schedule",
        cascade="all, delete-orphan",
        order_by="ScheduleOffer.id",
    )

    @property
    def archived(self) -> bool:
        return self.archived_at is not None


class ScheduleOffer(Base):
    """A catalog product offered in one schedule.

    Name, unit, and price are snapshots taken from the catalog when the offer is
    created. Editing the catalog later does not silently rewrite an existing
    offer or (from T5) an order item built from it.
    """

    __tablename__ = "schedule_offers"
    __table_args__ = (
        UniqueConstraint(
            "schedule_id", "product_id", name="uq_schedule_offers_schedule_product"
        ),
        CheckConstraint("quota BETWEEN 1 AND 999", name="ck_schedule_offers_quota"),
        CheckConstraint(
            "price_rupiah BETWEEN 1000 AND 1000000",
            name="ck_schedule_offers_price_rupiah",
        ),
        CheckConstraint(
            "CHAR_LENGTH(selling_unit) BETWEEN 2 AND 40",
            name="ck_schedule_offers_unit_length",
        ),
        {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_0900_as_cs"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    schedule_id: Mapped[int] = mapped_column(ForeignKey("schedules.id", ondelete="CASCADE"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
    product_name: Mapped[str] = mapped_column(String(80))
    selling_unit: Mapped[str] = mapped_column(String(40))
    price_rupiah: Mapped[int] = mapped_column()
    quota: Mapped[int] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6), server_default=text("CURRENT_TIMESTAMP(6)")
    )

    schedule: Mapped[Schedule] = relationship(back_populates="offers")


ORDER_STATUSES = (
    "menunggu_pembayaran",
    "menunggu_pemeriksaan",
    "terkonfirmasi",
    "siap_diambil",
    "selesai",
    "batal",
)

# 50 offers x 999 units x Rp1.000.000 is the largest total the API accepts.
MAX_ORDER_TOTAL_RUPIAH = 50 * 999 * 1_000_000


class Order(Base):
    """One checkout by one buyer for one schedule.

    Owner, totals, and status are server-owned. Item name/unit/price and the pickup
    time are snapshots so later catalog or offer edits never rewrite history.
    """

    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint(
            "status IN (" + ", ".join(f"'{status}'" for status in ORDER_STATUSES) + ")",
            name="ck_orders_status",
        ),
        CheckConstraint(
            f"total_rupiah BETWEEN 1000 AND {MAX_ORDER_TOTAL_RUPIAH}",
            name="ck_orders_total_rupiah",
        ),
        CheckConstraint(
            "CHAR_LENGTH(checkout_key) BETWEEN 8 AND 64",
            name="ck_orders_checkout_key_length",
        ),
        UniqueConstraint("user_id", "checkout_key", name="uq_orders_user_checkout_key"),
        {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_0900_as_cs"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    schedule_id: Mapped[int] = mapped_column(
        ForeignKey("schedules.id", ondelete="RESTRICT")
    )
    order_number: Mapped[str] = mapped_column(String(32), unique=True)
    checkout_key: Mapped[str] = mapped_column(String(64))
    checkout_fingerprint: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), default="menunggu_pembayaran")
    total_rupiah: Mapped[int] = mapped_column(BigInteger)
    pickup_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6), server_default=text("CURRENT_TIMESTAMP(6)")
    )
    # Facts recorded by T6. They are server-owned and never accepted from clients.
    transfer_note: Mapped[str | None] = mapped_column(String(200))
    transfer_reported_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    transfer_reported_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    verified_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    verified_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    payment_received_rupiah: Mapped[int | None] = mapped_column(BigInteger)
    cancelled_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    cancelled_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    cancellation_reason: Mapped[str | None] = mapped_column(String(300))
    refund_outcome: Mapped[str | None] = mapped_column(String(24))

    # Orders point at several users now, so every relationship to `users`
    # names its own foreign key explicitly.
    buyer: Mapped[User] = relationship(foreign_keys="Order.user_id")
    transfer_reported_by: Mapped[User | None] = relationship(
        foreign_keys="Order.transfer_reported_by_id"
    )
    verified_by: Mapped[User | None] = relationship(foreign_keys="Order.verified_by_id")
    cancelled_by: Mapped[User | None] = relationship(foreign_keys="Order.cancelled_by_id")
    schedule: Mapped[Schedule] = relationship()

    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
        order_by="OrderItem.id",
    )

    @property
    def order_cutoff_at(self) -> datetime:
        """The shared cutoff is shown live; it is not an order snapshot."""
        return self.schedule.order_cutoff_at

    @property
    def cancelled_by_role(self) -> str | None:
        return self.cancelled_by.role if self.cancelled_by is not None else None


class OrderItem(Base):
    """A server-computed snapshot line for one offer in one order."""

    __tablename__ = "order_items"
    __table_args__ = (
        UniqueConstraint("order_id", "offer_id", name="uq_order_items_order_offer"),
        CheckConstraint(
            "unit_price_rupiah BETWEEN 1000 AND 1000000",
            name="ck_order_items_unit_price",
        ),
        CheckConstraint("quantity BETWEEN 1 AND 999", name="ck_order_items_quantity"),
        CheckConstraint(
            "line_total_rupiah = unit_price_rupiah * quantity",
            name="ck_order_items_line_total",
        ),
        {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_0900_as_cs"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"))
    offer_id: Mapped[int] = mapped_column(
        ForeignKey("schedule_offers.id", ondelete="RESTRICT")
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
    product_name: Mapped[str] = mapped_column(String(80))
    selling_unit: Mapped[str] = mapped_column(String(40))
    unit_price_rupiah: Mapped[int] = mapped_column()
    quantity: Mapped[int] = mapped_column()
    line_total_rupiah: Mapped[int] = mapped_column(BigInteger)

    order: Mapped[Order] = relationship(back_populates="items")
