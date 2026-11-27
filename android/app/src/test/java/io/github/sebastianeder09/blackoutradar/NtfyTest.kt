package io.github.sebastianeder09.blackoutradar

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class NtfyTest {
    private val topic = "blackout-radar-abc123XYZ_ok"

    @Test
    fun themaInAllenUeblichenSchreibweisen() {
        val expected = Target("https://ntfy.sh", topic)
        for (input in listOf(
            topic,
            "  $topic \n",
            "https://ntfy.sh/$topic",
            "https://ntfy.sh/$topic/",
            "ntfy://ntfy.sh/$topic",
            "ntfy.sh/$topic",
            "HTTPS://NTFY.SH/$topic",
            "https://ntfy.sh/$topic?x=1",
            "`$topic`",
            "„$topic“",
        )) {
            assertEquals(input, expected, Ntfy.parseTarget(input))
        }
    }

    @Test
    fun eigenerServerMitPort() {
        assertEquals(Target("https://ntfy.example.org:8443", "alarm"), Ntfy.parseTarget("https://ntfy.example.org:8443/alarm"))
    }

    @Test
    fun unverschluesseltNurImTestbau() {
        assertNull(Ntfy.parseTarget("http://10.0.2.2:8765/thema"))
        assertEquals(Target("http://10.0.2.2:8765", "thema"), Ntfy.parseTarget("http://10.0.2.2:8765/thema", allowHttp = true))
    }

    @Test
    fun ungueltigeEingaben() {
        for (input in listOf("", "   ", "zwei worte", "ümlaut", "a/b/c", "https://ntfy.sh/", "ftp://ntfy.sh/x",
            "https://ntfy.sh/thema mit leerzeichen", "x".repeat(65), "javascript:alert(1)")) {
            assertNull(input, Ntfy.parseTarget(input))
        }
    }

    @Test
    fun linkDerApp() {
        val expected = Target("https://ntfy.sh", topic)
        for (link in listOf(
            "blackoutradar://abo/$topic",
            "blackoutradar://abo/$topic/",
            "BlackoutRadar://abo/$topic",
            "blackoutradar://abo?thema=$topic",
            "blackoutradar://abo?x=1&thema=$topic",
            "blackoutradar://$topic",
            "blackoutradar://abo?thema=https%3A%2F%2Fntfy.sh%2F$topic",
        )) {
            assertEquals(link, expected, Ntfy.parseLink(link))
            assertEquals(link, expected, Ntfy.parseTarget(link))
        }
        assertEquals(Target("https://ntfy.example.org:8443", "alarm"),
            Ntfy.parseLink("blackoutradar://abo?thema=https%3A%2F%2Fntfy.example.org%3A8443%2Falarm"))
    }

    @Test
    fun kaputteLinks() {
        for (link in listOf(
            "blackoutradar://abo",
            "blackoutradar://abo/",
            "blackoutradar://abo/zwei/teile",
            "blackoutradar://abo/ümlaut",
            "blackoutradar://abo?thema=",
            "blackoutradar://abo?thema=%zz",
            "blackoutradar://abo?thema=http%3A%2F%2F10.0.2.2%2Fx",
            "blackoutradar://abo?thema=blackoutradar%3A%2F%2Fabo%2Fx",
            "https://ntfy.sh/$topic",
            topic,
        )) {
            assertNull(link, Ntfy.parseLink(link))
        }
        // Ein kaputter Link im Text wird nicht stillschweigend als etwas anderes gelesen.
        assertNull(Ntfy.parseTarget("blackoutradar://abo/zwei/teile"))
    }

    @Test
    fun weitergegebeneNachrichtRichtetEin() {
        val url = "https://github.com/sebastianeder09/blackout-radar/releases/latest/download/blackout-radar.apk"
        for (target in listOf(Target("https://ntfy.sh", topic), Target("https://ntfy.example.org:8443", "alarm_1"))) {
            val text = Ntfy.shareText(target, url)
            assertTrue(text, url in text)
            assertEquals(target, Ntfy.parseTarget(text))
            // So kommt sie aus manchem Messenger zurück: mit Zusatz davor und Satzzeichen danach.
            assertEquals(target, Ntfy.parseTarget("Weitergeleitet:\n$text.\n\nLG"))
            assertEquals(target, Ntfy.parseLink(Ntfy.findLink(text)!!))
            assertEquals(target, Ntfy.parseTarget(Ntfy.plain(target)))
        }
        assertEquals(topic, Ntfy.plain(Target("https://ntfy.sh", topic)))
        assertNull(Ntfy.findLink("nur Text ohne Link, https://ntfy.sh/$topic"))
    }

    @Test
    fun adressenFuerDenServer() {
        val target = Target("https://ntfy.sh", "t1")
        assertEquals("https://ntfy.sh/t1/json?since=abc", Ntfy.streamUrl(target, "abc"))
        assertEquals("https://ntfy.sh/t1/json?since=all&poll=1", Ntfy.pollUrl(target, "all"))
    }

    @Test
    fun zeilenDesDatenstroms() {
        assertEquals(StreamEvent.Open, Ntfy.parseLine("""{"id":"a","time":1,"event":"open","topic":"t"}"""))
        assertEquals(StreamEvent.Keepalive, Ntfy.parseLine("""{"id":"b","time":2,"event":"keepalive","topic":"t"}"""))
        assertNull(Ntfy.parseLine(""))
        assertNull(Ntfy.parseLine("kein json"))
        assertEquals(StreamEvent.Other, Ntfy.parseLine("""{"event":"poll_request"}"""))

        val event = Ntfy.parseLine(
            """{"id":"xYz","time":1795776325,"expires":1795819525,"event":"message","topic":"t",""" +
                """"title":"Netzfrequenz-Alarm: 49,31 Hz","message":"Zeile 1\nZeile 2","priority":5,""" +
                """"tags":["rotating_light"],"click":"https://example.org/status.md"}""")
        assertTrue(event is StreamEvent.Message)
        val notice = (event as StreamEvent.Message).notice
        assertEquals("xYz", notice.id)
        assertEquals(1795776325L, notice.time)
        assertEquals("Netzfrequenz-Alarm: 49,31 Hz", notice.title)
        assertEquals("Zeile 1\nZeile 2", notice.message)
        assertEquals(5, notice.priority)
        assertEquals(listOf("rotating_light"), notice.tags)
        assertEquals("https://example.org/status.md", notice.click)
        assertEquals("alarm", notice.level)
    }

    @Test
    fun fehlendeFelderBekommenStandardwerte() {
        val notice = (Ntfy.parseLine("""{"id":"q","time":5,"event":"message","topic":"t","message":"nur Text","title":null}""")
            as StreamEvent.Message).notice
        assertEquals("", notice.title)
        assertEquals(3, notice.priority)
        assertEquals(emptyList<String>(), notice.tags)
        assertEquals("", notice.click)
        assertEquals("info", notice.level)
        assertEquals("Blackout-Radar", Ntfy.displayTitle(notice))
        assertEquals(StreamEvent.Other, Ntfy.parseLine("""{"time":5,"event":"message","topic":"t"}"""))
    }

    @Test
    fun stufenWieImRadar() {
        fun level(priority: Int, vararg tags: String) = Notice("i", 0, "", "", priority, tags.toList(), "").level
        assertEquals("alarm", level(5, "rotating_light"))
        assertEquals("warn", level(4, "warning"))
        assertEquals("ok", level(3, "white_check_mark"))
        assertEquals("info", level(3, "zap"))
        assertEquals("daily", level(2, "bar_chart"))
        assertEquals("daily", level(1))
    }

    @Test
    fun symboleUndTitel() {
        val notice = Notice("i", 0, "Stromausfall: Oberösterreich", "", 4, listOf("warning", "unbekannt"), "")
        assertEquals("⚠️ Stromausfall: Oberösterreich", Ntfy.displayTitle(notice))
    }

    @Test
    fun themaWirdVerdeckt() {
        assertEquals("blac…uz5", Ntfy.mask("blackout-radar-1234567890uz5"))
        assertEquals("•••••", Ntfy.mask("kurz1"))
    }

    @Test
    fun wartezeitenWachsenBisZurGrenze() {
        val steps = (1..12).map { Backoff.delayMs(it) }
        assertEquals(2_000L, steps.first())
        assertEquals(300_000L, steps.last())
        assertTrue(steps.zipWithNext().all { (a, b) -> b >= a })
        assertEquals(Backoff.RATE_LIMIT_MS, Backoff.delayMs(1, rateLimited = true))
        assertEquals(2_400L, Backoff.delayMs(1, jitter = 1.0))
        assertEquals(2_000L, Backoff.delayMs(0))
    }
}
