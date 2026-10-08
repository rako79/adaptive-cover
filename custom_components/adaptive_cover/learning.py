"""Persistent behavioral learning for Adaptive Cover."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store

STORAGE_VERSION = 1
LEARNING_GUARD_VERSION = 4
LEARNING_GUARD_RESET_REASON = "temperature_source_guard_upgrade"
POSITION_BIAS_LIMIT = 25.0
TEMPERATURE_OFFSET_LIMIT = 3.0


def _bounded_offsets(values: dict, limit: float) -> dict[str, float]:
    """Odrzuć uszkodzone liczby i ogranicz odczytane preferencje."""
    result = {}
    for key, value in values.items():
        numeric = float(value)
        if not isfinite(numeric):
            raise ValueError("Niepoprawna liczba w danych uczenia")
        result[str(key)] = max(-limit, min(limit, numeric))
    return result


class BehavioralLearner:
    """Learn small user preference offsets from genuine manual overrides."""

    def __init__(self, hass: HomeAssistant, logger, entry_id: str) -> None:
        """Initialize persistent learning for one config entry."""
        self.hass = hass
        self.logger = logger
        self.alpha = 0.1
        self.position_biases: dict[str, float] = {}
        self.temperature_offsets: dict[str, float] = {}
        self.override_counts: dict[str, int] = {}
        self.loaded = False
        self.last_load_at: datetime | None = None
        self.last_load_error: str | None = None
        self.last_override: dict[str, Any] | None = None
        self.last_save_scheduled_at: datetime | None = None
        self.last_direct_sun_at: datetime | None = None
        self.last_guard_reset_at: datetime | None = None
        self.guard_reset_reason: str | None = None
        self._last_direct_sun_saved_at: datetime | None = None
        self._store = Store(
            hass,
            STORAGE_VERSION,
            f"adaptive_cover.learning.{entry_id}",
        )

    async def async_load(self) -> None:
        """Restore learned values from Home Assistant storage."""
        try:
            data: dict[str, Any] = await self._store.async_load() or {}
        except (HomeAssistantError, OSError) as err:
            self.last_load_error = str(err)
            self.logger.error("Unable to load behavioral learning: %s", err)
            return
        try:
            stored_biases = _bounded_offsets(
                data.get("position_biases", {}), POSITION_BIAS_LIMIT
            )
            stored_offsets = _bounded_offsets(
                data.get("temperature_offsets", {}), TEMPERATURE_OFFSET_LIMIT
            )
            stored_counts = {
                str(key): int(value)
                for key, value in data.get("override_counts", {}).items()
            }
            guard_version = int(data.get("learning_guard_version", 0))
            guard_upgrade = guard_version < LEARNING_GUARD_VERSION
            if guard_upgrade:
                self.position_biases = {}
                self.temperature_offsets = {}
                self.override_counts = {}
                if stored_biases or stored_offsets or stored_counts:
                    self.last_guard_reset_at = datetime.now(UTC)
                    self.guard_reset_reason = LEARNING_GUARD_RESET_REASON
                    self.logger.warning(
                        "Resetting behavioral learning affected by legacy movement "
                        "or invalid temperature-source detection"
                    )
            else:
                self.position_biases = stored_biases
                self.temperature_offsets = stored_offsets
                self.override_counts = stored_counts
                self.guard_reset_reason = data.get("last_guard_reset_reason")
                stored_reset = data.get("last_guard_reset_at")
                self.last_guard_reset_at = (
                    datetime.fromisoformat(stored_reset) if stored_reset else None
                )
                if self.last_guard_reset_at and self.last_guard_reset_at.tzinfo is None:
                    self.last_guard_reset_at = self.last_guard_reset_at.replace(
                        tzinfo=UTC
                    )
            stored_sun = data.get("last_direct_sun_at")
            self.last_direct_sun_at = (
                datetime.fromisoformat(stored_sun) if stored_sun else None
            )
            if self.last_direct_sun_at and self.last_direct_sun_at.tzinfo is None:
                self.last_direct_sun_at = self.last_direct_sun_at.replace(tzinfo=UTC)
            self._last_direct_sun_saved_at = self.last_direct_sun_at
            self.loaded = True
            self.last_load_at = datetime.now(UTC)
            self.last_load_error = None
            if guard_upgrade:
                try:
                    await self._store.async_save(self._storage_payload())
                except (HomeAssistantError, OSError) as err:
                    self.last_load_error = str(err)
                    self.logger.error(
                        "Unable to persist behavioral learning guard upgrade: %s",
                        err,
                    )
        except (AttributeError, TypeError, ValueError) as err:
            self.last_load_error = str(err)
            self.logger.error("Invalid behavioral learning storage; using defaults")
            self.position_biases.clear()
            self.temperature_offsets.clear()
            self.override_counts.clear()
            self.last_direct_sun_at = None
            self.last_guard_reset_at = None
            self._last_direct_sun_saved_at = None

    def remember_direct_sun(self, timestamp: datetime, *, force: bool = False) -> None:
        """Persist recent direct-sun activity with bounded write frequency."""
        if timestamp.tzinfo is None:
            raise ValueError("Direct-sun timestamp must be timezone-aware")
        self.last_direct_sun_at = timestamp
        if (
            not force
            and self._last_direct_sun_saved_at is not None
            and timestamp - self._last_direct_sun_saved_at < timedelta(minutes=15)
        ):
            return
        self._last_direct_sun_saved_at = timestamp
        self._schedule_save()

    def register_override(
        self,
        entity_id: str,
        current_temp: float | None,
        our_state: int,
        new_position: int,
        is_summer: bool,
    ) -> None:
        """Update learned offsets after a verified manual position change."""
        position_delta = float(new_position) - float(our_state)
        if abs(position_delta) < 2:
            return

        old_bias = self.position_biases.get(entity_id, 0.0)
        # our_state zawiera już dotychczasowy bias; uczymy pozostały błąd.
        learned_bias = old_bias + self.alpha * position_delta
        self.position_biases[entity_id] = max(
            -POSITION_BIAS_LIMIT,
            min(POSITION_BIAS_LIMIT, learned_bias),
        )
        self.override_counts[entity_id] = self.override_counts.get(entity_id, 0) + 1
        self.last_override = {
            "timestamp": datetime.now(UTC),
            "entity_id": entity_id,
            "calculated_position": our_state,
            "manual_position": new_position,
            "position_delta": position_delta,
            "temperature": current_temp,
            "is_summer": is_summer,
        }

        if current_temp is not None:
            old_offset = self.temperature_offsets.get(entity_id, 0.0)
            direction = -0.1 if new_position < our_state else 0.1
            if not is_summer and new_position > our_state:
                direction = 0.05
            self.temperature_offsets[entity_id] = max(
                -TEMPERATURE_OFFSET_LIMIT,
                min(TEMPERATURE_OFFSET_LIMIT, old_offset + direction),
            )

        self.logger.info(
            "Learned preference for %s: position bias %.1f%%, temperature offset %.1f°C",
            entity_id,
            self.position_biases[entity_id],
            self.temperature_offsets.get(entity_id, 0.0),
        )
        self._schedule_save()

    def get_adjusted_position(self, entity_id: str, target: int) -> int:
        """Apply the learned position bias and clamp the result."""
        bias = self.position_biases.get(entity_id, 0.0)
        return max(0, min(100, round(float(target) + bias)))

    def get_temp_offset(self, entity_id: str) -> float:
        """Return the learned comfort-temperature offset."""
        return self.temperature_offsets.get(entity_id, 0.0)

    def reset(self, entity_id: str | None = None) -> None:
        """Reset learned values for one cover or the whole config entry."""
        if entity_id is None:
            self.position_biases.clear()
            self.temperature_offsets.clear()
            self.override_counts.clear()
        else:
            self.position_biases.pop(entity_id, None)
            self.temperature_offsets.pop(entity_id, None)
            self.override_counts.pop(entity_id, None)
        self._schedule_save()

    def _storage_payload(self) -> dict[str, Any]:
        """Return only values which must survive a restart."""
        return {
            "learning_guard_version": LEARNING_GUARD_VERSION,
            "position_biases": dict(self.position_biases),
            "temperature_offsets": dict(self.temperature_offsets),
            "override_counts": dict(self.override_counts),
            "last_direct_sun_at": (
                self.last_direct_sun_at.isoformat()
                if self.last_direct_sun_at is not None
                else None
            ),
            "last_guard_reset_at": (
                self.last_guard_reset_at.isoformat()
                if self.last_guard_reset_at is not None
                else None
            ),
            "last_guard_reset_reason": self.guard_reset_reason,
        }

    def diagnostics(self) -> dict[str, Any]:
        """Return JSON-safe learning diagnostics."""
        return self._storage_payload() | {
            "storage_loaded": self.loaded,
            "last_load_at": self.last_load_at,
            "last_load_error": self.last_load_error,
            "last_override": self.last_override,
            "last_save_scheduled_at": self.last_save_scheduled_at,
            "guard_reset_reason": self.guard_reset_reason,
        }

    def _schedule_save(self) -> None:
        """Coalesce frequent overrides into one storage write."""
        self.last_save_scheduled_at = datetime.now(UTC)
        self._store.async_delay_save(self._storage_payload, 1)
