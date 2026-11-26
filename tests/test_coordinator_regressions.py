"""Regresje koordynatora sprawdzane przez zachowanie, a nie tekst źródła."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from zoneinfo import ZoneInfo

from freezegun import freeze_time

from custom_components.adaptive_cover.coordinator_data import CoordinatorDataMixin
from custom_components.adaptive_cover.coordinator_events import CoordinatorEventsMixin
from custom_components.adaptive_cover.decision import DecisionResult
from custom_components.adaptive_cover.manual_control import AdaptiveCoverManager
from custom_components.adaptive_cover.models import PendingRefreshes, RefreshTrigger
from custom_components.adaptive_cover.schedule import ScheduleResolver
from custom_components.adaptive_cover.switch import AdaptiveCoverSwitch
from fakes import FakeState
from test_automation_audit import AuditCoordinator


async def test_night_purge_deadline_requests_fresh_decision_without_moving():
    """Timer końca wietrzenia nie wysyła pozycji sam, tylko zleca pełne odświeżenie."""
    owner = SimpleNamespace(
        schedule_controller=Mock(),
        _pending_refreshes=PendingRefreshes(),
        async_refresh=AsyncMock(),
        _schedule_night_purge_close=Mock(),
        movement=Mock(),
    )

    await CoordinatorEventsMixin.async_close_after_night_purge(owner, None)

    assert owner._pending_refreshes.contains(RefreshTrigger.NIGHT_PURGE_DEADLINE)
    owner.async_refresh.assert_awaited_once()
    owner.movement.async_set_position.assert_not_called()


async def test_first_refresh_catches_up_missed_night_purge_deadline():
    """Restart po terminie wietrzenia wykonuje zaległe zamknięcie."""
    coordinator = AuditCoordinator()
    coordinator._night_purge_close_overdue = lambda: True
    coordinator.async_handle_timed_refresh = AsyncMock()

    await coordinator.async_handle_first_refresh(0, {})

    coordinator.async_handle_timed_refresh.assert_awaited_once_with(0, {})


async def test_no_physical_movement_before_runtime_initialization():
    """Zdarzenia z rozruchu HA nie mogą poruszyć rolety."""
    coordinator = AuditCoordinator()
    coordinator._runtime_initialized = False

    await coordinator.async_handle_call_service("cover.room", 100, {})

    assert not coordinator.hass.services.calls
    assert coordinator.manager.status_reason["cover.room"] == "runtime_initializing"


async def test_intermediate_cover_state_is_ignored_before_refresh():
    """Stan „opening” nie uruchamia rozpoznawania ręcznego ruchu."""
    owner = SimpleNamespace(
        logger=Mock(),
        ignore_intermediate_states=True,
        _pending_cover_events=[],
        _pending_refreshes=PendingRefreshes(),
        async_refresh=AsyncMock(),
    )
    event = SimpleNamespace(
        data={
            "entity_id": "cover.room",
            "old_state": FakeState("open", {"current_position": 100}),
            "new_state": FakeState("opening", {"current_position": 60}),
        }
    )

    await CoordinatorEventsMixin.async_check_cover_state_change(owner, event)

    owner.async_refresh.assert_not_awaited()
    assert not owner._pending_cover_events


def test_emergency_decision_bypasses_manual_override_and_limits():
    """Deszcz i wiatr ignorują ręczne przejęcie i cooldown; komfort nie."""
    coordinator = AuditCoordinator()
    coordinator.current_position = 100
    coordinator.manager.mark_manual_control("cover.room")
    coordinator.manager.movement_history["cover.room"] = [datetime.now(UTC)]

    coordinator.last_decision = DecisionResult(0, "rain_detected", "deszcz", 100)
    assert coordinator.movement_block_reason("cover.room", 0, {}) is None

    coordinator.last_decision = DecisionResult(0, "auto", "komfort", 10)
    assert coordinator.movement_block_reason("cover.room", 0, {}) is not None


async def test_manual_override_uses_absolute_deadline():
    """Skrócenie czasu przejęcia nie kończy już trwającego przed terminem."""
    manager = AdaptiveCoverManager({"minutes": 120}, Mock())
    manager.add_covers(["cover.room"])
    with freeze_time("2026-11-26 12:00:00"):
        manager.mark_manual_control("cover.room")
        manager.set_last_updated(
            "cover.room", SimpleNamespace(last_updated=datetime.now(UTC)), True
        )
    manager.reset_duration = timedelta(minutes=30)

    with freeze_time("2026-11-26 13:00:00"):
        await manager.reset_if_needed()
    assert manager.is_cover_manual("cover.room")
    with freeze_time("2026-11-26 14:00:01"):
        await manager.reset_if_needed()
    assert not manager.is_cover_manual("cover.room")


def test_weather_wind_outage_keeps_last_reading():
    """Niedostępna encja pogody nie zamienia wichury na 0 km/h."""
    states = {}
    owner = SimpleNamespace(
        hass=SimpleNamespace(states=SimpleNamespace(get=states.get)),
        _last_weather_wind_kmh=0.0,
    )
    options = {"weather_entity": "weather.home"}
    readings = (
        (FakeState("windy", {"wind_speed": 80, "wind_speed_unit": "km/h"}), 80),
        (FakeState("unavailable", {}), 80),
        (FakeState("sunny", {"wind_speed": 10, "wind_speed_unit": "km/h"}), 10),
    )

    for state, expected in readings:
        states["weather.home"] = state
        assert CoordinatorDataMixin._wind_snapshot(owner, options) == expected


def test_zero_is_valid_interpolation_start():
    """Początek zakresu 0 nie wyłącza interpolacji."""
    data = SimpleNamespace(start_value=0, end_value=50, normal_list=None, new_list=None)

    assert CoordinatorDataMixin.interpolate_states(data, 50) == 25


def test_start_time_without_workday_entity_uses_universal_option():
    """Bez encji Workday obowiązuje zwykły start; niedostępna encja daje fallback."""
    zone = ZoneInfo("Europe/Warsaw")
    resolver = ScheduleResolver(zone)
    now = datetime(2026, 11, 26, 5, tzinfo=zone)
    common = {
        "local_now": now,
        "start_entity_configured": False,
        "start_entity_value": None,
        "explicit_start_time": "08:00:00",
        "workday_start_time": "07:00:00",
        "weekend_start_time": "09:00:00",
    }

    universal = resolver.resolve_start(
        workday_configured=False, workday_state=None, **common
    )
    unknown = resolver.resolve_start(
        workday_configured=True, workday_state="unavailable", **common
    )

    assert (universal.source, universal.value.hour) == ("start_time", 8)
    assert unknown.source == "workday_start"
    assert unknown.fallback_reason == "workday_unavailable_assumed_on"


async def test_control_switch_moves_covers_through_shared_gate():
    """Włączenie automatyki używa tej samej bramki co zwykły ruch."""
    coordinator = Mock(
        entities=["cover.room"], state=40, _active_options={"x": 1}
    )
    coordinator.async_refresh = AsyncMock()
    coordinator.async_handle_call_service = AsyncMock()
    switch = SimpleNamespace(
        coordinator=coordinator,
        _key="control_toggle",
        schedule_update_ha_state=Mock(),
    )

    await AdaptiveCoverSwitch.async_turn_on(switch)

    coordinator.async_handle_call_service.assert_awaited_once_with(
        "cover.room", 40, {"x": 1}
    )
