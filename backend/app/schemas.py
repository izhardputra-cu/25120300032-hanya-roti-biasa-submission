from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    EmailStr,
    Field,
    PlainSerializer,
    SecretStr,
    StringConstraints,
    field_validator,
    model_validator,
)

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=100)]
PASSWORD_MIN = 12
PASSWORD_MAX = 128


class RegisterInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    email: EmailStr
    password: SecretStr

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("password")
    @classmethod
    def check_password_length(cls, value: SecretStr) -> SecretStr:
        length = len(value.get_secret_value())
        if length < PASSWORD_MIN:
            raise ValueError(f"Password must be at least {PASSWORD_MIN} characters")
        if length > PASSWORD_MAX:
            raise ValueError(f"Password must be at most {PASSWORD_MAX} characters")
        return value


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: SecretStr = Field(min_length=PASSWORD_MIN, max_length=PASSWORD_MAX)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class UserView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    role: Literal["buyer", "seller"]


class UserResult(BaseModel):
    user: UserView


class SessionContext(BaseModel):
    user: UserView | None
    csrf_token: str


class LoginResult(BaseModel):
    user: UserView
    csrf_token: str


ProductName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=80)]
SellingUnit = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=40)]
ProductDescription = Annotated[str, StringConstraints(strip_whitespace=True, max_length=400)]
PRICE_MIN = 1_000
PRICE_MAX = 1_000_000


class ProductInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: ProductName
    selling_unit: SellingUnit
    price_rupiah: int = Field(ge=PRICE_MIN, le=PRICE_MAX, strict=True)
    description: ProductDescription = ""


class ProductUpdate(BaseModel):
    """Partial update. Server-owned fields (is_demo, archived) are rejected."""

    model_config = ConfigDict(extra="forbid")

    name: ProductName | None = None
    selling_unit: SellingUnit | None = None
    price_rupiah: int | None = Field(default=None, ge=PRICE_MIN, le=PRICE_MAX, strict=True)
    description: ProductDescription | None = None

    @field_validator("name", "selling_unit", "price_rupiah", "description")
    @classmethod
    def reject_explicit_null(cls, value: str | int | None) -> str | int:
        if value is None:
            raise ValueError("Product fields cannot be null; omit fields to leave them unchanged")
        return value


class ProductView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    selling_unit: str
    price_rupiah: int
    description: str
    is_demo: bool
    archived: bool
    created_at: datetime


class ProductList(BaseModel):
    items: list[ProductView]


def _iso_utc(value: datetime) -> str:
    """Serialize a stored naive-UTC value with an explicit, unambiguous offset."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


UtcTimestamp = Annotated[datetime, PlainSerializer(_iso_utc, return_type=str)]
QUOTA_MIN = 1
QUOTA_MAX = 999
MAX_OFFERS_PER_SCHEDULE = 50


def _parse_iso_time(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Time must be an ISO string with an explicit offset")
    return datetime.fromisoformat(value)


OffsetTimeInput = Annotated[AwareDatetime, BeforeValidator(_parse_iso_time)]


def _normalize_utc(value: datetime) -> datetime:
    try:
        return value.astimezone(UTC).replace(tzinfo=None, microsecond=0)
    except OverflowError:
        raise ValueError("Time is outside the supported UTC range") from None


class OfferInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: int = Field(gt=0, strict=True)
    quota: int = Field(ge=QUOTA_MIN, le=QUOTA_MAX, strict=True)


class ScheduleTimesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pickup_at: OffsetTimeInput
    order_cutoff_at: OffsetTimeInput

    @field_validator("pickup_at", "order_cutoff_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        return _normalize_utc(value)

    @model_validator(mode="after")
    def cutoff_must_precede_pickup(self) -> "ScheduleTimesInput":
        if self.order_cutoff_at >= self.pickup_at:
            raise ValueError(
                "Batas PO harus sebelum waktu pengambilan; tepat pada waktu yang sama ditolak."
            )
        return self


class ScheduleCreate(ScheduleTimesInput):
    offers: list[OfferInput] = Field(default_factory=list, max_length=MAX_OFFERS_PER_SCHEDULE)

    @model_validator(mode="after")
    def products_must_be_unique(self) -> "ScheduleCreate":
        product_ids = [offer.product_id for offer in self.offers]
        if len(product_ids) != len(set(product_ids)):
            raise ValueError("Setiap produk hanya boleh muncul satu kali dalam satu jadwal.")
        return self


class ScheduleUpdate(BaseModel):
    """Partial time update. Null is rejected when a field is explicitly sent."""

    model_config = ConfigDict(extra="forbid")

    pickup_at: OffsetTimeInput | None = None
    order_cutoff_at: OffsetTimeInput | None = None

    @field_validator("pickup_at", "order_cutoff_at")
    @classmethod
    def normalize_or_reject_null(cls, value: datetime | None) -> datetime:
        if value is None:
            raise ValueError("Omit a time field to leave it unchanged; it cannot be null")
        return _normalize_utc(value)


class OfferUpdate(BaseModel):
    """Partial offer edit. Price and quota are the only seller-editable fields."""

    model_config = ConfigDict(extra="forbid")

    quota: int | None = Field(default=None, ge=QUOTA_MIN, le=QUOTA_MAX, strict=True)
    price_rupiah: int | None = Field(
        default=None, ge=PRICE_MIN, le=PRICE_MAX, strict=True
    )

    @field_validator("quota", "price_rupiah")
    @classmethod
    def reject_explicit_null(cls, value: int | None) -> int:
        if value is None:
            raise ValueError("Omit a field to leave it unchanged; it cannot be null")
        return value

    @model_validator(mode="after")
    def require_at_least_one_field(self) -> "OfferUpdate":
        if not self.model_fields_set:
            raise ValueError("Send quota, price_rupiah, or both")
        return self


class OfferView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    product_name: str
    selling_unit: str
    price_rupiah: int
    quota: int
    # Server-computed from non-cancelled orders; the client never sends these.
    allocated_quantity: int = 0
    remaining_quota: int = 0


class ScheduleView(BaseModel):
    id: int
    pickup_at: UtcTimestamp
    order_cutoff_at: UtcTimestamp
    # Server-owned: the client must display this value, never recompute it.
    orders_open: bool
    # Server-owned archive flag; only the seller archive/restore endpoints set it.
    archived: bool
    offers: list[OfferView]


class ScheduleList(BaseModel):
    items: list[ScheduleView]


OrderStatus = Literal[
    "menunggu_pembayaran",
    "menunggu_pemeriksaan",
    "terkonfirmasi",
    "siap_diambil",
    "selesai",
    "batal",
]
RefundOutcome = Literal["refunded_manually", "no_funds_received"]
MAX_ORDER_TOTAL_RUPIAH = 50 * 999 * 1_000_000


class OrderItemView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    offer_id: int
    product_id: int
    product_name: str
    selling_unit: str
    unit_price_rupiah: int
    quantity: int
    line_total_rupiah: int


class OrderView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_number: str
    schedule_id: int
    status: OrderStatus
    pickup_at: UtcTimestamp
    order_cutoff_at: UtcTimestamp
    total_rupiah: int
    created_at: UtcTimestamp
    transfer_note: str | None = None
    transfer_reported_at: UtcTimestamp | None = None
    verified_at: UtcTimestamp | None = None
    payment_received_rupiah: int | None = None
    cancelled_at: UtcTimestamp | None = None
    cancellation_reason: str | None = None
    refund_outcome: RefundOutcome | None = None
    cancelled_by_role: Literal["buyer", "seller"] | None = None
    items: list[OrderItemView]


class OrderList(BaseModel):
    items: list[OrderView]


class OrderBuyerView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str


class SellerOrderView(OrderView):
    buyer: OrderBuyerView


class SellerOrderList(BaseModel):
    items: list[SellerOrderView]


CHECKOUT_KEY_MIN = 8
CHECKOUT_KEY_MAX = 64
MAX_CHECKOUT_ITEMS = 50

CheckoutKey = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=CHECKOUT_KEY_MIN,
        max_length=CHECKOUT_KEY_MAX,
        pattern=r"^[A-Za-z0-9_-]+$",
    ),
]


class CheckoutItemInput(BaseModel):
    """One reviewed cart line. Prices are quotes to compare, never trusted totals."""

    model_config = ConfigDict(extra="forbid")

    offer_id: int = Field(gt=0, strict=True)
    quantity: int = Field(ge=1, le=999, strict=True)
    quoted_price_rupiah: int = Field(ge=PRICE_MIN, le=PRICE_MAX, strict=True)


class CheckoutInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checkout_key: CheckoutKey
    schedule_id: int = Field(gt=0, strict=True)
    items: list[CheckoutItemInput] = Field(
        min_length=1, max_length=MAX_CHECKOUT_ITEMS
    )

    @model_validator(mode="after")
    def offers_must_be_unique(self) -> "CheckoutInput":
        offer_ids = [item.offer_id for item in self.items]
        if len(offer_ids) != len(set(offer_ids)):
            raise ValueError("Setiap penawaran hanya boleh muncul satu kali dalam pesanan.")
        return self


TransferNote = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=3, max_length=200)
]
CancellationReason = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=3, max_length=300)
]


class TransferReportInput(BaseModel):
    """A short matching note from the buyer; it is never proof of payment."""

    model_config = ConfigDict(extra="forbid")

    note: TransferNote


class BuyerCancelInput(BaseModel):
    """The buyer cancellation has no fields; rejecting extras keeps it explicit."""

    model_config = ConfigDict(extra="forbid")


class VerifyPaymentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    received_total_rupiah: int = Field(
        ge=1000, le=MAX_ORDER_TOTAL_RUPIAH, strict=True
    )


class SellerCancelInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: CancellationReason
    refund_outcome: RefundOutcome


class FulfillmentActionInput(BaseModel):
    """Pickup steps have no fields; rejecting extras keeps the transition explicit."""

    model_config = ConfigDict(extra="forbid")


class ScheduleArchiveInput(BaseModel):
    """Archive and restore have no fields; rejecting extras keeps them explicit."""

    model_config = ConfigDict(extra="forbid")


class ProductionRecapLine(BaseModel):
    """One selling unit offered in a schedule, summed for paid live orders."""

    offer_id: int
    product_id: int
    product_name: str
    selling_unit: str
    quantity: int


class ProductionRecapSchedule(BaseModel):
    schedule_id: int
    pickup_at: UtcTimestamp
    order_cutoff_at: UtcTimestamp
    orders_open: bool
    archived: bool
    lines: list[ProductionRecapLine]
    # Server-computed sum of line quantities, never the number of orders or products.
    total_quantity: int


class ProductionRecap(BaseModel):
    included_statuses: list[OrderStatus]
    items: list[ProductionRecapSchedule]
