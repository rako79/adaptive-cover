"""Behavioral Learning Module for Adaptive Cover."""

from homeassistant.core import HomeAssistant

class BehavioralLearner:
    """Learns user preferences using Exponential Moving Average."""

    def __init__(self, hass: HomeAssistant, logger) -> None:
        """Initialize the learner."""
        self.hass = hass
        self.logger = logger
        self.learned_positions = {}
        self.learned_temps = {}
        self.alpha = 0.1  # Szybkość uczenia (10% nowej wartości, 90% starej)

    def register_override(self, entity_id: str, current_temp: float, our_state: int, new_position: int, is_summer: bool):
        """Register a manual override event and update EMA."""
        # 1. Adaptacja domyślnej pozycji
        if entity_id not in self.learned_positions:
            self.learned_positions[entity_id] = float(our_state)

        old_pos = self.learned_positions[entity_id]
        # EMA uczenie pozycji
        self.learned_positions[entity_id] = (1 - self.alpha) * old_pos + self.alpha * new_position

        self.logger.info(
            "Behavioral ML: Zaktualizowano preferowaną pozycję dla %s. Stara: %s, Nowa (nauczona): %s (Użytkownik ustawił: %s)",
            entity_id, old_pos, self.learned_positions[entity_id], new_position
        )

        # 2. Adaptacja temperatury komfortu (jeśli użytkownik zamyka w lecie pomimo braku stresu)
        if current_temp is not None:
            if entity_id not in self.learned_temps:
                self.learned_temps[entity_id] = 0.0 # offset

            # Jeśli w pokoju jest np. 23 stopnie, a system nie zamknął rolet, ale użytkownik to zrobił
            # Oznacza to, że użytkownik preferuje niższą temperaturę komfortową (próg)
            if new_position < our_state and not is_summer:
                # Obniżamy temperaturę komfortu
                self.learned_temps[entity_id] -= 0.1
                self.logger.info("Behavioral ML: Obniżono próg temperatury dla %s o 0.1st C", entity_id)

    def get_position_offset(self, entity_id: str, default_pos: int) -> int:
        """Get the learned position (if any) or fallback to default."""
        if entity_id in self.learned_positions:
            return int(self.learned_positions[entity_id])
        return default_pos

    def get_temp_offset(self, entity_id: str) -> float:
        """Get learned temperature offset."""
        return self.learned_temps.get(entity_id, 0.0)
