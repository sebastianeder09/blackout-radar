package io.github.sebastianeder09.blackoutradar

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class RulesTest {
    private val hour = 60 * 60_000L

    @Test
    fun kanalNachDringlichkeitUndAlter() {
        assertEquals(Alerts.CH_ALARM_LOUD, Alerts.channelFor(5, loud = true, ageMs = 0))
        assertEquals(Alerts.CH_ALARM, Alerts.channelFor(5, loud = false, ageMs = 0))
        assertEquals(Alerts.CH_ALARM_LOUD, Alerts.channelFor(5, loud = true, ageMs = 2 * hour))
        // Was erst Stunden später ankommt, läutet nicht mehr als Alarm.
        assertEquals(Alerts.CH_INFO, Alerts.channelFor(5, loud = true, ageMs = 4 * hour))
        assertEquals(Alerts.CH_WARN, Alerts.channelFor(4, loud = true, ageMs = 0))
        assertEquals(Alerts.CH_INFO, Alerts.channelFor(4, loud = true, ageMs = 4 * hour))
        assertEquals(Alerts.CH_INFO, Alerts.channelFor(3, loud = true, ageMs = 0))
        assertEquals(Alerts.CH_QUIET, Alerts.channelFor(2, loud = true, ageMs = 0))
        assertEquals(Alerts.CH_QUIET, Alerts.channelFor(1, loud = true, ageMs = 0))
    }

    @Test
    fun radarStehtStill() {
        val now = 1_000 * hour
        assertFalse(MonitorWatch.isStale(now, 0))
        assertFalse(MonitorWatch.isStale(now, now - 2 * hour))
        assertTrue(MonitorWatch.isStale(now, now - 3 * hour))
        assertTrue(MonitorWatch.shouldWarn(now, now - 4 * hour, lastWarnedMs = 0))
        assertFalse(MonitorWatch.shouldWarn(now, now - 4 * hour, lastWarnedMs = now - 2 * hour))
        assertTrue(MonitorWatch.shouldWarn(now, now - 20 * hour, lastWarnedMs = now - 13 * hour))
        assertFalse(MonitorWatch.shouldWarn(now, now - hour, lastWarnedMs = 0))
    }

    @Test
    fun zeitspannenWieImLagebericht() {
        assertEquals("0 min", MonitorWatch.age(-5))
        assertEquals("45 min", MonitorWatch.age(45 * 60_000L))
        assertEquals("3 h 05 min", MonitorWatch.age(3 * hour + 5 * 60_000L))
        assertEquals("2 T 4 h", MonitorWatch.age(52 * hour))
    }

    @Test
    fun vorgeschichteNachEinrichtenOhneNetz() {
        fun notice(id: String, time: Long) = Notice(id, time, "Titel $id", "Text", 5, emptyList(), "")
        val setup = 1_000_000L
        val all = listOf(notice("alt", setup - 3_600), notice("knapp", setup - 1), notice("gleich", setup), notice("neu", setup + 5))
        // Still in die Liste kommt nur, was vor dem Einrichten kam. Alles ab dann läutet über die Verbindung.
        assertEquals(listOf("alt", "knapp"), History.before(all, setup).map { it.id })
        assertTrue(History.before(emptyList(), setup).isEmpty())
        // ntfy.sh bewahrt Meldungen 12 Stunden auf. Danach gibt es nichts mehr nachzuholen.
        assertFalse(History.expired(setup + 11 * 3_600, setup))
        assertTrue(History.expired(setup + 13 * 3_600, setup))
    }

    @Test
    fun nummerDerVeroeffentlichung() {
        assertEquals(12, Updates.parseBuild("app-v12"))
        assertEquals(7, Updates.parseBuild(" app-v7 "))
        assertEquals(0, Updates.parseBuild("v12"))
        assertEquals(0, Updates.parseBuild("app-v"))
        assertEquals(0, Updates.parseBuild("app-v12-beta"))
    }
}
