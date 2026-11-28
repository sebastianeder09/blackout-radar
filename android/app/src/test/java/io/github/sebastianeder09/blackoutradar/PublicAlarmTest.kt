package io.github.sebastianeder09.blackoutradar

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Der öffentliche Alarm: Unter dem Thema kann jeder etwas hinschicken. In die App kommt nur, was der Radar
 * unterschrieben hat, und zwar mit den unterschriebenen Angaben.
 */
class PublicAlarmTest {
    private val good = Vectors.case("gültig")

    /** Der Zeitpunkt, zu dem der Radar die Beispiele erstellt hat. */
    private val created = good.expect!!.getLong("t")
    private val hour = 3600L

    private fun open(case: Vector, time: Long = created + 5, priority: Int = 3, tags: List<String> = emptyList()) =
        PublicAlarm.open(case.raw(time, priority, tags), case.topic, Vectors.keys)

    @Test
    fun gepruefteMeldung() {
        val notice = open(good)!!
        assertEquals("pub:$created:AT-20261126T1100:start:1", notice.id)
        assertEquals(created, notice.time)
        assertEquals(good.title, notice.title)
        // Die Zeile mit der Unterschrift gehört nicht zum Text, den die App zeigt.
        assertEquals(good.expect!!.getString("body"), notice.message)
        assertFalse(notice.message.contains("br1."))
        assertEquals(5, notice.priority)
        assertEquals(listOf("rotating_light"), notice.tags)
        assertEquals("alarm", notice.level)
        assertEquals(good.click, notice.click)
        assertTrue(notice.public)
        assertFalse(notice.fallback)
    }

    @Test
    fun kennung() {
        assertEquals("pub:5:a:b", PublicAlarm.id(5, "a:b"))
        assertTrue(Notice(PublicAlarm.id(5, "x"), 5, "t", "m", 3, emptyList(), "").public)
        assertFalse(Notice("AbCdEf123", 5, "t", "m", 3, emptyList(), "").public)
        assertFalse(Notice(Fallback.ID_PREFIX + "5:x", 5, "t", "m", 3, emptyList(), "", via = "radar").public)
    }

    @Test
    fun dringlichkeitKommtAusDerUnterschrift() {
        // Als Hinweis unterschrieben, bei ntfy als Alarm eingeliefert: Es bleibt ein Hinweis.
        val quiet = open(Vectors.case("gültig, Zeile im Text zählt nicht"), priority = 5, tags = listOf("rotating_light"))!!
        assertEquals(3, quiet.priority)
        assertEquals(listOf("zap"), quiet.tags)
        assertEquals("info", quiet.level)

        val daily = open(Vectors.case("gültig, tägliche Übersicht"), priority = 5, tags = listOf("rotating_light"))!!
        assertEquals(2, daily.priority)
        assertEquals(listOf("bar_chart"), daily.tags)
        assertEquals("daily", daily.level)

        // Umgekehrt: Ein Alarm bleibt ein Alarm, auch wenn ihn jemand leise weiterreicht.
        val loud = open(good, priority = 1, tags = listOf("bar_chart"))!!
        assertEquals(5, loud.priority)
        assertEquals("alarm", loud.level)
    }

    @Test
    fun dringlichkeitenDesRadars() {
        assertEquals(listOf(5, 4, 3, 3, 2), listOf("alarm", "warn", "info", "ok", "daily").map { Levels.priority(it) })
        assertEquals(listOf("rotating_light"), Levels.tags("alarm"))
        assertEquals(listOf("white_check_mark"), Levels.tags("ok"))
        // Was die App so anzeigt, stuft sie auch wieder so ein.
        for (level in listOf("alarm", "warn", "info", "ok", "daily")) {
            assertEquals(level, Notice("x", 1, "t", "m", Levels.priority(level), Levels.tags(level), "").level)
        }
        // Eine Dringlichkeit, die diese App noch nicht kennt, gilt als gewöhnliche Meldung.
        assertEquals(3, Levels.priority("neu"))
        assertEquals(emptyList<String>(), Levels.tags("neu"))
    }

    @Test
    fun zeitKommtAusDerUnterschrift() {
        // ntfy nennt den Zeitpunkt, zu dem es die Meldung angenommen hat. Für die App zählt, wann der Radar sie erstellt hat.
        assertEquals(created, open(good, time = created + 40 * 60)!!.time)
        assertEquals(created, open(good, time = created - 90)!!.time)
    }

    @Test
    fun wasNichtUnterschriebenIstFaelltWeg() {
        val invalid = Vectors.cases.filter { !it.valid }
        assertTrue(invalid.size >= 20)
        for (case in invalid) assertNull(case.name, open(case, priority = 5, tags = listOf("rotating_light")))
        val plain = Notice("x1", created, "Blackout: Österreich", "Ganz Österreich ohne Strom!", 5, listOf("rotating_light"), "")
        assertNull(PublicAlarm.open(plain, good.topic, Vectors.keys))
        assertNull(PublicAlarm.open(plain.copy(message = ""), good.topic, Vectors.keys))
    }

    @Test
    fun jedesGueltigeBeispielKommtAn() {
        for (case in Vectors.cases.filter { it.valid }) {
            val notice = open(case)
            assertNotNull(case.name, notice)
            assertEquals(case.name, case.expect!!.getString("body"), notice!!.message)
            assertEquals(case.name, PublicAlarm.id(created, case.expect.getString("i")), notice.id)
        }
    }

    @Test
    fun dieEchteAppNimmtDenTestschluesselNicht() {
        // Der geheime Teil des Testschlüssels ist allgemein bekannt: Damit kann jeder unterschreiben.
        val real = mapOf("k1" to Signed.KEYS.getValue("k1"))
        assertNull(PublicAlarm.open(good.raw(created + 5), good.topic, real))
        assertNotNull(PublicAlarm.open(good.raw(created + 5), good.topic, Vectors.keys))
    }

    @Test
    fun andereThemenGeltenNicht() {
        // Eine echte Meldung, in ein anderes Thema kopiert, gilt dort nicht.
        assertNull(PublicAlarm.open(good.raw(created + 5), "anderes-thema", Vectors.keys))
        assertNotNull(PublicAlarm.open(good.raw(created + 5), PublicAlarm.TOPIC, Vectors.keys))
        assertEquals(PublicAlarm.TOPIC, good.topic)
    }

    @Test
    fun alteEchteMeldungNeuEingespielt() {
        // Der Radar versucht den Versand 12 Stunden lang. So spät darf ntfy eine Meldung noch bekommen haben.
        assertNotNull(open(good, time = created))
        assertNotNull(open(good, time = created + 12 * hour))
        assertNotNull(open(good, time = created + PublicAlarm.MAX_DELAY_S))
        // Später ist es keine Zustellung des Radars mehr, sondern eine alte Meldung, die jemand noch einmal schickt.
        assertNull(open(good, time = created + PublicAlarm.MAX_DELAY_S + 1))
        assertNull(open(good, time = created + 3 * 24 * hour))
    }

    @Test
    fun dieselbeMeldungTraegtImmerDieselbeKennung() {
        val first = open(good, time = created + 5)!!
        // Noch einmal eingespielt: Bei ntfy ist es eine neue Zeile mit neuer Kennung, für die App dieselbe Meldung.
        val again = PublicAlarm.open(good.raw(created + hour).copy(id = "andere-zeile"), good.topic, Vectors.keys)!!
        assertEquals(first, again)
        // Auch in der zweiten Form derselben Unterschrift.
        assertEquals(first, open(Vectors.case("gültig, zweite Form derselben Unterschrift")))
        // Dieselbe Kennung trägt die Meldung über den Notweg aus dem Lagebericht.
        val posted = Posted("AT-20261126T1100:start:1", created, good.title, "Text", "alarm", handedOver = false, public = true)
        assertEquals(first.id, posted.id)
        assertEquals(first.id, Fallback.notice(posted, Fallback.VIA_RADAR, "https://example.org").id)
    }
}
