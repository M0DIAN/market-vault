"""Full bar outcomes for every original request, including non-matrix samples."""

from dataclasses import dataclass, replace
from datetime import datetime

from ..dataset.encoding import encode_identity, normalize_utc_datetime
from ..dataset.feature_models import FeatureValueResult
from ..dataset.label_models import LabelValueResult
from ..dataset.pit_identity import pit_sample_key, pit_sample_version_id
from ..dataset.pit_models import PITSampleRequest
from ._orchestration_validation import canonical_copy, flatten, hashes, items, pin_key, record, require


@dataclass(frozen=True, slots=True)
class MultiSourceSampleAudit:
    sample_key: str
    request: PITSampleRequest
    bar_sample_version_id: str
    dataset_as_of: datetime | None
    considered_canonical_build_ids: tuple[str, ...]
    feature_canonical_row_version_ids: tuple[str, ...]
    label_canonical_row_version_ids: tuple[str, ...]
    bar_feature_status: str
    bar_feature_values: tuple[FeatureValueResult, ...]
    label_status: str
    actual_label_end_time: datetime | None
    label_values: tuple[LabelValueResult, ...]

    def __post_init__(self):
        request = canonical_copy(self.request, PITSampleRequest, "audit request")
        object.__setattr__(self, "request", request)
        if self.dataset_as_of is not None:
            object.__setattr__(self, "dataset_as_of", normalize_utc_datetime(self.dataset_as_of, "dataset_as_of"))
        for name in ("considered_canonical_build_ids", "feature_canonical_row_version_ids", "label_canonical_row_version_ids"):
            value = getattr(self, name)
            normalized = hashes(value, name)
            if name == "considered_canonical_build_ids":
                object.__setattr__(self, name, normalized)
        require(self.sample_key == pit_sample_key(request), "audit sample key mismatch")
        version = pit_sample_version_id(sample_key=self.sample_key, dataset_as_of=self.dataset_as_of,
            feature_canonical_row_version_ids=self.feature_canonical_row_version_ids,
            label_canonical_row_version_ids=self.label_canonical_row_version_ids,
            considered_canonical_build_ids=self.considered_canonical_build_ids)
        require(self.bar_sample_version_id == version, "audit bar sample version mismatch")
        for name, cls in (("bar_feature_values", FeatureValueResult), ("label_values", LabelValueResult)):
            values = tuple(canonical_copy(v, cls, name) for v in items(getattr(self, name), cls, name, nonempty=True))
            require(len({v.spec_pin.name for v in values}) == len(values), "duplicate audit outcome")
            object.__setattr__(self, name, tuple(sorted(values, key=lambda v: pin_key(v.spec_pin))))
        for value in self.bar_feature_values:
            require(set(value.consumed_canonical_row_version_ids) <= set(self.feature_canonical_row_version_ids),
                    "bar Feature consumption outside exact sample role")
        for value in self.label_values:
            require(value.anchor_canonical_row_version_id is None or
                    value.anchor_canonical_row_version_id in self.feature_canonical_row_version_ids,
                    "Label anchor outside Feature association")
            require(set(value.consumed_label_canonical_row_version_ids) <= set(self.label_canonical_row_version_ids),
                    "Label consumption outside exact sample role")
        feature_status = "COMPLETE" if all(v.status == "COMPLETE" for v in self.bar_feature_values) else "EXCLUDED"
        label_status = "COMPLETE" if all(v.status == "COMPLETE" for v in self.label_values) else "INCOMPLETE"
        ends = [v.actual_label_end_time for v in self.label_values if v.actual_label_end_time is not None]
        require(self.bar_feature_status == feature_status and self.label_status == label_status,
                "audit aggregate status mismatch")
        require(self.actual_label_end_time == (max(ends) if ends else None), "audit Label end mismatch")


def normalize_audit(audit):
    audit = tuple(replace(a) for a in items(audit, MultiSourceSampleAudit, "sample audit"))
    require(len({a.sample_key for a in audit}) == len(audit), "duplicate sample audit")
    return tuple(sorted(audit, key=lambda a: a.sample_key))


def sample_audit_content_id(audit: tuple[MultiSourceSampleAudit, ...]) -> str:
    return encode_identity("multi-source-sample-audit-v1", flatten("samples", record(normalize_audit(audit))))


def build_audit(pit, features, labels):
    by_feature = {s.sample_key: s for s in features.samples}
    by_label = {s.sample_key: s for s in labels.samples}
    result = []
    association = {(r["sample_key"], r["role"], r["canonical_row_version_id"]): r for r in pit.association_rows}
    for sample in pit.samples:
        feature, label = by_feature[sample.sample_key], by_label[sample.sample_key]
        for value in label.values:
            if value.consumed_label_canonical_row_version_ids:
                row = association[(sample.sample_key, "LABEL", value.consumed_label_canonical_row_version_ids[-1])]
                require(value.actual_label_end_time == row["market_available_at"], "per-Label end not last consumed row")
            else:
                require(value.actual_label_end_time is None, "Label without consumed rows has an end")
        result.append(MultiSourceSampleAudit(sample.sample_key, sample.request, sample.sample_version_id,
            sample.dataset_as_of, sample.considered_canonical_build_ids, sample.feature_canonical_row_version_ids,
            sample.label_canonical_row_version_ids, feature.status, feature.values,
            label.status, label.actual_label_end_time, label.values))
    return normalize_audit(tuple(result))
