# Blackout-Radar

Überwacht größere Stromausfälle weltweit und meldet sie per Push aufs Handy oder den PC (ntfy) und per E-Mail. Dazu gibt es einen Lagebericht mit Verlauf und Statistik, der immer aktuell im Netz steht.

Das Programm läuft kostenlos alle 5 Minuten bei GitHub. Es braucht keinen eigenen Server und läuft deshalb auch weiter, wenn in Österreich der Strom weg ist.

## Was gemeldet wird

| Gebiet | Meldung | Dringlichkeit |
|---|---|---|
| **Oberösterreich** | sofort bei jedem Hinweis, auch bei kleinen und kurzen Ausfällen | Warnung, ab 15 % Betroffenen Alarm |
| **Österreich** | sofort, sobald rund 15 % des Landes betroffen sind | Alarm |
| **Nachbarländer** | wie Rest der Welt | Warnung |
| **Rest der Welt** | ab 30 Minuten Dauer und rund 500.000 Betroffenen, wenn Strom als Ursache belegt ist | Info |
| **Netzfrequenz Europa** | sofort bei mehr als 200 mHz Abweichung von 50 Hz | Warnung, ab 500 mHz Alarm |

Kleine und kurze Ausfälle außerhalb Oberösterreichs werden nicht gemeldet. Sie stehen im Lagebericht unter "Unter Beobachtung", mit dem Grund, warum keine Meldung kam.

Zu einem laufenden Ereignis kommen weitere Meldungen, wenn sich etwas ändert:

- Ausbreitung auf weitere Gebiete, Einstufung als Blackout
- Messwerte liegen vor (nach ersten Medienberichten)
- Wiederherstellung beginnt, ein Gebiet ist wieder versorgt
- Zwischenstand alle 2 Stunden, bei einem großen Ausfall in Österreich jede Stunde
- Entwarnung mit Gesamtdauer und Reihenfolge der Wiederversorgung

Jede Meldung nennt, wo es begonnen hat, wohin es sich ausgebreitet hat, wo der Strom zuerst zurück ist und wie lange es bisher dauert. Höchstens 4 Meldungen je Ereignis und Stunde.

Beispiel aus dem Planspiel:

```
Update Oberösterreich, Österreich, Tschechien: Wiederherstellung
Seit 03:56 Uhr. Neueste Messwerte von 05:36 Uhr, bis dahin 1 h 40 min ohne Strom. Die Daten kommen verzögert.
• Oberösterreich: 3 Medien berichten, Größe unbekannt
• Österreich: 4 Medien berichten, landesweiter Ausfall laut Schlagzeilen; Stromlast −86 % (1.316 statt 9.400 MW), Stand 05:36
• Tschechien: wieder versorgt seit 05:36 (nach 1 h 40 min, Spitze −33 %)
Verlauf: 03:56 Österreich → 03:56 Tschechien → 04:11 Oberösterreich (Medienbericht)
Zuerst wieder versorgt: Tschechien 05:36
```

## Einrichten

**1. Push aufs Handy (ntfy)**

1. App **ntfy** installieren (Android: Play Store oder F-Droid, iPhone: App Store).
2. In der App auf "+" tippen und das Thema eintragen. Das Thema ist ein langer Zufallsname und wirkt wie ein Passwort: Wer es kennt, kann mitlesen.
3. Am PC geht dasselbe im Browser unter `https://ntfy.sh/app`.

Damit ein Alarm auch nachts durchkommt, in den Benachrichtigungs-Einstellungen des Handys für ntfy erlauben, dass dringende Meldungen "Nicht stören" übergehen dürfen.

**2. Zugangsdaten bei GitHub hinterlegen**

Im Repository unter *Settings → Secrets and variables → Actions → New repository secret*:

| Secret | Inhalt | Nötig für |
|---|---|---|
| `NTFY_TOPIC` | das Thema aus Schritt 1 | Push |
| `NTFY_SERVER`, `NTFY_TOKEN` | Adresse und Zugriffstoken, falls ein eigener ntfy-Server verwendet wird | Push, optional |
| `SMTP_HOST` | Postausgangsserver, z. B. `smtp.example.org` | E-Mail |
| `SMTP_PORT` | `587` (Standard) oder `465` | E-Mail, optional |
| `SMTP_USER`, `SMTP_PASSWORD` | Anmeldung am Postausgangsserver | E-Mail |
| `MAIL_TO` | Empfänger, mehrere mit Komma getrennt | E-Mail |
| `MAIL_FROM` | Absender, falls er vom Benutzernamen abweicht | E-Mail, optional |

Zugangsdaten gehören nie in `config.toml`, weil das Repository öffentlich ist.

**3. Einschalten**

Sobald die Datei `.github/workflows/monitor.yml` im Hauptzweig `main` liegt, ist der Radar eingeschaltet. Die erste Meldung "Blackout-Radar ist aktiv" kommt mit dem ersten Lauf, sobald ein Kanal eingerichtet ist. GitHub soll den Lauf alle 5 Minuten starten, tut das aber nur "nach Möglichkeit". Deshalb gehört Schritt 4 dazu.

**4. Taktgeber einschalten**

GitHub startet Zeitpläne nicht verlässlich: Läufe kommen oft nur alle 15 bis 50 Minuten und in neuen Repositories anfangs manchmal gar nicht. Der Taktgeber macht den Radar davon unabhängig. Er ist eine Kette von Läufen: Jedes Glied wartet 5 Minuten, stößt dann das nächste Glied und einen Lauf des Radars an und endet. Während des Wartens ist bei GitHub kein Rechner belegt. Je Runde kommt zum Lauf des Radars nur ein zweiter, wenige Sekunden langer Lauf dazu.

Eingeschaltet wird er mit einer Einstellung im Repository:

1. *Settings → Environments → New environment*, als Name `takt` eintragen, "Configure environment".
2. "Wait timer" ankreuzen, `5` eintragen, "Save protection rules".

Der nächste Lauf des Radars startet die Kette von selbst. Sofort geht es von Hand unter *Actions → Blackout-Radar → Run workflow* mit der Aktion `takt`. In der Liste der Läufe heißen die Glieder "Taktgeber", eines davon steht immer auf "Waiting".

- **Reißt die Kette**, etwa bei einer Störung von GitHub, startet sie der nächste Lauf des Radars neu, egal ob er nach Zeitplan oder von Hand kommt.
- **Ohne Wartezeit läuft die Kette nicht.** Ein Glied, das nicht gewartet hat, bricht ab, statt ohne Pause weiterzumachen.
- **Abschalten:** die Wartezeit entfernen oder die Umgebung `takt` löschen. Die Kette endet dann mit dem nächsten Glied.
- Wartezeiten bietet GitHub in öffentlichen Repositories kostenlos an, in privaten nur mit bezahltem Plan.

## Bedienen

Unter *Actions → Blackout-Radar → Run workflow* gibt es fünf Aktionen:

| Aktion | Wirkung |
|---|---|
| `lauf` | ein normaler Lauf außer der Reihe |
| `test-push` | schickt eine Testmeldung an alle eingerichteten Kanäle |
| `planspiel` | spielt einen Blackout in Österreich im Zeitraffer durch und schickt 16 Meldungen mit dem Vermerk [TEST] |
| `diagnose` | fragt jede Datenquelle einmal ab und zeigt die Antworten im Protokoll |
| `takt` | startet den Taktgeber (Einrichten, Schritt 4). Selten nötig, weil jeder Lauf ihn von selbst startet |

**Lagebericht:** <https://github.com/sebastianeder09/blackout-radar/blob/state/status.md>

Jede Meldung führt per Antippen dorthin. Der Bericht zeigt laufende und beendete Ereignisse mit Zeitleiste, Störungen unter Beobachtung, Kennzahlen (Netzfrequenz, Stromlast), Statistik über 24 Stunden bis 90 Tage und den Zustand der Datenquellen. Dieselben Daten liegen maschinenlesbar in `status.json` daneben.

Täglich um 07:00 Uhr kommt eine leise Übersicht. Sie ist zugleich das Lebenszeichen: Bleibt sie aus, läuft die Überwachung nicht mehr.

## Einstellungen

Alle Schwellen stehen in [`config.toml`](config.toml), jeweils mit Erklärung. Ohne Änderung gelten die Standardwerte. Häufige Wünsche:

| Wunsch | Einstellung |
|---|---|
| Kriegsbedingte Ausfälle in der Ukraine nicht melden | `[filter] ignore_areas = ["UA"]` |
| Tägliche Übersicht abschalten | `[daily_summary] enabled = false` |
| Weltweit erst ab 1 Million Betroffenen melden | `[filter] min_affected_people = 1000000` |
| Ganz Österreich so behandeln wie Oberösterreich | `[priority] always_areas = ["AT-4", "AT"]` |

## Datenquellen

| Quelle | Liefert | Verzögerung | Stand der Prüfung |
|---|---|---|---|
| Netzfrequenz (Energy-Charts, Ersatz: netzfrequenzmessung.de, laut Anbieter nur für privaten Gebrauch) | Frequenz im Verbundnetz Kontinentaleuropa, sekundengenau | 1 bis 2 Minuten | live geprüft |
| Stromlast (Energy-Charts, Daten von ENTSO-E) | Verbrauch je Land für Österreich und 9 weitere Länder (DE, CZ, SK, HU, CH, FR, ES, PT, PL) | 2 bis 5 Stunden | live geprüft, Auswertung an 3 echten Großausfällen nachgespielt |
| Medien (Google News) | Schlagzeilen in 6 Sprachen, gezielte Suchen für Oberösterreich und Österreich | je nach Berichterstattung, geschätzt 15 bis 90 Minuten | live geprüft |
| Störmeldungen LINZ NETZ | öffentliche Störungsseite, zählt für Oberösterreich | wenige Minuten | Seite wird gelesen, eine echte Störung war beim Einrichten nicht aktiv |
| IODA (Georgia Tech) | Internet-Ausfälle weltweit | | abgeschaltet, der Dienst war beim Einrichten nicht erreichbar |
| Cloudflare Radar | Internet-Ausfälle mit Ursache | | abgeschaltet, braucht ein eigenes Token, ungeprüft |

### Gegenprobe mit echten Stromausfällen

Die Auswertung der Stromlast wurde mit den echten Werten von drei großen Ausfällen nachgespielt (Iberische Halbinsel, Tschechien, Westbalkan). Die Reihen liegen als Tests im Repository (`tests/data/lastreihen.json`).

| Ausfall | Was die Lastwerte zeigen | Ergebnis der Auswertung |
|---|---|---|
| Portugal, 28.04.2025 | Einbruch um 98 %, Wiederaufbau am Abend | Beginn richtig, Ende um 23 Uhr UTC, so wie das Netz wieder stand |
| Spanien, 28.04.2025 | **keine Werte**, eineinhalb Tage lang | kein Befund, der Lagebericht zeigt "keine neuen Werte seit ..." |
| Tschechien, 04.07.2025 | Einbruch um 28 %, vier Stunden | Beginn und Ende richtig |
| Bosnien und Montenegro, 21.06.2024 | Einbruch um 83 % und 67 %, zwei bis drei Stunden | Beginn und Ende richtig, kein Scheinbefund am Tag danach |
| 8 ruhige Wochen in Österreich und Deutschland, mit Weihnachten, Neujahr, Dreikönig und 1. Mai | Feiertage und Wochenenden | kein Befund |

In die ruhigen Wochen wurden außerdem 1.200 gedachte Ausfälle eingesetzt: an jedem Tag zu vier Tageszeiten, mit 25, 50 und 95 % weniger Last, 2 und 9 Stunden lang. Als richtig gilt: genau ein Einbruch, Beginn auf eine Stunde und Tiefe auf 8 Prozentpunkte genau, Ende höchstens eineinhalb Stunden zu spät. Nachrechnen: `python3 -m tests.gegenprobe` (dauert einige Minuten).

| Ruhige Wochen | Fälle | Richtig | Ungenau |
|---|---|---|---|
| Österreich, November 2026 | 312 | 312 | |
| Deutschland, November 2026 | 312 | 312 | |
| Österreich, um den 1. Mai 2026 | 216 | 205 | 11, alle am Feiertag oder am Abend davor |
| Österreich, Weihnachten 2025 bis Dreikönig 2026 | 360 | 348 | 12, alle mit 25 % weniger Last rund um die Feiertage |

An gewöhnlichen Tagen stimmen Beginn, Tiefe und Ende. Ungenau wird es rund um Feiertage, siehe Grenzen.

Italien und Slowenien werden nicht überwacht: Ihre Lastwerte waren bei der Prüfung lückenhaft (einzelne Viertelstunden und die neuesten Werte nur zum Teil gemeldet).

## Grenzen

- **Kein Messnetz für Stromausfälle.** Es gibt weltweit keine offene Echtzeit-Quelle für Stromausfälle. Das Programm kombiniert Indizien. Betroffenenzahlen sind grobe Schätzungen.
- **Medienberichte** belegen, dass etwas passiert ist, aber weder Dauer noch Ende. Ein Ausfall, der nur aus Medien bekannt ist, bekommt deshalb eine Meldung "(laut Medien)" und keine Entwarnung.
- **Schlagzeilen** entscheiden, ob ein Bericht zählt. Vorsorge, Übungen, Warnungen und Aufarbeitung werden aussortiert, im Deutschen zählt das Wort "Blackout" allein nicht. Für Oberösterreich genügt ein Bericht, dessen Schlagzeile einen Ort in Oberösterreich nennt. Nennt sie keinen Ort, braucht es ein zweites Medium. Ganz ausschließen lassen sich Fehlalarme und übersehene Berichte damit nicht.
- **Lastdaten kommen 2 bis 5 Stunden verzögert**, je nach Land. Die Zeiten in den Meldungen stimmen, aber Wiederherstellung und Entwarnung erfährt man entsprechend später. Im Ernstfall sind Radio (ORF) und Behörden schneller.
- **Lastdaten können bei einem großen Ausfall ganz ausbleiben.** In Spanien meldete der Netzbetreiber am 28.04.2025 ab Beginn des Ausfalls eineinhalb Tage lang keine Werte. Dann gibt es von dieser Quelle weder Bestätigung noch Entwarnung, die Meldungen stützen sich auf Netzfrequenz und Medien. Der Lagebericht zeigt in so einem Fall "keine neuen Werte seit ..." statt eines alten, normal aussehenden Werts. Ausbleibende Werte allein sind kein Beleg für einen Ausfall.
- **Kleine und kurze Einbrüche** sieht die Stromlast nicht: Ein Befund braucht mindestens 20 % weniger Last als an vergleichbaren Tagen, über mindestens zwei Werte. Als beendet gilt ein Einbruch, wenn die Last wieder bis auf 10 % am üblichen Wert liegt.
- **Feiertage kennt das Programm nicht.** Ein Feiertag allein löst keinen Befund aus (geprüft an Weihnachten, Neujahr, Dreikönig und 1. Mai). Fällt ein Ausfall aber auf einen Feiertag oder einen Tag direkt davor oder danach, sind Tiefe und Ende aus den Lastdaten ungenau: Die Entwarnung kann einen halben Tag zu spät kommen, und ein Einbruch um ein Viertel kann unerkannt bleiben.
- **Verlauf innerhalb Österreichs:** Gemessen wird je Land. Welches Bundesland zuerst wieder Strom hat, lässt sich aus offenen Daten nicht ablesen. Für Oberösterreich gibt es nur Medienberichte und die Störmeldungen der LINZ NETZ (Linz und Umgebung).
- **Wann das Netz wieder läuft**, kann niemand vorhersagen. Die Meldung nennt bei einem Blackout in Österreich den Richtwert der APG aus Simulationen (2021): im besten Fall etwa 10 Stunden, längstens 20 bis 30 Stunden ([ORF](https://orf.at/stories/3230171/)). Eine Studie für das Parlament (2022) nennt 10 bis 24 Stunden bis zu einem voll versorgten Übertragungsnetz ([Trending Topics](https://www.trendingtopics.eu/blackout-oesterreich-studie/)).
- **GitHub** startet geplante Läufe nur "nach Möglichkeit": oft spät, selten oder in neuen Repositories gar nicht. Deshalb gibt es den Taktgeber (Einrichten, Schritt 4). Auch er hängt an GitHub: Bei einer Störung dort kann die Kette reißen, bis der nächste Lauf sie neu startet. Nach einer Lücke von 90 Minuten kommt eine Meldung.
- **Zeitplan bei GitHub:** GitHub schaltet Zeitpläne ab, wenn in einem öffentlichen Repository 60 Tage lang nichts geschieht. Der Ablauf wirkt dem selbst entgegen: Einmal pro Woche bestätigt er seinen Zeitplan, und nach 45 Tagen ohne Änderung setzt er einen Vermerk in den Hauptzweig (`.github/zeitplan-aktiv`). Ob das auf Dauer reicht, zeigt erst die Zeit. Bleibt die tägliche Übersicht aus, lässt sich der Ablauf unter *Actions → Blackout-Radar* mit "Enable workflow" wieder einschalten.
- **ntfy.sh** begrenzt die kostenlose Nutzung je Absender-Adresse, und GitHub-Läufe teilen sich Adressen mit anderen Nutzern. Eine abgewiesene Meldung wird bei den nächsten Läufen erneut versucht, bis zu 12 Stunden lang. E-Mail ist der zweite Weg. Wer das ausschließen will, betreibt einen eigenen ntfy-Server (`NTFY_SERVER`).
- **Google News** bietet die Suche als RSS für Feed-Leser an, ohne Zusage. Fällt eine Quelle 3 Stunden aus, kommt eine Meldung.
- **Öffentlich:** Repository, Lagebericht und Protokolle sind für jeden lesbar. Zugangsdaten stehen nur in den GitHub-Secrets und werden aus Fehlertexten entfernt.

## Eigener Rechner statt GitHub

Das Programm braucht nur Python ab 3.11, keine weiteren Pakete.

```bash
git clone https://github.com/sebastianeder09/blackout-radar.git
cd blackout-radar
cp .env.example .env          # Zugangsdaten eintragen
set -a; . ./.env; set +a
python3 -m blackout_radar daemon
```

Weitere Befehle: `run` (ein Lauf), `run --dry-run` (nichts verschicken, nur anzeigen), `status`, `test-push`, `simulate`, `probe` (Diagnose der Datenquellen), `probe --only replay` (lädt die Lastwerte der echten Ausfälle neu und spielt sie durch). Der Zustand liegt dann unter `data/`. Ein Rechner im eigenen Haus fällt bei einem Stromausfall allerdings mit aus.

## Aufbau

| Teil | Aufgabe |
|---|---|
| `blackout_radar/collectors/` | Datenquellen, jede liefert Signale je Gebiet |
| `blackout_radar/engine.py` | fasst Signale zu Ereignissen zusammen und entscheidet, was gemeldet wird |
| `blackout_radar/notify.py` | Versand über ntfy und E-Mail mit Wiederholung |
| `blackout_radar/report.py` | Lagebericht, Statistik, tägliche Übersicht |
| `blackout_radar/simulate.py` | Planspiel |
| `blackout_radar/takt.py` | Taktgeber: die Kette von Läufen bei GitHub und ihre Sicherungen |
| `tests/` | Tests, laufen ohne Netz: `python3 -m unittest discover -s tests -t .` |
| `tests/gegenprobe.py` | Gegenprobe der Lastauswertung mit gedachten Ausfällen in echten Reihen: `python3 -m tests.gegenprobe` |
| `.github/workflows/monitor.yml` | Lauf alle 5 Minuten, Zustand im Zweig `state` |
| `.github/workflows/ci.yml` | Tests und Probelauf gegen die echten Datenquellen bei jeder Änderung |

Datenquellen: Energy-Charts (Fraunhofer ISE, Daten von ENTSO-E, CC BY 4.0, energy-charts.info), netzfrequenzmessung.de, Google News, Störmeldungen der LINZ NETZ GmbH.
