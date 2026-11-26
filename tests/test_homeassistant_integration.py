"""Testy pełnego cyklu życia integracji w Home Assistant 2026.7."""

from __future__ import annotations

import asyncio
import datetime as dt
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from homeassistant.core import HomeAssistant, State
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
import pytest
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, mock_restore_cache

from custom_components.adaptive_cover.const import DOMAIN
from custom_components.adaptive_cover.coordinator_data import CoordinatorDataMixin
from custom_components.adaptive_cover.coordinator_pipeline import (
    CoordinatorPipelineMixin,
    UpdateCycle,
)
from custom_components.adaptive_cover.decision import DecisionResult, decision_priority
from custom_components.adaptive_cover.models import RefreshTrigger
from custom_components.adaptive_cover.options import normalize_options


def create_entry(*, version: int = 2, **overrides) -> MockConfigEntry:
    """Utwórz kompletny wpis jednej rolety pionowej."""
    options = normalize_options(
        {
            "group": ["cover.test"],
            "climate_mode": False,
            "control_toggle": False,
            "window_height": 2.1,
            "distance_shaded_area": 0.5,
            **overrides,
        }
    )
    return MockConfigEntry(
        domain=DOMAIN,
        title="Testowa roleta",
        data={"name": "Testowa roleta", "sensor_type": "cover_blind"},
        options=options,
        version=version,
        unique_id="adaptive-cover-test",
    )


def set_required_states(hass: HomeAssistant) -> None:
    """Dodaj stany wymagane przez pierwszy snapshot koordynatora."""
    hass.states.async_set(
        "cover.test",
        "open",
        {"current_position": 60},
    )

    async def move_cover(call):
        """Zasymuluj raport napędu po faktycznym wywołaniu usługi HA."""
        target = call.data["position"]
        hass.states.async_set(
            "cover.test",
            "closed" if target == 0 else "open",
            {"current_position": target},
        )

    hass.services.async_register("cover", "set_cover_position", move_cover)


def create_pipeline(*, decision_code: str = "auto") -> CoordinatorPipelineMixin:
    """Utwórz minimalny pipeline do testowania arbitra terminów."""
    pipeline = CoordinatorPipelineMixin()
    pipeline._inverse_state = False
    pipeline._diagnostic_refresh = False
    pipeline.motor_position = int
    pipeline.last_decision = DecisionResult(
        target_position=82,
        code=decision_code,
        reason=decision_code,
        priority=decision_priority(decision_code),
    )
    pipeline.last_decision_trace = [
        {
            "code": decision_code,
            "active": True,
            "selected": True,
            "outcome": "selected",
        }
    ]
    pipeline._night_purge_close_overdue = lambda: False
    return pipeline


def create_cycle(trigger: RefreshTrigger, *, sunset_position: int = 0) -> UpdateCycle:
    """Utwórz cykl z pozycją komfortową różną od zamknięcia."""
    cover = SimpleNamespace(
        min_pos=0,
        max_pos=100,
        apply_min_position=False,
        apply_max_position=False,
        state_info="auto",
        state_reason="auto",
    )
    return UpdateCycle(
        options={"sunset_position": sunset_position},
        cover=cover,
        triggers={trigger},
        cover_events=[],
        state=82,
    )


@pytest.mark.usefixtures("enable_custom_integrations")
@pytest.mark.parametrize("expected_lingering_timers", [True])
async def test_wind_reports_and_reload_in_local_ha(hass: HomeAssistant, freezer):
    """Zamknij po trzech raportach i nie otwieraj po przeładowaniu przy wichurze."""
    freezer.move_to(dt.datetime(2026, 11, 19, 12, tzinfo=dt.UTC))
    hass.config.latitude = 0.0
    hass.config.longitude = 0.0
    set_required_states(hass)
    wind = "sensor.test_wind"
    unit = {"unit_of_measurement": "km/h"}
    hass.states.async_set(wind, "27.7", unit)
    hass.states.async_set("cover.test", "open", {"current_position": 100})
    entry = create_entry(
        climate_mode=True,
        set_azimuth=0,
        fov_left=30,
        fov_right=30,
        default_percentage=100,
        outside_threshold=20,
        start_time="00:00:00",
        end_time="23:59:00",
        wind_entity=wind,
        wind_confirmation_samples=3,
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.adaptive_cover.coordinator_events.RUNTIME_INITIALIZATION_DELAY", 0
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        coordinator = hass.data[DOMAIN][entry.entry_id]

        # Bez danych słonecznych ma nadal zadziałać ochrona pogodowa.
        hass.states.async_set("sun.sun", "unavailable")
        await hass.async_block_till_done()
        assert hass.states.get("cover.test").attributes["current_position"] == 100
        for count in (1, 2, 3):
            freezer.tick(dt.timedelta(seconds=15))
            hass.states.async_set(wind, "40.3", unit)
            await hass.async_block_till_done()
            await coordinator.async_refresh()
            assert coordinator._wind_confirmation.samples == count
            assert hass.states.get("cover.test").attributes["current_position"] == (
                0 if count == 3 else 100
            )

        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        coordinator = hass.data[DOMAIN][entry.entry_id]
        assert coordinator._wind_confirmation.samples == 0
        assert hass.states.get("cover.test").attributes["current_position"] == 0

        freezer.tick(dt.timedelta(seconds=15))
        hass.states.async_set(wind, "27.7", unit)
        await hass.async_block_till_done()
        await coordinator.async_refresh()
        assert hass.states.get("cover.test").attributes["current_position"] == 100
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.usefixtures("enable_custom_integrations")
@pytest.mark.parametrize("expected_lingering_timers", [True])
async def test_wind_sensor_dropout_keeps_protection_with_default_samples(
    hass: HomeAssistant, freezer
):
    """Utrata wiatromierza w czasie wichury nie otwiera rolety przy ustawieniu 1."""
    freezer.move_to(dt.datetime(2026, 11, 19, 12, tzinfo=dt.UTC))
    set_required_states(hass)
    wind = "sensor.test_wind"
    unit = {"unit_of_measurement": "km/h"}
    hass.states.async_set(wind, "27.7", unit)
    hass.states.async_set("cover.test", "open", {"current_position": 100})
    entry = create_entry(
        climate_mode=True,
        default_percentage=100,
        start_time="00:00:00",
        end_time="23:59:00",
        wind_entity=wind,
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.adaptive_cover.coordinator_events.RUNTIME_INITIALIZATION_DELAY", 0
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        coordinator = hass.data[DOMAIN][entry.entry_id]
        for value, protected in (("45", True), ("unavailable", True), ("20", False)):
            freezer.tick(dt.timedelta(seconds=15))
            hass.states.async_set(wind, value, unit)
            await hass.async_block_till_done()
            await coordinator.async_refresh()
            assert (coordinator.last_decision.code == "wind_detected") is protected, value
            if protected:
                assert hass.states.get("cover.test").attributes["current_position"] == 0

        # Czujnik nie powtarza niezmienionej wartości: po przeładowaniu liczy się bieżący odczyt.
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        assert not hass.data[DOMAIN][entry.entry_id].wind_opening_unconfirmed
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.usefixtures("enable_custom_integrations")
@pytest.mark.parametrize("expected_lingering_timers", [True])
async def test_runtime_starts_after_reload_and_offset_entity_exists(hass: HomeAssistant):
    """Po przeładowaniu automatyka rusza, a suwak offsetu istnieje mimo end_time."""
    set_required_states(hass)
    entry = create_entry(end_time="20:00:00")
    entry.add_to_hass(hass)
    with patch(
        "custom_components.adaptive_cover.coordinator_events.RUNTIME_INITIALIZATION_DELAY", 0
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        assert hass.data[DOMAIN][entry.entry_id]._runtime_initialized
        numbers = [
            item
            for item in er.async_entries_for_config_entry(
                er.async_get(hass), entry.entry_id
            )
            if item.domain == "number"
        ]
        assert len(numbers) == 1
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.usefixtures("enable_custom_integrations")
@pytest.mark.parametrize("expected_lingering_timers", [True])
async def test_restoring_switches_does_not_recalculate(hass: HomeAssistant):
    """Jedno przeliczenie po odtworzeniu wszystkich przełączników, z ich stanem."""
    set_required_states(hass)
    entry = create_entry(climate_mode=True)
    entry.add_to_hass(hass)
    dry_run_id = er.async_get(hass).async_get_or_create(
        "switch", DOMAIN, f"{entry.entry_id}_Dry Run", config_entry=entry
    ).entity_id
    mock_restore_cache(hass, [State(dry_run_id, "on")])
    with patch(
        "custom_components.adaptive_cover.coordinator.AdaptiveDataUpdateCoordinator"
        ".schedule_runtime_initialization"
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        coordinator = hass.data[DOMAIN][entry.entry_id]
        # Pierwsze przeliczenie przed encjami i jedno po odtworzeniu (nie po jednym na przełącznik).
        assert coordinator._update_count == 2
        assert coordinator.data.attributes["dry_run"] is True
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.usefixtures("enable_custom_integrations")
@pytest.mark.parametrize("expected_lingering_timers", [True])
async def test_manual_override_survives_reload(hass: HomeAssistant, freezer):
    """Zmiana opcji z panelu nie kasuje ręcznego przejęcia (np. projekcji)."""
    freezer.move_to(dt.datetime(2026, 11, 19, 12, tzinfo=dt.UTC))
    set_required_states(hass)
    entry = create_entry(start_time="00:00:00", end_time="23:59:00")
    entry.add_to_hass(hass)
    with patch(
        "custom_components.adaptive_cover.coordinator_events.RUNTIME_INITIALIZATION_DELAY", 0
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        manager = hass.data[DOMAIN][entry.entry_id].manager
        until = dt_util.utcnow() + dt.timedelta(hours=2)
        manager.mark_manual_control("cover.test")
        manager.set_last_updated(
            "cover.test", SimpleNamespace(last_updated=dt_util.utcnow()), True, until
        )

        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        manager = hass.data[DOMAIN][entry.entry_id].manager
        assert manager.is_cover_manual("cover.test")
        assert manager.manual_control_until["cover.test"] == until

        manager.reset("cover.test")
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        assert not hass.data[DOMAIN][entry.entry_id].manager.is_cover_manual("cover.test")
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.usefixtures("enable_custom_integrations")
@pytest.mark.parametrize("expected_lingering_timers", [True])
async def test_deferred_close_in_local_ha(hass: HomeAssistant, freezer):
    """Pomiń ruch bez kontaktronu, a po powrocie odczytu dokończ zamknięcie."""
    freezer.move_to(dt.datetime(2026, 11, 19, 11, 55, tzinfo=dt.UTC))
    set_required_states(hass)
    window = "binary_sensor.test_window"
    hass.states.async_set(window, "unavailable")
    entry = create_entry(
        start_time="00:00:00",
        end_time="12:00:00",
        return_sunset=True,
        window_entity=window,
        window_open_action="return_after_close",
        interp=True,
        interp_list=[0, 100],
        interp_list_new=[20, 80],
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.adaptive_cover.coordinator_events.RUNTIME_INITIALIZATION_DELAY", 0
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        coordinator = hass.data[DOMAIN][entry.entry_id]
        assert coordinator.motor_position(100) == 100
        freezer.move_to(dt.datetime(2026, 11, 19, 12, 1, tzinfo=dt.UTC))
        await coordinator.async_timed_refresh(None)
        assert hass.states.get("cover.test").attributes["current_position"] == 60
        assert coordinator._deferred_scheduled_close is not None
        assert coordinator.manager.last_skip_reason["cover.test"] == (
            "window_state_unavailable"
        )

        hass.states.async_set(window, "off")
        await hass.async_block_till_done()
        await coordinator.async_refresh()
        assert hass.states.get("cover.test").attributes["current_position"] == 0
        assert coordinator._deferred_scheduled_close is None
    assert await hass.config_entries.async_unload(entry.entry_id)


def test_night_purge_deadline_uses_explicit_night_position() -> None:
    """Koniec przewietrzania nie może wysłać bieżącej pozycji komfortowej."""
    pipeline = create_pipeline()
    cycle = create_cycle(RefreshTrigger.NIGHT_PURGE_DEADLINE)

    pipeline._apply_scheduled_close_decision(cycle)

    assert cycle.state == 0
    assert pipeline.last_decision.code == "night_purge_end"


@pytest.mark.parametrize(("in_schedule", "kept"), [(True, False), (False, True)])
def test_deferred_night_purge_close_ends_inside_schedule(in_schedule, kept) -> None:
    """Zaległe zamknięcie po wietrzeniu nie blokuje dnia, gdy start był wcześniej."""
    pipeline = create_pipeline()
    pipeline.check_adaptive_time = in_schedule
    pipeline._apply_scheduled_close_decision(
        create_cycle(RefreshTrigger.NIGHT_PURGE_DEADLINE)
    )
    pipeline.last_decision = DecisionResult(
        target_position=82, code="auto", reason="auto", priority=decision_priority("auto")
    )
    cycle = create_cycle(RefreshTrigger.PERIODIC)

    pipeline._apply_scheduled_close_decision(cycle)

    assert (pipeline._deferred_scheduled_close is not None) is kept
    assert (pipeline.last_decision.code == "night_purge_end") is kept


def test_night_purge_deadline_does_not_override_cold_protection() -> None:
    """Termin zamknięcia pozostawia aktywną decyzję bezpieczeństwa."""
    pipeline = create_pipeline(decision_code="cold_protection")
    pipeline.last_decision = DecisionResult(
        target_position=0,
        code="cold_protection",
        reason="cold",
        priority=decision_priority("cold_protection"),
    )
    cycle = create_cycle(RefreshTrigger.NIGHT_PURGE_DEADLINE, sunset_position=40)
    cycle.state = 0

    pipeline._apply_scheduled_close_decision(cycle)

    assert cycle.state == 0
    assert pipeline.last_decision.code == "cold_protection"


def test_startup_after_missed_night_purge_deadline_closes_cover() -> None:
    """Restart przed harmonogramem nadrabia pominięty termin nocny."""
    pipeline = create_pipeline()
    pipeline._night_purge_close_overdue = lambda: True
    cycle = create_cycle(RefreshTrigger.FIRST_REFRESH)

    pipeline._apply_scheduled_close_decision(cycle)

    assert cycle.state == 0
    assert pipeline.last_decision.code == "night_purge_end"


@pytest.mark.usefixtures("enable_custom_integrations")
@pytest.mark.parametrize("expected_lingering_timers", [True])
async def test_setup_reload_and_unload_leave_no_tasks(hass: HomeAssistant) -> None:
    """Uruchom, przeładuj i wyładuj wpis bez osieroconych zadań."""
    set_required_states(hass)
    entry = create_entry()
    entry.add_to_hass(hass)

    with patch(
        "custom_components.adaptive_cover.coordinator_events."
        "RUNTIME_INITIALIZATION_DELAY",
        0,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.entry_id in hass.data[DOMAIN]
        previous = hass.data[DOMAIN][entry.entry_id]
        previous.schedule_controller.schedule(
            "config_change",
            dt.datetime.now(dt.UTC) + dt.timedelta(hours=1),
            AsyncMock(),
        )

        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        coordinator = hass.data[DOMAIN][entry.entry_id]
        assert coordinator.update_interval == dt.timedelta(minutes=1)
        assert coordinator.entities == ["cover.test"]
        assert previous._unloading
        assert previous.schedule_controller.target("config_change") is None

        pending_retry = coordinator._create_background_task(
            asyncio.sleep(3600),
            "adaptive_cover pending retry test",
        )
        coordinator.movement.verify_tasks["cover.test"] = pending_retry
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

    assert coordinator._unloading
    assert pending_retry.cancelled()
    assert not coordinator.movement.verify_tasks
    assert coordinator.schedule_controller.target("end_time") is None
    assert coordinator.schedule_controller.target("night_purge") is None
    assert entry.entry_id not in hass.data[DOMAIN]


@pytest.mark.usefixtures("enable_custom_integrations")
@pytest.mark.parametrize("expected_lingering_timers", [True])
async def test_options_flow_opens_configuration_menu(hass: HomeAssistant) -> None:
    """Otwarcie konfiguracji wpisu zwraca menu zamiast błędu serwera."""
    entry = create_entry()
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "init"
    assert {"automation", "blind"} <= set(result["menu_options"])


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_migration_completes_legacy_options(hass: HomeAssistant) -> None:
    """Migracja starego wpisu zapisuje pełny schemat wersji 2."""
    from custom_components.adaptive_cover import async_migrate_entry  # noqa: PLC0415

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Stary wpis",
        data={"name": "Stary wpis", "sensor_type": "cover_blind"},
        options={"entities": ["cover.test"]},
        version=1,
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry)
    assert entry.version == 2
    assert entry.options == normalize_options(entry.options)


@pytest.mark.usefixtures("enable_custom_integrations")
@pytest.mark.parametrize("expected_lingering_timers", [True])
async def test_settings_and_diagnostics_export_contract(
    hass: HomeAssistant,
) -> None:
    """Oba eksporty zapisują bieżący schemat i ten sam wpis."""
    set_required_states(hass)
    entry = create_entry()
    entry.add_to_hass(hass)

    with patch(
        "custom_components.adaptive_cover.coordinator_events."
        "RUNTIME_INITIALIZATION_DELAY",
        0,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        await hass.services.async_call(
            DOMAIN,
            "export_config",
            {"filename": "settings-test.json", "include_date": False},
            blocking=True,
        )
        await hass.services.async_call(
            DOMAIN,
            "export_diagnostics",
            {
                "filename": "diagnostics-test.json",
                "include_date": False,
                "refresh": False,
            },
            blocking=True,
        )

    settings = json.loads(
        Path(hass.config.path("settings-test.json")).read_text(encoding="utf-8")
    )
    diagnostics = json.loads(
        Path(hass.config.path("diagnostics-test.json")).read_text(encoding="utf-8")
    )
    assert entry.entry_id in settings["entries"]
    assert entry.entry_id in diagnostics["entries"]
    assert (
        settings["integration_version"]
        == diagnostics["environment"]["integration_version"]
    )
    schedule = diagnostics["entries"][entry.entry_id]["runtime"]["schedule"]
    assert "start_time_resolution" in schedule
    assert "end_time_resolution" in schedule
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.usefixtures("enable_custom_integrations")
@pytest.mark.parametrize("expected_lingering_timers", [True])
async def test_new_weather_event_stops_older_two_cover_batch(
    hass: HomeAssistant,
) -> None:
    """Nowsze zdarzenie między roletami zatrzymuje pozostałą część starej partii."""
    set_required_states(hass)
    entry = create_entry()
    entry.add_to_hass(hass)
    with patch(
        "custom_components.adaptive_cover.coordinator_events."
        "RUNTIME_INITIALIZATION_DELAY",
        0,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    coordinator = hass.data[DOMAIN][entry.entry_id]
    coordinator.entities = ["cover.first", "cover.second"]
    coordinator._runtime_initialized = True
    coordinator.control_toggle = True
    coordinator._active_refresh_generation = coordinator._pending_refreshes.generation
    sent = []

    async def set_position(entity: str, state: int):
        sent.append((entity, state))
        coordinator._pending_refreshes.add(RefreshTrigger.ENTITY_STATE)

    with (
        patch.object(
            coordinator,
            "async_handle_window_policy",
            new=AsyncMock(return_value=False),
        ),
        patch.object(coordinator, "movement_block_reason", return_value=None),
        patch.object(coordinator, "async_set_position", new=set_position),
    ):
        await coordinator.async_handle_state_change(40, coordinator._active_options)

    assert sent == [("cover.first", 40)]
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize(
    ("new_list", "expected"),
    [([20, 80], [0, 50, 100]), ([100, 0], [100, 50, 0]), ([80, 20], [100, 50, 0])],
)
def test_interpolation_endpoints_follow_list_direction(new_list, expected) -> None:
    """Krańce zakresu dają pełne zamknięcie/otwarcie także przy odwróconej liście."""
    data = SimpleNamespace(
        start_value=None, end_value=None, normal_list=[0, 100], new_list=new_list
    )
    assert [
        CoordinatorDataMixin.interpolate_states(data, state) for state in (0, 50, 100)
    ] == expected
