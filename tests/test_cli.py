from datetime import datetime, timezone
from pathlib import Path
import shutil

from typer.testing import CliRunner

from content_factory.cli import app
from content_factory.storage import Store

runner = CliRunner()


def invoke(tmp_path, *args):
    return runner.invoke(app, ["--db", str(tmp_path / "db.sqlite3"), "--tenants-root", str(tmp_path / "tenants"), *args])


def demo(tmp_path):
    source = Path(__file__).parents[1] / "examples/tenants/demo"
    shutil.copytree(source, tmp_path / "tenants/demo")


def test_quick_start_cli(tmp_path, monkeypatch):
    demo(tmp_path)
    # A fixed Sunday avoids a clock-dependent weekly blackout in the test.
    monkeypatch.setattr("content_factory.cli.run_tick", lambda store, tenant, emit:
                        __import__("content_factory.scheduler", fromlist=["tick"]).tick(
                            store, tenant, clock=lambda: datetime(2026, 10, 25, 12, tzinfo=timezone.utc), emit=emit))
    assert invoke(tmp_path, "tenant", "validate", str(tmp_path / "tenants/demo")).exit_code == 0
    assert invoke(tmp_path, "db", "migrate").exit_code == 0
    added = invoke(tmp_path, "slot", "add", "--tenant", "demo", "--at", "2026-10-25T10:00:00Z", "--kind", "post",
                   "--channels", "demo-feed", "--caption", "Demo")
    assert added.exit_code == 0, added.output
    slot_id = added.output.strip()
    blocked = invoke(tmp_path, "tick", "--tenant", "demo")
    assert blocked.exit_code == 0 and "blocked=1" in blocked.output
    assert invoke(tmp_path, "slot", "approve", slot_id).exit_code == 0
    result = invoke(tmp_path, "tick", "--tenant", "demo")
    assert result.exit_code == 0 and "published=1" in result.output
    repeat = invoke(tmp_path, "tick", "--tenant", "demo")
    assert repeat.exit_code == 0 and "published=0" in repeat.output and "skipped=1" in repeat.output
    status = invoke(tmp_path, "status", "--tenant", "demo")
    assert status.exit_code == 0 and "demo-feed=published" in status.output
    assert invoke(tmp_path, "slot", "cancel", slot_id, "--tenant", "demo").exit_code == 0
    with Store(tmp_path / "db.sqlite3") as store:
        assert store.get_slot("demo", slot_id).cancelled
        assert len(store.deliveries("demo")) == 1


def test_cli_fails_clearly_on_naive_at(tmp_path):
    demo(tmp_path)
    result = invoke(tmp_path, "slot", "add", "--tenant", "demo", "--at", "2026-10-25T10:00:00",
                    "--kind", "post", "--channels", "demo-feed")
    assert result.exit_code == 1 and "timezone" in result.output


def test_cli_bad_tenant_and_channel(tmp_path):
    demo(tmp_path)
    result = invoke(tmp_path, "tick", "--tenant", "../other")
    assert result.exit_code == 1 and "invalid tenant slug" in result.output
    result = invoke(tmp_path, "slot", "add", "--tenant", "demo", "--at", "2026-10-25T10:00:00Z",
                    "--kind", "post", "--channels", "other")
    assert result.exit_code == 1 and "unknown channel" in result.output


def test_cli_add_media_and_cancel_tenant_scope(tmp_path):
    demo(tmp_path)
    file = tmp_path / "photo.jpg"
    file.write_bytes(b"fake")
    added = invoke(tmp_path, "slot", "add", "--tenant", "demo", "--at", "2026-10-25T10:00:00Z",
                   "--kind", "post", "--channels", "demo-feed", "--media", str(file))
    assert added.exit_code == 0, added.output
    slot_id = added.output.strip()
    assert invoke(tmp_path, "slot", "cancel", slot_id, "--tenant", "other").exit_code == 1
    with Store(tmp_path / "db.sqlite3") as store:
        slot = store.get_slot("demo", slot_id)
        assert store.media(slot)[0].source == str(file)
        assert not slot.cancelled
