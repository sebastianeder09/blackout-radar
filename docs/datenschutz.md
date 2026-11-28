# Datenschutzerklärung

Für die App „Blackout-Radar“. Stand: 28. November 2026.

## Kurz gesagt

- Die App braucht kein Konto und fragt keine persönlichen Angaben ab.
- Sie erfasst keinen Standort und enthält keine Werbung Dritter und keine Werkzeuge zur Auswertung des Nutzungsverhaltens.
- Der Anbieter betreibt keinen eigenen Server, an den die App Daten schickt. Der Anbieter erfährt nicht, wer die App nutzt.
- Damit Alarme ankommen, verbindet sich die App mit zwei fremden Diensten: ntfy.sh und GitHub. Dabei wird, wie bei jeder Verbindung im Internet, die IP-Adresse des Handys übertragen.

## Verantwortlicher

ASE-IT, Inhaber Sebastian Michael Eder  
Zudersdorf 7, 4284 Tragwein, Österreich  
Telefon: 07263 883 52 10  
E-Mail: [office@ase-it.at](mailto:office@ase-it.at)

## Welche Verbindungen die App aufbaut

### Alarme über ntfy.sh

Die App hält eine Verbindung zum Benachrichtigungsdienst ntfy.sh offen und empfängt darüber die Meldungen des Radars. Dabei erfährt ntfy.sh die IP-Adresse des Handys, den Zeitpunkt der Verbindung und das abonnierte Thema. Beim öffentlichen Alarm ist das Thema für alle dasselbe. Die App nennt dabei ihren Namen und ihre Versionsnummer, aber keine Kennung des Geräts oder der Person.

Betreiber von ntfy.sh ist die ntfy LLC mit Sitz in den USA. Nach deren Angaben dient die IP-Adresse dazu, Missbrauch zu begrenzen, und Meldungen werden höchstens 12 Stunden zwischengespeichert. Einzelheiten: [docs.ntfy.sh/privacy](https://docs.ntfy.sh/privacy/).

Zweck: Zustellung der Alarme, die Sie mit dem Einschalten des Alarms anfordern. Rechtsgrundlage: Art. 6 Abs. 1 lit. b DSGVO. Die Übermittlung in die USA ist für diese Zustellung erforderlich (Art. 49 Abs. 1 lit. b DSGVO). Eine Zertifizierung der ntfy LLC nach dem Datenschutzrahmen EU-USA ist uns nicht bekannt.

### Lagebericht und Notweg über GitHub

Den Lagebericht lädt die App von GitHub, wenn Sie sie öffnen, und im Hintergrund etwa alle 15 Minuten. Fehlt dort eine Meldung, die über ntfy.sh nicht angekommen ist, zeigt die App sie selbst an (Notweg). Die Fassung der App, die als Datei von GitHub stammt, fragt dort außerdem beim Öffnen nach, ob es eine neuere Fassung gibt, höchstens alle 12 Stunden. Bei jedem Abruf erfährt GitHub die IP-Adresse des Handys, den Zeitpunkt sowie Namen und Versionsnummer der App.

Betreiber ist die GitHub, Inc. mit Sitz in den USA, ein Unternehmen von Microsoft. GitHub ist nach eigenen Angaben nach dem Datenschutzrahmen EU-USA zertifiziert. Einzelheiten: [GitHub Privacy Statement](https://docs.github.com/de/site-policy/privacy-policies/github-general-privacy-statement).

Zweck: Anzeige des Lageberichts und Absicherung der Alarme. Rechtsgrundlage: Art. 6 Abs. 1 lit. b DSGVO.

### Verweise nach außen

Tippen Sie auf einen Verweis, etwa zur Homepage des Anbieters oder zu einer Quelle im Lagebericht, öffnet sich der Browser des Handys. Ab dann gilt die Datenschutzerklärung der jeweiligen Seite. Ein Tipp auf „Anrufen“ öffnet das Telefon mit der Nummer, gewählt wird erst, wenn Sie dort bestätigen. Ein Tipp auf „E-Mail schreiben“ oder „USV-Beratung anfragen“ öffnet Ihr E-Mail-Programm mit der Adresse des Anbieters. Abgeschickt wird erst, wenn Sie dort senden.

### Wenn Sie uns schreiben oder anrufen

Wenden Sie sich an den Anbieter, verarbeitet er die Angaben aus Ihrer Nachricht oder Ihrem Anruf (Name, Kontaktdaten, Inhalt), um die Anfrage zu beantworten. Rechtsgrundlage: Art. 6 Abs. 1 lit. b DSGVO, wenn es um ein Angebot oder einen Auftrag geht, sonst Art. 6 Abs. 1 lit. f DSGVO (Beantwortung von Anfragen). Die Angaben werden gelöscht, sobald die Anfrage erledigt ist und keine gesetzliche Pflicht zur Aufbewahrung besteht. Mit der Nutzung der App werden sie nicht verknüpft.

## Was die App auf dem Handy speichert

- die Einstellungen der App,
- die letzten 300 Meldungen,
- den zuletzt geladenen Lagebericht,
- bei einem eigenen Radar: Server und Thema.

Diese Daten bleiben auf dem Handy. Sie werden gelöscht, wenn Sie in der App den Alarm ausschalten oder das Thema ändern, die Daten der App in den Einstellungen von Android löschen oder die App entfernen.

## Zwischenablage

Nur auf der Seite „Eigenen Radar verbinden“ sieht die App in die Zwischenablage, damit ein weitergegebenes Thema nicht eingetippt werden muss. Sie übernimmt daraus ausschließlich einen Verweis des Blackout-Radars. Alles andere bleibt unberührt und verlässt das Handy nicht. Wer nur den öffentlichen Alarm einschaltet, dessen Zwischenablage sieht die App nie an.

## Berechtigungen

- **Benachrichtigungen:** damit Android Alarme anzeigt.
- **Im Hintergrund laufen (Ausnahme von der Akku-Optimierung, Dienst im Vordergrund, Start nach dem Einschalten des Handys):** damit die Verbindung hält und ein Alarm sofort ankommt, auch wenn das Handy ruht.
- **Internet:** für die oben genannten Verbindungen.

Die App verlangt keinen Zugriff auf Standort, Kontakte, Kamera, Mikrofon, Dateien oder Telefonfunktionen.

## Bezug über Google Play

Laden Sie die App aus Google Play, verarbeitet Google dabei Daten in eigener Verantwortung, zum Beispiel für Installation und Aktualisierung. Darauf hat der Anbieter keinen Einfluss. Es gilt die Datenschutzerklärung von Google.

## Speicherdauer und Empfänger

Der Anbieter selbst speichert keine Daten über die Nutzerinnen und Nutzer der App, solange Sie ihm nicht selbst schreiben oder ihn anrufen. Empfänger von Verbindungsdaten sind nur die genannten Dienste ntfy.sh und GitHub, für die Dauer, die sie in ihren Erklärungen nennen. Eine automatisierte Entscheidung im Einzelfall oder eine Profilbildung findet nicht statt.

## Ihre Rechte

Sie haben das Recht auf Auskunft, Berichtigung, Löschung, Einschränkung der Verarbeitung, Datenübertragbarkeit und Widerspruch. Wenden Sie sich dafür an den oben genannten Verantwortlichen. Da der Anbieter keine Daten über die Nutzung der App erhält, liegen ihm in aller Regel keine Daten zu Ihrer Person vor.

Sie können sich außerdem bei der Aufsichtsbehörde beschweren: Österreichische Datenschutzbehörde, Barichgasse 40–42, 1030 Wien, [www.dsb.gv.at](https://www.dsb.gv.at).

## Änderungen

Ändert sich die App, wird diese Erklärung angepasst. Es gilt die Fassung, die in der App und unter der öffentlichen Adresse steht.
