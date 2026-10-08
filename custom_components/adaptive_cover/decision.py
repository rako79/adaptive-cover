"""Pure decision helpers shared by the Adaptive Cover runtime and tests."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, time, timedelta
from math import isfinite
from typing import Any

COLD_PROTECTION_HYSTERESIS = 1.0


@dataclass(frozen=True, slots=True)
class DecisionResult:
    """Describe one complete, explainable Adaptive Cover decision."""

    target_position: int
    code: str
    reason: str
    priority: int
    inputs: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-safe representation for diagnostics."""
        return asdict(self)


class DecisionArbiter:
    """Wybieraj decyzję wyłącznie na podstawie jawnych priorytetów."""

    @staticmethod
    def select(candidates: list[DecisionResult]) -> DecisionResult:
        """Zwróć pierwszego kandydata o najwyższym priorytecie."""
        if not candidates:
            raise ValueError("At least one decision candidate is required")
        return max(candidates, key=lambda candidate: candidate.priority)

    @staticmethod
    def build_trace(
        evaluations: list[dict[str, Any]],
        selected: DecisionResult,
        constraint: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Zbuduj ślad zgodny z faktycznym wynikiem arbitra."""
        trace = []
        selected_marked = False
        for evaluation in evaluations:
            item = dict(evaluation)
            is_selected = (
                not selected_marked
                and item.get("active")
                and item.get("code") == selected.code
            )
            item["selected"] = is_selected
            if is_selected:
                selected_marked = True
                item["outcome"] = "selected"
            elif item.get("active"):
                item["outcome"] = "overridden_by_higher_priority"
            else:
                item["outcome"] = "inactive"
            trace.append(item)
        if constraint is not None:
            trace.append(
                {
                    **constraint,
                    "active": True,
                    "selected": False,
                    "outcome": "applied_constraint",
                }
            )
        return trace

    @staticmethod
    def constrain_position(
        decision: DecisionResult,
        *,
        minimum: int | None,
        maximum: int | None,
        apply_minimum: bool,
        apply_maximum: bool,
    ) -> tuple[DecisionResult, dict[str, Any] | None]:
        """Ogranicz pozycję po wyborze reguły, bez zmiany jej priorytetu."""
        target = decision.target_position
        constraint = None
        if apply_maximum and maximum is not None and target > maximum:
            target = int(maximum)
            constraint = {
                "code": "max_limit",
                "priority": decision_priority("max_limit"),
                "limit": int(maximum),
                "unconstrained_target": decision.target_position,
            }
        if apply_minimum and minimum is not None and target < minimum:
            target = int(minimum)
            constraint = {
                "code": "min_limit",
                "priority": decision_priority("min_limit"),
                "limit": int(minimum),
                "unconstrained_target": decision.target_position,
            }
        if constraint is None:
            return decision, None
        return (
            DecisionResult(
                target_position=target,
                code=decision.code,
                reason=f"{decision.reason} Zastosowano limit pozycji {target}%.",
                priority=decision.priority,
                inputs=dict(decision.inputs) | {"position_constraint": constraint},
            ),
            constraint,
        )


DECISION_PRIORITIES = {
    "control_disabled": 110,
    "window_open": 105,
    "rain_detected": 100,
    "wind_detected": 100,
    "max_limit": 98,
    "min_limit": 98,
    "cold_protection": 95,
    "dawn_protection": 90,
    "strict_sun_block": 85,
    "night_purge": 80,
    "night_purge_end": 70,
    "timed_end": 70,
    "thermal_hold": 60,
    "night_mode": 50,
    "sun_shadow": 40,
    "auto": 10,
}

LEARNABLE_DECISION_CODES = frozenset({"auto", "thermal_hold", "sun_shadow"})
SCHEDULE_EXEMPT_DECISION_CODES = frozenset(
    {
        "rain_detected",
        "wind_detected",
        "cold_protection",
        "dawn_protection",
        "strict_sun_block",
    }
)
EMERGENCY_DECISION_CODES = frozenset({"rain_detected", "wind_detected"})


def decision_priority(code: str) -> int:
    """Return a stable priority for a decision code."""
    return DECISION_PRIORITIES.get(code, 0)


def behavioral_learning_allowed(
    decision_code: str,
    *,
    adaptive_movement_allowed: bool,
) -> bool:
    """Zezwól na naukę tylko podczas aktywnej automatyki komfortowej."""
    return bool(adaptive_movement_allowed and decision_code in LEARNABLE_DECISION_CODES)


def apply_runtime_policies(
    decision: DecisionResult,
    *,
    control_enabled: bool,
    window_open: bool,
    window_action: str,
    window_position: int,
) -> tuple[DecisionResult, list[dict[str, Any]]]:
    """Dodaj nadrzędne polityki runtime do tego samego arbitra."""
    candidates = [decision]
    evaluations = [
        {
            "code": decision.code,
            "priority": decision.priority,
            "active": True,
        }
    ]
    if not control_enabled:
        candidates.append(
            DecisionResult(
                decision.target_position,
                "control_disabled",
                "Automatyka jest wyłączona; cel nie zostanie wykonany.",
                decision_priority("control_disabled"),
                dict(decision.inputs),
            )
        )
    evaluations.append(
        {
            "code": "control_disabled",
            "priority": decision_priority("control_disabled"),
            "active": not control_enabled,
        }
    )
    if window_open:
        target = (
            int(window_position)
            if window_action == "move_to_position"
            else decision.target_position
        )
        candidates.append(
            DecisionResult(
                target,
                "window_open",
                f"Okno otwarte; aktywna polityka {window_action}.",
                decision_priority("window_open"),
                dict(decision.inputs) | {"window_action": window_action},
            )
        )
    evaluations.append(
        {
            "code": "window_open",
            "priority": decision_priority("window_open"),
            "active": window_open,
            "window_action": window_action,
        }
    )
    selected = DecisionArbiter.select(candidates)
    return selected, DecisionArbiter.build_trace(evaluations, selected)


def inverse_state(state: int) -> int:
    """Odwróć pozycję dla napędów niezgodnych z semantyką Home Assistant."""
    return 100 - state


def position_requires_move(
    current_position: int | float,
    target_position: int | float,
    minimum_change: int | float,
) -> bool:
    """Return whether the configured position difference requires movement."""
    threshold = max(0.0, float(minimum_change))
    difference = abs(float(current_position) - float(target_position))
    if difference == 0:
        return False
    return threshold == 0 or difference >= threshold


def numeric_value_above_threshold(
    value: Any,
    threshold: int | float | None,
) -> bool:
    """Return a strong-signal result only for a valid numeric sensor reading."""
    if value is None or threshold is None:
        return False
    try:
        numeric = float(value)
        return isfinite(numeric) and numeric > float(threshold)
    except (TypeError, ValueError):
        return False


def resolve_cold_protection(
    *,
    outside_temperature: float | None,
    threshold: float,
    night_active: bool,
    previous_active: bool,
    hysteresis: float = COLD_PROTECTION_HYSTERESIS,
) -> bool:
    """Utrzymaj ochronę przed chłodem do przekroczenia progu zwolnienia."""
    if outside_temperature is None or not night_active:
        return False
    activation_threshold = float(threshold)
    release_threshold = activation_threshold + max(0.0, float(hysteresis))
    effective_threshold = release_threshold if previous_active else activation_threshold
    return float(outside_temperature) < effective_threshold


def is_night_purge_window_active(
    now_local: datetime,
    sunset_local: datetime,
    purge_end: time,
) -> bool:
    """Return whether now belongs to the sunset-to-deadline purge window."""
    if now_local.tzinfo is not None and sunset_local.tzinfo is not None:
        sunset_local = sunset_local.astimezone(now_local.tzinfo)
    sunset_today = datetime.combine(
        now_local.date(),
        sunset_local.timetz().replace(tzinfo=None),
        tzinfo=now_local.tzinfo,
    )
    end_today = datetime.combine(
        now_local.date(),
        purge_end,
        tzinfo=now_local.tzinfo,
    )
    if now_local < sunset_today:
        # Poranny fragment należy do nocy rozpoczętej poprzedniego dnia.
        return purge_end < time(12) and now_local < end_today

    if purge_end > sunset_today.time():
        end_date = now_local.date()
    elif purge_end < time(12):
        end_date = now_local.date() + timedelta(days=1)
    else:
        # Niejednoznaczna godzina dzienna wcześniejsza od zachodu nie tworzy
        # całodziennego okna przewietrzania.
        return False
    return now_local < datetime.combine(
        end_date,
        purge_end,
        tzinfo=now_local.tzinfo,
    )


def should_hold_thermal_protection(
    *,
    now: datetime,
    last_direct_sun_at: datetime | None,
    duration_minutes: float,
    direct_sun_valid: bool,
    inside_temperature: float | None,
    outside_temperature: float | None,
    release_delta: float,
    thermal_stress: float,
) -> bool:
    """Return whether post-sun thermal shading should remain active."""
    if direct_sun_valid or last_direct_sun_at is None or inside_temperature is None:
        return False
    if now.tzinfo is None or last_direct_sun_at.tzinfo is None:
        raise ValueError("Thermal hold timestamps must be timezone-aware")
    if now - last_direct_sun_at > timedelta(minutes=float(duration_minutes)):
        return False
    if (
        outside_temperature is not None
        and outside_temperature <= inside_temperature - float(release_delta)
    ):
        return False
    return thermal_stress > 0.0


def wind_speed_to_kmh(value: float, unit: str | None) -> float:
    """Normalize common Home Assistant wind-speed units to km/h."""
    normalized_unit = (unit or "km/h").lower().replace(" ", "")
    if normalized_unit in {"m/s", "mps"}:
        return value * 3.6
    if normalized_unit in {"mph", "mi/h"}:
        return value * 1.609344
    if normalized_unit in {"kn", "kt", "knot", "knots"}:
        return value * 1.852
    return value
