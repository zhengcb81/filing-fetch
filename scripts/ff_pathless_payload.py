"""Recognize private storage fields in otherwise pathless wire values."""


# Exact storage contract names: a business field such as growth_path is not
# a physical location. Unknown non-storage metadata is omitted by projection.
_PHYSICAL_FIELDS = frozenset(
    {
        "path",
        "paths",
        "path_ref",
        "canonical_path",
        "physical_path",
        "file_path",
        "absolute_path",
        "resolved_path",
        "storage_path",
        "document_path",
        "root",
        "roots",
        "root_id",
        "root_path",
        "root_kind",
        "physical_root",
        "company_wiki_root",
        "allowed_handle_roots",
        "location",
        "locations",
        "location_id",
        "canonical_location_id",
        "selected_location",
        "bundle",
        "source_bundle",
        "bundle_path",
        "bundle_status",
    }
)


def contains_physical_field(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            str(key).lower() in _PHYSICAL_FIELDS or contains_physical_field(child)
            for key, child in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(contains_physical_field(child) for child in value)
    return False
