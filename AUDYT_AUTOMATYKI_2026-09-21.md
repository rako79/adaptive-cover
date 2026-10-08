# Audyt automatyki Adaptive Cover rako Edition

Data: 21.09.2026. Wersja bazowa: 1.6.0.

## Zakres i status

- [x] Przegląd przepływu: konfiguracja, snapshot danych, harmonogram, arbiter, uczenie, bramki ruchu, usługa HA, potwierdzenie i eksport.
- [x] Przegląd geometrii, klimatu, ochrony pogodowej, nocnego przewietrzania, okien, ręcznego sterowania oraz cyklu start/reload/unload.
- [x] Implementacja potwierdzonych poprawek i testów regresji.
- [x] Dokumentacja PL/EN oraz CHANGELOG.
- [x] Ruff dla całego katalogu integracji i testów.
- [x] Końcowy pełny zestaw testów na HA 2026.7.4 i HA 2026.9.0: po 147 testów zakończonych powodzeniem.
- [ ] Obserwacja fizycznych rolet przez pełny dzień i noc po wdrożeniu w HA.

## Co potwierdził eksport

Źródła: diagnostyka i ustawienia z 21.09.2026, około godziny 16:51 czasu lokalnego.

| Roleta | Pozycja fizyczna | Bieżący cel końcowy | Polecenia w ostatniej godzinie | Limit |
| --- | ---: | ---: | ---: | ---: |
| Karol | 0% | 100% | 11 | 8 |
| Gabi | 0% | 87% | 16 | 8 |
| Sypialnia | 0% | 100% | 16 | 8 |

Ostatnie polecenia integracji miały cel 0% i zostały wysłane około 16:42:05–16:42:06.
Bieżący powód pominięcia otwarcia wynosił `time_delta_not_passed`.
Oczekujące zadania weryfikacji miały opóźnienie 601 sekund. Po upływie blokady
czasowej otwarcie mogło nadal blokować przekroczenie limitu godzinowego.

Historia decyzji Karola zaczynała się dopiero o 16:42:58. Dlatego nie można
udowodnić, która reguła zainicjowała zamknięcia około 16:41–16:42. Nie przypisujemy
tego zdarzenia słońcu, wiatrowi ani retry bez brakujących danych. Testy potwierdzają
błędy wykonawcy i przypadki, w których mogły powstawać powtórzone polecenia;
nie stanowią pełnego odtworzenia nieobecnej historii odczytów.

Cel Gabi 87% wynikał z istniejącej korekty BehavioralLearner względem bazy 100%.
Aktualizacja nie usuwa prawidłowych zapisanych preferencji i nie gwarantuje celu
100% w obecności takiej korekty. Reset uczenia pozostaje osobną operacją użytkownika.

## Naprawione problemy

| Obszar | Problem | Zmienione zachowanie |
| --- | --- | --- |
| Polecenia | Kilka zdarzeń mogło wysłać ten sam cel podczas ruchu | Jedno oczekujące polecenie dla identycznego celu; blokada wywołań jednej rolety |
| Retry | Stary cel pozostawał oczekujący, gdy nową decyzję blokowały limity | Unieważnienie starego retry przed bramkami nowego ruchu |
| Weryfikacja | Czas sprawdzania celu zależał od cooldownu i delta_time | Kontrola po 45 sekundach; potwierdzenie zdarzeniem kończy zadanie wcześniej |
| Ostatnie retry | Zgłoszenie niepowodzenia natychmiast po ostatnim ponowieniu | Osobne oczekiwanie i kontrola wyniku ostatniego polecenia |
| Generacje | Stare zakończenie mogło wyczyścić oczekiwanie nowszego ruchu | Stan kończy wyłącznie zgodna generacja |
| Wznowienie | Upływ czasu nie wyzwalał nowej decyzji bez zmiany encji | Okresowa ocena co minutę; zachowane limity i sterowanie ręczne |
| Współbieżność | Cykle używały współdzielonych pól koordynatora | Serializacja obliczeń oraz izolacja eksportu diagnostyki |
| Eksport | Diagnostyczne przeliczenie mogło zmieniać timery lub kolidować ze zdarzeniami | Eksport nie planuje terminów wykonawczych i nie konsumuje oczekujących zdarzeń |
| Uczenie | Powtórzony raport bez zmiany pozycji mógł wyglądać jak ręczna ingerencja | Sprawdzanie zmiany pozycji; pomijanie stanów przejściowych i niedostępnych |
| Bias | Aktualizacja ponownie tłumiła już zastosowany bias | Korekta pozostałego błędu pozycji; limity fizyczne obowiązują również po uczeniu |
| Silne słońce | Reguła pomijała zapamiętaną histerezę światła | Stan między progami on/off pozostaje stabilny |
| Noc | Małe wahania temperatur przy progach przewietrzania mogły przełączać decyzję | Oddzielne progi rozpoczęcia i zakończenia |
| Harmonogram | Wieczorny restart zakresu przez północ mógł uznać koniec za zaległy | Zamknięcie następnego lokalnego dnia, także przy zmianie czasu |
| Tryb podstawowy | Wynik podstawowy mógł odziedziczyć kod reguły klimatycznej | Kod i ślad odpowiadają wybranemu trybowi; cel nocny nie jest uczony |
| Dane | NaN/Infinity lub stara pozycja encji unavailable mogły trafić do obliczeń | Odrzucanie niepoprawnych danych wejściowych i uczenia |
| JSON | Bool był eksportowany jako 0.0/1.0 | Zachowanie wartości true/false |

## Stabilność nocnego przewietrzania

Start wymaga jednocześnie:

- aktywnego okna czasowego przewietrzania;
- temperatury wewnętrznej powyżej `temp_low + 0,5°C`;
- temperatury zewnętrznej niższej od wewnętrznej o ponad `1°C`.

Po rozpoczęciu funkcja pozostaje aktywna do spadku temperatury wewnętrznej do
`temp_low` albo zmniejszenia różnicy temperatur do `0,2°C`. Reguły bezpieczeństwa
i godzina końcowa nadal mają pierwszeństwo zgodnie z arbitrem. Skok temperatury
zewnętrznej ponad 3°C nadal wymaga pięciu minut potwierdzenia.

Kontaktron nie jest warunkiem uruchomienia przewietrzania. Jego stan `off` jest
zgodny z używaniem drugiej, nieopomiarowanej części okna. Stan `on` nadal uruchamia
skonfigurowaną politykę okna.

## Diagnostyka po aktualizacji

Każde zapisane polecenie ma własny snapshot kontekstu: kod i ślad decyzji,
generację cyklu i polecenia, wyzwalacze, pozycję wyjściową i cel, bias oraz
dostępne odczyty temperatury, promieniowania, wiatru i deszczu. Pole `kind`
rozróżnia polecenie początkowe, retry i dry run. Zmiana późniejszej decyzji nie
zmienia zapisanej przyczyny wcześniejszego polecenia.

Historia nadal jest ograniczona i przechowywana w pamięci. Restart ją usuwa;
nie zastępuje trwałego rejestratora HA. Rozszerzenie eksportu jest addytywne,
bez zmiany wersji konfiguracji i bez usuwania istniejących pól.

## Weryfikacja

Baza przed zmianami: 110 testów zakończonych powodzeniem. Zestaw po audycie:
147 testów, w tym scenariusze poniżej.

| Środowisko | Wtyczka testowa HA | Wynik |
| --- | --- | --- |
| Python 3.14.5, HA 2026.7.4 | pytest-homeassistant-custom-component 0.13.348 | 147 passed, 10,91 s |
| Python 3.14.5, HA 2026.9.0 | pytest-homeassistant-custom-component 0.13.363 | 147 passed, 13,92 s |
| Ruff: cała integracja i testy | lokalna konfiguracja repozytorium | All checks passed |
| git diff --check | zmienione pliki | bez błędów |

Testy uruchomiono lokalnie na Windows przez istniejący `tests/run_pytest.py`,
który dostarcza zastępniki interfejsów POSIX potrzebne runnerowi HA. To nie jest
test na fizycznym serwerze HA ani zdalny przebieg GitHub Actions. Drugie
środowisko znajduje się w ignorowanym katalogu `.venv/audit-ha202609`.

- Osiem godzin warunków dziennych z eksportu: bazowy cel otwarcia trzech rolet.
- Osiem godzin nocnego przewietrzania: szum temperatury, chwilowe skoki i jedno zakończenie o 06:00.
- Seria dwunastu równoległych żądań identycznego zamknięcia.
- Opóźnione osiągnięcie celu po ostatnim retry oraz unieważnianie starej generacji.
- Upływ blokady 10 minut i limitu godzinowego bez zdarzenia pogodowego.
- Ręczne przejęcie, niezmieniona pozycja, stany opening/closing i niedostępność.
- Ochrona przejścia przez otwarte drzwi i fizyczne limity pozycji po uczeniu.
- Histereza promieniowania i zbieżność korekt BehavioralLearner.
- Harmonogram przez północ i noc zmiany czasu Europe/Warsaw.
- Równoległy eksport i aktualizacja automatyki z oczekującym terminem zamknięcia.
- Testy integracyjne startu, przeładowania, wyładowania, konfiguracji i eksportu na HA.

## Wdrożenie i odbiór na urządzeniach

Zmiany są lokalne w repozytorium. Nie wykonano publikacji release ani zmiany
działającej instalacji Home Assistant. Po wdrożeniu należy obserwować pełny dzień
i noc oraz wyeksportować diagnostykę możliwie szybko po ewentualnym nieoczekiwanym
ruchu. Do odbioru potrzebne są: zgodność poleceń z ich zapisanymi przyczynami,
brak duplikatów podczas ruchu i poprawne wznowienie po ustaniu blokad.

Przegląd i testy nie dowodzą braku wszystkich możliwych błędów ani poprawności
raportowania konkretnego napędu. Weryfikacja fizyczna pozostaje osobnym etapem.
