# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased] - 2026-09-21

### Naprawione
- [Naprawione] Chłodniejsze powietrze zewnętrzne o skonfigurowaną przewagę chłodzenia zwalnia ochronę termiczną oraz ścisłą blokadę słońca, również przy bezpośrednim słońcu. Krótkie otwarcie po takim domknięciu omija tylko odstęp czasowy i cooldown; nadal respektuje limity godzinowe i dobowe, ręczne przejęcie oraz politykę otwartego okna.
- [Naprawione] Identyczne polecenia podczas oczekiwania na ruch nie są powielane; wywołania dla jednej rolety oraz cykle koordynatora są serializowane.
- [Naprawione] Nieaktualne retry jest anulowane również podczas blokady nowego celu przez limity. Weryfikacja następuje po 45 sekundach lub potwierdzeniu napędu, a ostatnie ponowienie jest sprawdzane przed zgłoszeniem niepowodzenia.
- [Naprawione] Okresowe przeliczenie co minutę przywraca sterowanie po wygaśnięciu ograniczeń bez oczekiwania na zmianę czujnika; limity ruchów pozostają aktywne.
- [Naprawione] Eksport diagnostyki nie koliduje z cyklem wykonawczym i nie przejmuje zdarzeń harmonogramu.
- [Naprawione] Powtórzone raporty tej samej pozycji i stany przejściowe nie uruchamiają ręcznego przejęcia ani uczenia. Korekty uczą pozostały błąd i respektują fizyczne limity pozycji.
- [Naprawione] Blokada silnego słońca respektuje histerezę światła. Harmonogram przechodzący przez północ wybiera właściwy dzień zamknięcia, również przy zmianie czasu.
- [Naprawione] Tryb podstawowy nie dziedziczy kodu decyzji klimatycznej; pozycja nocna nie jest traktowana jako komfortowy cel do uczenia.
- [Naprawione] Niedostępne pozycje i niepoprawne liczby nie trafiają do obliczeń. Eksport zachowuje wartości logiczne jako true/false.

### Zmienione
- [Zmienione] Nocne przewietrzanie otrzymało histerezę: start powyżej temp_low + 0,5°C przy różnicy wewnątrz/na zewnątrz ponad 1°C; zatrzymanie przy temp_low lub różnicy nie większej niż 0,2°C. Zachowano pięciominutowe potwierdzanie skoków temperatury ponad 3°C.

### Dodane
- [Dodane] Historia poleceń zawiera snapshot decyzji i jej śladu, generację, wyzwalacze, odczyty, pozycję początkową, cel, bias i rodzaj polecenia. Diagnostyka eksportuje również termin końca ręcznego przejęcia.
- [Dodane] Testy audytu obejmują sekwencje dnia i nocy, limity, duplikaty poleceń, współbieżność, harmonogramy, polityki okna i BehavioralLearner. Szczegóły i wyniki znajdują się w AUDYT_AUTOMATYKI_2026-09-21.md.
- [Dodane] Potwierdzono 150 testów na HA 2026.7.4 i 150 testów na HA 2026.9.0 oraz poprawny wynik Ruff dla całej integracji i testów.

## [Unreleased] - 2026-08-03

### Dodane
- [Dodane] Diagnostyka temperatury zewnętrznej pokazuje wartość surową, pogodową wartość referencyjną, wartość zaakceptowaną, oczekującego kandydata i licznik odrzuconych skoków.

### Zmienione
- [Zmienione] Walidacje HACS i Hassfest uruchamiają się na żądanie, przy `push` i `pull request`, bez codziennego harmonogramu powodującego powtarzające się powiadomienia e-mail.
- [Zmienione] Workflowy używają `actions/checkout@v5`, zgodnego z runtime Node.js 24 na GitHub Actions.

### Naprawione
- [Naprawione] `strings.json` zawiera pełne pola i opisy konfiguracji automatyki okna, zarówno przy tworzeniu, jak i edycji wpisu, zgodne z konfiguracją oraz tłumaczeniami.
- [Naprawione] Usunięto błędnie zagnieżdżone tłumaczenie harmonogramu z encji statusu algorytmu w wersjach PL i EN.
- [Naprawione] Integracja deklaruje `CONFIG_SCHEMA` właściwy dla konfiguracji wyłącznie przez wpisy konfiguracyjne, wymagany przez Hassfest.
- [Naprawione] Krótkie błędne skoki wspólnego czujnika temperatury zewnętrznej z około `19°C` do `7,1°C` lub `6,5°C` nie przełączają już rolet między ochroną przed zimnem `0%` i nocnym przewietrzaniem `40/41%`.
- [Naprawione] Duża zmiana temperatury przekraczająca `3°C` wymaga pięciu minut potwierdzenia; przy pierwszym odczycie po restarcie filtr może użyć bieżącej temperatury encji pogodowej jako bezpiecznej wartości referencyjnej.
- [Naprawione] Decyzja `night_mode` używa po zachodzie skonfigurowanej pozycji nocnej zamiast zachowywać dzienny cel `100%`, który powodował dodatkowe otwarcie przed przejściem do nocnego przewietrzania.
- [Naprawione] Dodano testy nocnych sekwencji `19,7 -> 7,1 -> 19,7°C`, utrzymującej się zmiany, pierwszego błędnego odczytu po restarcie oraz pozycji trybu nocnego; pełny zestaw obejmuje `110` testów.

## [Unreleased] - 2026-08-02

### Zmienione
- [Zmienione] BehavioralLearner zapisuje preferencje wyłącznie podczas aktywnego harmonogramu automatyki komfortowej.
- [Zmienione] Wersja ochrony danych BehavioralLearner została podniesiona do `4`; istniejące korekty utworzone przez ruchy spoza harmonogramu lub błędne źródło temperatury są jednorazowo zerowane z zachowaniem czasu ostatniego bezpośredniego słońca.
- [Zmienione] Diagnostyka klimatu pokazuje teraz `low_light`, `is_summer`, `is_winter`, `temperature_source` i dostępność czujnika pokojowego, aby rozdzielić prognozę od aktualnych warunków i jakości wejść.

### Naprawione
- [Naprawione] Słabe promieniowanie i zerowy stres termiczny przywracają pozycję domyślną nawet wtedy, gdy wysoka prognoza temperatury włączyła tryb letni.
- [Naprawione] Brak obecności nie powoduje już pełnego zamknięcia wyłącznie na podstawie prognozy; rzeczywista ochrona zależy od dodatniego stresu termicznego.
- [Naprawione] Usunięto korektę, przez którą bazowy cel `100%` rolety Gabi był obniżany do `94%` po ruchu zarejestrowanym przed startem harmonogramu.
- [Naprawione] Niedostępny skonfigurowany czujnik temperatury pomieszczenia nie jest już zastępowany temperaturą zewnętrzną, która dla rolety Gabi tworzyła fałszywy stres termiczny `100%` i cel `1%`.
- [Naprawione] Eksport diagnostyki nie oznacza już stanów `unknown` i `unavailable` jako dostępnych.
- [Naprawione] Czas zachodu zwracany przez Astral w UTC jest przeliczany na strefę lokalną przed oceną nocnego przewietrzania; rolety nie rozpoczynają go latem dwie godziny za wcześnie.
- [Naprawione] Dodano testy regresji z wartościami eksportów z 02.08.2026, w tym przypadek Gabi oraz konwersję zachodu `18:17 UTC` na `20:17 CEST`; pełny zestaw obejmuje `106` testów.

## [Unreleased] - 2026-07-30

### Zmienione
- [Zmienione] Ochrona przed chłodem używa histerezy `1°C`: aktywuje się poniżej skonfigurowanego progu i pozostaje aktywna do osiągnięcia progu zwolnienia.
- [Zmienione] BehavioralLearner jednorazowo usuwa korekty utworzone przez dawny błąd rozpoznawania własnych ruchów, zachowując znacznik ostatniego bezpośredniego słońca.
- [Zmienione] Diagnostyka pokazuje aktywność i oba progi ochrony przed chłodem oraz czas ostatniego fizycznego polecenia każdej rolety.

### Naprawione
- [Naprawione] Koniec nocnego przewietrzania ustawia skonfigurowaną pozycję nocną zamiast bieżącego celu geometrii lub klimatu; ta sama decyzja nadrabia pominięty termin po restarcie.
- [Naprawione] Pośredni raport pozycji ze stanem `open` lub `closed`, wysłany podczas ruchu zleconego przez integrację, nie jest już uznawany za ręczną zmianę.
- [Naprawione] Późny, powtórzony raport osiągniętej pozycji jest porównywany z ostatnim fizycznym celem, a nie z nowszą kalkulacją automatyki.
- [Naprawione] Wahania temperatury wokół progu ochrony przed chłodem nie przełączają już rolet między pozycją zamknięcia i nocnego przewietrzania.
- [Naprawione] Dodano testy regresji odtwarzające różne pozycje rolet o 06:00, fałszywe ręczne przejęcie podczas własnego ruchu i oscylację temperatury wokół `16°C`; pełny zestaw obejmuje `97` testów.

## [Unreleased] - 2026-07-29

### Dodane
- [Dodane] Wprowadzono modele `RefreshTrigger`, `PendingRefreshes`, `CoverTarget` i `MovementResult`, które nadają zdarzeniom oraz wykonaniu poleceń jawny stan i rosnącą generację.
- [Dodane] Dodano `ScheduleController` oraz wspólny resolver źródeł czasu z diagnostyką źródła, wartości surowej i powodu użycia fallbacku.
- [Dodane] Diagnostyka pokazuje oczekujące, aktywne i ostatnio wykonane przyczyny odświeżenia, generację cyklu oraz sposób wyznaczenia końca harmonogramu.
- [Dodane] Dodano testy runtime wykonawcy ruchów, BehavioralLearner, kolejki zdarzeń, timerów, fallbacków czasu, zmian DST oraz pełnego cyklu życia na Home Assistant `2026.7.4`; zestaw obejmuje 88 testów.
- [Dodane] Dodano testy integracyjne startu, przeładowania, wyładowania, migracji, eksportów, anulowania retry i zatrzymania nieaktualnej partii dwóch rolet.

### Zmienione
- [Zmienione] Podniesiono wersję integracji do `1.6.0` i zaktualizowano deklarowane wsparcie do Home Assistant `2026.7+` oraz Python `3.14.2+`.
- [Zmienione] Podzielono logikę na wyspecjalizowane moduły, w tym `coordinator_pipeline.py`; `coordinator.py` ma 190 linii i odpowiada wyłącznie za składanie oraz uruchamianie warstw runtime.
- [Zmienione] Reguły klimatyczne korzystają z jednego niezmiennego snapshota wejść i wspólnego arbitra kandydatów, bez bezpośrednich odczytów `hass.states`.
- [Zmienione] Zregenerowano `poetry.lock` dla Home Assistant `2026.7.4`, Python `>=3.14.2,<3.15` i Poetry `2.2.1`.
- [Zmienione] Usunięto monolityczny `calculation.py`; geometria i reguły klimatyczne mają oddzielnych właścicieli.
- [Zmienione] Wszystkie polecenia osłon, w tym retry i powrót po ręcznym przejęciu, przechodzą przez jedyną bramkę usług domeny `cover` w `movement.py`.
- [Zmienione] Platformy encji korzystają ze znormalizowanych opcji, a encje czasu używają `translation_key` w wersjach PL i EN.
- [Zmienione] Ujednolicono metadane projektu, autora forka, repozytorium, licencję MIT i odnośniki wydań w `pyproject.toml`.

### Naprawione
- [Naprawione] Koniec nocnego wietrzenia oraz pominięty termin po restarcie uruchamiają świeżą decyzję; deszcz, wiatr i polityka okna nie mogą zostać nadpisane pozycją nocną.
- [Naprawione] Zdarzenia przychodzące podczas trwającego `await` nie są zerowane przez starszy cykl, a nowsza generacja zatrzymuje wysyłanie pozostałych nieaktualnych celów do grupy rolet.
- [Naprawione] Retry porównuje finalny cel po korekcie BehavioralLearner, unieważnia starsze generacje i pozwala deszczowi oraz wiatrowi ominąć limity ruchu.
- [Naprawione] Niedostępna lub błędna encja końca harmonogramu przechodzi kolejno na jawną godzinę oraz zachód słońca z przesunięciem.
- [Naprawione] Priorytety ograniczeń pozycji w `decision_trace` odpowiadają rzeczywistej kolejności wykonania.
- [Naprawione] Termin harmonogramu zachowuje aktywne fizyczne ograniczenie minimalnej lub maksymalnej pozycji zamiast zastępować je nieograniczoną pozycją nocną.
- [Naprawione] Zwykły koniec harmonogramu jest jawnym kandydatem `timed_end`: nadpisuje decyzje komfortowe, ale pozostaje poniżej aktualnych zabezpieczeń.
- [Naprawione] Koordynator przekazuje `config_entry` do `DataUpdateCoordinator`, zgodnie z kontraktem Home Assistant wymaganym od wersji 2026.8.
- [Naprawione] Eksport diagnostyki pokazuje osobne rozstrzygnięcia początku i końca harmonogramu oraz poprawne identyfikatory encji temperatur zamiast wartości w polu `outside_temperature_entity`.
- [Naprawione] Przycisk resetu ręcznego przejęcia nie raportuje sukcesu, dopóki napęd nie potwierdzi pozycji docelowej.
- [Naprawione] Niestandardowe czasy z `DurationSelector` są normalizowane do minut i pozostają widoczne w encji wyboru zamiast zmieniać się pozornie na 60 minut.
- [Naprawione] Usunięto wymuszony import platformy diagnostycznej z `__init__.py`, który mógł wywoływać ostrzeżenie o blokującym `import_module` podczas startu HA.

## [Unreleased] - 2026-07-26

### Dodane
- [Dodane] Utworzono szczegółowy `PLAN_STABILIZACJI_I_MODULARYZACJI.md`, który porządkuje naprawy kolejności wykonania, testy runtime oraz etapowy podział koordynatora na mniejsze moduły.

## [Unreleased] - 2026-07-16

### Zmienione
- [Zmienione] Podniesiono wersję integracji do `1.5.6`.

### Naprawione
- [Naprawione] Encja `Przesunięcie zachodu (Zamykanie)` jest ponownie zawsze ładowana i nie pozostaje wyszarzona po ustawieniu jawnej godziny zakończenia lub encji końca.
- [Dodane] Dodano test regresyjny sprawdzający bezwarunkowe utworzenie encji przesunięcia zachodu.

## [Unreleased] - 2026-07-15

### Zmienione
- [Zmienione] Podniesiono wersję integracji do `1.5.5` po analizie diagnostyki z całodziennego działania Home Assistant 2026.7.

### Naprawione
- [Naprawione] Zastąpiono ręczne nasłuchiwanie `EVENT_HOMEASSISTANT_STARTED` helperem `async_at_started`, który poprawnie obsługuje zarówno pełny start HA, jak i przeładowanie integracji już podczas pracy systemu.
- [Naprawione] `runtime_initialized` nie pozostaje już stale `false`; po zakończeniu inicjalizacji integracja wykonuje aktualny cel zamiast ograniczać się do samych obliczeń.
- [Naprawione] Rolety pozostające fizycznie na `95–100%` otrzymają wyliczoną pozycję nocnego przewietrzania `40–41%`, jeżeli nie blokuje ich okno ani ręczne przejęcie.
- [Dodane] Dodano test regresyjny wymagający użycia bezpiecznego helpera cyklu życia Home Assistant.

## [Unreleased] - 2026-07-14

### Zmienione
- [Zmienione] Podniesiono wersję integracji do `1.5.4` po analizie rzeczywistej sekwencji rozruchowej Home Assistant 2026.7.
- [Zmienione] Ujednolicono priorytety wykonania: deszcz i wiatr omijają harmonogram, ręczne przejęcie, cooldown i limity ruchów, a pozostałe zabezpieczenia omijają harmonogram z zachowaniem ochrony silnika.
- [Zmienione] Uporządkowano pierwszeństwo źródeł czasu; `start_time` działa bez encji Workday, a `close_sunset_offset` jest dostępny tylko przy zamknięciu solarnym.

### Dodane
- [Dodane] BehavioralLearner zapisuje ostatni czas bezpośredniego nasłonecznienia z ograniczeniem częstotliwości zapisu, dzięki czemu Thermal Hold zachowuje kontekst po restarcie.
- [Dodane] Rozszerzono testy regresyjne o priorytety bezpieczeństwa, pominięte terminy, stany pośrednie silnika, trwałość uczenia, walidację czasu oraz interpolacji.

### Naprawione
- [Naprawione] Zakończenie nocnego wietrzenia wykonuje teraz rzeczywiste zamknięcie rolety do skonfigurowanej pozycji nocnej, niezależnie od późniejszego startu dziennego harmonogramu, z zachowaniem ochrony otwartego okna i aktywnego sterowania ręcznego.
- [Naprawione] Restart między końcem nocnego wietrzenia a startem dziennego harmonogramu nadrabia pominięte zamknięcie zamiast pozostawiać roletę w pozycji przewietrzania.
- [Naprawione] Pierwsze sterowanie odbywa się dopiero po odtworzeniu przełączników `RestoreEntity`, więc automatyka nie czeka na kolejne zdarzenie czujnika po uruchomieniu Home Assistant.
- [Naprawione] Ręczne włączenie automatyki najpierw przelicza aktualny cel i korzysta ze wspólnej ścieżki priorytetów zamiast blokować decyzje bezpieczeństwa własnym sprawdzeniem harmonogramu.
- [Naprawione] Wcześniejsza zmiana godziny końca oraz termin pominięty podczas restartu są wykonywane, zamiast pozostawać za starym zaplanowanym callbackiem.
- [Naprawione] `manual_ignore_intermediate` zatrzymuje obsługę stanów `opening` i `closing` przed uruchomieniem detekcji ręcznego sterowania.
- [Naprawione] Ręczne przejęcie używa stałego terminu końcowego; wariant „do zachodu słońca” nie kończy się w połowie pozostałego czasu.
- [Naprawione] BehavioralLearner nie uczy się z ręcznych zmian powstałych przy aktywnych decyzjach bezpieczeństwa.
- [Naprawione] Zmiana encji pogody nie zwraca prognozy zapamiętanej dla poprzedniej encji, gdy nowe źródło jest niedostępne.
- [Naprawione] Niejednoznaczna dzienna godzina końca nocnego przewietrzania nie aktywuje przewietrzania przez cały dzień.
- [Naprawione] Interpolacja obsługuje wartość początkową `0`, odrzuca powtarzające się punkty oraz wartości poza zakresem `0...100`.
- [Naprawione] Niedostępna encja Workday zachowuje bezpieczne założenie dnia roboczego zamiast przełączać harmonogram na weekendowy.
- [Naprawione] Strict Sun Block nie interpretuje już `null`, `unknown` ani `unavailable` z czujnika irradiancji/lux jako silnego słońca; wymaga aktualnego odczytu większego od progu włączenia.
- [Naprawione] Zdarzenia czujników i przejściowe stany przełączników podczas fazy `STARTING` mogą aktualizować obliczenia, ale nie wysyłają poleceń do rolet. Pierwszy ruch następuje dopiero po zdarzeniu pełnego uruchomienia HA i krótkiej stabilizacji encji.
- [Naprawione] Diagnostyka pokazuje stan `runtime_initialized` oraz źródło, wartość, próg i dostępność sygnału Strict Sun Block, co pozwala odróżnić prawdziwe silne słońce od brakującego odczytu.

## [Unreleased] - 2026-07-13

### Zmienione
- [Zmienione] Podniesiono wersję integracji do `1.5.1`, aby wdrożenie poprawki przepływu konfiguracji było jednoznacznie widoczne w Home Assistant i diagnostyce.
- [Zmienione] Przygotowano fork `Adaptive Cover rako Edition` do dystrybucji przez HACS: zaktualizowano nazwę, właściciela, dokumentację, obsługę zgłoszeń, szablony GitHub i release notes.
- [Zmienione] Zachowano domenę `adaptive_cover`, aby aktualizacja nie wymagała migracji istniejących wpisów konfiguracji ani encji Home Assistant.
- [Zmienione] Dokumentacja HACS ostrzega przed równoległą instalacją innego wariantu o tej samej domenie `adaptive_cover`.

### Dodane
- [Dodane] Dodano zasób marki `brand/icon.png` oraz plik `NOTICE.md` z informacją o pochodzeniu kodu, licencji MIT i utrzymaniu forka przez `@rako79`.
- [Dodane] Dodano `PLAN_ROZWOJU.md` z priorytetami przyszłych zmian: strefy olśnienia, panel Lovelace, bezpieczne tryby tymczasowe i arbiter sezonowy.

### Usunięte
- [Usunięte] Usunięto przekierowanie finansowania do poprzedniego maintenera.
- [Usunięte] Usunięto z planu rozwoju obsługę dwuosiowych żaluzji.

### Naprawione
- [Naprawione] Przepływ opcji korzysta z `config_entry` udostępnianego przez Home Assistant dopiero po inicjalizacji, zgodnie z API HA 2026.7; otwarcie przycisku „Konfiguruj” nie kończy się już błędem 500.

## [Unreleased] - 2026-07-12

### Dodane
- [Dodane] Wprowadzono wspólny schemat diagnostyki v4 dla eksportu serwisowego i standardowej diagnostyki Home Assistant, obejmujący wersje środowiska, ścieżkę załadowanego komponentu i stan `ConfigEntry`.
- [Dodane] Dodano ograniczoną historię 50 decyzji i poleceń, ślad oceny reguł, zdrowie koordynatora, czasy odświeżeń, stan cache prognozy oraz szczegółowe metadane zadań retry.
- [Dodane] Diagnostyka pozycji pokazuje błąd względem celu, efektywną tolerancję i jednoznaczne `target_satisfied`.
- [Dodane] Diagnostyka BehavioralLearner pokazuje stan odczytu Store, ostatni błąd, ostatnią korektę użytkownika i czas zaplanowania zapisu.

### Zmienione
- [Zmienione] Podniesiono wersję integracji do `1.5.0`, aby diagnostyka jednoznacznie identyfikowała wdrożenie zawierające schemat v4 i poprawki runtime.
- [Zmienione] Przepisano `README.md` w kompletnych wersjach PL i EN zgodnie z aktualnym działaniem integracji 1.5.0, jej encjami, usługami, priorytetami, zabezpieczeniami i diagnostyką v4.
- [Zmienione] Eksport ustawień używa schematu v4 i zapisuje datę, wersję integracji, wersję HA, strefę czasową, wersję wpisu oraz wynik walidacji opcji.
- [Zmienione] Eksporty domyślnie dodają lokalną datę do nazwy pliku, a pola nazwy i przełączniki daty są aktywne domyślnie w formularzu usługi.
- [Zmienione] Diagnostyka domyślnie wykonuje ograniczone do 30 sekund odświeżenie read-only, które przelicza aktualny stan bez wysyłania poleceń ruchu, oraz rejestruje jego wynik i czas.

### Naprawione
- [Naprawione] Pozycje krańcowe `0%` i `100%` respektują teraz `delta_position`, dzięki czemu urządzenie raportujące np. `97%` nie otrzymuje bez końca poleceń ustawienia `100%`.
- [Naprawione] Weryfikacja i ponowienia ruchu używają tej samej tolerancji pozycji co główna automatyka, co zapobiega seriom zbędnych retry i fałszywemu osiąganiu limitu dobowego.
- [Naprawione] Status rolety jest odświeżany po osiągnięciu celu w granicach tolerancji i nie pozostaje błędnie jako `daily_move_limit` lub wcześniejsze pominięcie.
- [Naprawione] Obliczenia słońca używają `get_astral_observer` zamiast wycofanego `get_astral_location`, usuwając masowe ostrzeżenia kompatybilności przed Home Assistant 2027.7.
- [Naprawione] Zdarzenie zwrotne z silnika używa `delta_position`, więc niedokładna pozycja krańcowa nie jest błędnie rozpoznawana jako ręczne zatrzymanie rolety.
- [Naprawione] Opóźniona weryfikacja pozycji działa jako zadanie tła powiązane z `ConfigEntry`, dlatego oczekiwanie na retry nie blokuje zakończenia startu Home Assistant.
- [Naprawione] Platforma `diagnostics` jest ładowana wraz z pakietem integracji, zamiast wykonywać pierwszy import pliku w pętli zdarzeń Home Assistant.
- [Naprawione] Wersja Home Assistant w diagnostyce jest pobierana z `homeassistant.const`, zgodnie z aktualnym API, dzięki czemu import platformy nie przerywa ładowania całej integracji.

## [Unreleased] - 2026-07-11

### Dodane
- [Dodane] Ukończono trwały `BehavioralLearner`: zapisuje per roleta ograniczone korekty pozycji i temperatury komfortu, odtwarza je po restarcie oraz udostępnia przycisk resetu uczenia.
- [Dodane] Dodano konfigurowalny czas `thermal_hold_duration` i różnicę temperatur `thermal_hold_release_delta` zwalniającą ochronę termiczną.
- [Dodane] Dodano czysty moduł decyzji oraz testy jednostkowe dla nocnego wietrzenia, ochrony termicznej i walidacji ustawień.
- [Dodane] Dodano typowany `DecisionResult` z kodem, priorytetem, uzasadnieniem i wejściami decyzji udostępnianymi w diagnostyce.
- [Dodane] Dodano workflow CI uruchamiający Ruff i testy jednostkowe.

### Zmienione
- [Zmienione] Wszystkie opóźnione retry otrzymują numer generacji, ponownie sprawdzają aktualny cel, automatykę, okno, manual override i limity ruchu oraz są anulowane przy przeładowaniu integracji.
- [Zmienione] Eksport ustawień używa schematu 3, a import pozostaje zgodny ze starszym formatem i odrzuca cały plik przed zmianami, gdy wykryje niespójne opcje.
- [Zmienione] Starsze wpisy `ConfigEntry` są jawnie migrowane do wersji 2 z kompletem znormalizowanych i zwalidowanych opcji.
- [Zmienione] Diagnostyka HA i eksport JSON pokazują trwałe uczenie, cel per roleta, stres termiczny, ostatnie bezpośrednie słońce, bieżący powód statusu i błędy usług.
- [Zmienione] Prognoza pogody jest buforowana przez godzinę, a obliczenia pozycji słońca nie tworzą wielokrotnie tych samych zakresów czasu.
- [Zmienione] Blueprint integracji oznaczono jako legacy dla dodatkowych rolet i usunięto dublowanie encji sterowanych bezpośrednio przez integrację.

### Naprawione
- [Naprawione] `thermal_hold` działa wyłącznie po rzeczywistym bezpośrednim nasłonecznieniu danego okna i zwalnia osłonę, gdy chłodniejsze powietrze zapewnia wystarczające chłodzenie.
- [Naprawione] Globalne promieniowanie nie wymusza już ochrony termicznej w pokojach, których okna pozostają w cieniu.
- [Naprawione] Godzina końca nocnego wietrzenia jest twardą granicą także przed wschodem słońca i uruchamia świeżą decyzję zamiast bezwarunkowego zamknięcia.
- [Naprawione] Włączenie automatyki respektuje politykę otwartego okna, harmonogram, cooldown, limity ruchu i ręczne przejęcie sterowania.
- [Naprawione] Zabezpieczono obliczenia markiz i lameli przed dzieleniem przez zero, `NaN` i wartościami spoza zakresu `0-100%`.
- [Naprawione] Obsłużono brak pozycji i niepełne zdarzenia rolet bez błędnego rozpoznawania manual override.
- [Naprawione] Prędkość wiatru jest normalizowana z `m/s`, `mph` i węzłów do `km/h` przed porównaniem z progiem bezpieczeństwa.
- [Naprawione] Status metody sterowania wraca do `intermediate`, a sensor harmonogramu pokazuje stan rzeczywisty zamiast stałego `Aktywny`.

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
