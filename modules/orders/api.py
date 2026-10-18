from datetime import datetime
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from modules.inventory.contract import InsufficientStock, ProductNotFound
from modules.orders.models import Order
from modules.orders.service import (
    InvalidOrderState,
    OrderLineInput,
    OrderNotFound,
    OrdersService,
    UnknownProduct,
)


class OrderLineRequest(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    quantity: int = Field(gt=0)


class CreateOrderRequest(BaseModel):
    customer_id: str = Field(min_length=1, max_length=100)
    lines: list[OrderLineRequest] = Field(min_length=1)


class OrderLineResponse(BaseModel):
    sku: str
    quantity: int
    unit_price: Decimal


class OrderResponse(BaseModel):
    id: UUID
    customer_id: str
    status: str
    total: Decimal
    created_at: datetime
    cancelled_at: datetime | None
    lines: list[OrderLineResponse]

    @classmethod
    def from_order(cls, order: Order) -> "OrderResponse":
        return cls(
            id=order.id,
            customer_id=order.customer_id,
            status=order.status,
            total=order.total,
            created_at=order.created_at,
            cancelled_at=order.cancelled_at,
            lines=[
                OrderLineResponse(
                    sku=line.sku,
                    quantity=line.quantity,
                    unit_price=line.unit_price,
                )
                for line in order.lines
            ],
        )


def _not_found(order_id: UUID) -> HTTPException:
    return HTTPException(
        status.HTTP_404_NOT_FOUND,
        {"error": "order_not_found", "order_id": str(order_id)},
    )


def build_router(service: OrdersService) -> APIRouter:
    router = APIRouter(prefix="/orders", tags=["orders"])

    @router.post(
        "",
        response_model=OrderResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_order(body: CreateOrderRequest) -> OrderResponse:
        try:
            order = await service.create_order(
                customer_id=body.customer_id,
                lines=[
                    OrderLineInput(sku=line.sku, quantity=line.quantity)
                    for line in body.lines
                ],
            )
        except UnknownProduct as exc:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                {"error": "product_not_found", "sku": exc.sku},
            ) from exc
        except ProductNotFound as exc:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                {"error": "product_not_found", "sku": exc.sku},
            ) from exc
        except InsufficientStock as exc:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                {
                    "error": "insufficient_stock",
                    "sku": exc.sku,
                    "requested": exc.requested,
                    "available": exc.available,
                },
            ) from exc
        return OrderResponse.from_order(order)

    @router.get("/{order_id}", response_model=OrderResponse)
    async def get_order(order_id: UUID) -> OrderResponse:
        try:
            order = await service.get_order(order_id)
        except OrderNotFound as exc:
            raise _not_found(order_id) from exc
        return OrderResponse.from_order(order)

    @router.post("/{order_id}/cancel", response_model=OrderResponse)
    async def cancel_order(
        order_id: UUID, reason: str | None = None
    ) -> OrderResponse:
        try:
            order = await service.cancel_order(order_id, reason=reason)
        except OrderNotFound as exc:
            raise _not_found(order_id) from exc
        except InvalidOrderState as exc:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                {"error": "invalid_order_state", "status": exc.status},
            ) from exc
        return OrderResponse.from_order(order)

    return router
