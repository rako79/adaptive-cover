"""Generate values for all types of covers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from homeassistant.core import HomeAssistant
from numpy import cos, sin, tan
from numpy import radians as rad

from .helpers import get_domain, get_safe_state
from .sun import SunData
from .config_context_adapter import ConfigContextAdapter

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
    @staticmethod
    def calculate(gamma: float, sol_elev: float) -> float:
        margin = 1.0
        gamma_abs = abs(gamma)
        if gamma_abs > SAFETY_MARGIN_GAMMA_THRESHOLD:
            t = (gamma_abs - SAFETY_MARGIN_GAMMA_THRESHOLD) / (90 - SAFETY_MARGIN_GAMMA_THRESHOLD)
            t = float(np.clip(t, 0, 1))
            smooth_t = t * t * (3 - 2 * t)
            margin += SAFETY_MARGIN_GAMMA_MAX * smooth_t
        if sol_elev < SAFETY_MARGIN_LOW_ELEV_THRESHOLD:
            t = (SAFETY_MARGIN_LOW_ELEV_THRESHOLD - sol_elev) / SAFETY_MARGIN_LOW_ELEV_THRESHOLD
            margin += SAFETY_MARGIN_LOW_ELEV_MAX * float(np.clip(t, 0, 1))
        elif sol_elev > SAFETY_MARGIN_HIGH_ELEV_THRESHOLD:
            t = (sol_elev - SAFETY_MARGIN_HIGH_ELEV_THRESHOLD) / (90 - SAFETY_MARGIN_HIGH_ELEV_THRESHOLD)
            margin += SAFETY_MARGIN_HIGH_ELEV_MAX * float(np.clip(t, 0, 1))
        return float(margin)

class EdgeCaseHandler:
    @staticmethod
    def check_and_handle(sol_elev: float, gamma: float, distance: float, h_win: float) -> tuple[bool, float]:
        if sol_elev < EDGE_CASE_LOW_ELEVATION:
            return (True, h_win)
        if abs(gamma) > EDGE_CASE_EXTREME_GAMMA:
            return (True, h_win)
        if sol_elev > EDGE_CASE_HIGH_ELEVATION:
            simple_height = distance * np.tan(np.radians(sol_elev))
            return (True, float(np.clip(simple_height, 0, h_win)))
        return (False, 0.0)

def state_attr(hass, entity_id: str, attr_name: str):
    if not entity_id:
        return None
    state = hass.states.get(entity_id)
    if state is None:
        return None
    return state.attributes.get(attr_name)

@dataclass
class AdaptiveGeneralCover(ABC):
    """Collect common data."""

    hass: HomeAssistant
    logger: ConfigContextAdapter
    sol_azi: float
    sol_elev: float
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

    def __post_init__(self):
        """Add solar data to dataset."""
        self.sun_data = SunData(self.timezone, self.hass)

    def solar_times(self):
        """Determine start/end times."""
        df_today = pd.DataFrame(
            {
                "azimuth": self.sun_data.solar_azimuth,
                "elevation": self.sun_data.solar_elevation,
            }
        )
        solpos = df_today.set_index(self.sun_data.times)

        alpha = solpos["azimuth"]
        frame = (
            (alpha - self.azi_min_abs) % 360
            <= (self.azi_max_abs - self.azi_min_abs) % 360
        ) & (solpos["elevation"] > 0)

        if solpos[frame].empty:
            return None, None
        else:
            return (
                solpos[frame].index[0].to_pydatetime(),
                solpos[frame].index[-1].to_pydatetime(),
            )

    @property
    def _get_azimuth_edges(self) -> tuple[int, int]:
        """Calculate azimuth edges."""
        return self.fov_left + self.fov_right

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
        sunset = self.sun_data.sunset().replace(tzinfo=None)
        sunrise = self.sun_data.sunrise().replace(tzinfo=None)
        after_sunset = datetime.utcnow() > (sunset + timedelta(minutes=self.sunset_off))
        before_sunrise = datetime.utcnow() < (
            sunrise + timedelta(minutes=self.sunrise_off)
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

    def fov(self) -> list:
        """Return field of view."""
        return [self.azi_min_abs, self.azi_max_abs]

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
        return (self.valid) & (not self.sunset_valid) & (not self.is_sun_in_blind_spot)

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
        
        # Ochrona przed zaokrąglaniem w dół do 0 gdy słońce w oknie
        if dsv:
            result = max(result, 1)

        if self.cover.apply_max_position and result > self.cover.max_pos:
            return self.cover.max_pos
        if self.cover.apply_min_position and result < self.cover.min_pos:
            return self.cover.min_pos
        return result


@dataclass
class ClimateCoverData:
    """Fetch additional data."""

    hass: HomeAssistant
    logger: ConfigContextAdapter
    temp_entity: str
    temp_low: float
    temp_high: float
    presence_entity: str
    weather_entity: str
    weather_condition: list[str]
    outside_entity: str
    temp_switch: bool
    blind_type: str
    transparent_blind: bool
    lux_entity: str
    irradiance_entity: str
    lux_threshold: int
    irradiance_threshold: int
    temp_summer_outside: float
    _use_lux: bool
    _use_irradiance: bool
    rain_entity: str
    wind_entity: str
    dawn_start_month: int
    dawn_end_month: int
    dawn_duration_min: int
    cold_threshold: float
    wind_threshold: float
    purge_pos: int
    rain_night_only: bool
    strict_sun_block_toggle: bool = False

    @property
    def is_raining(self) -> bool:
        """Check for rain using dedicated sensor or weather entity."""
        # --- 1. ZBIERAMY DANE: Sprawdzamy, czy fizycznie pada deszcz ---
        is_actually_raining = False

        # Sprawdź dedykowany czujnik deszczu (np. binary_sensor)
        if self.rain_entity:
            state = get_safe_state(self.hass, self.rain_entity)
            if str(state).lower() in ["on", "true", "detected", "1"]:
                is_actually_raining = True
            else:
                # Jeśli to sensor liczbowy (np. mm/h), uznamy deszcz powyżej 0
                try:
                    if float(state) > 0: 
                        is_actually_raining = True
                except (ValueError, TypeError): 
                    pass

        # Fallback do encji pogody (jeśli czujnik opadów nie wykrył deszczu)
        if not is_actually_raining:
            weather = get_safe_state(self.hass, self.weather_entity)
            if weather in ['rainy', 'pouring', 'lightning-rainy', 'hail', 'snowy', 'snowy-rainy']:
                is_actually_raining = True

        # --- 2. NOWA LOGIKA: Zignoruj deszcz, jeśli jest dzień i opcja jest włączona ---
        if is_actually_raining:
            # Pobieramy ustawienie z opcji (zabezpieczenie na wypadek braku klucza)
            # Jeśli self.config to słownik/ConfigEntry, używamy metody pobierania opcji
            night_only = self.rain_night_only
            
            # Sprawdzamy pozycję słońca prosto z Home Assistanta, żeby było niezawodnie
            sun_state = self.hass.states.get('sun.sun')
            is_daytime = sun_state and sun_state.state == 'above_horizon'
            
            # Jeśli włączono opcję ignorowania w dzień ORAZ słońce jest nad horyzontem
            if night_only and is_daytime:
                return False  # Oszukujemy system: "Słońce świeci, udajemy, że nie pada"
            
            return True  # W nocy lub gdy opcja jest wyłączona: mówimy prawdę (pada)
            
        return False

    @property
    def current_wind_speed(self) -> float:
        """Get wind speed from dedicated sensor or weather entity."""
        if self.wind_entity:
            val = get_safe_state(self.hass, self.wind_entity)
            try: return float(val)
            except (ValueError, TypeError): pass
            
        # Fallback do atrybutu weather_entity
        if self.weather_entity:
            return float(state_attr(self.hass, self.weather_entity, "wind_speed") or 0)
        return 0.0
    
    @property
    def outside_temperature(self):
        """Get outside temperature and today's max forecast."""
        temp = None
        
        # Jeśli użyto osobnego sensora temperatury zewnętrznej
        if self.outside_entity:
            temp = get_safe_state(
                self.hass,
                self.outside_entity,
            )
            # W tym trybie nie mamy prognozy z pojedynczego sensora, przypisujemy temp do max_forecast
            self.max_forecast_temp = float(temp) if temp is not None else None

        # Jeśli użyto integracji pogody (np. weather.home)
        elif self.weather_entity:
            # 1. Pobierz aktualną temperaturę na zewnątrz
            temp = state_attr(self.hass, self.weather_entity, "temperature")
            
            # 2. Pobierz prognozę, by wiedzieć, czy później będzie gorąco
            forecast_data = state_attr(self.hass, self.weather_entity, "forecast")
            if forecast_data and isinstance(forecast_data, list) and len(forecast_data) > 0:
                # Bierzemy prognozowaną temperaturę na pierwszy dzień/godzinę z listy
                # (Zazwyczaj jest to dzisiejsze maksimum w prognozach dziennych)
                forecast_temp = forecast_data[0].get("temperature")
                if forecast_temp is not None:
                    self.max_forecast_temp = float(forecast_temp)
                else:
                    self.max_forecast_temp = float(temp) if temp is not None else None
            else:
                self.max_forecast_temp = float(temp) if temp is not None else None
                
        return temp

    @property
    def inside_temperature(self):
        """Get inside temp from entity."""
        if self.temp_entity is not None:
            if get_domain(self.temp_entity) != "climate":
                temp = get_safe_state(
                    self.hass,
                    self.temp_entity,
                )
            else:
                temp = state_attr(self.hass, self.temp_entity, "current_temperature")
            return temp

    @property
    def get_current_temperature(self) -> float:
        """Get temperature."""
        if self.temp_switch:
            if self.outside_temperature is not None:
                return float(self.outside_temperature)
        if self.inside_temperature is not None:
            return float(self.inside_temperature)

    @property
    def is_presence(self):
        """Checks if people are present."""
        presence = None
        if self.presence_entity is not None:
            presence = get_safe_state(self.hass, self.presence_entity)
        # set to true if no sensor is defined
        if presence is not None:
            domain = get_domain(self.presence_entity)
            if domain == "device_tracker":
                return presence == "home"
            if domain == "zone":
                return int(presence) > 0
            if domain in ["binary_sensor", "input_boolean"]:
                return presence == "on"
        return True

    @property
    def is_winter(self) -> bool:
        """Check if temperature is below threshold."""
        if self.temp_low is not None and self.get_current_temperature is not None:
            is_it = self.get_current_temperature < self.temp_low
        else:
            is_it = False

        self.logger.debug(
            "is_winter(): current_temperature < temp_low: %s < %s = %s",
            self.get_current_temperature,
            self.temp_low,
            is_it,
        )
        return is_it

    @property
    def outside_high(self) -> bool:
        """Check if outdoor temperature is above threshold."""
        if (
            self.temp_summer_outside is not None
            and self.outside_temperature is not None
        ):
            return float(self.outside_temperature) > self.temp_summer_outside
        return True

    @property
    def is_summer(self) -> bool:
        """Check if temperature is over threshold OR if predictive high heat is expected."""
        if self.temp_high is None or self.get_current_temperature is None:
             return False

        # 1. Wymaganie starego algorytmu: w pokoju już jest za gorąco
        already_hot_inside = self.get_current_temperature > self.temp_high
        
        # 2. PREDYKCJA: W pokoju jest OK, ale prognoza przewiduje duży upał (np. o 2 stopnie wyżej niż nasza tolerancja temp_summer_outside)
        # Musimy wywołać outside_temperature, żeby zmienna max_forecast_temp się zainicjowała
        _ = self.outside_temperature 
        predictive_heat = False
        
        if hasattr(self, 'max_forecast_temp') and self.max_forecast_temp is not None and self.temp_summer_outside is not None:
            # Jeśli prognoza przekracza nasz ustawiony próg zewnętrzny (plus bufor)
            predictive_heat = self.max_forecast_temp > (self.temp_summer_outside + 2.0)

        # 3. WYSOKIE NASŁONECZNIENIE: W pokoju jest gorąco i słońce mocno grzeje (nawet jeśli na zewnątrz jest chłodno)
        high_radiation = False
        if already_hot_inside:
            if getattr(self, "_use_irradiance", False) and getattr(self, "irradiance_entity", None) and getattr(self, "irradiance_threshold", None) is not None:
                val = get_safe_state(self.hass, self.irradiance_entity)
                try:
                    # Jeśli nasłonecznienie jest > progu (czyli słońce świeci)
                    high_radiation = float(val) > self.irradiance_threshold
                except (ValueError, TypeError):
                    pass
            elif getattr(self, "_use_lux", False) and getattr(self, "lux_entity", None) and getattr(self, "lux_threshold", None) is not None:
                val = get_safe_state(self.hass, self.lux_entity)
                try:
                    high_radiation = float(val) > self.lux_threshold
                except (ValueError, TypeError):
                    pass

        # Jest "Lato" (czyli zamykamy rolety), jeśli wewnątrz już jest gorąco ALBO na zewnątrz będzie bardzo gorąco.
        # Warunkiem koniecznym dla already_hot_inside jest, że na zewnątrz faktycznie JEST cieplej/prognozowane cieplej, żeby nie zamknąć rolet zimą.
        # DODATEK: Jeśli słońce bezpośrednio grzeje (high_radiation = True), zamykamy rolety niezależnie od temp na zewnątrz, jeśli wewnątrz jest gorąco.
        is_it = (already_hot_inside and self.outside_high) or predictive_heat or high_radiation

        self.logger.debug(
            "PREDICTIVE is_summer(): Already Hot? %s | Predictive Heat Expected? %s (Max Forecast: %s) | High Radiation? %s -> Result: %s",
            already_hot_inside,
            predictive_heat,
            getattr(self, 'max_forecast_temp', 'N/A'),
            high_radiation,
            is_it,
        )
        return is_it

    @property
    def thermal_stress(self) -> float:
        """Calculate thermal stress for fuzzy logic (0.0 to 1.0) using MPC (Model Predictive Control)."""
        if self.temp_high is None or self.get_current_temperature is None:
            return 0.0
            
        current = self.get_current_temperature
        comfort = self.temp_high
        outside = self.outside_temperature
        
        # Start closing blinds when we are 2 degrees below comfort
        start_temp = comfort - 2.0
        
        # --- MODEL PREDICTIVE CONTROL (MPC) ---
        # Predict temperature in 1 hour
        # T_next = T_current + (alpha * Irradiance) - beta * (T_current - T_outside)
        
        alpha = 0.002 # Wzrost o 0.002 st. na każdy W/m2 nasłonecznienia
        beta = 0.1    # Wymiana ciepła z otoczeniem
        
        predicted_temp = current
        
        # Oszacowanie nasłonecznienia
        rad_value = 0.0
        if getattr(self, "irradiance_entity", None):
            val = get_safe_state(self.hass, self.irradiance_entity)
            try:
                rad_value = float(val)
            except (ValueError, TypeError):
                pass
        elif getattr(self, "lux_entity", None):
            val = get_safe_state(self.hass, self.lux_entity)
            try:
                rad_value = float(val) * 0.0079 # przybliżony przelicznik z lux na W/m2
            except (ValueError, TypeError):
                pass
                
        # Obliczanie predykcji
        if outside is not None:
            delta_t = current - float(outside)
            predicted_temp = current + (alpha * rad_value) - (beta * delta_t)
            
        # Zabezpieczenie przed wychłodzeniem predykcyjnym (np. gdy otwarto okno w zimie)
        # Bierzemy maksymalną wartość (nie chcemy, by predykcja gwałtownie otwierała rolety latem)
        effective_temp = max(current, predicted_temp)
        
        # Ochrona przed "szklarnią": Jeśli słońce mocno grzeje, ucinamy strefę komfortu, 
        # żeby system zaczął zamykać rolety wcześniej, nawet jeśli na zewnątrz jest chłodno.
        if getattr(self, "_use_irradiance", False) and getattr(self, "irradiance_threshold", None) is not None:
            try:
                if float(rad_value) > self.irradiance_threshold:
                    start_temp -= 1.0
                    comfort -= 1.0
                    self.logger.debug("Silne nasłonecznienie (%s > %s). Obniżono strefę komfortu o 1°C.", rad_value, self.irradiance_threshold)
            except (ValueError, TypeError):
                pass
        
        # Add predictive heat offset from weather forecast (macro prediction)
        if hasattr(self, 'max_forecast_temp') and self.max_forecast_temp is not None and self.temp_summer_outside is not None:
            if self.max_forecast_temp > (self.temp_summer_outside + 2.0):
                # Shift the comfort zone down by 1 degree if it's going to be very hot later
                start_temp -= 1.0
                comfort -= 1.0
        
        if effective_temp >= comfort:
            return 1.0
        elif effective_temp <= start_temp:
            return 0.0
        else:
            return (effective_temp - start_temp) / (comfort - start_temp)

    @property
    def is_sunny(self) -> bool:
        """Check if condition can contain radiation in winter/summer."""
        if not self.weather_entity:
            self.logger.debug("is_sunny(): Brak encji pogodowej")
            return True

        weather_state = get_safe_state(self.hass, self.weather_entity)
        
        # --- ETAP 5: INTELIGENTNY BUFOR CHMUR (CLOUD COVERAGE) ---
        # 1. Sprawdzamy dokładny procent zachmurzenia (jeśli pogoda go podaje)
        cloud_coverage = state_attr(self.hass, self.weather_entity, "cloud_coverage")
        if cloud_coverage is not None:
            try:
                clouds = float(cloud_coverage)
                self.logger.debug("is_sunny: Odczytano zachmurzenie %s%%", clouds)
                
                # Histereza (Bufor):
                if clouds > 65:
                    self.logger.debug("is_sunny: Grube chmury (>65%). Brak słońca.")
                    return False  # Na pewno nie ma słońca
                elif clouds < 35:
                    self.logger.debug("is_sunny: Czyste niebo (<35%). Jest słońce.")
                    return True   # Na pewno jest słońce
                
                # Jeśli zachmurzenie jest pomiędzy 35% a 65%, algorytm NIE PODEJMUJE agresywnej decyzji z procentów,
                # tylko "przepuszcza" logikę dalej, unikając skakania rolet przy każdej małej chmurce.
            except (ValueError, TypeError):
                pass
        # ---------------------------------------------------------

        # 2. Standardowy fallback do statusu słownego (jeśli pogoda nie ma procentów 
        # lub chmury są w strefie przejściowej 35-65%)
        if self.weather_condition is not None:
            matches = weather_state in self.weather_condition
            self.logger.debug("is_sunny(): Stan %s w liście słonecznych = %s", weather_state, matches)
            return matches
            
        return True

    @property
    def lux(self) -> bool:
        """Get lux value and compare to threshold."""
        if not self._use_lux:
            return False
        if self.lux_entity is not None and self.lux_threshold is not None:
            value = get_safe_state(self.hass, self.lux_entity)
            return float(value) <= self.lux_threshold
        return False

    @property
    def irradiance(self) -> bool:
        """Get irradiance value and compare to threshold."""
        if not self._use_irradiance:
            return False
        if self.irradiance_entity is not None and self.irradiance_threshold is not None:
            value = get_safe_state(self.hass, self.irradiance_entity)
            return float(value) <= self.irradiance_threshold
        return False


@dataclass
class ClimateCoverState(NormalCoverState):
    """Compute state for climate control operation."""

    climate_data: ClimateCoverData

    def normal_type_cover(self) -> int:
        """Determine state for horizontal and vertical covers."""

        self.cover.logger.debug("Is presence? %s", self.climate_data.is_presence)

        if self.climate_data.is_presence:
            return self.normal_with_presence()

        return self.normal_without_presence()

    def normal_with_presence(self) -> int:
        """Determine state for horizontal and vertical covers with occupants."""

        is_summer = self.climate_data.is_summer
        stress = self.climate_data.thermal_stress

        # Check if it's not summer and either lux, irradiance or sunny weather is present
        if not is_summer and (
            self.climate_data.lux
            or self.climate_data.irradiance
            or not self.climate_data.is_sunny
        ):
            # If it's winter and the cover is valid, return 100
            if self.climate_data.is_winter and self.cover.valid:
                self.cover.logger.debug(
                    "n_w_p(): Winter and sun is in front of window = use 100"
                )
                self.cover.state_reason = "Tryb zimowy: okno w pełni odsłonięte, aby nagrzać pomieszczenie słońcem."
                return 100
            # Otherwise, return the default cover state
            self.cover.logger.debug(
                "n_w_p(): it's not summer and sunny weather is not present = use default"
            )
            self.cover.state_reason = "Brak silnego słońca lub lata: używam domyślnej pozycji (wpuść światło)."
            return self.cover.default

        # If it's summer and there's a transparent blind, return 0
        if is_summer and self.climate_data.transparent_blind:
            self.cover.state_reason = "Tryb letni (transparentna roleta): całkowite zamknięcie w celu blokady nagrzewania."
            return 0

        # FUZZY LOGIC: Interpolate position based on thermal stress
        if stress > 0.0 and self.cover.valid:
            base_pos = super().get_state()
            fuzzy_pos = int(base_pos * (1.0 - stress))
            self.cover.logger.debug(
                "n_w_p(): Fuzzy logic triggered. Stress: %s, Base: %s, Fuzzy: %s",
                stress, base_pos, fuzzy_pos
            )
            self.cover.state_reason = f"Częściowe zamknięcie (Logika Rozmyta). Stres termiczny: {int(stress*100)}%. Pozycja: {fuzzy_pos}%."
            return fuzzy_pos

        # If none of the above conditions are met, get the state from the parent class
        self.cover.logger.debug("n_w_p(): None of the climate conditions are met")
        self.cover.state_reason = "Adaptacja do pozycji słońca (minimalizacja odblasków, wpuszczenie światła)."
        return super().get_state()

    def normal_without_presence(self) -> int:
        """Determine state for horizontal and vertical covers without occupants."""
        if self.cover.valid:
            stress = self.climate_data.thermal_stress
            if stress > 0.0 or self.climate_data.is_summer:
                # Wymuszamy 100% stress, jeśli is_summer=True
                effective_stress = max(stress, 1.0 if self.climate_data.is_summer else 0.0)
                fuzzy_pos = int(self.cover.default * (1.0 - effective_stress))
                self.cover.state_reason = f"Tryb letni / bez obecności. Stres termiczny: {int(effective_stress*100)}%. Pozycja: {fuzzy_pos}%."
                return fuzzy_pos
            if self.climate_data.is_winter:
                self.cover.state_reason = "Tryb zimowy / bez obecności. Maksymalne nagrzewanie pokoju promieniami słońca."
                return 100
        self.cover.state_reason = "Brak obecności. Używam pozycji domyślnej."
        return self.cover.default

    def tilt_with_presence(self, degrees: int) -> int:
        """Determine state for tilted blinds with occupants."""
        stress = self.climate_data.thermal_stress
        
        if self.cover.valid and (
            self.climate_data.lux
            or self.climate_data.irradiance
            or not self.climate_data.is_sunny
        ):
            if self.climate_data.is_summer or stress > 0.5:
                # If it's summer, return 45 degrees
                self.cover.state_reason = "Tryb letni (obecność): lamele pochylone pod kątem 45 stopni dla redukcji nasłonecznienia."
                return int(45 / degrees * 100)
            
            # Not summer, use base state
            base_pos = super().get_state()
            self.cover.state_reason = "Tryb standardowy (pochylenie lamel zależy od słońca)."
            return base_pos
            
        self.cover.state_reason = "Lamele otwarte do 80 stopni (ochrona przed odblaskami / brak mocnego słońca)."
        return int(80 / degrees * 100)

    def tilt_without_presence(self, degrees: int) -> int:
        """Determine state for tilted blinds without occupants."""
        beta = np.rad2deg(self.cover.beta)
        if self.cover.valid:
            stress = self.climate_data.thermal_stress
            if self.climate_data.is_summer or stress > 0.0:
                # block out all light in summer
                effective_stress = max(stress, 1.0 if self.climate_data.is_summer else 0.0)
                fuzzy_pos = int(0 + (80 / degrees * 100) * (1.0 - effective_stress))
                self.cover.state_reason = f"Tryb letni / bez obecności: lamele przymknięte na {fuzzy_pos}% ze względu na stres termiczny ({int(effective_stress*100)}%)."
                return fuzzy_pos
            if self.climate_data.is_winter and self.cover.mode == "mode2":
                # parallel to sun beams, not possible with single direction
                self.cover.state_reason = "Tryb zimowy / bez obecności: lamele równolegle do promieni słonecznych w celu nagrzania pomieszczenia."
                return int((beta + 90) / degrees * 100)
            
            self.cover.state_reason = "Domyślne otwarcie do 80 stopni."
            return int(80 / degrees * 100)
        
        self.cover.state_reason = "Oczekiwanie na normalne warunki (adaptacja lamel)."
        return super().get_state()

    def tilt_state(self):
        """Add tilt specific controls."""
        degrees = 90
        if self.cover.mode == "mode2":
            degrees = 180
        if self.climate_data.is_presence:
            return self.tilt_with_presence(degrees)
        return self.tilt_without_presence(degrees)

    def get_state(self) -> int:
        """Return state."""
        self.cover.state_info = "auto"
        if not hasattr(self.cover, 'state_reason') or not self.cover.state_reason:
            self.cover.state_reason = "Działanie automatyczne."
            
        now = datetime.now()
        result = None

        # 1. Ochrona pogodowa
        if self.climate_data.is_raining:
            self.cover.state_info = "rain_detected"
            self.cover.state_reason = "Ochrona pogodowa: Wykryto deszcz. Całkowite zamknięcie."
            result = 0
            
        wind_thresh = getattr(self.climate_data, "wind_threshold", 40)
        if result is None and self.climate_data.current_wind_speed > wind_thresh:
            self.cover.state_info = "wind_detected"
            self.cover.state_reason = "Ochrona pogodowa: Silny wiatr. Całkowite zamknięcie."
            result = 0

        # 2. Ochrona przed świtem (Dawn Protection)
        m_start = getattr(self.climate_data, "dawn_start_month", 5)
        m_end = getattr(self.climate_data, "dawn_end_month", 10)
        duration = getattr(self.climate_data, "dawn_duration_min", 60)
        
        if result is None and m_start <= now.month <= m_end:
            now_utc = datetime.utcnow()
            sunrise = self.cover.sun_data.sunrise().replace(tzinfo=None)
            time_to_sunrise = (sunrise - now_utc).total_seconds()
            if 0 < time_to_sunrise < (duration * 60):
                self.cover.state_info = "dawn_protection"
                self.cover.state_reason = "Ochrona przed świtem (blokowanie wczesnego słońca latem)."
                result = 0

        # 2.5 Strict Sun Block
        if result is None and getattr(self.climate_data, "strict_sun_block_toggle", False):
            if m_start <= now.month <= m_end:
                if self.cover.direct_sun_valid:
                    # Sprawdź, czy faktycznie jest słonecznie i nie pada
                    has_sun = False
                    
                    if getattr(self.climate_data, "irradiance_entity", None):
                        # irradiance jest True, gdy wartość JEST <= próg (czyli brak słońca)
                        # Więc jeśli irradiance jest False, to znaczy że słońce przekracza próg W/m2
                        if not self.climate_data.irradiance and not self.climate_data.is_raining:
                            has_sun = True
                    else:
                        if self.climate_data.is_sunny and not self.climate_data.is_raining:
                            has_sun = True

                    if has_sun:
                        self.cover.state_info = "strict_sun_block"
                        self.cover.state_reason = "Blokada słońca: silne słońce w oknie, rolety zamknięte."
                        result = 0

        # 3. Ochrona przed zimnem i Nocne wietrzenie
        if result is None:
            outside = self.climate_data.outside_temperature
            if outside is not None:
                cold_thresh = getattr(self.climate_data, "cold_threshold", 16)
                
                # --- POPRAWKA: Ochrona przed zimnem działa TYLKO w nocy (po zachodzie słońca) ---
                if float(outside) < cold_thresh and self.cover.sunset_valid:
                    self.cover.state_info = "cold_protection"
                    self.cover.state_reason = "Ochrona przed zimnem: jest noc i niska temperatura na zewnątrz."
                    result = 0
                
                # Purge (wietrzenie) również tylko w nocy
                if result is None and self.cover.sunset_valid:
                    inside = self.climate_data.inside_temperature
                    temp_comfort = self.climate_data.temp_low
                    purge_val = getattr(self.climate_data, "purge_pos", 15)
                    
                    if inside is not None and temp_comfort is not None:
                        if float(inside) > float(temp_comfort) and float(outside) < float(inside):
                            self.cover.state_info = "night_purge"
                            self.cover.state_reason = "Nocne wietrzenie (Night Purge): lekko uchylone rolety, aby schłodzić pokój."
                            result = purge_val if self.climate_data.blind_type != "cover_tilt" else 50

        # 4. Powrót do standardowej logiki (dla trybów dziennych / nocnych jeśli żaden z powyższych)
        if result is None:
            result = self.normal_type_cover()
            if self.climate_data.blind_type == "cover_tilt":
                # Tilt state requires a custom reason string, assuming `tilt_state` will set it
                result = self.tilt_state()
                
            # Ochrona przed zaokrąglaniem w dół do 0 gdy słońce w oknie i brak innej ochrony klimatycznej
            if self.cover.direct_sun_valid and self.cover.state_info == "auto":
                result = max(result, 1)

            if not self.cover.valid and self.cover.sunset_valid:
                 self.cover.state_info = "night_mode"
                 self.cover.state_reason = "Tryb nocny: słońce po zachodzie."
            elif not self.cover.valid:
                 self.cover.state_info = "sun_shadow"
                 self.cover.state_reason = "Słońce poza zasięgiem okna (okno w cieniu)."

        # --- Aplikacja nadrzędnych limitów ---
        if self.cover.apply_max_position and result > self.cover.max_pos:
            self.cover.state_info = "max_limit"
            self.cover.state_reason = f"Ograniczenie przez maksymalną pozycję ({self.cover.max_pos}%)."
            return self.cover.max_pos
        if self.cover.apply_min_position and result < self.cover.min_pos:
            self.cover.state_info = "min_limit"
            self.cover.state_reason = f"Ograniczenie przez minimalną pozycję ({self.cover.min_pos}%)."
            return self.cover.min_pos

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
            sill_offset = self.sill_height / max(float(tan(rad(self.sol_elev))), MIN_TAN_ELEVATION_CLAMP)
            effective_distance -= sill_offset

        if effective_distance < 0:
            effective_distance = 0.0

        cos_gamma = float(cos(rad(self.gamma)))
        cos_gamma_clamped = max(abs(cos_gamma), MIN_COS_GAMMA_CLAMP) * (1 if cos_gamma >= 0 else -1)
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
        length = ((self.h_win - vertical_position) * sin(rad(a_angle))) / sin(
            rad(c_angle)
        )
        # return np.clip(length, 0, self.awn_length)
        return length

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

        slat = 2 * np.arctan(
            (
                tan(beta)
                + np.sqrt(
                    (tan(beta) ** 2) - ((self.slat_distance / self.depth) ** 2) + 1
                )
            )
            / (1 + self.slat_distance / self.depth)
        )
        result = np.rad2deg(slat)

        return result

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
