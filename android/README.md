# Blackout-Radar als Android-App

Die App meldet große Stromausfälle direkt am Handy und zeigt den Lagebericht. Es gibt zwei Wege, sie zu nutzen:

- **Öffentlicher Alarm:** installieren, öffnen, auf **Alarm einschalten** tippen. Die App verbindet sich mit dem öffentlichen Thema dieses Radars und nimmt dort nur an, was der Radar unterschrieben hat. Ein Konto, eine Anmeldung oder ein Thema braucht es nicht.
- **Eigener Radar:** Wer den Radar selbst betreibt ([Hauptseite](../README.md)), verbindet die App mit dem eigenen ntfy-Thema.

Die App braucht weder die ntfy-App noch einen eigenen Server: Sie hält selbst eine Verbindung zu ntfy.sh offen und bekommt jede Meldung, sobald der Radar sie verschickt. Bleibt eine Meldung dort aus, holt die App sie über einen zweiten Weg aus dem Lagebericht bei GitHub.

Anbieter der App ist ASE-IT. [Impressum](../docs/impressum.md) und [Datenschutzerklärung](../docs/datenschutz.md) stehen auch in der App selbst.

## Installieren

1. Am Handy diesen Link öffnen: <https://github.com/sebastianeder09/blackout-radar/releases/latest/download/blackout-radar.apk>
2. Die heruntergeladene Datei antippen. Android fragt einmal, ob der Browser Apps installieren darf: erlauben, dann **Installieren**.
3. Die App öffnen und auf **Alarm einschalten** tippen. Wer einen eigenen Radar betreibt, tippt stattdessen auf **Eigenen Radar verbinden** und trägt das ntfy-Thema ein, also denselben Namen, der als Secret `NTFY_TOPIC` hinterlegt ist. **Einfügen** übernimmt ihn aus der Zwischenablage.
4. Die beiden Rückfragen von Android erlauben: **Benachrichtigungen** und **im Hintergrund laufen** (Ausnahme von der Akku-Optimierung). Ohne die zweite trennt Android die Verbindung, sobald das Handy ruht.

Statt das Thema einzutippen, geht auch ein Link der Form `blackoutradar://abo/<thema>`. Ist noch nichts eingerichtet, verbindet die App damit sofort.

Kam die App als Datei von einem Handy, auf dem sie schon läuft (siehe *Weitere Handys*), entfällt Schritt 3: Sie bringt das Thema mit und richtet sich beim ersten Öffnen selbst ein.

Android warnt beim Installieren, weil die App nicht aus dem Play Store kommt. Das ist bei jeder App so, die man selbst herunterlädt.

### Weitere Handys

Die App läuft auf beliebig vielen Handys, alle bekommen dieselben Meldungen. Zwei Wege führen dorthin, beide beginnen am eingerichteten Handy unter **App → Weitere Handys**.

**App samt Thema weitergeben** schickt die App selbst als Datei (`blackout-radar-mit-thema.apk`), per Messenger, Quick Share, Bluetooth oder über einen eigenen Speicher. Die Datei enthält das Thema dieses Handys. Am anderen Handy die Datei antippen, installieren und die App einmal öffnen: Sie richtet sich selbst ein, eingeben muss dort niemand etwas. Die Datei, die bei GitHub zum Download liegt, enthält kein Thema. Das Thema kommt erst am Handy hinein, beim Weitergeben.

- Die Datei ist die Fassung der App, die auf dem weitergebenden Handy läuft. Gibt es eine neuere, bietet die App am anderen Handy das Update von selbst an.
- Läuft die App am anderen Handy schon, lässt sich die Datei darüber installieren. Was dort eingerichtet ist, bleibt. Bringt die Datei ein anderes Thema mit, fragt die App einmal, ob sie es übernehmen soll. So lässt sich auch ein neues Thema an alle Handys verteilen.
- Nach **Thema ändern** steht auf der Seite zum Einrichten der Knopf **Thema aus der Installationsdatei verwenden**.

**Nur Nachricht mit Link weitergeben** schickt eine Nachricht mit dem Download und dem Thema. Das hilft, wo ein Dienst keine App-Dateien annimmt, zum Beispiel Gmail. Am anderen Handy die App installieren, die ganze Nachricht kopieren, die App öffnen und auf **Eigenen Radar verbinden** tippen: Sie erkennt die Nachricht und trägt das Thema selbst ein, dort nur noch auf **Verbinden** tippen. Dafür sieht die App in die Zwischenablage, aber nur solange diese eine Seite offen ist, und übernimmt daraus nur ihren eigenen Link. Alles andere lässt sie liegen. Auf der Willkommensseite und beim öffentlichen Alarm liest sie die Zwischenablage nie. Klappt das auf einem Handy nicht, holt **Einfügen** die Nachricht.

Das Thema wirkt wie ein Passwort: Wer es kennt, kann mitlesen und selbst Meldungen an alle schicken. Die Datei mit Thema und die Nachricht sind deshalb so vertraulich wie das Thema selbst: nur an Leute weitergeben, denen man vertraut, und nirgends öffentlich ablegen.

## Was die App kann

| Teil | Inhalt |
|---|---|
| **Lage** | Lagebericht des Radars: laufende und beendete Ereignisse, Kennzahlen, Statistik, Datenquellen. Der letzte Stand bleibt auch ohne Netz lesbar. |
| **Meldungen** | alle empfangenen Meldungen, nach Tagen geordnet |
| **App** | Zustand der Verbindung, Prüfliste der Erlaubnisse, Einstellungen, Probealarm, Weitergabe an weitere Handys, neue Version |
| **Über uns** | wer die App anbietet, Kontakt, Impressum und Datenschutzerklärung. Nur hier stellt sich der Anbieter vor, nie in einer Meldung oder zwischen Lage und Meldungen |

**Öffentlicher Alarm:** Das öffentliche Thema (`blackout-radar-alarm` bei ntfy.sh) kann jeder lesen und jeder beschreiben. Der Radar unterschreibt deshalb jede Meldung, die App kennt nur den öffentlichen Schlüssel und verwirft alles, was nicht dazu passt: Es läutet nicht und steht nicht in der Liste. Zeit, Dringlichkeit und Kennung einer Meldung nimmt die App aus den unterschriebenen Angaben, nie aus dem, was ntfy mitliefert. Spielt jemand eine echte Meldung noch einmal ein, läutet sie kein zweites Mal, und eine alte echte Meldung gilt nach 13 Stunden nicht mehr. Meldungen über den Betrieb des Radars gehen nur an den Betreiber. Der Notweg gilt auch hier.

**Alarm:** Ein Alarm (großer Stromausfall in Österreich, schwere Störung der Netzfrequenz) läutet über die Wecker-Lautstärke, also auch bei Lautlos und bei "Nicht stören", solange dort Wecker erlaubt sind (Standard). Auf Wunsch wiederholt sich der Ton, bis man die Meldung öffnet. Warnungen und Meldungen kommen mit dem normalen Benachrichtigungston, die tägliche Übersicht leise. In den Android-Einstellungen der App lässt sich jeder dieser Kanäle einzeln anpassen.

**Wächter:** Etwa alle 15 Minuten prüft die App, ob ihre Verbindung lebt, und baut sie sonst neu auf. Nach einem Funkloch, einem Neustart des Handys oder wenn Android die App beendet hat, holt sie nach, was in der Zwischenzeit gekommen ist. Zugleich schaut sie, ob der Radar selbst noch läuft: Ist der Lagebericht älter als 3 Stunden, kommt ein Hinweis, weil dann auch keine Alarme kämen.

**Notweg:** Der Radar führt im Lagebericht bei GitHub, welche Meldungen er verschickt hat. Die App vergleicht das etwa alle 15 Minuten mit dem, was über ntfy angekommen ist. Hat sie keine Verbindung zu ntfy, sieht sie etwa alle 5 Minuten nach. Fehlt eine Meldung, holt die App sie aus dem Lagebericht und meldet sich selbst, mit derselben Dringlichkeit wie über ntfy. In der Liste trägt die Meldung dann das Kennzeichen „Notweg“ und den Grund: Der Radar wurde sie bei ntfy nicht los, ntfy war vom Handy aus nicht erreichbar, oder das Thema am Handy stimmt nicht mit dem des Radars überein. Kommt dieselbe Meldung später doch noch über ntfy, ersetzt sie den Eintrag und läutet nicht noch einmal. Ein Alarm hängt damit nicht mehr an ntfy allein.

**Europa:** Der Radar läuft in den USA, seine Messquellen stehen in Europa. Antwortet keine von ihnen mehr, zeigt der Tab **Lage** das ganz oben: Dann heißt „nichts erkannt“ nicht mehr „alles in Ordnung“.

**Einrichten ohne Netz:** Ist ntfy.sh beim Einrichten nicht erreichbar, merkt sich die App das Thema und verbindet sich, sobald das Netz da ist. Die Meldungen der letzten 12 Stunden holt sie dann nach. Sie kommen still in die Liste, weil sie schon älter sind. Alles, was ab dem Einrichten kommt, läutet wie gewohnt.

**Uhrzeiten:** Die App zeigt alle Zeiten in österreichischer Zeit, so wie der Radar sie in seinen Meldungen schreibt, auch wenn das Handy auf eine andere Zeitzone gestellt ist.

**Neue Versionen:** Die App fragt zweimal am Tag bei GitHub nach. Gibt es eine neue Version, steht im Tab **App** ein Knopf zum Herunterladen. Thema und Einstellungen bleiben beim Aktualisieren erhalten. Die Fassung aus Google Play fragt nicht selbst nach, dort aktualisiert der Store.

## Grenzen

- **ntfy.sh hebt Meldungen 12 Stunden auf.** War das Handy länger ohne Netz, fehlen ältere Meldungen in der Liste. Der Lagebericht zeigt trotzdem den aktuellen Stand.
- **Der Notweg ist langsamer als der Push.** Meist dauert es einige Minuten, im ungünstigen Fall rund 20: Der Radar schreibt den Lagebericht alle 5 Minuten, die App sieht alle 15 Minuten nach. Er braucht Internet am Handy und einen Radar, der läuft. Meldungen von vor dem Einrichten und Meldungen, die älter als knapp 12 Stunden sind, holt er nicht. Solange der Radar seine Meldungen noch nicht im Lagebericht führt, steht im Tab **App** beim Notweg „wartet auf den Radar“.
- **Stromsparfunktionen der Hersteller.** Samsung, Xiaomi, Huawei und andere beenden Apps zum Teil trotz Ausnahme. Bei Samsung die App unter *Einstellungen → Akku → Hintergrundnutzungslimits* bei "Nie ruhende Apps" eintragen. Anleitungen für jeden Hersteller: <https://dontkillmyapp.com>
- **Dauermeldung.** Android verlangt für Apps, die im Hintergrund auf Meldungen warten, die Anzeige "Blackout-Radar wacht". Sie lässt sich beim Kanal "Verbindung" ausblenden.
- **Die Datei mit Thema schützt das Thema nicht.** Wer sie hat, kann das Thema herauslesen, es steht unverschlüsselt darin. Auf einem Handy, das aus dieser Datei installiert wurde, liegt sie als Installationsdatei der App vor. Die Einstellungen einer App sind für andere Apps gesperrt, ihre Installationsdatei ist es nicht: Apps mit weitreichenden Rechten (Dateimanager, „App teilen“, Virenscanner) können sie lesen und weitergeben, und mit ihr das Thema. Nach einem Update aus dem Download bei GitHub steht das Thema nur noch in den Einstellungen der App.
- **Der Notweg trägt keine Unterschrift.** Was die App aus dem Lagebericht holt, kommt über eine verschlüsselte Verbindung aus dem Repository des Radars bei GitHub. Schreiben kann dort nur, wer Zugriff auf das Repository hat. Die Unterschrift schützt den Weg über ntfy, wo jeder schreiben kann.
- **Der Probealarm** in der App prüft nur Ton und Anzeige am Handy. Den ganzen Weg prüft die Aktion `test-push` des Radars (Actions → Blackout-Radar → Run workflow).

## Für Entwickler

| Teil | Aufgabe |
|---|---|
| `app/src/main/java/…/ListenerService.kt` | Dauerverbindung zu ntfy (`/<thema>/json`), Wiederaufbau mit wachsenden Wartezeiten |
| `app/src/main/java/…/Watchdog.kt` | Wächter über Wecker und JobScheduler, Abgleich mit dem Lagebericht, Start nach dem Einschalten |
| `app/src/main/java/…/Fallback.kt` | Notweg: vergleicht die Meldungen des Radars aus `status.json` (Schlüssel `notices`) mit dem, was über ntfy ankam, und zeigt Fehlendes selbst an |
| `app/src/main/java/…/Sync.kt` | Einrichten und Nachholen verpasster Meldungen (`poll=1`, `since=<letzte Meldung>`), dazu die Vorgeschichte nach einem Einrichten ohne Netz |
| `app/src/main/java/…/Alerts.kt` | Benachrichtigungskanäle und Anzeige |
| `app/src/main/java/…/Signed.kt` | Prüft die Unterschrift des öffentlichen Alarms (ECDSA P-256 mit den Bordmitteln von Android). Urteilt genau wie `sign.unseal` im Radar: Beide prüfen dieselben Beispiele aus `tests/data/unterschrift.json`. Der Testschlüssel gilt nur im Testbau |
| `app/src/main/java/…/PublicAlarm.kt` | Der öffentliche Alarm: festes Thema, Kennung einer Meldung aus den unterschriebenen Angaben (`pub:<Zeit>:<Schlüssel>`), Grenze für alte Meldungen |
| `app/src/main/java/…/ApkTopic.kt` | Das Thema in der Installationsdatei: liest und schreibt einen eigenen Eintrag im Signaturblock der Datei ("APK Signing Block", Kennung `0x42524B31`). Der Block liegt außerhalb dessen, was die Signatur abdeckt, und Android überliest unbekannte Einträge. Die Datei bleibt gültig signiert und wird nicht größer, am Programm ändert sich kein Byte |
| `app/src/main/java/…/AppFile.kt` | Android-Teil dazu: liest beim Start das Thema aus der eigenen Installationsdatei, schreibt die Kopie zum Weitergeben und reicht sie über `AppFileProvider` an die App, die der Mensch wählt. Von außen ist die Kopie nicht erreichbar. Abschalten für einen Bau, den ein Store selbst signiert: `APP_FILE` in `app/build.gradle.kts` |
| `app/src/main/assets/www/` | Oberfläche (HTML, CSS, JavaScript in einer WebView, lädt nichts aus dem Netz) |
| `../docs/impressum.md`, `../docs/datenschutz.md` | Impressum und Datenschutzerklärung. Sie stehen einmal im Repository und kommen beim Bauen in die App (Ordner `rechtstexte` der Assets). Die App zeigt sie ohne Netz, der Eintrag im Store verweist auf dieselben Dateien |
| `app/src/main/res/drawable/ic_launcher_*.xml` | App-Symbol als Vektor, abgeleitet vom Logo des Betreibers: heller Grund, darauf die zweigeteilte Pille mit dem Verlauf von Hellblau nach Dunkelblau, darin weiß der Schriftzug. An der Stelle des Spalts zwischen den beiden Hälften steht der Blitz. Die Buchstaben sind Pfade (die Umrisse aus der Vorlage des Logos), weil ein Vektorbild von Android keine Schrift kennt. In der einfarbigen Fassung sind sie ausgespart. Dasselbe Zeichen steht als `LOGO_BIG` in `assets/www/app.js`, für die Kopfzeile gibt es dort das kleine `LOGO` ohne Schrift |
| `app/src/debug/` | nur im Testbau: Einrichten per `adb` mit Rückmeldung, wie es ausging, Abgleich mit dem Lagebericht auf Zuruf, weitergegebene Nachricht in die Zwischenablage legen, Leseerlaubnis für die Datei mit Thema an `adb`, Ziel des öffentlichen Alarms auf den nachgestellten Server legen, unverschlüsselte Verbindung dorthin, absichtlicher Absturz für die Gegenprobe im Emulator-Test |
| `test/emulator.sh` | Emulator-Test: fertige App gegen ntfy.sh, Testbau gegen den nachgestellten Server `fake_ntfy.py` mit Testdaten aus dem Planspiel (`fixtures.py`), zuletzt der Testbau der Fassung für Google Play (Leiste, Zahnrad, Zurück-Wege, keine Nennung von GitHub oder ntfy, Name in der Kopfzeile auch bei 360 dp Breite und großer Schrift) |
| `test/fake_ntfy.py` | stellt ntfy, den Lagebericht und den Radar nach. Dahinter läuft der echte Versand des Radars (`blackout_radar/notify.py`) mit seinem Postausgang, auch an ein öffentliches Thema mit Unterschrift (Testschlüssel). Störungen lassen sich schalten: Radar erreicht ntfy nicht, Handy erreicht ntfy nicht, anderes Thema. Ein „Fremder“ schreibt auf Zuruf Meldungen ohne gültige Unterschrift in das öffentliche Thema |
| `test/thema_datei.py` | legt das Thema am Rechner in eine Installationsdatei und liest es heraus, mit eigenem Code. Der Emulator-Test vergleicht damit, was das Handy schreibt |
| `test/seite.py` | liest im Emulator, was die App gerade anzeigt, und kann Knöpfe drücken (über die Entwickler-Schnittstelle der WebView) |
| `test/aufbau.js`, `test/fremdtext.js` | laufen in der Seite der App: Sitzt der Rahmen (Kopfzeile, Leiste), und steht irgendwo Text, der nie gewollt ist (ein nacktes „null“ oder „undefined“)? |
| `test/Vorschau.java` | schreibt die Bildschirmfotos verkleinert ins Protokoll, holt sie dort wieder heraus, vergleicht zwei Bilder und sagt, ob ein Bild überhaupt etwas zeigt (nach jedem ersten Start wartet der Emulator-Test darauf, und am Schluss darf kein Bild eine leere Seite zeigen) |

Bauen: `cd android && gradle assembleGithubRelease` (Gradle 8.14, JDK 17, Android SDK 36). Tests: `gradle testGithubDebugUnitTest`. Das Paket für Google Play: `gradle bundlePlayRelease`.

### Zwei Fassungen

Dasselbe Programm entsteht in zwei Fassungen (`productFlavors` in `app/build.gradle.kts`). Sie lassen sich nebeneinander installieren.

| | GitHub (`github`) | Google Play (`play`) |
|---|---|---|
| Paketname | `io.github.sebastianeder09.blackoutradar` | `at.ase_it.blackoutradar` |
| Datei | `blackout-radar.apk` | `blackout-radar-play.aab` |
| Signatur | offener Schlüssel (siehe unten) | Upload-Schlüssel (siehe unten), für die Handys signiert Google |
| Neue Versionen | die App fragt bei GitHub nach | über den Store, die App fragt nicht selbst |
| Weitergabe als Datei samt Thema | ja | nein, Google signiert die Datei am Handy neu |
| Leiste unten | Lage, Meldungen, App, Über uns | nur Lage und Meldungen. Die Einstellungen liegen hinter dem Zahnrad oben rechts, „Über uns“ hinter dem Namen in der Kopfzeile, aktualisiert wird beim Stand des Lageberichts |
| Eigener Radar (eigenes Thema) | ja | wird nicht angeboten |
| Fremde Dienste beim Namen (GitHub, ntfy) | ja, mit Verweisen dorthin | nur in der Datenschutzerklärung, keine Verweise |

Unter dem Symbol am Startbildschirm heißt die App in beiden Fassungen „Blackout“ (`app_name`), weil viele Handys dort längere Namen abschneiden. In der App und im Store heißt sie „Blackout-Radar“. Die Kopfzeile zeigt den Namen immer ganz: Wird es eng (schmales Handy, große Schrift), wird seine Schrift kleiner, und das Wort neben dem Punkt der Verbindung weicht (`fitHeader` in `app.js`).

Beide Dateien hängen an jeder Veröffentlichung unter *Releases*. Das Paket für Google Play lässt sich nicht am Handy installieren, es wird in der Play Console hochgeladen. Ziel ist Android 16 (API 36), lauffähig ist die App ab Android 8.

### Prüfung bei GitHub

Bei jeder Änderung unter `android/` baut GitHub Actions die App (`.github/workflows/android.yml`), führt die Tests aus und prüft sie in drei Emulatoren (Android 12, 15 und 16) gegen das echte ntfy.sh: Willkommensseite, Einrichten per Link, Lagebericht, Alarm, Funkloch, Ruhezustand, hart beendete App, Neustart und Weitergeben. Schon beim Bauen steht fest, dass die App von GitHub ihren Paketnamen und ihr Zertifikat behält, sonst ließe sie sich auf keinem Handy mehr aktualisieren. Der Testbau zeigt zuerst die Willkommensseite. Dort darf er die Zwischenablage nicht lesen, Android führt darüber Buch. Dann wird er so eingerichtet wie ein weiteres Handy am eigenen Radar: Die weitergegebene Nachricht liegt in der Zwischenablage, auf der Seite **Eigenen Radar verbinden** muss das Thema von selbst im Feld stehen, und ein Tipp auf „Verbinden“ muss genügen. Danach zeigt er einen nachgestellten Blackout und wird einmal ohne Netz eingerichtet: Die älteren Meldungen müssen danach still in der Liste stehen. Den Notweg prüft der Testbau in fünf Lagen: Der Radar wird eine Meldung bei ntfy nicht los, er stellt sie später verspätet zu, er schickt sie an ein anderes Thema, eine Meldung kommt wie gewohnt an, und ntfy fällt für das Handy aus. In der letzten Lage stößt niemand den Abgleich an, die App muss von selbst alarmieren. Jede Meldung muss genau einmal läuten. Den öffentlichen Alarm prüft der Testbau am nachgestellten Server, dessen Radar mit dem Testschlüssel unterschreibt: Jede unterschriebene Meldung muss ankommen, ein Alarm muss läuten. Was ein Fremder in dasselbe Thema schreibt, darf weder läuten noch in der Liste stehen: eine Meldung ohne Unterschrift, die Unterschrift einer echten Meldung unter anderem Text oder Titel, und eine echte Meldung, die noch einmal eingespielt wird. Der Notweg holt auch hier, was der Radar nicht loswird, und lässt Meldungen über den Betrieb des Radars aus. Impressum, Datenschutzerklärung und die Seite „Über uns“ müssen sich öffnen, die Zurück-Geste führt eine Ebene zurück und zuletzt aus der App. Zwei Bildvergleiche zeigen, dass die Anzeige einer Änderung von selbst folgt. Auf jeder Seite, die der Lauf zeigt, sucht er nach Text, der nie gewollt ist (ein nacktes „null“). Zum Schluss geben beide die App als Datei samt Thema weiter. Der Lauf holt die Datei so ab, wie es ein Messenger täte, und verlangt, dass sie Byte für Byte der installierten Datei samt Thema gleicht und ohne Erlaubnis von außen nicht lesbar ist. Über eine vorhandene Installation gespielt, muss eine Datei mit anderem Thema eine Rückfrage auslösen und darf nichts ersetzen. Dann werden beide Apps entfernt und aus der Datei frisch installiert: Android muss die Signatur annehmen, und beim ersten Öffnen müssen beide verbunden sein, ohne dass jemand etwas eingibt. Schon beim Bauen prüft `apksigner`, dass eine Datei mit Thema gültig signiert bleibt. Dann schaltet die fertige App den öffentlichen Alarm am echten Thema ein. Der Lauf liest dort nur und schickt nichts hin: Die App muss genau die Meldungen zeigen, die auch `blackout_radar/sign.py` als echt anerkennt. Zuletzt startet der Testbau der Fassung für Google Play, schaltet den öffentlichen Alarm ein und meldet einen unterschriebenen Alarm. Er darf weder nach neuen Fassungen suchen noch die App als Datei weitergeben. Am Ende fragt der Lauf Android, ob die App abgestürzt oder hängen geblieben ist, und prüft mit einem absichtlichen Absturz des Testbaus, dass diese Frage auch anschlägt. Nach dem Zusammenführen in `main` erscheint die neue Fassung unter *Releases*.

Die Bildschirmfotos des Emulators liegen in voller Größe als Artefakt `emulator-api-<Nummer>` beim Lauf. In Pull Requests stehen sie zusätzlich verkleinert im Protokoll (Schritt "Bilder verkleinert ins Protokoll"), bei einem fehlgeschlagenen Lauf auch sonst. Dann zeigt der Schritt "Protokoll des nachgestellten Servers" außerdem, welche Anfragen der App dort angekommen sind. So holt man die Bilder heraus:

```sh
gh api repos/sebastianeder09/blackout-radar/actions/jobs/<Nummer des Jobs>/logs > protokoll.txt
java android/test/Vorschau.java lesen protokoll.txt bilder/
```

**Signaturschlüssel:** `keystore/blackout-radar.p12` liegt absichtlich offen im Repository (Passwort `blackout-radar`). Android nimmt ein Update nur an, wenn es mit demselben Schlüssel signiert ist. Ein geheimer Schlüssel müsste als Secret hinterlegt werden und schützt nur davor, dass jemand eine gefälschte Fassung baut, die sich als Update installieren lässt. Das setzt voraus, dass man diese Datei selbst aus einer fremden Quelle installiert. Die App kommt aus den Releases dieses Repositorys oder als Datei von einem Handy, dem man vertraut, deshalb überwiegt hier der einfache Betrieb. Eine App-Datei, die ungefragt von Fremden kommt, installiert man nicht.

**Upload-Schlüssel für Google Play:** `keystore/play-upload.p12` (Alias `upload`) liegt im Repository, sein Kennwort nicht. Das Kennwort ist ein langer Zufallswert und steht nur als Secret `PLAY_UPLOAD_PASSWORD` bei GitHub. Die Datei ist damit verschlüsselt (AES-256), ohne das Kennwort ist sie wertlos. Ist das Secret gesetzt, unterschreibt der Lauf das Paket `blackout-radar-play.aab`. Fehlt es, entsteht das Paket zur Probe ohne Unterschrift und kommt nicht in die Veröffentlichung. Bei Google Play gilt dieser Schlüssel nur für das Hochladen: Für die Handys signiert Google selbst (Play App Signing). Geht das Kennwort verloren, lässt sich in der Play Console ein neuer Upload-Schlüssel hinterlegen. Fingerabdruck des Zertifikats (SHA-256): `F2:08:26:95:63:AD:0E:23:8D:B7:18:3B:05:12:02:03:1B:E5:19:96:73:6A:8B:3B:FD:F1:B6:1E:35:5E:B7:56`.
