from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from modules.inventory.contract import (
    InsufficientStock,
    Product,
    ProductNotFound,
    Reservation,
)
from modules.inventory.service import DuplicateSku, SqlInventoryService


class ProductCreate(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    unit_price: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    quantity: int = Field(ge=0)


class ProductResponse(BaseModel):
    sku: str
    name: str
    unit_price: Decimal
    available: int

    @classmethod
    def from_contract(cls, product: Product) -> "ProductResponse":
        return cls(
            sku=product.sku,
            name=product.name,
            unit_price=product.unit_price,
            available=product.available,
        )


class AvailabilityResponse(BaseModel):
    sku: str
    quantity: int
    available: bool


class ReservationRequest(BaseModel):
    order_id: UUID
    sku: str = Field(min_length=1, max_length=64)
    quantity: int = Field(gt=0)


class ReservationResponse(BaseModel):
    reservation_id: UUID
    order_id: UUID
    sku: str
    quantity: int

    @classmethod
    def from_contract(cls, reservation: Reservation) -> "ReservationResponse":
        return cls(
            reservation_id=reservation.id,
            order_id=reservation.order_id,
            sku=reservation.sku,
            quantity=reservation.quantity,
        )


class ReleaseResponse(BaseModel):
    released: int


def build_router(service: SqlInventoryService) -> APIRouter:
    router = APIRouter(prefix="/inventory", tags=["inventory"])

    @router.post(
        "/products",
        response_model=ProductResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_product(body: ProductCreate) -> ProductResponse:
        try:
            product = await service.create_product(
                sku=body.sku,
                name=body.name,
                unit_price=body.unit_price,
                quantity=body.quantity,
            )
        except DuplicateSku as exc:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                {"error": "duplicate_sku", "sku": exc.sku, "message": str(exc)},
            ) from exc
        return ProductResponse.from_contract(product)

    @router.get("/products", response_model=list[ProductResponse])
    async def list_products() -> list[ProductResponse]:
        return [
            ProductResponse.from_contract(product)
            for product in await service.list_products()
        ]

    @router.get("/products/{sku}", response_model=ProductResponse)
    async def get_product(sku: str) -> ProductResponse:
        product = await service.get_product(sku)
        if product is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                {"error": "product_not_found", "sku": sku},
            )
        return ProductResponse.from_contract(product)

    @router.get("/availability/{sku}", response_model=AvailabilityResponse)
    async def check_availability(
        sku: str, quantity: int = Query(default=1, gt=0)
    ) -> AvailabilityResponse:
        return AvailabilityResponse(
            sku=sku,
            quantity=quantity,
            available=await service.check_availability(sku, quantity),
        )

    @router.post(
        "/reservations",
        response_model=ReservationResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def reserve(body: ReservationRequest) -> ReservationResponse:
        try:
            reservation = await service.reserve(
                order_id=body.order_id,
                sku=body.sku,
                quantity=body.quantity,
            )
        except ProductNotFound as exc:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                {"error": "product_not_found", "sku": exc.sku, "message": str(exc)},
            ) from exc
        except InsufficientStock as exc:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                {
                    "error": "insufficient_stock",
                    "sku": exc.sku,
                    "requested": exc.requested,
                    "available": exc.available,
                    "message": str(exc),
                },
            ) from exc
        return ReservationResponse.from_contract(reservation)

    @router.delete(
        "/reservations/order/{order_id}", response_model=ReleaseResponse
    )
    async def release_for_order(
        order_id: UUID, reason: str = "order_cancelled"
    ) -> ReleaseResponse:
        released = await service.release_for_order(order_id, reason=reason)
        return ReleaseResponse(released=released)

    return router
