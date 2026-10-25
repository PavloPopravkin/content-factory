import logging

from ..config import Channel
from ..models import Asset, Delivery, Part, Result, Slot, State
from .base import HttpPublisher, validate_context

log = logging.getLogger(__name__)


class DryPublisher(HttpPublisher):
    def publish(self, delivery: Delivery, slot: Slot, channel: Channel, media: list[Asset]) -> Result:
        validate_context(delivery, slot, channel, media)
        self.gate()
        log.info("DRY tenant=%s slot=%s channel=%s kind=%s", slot.tenant_slug, slot.id, channel.id, slot.kind)
        return self.save(delivery, ids={"dry_id": delivery.delivery_key}, state=State.PUBLISHED,
                         parts=[self.part(delivery, "dry", delivery.delivery_key)])

    def reconcile(self, delivery: Delivery) -> Result:
        return Result(state=State.PUBLISHED if delivery.external_ids.get("dry_id") else State.UNKNOWN,
                      external_ids=delivery.external_ids)

    def delete(self, part: Part) -> None:
        self.gate()
        log.info("DRY delete %s", part.external_id)
