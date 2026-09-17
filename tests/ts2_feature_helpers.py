"""Real offline Canonical-reader/PIT fixtures for TS2 Feature tests."""

from dataclasses import fields, replace

from cross_day_helpers import AS_OF, ARCHIVE, bar, build, pit, local
from market_vault.dataset.models import DatasetField
from market_vault.dataset.spec_models import FeatureSpec, SpecParameter, SpecVersionRequirements
from market_vault.ts2_feature import execute_ts2_features

FIELDS = {
    "candle_body": ("open", "close"), "candle_range": ("high", "low"),
    "rolling_volume_mean": ("volume",), "volume_ratio": ("volume",),
}


def spec(transform="simple_return", *, n=2, name=None, schema="10.9-mv-ts2"):
    name = name or "ts2_" + transform
    return FeatureSpec("market-vault-feature-spec-v1", name, "v1", DatasetField(name, "float64", False),
        FIELDS.get(transform, ("close",)), f"market_vault.dataset.feature_transforms.{transform}:{transform}",
        () if transform in ("candle_body", "candle_range") else (SpecParameter("window_bars", n),),
        SpecVersionRequirements(("market-bars-canonical-schema-v1",), (schema,)))


def fixture(tmp_path, *, slots=(0, 1), schema="10.9-mv-ts2"):
    bars = tuple(bar(slot=slot, close=100.0 + 25.0 * i, schema=schema) for i, slot in enumerate(slots))
    one = build(tmp_path, bars, schema=schema)
    result = pit((one,), slot=max(slots, default=1))
    return one, result


def execute(one, result, specs=None, *, cutoff=AS_OF):
    return execute_ts2_features((one,), result, (spec(),) if specs is None else specs, dataset_as_of=cutoff)


def tamper(record, **changes):
    assert set(changes) <= {f.name for f in fields(record)}
    copy = replace(record)
    for name, item in changes.items():
        object.__setattr__(copy, name, item)
    return copy
