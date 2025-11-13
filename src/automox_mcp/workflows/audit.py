"""Audit trail workflows for Automox MCP."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from typing import Any, cast
from urllib.parse import parse_qs, urlparse
from uuid import UUID

from pydantic import EmailStr, TypeAdapter, ValidationError

from ..client import AutomoxAPIError, AutomoxClient
from ..utils import resolve_org_uuid

_EMAIL_VALIDATOR: TypeAdapter[EmailStr] = TypeAdapter(EmailStr)

_SANITIZED_STRING_LIMIT = 400
_SANITIZED_SEQUENCE_LIMIT = 10
_MAX_RECURSION_DEPTH = 6


def _normalize_email(value: str | None) -> str | None:
    if value is None:
        return None
    email = value.strip().lower()
    return email or None


def _normalize_uuid(value: str | None) -> str | None:
    if value is None:
        return None
    uuid_text = str(value).strip().lower()
    return uuid_text or None


def _email_looks_valid(value: str | None) -> bool:
    if not value:
        return False
    try:
        _EMAIL_VALIDATOR.validate_python(value)
    except ValidationError:
        return False
    else:
        return True
    email = _normalize_email(value)
    if not email:
        return False
    if "@" not in email:
        return False
    local, _, domain = email.partition("@")
    return bool(local) and bool(domain)


def _tokenize(value: str | None) -> list[str]:
    if not value:
        return []
    return [token for token in value.lower().split() if token]


def _string_from_keys(payload: Mapping[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = payload.get(key)
        if value in (None, "", [], {}):
            continue
        if isinstance(value, (str, int)):
            text = str(value).strip()
            if text:
                return text
        elif hasattr(value, "hex"):  # UUID-like
            text = str(value).strip()
            if text:
                return text
    return None


def _extract_user_info(obj: Any) -> dict[str, Any] | None:
    if not isinstance(obj, Mapping):
        return None

    current: Mapping[str, Any] | None = obj
    visited: set[int] = set()
    while isinstance(current, Mapping) and "user" in current:
        next_obj = current.get("user")
        if not isinstance(next_obj, Mapping):
            break
        obj_id = id(next_obj)
        if obj_id in visited:
            break
        visited.add(obj_id)
        current = next_obj

    if not isinstance(current, Mapping):
        return None

    email = _string_from_keys(current, ("email_addr", "email", "email_address", "username"))
    uuid_text = _string_from_keys(current, ("uid", "uuid", "id"))
    display_name = _string_from_keys(current, ("display_name", "name", "full_name"))
    role = _string_from_keys(current, ("role", "role_name"))

    org_info = current.get("org") if isinstance(current.get("org"), Mapping) else None
    org_details: dict[str, str] | None = None
    if isinstance(org_info, Mapping):
        org_uuid = _string_from_keys(org_info, ("uid", "uuid", "id"))
        org_name = _string_from_keys(org_info, ("name",))
        filtered_details = {k: v for k, v in {"uuid": org_uuid, "name": org_name}.items() if v}
        org_details = cast(dict[str, str], filtered_details)

    result: dict[str, Any] = {
        "email": email,
        "uuid": uuid_text,
        "name": display_name,
        "role": role,
    }
    result = {k: v for k, v in result.items() if v}
    if org_details:
        result["organization"] = org_details
    return result or None


def _extract_account_user(record: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(record, Mapping):
        return None

    email = _string_from_keys(record, ("email_addr", "email", "email_address", "username"))
    uuid_text = _string_from_keys(record, ("uid", "uuid", "id", "user_id"))
    display_name = _string_from_keys(record, ("display_name", "name", "full_name"))
    first_name = _string_from_keys(record, ("first_name", "first"))
    last_name = _string_from_keys(record, ("last_name", "last"))
    role = _string_from_keys(record, ("role", "role_name", "account_rbac_role"))

    combined_name = display_name
    if not combined_name:
        combined_name = " ".join(part for part in (first_name, last_name) if part)

    result: dict[str, Any] = {
        "email": email,
        "uuid": uuid_text,
        "name": combined_name or None,
        "role": role,
    }
    result = {k: v for k, v in result.items() if v}
    return result or None


async def _lookup_actor_from_hints(
    client: AutomoxClient,
    *,
    actor_name: str | None,
    actor_email_hint: str | None,
) -> tuple[str | None, str | None, dict[str, Any]]:
    name_text = (actor_name or "").strip()
    email_hint = (actor_email_hint or "").strip()

    normalized_name_tokens = _tokenize(name_text)
    normalized_email_hint = _normalize_email(email_hint) if email_hint else None

    resolved_email: str | None = None
    partial_email: str | None = None
    if normalized_email_hint:
        if _email_looks_valid(normalized_email_hint):
            resolved_email = normalized_email_hint
        else:
            partial_email = normalized_email_hint

    if not name_text and not partial_email:
        return (
            resolved_email,
            None,
            {
                "status": "skipped",
                "reason": "no_lookup_hints",
            },
        )

    account_uuid = getattr(client, "account_uuid", None)
    if not account_uuid:
        return (
            resolved_email,
            None,
            {
                "status": "skipped",
                "reason": "missing_account_uuid",
            },
        )

    search_terms: list[str] = []
    if name_text:
        search_terms.append(name_text)
    if partial_email and partial_email not in search_terms:
        search_terms.append(partial_email)
    if not search_terms and resolved_email:
        search_terms.append(resolved_email)

    candidates: list[dict[str, Any]] = []
    seen_keys: set[tuple[str | None, str | None]] = set()

    for term in search_terms:
        params: dict[str, Any] = {"limit": 200}
        if term:
            params["search"] = term
        try:
            response = await client.get(
                f"/accounts/{account_uuid}/users",
                params=params,
                api="console",
            )
        except AutomoxAPIError as exc:
            error_payload: dict[str, Any] = {
                "status": "error",
                "reason": "actor_lookup_request_failed",
                "search_terms": search_terms,
                "matches_considered": len(candidates),
                "error": {
                    "status_code": exc.status_code,
                    "message": str(exc),
                    "payload": exc.payload,
                },
            }
            if partial_email and partial_email != resolved_email:
                error_payload["partial_email_hint"] = partial_email
            return resolved_email, None, error_payload
        if isinstance(response, Sequence):
            user_items = response
        elif isinstance(response, Mapping):
            data_block = response.get("data")
            if isinstance(data_block, Sequence):
                user_items = data_block
            else:
                user_items = []
        else:
            user_items = []

        for item in user_items:
            record = _extract_account_user(item if isinstance(item, Mapping) else None)
            if not record:
                continue
            normalized_email = _normalize_email(record.get("email"))
            normalized_uuid = _normalize_uuid(record.get("uuid"))
            key = (normalized_email, normalized_uuid)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            record["normalized_email"] = normalized_email
            record["normalized_uuid"] = normalized_uuid
            candidates.append(record)

        # Stop once we have a reasonable pool to score
        if len(candidates) >= 25:
            break

    if not candidates:
        return (
            resolved_email,
            None,
            {
                "status": "no_matches",
                "search_terms": search_terms,
                "matches_considered": 0,
            },
        )

    scored_matches: list[dict[str, Any]] = []
    for record in candidates:
        score = 0
        reasons: list[str] = []

        candidate_email = record.get("normalized_email")
        candidate_name = (record.get("name") or "").lower()

        if resolved_email and candidate_email and candidate_email == resolved_email:
            score += 120
            reasons.append("email_exact")
        if partial_email and candidate_email and partial_email in candidate_email:
            score += 60
            reasons.append("email_partial")
        if normalized_name_tokens and candidate_name:
            matched_tokens = [token for token in normalized_name_tokens if token in candidate_name]
            if matched_tokens:
                score += 25 * len(matched_tokens)
                if len(matched_tokens) == len(normalized_name_tokens):
                    score += 15
                reasons.append(f"name_tokens:{len(matched_tokens)}")
        if not reasons:
            score = max(score, 5)
            reasons.append("search_match")

        scored_matches.append(
            {
                "record": record,
                "score": score,
                "reasons": reasons,
            }
        )

    scored_matches.sort(key=lambda item: item["score"], reverse=True)

    top_matches = [
        {
            "name": match["record"].get("name"),
            "email": match["record"].get("email"),
            "uuid": match["record"].get("uuid"),
            "role": match["record"].get("role"),
            "score": match["score"],
            "matched_on": match["reasons"],
        }
        for match in scored_matches[:5]
    ]

    best_match = scored_matches[0] if scored_matches else None
    resolved_uuid = None
    resolved_display_name = None

    if best_match:
        best_record = best_match["record"]
        resolved_email = resolved_email or best_record.get("normalized_email")
        resolved_uuid = best_record.get("normalized_uuid")
        resolved_display_name = best_record.get("name")

    lookup_metadata: dict[str, Any] = {
        "status": "matched" if best_match else "no_matches",
        "search_terms": search_terms,
        "matches_considered": len(candidates),
        "top_matches": top_matches,
    }
    if resolved_email or resolved_uuid or resolved_display_name:
        lookup_metadata["resolved"] = {
            k: v
            for k, v in {
                "name": resolved_display_name,
                "email": resolved_email,
                "uuid": resolved_uuid,
            }.items()
            if v
        }
    if partial_email and partial_email != resolved_email:
        lookup_metadata["partial_email_hint"] = partial_email

    return resolved_email, resolved_uuid, lookup_metadata


def _extract_actor(event: Mapping[str, Any]) -> dict[str, Any] | None:
    actor_obj = event.get("actor")
    if not isinstance(actor_obj, Mapping):
        return None
    actor_info = _extract_user_info(actor_obj)
    if actor_info and "role" not in actor_info:
        role_obj = actor_obj.get("role")
        if isinstance(role_obj, Mapping):
            role_name = _string_from_keys(role_obj, ("name", "role"))
            if role_name:
                actor_info["role"] = role_name
    return actor_info


def _extract_target_user(event: Mapping[str, Any]) -> dict[str, Any] | None:
    for key in ("user", "target", "subject", "resource"):
        candidate = event.get(key)
        info = _extract_user_info(candidate)
        if info:
            return info
    return None


def _collect_observable_values(
    event: Mapping[str, Any],
    *,
    desired_types: Sequence[str],
) -> list[str]:
    observables = event.get("observables")
    if not isinstance(observables, Sequence):
        return []

    extracted: list[str] = []
    desired_lower = {item.lower() for item in desired_types}
    for item in observables:
        if not isinstance(item, Mapping):
            continue
        value = item.get("value")
        if not isinstance(value, str) or not value.strip():
            continue
        type_name = str(item.get("type") or item.get("name") or "").lower()
        if type_name in desired_lower:
            extracted.append(value.strip())
            continue
        type_id = item.get("type_id")
        if isinstance(type_id, int) and type_id == 5 and "email" in desired_lower:
            extracted.append(value.strip())
    return extracted


def _coerce_datetime(value: Any, depth: int = 0) -> datetime | None:
    if depth > _MAX_RECURSION_DEPTH:
        return None

    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)

    if isinstance(value, (int, float)):
        timestamp = float(value)
        if timestamp > 1_000_000_000_000:  # likely milliseconds
            timestamp /= 1000.0
        try:
            return datetime.fromtimestamp(timestamp, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        # Try integer conversion first
        try:
            int_value = int(text)
        except ValueError:
            pass
        else:
            return _coerce_datetime(int_value, depth + 1)
        # Fall back to ISO parsing
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)

    if isinstance(value, Mapping):
        for key in (
            "observed_time",
            "generated_time",
            "detected_time",
            "event_time",
            "created_time",
            "updated_time",
            "time",
        ):
            if key not in value:
                continue
            dt = _coerce_datetime(value[key], depth + 1)
            if dt:
                return dt
        return None

    return None


def _format_timestamp(value: Any) -> str | None:
    dt = _coerce_datetime(value)
    if not dt:
        return None
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _resolve_event_time(event: Mapping[str, Any]) -> str | None:
    for key in (
        "time",
        "event_time",
        "observed_time",
        "generated_time",
        "detected_time",
        "created_time",
        "updated_time",
    ):
        if key in event:
            ts = _format_timestamp(event.get(key))
            if ts:
                return ts
    time_obj = event.get("time")
    if isinstance(time_obj, Mapping):
        ts = _format_timestamp(time_obj)
        if ts:
            return ts
    metadata = event.get("metadata")
    if isinstance(metadata, Mapping):
        ts = _format_timestamp(metadata.get("time"))
        if ts:
            return ts
    return None


def _sanitize_payload(value: Any, depth: int = 0) -> Any:
    if depth > _MAX_RECURSION_DEPTH:
        return "... (max depth reached)"

    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for key, inner_value in value.items():
            if inner_value in (None, "", [], {}):
                continue
            sanitized[key] = _sanitize_payload(inner_value, depth + 1)
        return sanitized

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        items = [_sanitize_payload(item, depth + 1) for item in value[:_SANITIZED_SEQUENCE_LIMIT]]
        if len(value) > _SANITIZED_SEQUENCE_LIMIT:
            items.append(f"... {len(value) - _SANITIZED_SEQUENCE_LIMIT} more")
        return items

    if isinstance(value, str):
        text = value.strip()
        if len(text) <= _SANITIZED_STRING_LIMIT:
            return text
        trimmed = text[:_SANITIZED_STRING_LIMIT]
        remaining = len(text) - _SANITIZED_STRING_LIMIT
        return f"{trimmed}... ({remaining} chars truncated)"

    return value


def _extract_event_cursor(event: Mapping[str, Any]) -> str | None:
    metadata = event.get("metadata")
    if isinstance(metadata, Mapping):
        cursor = metadata.get("uid") or metadata.get("cursor")
        if isinstance(cursor, (str, int)):
            cursor_text = str(cursor).strip()
            if cursor_text:
                return cursor_text
    direct_uid = event.get("uid") or event.get("id")
    if isinstance(direct_uid, (str, int)):
        cursor_text = str(direct_uid).strip()
        if cursor_text:
            return cursor_text
    return None


def _collect_event_emails(
    event: Mapping[str, Any],
    *,
    actor: Mapping[str, Any] | None,
    target_user: Mapping[str, Any] | None,
) -> set[str]:
    emails: set[str] = set()

    def add_email(value: Any) -> None:
        normalized = _normalize_email(str(value)) if isinstance(value, str) else None
        if normalized:
            emails.add(normalized)

    if actor and actor.get("email"):
        add_email(actor.get("email"))
    if target_user and target_user.get("email"):
        add_email(target_user.get("email"))

    user_obj = event.get("user")
    if isinstance(user_obj, Mapping):
        add_email(user_obj.get("email_addr") or user_obj.get("email"))

    observables_emails = _collect_observable_values(
        event,
        desired_types=("email address", "email"),
    )
    for item in observables_emails:
        add_email(item)

    return emails


def _collect_event_uuids(
    event: Mapping[str, Any],
    *,
    actor: Mapping[str, Any] | None,
    target_user: Mapping[str, Any] | None,
) -> set[str]:
    uuids: set[str] = set()

    def add_uuid(value: Any) -> None:
        normalized = _normalize_uuid(str(value)) if isinstance(value, str) else None
        if normalized:
            uuids.add(normalized)

    if actor and actor.get("uuid"):
        add_uuid(actor.get("uuid"))
    if target_user and target_user.get("uuid"):
        add_uuid(target_user.get("uuid"))

    user_obj = event.get("user")
    if isinstance(user_obj, Mapping):
        add_uuid(user_obj.get("uid") or user_obj.get("uuid") or user_obj.get("id"))

    observables_org_ids = _collect_observable_values(
        event,
        desired_types=("organization id", "organization.id", "uuid"),
    )
    for item in observables_org_ids:
        add_uuid(item)

    return uuids


def _summarize_event(
    event: Mapping[str, Any],
    *,
    actor: dict[str, Any] | None,
    include_raw: bool,
) -> dict[str, Any]:
    target_user = _extract_target_user(event)
    event_cursor = _extract_event_cursor(event)
    event_time = _resolve_event_time(event)

    summary: dict[str, Any] = {
        "event_uid": event_cursor,
        "timestamp": event_time,
        "activity": event.get("activity"),
        "message": event.get("message"),
        "status": event.get("status") or event.get("status_name"),
        "severity": event.get("severity"),
        "category_uid": event.get("category_uid"),
        "type_uid": event.get("type_uid"),
        "actor": actor,
    }

    details: dict[str, Any] = {}
    for key in ("resource", "object", "policy", "device", "account", "http_request", "changes"):
        value = event.get(key)
        if isinstance(value, Mapping) or (
            isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))
        ):
            details[key] = _sanitize_payload(value)
    if details:
        summary["context"] = details

    if target_user and target_user != actor:
        summary["target_user"] = target_user

    if include_raw:
        summary["raw_event"] = _sanitize_payload(event)

    return {k: v for k, v in summary.items() if v not in (None, "", [], {})}


def _format_activity_summary(counter: Counter[str]) -> list[dict[str, Any]]:
    summary = []
    for activity, count in counter.most_common(10):
        summary.append({"activity": activity, "count": count})
    return summary


async def audit_trail_user_activity(
    client: AutomoxClient,
    *,
    org_id: int,
    date: date,
    actor_email: str | None = None,
    actor_uuid: str | UUID | None = None,
    actor_name: str | None = None,
    cursor: str | None = None,
    limit: int | None = None,
    include_raw_events: bool | None = False,
    org_uuid: str | UUID | None = None,
) -> dict[str, Any]:
    resolved_org_uuid = await resolve_org_uuid(
        client,
        explicit_uuid=org_uuid,
        org_id=org_id,
        allow_account_uuid=False,
    )

    query_date = date.isoformat()
    params: dict[str, Any] = {"date": query_date}
    if cursor:
        params["cursor"] = cursor
    if limit is not None:
        params["limit"] = limit

    headers = {"x-ax-organization-uuid": resolved_org_uuid}
    response = await client.get(
        f"/audit-service/v1/orgs/{resolved_org_uuid}/events",
        params=params,
        headers=headers,
        api="console",
    )

    api_metadata: Mapping[str, Any] | None = None
    events: list[Mapping[str, Any]]
    if isinstance(response, Sequence):
        events = [item for item in response if isinstance(item, Mapping)]
    elif isinstance(response, Mapping):
        api_metadata = (
            response.get("metadata") if isinstance(response.get("metadata"), Mapping) else None
        )
        data_block = response.get("data")
        if isinstance(data_block, Sequence):
            events = [item for item in data_block if isinstance(item, Mapping)]
        else:
            events = []
    else:
        events = []

    actor_email_text = (actor_email or "").strip() or None
    actor_uuid_text = str(actor_uuid).strip() if actor_uuid is not None else ""
    actor_uuid_filter_input = actor_uuid_text or None
    actor_name_text = (actor_name or "").strip() or None

    normalized_email_filter = _normalize_email(actor_email_text)
    normalized_uuid_filter = _normalize_uuid(actor_uuid_filter_input)
    lookup_metadata: dict[str, Any] | None = None

    if actor_name_text or (actor_email_text and not _email_looks_valid(actor_email_text)):
        resolved_email, resolved_uuid, lookup_metadata = await _lookup_actor_from_hints(
            client,
            actor_name=actor_name_text,
            actor_email_hint=actor_email_text,
        )
        if resolved_email:
            normalized_email_filter = resolved_email
        if resolved_uuid:
            normalized_uuid_filter = resolved_uuid

    include_raw = bool(include_raw_events)

    filtered_events: list[dict[str, Any]] = []
    activity_counter: Counter[str] = Counter()
    matched_actor_context: dict[str, Any] | None = None

    for event in events:
        actor_info = _extract_actor(event)
        target_user = _extract_target_user(event)

        candidate_emails = _collect_event_emails(event, actor=actor_info, target_user=target_user)
        candidate_uuids = _collect_event_uuids(event, actor=actor_info, target_user=target_user)

        if normalized_email_filter and normalized_email_filter not in candidate_emails:
            continue
        if normalized_uuid_filter and normalized_uuid_filter not in candidate_uuids:
            continue

        summary = _summarize_event(event, actor=actor_info, include_raw=include_raw)
        filtered_events.append(summary)
        activity = summary.get("activity")
        if isinstance(activity, str):
            activity_counter[activity] += 1
        if matched_actor_context is None and summary.get("actor"):
            matched_actor_context = summary["actor"]

    next_cursor = None
    for event in reversed(events):
        next_cursor = _extract_event_cursor(event)
        if next_cursor:
            break

    last_filtered_cursor = None
    if filtered_events:
        last_filtered_cursor = filtered_events[-1].get("event_uid")

    api_next_link = None
    api_result_count = None
    if api_metadata:
        api_next_link = api_metadata.get("next")
        count_value = (
            api_metadata.get("count")
            or api_metadata.get("total")
            or api_metadata.get("total_count")
        )
        if isinstance(count_value, int):
            api_result_count = count_value

    if api_next_link and not next_cursor:
        parsed = urlparse(str(api_next_link))
        params = parse_qs(parsed.query)
        maybe_cursor = params.get("cursor")
        if maybe_cursor:
            next_cursor = maybe_cursor[0]

    applied_filters = {
        "actor_email": normalized_email_filter,
        "actor_uuid": normalized_uuid_filter,
        "actor_name": actor_name_text,
        "cursor": cursor,
        "limit": limit,
        "include_raw_events": include_raw,
    }
    if actor_email_text and normalized_email_filter != _normalize_email(actor_email_text):
        applied_filters["actor_email_hint"] = actor_email_text

    resolved_actor = lookup_metadata.get("resolved") if lookup_metadata else None

    data = {
        "org_uuid": resolved_org_uuid,
        "date": query_date,
        "actor": matched_actor_context,
        "events": filtered_events,
        "activity_summary": _format_activity_summary(activity_counter),
        "events_returned": len(filtered_events),
    }
    if resolved_actor:
        data["resolved_actor"] = resolved_actor

    metadata = {
        "org_id": org_id,
        "org_uuid": resolved_org_uuid,
        "date": query_date,
        "cursor": cursor,
        "next_cursor": next_cursor,
        "last_event_cursor": last_filtered_cursor,
        "limit": limit,
        "events_seen": api_result_count if isinstance(api_result_count, int) else len(events),
        "events_returned": len(filtered_events),
        "applied_filters": applied_filters,
    }
    if api_next_link:
        metadata["api_next_link"] = api_next_link
    if lookup_metadata:
        metadata["actor_lookup"] = lookup_metadata

    return {
        "data": data,
        "metadata": metadata,
    }


__all__ = ["audit_trail_user_activity"]
