"""Rendering helpers for the calendar add-status portion of an event display.

Owns the mapping from `EventUserData.calendar_add_error` codes (emitted by the
server's CalendarAutoAddService) to user-facing messages plus a single
remediation hint per code. Returns `(severity, message)` tuples instead of
calling OutputFormatter directly so tests can assert on data rather than
captured stdout.

The success branch (`Added to {provider} calendar...`) is NOT in this module —
it stays inline in EventCommandBase.display_event_details. This module only
covers the no-add path.
"""

from typing import Any, Dict, List, Optional, Tuple

from herds_cli.api import APIClient

# (severity, message) where severity is "info" | "warning". The caller
# dispatches via OutputFormatter.print_info / print_warning. A two-line
# message embeds a literal "\n" so Rich renders the icon on the first line
# only and indents the continuation under it.
CalendarStatusLine = Tuple[str, str]
CalendarStatusOutput = List[CalendarStatusLine]


# Sentinel for "resolver hasn't been called yet" — distinct from None
# (which is a legitimate cached result meaning "not connected" or "fetch failed").
_UNFETCHED: Any = object()


class ReconnectProviderResolver:
    """Lazily fetches GET /api/calendar/status to learn which provider the
    user previously connected. Used only on the calendar_needs_reconnect path.

    One instance per upload — the result is cached so a multi-event image
    makes at most one extra HTTP call regardless of how many events trigger
    reconnect. Network failures and `connected: false` both collapse to None,
    which the renderer translates back into a `<google|outlook>` placeholder.
    """

    def __init__(self, api_client: APIClient) -> None:
        self._api_client = api_client
        self._cached: Any = _UNFETCHED

    def get_provider(self) -> Optional[str]:
        if self._cached is not _UNFETCHED:
            return self._cached
        provider: Optional[str] = None
        try:
            url = f"{self._api_client.base_url}/api/calendar/status"
            response = self._api_client._make_request("GET", url)
            if response.status_code == 200:
                data = response.json()
                if data.get("connected"):
                    raw = data.get("provider")
                    provider = raw if isinstance(raw, str) and raw else None
        except Exception:
            # Swallow on purpose — the renderer's placeholder fallback is
            # safer than bubbling up and masking the calendar-status message.
            # This intentionally also swallows SessionExpiredError raised by
            # APIClient._make_request: by the time it reaches us, _make_request
            # has already surfaced an OutputFormatter.print_error to the user
            # describing the auth failure, so re-raising here would only add
            # a second crashy stack trace on top of the existing notice.
            provider = None
        self._cached = provider
        return provider


# severity, plain-language reason, remediation hint
_CODE_TABLE: Dict[str, Tuple[str, str, str]] = {
    "auto_add_disabled": (
        "info",
        "auto-add is disabled in your settings",
        "Enable with: herds user-settings update --auto-add-to-calendar=True",
    ),
    "no_calendar_connection": (
        "info",
        "no calendar provider connected",
        "Connect with: herds calendar connect --provider google  (or --provider outlook)",
    ),
    "calendar_provider_error": (
        "warning",
        "your calendar provider rejected the event",
        "Run: herds calendar status   for connection diagnostics",
    ),
    "calendar_add_exception": (
        "warning",
        "an unexpected error occurred during auto-add",
        "Run: herds calendar status   for connection diagnostics",
    ),
}

_NEEDS_RECONNECT_PREFIX = (
    "Not added to calendar: connection has expired and needs to be reconnected"
)


def render_calendar_status(
    user_data: Dict[str, Any],
    *,
    resolver: Optional[ReconnectProviderResolver] = None,
) -> CalendarStatusOutput:
    """Build the calendar-status output for one event.

    Args:
        user_data: The event's `user_data` dict (may be empty).
        resolver: Optional. Required only to produce a precise reconnect hint
            on `calendar_needs_reconnect` — without it (or if it returns None)
            the hint falls back to `<google|outlook>`.

    Returns:
        A list of (severity, message) tuples. Empty list is never returned —
        every event produces at least one calendar-status line so the user is
        never left guessing.
    """
    code_raw = user_data.get("calendar_add_error")
    if not code_raw:
        return [("info", "Not added to a calendar")]

    code = code_raw.lower() if isinstance(code_raw, str) else ""

    if code == "calendar_needs_reconnect":
        provider = resolver.get_provider() if resolver is not None else None
        provider_arg = provider if provider else "<google|outlook>"
        hint = f"Reconnect with: herds calendar connect --provider {provider_arg}"
        return [("warning", f"{_NEEDS_RECONNECT_PREFIX}\n   {hint}")]

    entry = _CODE_TABLE.get(code)
    if entry is None:
        return [("warning", f"Not added to calendar: {code_raw}")]

    severity, reason, hint = entry
    return [(severity, f"Not added to calendar: {reason}\n   {hint}")]
