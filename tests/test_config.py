from pathlib import Path

import pytest
import yaml

from content_factory.config import Tenant, load_tenant

DEMO = Path(__file__).parents[1] / "examples/tenants/demo"


def test_full_demo():
    tenant = load_tenant(DEMO)
    assert tenant.schema_version == 1
    assert tenant.channels[0].publisher == "dry"
    assert tenant.schedule.blackout[0].from_ == "fri 15:00"
    assert Tenant.model_validate_json(tenant.model_dump_json(by_alias=True)) == tenant


@pytest.mark.parametrize("field,value,expected", [
    ("schema_version", 2, "schema_version"),
    ("slug", "../other", "slug"),
    ("timezone", "Moon/Sea", "timezone"),
    ("languages", {"content": [], "ops": "en", "contributors": ["en"]}, "content"),
    ("unknown", 1, "Extra inputs"),
])
def test_invalid_top_level(tenant, field, value, expected):
    data = tenant.model_dump(mode="json", by_alias=True)
    data[field] = value
    with pytest.raises(ValueError, match=expected):
        Tenant.model_validate(data)


@pytest.mark.parametrize("path,value", [
    (("channels", 0, "secret_ref"), "1234:actual-token"),
    (("channels", 0, "token"), "forbidden"),
    (("channels", 0, "publisher"), "unknown"),
    (("channels", 0, "capabilities"), ["invented"]),
    (("schedule", "daily_caps"), {"post": 1}),
    (("schedule", "daily_caps"), {"post": -1, "reel": 2, "story": 2}),
    (("schedule", "min_gap_minutes"), -1),
    (("schedule", "hours"), ["99:00", "24:00"]),
    (("schedule", "hours"), ["00:00", "00:00"]),
    (("schedule", "blackout"), [{"type": "weekly", "from": "friday 15:00", "to": "sat 21:00"}]),
    (("schedule", "blackout"), [{"type": "weekly", "from": "fri 15:00", "to": "fri 15:00"}]),
    (("schedule", "blackout"), [{"type": "sunset_shabbat", "lat": 91, "lon": 0,
                                "margin_before_min": 30, "margin_after_min": 70}]),
])
def test_invalid_nested(tenant, path, value):
    data = tenant.model_dump(mode="json", by_alias=True)
    current = data
    for part in path[:-1]:
        current = current[part]
    current[path[-1]] = value
    with pytest.raises(ValueError):
        Tenant.model_validate(data)


def test_duplicate_channels(tenant):
    data = tenant.model_dump(mode="json", by_alias=True)
    data["channels"] *= 2
    with pytest.raises(ValueError, match="unique"):
        Tenant.model_validate(data)


@pytest.mark.parametrize("publisher,channel_type", [("telegram", "ig"), ("meta", "yt")])
def test_wrong_publisher_type(tenant, publisher, channel_type):
    data = tenant.model_dump(mode="json", by_alias=True)
    data["channels"][0].update(publisher=publisher, type=channel_type)
    with pytest.raises(ValueError, match="requires"):
        Tenant.model_validate(data)


@pytest.mark.parametrize("policy", ["../outside.md", "missing.md", "policy.txt"])
def test_policy_path(tmp_path, tenant, policy):
    data = tenant.model_dump(mode="json", by_alias=True)
    data["policy_file"] = policy
    (tmp_path / "tenant.yaml").write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError, match="Invalid tenant config"):
        load_tenant(tmp_path)


def test_policy_symlink_escape(tmp_path, tenant):
    directory = tmp_path / "tenant"
    directory.mkdir()
    (tmp_path / "outside.md").write_text("policy")
    (directory / "policy.md").symlink_to(tmp_path / "outside.md")
    (directory / "tenant.yaml").write_text(yaml.safe_dump(tenant.model_dump(mode="json", by_alias=True)))
    with pytest.raises(ValueError, match="inside"):
        load_tenant(directory)


@pytest.mark.parametrize("contents", ["[broken", "null", "name: only"])
def test_invalid_yaml(tmp_path, contents):
    (tmp_path / "tenant.yaml").write_text(contents)
    with pytest.raises(ValueError, match="Invalid tenant config"):
        load_tenant(tmp_path)
