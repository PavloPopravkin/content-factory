from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import os

import httpx

from .config import Channel, Tenant
from .models import Delivery, Result, Slot, State
from .planner import admit, blackout_violations
from .publishers import DryPublisher, MetaPublisher, PostizPublisher, TelegramPublisher
from .publishers.base import PolicyBlocked, PublishDeferred, Publisher, PublisherError
from .storage import Store


@dataclass
class TickReport:
    published: int = 0
    accepted: int = 0
    failed: int = 0
    unknown: int = 0
    blocked: int = 0
    skipped: int = 0
    reconciled: int = 0
    deferred: int = 0
    missed: int = 0

    def __str__(self) -> str:
        return " ".join(f"{key}={value}" for key, value in vars(self).items())


def publisher_for(channel: Channel, client: httpx.Client, gate: Callable[[], None],
                  checkpoint: Callable[[Result], None]) -> Publisher:
    options = {"gate": gate, "checkpoint": checkpoint}
    if channel.publisher == "dry":
        return DryPublisher(client, **options)
    secret = os.environ.get(channel.secret_ref)
    if not secret:
        raise ValueError(f"missing publisher credential env var {channel.secret_ref}")
    if channel.publisher == "telegram":
        return TelegramPublisher(client, secret, channel.external_id, **options)
    if channel.publisher == "meta":
        return MetaPublisher(client, secret, graph_version=os.environ.get("CF_META_GRAPH_VERSION", "v25.0"), **options)
    url = os.environ.get("CF_POSTIZ_URL")
    if not url:
        raise ValueError("CF_POSTIZ_URL is required for postiz publisher")
    return PostizPublisher(client, secret, url, **options)


Factory = Callable[[Channel, httpx.Client, Callable[[], None], Callable[[Result], None]], Publisher]


def tick(store: Store, tenant: Tenant, *, clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
         factory: Factory = publisher_for, client: httpx.Client | None = None,
         emit: Callable[[str], None] = lambda text: None) -> TickReport:
    with store.lock():
        store.register(tenant)
        if client is None:
            with httpx.Client(timeout=30, follow_redirects=False, trust_env=False) as session:
                return _tick(store, tenant, clock, factory, session, emit)
        return _tick(store, tenant, clock, factory, client, emit)


def _tick(store: Store, tenant: Tenant, clock: Callable[[], datetime], factory: Factory,
          client: httpx.Client, emit: Callable[[str], None]) -> TickReport:
    report = TickReport()
    # A process may have died at any point after its committed submitting fence.
    for delivery in store.deliveries(tenant.slug):
        if delivery.state == State.SUBMITTING:
            store.checkpoint(delivery, Result(state=State.UNKNOWN, error="interrupted submitting; never auto retry"))

    for delivery in store.deliveries(tenant.slug):
        if delivery.state not in (State.ACCEPTED, State.UNKNOWN):
            continue
        def read_gate() -> None:
            violations = blackout_violations(clock(), tenant)
            if violations:
                raise PolicyBlocked(", ".join(violations))

        try:
            adapter = factory(tenant.channel(delivery.channel_id), client, read_gate,
                              lambda result, d=delivery: store.checkpoint(d, result))
            read_gate()
            result = adapter.reconcile(delivery)
            store.checkpoint(delivery, result)
            report.reconciled += 1
            emit(f"reconcile {delivery.id} {result.state}")
        except PolicyBlocked:
            continue
        except (PublisherError, ValueError) as exc:
            # Failure of a read cannot prove that an accepted write failed.
            store.event(tenant.slug, "reconcile_error", slot_id=delivery.slot_id, delivery_id=delivery.id,
                        details={"error": str(exc)})

    for slot in store.slots(tenant.slug):
        if slot.cancelled or slot.missed or slot.at > clock():
            continue
        deliveries = {d.channel_id: d for d in store.deliveries(tenant.slug, slot.id)}
        pending = [c for c in slot.channel_ids if c not in deliveries or deliveries[c].state == State.DEFERRED]
        if pending and clock() - slot.at > timedelta(minutes=tenant.schedule.max_lateness_minutes):
            store.miss(slot)
            report.missed += 1
            emit(f"missed {slot.id}: maximum lateness exceeded")
            continue
        for channel_id in slot.channel_ids:
            previous = deliveries.get(channel_id)
            if previous and (previous.state != State.DEFERRED or previous.next_attempt_at > clock()):
                report.skipped += 1
                continue
            delivery: Delivery | None = None
            fingerprint: str | None = None

            def send_gate() -> None:
                fresh = store.check_approval(store.get_slot(tenant.slug, slot.id))
                if (fresh.version != slot.version or fresh.caption != slot.caption
                        or fresh.media_ids != slot.media_ids or set(fresh.channel_ids) != set(slot.channel_ids)
                        or (fingerprint is not None and store.content_hash(fresh) != fingerprint)):
                    raise PolicyBlocked("slot content changed during submission")
                if clock() - fresh.at > timedelta(minutes=tenant.schedule.max_lateness_minutes):
                    raise PolicyBlocked("maximum lateness exceeded")
                candidate = fresh.model_copy(update={"at": clock(), "channel_ids": [channel_id]})
                violations = admit(candidate, tenant, store.history(tenant.slug))
                if violations:
                    raise PolicyBlocked(", ".join(violations))

            def checkpoint(result: Result) -> None:
                if delivery is None:
                    raise RuntimeError("publisher checkpoint before delivery fence")
                store.checkpoint(delivery, result)

            try:
                channel = tenant.channel(channel_id)
                media = store.media(slot)
                send_gate()
                fingerprint = store.content_hash(slot)
                adapter = factory(channel, client, send_gate, checkpoint)
                if isinstance(adapter, PostizPublisher):
                    def reserve_post() -> None:
                        send_gate()
                        wait = store.consume_postiz_token(tenant.slug, adapter.rate_scope, adapter.api_limit, clock())
                        if wait:
                            raise PublishDeferred("Postiz org API_LIMIT budget exhausted", wait)
                    adapter.reserve_post = reserve_post
                delivery = (store.retry_delivery(previous, at=clock()) if previous
                            else store.begin_delivery(slot, channel_id, at=clock()))
                result = adapter.publish(delivery, slot, channel, media)
                if result.state == State.SUBMITTING:
                    raise ValueError("publisher returned nonterminal submitting result")
                store.checkpoint(delivery, result)
            except PublishDeferred as exc:
                if delivery is None:
                    raise
                if isinstance(adapter, PostizPublisher):
                    store.postpone_postiz(tenant.slug, adapter.rate_scope, adapter.api_limit, clock(), exc.retry_after)
                if store.parts(tenant.slug, delivery.id):
                    # Earlier public effects cannot be replayed with a fresh publish call.
                    result = Result(state=State.UNKNOWN, error=str(exc))
                    store.checkpoint(delivery, result)
                else:
                    store.defer(delivery, at=clock() + timedelta(seconds=exc.retry_after), error=str(exc))
                    result = Result(state=State.DEFERRED, error=str(exc))
            except (PublisherError, ValueError, OSError) as exc:
                if delivery is None:
                    if isinstance(exc, PolicyBlocked):
                        report.blocked += 1
                        emit(f"blocked {slot.id}/{channel_id}: {exc}")
                    else:
                        report.failed += 1
                        store.event(tenant.slug, "preflight_failed", slot_id=slot.id,
                                    details={"channel_id": channel_id, "error": str(exc)})
                        emit(f"preflight failed {slot.id}/{channel_id}: {exc}")
                    continue
                uncertain = (getattr(exc, "uncertain", False) or bool(delivery.external_ids)
                             or bool(store.parts(tenant.slug, delivery.id)))
                state = State.UNKNOWN if uncertain else State.FAILED
                store.checkpoint(delivery, Result(state=state, error=str(exc)))
                result = Result(state=state, error=str(exc))
            except Exception:
                if delivery is not None:
                    store.checkpoint(delivery, Result(state=State.UNKNOWN, error="unexpected publisher failure"))
                raise
            setattr(report, result.state.value, getattr(report, result.state.value) + 1)
            emit(f"delivery {delivery.id} {result.state} channel={channel_id}")
    return report
