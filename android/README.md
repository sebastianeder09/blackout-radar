# Blackout-Radar als Android-App

Die App holt die Meldungen des Radars direkt aufs Handy und zeigt den Lagebericht. Sie braucht weder die ntfy-App noch den Play Store und keinen eigenen Server: Sie hält selbst eine Verbindung zu ntfy.sh offen und bekommt jede Meldung, sobald der Radar sie verschickt.

## Installieren

1. Am Handy diesen Link öffnen: <https://github.com/sebastianeder09/blackout-radar/releases/latest/download/blackout-radar.apk>
2. Die heruntergeladene Datei antippen. Android fragt einmal, ob der Browser Apps installieren darf: erlauben, dann **Installieren**.
3. Die App öffnen und das ntfy-Thema eintragen, also denselben Namen, der als Secret `NTFY_TOPIC` hinterlegt ist. **Einfügen** übernimmt ihn aus der Zwischenablage.
4. Die beiden Rückfragen von Android erlauben: **Benachrichtigungen** und **im Hintergrund laufen** (Ausnahme von der Akku-Optimierung). Ohne die zweite trennt Android die Verbindung, sobald das Handy ruht.

Statt das Thema einzutippen, geht auch ein Link der Form `blackoutradar://abo/<thema>`. Ist noch kein Thema eingerichtet, verbindet die App damit sofort.

Android warnt beim Installieren, weil die App nicht aus dem Play Store kommt. Das ist bei jeder App so, die man selbst herunterlädt.

### Weitere Handys

Die App läuft auf beliebig vielen Handys, alle bekommen dieselben Meldungen. Am eingerichteten Handy: **App → Weitere Handys → App und Thema weitergeben** und die Nachricht per Messenger oder E-Mail schicken. Sie enthält den Download und das Thema. Am anderen Handy die App installieren, die ganze Nachricht kopieren und in der App auf **Einfügen** tippen.

Das Thema wirkt wie ein Passwort: Wer es kennt, kann mitlesen und selbst Meldungen an alle schicken. Deshalb nur an Leute weitergeben, denen man vertraut.

## Was die App kann

| Teil | Inhalt |
|---|---|
| **Lage** | Lagebericht des Radars: laufende und beendete Ereignisse, Kennzahlen, Statistik, Datenquellen. Der letzte Stand bleibt auch ohne Netz lesbar. |
| **Meldungen** | alle empfangenen Meldungen, nach Tagen geordnet |
| **App** | Zustand der Verbindung, Prüfliste der Erlaubnisse, Einstellungen, Probealarm, Weitergabe an weitere Handys, neue Version |

**Alarm:** Ein Alarm (großer Stromausfall in Österreich, schwere Störung der Netzfrequenz) läutet über die Wecker-Lautstärke, also auch bei Lautlos und bei "Nicht stören", solange dort Wecker erlaubt sind (Standard). Auf Wunsch wiederholt sich der Ton, bis man die Meldung öffnet. Warnungen und Meldungen kommen mit dem normalen Benachrichtigungston, die tägliche Übersicht leise. In den Android-Einstellungen der App lässt sich jeder dieser Kanäle einzeln anpassen.

**Wächter:** Etwa alle 15 Minuten prüft die App, ob ihre Verbindung lebt, und baut sie sonst neu auf. Nach einem Funkloch, einem Neustart des Handys oder wenn Android die App beendet hat, holt sie nach, was in der Zwischenzeit gekommen ist. Zugleich schaut sie, ob der Radar selbst noch läuft: Ist der Lagebericht älter als 3 Stunden, kommt ein Hinweis, weil dann auch keine Alarme kämen.

**Uhrzeiten:** Die App zeigt alle Zeiten in österreichischer Zeit, so wie der Radar sie in seinen Meldungen schreibt, auch wenn das Handy auf eine andere Zeitzone gestellt ist.

**Neue Versionen:** Die App fragt zweimal am Tag bei GitHub nach. Gibt es eine neue Version, steht im Tab **App** ein Knopf zum Herunterladen. Thema und Einstellungen bleiben beim Aktualisieren erhalten.

## Grenzen

- **ntfy.sh hebt Meldungen 12 Stunden auf.** War das Handy länger ohne Netz, fehlen ältere Meldungen in der Liste. Der Lagebericht zeigt trotzdem den aktuellen Stand.
- **Stromsparfunktionen der Hersteller.** Samsung, Xiaomi, Huawei und andere beenden Apps zum Teil trotz Ausnahme. Bei Samsung die App unter *Einstellungen → Akku → Hintergrundnutzungslimits* bei "Nie ruhende Apps" eintragen. Anleitungen für jeden Hersteller: <https://dontkillmyapp.com>
- **Dauermeldung.** Android verlangt für Apps, die im Hintergrund auf Meldungen warten, die Anzeige "Blackout-Radar wacht". Sie lässt sich beim Kanal "Verbindung" ausblenden.
- **Der Probealarm** in der App prüft nur Ton und Anzeige am Handy. Den ganzen Weg prüft die Aktion `test-push` des Radars (Actions → Blackout-Radar → Run workflow).

## Für Entwickler

| Teil | Aufgabe |
|---|---|
| `app/src/main/java/…/ListenerService.kt` | Dauerverbindung zu ntfy (`/<thema>/json`), Wiederaufbau mit wachsenden Wartezeiten |
| `app/src/main/java/…/Watchdog.kt` | Wächter über Wecker und JobScheduler, Start nach dem Einschalten |
| `app/src/main/java/…/Sync.kt` | Einrichten und Nachholen verpasster Meldungen (`poll=1`, `since=<letzte Meldung>`) |
| `app/src/main/java/…/Alerts.kt` | Benachrichtigungskanäle und Anzeige |
| `app/src/main/assets/www/` | Oberfläche (HTML, CSS, JavaScript in einer WebView, lädt nichts aus dem Netz) |
| `app/src/debug/` | nur im Testbau: Einrichten per `adb`, unverschlüsselte Verbindung zum nachgestellten Server |
| `test/emulator.sh` | Emulator-Test: fertige App gegen ntfy.sh, Testbau gegen den nachgestellten Server `fake_ntfy.py` mit Testdaten aus dem Planspiel (`fixtures.py`) |
| `test/seite.py` | liest im Emulator, was die App gerade anzeigt, und kann Knöpfe drücken (über die Entwickler-Schnittstelle der WebView) |
| `test/Vorschau.java` | schreibt die Bildschirmfotos verkleinert ins Protokoll und holt sie dort wieder heraus |

Bauen: `cd android && gradle assembleRelease` (Gradle 8.14, JDK 17, Android SDK 35). Tests: `gradle testDebugUnitTest`.

Bei jeder Änderung unter `android/` baut GitHub Actions die App (`.github/workflows/android.yml`), führt die Tests aus und prüft sie in zwei Emulatoren (Android 12 und 15) gegen das echte ntfy.sh: Einrichten per Link, Lagebericht, Alarm, Funkloch, Ruhezustand, hart beendete App und Neustart. Nach dem Zusammenführen in `main` erscheint die neue Fassung unter *Releases*.

Die Bildschirmfotos des Emulators liegen in voller Größe als Artefakt `emulator-api-<Nummer>` beim Lauf. In Pull Requests stehen sie zusätzlich verkleinert im Protokoll (Schritt "Bilder verkleinert ins Protokoll"). So holt man sie heraus:

```sh
gh api repos/sebastianeder09/blackout-radar/actions/jobs/<Nummer des Jobs>/logs > protokoll.txt
java android/test/Vorschau.java lesen protokoll.txt bilder/
```

**Signaturschlüssel:** `keystore/blackout-radar.p12` liegt absichtlich offen im Repository (Passwort `blackout-radar`). Android nimmt ein Update nur an, wenn es mit demselben Schlüssel signiert ist. Ein geheimer Schlüssel müsste als Secret hinterlegt werden und schützt nur davor, dass jemand eine gefälschte Fassung baut, die sich als Update installieren lässt. Das setzt voraus, dass man diese Datei selbst aus einer fremden Quelle installiert. Die App kommt nur aus den Releases dieses Repositorys, deshalb überwiegt hier der einfache Betrieb.
