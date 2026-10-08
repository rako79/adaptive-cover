"""Modele danych używane przez warstwę runtime Adaptive Cover."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class RefreshTrigger(StrEnum):
    """Źródło żądania ponownego przeliczenia i wykonania decyzji."""

    ENTITY_STATE = "entity_state"
    COVER_STATE = "cover_state"
    PERIODIC = "periodic"
    FIRST_REFRESH = "first_refresh"
    TIMED_END = "timed_end"
    NIGHT_PURGE_DEADLINE = "night_purge_deadline"


@dataclass(slots=True)
class PendingRefreshes:
    """Przechowuj zdarzenia, które nie mogą zginąć podczas trwającego await."""

    _triggers: set[RefreshTrigger] = field(default_factory=set)
    generation: int = 0

    def add(self, trigger: RefreshTrigger) -> int:
        """Dodaj przyczynę i zwróć jej rosnącą generację."""
        self.generation += 1
        self._triggers.add(trigger)
        return self.generation

    def drain(self) -> tuple[int, frozenset[RefreshTrigger]]:
        """Pobierz bieżącą partię, pozostawiając miejsce na nowsze zdarzenia."""
        generation = self.generation
        triggers = frozenset(self._triggers)
        self._triggers.clear()
        return generation, triggers

    def restore(self, triggers: frozenset[RefreshTrigger]) -> None:
        """Przywróć partię, której nie można było bezpiecznie wykonać."""
        self._triggers.update(triggers)

    def contains(self, trigger: RefreshTrigger) -> bool:
        """Sprawdź, czy wskazana przyczyna oczekuje na wykonanie."""
        return trigger in self._triggers

    def discard(self, trigger: RefreshTrigger) -> None:
        """Usuń wskazaną przyczynę bez zmiany pozostałych zdarzeń."""
        self._triggers.discard(trigger)

    @property
    def values(self) -> frozenset[RefreshTrigger]:
        """Zwróć niemutowalny snapshot oczekujących przyczyn."""
        return frozenset(self._triggers)


@dataclass(slots=True)
class StateChangedData:
    """Opis jednej zmiany stanu rolety bez zależności od pakietu HA."""

    entity_id: str
    old_state: Any | None
    new_state: Any | None


@dataclass(slots=True)
class AdaptiveCoverData:
    """Dane publikowane przez koordynator do encji integracji."""

    climate_mode_toggle: bool
    states: dict[str, Any]
    attributes: dict[str, Any]


@dataclass(frozen=True, slots=True)
class CoverTarget:
    """Finalny cel jednej rolety wraz z decyzją, która go utworzyła."""

    entity_id: str
    position: int
    decision_code: str
    decision_generation: int


class MovementOutcome(StrEnum):
    """Końcowa kategoria przyjęcia polecenia ruchu."""

    EXECUTED = "executed"
    SKIPPED = "skipped"
    BLOCKED = "blocked"
    DRY_RUN = "dry_run"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class MovementResult:
    """Jawny wynik przejścia przez bramkę wykonawczą."""

    entity_id: str
    target_position: int
    outcome: MovementOutcome
    reason: str
    generation: int | None = None

    def __bool__(self) -> bool:
        """Pozwól zachować zgodność z dotychczasowym wynikiem logicznym."""
        return self.outcome in {
            MovementOutcome.EXECUTED,
            MovementOutcome.DRY_RUN,
        } or (
            self.outcome is MovementOutcome.SKIPPED
            and self.reason == "target_within_tolerance"
        )
