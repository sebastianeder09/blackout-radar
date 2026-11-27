# Blackout-Radar als Android-App

Die App holt die Meldungen des Radars direkt aufs Handy und zeigt den Lagebericht. Sie braucht weder die ntfy-App noch den Play Store und keinen eigenen Server: Sie hält selbst eine Verbindung zu ntfy.sh offen und bekommt jede Meldung, sobald der Radar sie verschickt. Bleibt eine Meldung dort aus, holt die App sie über einen zweiten Weg aus dem Lagebericht bei GitHub.

## Installieren

1. Am Handy diesen Link öffnen: <https://github.com/sebastianeder09/blackout-radar/releases/latest/download/blackout-radar.apk>
2. Die heruntergeladene Datei antippen. Android fragt einmal, ob der Browser Apps installieren darf: erlauben, dann **Installieren**.
3. Die App öffnen und das ntfy-Thema eintragen, also denselben Namen, der als Secret `NTFY_TOPIC` hinterlegt ist. **Einfügen** übernimmt ihn aus der Zwischenablage.
4. Die beiden Rückfragen von Android erlauben: **Benachrichtigungen** und **im Hintergrund laufen** (Ausnahme von der Akku-Optimierung). Ohne die zweite trennt Android die Verbindung, sobald das Handy ruht.

Statt das Thema einzutippen, geht auch ein Link der Form `blackoutradar://abo/<thema>`. Ist noch kein Thema eingerichtet, verbindet die App damit sofort.

Android warnt beim Installieren, weil die App nicht aus dem Play Store kommt. Das ist bei jeder App so, die man selbst herunterlädt.

### Weitere Handys

Die App läuft auf beliebig vielen Handys, alle bekommen dieselben Meldungen. Am eingerichteten Handy: **App → Weitere Handys → App und Thema weitergeben** und die Nachricht per Messenger oder E-Mail schicken. Sie enthält den Download und das Thema. Am anderen Handy die App installieren, die ganze Nachricht kopieren und die App öffnen: Sie erkennt die Nachricht und trägt das Thema selbst ein, dort nur noch auf **Verbinden** tippen. Dafür sieht die App in die Zwischenablage, solange noch kein Thema eingerichtet ist, und übernimmt daraus nur ihren eigenen Link. Alles andere lässt sie liegen. Klappt das auf einem Handy nicht, holt **Einfügen** die Nachricht.

Das Thema wirkt wie ein Passwort: Wer es kennt, kann mitlesen und selbst Meldungen an alle schicken. Deshalb nur an Leute weitergeben, denen man vertraut.

## Was die App kann

| Teil | Inhalt |
|---|---|
| **Lage** | Lagebericht des Radars: laufende und beendete Ereignisse, Kennzahlen, Statistik, Datenquellen. Der letzte Stand bleibt auch ohne Netz lesbar. |
| **Meldungen** | alle empfangenen Meldungen, nach Tagen geordnet |
| **App** | Zustand der Verbindung, Prüfliste der Erlaubnisse, Einstellungen, Probealarm, Weitergabe an weitere Handys, neue Version |

**Alarm:** Ein Alarm (großer Stromausfall in Österreich, schwere Störung der Netzfrequenz) läutet über die Wecker-Lautstärke, also auch bei Lautlos und bei "Nicht stören", solange dort Wecker erlaubt sind (Standard). Auf Wunsch wiederholt sich der Ton, bis man die Meldung öffnet. Warnungen und Meldungen kommen mit dem normalen Benachrichtigungston, die tägliche Übersicht leise. In den Android-Einstellungen der App lässt sich jeder dieser Kanäle einzeln anpassen.

**Wächter:** Etwa alle 15 Minuten prüft die App, ob ihre Verbindung lebt, und baut sie sonst neu auf. Nach einem Funkloch, einem Neustart des Handys oder wenn Android die App beendet hat, holt sie nach, was in der Zwischenzeit gekommen ist. Zugleich schaut sie, ob der Radar selbst noch läuft: Ist der Lagebericht älter als 3 Stunden, kommt ein Hinweis, weil dann auch keine Alarme kämen.

**Notweg:** Der Radar führt im Lagebericht bei GitHub, welche Meldungen er verschickt hat. Die App vergleicht das etwa alle 15 Minuten mit dem, was über ntfy angekommen ist. Hat sie keine Verbindung zu ntfy, sieht sie etwa alle 5 Minuten nach. Fehlt eine Meldung, holt die App sie aus dem Lagebericht und meldet sich selbst, mit derselben Dringlichkeit wie über ntfy. In der Liste trägt die Meldung dann das Kennzeichen „Notweg“ und den Grund: Der Radar wurde sie bei ntfy nicht los, ntfy war vom Handy aus nicht erreichbar, oder das Thema am Handy stimmt nicht mit dem des Radars überein. Kommt dieselbe Meldung später doch noch über ntfy, ersetzt sie den Eintrag und läutet nicht noch einmal. Ein Alarm hängt damit nicht mehr an ntfy allein.

**Europa:** Der Radar läuft in den USA, seine Messquellen stehen in Europa. Antwortet keine von ihnen mehr, zeigt der Tab **Lage** das ganz oben: Dann heißt „nichts erkannt“ nicht mehr „alles in Ordnung“.

**Einrichten ohne Netz:** Ist ntfy.sh beim Einrichten nicht erreichbar, merkt sich die App das Thema und verbindet sich, sobald das Netz da ist. Die Meldungen der letzten 12 Stunden holt sie dann nach. Sie kommen still in die Liste, weil sie schon älter sind. Alles, was ab dem Einrichten kommt, läutet wie gewohnt.

**Uhrzeiten:** Die App zeigt alle Zeiten in österreichischer Zeit, so wie der Radar sie in seinen Meldungen schreibt, auch wenn das Handy auf eine andere Zeitzone gestellt ist.

**Neue Versionen:** Die App fragt zweimal am Tag bei GitHub nach. Gibt es eine neue Version, steht im Tab **App** ein Knopf zum Herunterladen. Thema und Einstellungen bleiben beim Aktualisieren erhalten.

## Grenzen

- **ntfy.sh hebt Meldungen 12 Stunden auf.** War das Handy länger ohne Netz, fehlen ältere Meldungen in der Liste. Der Lagebericht zeigt trotzdem den aktuellen Stand.
- **Der Notweg ist langsamer als der Push.** Meist dauert es einige Minuten, im ungünstigen Fall rund 20: Der Radar schreibt den Lagebericht alle 5 Minuten, die App sieht alle 15 Minuten nach. Er braucht Internet am Handy und einen Radar, der läuft. Meldungen von vor dem Einrichten und Meldungen, die älter als knapp 12 Stunden sind, holt er nicht. Solange der Radar seine Meldungen noch nicht im Lagebericht führt, steht im Tab **App** beim Notweg „wartet auf den Radar“.
- **Stromsparfunktionen der Hersteller.** Samsung, Xiaomi, Huawei und andere beenden Apps zum Teil trotz Ausnahme. Bei Samsung die App unter *Einstellungen → Akku → Hintergrundnutzungslimits* bei "Nie ruhende Apps" eintragen. Anleitungen für jeden Hersteller: <https://dontkillmyapp.com>
- **Dauermeldung.** Android verlangt für Apps, die im Hintergrund auf Meldungen warten, die Anzeige "Blackout-Radar wacht". Sie lässt sich beim Kanal "Verbindung" ausblenden.
- **Der Probealarm** in der App prüft nur Ton und Anzeige am Handy. Den ganzen Weg prüft die Aktion `test-push` des Radars (Actions → Blackout-Radar → Run workflow).

## Für Entwickler

| Teil | Aufgabe |
|---|---|
| `app/src/main/java/…/ListenerService.kt` | Dauerverbindung zu ntfy (`/<thema>/json`), Wiederaufbau mit wachsenden Wartezeiten |
| `app/src/main/java/…/Watchdog.kt` | Wächter über Wecker und JobScheduler, Abgleich mit dem Lagebericht, Start nach dem Einschalten |
| `app/src/main/java/…/Fallback.kt` | Notweg: vergleicht die Meldungen des Radars aus `status.json` (Schlüssel `notices`) mit dem, was über ntfy ankam, und zeigt Fehlendes selbst an |
| `app/src/main/java/…/Sync.kt` | Einrichten und Nachholen verpasster Meldungen (`poll=1`, `since=<letzte Meldung>`), dazu die Vorgeschichte nach einem Einrichten ohne Netz |
| `app/src/main/java/…/Alerts.kt` | Benachrichtigungskanäle und Anzeige |
| `app/src/main/assets/www/` | Oberfläche (HTML, CSS, JavaScript in einer WebView, lädt nichts aus dem Netz) |
| `app/src/main/res/drawable/ic_launcher_*.xml` | App-Symbol als Vektor: heller Grund, Oval mit Verlauf von Grau nach Blau, darin der Schriftzug des Logos mit dem Blitz an der Stelle des Bindestrichs. Die Buchstaben sind Pfade (aus Liberation Sans Bold), weil ein Vektorbild von Android keine Schrift kennt. Dasselbe Zeichen steht als `LOGO_BIG` in `assets/www/app.js`, für die Kopfzeile gibt es dort das kleine `LOGO` ohne Schrift |
| `app/src/debug/` | nur im Testbau: Einrichten per `adb` mit Rückmeldung, wie es ausging, Abgleich mit dem Lagebericht auf Zuruf, weitergegebene Nachricht in die Zwischenablage legen, unverschlüsselte Verbindung zum nachgestellten Server, absichtlicher Absturz für die Gegenprobe im Emulator-Test |
| `test/emulator.sh` | Emulator-Test: fertige App gegen ntfy.sh, Testbau gegen den nachgestellten Server `fake_ntfy.py` mit Testdaten aus dem Planspiel (`fixtures.py`) |
| `test/fake_ntfy.py` | stellt ntfy, den Lagebericht und den Radar nach. Dahinter läuft der echte Versand des Radars (`blackout_radar/notify.py`) mit seinem Postausgang, Störungen lassen sich schalten: Radar erreicht ntfy nicht, Handy erreicht ntfy nicht, anderes Thema |
| `test/seite.py` | liest im Emulator, was die App gerade anzeigt, und kann Knöpfe drücken (über die Entwickler-Schnittstelle der WebView) |
| `test/Vorschau.java` | schreibt die Bildschirmfotos verkleinert ins Protokoll, holt sie dort wieder heraus und vergleicht zwei Bilder |

Bauen: `cd android && gradle assembleRelease` (Gradle 8.14, JDK 17, Android SDK 35). Tests: `gradle testDebugUnitTest`.

Bei jeder Änderung unter `android/` baut GitHub Actions die App (`.github/workflows/android.yml`), führt die Tests aus und prüft sie in zwei Emulatoren (Android 12 und 15) gegen das echte ntfy.sh: Einrichten per Link, Lagebericht, Alarm, Funkloch, Ruhezustand, hart beendete App, Neustart und Weitergeben. Der Testbau wird zuerst so eingerichtet wie ein weiteres Handy: Die weitergegebene Nachricht liegt in der Zwischenablage, das Thema muss beim Öffnen von selbst im Feld stehen, und ein Tipp auf „Verbinden“ muss genügen. Danach zeigt er einen nachgestellten Blackout und wird einmal ohne Netz eingerichtet: Die älteren Meldungen müssen danach still in der Liste stehen. Den Notweg prüft der Testbau in fünf Lagen: Der Radar wird eine Meldung bei ntfy nicht los, er stellt sie später verspätet zu, er schickt sie an ein anderes Thema, eine Meldung kommt wie gewohnt an, und ntfy fällt für das Handy aus. In der letzten Lage stößt niemand den Abgleich an, die App muss von selbst alarmieren. Jede Meldung muss genau einmal läuten. Zwei Bildvergleiche zeigen, dass die Anzeige einer Änderung von selbst folgt. Am Ende fragt der Lauf Android, ob die App abgestürzt oder hängen geblieben ist, und prüft mit einem absichtlichen Absturz des Testbaus, dass diese Frage auch anschlägt. Nach dem Zusammenführen in `main` erscheint die neue Fassung unter *Releases*.

Die Bildschirmfotos des Emulators liegen in voller Größe als Artefakt `emulator-api-<Nummer>` beim Lauf. In Pull Requests stehen sie zusätzlich verkleinert im Protokoll (Schritt "Bilder verkleinert ins Protokoll"), bei einem fehlgeschlagenen Lauf auch sonst. Dann zeigt der Schritt "Protokoll des nachgestellten Servers" außerdem, welche Anfragen der App dort angekommen sind. So holt man die Bilder heraus:

```sh
gh api repos/sebastianeder09/blackout-radar/actions/jobs/<Nummer des Jobs>/logs > protokoll.txt
java android/test/Vorschau.java lesen protokoll.txt bilder/
```

**Signaturschlüssel:** `keystore/blackout-radar.p12` liegt absichtlich offen im Repository (Passwort `blackout-radar`). Android nimmt ein Update nur an, wenn es mit demselben Schlüssel signiert ist. Ein geheimer Schlüssel müsste als Secret hinterlegt werden und schützt nur davor, dass jemand eine gefälschte Fassung baut, die sich als Update installieren lässt. Das setzt voraus, dass man diese Datei selbst aus einer fremden Quelle installiert. Die App kommt nur aus den Releases dieses Repositorys, deshalb überwiegt hier der einfache Betrieb.
