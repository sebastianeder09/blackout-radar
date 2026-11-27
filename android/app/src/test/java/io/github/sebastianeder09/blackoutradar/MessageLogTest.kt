package io.github.sebastianeder09.blackoutradar

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
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
}
