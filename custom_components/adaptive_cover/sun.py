"""Fetch sun data."""

from datetime import UTC, date, datetime, time, timedelta

from astral import Observer
from astral.sun import sunrise, sunset
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

try:
    from homeassistant.helpers.sun import get_astral_observer
except ImportError:

    def get_astral_observer(hass: HomeAssistant) -> Observer:
        """Build an Astral observer for older Home Assistant releases."""
        return Observer(
            latitude=hass.config.latitude,
            longitude=hass.config.longitude,
            elevation=hass.config.elevation,
        )


class SunData:
    """Access local sun data."""

    def __init__(self, timezone, hass: HomeAssistant) -> None:  # noqa: D107
        self.hass = hass
        self.observer = get_astral_observer(self.hass)
        self.timezone = timezone

    @property
    def times(self) -> list[datetime]:
        """Zwróć chwile co 5 minut od lokalnej północy do kolejnej (z obiema)."""
        tz = (
            dt_util.get_time_zone(self.timezone)
            if isinstance(self.timezone, str)
            else self.timezone
        )
        today = dt_util.now().date()
        # Krok w UTC: doba zmiany czasu ma 23 lub 25 godzin, jak w pandas.date_range.
        moment = datetime.combine(today, time(), tzinfo=tz).astimezone(UTC)
        end = datetime.combine(today + timedelta(days=1), time(), tzinfo=tz)
        result = []
        while moment <= end:
            result.append(moment.astimezone(tz))
            moment += timedelta(minutes=5)
        return result

    def sunset(self, on_date: date | None = None) -> datetime:
        """Fetch sunset time."""
        return sunset(self.observer, on_date or dt_util.now().date())

    def sunrise(self, on_date: date | None = None) -> datetime:
        """Fetch sunrise time."""
        return sunrise(self.observer, on_date or dt_util.now().date())
