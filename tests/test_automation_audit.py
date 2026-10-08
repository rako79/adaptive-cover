"""Regresje wykonawcze i wielogodzinne scenariusze audytu z września 2026."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from freezegun import freeze_time
import pytest

from custom_components.adaptive_cover import _json_safe
from custom_components.adaptive_cover.coordinator_data import CoordinatorDataMixin
from custom_components.adaptive_cover.coordinator_events import CoordinatorEventsMixin
from custom_components.adaptive_cover.coordinator_execution import (
    CoordinatorExecutionMixin,
)
from custom_components.adaptive_cover.coordinator_pipeline import (
    CoordinatorPipelineMixin,
    UpdateCycle,
)
from custom_components.adaptive_cover.decision import (
    DecisionResult,
    position_requires_move,
)
from custom_components.adaptive_cover.manual_control import AdaptiveCoverManager
from custom_components.adaptive_cover.models import PendingRefreshes, RefreshTrigger
from custom_components.adaptive_cover.movement import CoverMovementExecutor
from fakes import FakeState, FakeStateChange
from test_climate_runtime import FakeCover, climate, climate_data
from test_movement_runtime import FakeContext


class AuditCoordinator(
    CoordinatorExecutionMixin,
    CoordinatorEventsMixin,
    CoordinatorPipelineMixin,
    FakeContext,
):
    """Uruchamiaj rzeczywiste bramki i wykonawcę z symulowanym napędem."""

    def __init__(self):
        """Ustaw konfigurację odpowiadającą eksportowi z 21 września."""
        super().__init__()
        self.entities = ["cover.room"]
        self.manager = AdaptiveCoverManager({"minutes": 30}, Mock(), Mock())
        self.manager.add_covers(self.entities)
        self.movement = CoverMovementExecutor(self)
        self.learner = SimpleNamespace(
            get_adjusted_position=lambda entity, target: target
        )
        self.normal_cover_state = SimpleNamespace(cover=FakeCover())
        self._runtime_initialized = True
        self._diagnostic_refresh = False
        self._pending_refreshes = PendingRefreshes()
        self._pending_cover_events = []
        self._active_refresh_generation = 0
        self._active_refresh_triggers = frozenset({RefreshTrigger.ENTITY_STATE})
        self.adaptive_movement_allowed = True
        self.min_change = 10
        self.time_threshold = 10
        self.global_cooldown = 5
        self.last_decision = DecisionResult(100, "sun_shadow", "Poza słońcem", 40)
        self.last_decision_trace = []
        self.current_position = 0

    check_time_delta = CoordinatorDataMixin.check_time_delta
    _create_background_task = FakeContext._create_background_task

    def check_position_delta(self, entity, target, options):
        """Oceń rzeczywistą różnicę pozycji symulowanego napędu."""
        return position_requires_move(self.current_position, target, self.min_change)


async def test_concurrent_identical_commands_are_coalesced():
    """Seria zdarzeń awaryjnych podczas zamykania wysyła jeden rozkaz."""
    context = FakeContext()
    context.decision_code = "wind_detected"
    executor = CoverMovementExecutor(context)
    try:
        await asyncio.gather(
            *(executor.async_set_position("cover.room", 0) for _ in range(12))
        )
        assert len(context.hass.services.calls) == 1
        assert len(context.manager.moves) == 1
    finally:
        executor.cancel()


async def test_confirmed_motor_event_finishes_verification_immediately():
    """Potwierdzenie celu usuwa zadanie bez czekania na cooldown."""
    context = FakeContext()
    executor = CoverMovementExecutor(context)
    await executor.async_set_position("cover.room", 0)
    assert executor.observe_position_event(
        "cover.room", position=0, movement_state="closed", tolerance=1
    )
    await asyncio.sleep(0)
    assert not executor.is_waiting("cover.room")
    assert not executor.verify_tasks
    assert (
        executor.verify_task_metadata["cover.room"]["outcome"]
        == "target_verified_by_event"
    )


async def test_changed_target_cancels_old_retry_even_while_cooldown_blocks():
    """Nowe 100% unieważnia stare 0%, ale nadal respektuje limit ruchów."""
    context = AuditCoordinator()
    context.current_position = 100
    context.last_decision = DecisionResult(0, "wind_detected", "Wiatr", 100)
    await context.movement.async_set_position("cover.room", 0)
    context.current_position = 0
    context.last_decision = DecisionResult(100, "sun_shadow", "Poza słońcem", 40)
    context.movement.reconcile("cover.room", 100)
    await context.async_handle_call_service("cover.room", 100, {})
    await asyncio.sleep(0)
    assert not context.movement.verify_tasks
    assert len(context.hass.services.calls) == 1
    assert context.manager.status_reason["cover.room"] == "time_delta_not_passed"


def test_cooling_release_bypasses_only_generic_pacing_limits():
    """Chłodne powietrze odwraca domknięcie bez znoszenia limitów ruchów."""
    context = AuditCoordinator()
    context.current_position = 0
    context.last_decision = DecisionResult(100, "auto", "Otwarcie", 10)
    context.last_climate_data = SimpleNamespace(
        inside_temperature=21.57,
        outside_temperature=12.0,
        thermal_hold_release_delta=1.0,
    )
    context.manager.record_move(
        "cover.room",
        "set_cover_position",
        {"position": 0},
        command_context={"decision": {"code": "auto"}},
    )

    assert context.movement_block_reason("cover.room", 100, {}) is None

    context.manager.movement_history["cover.room"] = [datetime.now(UTC)] * 8
    assert (
        context.movement_block_reason("cover.room", 100, {})
        == "hourly_move_limit"
    )


async def test_periodic_cycle_reopens_after_limit_without_sensor_event():
    """Po dziesięciu minutach nowa decyzja zostaje wykonana bez zdarzenia pogody."""
    context = AuditCoordinator()
    with freeze_time("2026-09-21T14:42:06Z", real_asyncio=True) as clock:
        context.manager.record_move("cover.room", "set_cover_position", {"position": 0})
        await context.async_handle_call_service("cover.room", 100, {})
        assert not context.hass.services.calls
        clock.tick(timedelta(minutes=10, seconds=1))
        _, triggers, events = context._drain_execution_events()
        assert triggers == {RefreshTrigger.PERIODIC}
        cycle = UpdateCycle({}, context.normal_cover_state.cover, triggers, events, 100)
        await context._execute_pending_events(cycle)
        assert context.hass.services.calls[0][2]["position"] == 100
    context.movement.cancel()


async def test_hourly_limit_does_not_silently_disappear_on_periodic_refresh():
    """Odtwórz 11 poleceń Karola: najpierw blokada, potem otwarcie po wygaśnięciu limitu."""
    context = AuditCoordinator()
    with freeze_time("2026-09-21T14:51:00Z", real_asyncio=True) as clock:
        context.manager.movement_history["cover.room"] = [
            datetime.now(UTC) - timedelta(minutes=20)
        ] * 11
        await context.async_handle_call_service("cover.room", 100, {})
        assert context.manager.status_reason["cover.room"] == "hourly_move_limit"
        assert not context.hass.services.calls
        clock.tick(timedelta(minutes=41))
        await context.async_handle_call_service("cover.room", 100, {})
        assert len(context.hass.services.calls) == 1
    context.movement.cancel()


async def test_last_retry_is_verified_before_reporting_failure(monkeypatch):
    """Napęd osiągający cel po ostatnim retry nie może dostać fałszywego błędu."""
    context = FakeContext()
    context.target = 0
    executor = CoverMovementExecutor(context)
    executor.command_generation["cover.room"] = 1
    executor.wait_for_target["cover.room"] = True
    executor.verify_task_metadata["cover.room"] = {"generation": 1}
    waits = 0

    async def verify_delay(*args):
        nonlocal waits
        waits += 1
        if waits == 3:
            context.current_position = 0

    monkeypatch.setattr(executor, "_wait_before_verification", verify_delay)
    await executor.async_verify_and_retry(
        "cover.room", 0, "set_cover_position", {"position": 0}, generation=1
    )
    assert len(context.hass.services.calls) == 2
    assert waits == 3
    assert (
        executor.verify_task_metadata["cover.room"]["outcome"]
        == "target_within_tolerance"
    )


def test_verification_delay_is_independent_of_movement_limits():
    """Ustawienia 10/5 minut nie opóźniają samego odczytu napędu."""
    context = AuditCoordinator()
    assert context.movement._verification_wait_time() == 45


def test_expired_generation_cannot_clear_new_command():
    """Kończące się starsze zadanie nie zmienia stanu nowego ruchu."""
    executor = CoverMovementExecutor(FakeContext())
    executor.command_generation["cover.room"] = 2
    executor.wait_for_target["cover.room"] = True
    executor._finish_verification("cover.room", 1, "target_not_reached")
    assert executor.is_waiting("cover.room")


def test_scheduled_retry_becomes_stale_when_current_decision_changes():
    """Timer nocny nie może ponowić zamknięcia po nadejściu dnia."""
    context = AuditCoordinator()
    context.movement.command_generation["cover.room"] = 1
    assert context.movement.retry_is_stale("cover.room", 0, 1, False)


async def test_command_provenance_is_snapshot_of_sent_decision():
    """Historia zachowuje przyczynę zamknięcia po nowszej decyzji otwarcia."""
    context = AuditCoordinator()
    context.current_position = 100
    context.last_decision = DecisionResult(
        0, "wind_detected", "Wiatr", 100, {"wind_speed": 45}
    )
    context.last_decision_trace = [{"code": "wind_detected", "wind_speed": 45}]
    await context.movement.async_set_position("cover.room", 0)
    context.last_decision_trace[0]["wind_speed"] = 16.6
    snapshot = context.manager.command_history["cover.room"][0]["context"]
    assert snapshot["decision"]["code"] == "wind_detected"
    assert snapshot["decision_trace"][0]["wind_speed"] == 45
    assert snapshot["current_position"] == 100
    assert snapshot["final_target"] == 0
    assert snapshot["kind"] == "initial"
    context.movement.cancel()


def test_repeated_position_does_not_learn_or_extend_manual_override():
    """Powtórzony raport po dwóch minutach nie jest ingerencją użytkownika."""
    context = AuditCoordinator()
    learner = Mock()
    context.manager.learner = learner
    state = FakeState("closed", {"current_position": 0})
    event = FakeStateChange("cover.room", state, state)
    context.manager.handle_state_change(
        event, 100, "cover_blind", True, context.movement, None
    )
    assert not context.manager.is_cover_manual("cover.room")
    learner.register_override.assert_not_called()


@pytest.mark.parametrize("state", ["opening", "closing", "unavailable", "unknown"])
def test_unfinished_or_unavailable_state_does_not_train_learner(state):
    """Ucz tylko na potwierdzonej zmianie pozycji napędu."""
    context = AuditCoordinator()
    event = FakeStateChange(
        "cover.room",
        FakeState("open", {"current_position": 100}),
        FakeState(state, {"current_position": 30}),
    )
    context.manager.handle_state_change(
        event, 100, "cover_blind", True, context.movement, None
    )
    assert not context.manager.is_cover_manual("cover.room")


@pytest.mark.parametrize(("bias", "expected"), [(25, 60), (-25, 40)])
def test_learning_respects_physical_position_limits(bias, expected):
    """Korekta uczenia nie omija limitów zastosowanych przez arbitra."""
    context = AuditCoordinator()
    cover = context.normal_cover_state.cover
    cover.apply_min_position = cover.apply_max_position = True
    cover.min_pos, cover.max_pos = 40, 60
    context.learner.get_adjusted_position = lambda entity, target: target + bias
    assert context._target_for_entity("cover.room", 50) == expected


@pytest.mark.parametrize(
    ("light", "value", "low", "expected"),
    [
        ("irradiance", 370, False, True),
        ("irradiance", 370, True, False),
        ("lux", 1190, False, True),
        ("lux", 1190, True, False),
    ],
)
def test_strict_sun_respects_existing_hysteresis(light, value, low, expected):
    """Sygnał między progami zachowuje poprzedni stan blokady słońca."""
    data = climate_data(
        **{
            "use_irradiance": light == "irradiance",
            "use_lux": light == "lux",
            f"{light}_value": value,
            f"{light}_low_light_state": low,
            f"{light}_entity": "sensor.light",
            "irradiance_threshold_on": 375,
            "irradiance_threshold_off": 275,
        }
    )
    active, _ = climate.ClimateCoverState(FakeCover(), data)._strict_sun(False)
    assert active is expected


def test_all_day_export_conditions_do_not_request_closing():
    """Przez osiem godzin warunków z eksportu trzy rolety mają cel 100%."""
    for minute in range(0, 480, 5):
        now = datetime(2026, 9, 21, 7, tzinfo=UTC) + timedelta(minutes=minute)
        for direct in (False, True, False):
            cover = FakeCover(valid=direct, direct_sun_valid=direct, default=100)
            data = climate_data(
                now=now,
                inside_temperature_value=21.8,
                outside_temperature_value=13.5,
                forecast_temperature=14.4,
                irradiance_value=218,
                irradiance_low_light_state=True,
                presence=False,
                wind_speed_kmh=16.6,
                rain_night_only=True,
                weather_state="rainy",
                direct_sun_valid=direct,
            )
            assert (
                climate.ClimateCoverState(cover, data).get_decision().target_position
                == 100
            )


def test_export_preserves_boolean_types():
    """Eksport ustawień nie zamienia bool na liczby 0.0/1.0."""
    result = _json_safe({"enabled": True, "disabled": False, "position": 0})
    assert result["enabled"] is True
    assert result["disabled"] is False
    assert type(result["position"]) is int


async def test_diagnostic_refresh_never_executes_a_movement():
    """Nawet oczekujący timer podczas eksportu nie uruchamia napędu."""
    context = AuditCoordinator()
    context._diagnostic_refresh = True
    context.async_handle_timed_refresh = AsyncMock()
    cycle = UpdateCycle({}, None, {RefreshTrigger.TIMED_END}, [], 0)
    await context._execute_pending_events(cycle)
    context.async_handle_timed_refresh.assert_not_called()


def test_night_purge_is_stable_over_entire_night_and_closes_at_deadline():
    """Symuluj osiem godzin bez ruchów od szumu temperatury i z terminem 06:00."""
    from zoneinfo import ZoneInfo

    timezone = ZoneInfo("Europe/Warsaw")
    start = datetime(2026, 9, 21, 22, tzinfo=timezone)
    cover = FakeCover(valid=False, sunset_valid=True, direct_sun_valid=False)
    temperature_filter = climate.TemperatureStabilityFilter()
    active = False
    positions = []
    for minute in range(481):
        now = start + timedelta(minutes=minute)
        # Pojedyncze skoki czujnika nie utrzymują się przez wymagane pięć minut.
        raw = 7.1 if minute in {31, 90, 190, 300} else 19.7
        outside = temperature_filter.update(raw, now=now, reference_value=19.7)
        inside = 21.0 if minute == 0 else (20.35 if minute % 2 else 20.45)
        data = climate_data(
            now=now,
            sunrise=now.replace(hour=6, minute=30),
            sunset=now.replace(hour=19, minute=0),
            inside_temperature_value=inside,
            outside_temperature_value=outside,
            temp_low=20,
            night_purge_previous_active=active,
            night_purge_end_time="06:00:00",
            cold_protection_active=False,
            dawn_start_month=5,
            dawn_end_month=8,
            irradiance_value=0,
            irradiance_low_light_state=True,
        )
        calculator = climate.ClimateCoverState(cover, data)
        active = calculator._night_purge_active()
        positions.append(calculator.get_decision().target_position)
    assert set(positions[:-1]) == {15}
    assert positions[-1] == 0
    assert sum(left != right for left, right in zip(positions, positions[1:])) == 1


def test_night_purge_does_not_restart_at_noisy_cooling_boundary():
    """Po ustaniu chłodzenia potrzebna jest różnica 1°C do ponownego otwarcia."""
    active = True
    results = []
    for outside in (20.7, 20.9, 20.7, 20.9, 20.7, 19.8):
        data = climate_data(
            now=datetime(2026, 9, 21, 23, tzinfo=UTC),
            inside_temperature_value=21,
            outside_temperature_value=outside,
            night_purge_previous_active=active,
        )
        active = climate.ClimateCoverState(FakeCover(), data)._night_purge_active()
        results.append(active)
    assert results == [True, False, False, False, False, True]


async def test_overnight_schedule_does_not_close_at_evening_start(monkeypatch):
    """Start o 22:00 i koniec 06:00 oznaczają zamknięcie następnego ranka."""
    from custom_components.adaptive_cover.schedule import ResolvedSchedule, ResolvedTime

    pipeline = CoordinatorPipelineMixin()
    now = datetime(2026, 9, 21, 23, tzinfo=UTC)
    pipeline._end_time = now.replace(hour=6)
    pipeline._track_end_time = True
    pipeline._scheduled_time = None
    pipeline._resolved_schedule = ResolvedSchedule(
        ResolvedTime(now.replace(hour=22), "start"),
        ResolvedTime(pipeline._end_time, "end"),
    )
    pipeline.async_timed_end_time = AsyncMock()
    pipeline._async_cancel_update_listener = Mock()
    cycle = UpdateCycle({}, None, {RefreshTrigger.FIRST_REFRESH}, [], 100)
    with freeze_time(now):
        await pipeline._sync_end_timer(cycle)
    assert RefreshTrigger.TIMED_END not in cycle.triggers
    pipeline.async_timed_end_time.assert_awaited_once_with(
        now.replace(hour=6) + timedelta(days=1)
    )


def test_basic_mode_does_not_inherit_climate_emergency_code():
    """Wyłączony klimat nie może oznaczać zwykłej pozycji jako awaryjnej."""
    pipeline = CoordinatorPipelineMixin()
    pipeline._switch_mode = False
    pipeline._calculated_decision = DecisionResult(0, "wind_detected", "Wiatr", 100)
    cover = FakeCover(valid=False, direct_sun_valid=False, sunset_valid=True)
    cover.sol_azi, cover.sol_elev = 200, -10
    result = pipeline._base_decision(cover, 0)
    assert result.code == "night_mode"
    assert result.target_position == 0
    assert pipeline.last_decision_trace[0]["code"] == "night_mode"


@pytest.mark.parametrize(
    ("action", "target", "current", "expected"),
    [
        ("pause", 0, 100, True),
        ("return_after_close", 0, 100, True),
        ("block_closing_only", 0, 100, True),
        ("block_closing_only", 100, 0, False),
    ],
)
async def test_window_policies_prevent_unintended_closing(
    action, target, current, expected
):
    """Otwarte drzwi zachowują skonfigurowaną ochronę przejścia."""
    context = AuditCoordinator()
    context.is_window_open = True
    context.window_open_action = action
    context.current_position = current
    assert await context.async_handle_window_policy("cover.room", target) is expected
    assert not context.hass.services.calls


async def test_manual_override_resets_before_periodic_execution():
    """Wygaśnięcie ręcznego przejęcia przywraca możliwość ruchu."""
    context = AuditCoordinator()
    now = datetime.now(UTC)
    context.manager.mark_manual_control("cover.room")
    context.manager.manual_control_time["cover.room"] = now - timedelta(minutes=31)
    context.manager.manual_control_until["cover.room"] = now - timedelta(minutes=1)
    await context.manager.reset_if_needed()
    await context.async_handle_call_service("cover.room", 100, {})
    assert len(context.hass.services.calls) == 1
    context.movement.cancel()


async def test_diagnostic_and_automatic_cycles_are_serialized():
    """Eksport czeka na automatykę i nie przejmuje oczekującego terminu zamknięcia."""
    from custom_components.adaptive_cover.coordinator import (
        AdaptiveDataUpdateCoordinator,
    )

    context = AuditCoordinator()
    context._update_lock = asyncio.Lock()
    context.async_set_updated_data = Mock()
    entered, release = asyncio.Event(), asyncio.Event()
    cycles = []

    async def pipeline():
        _, triggers, _ = context._drain_execution_events()
        cycles.append((context._diagnostic_refresh, triggers))
        if not context._diagnostic_refresh:
            entered.set()
            await release.wait()
        return {}

    context.async_run_update_pipeline = pipeline
    context._pending_refreshes.add(RefreshTrigger.ENTITY_STATE)
    automatic = asyncio.create_task(
        AdaptiveDataUpdateCoordinator._async_calculate_update_data(context)
    )
    await entered.wait()
    context._pending_refreshes.add(RefreshTrigger.TIMED_END)
    diagnostic = asyncio.create_task(context.async_diagnostic_refresh())
    await asyncio.sleep(0)
    assert not context._diagnostic_refresh
    release.set()
    await asyncio.gather(automatic, diagnostic)
    assert cycles == [(False, {RefreshTrigger.ENTITY_STATE}), (True, set())]
    assert context._pending_refreshes.contains(RefreshTrigger.TIMED_END)
    assert not context._diagnostic_refresh


async def test_overnight_timer_uses_local_day_across_dst(monkeypatch):
    """Zamknięcie o 06:00 po zmianie czasu nadal wypada o 06:00 lokalnie."""
    from zoneinfo import ZoneInfo
    from homeassistant.util import dt as dt_util
    from custom_components.adaptive_cover.schedule import ResolvedSchedule, ResolvedTime

    timezone = ZoneInfo("Europe/Warsaw")
    now = datetime(2026, 10, 24, 23, tzinfo=timezone)
    end = now.replace(hour=6)
    pipeline = CoordinatorPipelineMixin()
    pipeline._end_time = end.astimezone(UTC)
    pipeline._track_end_time = True
    pipeline._scheduled_time = None
    pipeline._resolved_schedule = ResolvedSchedule(
        ResolvedTime(now.replace(hour=22), "start"), ResolvedTime(end, "end")
    )
    pipeline.async_timed_end_time = AsyncMock()
    cycle = UpdateCycle({}, None, set(), [], 100)
    with monkeypatch.context() as timezone_patch:
        timezone_patch.setattr(dt_util, "DEFAULT_TIME_ZONE", timezone)
        with freeze_time(now):
            await pipeline._sync_end_timer(cycle)
        pipeline.async_timed_end_time.assert_awaited_once_with(
            datetime(2026, 10, 25, 5, tzinfo=UTC)
        )
