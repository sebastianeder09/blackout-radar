package io.github.sebastianeder09.blackoutradar

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class MessageLogTest {
    @get:Rule
    val folder = TemporaryFolder()

    private fun notice(id: String, time: Long, priority: Int = 3) =
        Notice(id, time, "Titel $id", "Text $id\nzweite Zeile", priority, listOf("zap"), "")

    @Test
    fun jedeMeldungNurEinmal() {
        val log = MessageLog(folder.newFile("m.json"))
        assertTrue(log.add(notice("a", 10)))
        assertFalse(log.add(notice("a", 10)))
        assertEquals(1, log.all().size)
    }

    @Test
    fun neuesteZuerstAuchBeiVertauschterAnkunft() {
        val log = MessageLog(folder.newFile("m.json"))
        log.add(notice("b", 20))
        log.add(notice("a", 10))
        log.add(notice("c", 30))
        assertEquals(listOf("c", "b", "a"), log.all().map { it.id })
        assertEquals("c", log.newestId())
    }

    @Test
    fun bleibtNachNeustartErhalten() {
        val file = folder.newFile("m.json")
        MessageLog(file).apply {
            add(notice("a", 10, priority = 5))
            add(notice("b", 20))
        }
        val again = MessageLog(file)
        assertEquals(listOf("b", "a"), again.all().map { it.id })
        assertEquals(5, again.all()[1].priority)
        assertEquals("Text a\nzweite Zeile", again.all()[1].message)
        assertFalse(again.add(notice("a", 10)))
    }

    @Test
    fun aeltesteFallenWeg() {
        val log = MessageLog(folder.newFile("m.json"), limit = 3)
        for (i in 1..5) log.add(notice("n$i", i.toLong()))
        assertEquals(listOf("n5", "n4", "n3"), log.all().map { it.id })
    }

    @Test
    fun kaputteDateiStoertNicht() {
        val file = folder.newFile("m.json")
        file.writeText("{kaputt")
        val log = MessageLog(file)
        assertEquals(0, log.all().size)
        assertTrue(log.add(notice("a", 1)))
        assertEquals(1, MessageLog(file).all().size)
    }

    @Test
    fun leeren() {
        val file = folder.newFile("m.json")
        val log = MessageLog(file)
        log.add(notice("a", 1))
        log.clear()
        assertEquals(0, log.all().size)
        assertEquals(0, MessageLog(file).all().size)
        assertTrue(log.add(notice("a", 1)))
    }

    @Test
    fun zustellungErsetztDenEintragDesNotwegs() {
        val log = MessageLog(folder.newFile("m.json"))
        log.add(notice("alt", 5))
        log.add(notice("notweg:20:e1", 20).copy(via = "radar"))
        // Dieselbe Meldung kommt doch noch über ntfy: Sie tritt an die Stelle des Eintrags.
        assertTrue(log.replace("notweg:20:e1", notice("ntfy1", 25)))
        assertEquals(listOf("ntfy1", "alt"), log.all().map { it.id })
        assertFalse(log.all().any { it.fallback })
        // Kommt sie ein zweites Mal, ändert sich nichts mehr, und ein anderer Eintrag bleibt stehen.
        log.add(notice("notweg:30:e2", 30).copy(via = "netz"))
        assertFalse(log.replace("notweg:30:e2", notice("ntfy1", 25)))
        assertEquals(listOf("notweg:30:e2", "ntfy1", "alt"), log.all().map { it.id })
        // Ein Eintrag, den es nicht gibt, stört nicht.
        assertTrue(log.replace("gibt-es-nicht", notice("ntfy2", 40)))
        assertEquals(4, log.all().size)
    }

    @Test
    fun zustellungMitGleicherKennungTrittAnDieStelleDesNotwegs() {
        // Beim öffentlichen Alarm trägt eine Meldung auf jedem Weg dieselbe Kennung.
        val file = folder.newFile("m.json")
        val log = MessageLog(file)
        log.add(notice("alt", 5))
        log.add(notice("pub:20:e1", 20).copy(via = "radar", message = "aus dem Lagebericht"))
        assertTrue(log.find("pub:20:e1")!!.fallback)
        // Ohne Auftrag zum Ersetzen bleibt der Eintrag, wie er ist.
        assertFalse(log.add(notice("pub:20:e1", 20)))
        assertTrue(log.find("pub:20:e1")!!.fallback)
        // Die geprüfte Zustellung über ntfy tritt an seine Stelle.
        assertTrue(log.replace("pub:20:e1", notice("pub:20:e1", 20)))
        assertEquals(listOf("pub:20:e1", "alt"), log.all().map { it.id })
        assertFalse(log.find("pub:20:e1")!!.fallback)
        assertEquals("Text pub:20:e1\nzweite Zeile", log.find("pub:20:e1")!!.message)
        assertNull(log.find("gibt-es-nicht"))
        // So steht es auch nach einem Neustart in der Datei.
        assertEquals(listOf(false, false), MessageLog(file).all().map { it.fallback })
    }

    @Test
    fun wegBleibtNachNeustartErhalten() {
        val file = folder.newFile("m.json")
        MessageLog(file).apply {
            add(notice("a", 10))
            add(notice("notweg:20:e1", 20).copy(via = "thema"))
        }
        val again = MessageLog(file).all()
        assertEquals(listOf("thema", ""), again.map { it.via })
        assertEquals(listOf(true, false), again.map { it.fallback })
    }
}
