"""Pure validation and owner-editor projection for sparse mapping Drafts."""
import copy
import hashlib
from pathlib import Path

from agent.core.standard_field_catalog import get_standard_field_catalog
from agent.tools.rule_generator import apply_manual_field_mappings, rules_to_base64_text
from agent.tools.rule_generator.field_mapping import MAPPING_EXCLUDED_STANDARD_FIELDS
from .mapping_projection import mapping_rows, operation_key


class DraftError(ValueError):
    def __init__(self, code, details=None):
        super().__init__(code)
        self.details = details or {}


def catalog_version():
    loaded = get_standard_field_catalog().standard_fields_text
    try:
        current = (Path(__file__).resolve().parents[4] / "config" / "标准字段.txt").read_text(encoding="utf-8")
    except OSError:
        raise DraftError("mapping_catalog_changed") from None
    if current != loaded:
        raise DraftError("mapping_catalog_changed")
    return hashlib.sha256(loaded.encode("utf-8")).hexdigest()


def flatten_operations(operations):
    changes = {}
    for operation in operations:
        for change in operation["changes"]:
            changes[(change["sub_rule_id"], change["source_path"])] = change
    return list(changes.values())


def effective_changes(base, operations):
    return [change for change in flatten_operations(operations)
            if str(next(entry for entry in base["config"][int(change["sub_rule_id"])]["normalize"]
               if entry.get("index") == change["source_path"]).get("field") or "") != (change["standard_field"] or "")]


def project_payload(base, operations, *, editing=False, validate_occupancy=True):
    changes = effective_changes(base, operations)
    result = copy.deepcopy(base)
    result["config"] = apply_manual_field_mappings(base["config"], changes, validate_occupancy=validate_occupancy)
    identities = {(str(item["sub_rule_id"]), item["source_path"]) for item in base.get("manual_fields", [])}
    identities.update((item["sub_rule_id"], item["source_path"]) for item in changes)
    result["manual_fields"] = [{"sub_rule_id": rule, "source_path": source} for rule, source in sorted(identities)]
    if editing:
        result["row_order"] = {rule["id"]: [row["source_path"] for row in rule["rows"]] for rule in mapping_rows(base)}
        result["draft_fields"] = changes
        result["group_statuses"] = {rule["id"]: {row["source_path"]: row["status"] for row in rule["rows"]} for rule in mapping_rows(base)}
    else:
        result.pop("row_order", None)
        result["download_content"] = rules_to_base64_text(result["config"])
    return result


def candidates(payload, proposal):
    source, target = proposal["source_path"], proposal.get("standard_field") or ""
    current, linked = proposal["sub_rule_id"], proposal.get("linked_sub_rule_ids", [])
    items = []
    for rule in mapping_rows(payload):
        if rule["id"] == current:
            continue
        row = next((row for row in rule["rows"] if row["source_path"] == source), None)
        if row is None:
            continue
        occupant = next((entry.get("index") for entry in payload["config"][int(rule["id"])].get("normalize", [])
                         if target and entry.get("field") == target and entry.get("index") != source), None)
        items.append({"sub_rule_id": rule["id"], "name": rule["name"],
                      "current_standard_field": row["standard_field"], "samples": row["samples"],
                      "selectable": row["editable"] and occupant is None, "conflict_source_path": occupant,
                      "disabled_reason": ("mapping_source_not_editable" if not row["editable"] else
                                          "mapping_target_conflict" if occupant else None),
                      "selected": rule["id"] in linked})
    return {"source_path": source, "standard_field": target or None, "items": items}


def prepare_operation(base, operations, key, proposal, *, replace=False):
    if key != operation_key(proposal["sub_rule_id"], proposal["source_path"]):
        raise DraftError("mapping_operation_key_invalid")
    previous = next((operation for operation in operations if operation["operation_key"] == key), None)
    current = project_payload(base,operations)
    previous_current = previous is not None and all(
        str(next(entry for entry in current["config"][int(change["sub_rule_id"])]["normalize"]
            if entry.get("index") == change["source_path"]).get("field") or "") == (change["standard_field"] or "")
        for change in previous["changes"])
    if previous_current and previous["proposal"] == proposal:
        return previous,candidates(current,proposal),False
    without = [operation for operation in operations if operation["operation_key"] != key]
    payload = project_payload(base, without, validate_occupancy=False)
    rules = mapping_rows(payload)
    rule = next((rule for rule in rules if rule["id"] == proposal["sub_rule_id"]), None)
    if rule is None:
        raise DraftError("mapping_sub_rule_not_found")
    row = next((row for row in rule["rows"] if row["source_path"] == proposal["source_path"]), None)
    if row is None or not row["editable"]:
        raise DraftError("mapping_source_not_editable", {"sub_rule_id":rule["id"],"source_path":proposal["source_path"]})
    target = proposal.get("standard_field") or ""
    legal = {field.system_property_name for field in get_standard_field_catalog().fields} - MAPPING_EXCLUDED_STANDARD_FIELDS
    if target and target not in legal:
        raise DraftError("mapping_target_invalid", {"sub_rule_id": rule["id"], "source_path": row["source_path"]})
    linked = proposal.get("linked_sub_rule_ids", [])
    if len(linked) != len(set(linked)) or rule["id"] in linked:
        raise DraftError("mapping_scope_invalid")
    choices = candidates(payload, proposal)
    selectable = {item["sub_rule_id"] for item in choices["items"] if item["selectable"]}
    if any(identifier not in selectable for identifier in linked):
        raise DraftError("mapping_link_conflict", {"candidates": choices})
    occupant = next((entry.get("index") for entry in payload["config"][int(rule["id"])].get("normalize", [])
                     if target and entry.get("field") == target and entry.get("index") != row["source_path"]), None)
    if occupant and not replace:
        raise DraftError("mapping_target_conflict", {"proposal": proposal, "operation_key": key,
                         "occupied_by": occupant, "candidates": choices})
    changes = [{"sub_rule_id": identifier, "source_path": row["source_path"], "standard_field": target or None}
               for identifier in [rule["id"], *linked]]
    if occupant:
        if not any(item["source_path"] == occupant for item in rule["rows"]):
            raise DraftError("mapping_occupant_not_editable")
        changes.append({"sub_rule_id": rule["id"], "source_path": occupant, "standard_field": None})
    changes = [change for change in changes if str(next(entry for entry in payload["config"][int(change["sub_rule_id"])]["normalize"]
                if entry.get("index") == change["source_path"]).get("field") or "") != (change["standard_field"] or "")]
    operation = {"operation_key": key, "proposal": proposal, "changes": changes}
    project_payload(base, [*without, operation])  # Validate the entire resulting configuration.
    return operation, choices, previous != operation or not previous_current
