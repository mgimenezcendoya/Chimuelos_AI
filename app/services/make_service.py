from typing import Dict, Any
import httpx
from app.core.config import settings
from app.models.order import Order

class MakeService:
    def __init__(self):
        self.webhook_url = settings.MAKE_WEBHOOK_URL
        self.api_key = settings.MAKE_API_KEY
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
    
    async def send_order(self, order: Order) -> Dict[str, Any]:
        """Send order to Make.com webhook"""
        async with httpx.AsyncClient() as client:
            payload = self._prepare_order_payload(order)
            response = await client.post(
                self.webhook_url,
                json=payload,
                headers=self.headers
            )
            response.raise_for_status()
            return response.json()
    
    def _prepare_order_payload(self, order: Order) -> Dict[str, Any]:
        """Prepare order data for Make.com webhook"""
        return {
            "order_id": order.id,
            "customer": {
                "id": order.customer.id,
                "name": order.customer.name,
                "phone": order.customer.phone_number
            },
            "items": order.items,
            "total_amount": order.total_amount,
            "status": order.status.value,
            "delivery_address": order.delivery_address,
            "payment_method": order.payment_method,
            "notes": order.notes,
            "created_at": order.created_at.isoformat(),
            "updated_at": order.updated_at.isoformat()
        }
    
    async def update_order_status(self, order_id: int, status: str) -> None:
        """Update order status from Make.com webhook"""
        # This method will be called by the webhook endpoint when Make.com
        # sends updates about order status changes
        pass 