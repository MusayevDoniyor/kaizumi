"""actions/calendar.py — Google Calendar (list / add / delete events)."""
from datetime import datetime, timedelta, timezone

from googleapiclient.discovery import build

import google_oauth


def _service():
    creds = google_oauth.get_credentials()
    if not creds:
        raise RuntimeError(
            "Google is not authorized yet. Run 'google_auth' first, or say "
            "'googleni avtorizatsiya qil' and follow the code link.")
    return build("calendar", "v3", credentials=creds)


def _fmt(dt_str: str) -> str:
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        local = dt.astimezone()
        return local.strftime("%d.%m %H:%M")
    except Exception:
        return dt_str


def _parse_time(value: str | None, default) -> str:
    """Accept '2026-08-20 15:00', '15:00', or ISO; returns RFC3339."""
    v = (value or "").strip()
    if not v:
        return default.isoformat()
    tz = default.tzinfo
    try:
        if len(v) <= 5 and ":" in v and "-" not in v:
            hh, mm = v.split(":")
            return default.replace(hour=int(hh), minute=int(mm), second=0).isoformat()
        if len(v) == 16 and " " in v:
            return datetime.strptime(v, "%Y-%m-%d %H:%M").replace(tzinfo=tz).isoformat()
        return datetime.fromisoformat(v).isoformat()
    except Exception:
        return default.isoformat()


def calendar_action(parameters: dict, response=None, player=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "list")).lower().strip()
    try:
        svc = _service()

        if action in ("list", "upcoming", "today", "agenda"):
            max_results = int(params.get("max_results", 10) or 10)
            tz = timezone(timedelta(hours=5))
            now = datetime.now(tz)
            time_min = now.isoformat()
            time_max = (now + timedelta(days=30)).isoformat()
            events = svc.events().list(
                calendarId=params.get("calendar_id", "primary"),
                timeMin=time_min, timeMax=time_max,
                maxResults=max_results, singleEvents=True,
                orderBy="startTime",
            ).execute().get("items", [])
            if not events:
                return "No upcoming events in the next 30 days, sir."
            lines = ["📅 Upcoming events:"]
            for ev in events:
                start = (ev.get("start") or {}).get("dateTime") or (ev.get("start") or {}).get("date", "?")
                lines.append(f"• {_fmt(start)}  {ev.get('summary', '(no title)')}")
            return "\n".join(lines)

        if action in ("add", "create", "new"):
            summary = str(params.get("summary", "")).strip()
            if not summary:
                return "I need the event title (summary), sir."
            now = datetime.now(timezone(timedelta(hours=5)))
            start_iso = _parse_time(params.get("start"), now)
            end_iso   = _parse_time(params.get("end"), now + timedelta(hours=1))
            body = {
                "summary":     summary,
                "start":       {"dateTime": start_iso},
                "end":         {"dateTime": end_iso},
                "description": str(params.get("description", "")).strip(),
            }
            created = svc.events().insert(
                calendarId=params.get("calendar_id", "primary"), body=body).execute()
            link = created.get("htmlLink", "")
            return (f"✅ Added: '{summary}' at {_fmt(start_iso)}. "
                    f"{link}")

        if action in ("delete", "remove", "cancel"):
            ev_id = str(params.get("event_id", "")).strip()
            if ev_id:
                svc.events().delete(
                    calendarId=params.get("calendar_id", "primary"),
                    eventId=ev_id).execute()
                return "Event deleted, sir."
            # delete by summary match
            query = str(params.get("summary", "")).strip().lower()
            if not query:
                return "I need event_id or a summary to delete, sir."
            now = datetime.now(timezone(timedelta(hours=5)))
            events = svc.events().list(
                calendarId="primary", timeMin=now.isoformat(),
                maxResults=50, singleEvents=True,
            ).execute().get("items", [])
            for ev in events:
                if query in ev.get("summary", "").lower():
                    svc.events().delete(calendarId="primary", eventId=ev["id"]).execute()
                    return f"Deleted '{ev.get('summary')}', sir."
            return f"No upcoming event matching '{query}' found, sir."

        return f"Unknown calendar action: {action}. Use list | add | delete."
    except Exception as e:
        return f"Calendar error: {e}"
