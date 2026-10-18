from datetime import datetime
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel

from modules.notifications.models import Notification
from modules.notifications.service import NotificationService


class NotificationResponse(BaseModel):
    id: UUID
    order_id: UUID
    message: str
    created_at: datetime

    @classmethod
    def from_model(cls, notification: Notification) -> "NotificationResponse":
        return cls(
            id=notification.id,
            order_id=notification.order_id,
            message=notification.message,
            created_at=notification.created_at,
        )


def build_router(service: NotificationService) -> APIRouter:
    router = APIRouter(prefix="/notifications", tags=["notifications"])

    @router.get("/orders/{order_id}", response_model=list[NotificationResponse])
    async def list_for_order(order_id: UUID) -> list[NotificationResponse]:
        return [
            NotificationResponse.from_model(notification)
            for notification in await service.list_for_order(order_id)
        ]

    return router
