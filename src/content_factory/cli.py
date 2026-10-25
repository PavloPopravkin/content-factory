from dataclasses import dataclass
from datetime import datetime
from functools import wraps
import logging
from pathlib import Path
from typing import Annotated, Any, Callable
from urllib.parse import urlparse

import typer

from .config import Tenant, load_tenant
from .models import Asset, Kind, Slot
from .scheduler import tick as run_tick
from .storage import LockedError, Store

app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)
tenant_app = typer.Typer(no_args_is_help=True)
db_app = typer.Typer(no_args_is_help=True)
slot_app = typer.Typer(no_args_is_help=True)
app.add_typer(tenant_app, name="tenant")
app.add_typer(db_app, name="db")
app.add_typer(slot_app, name="slot")


@dataclass
class Settings:
    db: Path
    tenants_root: Path


def user_errors(fn: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(fn)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except (ValueError, OSError, LockedError) as exc:
            typer.echo(f"Error: {exc}", err=True)
            raise typer.Exit(1) from None
    return wrapped


@app.callback()
def main(ctx: typer.Context,
         db: Annotated[Path, typer.Option(envvar="CF_DB")] = Path(".cf/content_factory.sqlite3"),
         tenants_root: Annotated[Path, typer.Option(envvar="CF_TENANTS_ROOT")] = Path("tenants")) -> None:
    ctx.obj = Settings(db, tenants_root)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def tenant_config(ctx: typer.Context, slug: str) -> Tenant:
    if not slug or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in slug):
        raise ValueError("invalid tenant slug")
    tenant = load_tenant(ctx.obj.tenants_root / slug / "tenant.yaml")
    if tenant.slug != slug:
        raise ValueError("tenant slug differs from directory name")
    return tenant


@tenant_app.command("validate")
@user_errors
def tenant_validate(path: Path) -> None:
    tenant = load_tenant(path)
    typer.echo(f"valid tenant={tenant.slug} schema_version={tenant.schema_version} channels={len(tenant.channels)}")


@db_app.command("migrate")
@user_errors
def migrate(ctx: typer.Context) -> None:
    with Store(ctx.obj.db) as store:
        store.migrate()
    typer.echo("database migrated")


@slot_app.command("add")
@user_errors
def slot_add(ctx: typer.Context, tenant: Annotated[str, typer.Option()],
             at: Annotated[str, typer.Option(help="ISO 8601 datetime with UTC offset")],
             kind: Annotated[Kind, typer.Option()], channels: Annotated[str, typer.Option(help="Comma-separated channel ids")],
             caption: Annotated[str, typer.Option()] = "",
             media: Annotated[list[str] | None, typer.Option(help="Repeat --media for each path or URL")] = None) -> None:
    config = tenant_config(ctx, tenant)
    assets = []
    for source in media or []:
        parsed = urlparse(source)
        path = parsed.path if parsed.scheme in ("https", "http") else source
        if parsed.scheme not in ("https", "http"):
            file = Path(source).resolve()
            if not file.is_file():
                raise ValueError(f"media file does not exist: {source}")
            source = str(file)
        media_kind = "video" if Path(path).suffix.lower() in (".mp4", ".mov", ".webm", ".m4v") else "photo"
        assets.append(Asset(tenant_slug=tenant, source=source, kind=media_kind))
    channel_ids = [c.strip() for c in channels.split(",")]
    for channel_id in channel_ids:
        config.channel(channel_id)
    slot = Slot(tenant_slug=tenant, at=at, kind=kind, channel_ids=channel_ids,
                caption=caption, media_ids=[a.id for a in assets])
    with Store(ctx.obj.db) as store:
        store.migrate()
        with store.lock():
            store.register(config)
            for asset in assets:
                store.add_asset(asset)
            store.add_slot(slot)
    typer.echo(slot.id)


def slot_tenant(store: Store, slot_id: str, tenant: str | None) -> str:
    if tenant is not None:
        store.get_slot(tenant, slot_id)
        return tenant
    # Local CLI is an operator tool, not a remotely exposed authorization boundary.
    row = store.db.execute("SELECT tenant_slug FROM slot WHERE id=?", (slot_id,)).fetchone()
    if row is None:
        raise ValueError(f"slot {slot_id} not found")
    return row[0]


@slot_app.command("approve")
@user_errors
def slot_approve(ctx: typer.Context, slot_id: str, tenant: Annotated[str | None, typer.Option()] = None) -> None:
    with Store(ctx.obj.db) as store:
        store.migrate()
        with store.lock():
            store.approve(slot_tenant(store, slot_id, tenant), slot_id)
    typer.echo(f"approved {slot_id}")


@slot_app.command("cancel")
@user_errors
def slot_cancel(ctx: typer.Context, slot_id: str, tenant: Annotated[str | None, typer.Option()] = None) -> None:
    with Store(ctx.obj.db) as store:
        store.migrate()
        with store.lock():
            store.cancel(slot_tenant(store, slot_id, tenant), slot_id)
    typer.echo(f"cancelled {slot_id}; existing publications are retained")


@app.command("tick")
@user_errors
def tick(ctx: typer.Context, tenant: Annotated[str, typer.Option()]) -> None:
    config = tenant_config(ctx, tenant)
    with Store(ctx.obj.db) as store:
        store.migrate()
        report = run_tick(store, config, emit=typer.echo)
    typer.echo(f"tick tenant={tenant} {report}")


@app.command("status")
@user_errors
def status(ctx: typer.Context, tenant: Annotated[str, typer.Option()]) -> None:
    tenant_config(ctx, tenant)
    with Store(ctx.obj.db) as store:
        store.migrate()
        for slot in store.slots(tenant):
            deliveries = store.deliveries(tenant, slot.id)
            states = ",".join(f"{d.channel_id}={d.state}" for d in deliveries) or "pending"
            typer.echo(f"{slot.id} {slot.at.isoformat()} {slot.kind} v{slot.version} "
                       f"approved={slot.approved_version} cancelled={slot.cancelled} {states}")
            for delivery in deliveries:
                if delivery.error:
                    typer.echo(f"  {delivery.channel_id}: {delivery.error}")
