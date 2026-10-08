"""Tests for persistent BehavioralLearner calculations."""

from datetime import UTC, datetime, timedelta
import importlib.util
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import Mock


class FakeStore:
    """Minimal Home Assistant Store replacement used by unit tests."""

    def __init__(self, hass, version, key) -> None:
        """Capture storage metadata without file-system access."""
        self.data = None
        self.delayed_payload = None
        self.saved_payload = None

    async def async_load(self):
        """Return the configured in-memory payload."""
        return self.data

    def async_delay_save(self, callback, delay) -> None:
        """Capture the payload that would be persisted by Home Assistant."""
        self.delayed_payload = callback()

    async def async_save(self, payload) -> None:
        """Przechwyć natychmiastowy zapis migracji danych."""
        self.saved_payload = payload


homeassistant = ModuleType("homeassistant")
homeassistant_core = ModuleType("homeassistant.core")
homeassistant_core.HomeAssistant = object
homeassistant_exceptions = ModuleType("homeassistant.exceptions")
homeassistant_exceptions.HomeAssistantError = type(
    "HomeAssistantError", (Exception,), {}
)
homeassistant_helpers = ModuleType("homeassistant.helpers")
homeassistant_storage = ModuleType("homeassistant.helpers.storage")
homeassistant_storage.Store = FakeStore
sys.modules.setdefault("homeassistant", homeassistant)
sys.modules.setdefault("homeassistant.core", homeassistant_core)
sys.modules.setdefault("homeassistant.exceptions", homeassistant_exceptions)
sys.modules.setdefault("homeassistant.helpers", homeassistant_helpers)
sys.modules.setdefault("homeassistant.helpers.storage", homeassistant_storage)

MODULE_PATH = (
    Path(__file__).parents[1] / "custom_components" / "adaptive_cover" / "learning.py"
)
SPEC = importlib.util.spec_from_file_location("adaptive_cover_learning", MODULE_PATH)
learning = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(learning)
learning.Store = FakeStore


class BehavioralLearnerTests(unittest.IsolatedAsyncioTestCase):
    """Verify learning, persistence payloads and reset behavior."""

    async def test_load_restores_persisted_offsets(self) -> None:
        """Restore valid persisted learning values."""
        learner = learning.BehavioralLearner(object(), Mock(), "entry")
        learner._store.data = {
            "learning_guard_version": learning.LEARNING_GUARD_VERSION,
            "position_biases": {"cover.room": 4.5},
            "temperature_offsets": {"cover.room": -0.3},
            "override_counts": {"cover.room": 3},
            "last_direct_sun_at": "2026-07-14T10:15:00+00:00",
        }
        await learner.async_load()
        self.assertEqual(34, learner.get_adjusted_position("cover.room", 30))
        self.assertEqual(-0.3, learner.get_temp_offset("cover.room"))
        self.assertTrue(learner.diagnostics()["storage_loaded"])
        self.assertIsNotNone(learner.diagnostics()["last_load_at"])
        self.assertEqual(
            datetime(2026, 7, 14, 10, 15, tzinfo=UTC),
            learner.last_direct_sun_at,
        )

    async def test_legacy_learning_is_reset_but_direct_sun_is_retained(self) -> None:
        """Usuń korekty skażone dawnym wykrywaniem własnych ruchów."""
        learner = learning.BehavioralLearner(object(), Mock(), "entry")
        learner._store.data = {
            "learning_guard_version": 3,
            "position_biases": {"cover.room": -19.0},
            "temperature_offsets": {"cover.room": -3.0},
            "override_counts": {"cover.room": 196},
            "last_direct_sun_at": "2026-07-29T11:43:56+00:00",
        }

        await learner.async_load()

        self.assertEqual(50, learner.get_adjusted_position("cover.room", 50))
        self.assertEqual(0.0, learner.get_temp_offset("cover.room"))
        self.assertEqual(
            learning.LEARNING_GUARD_RESET_REASON,
            learner.diagnostics()["guard_reset_reason"],
        )
        self.assertEqual(
            learning.LEARNING_GUARD_VERSION,
            learner._store.saved_payload["learning_guard_version"],
        )
        self.assertEqual({}, learner._store.saved_payload["position_biases"])
        self.assertEqual(
            "2026-07-29T11:43:56+00:00",
            learner._store.saved_payload["last_direct_sun_at"],
        )

    async def test_override_updates_and_schedules_persistence(self) -> None:
        """Learn bounded position and temperature preferences."""
        learner = learning.BehavioralLearner(object(), Mock(), "entry")
        learner.register_override("cover.room", 23.0, 50, 30, True)
        self.assertEqual(48, learner.get_adjusted_position("cover.room", 50))
        self.assertEqual(-0.1, learner.get_temp_offset("cover.room"))
        self.assertEqual(
            1, learner._store.delayed_payload["override_counts"]["cover.room"]
        )
        self.assertEqual(
            30,
            learner.diagnostics()["last_override"]["manual_position"],
        )
        self.assertIsNotNone(learner.diagnostics()["last_save_scheduled_at"])

    async def test_reset_clears_all_learning(self) -> None:
        """Clear learned offsets and persist the empty state."""
        learner = learning.BehavioralLearner(object(), Mock(), "entry")
        learner.register_override("cover.room", 23.0, 50, 30, True)
        learner.reset()
        self.assertEqual(50, learner.get_adjusted_position("cover.room", 50))
        self.assertEqual({}, learner._store.delayed_payload["position_biases"])

    async def test_learning_corrects_remaining_error_without_halving_preference(
        self,
    ) -> None:
        """Kolejne korekty do 60% z bazy 50% zbiegają do biasu 10%, nie 5%."""
        learner = learning.BehavioralLearner(object(), Mock(), "entry")
        for _ in range(40):
            target = learner.get_adjusted_position("cover.room", 50)
            learner.register_override("cover.room", 23, target, 60, False)
        self.assertGreaterEqual(learner.get_adjusted_position("cover.room", 50), 59)

    async def test_invalid_stored_bias_does_not_break_position_calculation(
        self,
    ) -> None:
        """Uszkodzone dane uczenia są zgłaszane i nie trafiają do obliczeń pozycji."""
        learner = learning.BehavioralLearner(object(), Mock(), "entry")
        learner._store.data = {
            "learning_guard_version": learning.LEARNING_GUARD_VERSION,
            "position_biases": {"cover.room": float("nan")},
        }
        await learner.async_load()
        self.assertIsNotNone(learner.last_load_error)
        self.assertEqual(100, learner.get_adjusted_position("cover.room", 100))

    async def test_direct_sun_is_persisted_without_excessive_writes(self) -> None:
        """Retain thermal context and throttle repeated storage updates."""
        learner = learning.BehavioralLearner(object(), Mock(), "entry")
        first = datetime(2026, 7, 14, 10, 0, tzinfo=UTC)
        learner.remember_direct_sun(first)
        first_payload = learner._store.delayed_payload
        learner._store.delayed_payload = None
        learner.remember_direct_sun(first + timedelta(minutes=5))
        self.assertIsNone(learner._store.delayed_payload)
        learner.remember_direct_sun(first + timedelta(minutes=5), force=True)
        self.assertIsNotNone(learner._store.delayed_payload)
        self.assertEqual(first.isoformat(), first_payload["last_direct_sun_at"])


if __name__ == "__main__":
    unittest.main()
