"""Geometria słońca i modele typów osłon Adaptive Cover."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from astral.sun import azimuth, elevation
import numpy as np
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from numpy import cos, sin, tan
from numpy import radians as rad

from .config_context_adapter import ConfigContextAdapter
from .sun import SunData

# --- Geometric accuracy constants ---
EDGE_CASE_LOW_ELEVATION = 2.0
EDGE_CASE_HIGH_ELEVATION = 88.0
EDGE_CASE_EXTREME_GAMMA = 85
SAFETY_MARGIN_GAMMA_THRESHOLD = 45
SAFETY_MARGIN_GAMMA_MAX = 0.2
SAFETY_MARGIN_LOW_ELEV_THRESHOLD = 10
SAFETY_MARGIN_LOW_ELEV_MAX = 0.15
SAFETY_MARGIN_HIGH_ELEV_THRESHOLD = 75
SAFETY_MARGIN_HIGH_ELEV_MAX = 0.1
WINDOW_DEPTH_GAMMA_THRESHOLD = 10
MIN_TAN_ELEVATION_CLAMP = 0.05
MIN_COS_GAMMA_CLAMP = 0.01


class SafetyMarginCalculator:
    """Calculate extra geometric safety margins."""

    @staticmethod
    def calculate(gamma: float, sol_elev: float) -> float:
        """Calculate a margin factor for difficult sun angles."""
        margin = 1.0
        gamma_abs = abs(gamma)
        if gamma_abs > SAFETY_MARGIN_GAMMA_THRESHOLD:
            t = (gamma_abs - SAFETY_MARGIN_GAMMA_THRESHOLD) / (
                90 - SAFETY_MARGIN_GAMMA_THRESHOLD
            )
            t = float(np.clip(t, 0, 1))
            smooth_t = t * t * (3 - 2 * t)
            margin += SAFETY_MARGIN_GAMMA_MAX * smooth_t
        if sol_elev < SAFETY_MARGIN_LOW_ELEV_THRESHOLD:
            t = (
                SAFETY_MARGIN_LOW_ELEV_THRESHOLD - sol_elev
            ) / SAFETY_MARGIN_LOW_ELEV_THRESHOLD
            margin += SAFETY_MARGIN_LOW_ELEV_MAX * float(np.clip(t, 0, 1))
        elif sol_elev > SAFETY_MARGIN_HIGH_ELEV_THRESHOLD:
            t = (sol_elev - SAFETY_MARGIN_HIGH_ELEV_THRESHOLD) / (
                90 - SAFETY_MARGIN_HIGH_ELEV_THRESHOLD
            )
            margin += SAFETY_MARGIN_HIGH_ELEV_MAX * float(np.clip(t, 0, 1))
        return float(margin)


class EdgeCaseHandler:
    """Handle extreme sun-position edge cases."""

    @staticmethod
    def check_and_handle(
        sol_elev: float, gamma: float, distance: float, h_win: float
    ) -> tuple[bool, float]:
        """Return whether an edge case applies and its computed position."""
        if sol_elev < EDGE_CASE_LOW_ELEVATION:
            return (True, 0.0)
        if abs(gamma) > EDGE_CASE_EXTREME_GAMMA:
            return (True, h_win)
        if sol_elev > EDGE_CASE_HIGH_ELEVATION:
            simple_height = distance * np.tan(np.radians(sol_elev))
            return (True, float(np.clip(simple_height, 0, h_win)))
        return (False, 0.0)


@dataclass
class AdaptiveGeneralCover(ABC):
    """Collect common data."""

    hass: HomeAssistant
    logger: ConfigContextAdapter
    sol_azi: float | None
    sol_elev: float | None
    sunset_pos: int
    sunset_off: int
    sunrise_off: int
    timezone: str
    fov_left: int
    fov_right: int
    win_azi: int
    h_def: int
    max_pos: int
    min_pos: int
    max_pos_bool: bool
    min_pos_bool: bool
    blind_spot_left: int
    blind_spot_right: int
    blind_spot_elevation: int
    blind_spot_on: bool
    min_elevation: int
    max_elevation: int
    sun_data: SunData = field(init=False)
    snapshot_time: datetime = field(init=False)
    sunrise_at: datetime = field(init=False)
    sunset_at: datetime = field(init=False)

    def __post_init__(self):
        """Utwórz jeden snapshot czasu i danych słonecznych."""
        self.sun_data = SunData(self.timezone, self.hass)
        self.snapshot_time = dt_util.utcnow()
        local_date = dt_util.as_local(self.snapshot_time).date()
        self.sunrise_at = self.sun_data.sunrise(local_date)
        self.sunset_at = self.sun_data.sunset(local_date)

    def solar_times(self):
        """Determine start/end times."""
        sun = self.sun_data
        span = (self.azi_max_abs - self.azi_min_abs) % 360
        in_view = [
            moment
            for moment in sun.times
            if (azimuth(sun.observer, moment) - self.azi_min_abs) % 360 <= span
            and elevation(sun.observer, moment) > 0
        ]
        return (in_view[0], in_view[-1]) if in_view else (None, None)

    @property
    def is_sun_in_blind_spot(self) -> bool:
        """Check if sun is in blind spot."""
        if (
            self.blind_spot_left is not None
            and self.blind_spot_right is not None
            and self.blind_spot_on
        ):
            left_edge = self.fov_left - self.blind_spot_left
            right_edge = self.fov_left - self.blind_spot_right
            blindspot = (self.gamma <= left_edge) & (self.gamma >= right_edge)
            if self.blind_spot_elevation is not None:
                blindspot = blindspot & (self.sol_elev <= self.blind_spot_elevation)
            self.logger.debug("Is sun in blind spot? %s", blindspot)
            return blindspot
        return False

    @property
    def azi_min_abs(self) -> int:
        """Calculate min azimuth."""
        azi_min_abs = (self.win_azi - self.fov_left + 360) % 360
        return azi_min_abs

    @property
    def azi_max_abs(self) -> int:
        """Calculate max azimuth."""
        azi_max_abs = (self.win_azi + self.fov_right + 360) % 360
        return azi_max_abs

    @property
    def gamma(self) -> float:
        """Calculate Gamma."""
        # surface solar azimuth
        gamma = (self.win_azi - self.sol_azi + 180) % 360 - 180
        return gamma

    @property
    def valid_elevation(self) -> bool:
        """Check if elevation is within range."""
        if self.min_elevation is None and self.max_elevation is None:
            return self.sol_elev >= 0
        if self.min_elevation is None:
            return self.sol_elev <= self.max_elevation
        if self.max_elevation is None:
            return self.sol_elev >= self.min_elevation
        within_range = self.min_elevation <= self.sol_elev <= self.max_elevation
        self.logger.debug("elevation within range? %s", within_range)
        return within_range

    @property
    def valid(self) -> bool:
        """Determine if sun is in front of window."""
        if self.sol_azi is None or self.sol_elev is None:
            return False
        # clip azi_min and azi_max to 90
        azi_min = min(self.fov_left, 90)
        azi_max = min(self.fov_right, 90)

        # valid sun positions are those within the blind's azimuth range and above the horizon (FOV)
        valid = (
            (self.gamma < azi_min) & (self.gamma > -azi_max) & (self.valid_elevation)
        )
        self.logger.debug("Sun in front of window (ignoring blindspot)? %s", valid)
        return valid

    @property
    def sunset_valid(self) -> bool:
        """Determine if it is after sunset plus offset."""
        after_sunset = self.snapshot_time > (
            self.sunset_at + timedelta(minutes=self.sunset_off)
        )
        before_sunrise = self.snapshot_time < (
            self.sunrise_at + timedelta(minutes=self.sunrise_off)
        )
        self.logger.debug(
            "After sunset plus offset? %s", (after_sunset or before_sunrise)
        )
        return after_sunset or before_sunrise

    @property
    def default(self) -> float:
        """Change default position at sunset."""
        default = self.h_def
        if self.sunset_valid:
            default = self.sunset_pos
        return default

    @property
    def apply_min_position(self) -> bool:
        """Check if min position is applied."""
        if self.min_pos is not None and self.min_pos != 0:
            if self.min_pos_bool:
                return self.direct_sun_valid
            return True
        return False

    @property
    def apply_max_position(self) -> bool:
        """Check if max position is applied."""
        if self.max_pos is not None and self.max_pos != 100:
            if self.max_pos_bool:
                return self.direct_sun_valid
            return True
        return False

    @property
    def direct_sun_valid(self) -> bool:
        """Check if sun is directly in front of window."""
        return self.valid and not self.sunset_valid and not self.is_sun_in_blind_spot

    @abstractmethod
    def calculate_position(self) -> float:
        """Calculate the position of the blind."""

    @abstractmethod
    def calculate_percentage(self) -> int:
        """Calculate percentage from position."""


@dataclass
class NormalCoverState:
    """Compute state for normal operation."""

    cover: AdaptiveGeneralCover

    def get_state(self) -> int:
        """Return state."""
        self.cover.logger.debug("Determining normal position")
        dsv = self.cover.direct_sun_valid
        self.cover.logger.debug(
            "Sun directly in front of window & before sunset + offset? %s", dsv
        )
        if dsv:
            state = self.cover.calculate_percentage()
            self.cover.logger.debug(
                "Yes sun in window: using calculated percentage (%s)", state
            )
        else:
            state = self.cover.default
            self.cover.logger.debug("No sun in window: using default value (%s)", state)

        result = np.clip(state, 0, 100)
        if not np.isfinite(result):
            self.cover.logger.warning(
                "Non-finite cover result detected; using the configured default"
            )
            result = np.clip(self.cover.default, 0, 100)

        # Ochrona przed zaokrąglaniem w dół do 0 gdy słońce w oknie
        if dsv:
            result = max(result, 1)

        return result


@dataclass
class AdaptiveVerticalCover(AdaptiveGeneralCover):
    """Calculate state for Vertical blinds."""

    distance: float
    h_win: float
    window_depth: float
    sill_height: float

    def calculate_position(self) -> float:
        """Calculate blind height with enhanced geometric accuracy."""
        is_edge_case, edge_position = EdgeCaseHandler.check_and_handle(
            self.sol_elev, self.gamma, self.distance, self.h_win
        )
        if is_edge_case:
            return edge_position

        effective_distance = self.distance

        if self.window_depth > 0 and abs(self.gamma) > WINDOW_DEPTH_GAMMA_THRESHOLD:
            depth_contribution = self.window_depth * float(sin(rad(abs(self.gamma))))
            effective_distance += depth_contribution

        if self.sill_height > 0:
            sill_offset = self.sill_height / max(
                float(tan(rad(self.sol_elev))), MIN_TAN_ELEVATION_CLAMP
            )
            effective_distance -= sill_offset

        if effective_distance < 0:
            effective_distance = 0.0

        cos_gamma = float(cos(rad(self.gamma)))
        cos_gamma_clamped = max(abs(cos_gamma), MIN_COS_GAMMA_CLAMP) * (
            1 if cos_gamma >= 0 else -1
        )
        path_length = effective_distance / cos_gamma_clamped
        base_height = path_length * float(tan(rad(self.sol_elev)))

        safety_margin = SafetyMarginCalculator.calculate(self.gamma, self.sol_elev)
        adjusted_height = base_height * safety_margin

        return float(np.clip(adjusted_height, 0, self.h_win))

    def calculate_percentage(self) -> float:
        """Convert blind height to percentage or default value."""
        position = self.calculate_position()
        self.logger.debug(
            "Converting height to percentage: %s / %s * 100", position, self.h_win
        )
        result = position / self.h_win * 100
        return round(result)


@dataclass
class AdaptiveHorizontalCover(AdaptiveVerticalCover):
    """Calculate state for Horizontal blinds."""

    awn_length: float
    awn_angle: float

    def calculate_position(self) -> float:
        """Calculate awn length from blind height."""
        awn_angle = 90 - self.awn_angle
        a_angle = 90 - self.sol_elev
        c_angle = 180 - awn_angle - a_angle

        vertical_position = super().calculate_position()
        denominator = float(sin(rad(c_angle)))
        if abs(denominator) < 1e-6:
            self.logger.warning("Awning geometry denominator is too small")
            return 0.0
        length = (
            (self.h_win - vertical_position) * float(sin(rad(a_angle)))
        ) / denominator
        if not np.isfinite(length):
            return 0.0
        return float(np.clip(length, 0, self.awn_length))

    def calculate_percentage(self) -> float:
        """Convert awn length to percentage or default value."""
        result = self.calculate_position() / self.awn_length * 100
        return round(result)


@dataclass
class AdaptiveTiltCover(AdaptiveGeneralCover):
    """Calculate state for tilted blinds."""

    slat_distance: float
    depth: float
    mode: str

    @property
    def beta(self):
        """Calculate beta."""
        beta = np.arctan(tan(rad(self.sol_elev)) / cos(rad(self.gamma)))
        return beta

    def calculate_position(self) -> float:
        """Calculate position of venetian blinds.

        https://www.mdpi.com/1996-1073/13/7/1731
        """
        beta = self.beta
        if self.depth <= 0:
            self.logger.error("Slat depth must be greater than zero")
            return 0.0

        ratio = self.slat_distance / self.depth
        radicand = (tan(beta) ** 2) - (ratio**2) + 1
        if radicand < 0:
            self.logger.warning("Tilt geometry has no real solution; clamping slats")
            radicand = 0.0
        denominator = 1 + ratio
        if abs(denominator) < 1e-6:
            return 0.0
        slat = 2 * np.arctan((tan(beta) + np.sqrt(radicand)) / denominator)
        result = np.rad2deg(slat)
        return float(result) if np.isfinite(result) else 0.0

    def calculate_percentage(self):
        """Convert tilt angle to percentages or default value."""
        # 0 degrees is closed, 90 degrees is open, 180 degrees is closed
        percentage_single = self.calculate_position() / 90 * 100  # single directional
        percentage_bi = self.calculate_position() / 180 * 100  # bi-directional

        if self.mode == "mode1":
            percentage = percentage_single
        else:
            percentage = percentage_bi

        return round(percentage)
