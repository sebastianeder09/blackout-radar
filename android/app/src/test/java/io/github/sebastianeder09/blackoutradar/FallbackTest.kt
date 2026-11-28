package io.github.sebastianeder09.blackoutradar

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.Instant
import java.time.ZoneId

/** Der Notweg: Was der Radar im Lagebericht führt, muss am Handy genau einmal läuten. */
class FallbackTest {
    private val vienna = ZoneId.of("Europe/Vienna")

    /** 27.11.2026, 18:00 Uhr in Wien. */
    private val t0 = Instant.parse("2026-11-27T17:00:00Z").epochSecond
    private val minute = 60L
    private val hour = 3600L

    private val title = "Blackout: Österreich"
    private val body = "Seit 18:00 Uhr, Dauer bisher 5 min"

    private fun posted(key: String, time: Long, title: String = this.title, handedOver: Boolean = true, level: String = "alarm") =
        Posted(key, time, title, body, level, handedOver)

    /** Eine Meldung, wie sie über ntfy ankommt. */
    private fun arrived(id: String, time: Long, title: String = this.title, message: String = body) =
        Notice(id, time, title, message, 5, listOf("rotating_light"), "")

    /** Der Text, den der Radar einer verspäteten Zustellung gibt. [createdAt] ist der Zeitpunkt des Erstellens. */
    private fun late(createdAt: Long) = "Verspätet zugestellt, erstellt am ${Fallback.stamp(createdAt, vienna)} Uhr.\n$body"

    private fun missing(posted: List<Posted>, log: List<Notice>, setup: Long = t0 - hour, now: Long = t0 + hour) =
        Fallback.missing(posted, log, setup, now, vienna).map { it.key }

    /** So kürzt der Radar einen Titel für ntfy (notify.clip). */
    private fun clip(text: String, maxBytes: Int = 240): String {
        val raw = text.toByteArray(Charsets.UTF_8)
        if (raw.size <= maxBytes) return text
        var cut = maxBytes - 4
        while (cut > 0 && (raw[cut].toInt() and 0xC0) == 0x80) cut--
        return String(raw, 0, cut, Charsets.UTF_8).trimEnd() + " …"
    }

    // ------------------------------------------------------------------ Lesen

    @Test
    fun lageberichtOhneMeldungenLaesstDenNotwegRuhen() {
        assertNull(Fallback.parse(null))
        assertNull(Fallback.parse("kein json"))
        assertNull(Fallback.parse("""{"generated_at":"2026-11-27T17:00:00Z","active":[]}"""))
        assertNull(Fallback.parse("""{"notices":"nichts"}"""))
        // Führt der Radar die Liste und sie ist leer, ist der Notweg bereit.
        assertEquals(emptyList<Posted>(), Fallback.parse("""{"notices":[]}"""))
    }

    @Test
    fun meldungenAusDemLagebericht() {
        val json = """{"timezone":"Europe/Vienna","notices":[
            {"key":"e1:start","t":"2026-11-27T17:00:00Z","title":"Blackout: Österreich","body":"Zeile 1\nZeile 2",
             "level":"alarm","delivered":["ntfy","email"],"pending":[]},
            {"key":"e1:update","t":"2026-11-27T17:20:00+00:00","title":"Update Österreich: dauert an","body":"",
             "level":"info","delivered":["email"],"pending":["ntfy"]},
            {"key":"daily:2026-11-27","t":"2026-11-27T06:00:00Z","title":"Lagebericht","body":"x",
             "level":"daily","delivered":["email"],"pending":[]},
            {"key":"ohne-titel","t":"2026-11-27T17:00:00Z","title":"","body":"x","level":"info","delivered":["ntfy"]},
            {"key":"ohne-zeit","t":"gestern","title":"Titel","body":"x","level":"info","delivered":["ntfy"]},
            {"t":"2026-11-27T17:30:00Z","title":"Ohne Schlüssel und Stufe","body":null,"delivered":["ntfy"]},
            "kein Eintrag"
        ]}"""
        val list = Fallback.parse(json)!!
        assertEquals(listOf("e1:start", "e1:update", ""), list.map { it.key })

        val start = list[0]
        assertEquals(t0, start.time)
        assertEquals("Blackout: Österreich", start.title)
        assertEquals("Zeile 1\nZeile 2", start.body)
        assertEquals("alarm", start.level)
        assertTrue(start.handedOver)

        // Noch im Postausgang des Radars: nicht an ntfy übergeben.
        assertEquals(t0 + 20 * minute, list[1].time)
        assertFalse(list[1].handedOver)

        // Was der Radar gar nicht an ntfy schicken wollte (hier die tägliche Übersicht), fehlt am Handy nicht.
        assertTrue(list.none { it.key.startsWith("daily") })

        assertEquals("info", list[2].level)
        assertEquals("", list[2].body)
        assertTrue(list[2].handedOver)
    }

    @Test
    fun zeitzoneDesRadars() {
        assertEquals(ZoneId.of("Europe/Berlin"), Fallback.zone("""{"timezone":"Europe/Berlin"}"""))
        assertEquals(vienna, Fallback.zone("""{"notices":[]}"""))
        assertEquals(vienna, Fallback.zone("""{"timezone":"Mond/Krater"}"""))
        assertEquals(vienna, Fallback.zone("kaputt"))
        assertEquals(vienna, Fallback.zone(null))
        assertEquals("27.11. 18:00", Fallback.stamp(t0, vienna))
        // Im Sommer gilt die Sommerzeit, so wie der Radar sie schreibt.
        assertEquals("01.07. 14:05", Fallback.stamp(Instant.parse("2026-07-01T12:05:59Z").epochSecond, vienna))
    }

    // -------------------------------------------------------------- Vergleichen

    @Test
    fun titelVergleich() {
        assertTrue(Fallback.sameTitle("Blackout: Österreich", "Blackout: Österreich"))
        assertTrue(Fallback.sameTitle("Blackout:  Österreich ", " Blackout: Österreich"))
        assertFalse(Fallback.sameTitle("Blackout: Österreich", "Blackout: Deutschland"))
        assertFalse(Fallback.sameTitle("Update Österreich: dauert an, bisher 1 h 10 min", "Update Österreich: dauert an, bisher 2 h 10 min"))

        // Sehr lange Titel kürzt der Radar für ntfy. Im Lagebericht stehen sie ganz.
        val long = "Stromausfall: " + (1..40).joinToString(", ") { "Gebiet Nummer $it mit Umlaut ä" }
        val clipped = clip(long)
        assertTrue(clipped.endsWith(" …"))
        assertTrue(clipped.toByteArray(Charsets.UTF_8).size <= 240)
        assertTrue(Fallback.sameTitle(long, clipped))
        assertFalse(Fallback.sameTitle(long.replace("Stromausfall", "Blackout"), clipped))

        // Drei Punkte allein machen aus zwei Titeln nicht denselben.
        assertFalse(Fallback.sameTitle("Blackout: Österreich und Bayern", "Blackout …"))
        assertTrue(Fallback.sameTitle("Blackout …", "Blackout …"))
    }

    @Test
    fun puenktlichOderMitVermerk() {
        fun same(arrived: Notice, postedTime: Long = t0, postedTitle: String = title) =
            Fallback.same(postedTime, postedTitle, arrived, vienna)

        // pünktlich: Sekunden bis wenige Minuten nach dem Erstellen
        assertTrue(same(arrived("a", t0 + 5)))
        assertTrue(same(arrived("a", t0 + 19 * minute)))
        assertTrue(same(arrived("a", t0 + Fallback.ON_TIME_S)))
        assertFalse(same(arrived("a", t0 + Fallback.ON_TIME_S + 1)))

        // Uhren gehen nicht ganz gleich
        assertTrue(same(arrived("a", t0 - 60)))
        assertFalse(same(arrived("a", t0 - Fallback.EARLY_S - 1)))

        // gleicher Titel, aber Stunden später: Das ist eine neue Meldung.
        assertFalse(same(arrived("a", t0 + 3 * hour)))
        assertFalse(same(arrived("a", t0 + 5, title = "Blackout: Deutschland")))

        // verspätet: Der Vermerk des Radars nennt die Minute des Erstellens.
        assertTrue(same(arrived("a", t0 + 3 * hour, message = late(t0))))
        assertTrue(same(arrived("a", t0 + 3 * hour, message = late(t0 + 59))))
        assertFalse(same(arrived("a", t0 + 3 * hour, message = late(t0 - 10 * minute))))
        // Der Vermerk entscheidet auch dann, wenn die Zeit allein noch passen würde.
        assertFalse(same(arrived("a", t0 + 25 * minute, message = late(t0 - 10 * minute))))
        assertFalse(same(arrived("a", t0 - 10 * minute, message = late(t0))))

        // Was die App selbst über den Notweg angelegt hat, ist keine Zustellung von ntfy.
        assertFalse(same(arrived("a", t0 + 5).copy(via = Fallback.VIA_RADAR)))

        assertEquals("27.11. 18:00", Fallback.lateStamp(arrived("a", t0, message = late(t0))))
        assertNull(Fallback.lateStamp(arrived("a", t0)))
        // Der Vermerk zählt nur am Anfang des Textes, so wie der Radar ihn setzt.
        assertNull(Fallback.lateStamp(arrived("a", t0, message = "Text\n" + late(t0))))
    }

    @Test
    fun angekommenHeisstNichtFehlend() {
        val list = listOf(posted("a", t0), posted("b", t0 + 20 * minute, title = "Update Österreich: dauert an"))
        val log = listOf(
            arrived("x1", t0 + 4),
            arrived("x2", t0 + 20 * minute + 7, title = "Update Österreich: dauert an"),
            arrived("x3", t0 + 30 * minute, title = "Testmeldung vom Blackout-Radar"),
        )
        assertEquals(emptyList<String>(), missing(list, log))
        assertEquals(listOf("b"), missing(list, log.take(1)))
        assertEquals(listOf("a", "b"), missing(list, emptyList()))
        // Die Probemeldung des Radars steht nicht im Lagebericht und stört den Abgleich nicht.
        assertEquals(listOf("a", "b"), missing(list, log.takeLast(1)))
    }

    @Test
    fun vorgeschichteUndAltesZaehlenNicht() {
        val list = listOf(posted("alt", t0 - 2 * hour), posted("neu", t0))
        // Eingerichtet eine Stunde vor t0: Was davor kam, hat dieses Handy nie betroffen.
        assertEquals(listOf("neu"), missing(list, emptyList(), setup = t0 - hour))
        assertEquals(listOf("alt", "neu"), missing(list, emptyList(), setup = t0 - 3 * hour))
        // In derselben Sekunde eingerichtet: zählt, damit ein Alarm nie durchrutscht.
        assertEquals(listOf("neu"), missing(list, emptyList(), setup = t0))
        assertEquals(emptyList<String>(), missing(list, emptyList(), setup = t0 + 1))

        // Zu alt, um bei ntfy noch nachzufragen: Der Notweg lässt es liegen.
        assertEquals(listOf("neu"), missing(listOf(posted("neu", t0)), emptyList(), setup = 0, now = t0 + Fallback.MAX_AGE_S))
        assertEquals(emptyList<String>(), missing(listOf(posted("neu", t0)), emptyList(), setup = 0, now = t0 + Fallback.MAX_AGE_S + 1))
        assertTrue(Fallback.MAX_AGE_S < History.KEPT_SECONDS)
    }

    @Test
    fun ueberDenNotwegGezeigtLaeutetNichtNochEinmal() {
        val item = posted("a", t0, handedOver = false)
        val shown = Fallback.notice(item, Fallback.VIA_RADAR, "https://example.org/status.md")
        assertEquals(emptyList<String>(), missing(listOf(item), listOf(shown)))
        // Derselbe Schlüssel zu einer anderen Zeit ist eine neue Meldung.
        assertEquals(listOf("a"), missing(listOf(posted("a", t0 + 10 * minute, handedOver = false)), listOf(shown)))
        // Ein Eintrag des Notwegs deckt keine andere Meldung mit gleichem Titel ab.
        assertEquals(listOf("b"), missing(listOf(item, posted("b", t0 + 5 * minute)), listOf(shown)))
    }

    @Test
    fun jedeZustellungDecktNurEineMeldung() {
        val list = listOf(posted("a", t0), posted("b", t0 + 10 * minute))
        // Zweimal derselbe Titel, nur eine Zustellung: Eine der beiden fehlt.
        assertEquals(1, missing(list, listOf(arrived("x1", t0 + 5))).size)
        assertEquals(1, missing(list, listOf(arrived("x2", t0 + 10 * minute + 5))).size)
        assertEquals(emptyList<String>(), missing(list, listOf(arrived("x1", t0 + 5), arrived("x2", t0 + 10 * minute + 5))))
        // Beide nach einer Störung bei ntfy im selben Lauf zugestellt, noch ohne Vermerk.
        assertEquals(emptyList<String>(), missing(list, listOf(arrived("x1", t0 + 15 * minute), arrived("x2", t0 + 15 * minute + 1))))
        // Die Reihenfolge in der Liste spielt keine Rolle.
        assertEquals(emptyList<String>(),
            missing(list.reversed(), listOf(arrived("x2", t0 + 10 * minute + 5), arrived("x1", t0 + 5))))
    }

    @Test
    fun verspaeteteZustellungNimmtKeinerPuenktlichenDieMeldungWeg() {
        // a wird 45 Minuten zu spät zugestellt (mit Vermerk), b mit gleichem Titel pünktlich.
        val list = listOf(posted("a", t0), posted("b", t0 + 25 * minute))
        val onTime = arrived("x-b", t0 + 25 * minute + 5)
        val delayed = arrived("x-a", t0 + 45 * minute, message = late(t0))
        assertEquals(emptyList<String>(), missing(list, listOf(onTime, delayed)))
        assertEquals(listOf("b"), missing(list, listOf(delayed)))
        // Kam nur die pünktliche, fehlt genau eine. Welche der beiden gleichlautenden, ist gleich.
        assertEquals(1, missing(list, listOf(onTime)).size)
    }

    // ------------------------------------------------------------- Zustellung nach dem Notweg

    @Test
    fun spaetereZustellungErsetztDenEintragDesNotwegs() {
        val shown = Fallback.notice(posted("a", t0, handedOver = false), Fallback.VIA_RADAR, "")
        val other = arrived("x0", t0 - 5 * minute, title = "Netzfrequenz-Alarm: 49,31 Hz")
        val log = listOf(shown, other)

        assertEquals(shown, Fallback.twin(log, arrived("x1", t0 + 12 * minute), vienna))
        assertEquals(shown, Fallback.twin(log, arrived("x1", t0 + 3 * hour, message = late(t0)), vienna))
        // Anderer Titel, oder derselbe Titel Stunden später ohne Vermerk: neue Meldung, sie muss läuten.
        assertNull(Fallback.twin(log, arrived("x1", t0 + 5, title = "Blackout: Deutschland"), vienna))
        assertNull(Fallback.twin(log, arrived("x1", t0 + 3 * hour), vienna))
        assertNull(Fallback.twin(log, arrived("x1", t0 + 3 * hour, message = late(t0 + 2 * hour)), vienna))
        // Eine gewöhnliche Meldung in der Liste ist nie ein Eintrag des Notwegs.
        assertNull(Fallback.twin(log, arrived("x9", t0 - 5 * minute + 3, title = "Netzfrequenz-Alarm: 49,31 Hz"), vienna))
        assertNull(Fallback.twin(emptyList(), arrived("x1", t0 + 5), vienna))
    }

    @Test
    fun beiZweiEintraegenDesNotwegsZaehltDerAeltere() {
        val first = Fallback.notice(posted("a", t0), Fallback.VIA_NET, "")
        val second = Fallback.notice(posted("b", t0 + 10 * minute), Fallback.VIA_NET, "")
        val log = listOf(second, first)
        // ntfy liefert nach der Störung der Reihe nach, mit der ursprünglichen Zeit.
        assertEquals(first, Fallback.twin(log, arrived("x1", t0 + 4), vienna))
        assertEquals(second, Fallback.twin(listOf(second, arrived("x1", t0 + 4)), arrived("x2", t0 + 10 * minute + 4), vienna))
        // Mit Vermerk ist die Zuordnung eindeutig.
        assertEquals(second, Fallback.twin(log, arrived("x2", t0 + 2 * hour, message = late(t0 + 10 * minute)), vienna))
    }

    @Test
    fun nachDemErsetzenFehltNichtsMehr() {
        // Der ganze Weg: Notweg zeigt die Meldung, später stellt ntfy sie doch noch zu.
        val item = posted("a", t0, handedOver = false)
        val shown = Fallback.notice(item, Fallback.VIA_RADAR, "")
        val delivered = arrived("x1", t0 + 50 * minute, message = late(t0))
        assertEquals(shown, Fallback.twin(listOf(shown), delivered, vienna))
        assertEquals(emptyList<String>(), missing(listOf(item.copy(handedOver = true)), listOf(delivered)))
    }

    // ------------------------------------------------------- öffentlicher Alarm

    /** Ein Lagebericht mit dem Abschnitt "public", wie ihn ein Radar mit öffentlichem Alarm schreibt. */
    private fun report(public: String?, notices: String): String =
        "{" + (if (public == null) "" else "\"public\":$public,") + "\"notices\":[$notices]}"

    private val sending = """{"enabled":true,"server":"https://ntfy.sh","topic":"blackout-radar-alarm","key":"k1"}"""
    private val silent = """{"enabled":false,"server":"https://ntfy.sh","topic":"blackout-radar-alarm","key":null,
        "problem":"ALARM_KEY fehlt"}"""

    private val rows = """
        {"key":"e1:start","t":"2026-11-27T17:00:00Z","title":"Blackout: Österreich","body":"Seit 18:00 Uhr",
         "level":"alarm","scope":"all","delivered":["ntfy","email","public"],"pending":[]},
        {"key":"e1:update","t":"2026-11-27T17:20:00Z","title":"Update Österreich: dauert an","body":"",
         "level":"info","scope":"all","delivered":["ntfy"],"pending":["public"]},
        {"key":"betrieb:quelle","t":"2026-11-27T17:25:00Z","title":"Datenquelle gestört","body":"x",
         "level":"warn","scope":"operator","delivered":["ntfy"],"pending":[]},
        {"key":"daily:2026-11-27","t":"2026-11-27T06:00:00Z","title":"Lagebericht","body":"x",
         "level":"daily","scope":"all","delivered":["ntfy","email"],"pending":[]},
        {"key":"alt","t":"2026-11-27T17:30:00Z","title":"Ohne Angabe, für wen","body":"x",
         "level":"info","delivered":["ntfy","public"],"pending":[]}"""

    @Test
    fun oeffentlicherAlarmZaehltNurWasFuerAlleGedachtIst() {
        val list = Fallback.parse(report(sending, rows), public = true)!!
        // Meldungen über den Betrieb gehen nur an den Betreiber. Was der Radar gar nicht an den öffentlichen
        // Alarm schicken wollte (hier die tägliche Übersicht), fehlt dort auch nicht.
        assertEquals(listOf("e1:start", "e1:update"), list.map { it.key })
        assertTrue(list.all { it.public })
        assertTrue(list[0].handedOver)
        // Noch im Postausgang des Radars: nicht an ntfy übergeben.
        assertFalse(list[1].handedOver)
        assertEquals(t0, list[0].time)
        assertEquals("alarm", list[0].level)

        // Dasselbe für das eigene Thema gelesen: Dort zählt, was an ntfy ging, auch die Meldung an den Betreiber.
        val own = Fallback.parse(report(sending, rows))!!
        assertEquals(listOf("e1:start", "e1:update", "betrieb:quelle", "daily:2026-11-27", "alt"), own.map { it.key })
        assertTrue(own.none { it.public })
        assertTrue(own.all { it.handedOver })
    }

    @Test
    fun radarOhneOeffentlichenAlarmLaesstDenNotwegRuhen() {
        // Ein Radar, der den öffentlichen Alarm noch nicht kennt, führt den Abschnitt "public" nicht.
        assertNull(Fallback.parse(report(null, rows), public = true))
        assertNull(Fallback.parse("""{"public":"ja","notices":[]}""", public = true))
        assertNull(Fallback.parse("""{"public":{"enabled":true}}""", public = true))
        assertEquals(emptyList<Posted>(), Fallback.parse(report(sending, ""), public = true))
        // Für das eigene Thema spielt der Abschnitt keine Rolle.
        assertEquals(5, Fallback.parse(report(null, rows))!!.size)
    }

    @Test
    fun sendetDerRadarNichtZeigtDieAppAllesSelbst() {
        // Der Schlüssel fehlt oder passt nicht: Der Radar schickt nichts an den öffentlichen Alarm und nennt den
        // Kanal bei keiner Meldung. Dann gilt jede Meldung für alle als nicht übergeben.
        val list = Fallback.parse(report(silent, rows), public = true)!!
        assertEquals(listOf("e1:start", "e1:update", "daily:2026-11-27"), list.map { it.key })
        // Was der Radar früher noch übergeben hat, bleibt übergeben. Alles andere zeigt die App selbst.
        assertEquals(listOf(true, false, false), list.map { it.handedOver })
        assertEquals(emptyList<Posted>(), Fallback.parse(report("{}", rows.replace("\"all\"", "\"operator\"")), public = true))
        assertEquals(3, Fallback.parse(report("{}", rows), public = true)!!.size)
    }

    @Test
    fun kennungBeimOeffentlichenAlarm() {
        val list = Fallback.parse(report(sending, rows), public = true)!!
        assertEquals("pub:$t0:e1:start", list[0].id)
        assertEquals(PublicAlarm.id(t0 + 20 * minute, "e1:update"), list[1].id)
        val notice = Fallback.notice(list[1], Fallback.VIA_RADAR, "https://example.org/status.md")
        assertEquals(list[1].id, notice.id)
        assertTrue(notice.public)
        assertTrue(notice.fallback)
        assertTrue(notice.message.contains("Lagebericht"))
        // Dieselbe Meldung für das eigene Thema gelesen trägt die Kennung des Notwegs.
        assertEquals("notweg:$t0:e1:start", Fallback.parse(report(sending, rows))!![0].id)
    }

    @Test
    fun beimOeffentlichenAlarmEntscheidetDieKennung() {
        val list = Fallback.parse(report(sending, rows), public = true)!!
        fun missing(log: List<Notice>, setup: Long = t0 - hour, now: Long = t0 + hour) =
            Fallback.missingPublic(list, log, setup, now).map { it.key }

        assertEquals(listOf("e1:start", "e1:update"), missing(emptyList()))
        // Über ntfy angekommen und geprüft: Die Meldung steht unter derselben Kennung in der Liste.
        val arrived = Notice(PublicAlarm.id(t0, "e1:start"), t0, "Blackout: Österreich", "Seit 18:00 Uhr", 5, listOf("rotating_light"), "")
        assertEquals(listOf("e1:update"), missing(listOf(arrived)))
        // Schon über den Notweg gezeigt: läutet nicht noch einmal.
        val shown = Fallback.notice(list[1], Fallback.VIA_RADAR, "")
        assertEquals(emptyList<String>(), missing(listOf(arrived, shown)))
        // Titel und Zeit einer fremden Zeile zählen nicht, nur die Kennung.
        val other = arrived.copy(id = "pub:${t0 + 1}:e1:start")
        assertEquals(listOf("e1:start", "e1:update"), missing(listOf(other)))

        // Vorgeschichte und Altes bleiben liegen, wie beim eigenen Thema.
        assertEquals(listOf("e1:update"), missing(emptyList(), setup = t0 + 1))
        assertEquals(emptyList<String>(), missing(emptyList(), setup = t0 + hour))
        assertEquals(listOf("e1:update"), missing(emptyList(), setup = 0, now = t0 + Fallback.MAX_AGE_S + 1))
        // Älteste zuerst, egal in welcher Reihenfolge der Lagebericht sie führt.
        assertEquals(listOf("e1:start", "e1:update"), Fallback.missingPublic(list.reversed(), emptyList(), t0 - hour, t0 + hour).map { it.key })
    }

    // ------------------------------------------------------------------ Anzeige

    @Test
    fun meldungFuerDieListe() {
        val item = Posted("e1:start", t0, "Blackout: Österreich", "Seit 18:00 Uhr", "alarm", handedOver = false)
        val notice = Fallback.notice(item, Fallback.VIA_RADAR, "https://example.org/status.md")
        assertEquals("notweg:$t0:e1:start", notice.id)
        assertEquals(item.id, notice.id)
        assertEquals(t0, notice.time)
        assertEquals("Blackout: Österreich", notice.title)
        assertEquals("Seit 18:00 Uhr", notice.message)
        assertEquals(5, notice.priority)
        assertEquals(listOf("rotating_light"), notice.tags)
        assertEquals("https://example.org/status.md", notice.click)
        assertEquals(Fallback.VIA_RADAR, notice.via)
        assertTrue(notice.fallback)
        assertEquals("🚨 Blackout: Österreich", Ntfy.displayTitle(notice))

        // Dieselbe Dringlichkeit wie über ntfy, für jede Stufe des Radars.
        for (level in listOf("alarm", "warn", "ok", "info", "daily")) {
            assertEquals(level, Fallback.notice(item.copy(level = level), Fallback.VIA_NET, "").level)
        }
        assertEquals(3, Fallback.notice(item.copy(level = "unbekannt"), Fallback.VIA_NET, "").priority)

        // Ältere Einträge des Radars haben keinen Wortlaut. Die Meldung kommt trotzdem.
        val bare = Fallback.notice(item.copy(body = " "), Fallback.VIA_NET, "")
        assertTrue(bare.message.contains("Lagebericht"))
    }

    @Test
    fun kennungMitZeit() {
        assertNotEquals(posted("a", t0).id, posted("a", t0 + 1).id)
        assertNotEquals(posted("a", t0).id, posted("b", t0).id)
        assertEquals(posted("a", t0).id, posted("a", t0, handedOver = false).id)
        // Ohne Schlüssel unterscheidet der Titel.
        assertNotEquals(posted("", t0, title = "Eins").id, posted("", t0, title = "Zwei").id)
        assertTrue(posted("a", t0).id.startsWith(Fallback.ID_PREFIX))
    }

    @Test
    fun grundInWorten() {
        assertEquals("", Fallback.reason(""))
        val texts = listOf(Fallback.VIA_RADAR, Fallback.VIA_NET, Fallback.VIA_TOPIC, "neu").map { Fallback.reason(it) }
        assertTrue(texts.all { it.startsWith("Über den Notweg aus dem Lagebericht.") })
        assertEquals(4, texts.toSet().size)

        // Beim öffentlichen Alarm gibt niemand ein Thema ein, es kann also auch nicht falsch sein.
        assertTrue(Fallback.reason(Fallback.VIA_TOPIC).contains("Thema"))
        val public = listOf(Fallback.VIA_RADAR, Fallback.VIA_NET, Fallback.VIA_TOPIC, "neu").map { Fallback.reason(it, public = true) }
        assertTrue(public.all { it.startsWith("Über den Notweg aus dem Lagebericht.") })
        assertTrue(public.none { it.contains("Thema") })
        assertEquals(4, public.toSet().size)
        assertEquals("", Fallback.reason("", public = true))
    }

    @Test
    fun grundInWortenOhneNamenDesDienstesInDerPlayFassung() {
        val wege = listOf(Fallback.VIA_RADAR, Fallback.VIA_NET, Fallback.VIA_TOPIC, "neu")
        for (public in listOf(true, false)) {
            val play = wege.map { Fallback.reason(it, public = public, play = true) }
            val github = wege.map { Fallback.reason(it, public = public, play = false) }
            // Die Fassung aus dem Play Store nennt den Dienst nicht beim Namen, sagt sonst aber dasselbe.
            assertTrue(play.none { it.contains("ntfy", ignoreCase = true) })
            assertEquals(3, github.count { it.contains("ntfy") })
            assertEquals(github.map { it.replace("an ntfy", "an den Push-Dienst").replace("ntfy", "Der Push-Dienst") }, play)
            assertEquals(4, play.toSet().size)
            assertEquals("", Fallback.reason("", public = public, play = true))
        }
        // Ohne Angabe gilt die Fassung, die gerade gebaut ist.
        assertEquals(Fallback.reason(Fallback.VIA_NET, play = BuildConfig.PLAY), Fallback.reason(Fallback.VIA_NET))
    }
}
