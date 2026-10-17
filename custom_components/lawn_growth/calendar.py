"""Lawn Growth's application calendar (read-only): windows and logged applications."""
from __future__ import annotations

from datetime import datetime

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.util import dt as dt_util

from .entity import LawnEntity


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    async_add_entities([ApplicationsCalendar(entry.runtime_data)])


def _event(e) -> CalendarEvent:
    return CalendarEvent(start=e.start, end=e.end, summary=e.summary,
                         description=e.description or None, uid=e.key)


class ApplicationsCalendar(LawnEntity, CalendarEntity):
    """All-day events from model.appcalendar.calendar_events, rebuilt on every run."""

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "applications", "calendar")

    @property
    def event(self) -> CalendarEvent | None:
        today = dt_util.now().date()
        upcoming = [e for e in self.coordinator.calendar if e.end > today]
        return _event(min(upcoming, key=lambda e: e.start)) if upcoming else None

    async def async_get_events(self, hass, start_date: datetime,
                               end_date: datetime) -> list[CalendarEvent]:
        events = [_event(e) for e in self.coordinator.calendar]
        return [e for e in events
                if e.start_datetime_local < end_date and e.end_datetime_local > start_date]
