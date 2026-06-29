# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased] - 2026-06-27

### Naprawione
- [Naprawione] Status algorytmu pokazuje teraz wyłączoną automatykę zamiast nieaktualnego powodu wyliczonej pozycji.
- [Naprawione] Uzupełniono listę stanów sensora algorytmu o `control_disabled` i brakujący `strict_sun_block`.
- [Naprawione] Koniec dziennego harmonogramu nie wymusza już pozycji `0%`, gdy aktywne jest nocne sterowanie klimatyczne.
- [Naprawione] Nocne wietrzenie i zabezpieczenia klimatyczne mogą reagować także poza godzinami dziennego harmonogramu.
- [Naprawione] Ruch wykonany przez dodatek nie jest już błędnie oznaczany jako ręczne sterowanie po osiągnięciu pozycji docelowej.
- [Naprawione] Dostępny fizyczny czujnik opadów ma pierwszeństwo przed prognozą pogody, co zapobiega cyklicznemu zamykaniu i otwieraniu rolet podczas nocnego wietrzenia.

### Dodane
- [Dodane] Dodano konfigurowalną godzinę zakończenia nocnego wietrzenia; rolety są wtedy zamykane na `0%`.
- [Zmienione] Ochrona przed świtem i poranna blokada słońca nie przerywają wietrzenia przed ustawioną godziną, jeśli nadal spełnione są warunki temperaturowe.

## [Unreleased] - 2026-06-18

### Naprawione
- [Naprawione] Dodano nazwę przełącznika `dry_run_toggle` jako `Tryb testowy`, aby nie wyświetlał się jako nazwa pomieszczenia.
- [Dodane] Rozszerzono `export_diagnostics` o `schema_version`, `configured_covers` oraz `cover_diagnostics` z czytelnym podsumowaniem każdej rolety.
- [Dodane] Dodano do atrybutów diagnostycznych surowe odczyty `inside_temperature`, `lux`, `irradiance`, `outside_temperature_entity`, `rain_rate`, `weather_state` i `wind_gust`.
- [Dodane] Dodano konfigurowalne utrzymanie ochrony termicznej po wyjściu słońca z zasięgu okna.
- [Dodane] Dodano przełącznik nocnego wietrzenia oraz suwak pozycji wietrzenia nocnego w ustawieniach klimatycznych.
- [Naprawione] Zmieniono blokadę `delta_time`, aby opierała się na ostatnim ruchu wykonanym przez dodatek, a nie na `last_updated` encji rolety w Home Assistant. Dzięki temu świeżo odświeżony stan rolety nie blokuje automatycznego domknięcia.
- [Naprawione] Poprawiono wybór temperatury bieżącej w logice klimatycznej: algorytm używa temperatury pokoju, a temperatury zewnętrznej tylko jako awaryjnego fallbacku.
- [Naprawione] Rozszerzono diagnostykę pominiętych ruchów o konkretny powód blokady, np. `time_delta_not_passed`, `manual_override_active` albo `position_delta_too_small`.
- [Naprawione] Poprawiono polskie opisy usług w `services.yaml`.

## [Unreleased] - 2026-05-26

### Dodane (Added)
- **PL:** Wdrożono **Explainable AI** – dodano nowy sensor `sensor.{type}_state_reason_{name}` opisujący powody podejmowanych decyzji przez algorytm.
- **EN:** Implemented **Explainable AI** – added a new `sensor.{type}_state_reason_{name}` entity describing the reasons behind algorithm decisions.
- **PL:** Dodano **Model Predictive Control (MPC)** – wbudowano predykcyjny model termiczny szacujący temperaturę za godzinę na podstawie nasłonecznienia (W/m2 / Lux).
- **EN:** Added **Model Predictive Control (MPC)** – built-in predictive thermal model estimating the room temperature in 1 hour based on solar irradiance (W/m2 / Lux).
- **PL:** Dodano moduł **Uczenia Nawyków (Behavioral ML)** bazujący na EMA (Exponential Moving Average), uczący się preferowanej pozycji rolet i temperatury po ręcznych zmianach użytkownika (`learning.py`).
- **EN:** Added **Behavioral ML** module using EMA (Exponential Moving Average) to learn preferred cover positions and comfort temperatures after manual overrides (`learning.py`).
- **PL:** Dodano usługi `adaptive_cover.export_config` i `adaptive_cover.import_config` pozwalające na zrzut i wgrywanie pełnej konfiguracji wszystkich rolet z/do pliku `adaptive_cover_settings.json` w katalogu `/config`. 
- **EN:** Added `adaptive_cover.export_config` and `adaptive_cover.import_config` services to export and import full configuration of all covers from/to `adaptive_cover_settings.json` file in the `/config` directory.
- **PL:** Dodano tryb **Strict Sun Block** – funkcja zamykająca rolety wyłącznie na podstawie bezpośredniego nasłonecznienia okna, jeśli dzień jest słoneczny. Posiada własny przełącznik w interfejsie.
- **EN:** Added **Strict Sun Block** mode – a feature that closes the blinds strictly based on direct sun exposure on the window during sunny days, equipped with its own dashboard switch.

### Zmienione / Poprawione (Changed / Fixed)
- **PL:** Zmieniono zachowanie domyślne na **Logikę Rozmytą (Fuzzy Logic)** – zamiast zachowania 0% / 100%, rolety zamykają i otwierają się płynnie w zależności od "Stresu termicznego".
- **EN:** Changed the default behavior to **Fuzzy Logic** – instead of 0% / 100% states, covers now adjust fluently based on the calculated "Thermal Stress".
- **PL:** Zmieniono logikę `is_summer` (letniego zamykania rolet) w `calculation.py`. Od teraz rolety zostaną zamknięte, gdy wewnątrz pomieszczenia robi się zbyt gorąco i słońce mocno grzeje (nasłonecznienie/lux przewyższa próg), niezależnie od tego czy na zewnątrz jest upał czy nie. 
- **EN:** Modified `is_summer` logic in `calculation.py`. The covers will now close when the inside temperature is too hot and the sun radiation/lux is above the threshold, ignoring the outside temperature condition.
- **PL:** Naprawiono błąd (Anti-Fighting Mechanism) polegający na ponawianiu komendy zamknięcia/otwarcia po tym, jak użytkownik zatrzymał roletę w połowie drogi (poprawna detekcja manual override).
- **EN:** Fixed an issue (Anti-Fighting Mechanism) where the system persistently retried moving the blind if the user manually stopped it midway (proper manual override detection).
- **PL:** Naprawiono nadpisywanie ręcznej blokady – odświeżanie czasowe np. przy zachodzie słońca (`timed_refresh`) respektuje teraz aktywne blokady przycisku na ścianie.
- **EN:** Fixed manual override bypass – timed refreshes (e.g., at sunset) now properly respect active manual wall switch blockades.
- **PL:** Naprawiono omijanie limitów `min_pos` i `max_pos` – od teraz krytyczne stany ochronne (deszcz, wiatr, blokada słońca) poprawnie respektują fizyczne limity zadane przez użytkownika, zamiast w ciemno wymuszać pozycję 0%.
- **EN:** Fixed `min_pos` and `max_pos` bypass – critical protective states (rain, wind, sun block) now properly respect physical limits set by the user instead of blindly forcing the 0% position.
- **PL:** Usunięto kodowanie "na sztywno" nazw encji (sensorów, przełączników, przycisków) w Pythonie. Wdrożono natywny mechanizm tłumaczeń Home Assistant oparty na plikach `pl.json` i `en.json`. 
- **EN:** Removed hardcoded entity names (sensors, switches, buttons) in Python. Implemented native Home Assistant translation mechanism using `pl.json` and `en.json`.
- **PL:** Zmodyfikowano usługę `import_config`, aby parowała zapisane ustawienia z nowymi instancjami po **nazwie urządzenia**, a nie po ukrytym kluczu `entry_id`. Umożliwia to poprawne odtworzenie konfiguracji nawet po całkowitym usunięciu i ponownym dodaniu integracji. Dodano również domyślną nazwę pliku `adaptive_cover_settings.json` dla usługi importu.
- **EN:** Modified `import_config` service to match stored settings with new instances using the **device title** rather than the hidden `entry_id`. This allows restoring configurations properly even after completely removing and re-adding the integration. Added a default filename `adaptive_cover_settings.json` to the import service schema.
