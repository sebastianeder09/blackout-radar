package io.github.sebastianeder09.blackoutradar

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.IOException
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.Random
import java.util.zip.ZipEntry
import java.util.zip.ZipFile
import java.util.zip.ZipOutputStream

/**
 * Das Thema in der Installationsdatei. Die Dateien hier sind nachgebaut: Dateien des Archivs, Signaturblock,
 * Inhaltsverzeichnis, Schluss. Den Block bauen und zerlegen die Tests mit eigenem Code, nicht mit dem der App.
 * Dass Android eine echte Datei mit Thema annimmt, prüft der Emulator-Test.
 */
class ApkTopicTest {
    @get:Rule
    val folder = TemporaryFolder()

    private val v2 = 0x7109871A          // Signatur v2
    private val deps = 0x504B4453        // Angaben zum Bau, wie sie das Android-Plugin dazulegt
    private val padding = 0x42726577     // leerer Eintrag zum Auffüllen
    private val magic = "APK Sig Block 42".toByteArray(Charsets.US_ASCII)

    private fun bytes(size: Int, seed: Long): ByteArray = ByteArray(size).also { Random(seed).nextBytes(it) }

    private fun le(size: Int): ByteBuffer = ByteBuffer.allocate(size).order(ByteOrder.LITTLE_ENDIAN)

    private fun le(data: ByteArray): ByteBuffer = ByteBuffer.wrap(data).order(ByteOrder.LITTLE_ENDIAN)

    /** Ein Signaturblock aus seinen Einträgen, ohne Auffüllen. */
    private fun block(entries: List<Pair<Int, ByteArray>>): ByteArray {
        val body = ByteArrayOutputStream()
        for ((id, value) in entries) {
            body.write(le(12).putLong(value.size + 4L).putInt(id).array())
            body.write(value)
        }
        val size = body.size() + 24L
        return le(8).putLong(size).array() + body.toByteArray() + le(8).putLong(size).array() + magic
    }

    /** Wie das Signierwerkzeug: Ein leerer Eintrag bringt den Block auf ein Vielfaches von 4096 Bytes. */
    private fun padded(entries: List<Pair<Int, ByteArray>>): List<Pair<Int, ByteArray>> {
        val size = block(entries).size
        if (size % 4096 == 0) return entries
        var gap = 4096 - size % 4096
        if (gap < 12) gap += 4096
        return entries + (padding to ByteArray(gap - 12))
    }

    private val signature = bytes(1897, 2)
    private val buildInfo = bytes(343, 3)
    private val usual = listOf(v2 to signature, deps to buildInfo)

    /** Der Schluss des Archivs: 22 Bytes und ein Kommentar. */
    private fun end(dirSize: Int, dirStart: Int, comment: ByteArray): ByteArray =
        le(22).putInt(0x06054B50).putShort(0).putShort(0).putShort(3).putShort(3)
            .putInt(dirSize).putInt(dirStart).putShort(comment.size.toShort()).array() + comment

    /** Eine nachgebaute Installationsdatei. Ohne [entries] fehlt der Signaturblock. */
    private fun archive(
        entries: List<Pair<Int, ByteArray>>? = padded(usual),
        files: ByteArray = bytes(5000, 1),
        directory: ByteArray = bytes(300, 4),
        comment: ByteArray = ByteArray(0),
    ): ByteArray {
        val block = entries?.let { block(it) } ?: ByteArray(0)
        return files + block + directory + end(directory.size, files.size + block.size, comment)
    }

    private class Parts(val files: ByteArray, val entries: List<Pair<Int, ByteArray>>, val blockSize: Int,
        val directory: ByteArray, val end: ByteArray)

    /** Zerlegt eine Datei wieder. Verlangt, dass alle Angaben zusammenpassen. */
    private fun parts(data: ByteArray, comment: Int = 0): Parts {
        val endStart = data.size - 22 - comment
        val end = data.copyOfRange(endStart, data.size)
        assertEquals("Kennung des Schlusses", 0x06054B50, le(end).getInt(0))
        val dirSize = le(end).getInt(12)
        val dirStart = le(end).getInt(16)
        assertEquals("Das Inhaltsverzeichnis endet am Schluss", endStart, dirStart + dirSize)
        assertArrayEquals("Schlusswort des Blocks", magic, data.copyOfRange(dirStart - 16, dirStart))
        val size = le(data).getLong(dirStart - 24).toInt()
        val blockStart = dirStart - size - 8
        assertEquals("Länge vorne und hinten gleich", size.toLong(), le(data).getLong(blockStart))
        val entries = ArrayList<Pair<Int, ByteArray>>()
        var pos = blockStart + 8
        while (pos < dirStart - 24) {
            val length = le(data).getLong(pos).toInt()
            entries.add(le(data).getInt(pos + 8) to data.copyOfRange(pos + 12, pos + 8 + length))
            pos += 8 + length
        }
        assertEquals("Die Einträge füllen den Block genau", dirStart - 24, pos)
        return Parts(data.copyOfRange(0, blockStart), entries, size + 8, data.copyOfRange(dirStart, endStart), end)
    }

    private fun file(name: String, data: ByteArray): File = File(folder.root, name).also { it.writeBytes(data) }

    private fun withTopic(data: ByteArray, text: String, name: String = "mit.apk"): ByteArray {
        val target = File(folder.root, name)
        ApkTopic.write(file("vorlage-$name", data), target, text)
        return target.readBytes()
    }

    private fun topicOf(data: ByteArray, name: String = "lesen.apk"): String? {
        val file = File(folder.root, name)
        file.writeBytes(data)
        return ApkTopic.read(file)
    }

    @Test
    fun dateiVonGithubBringtKeinThemaMit() {
        assertNull(topicOf(archive()))
    }

    @Test
    fun themaKommtWiederHeraus() {
        assertEquals("blackout-radar-beispiel", topicOf(withTopic(archive(), "blackout-radar-beispiel")))
        assertEquals("https://ntfy.example.org/mein_thema-1", topicOf(withTopic(archive(), "https://ntfy.example.org/mein_thema-1", "b.apk")))
    }

    @Test
    fun dateiWirdNichtGroesser() {
        val before = archive()
        val after = withTopic(before, "blackout-radar-beispiel")
        assertEquals(before.size, after.size)
        assertEquals(4096, parts(before).blockSize)
        assertEquals(4096, parts(after).blockSize)
    }

    @Test
    fun ausserhalbDesBlocksBleibtJedesByte() {
        val before = parts(archive())
        val after = parts(withTopic(archive(), "blackout-radar-beispiel"))
        assertArrayEquals("Dateien des Archivs", before.files, after.files)
        assertArrayEquals("Inhaltsverzeichnis", before.directory, after.directory)
        assertArrayEquals("Schluss des Archivs", before.end, after.end)
    }

    @Test
    fun signaturBleibtUndDasThemaStehtDahinter() {
        val after = parts(withTopic(archive(), "blackout-radar-beispiel"))
        assertEquals(listOf(v2, deps, ApkTopic.ID, padding), after.entries.map { it.first })
        assertArrayEquals(signature, after.entries[0].second)
        assertArrayEquals(buildInfo, after.entries[1].second)
        assertArrayEquals("blackout-radar-beispiel".toByteArray(), after.entries[2].second)
        assertTrue("Der Fülleintrag ist leer", after.entries[3].second.all { it == 0.toByte() })
    }

    @Test
    fun vorhandenesThemaWirdErsetzt() {
        val first = withTopic(archive(), "erstes-thema")
        val second = withTopic(first, "zweites-thema", "zweite.apk")
        assertEquals("zweites-thema", topicOf(second))
        assertEquals(1, parts(second).entries.count { it.first == ApkTopic.ID })
        assertEquals(first.size, second.size)
    }

    @Test
    fun gleichesThemaErgibtDieselbeDatei() {
        val first = withTopic(archive(), "blackout-radar-beispiel")
        assertArrayEquals(first, withTopic(first, "blackout-radar-beispiel", "noch-einmal.apk"))
    }

    @Test
    fun ohneFuelleintragWaechstDerBlockUndDerSchlussZeigtRichtig() {
        val before = archive(entries = usual)
        assertTrue(parts(before).blockSize % 4096 != 0)
        val after = withTopic(before, "blackout-radar-beispiel")
        val result = parts(after)  // prüft auch, dass der Schluss auf das verschobene Inhaltsverzeichnis zeigt
        assertEquals(0, result.blockSize % 4096)
        assertEquals("blackout-radar-beispiel", topicOf(after))
        assertArrayEquals(parts(before).files, result.files)
        assertArrayEquals(parts(before).directory, result.directory)
    }

    @Test
    fun bleibtZuWenigPlatzKommtEineSeiteDazu() {
        // So viel Inhalt, dass nach dem Thema nur noch wenige Bytes bis zur Seitengrenze fehlen. Ein leerer Eintrag
        // braucht 12 Bytes: Fehlen 1 bis 11, passt er nicht mehr hinein, und der Block wächst um eine Seite.
        val topic = "blackout-radar-beispiel"
        for (gap in 0..13) {
            val used = block(usual + (ApkTopic.ID to topic.toByteArray())).size
            val filler = 0x11223344 to ByteArray(4096 - used - 12 - gap)
            val after = withTopic(archive(entries = padded(usual + filler)), topic, "rand-$gap.apk")
            val result = parts(after)
            assertEquals("Lücke $gap", 0, result.blockSize % 4096)
            assertEquals("Lücke $gap", if (gap in 1..11) 8192 else 4096, result.blockSize)
            assertEquals(topic, topicOf(after, "rand-lesen-$gap.apk"))
            assertArrayEquals(filler.second, result.entries.first { it.first == filler.first }.second)
        }
    }

    @Test
    fun kommentarAmSchlussBleibtErhalten() {
        val comment = "Ein Kommentar am Ende des Archivs".toByteArray()
        val before = archive(comment = comment)
        val after = withTopic(before, "blackout-radar-beispiel")
        assertEquals("blackout-radar-beispiel", topicOf(after))
        assertArrayEquals(parts(before, comment.size).end, parts(after, comment.size).end)
    }

    @Test
    fun laengeDesThemasIstBegrenzt() {
        val longest = "a".repeat(ApkTopic.MAX_BYTES)
        assertEquals(longest, topicOf(withTopic(archive(), longest)))
        for (text in listOf("", longest + "a")) {
            try {
                withTopic(archive(), text, "grenze-${text.length}.apk")
                fail("Ein Thema mit ${text.length} Zeichen darf nicht in die Datei")
            } catch (e: IOException) {
                // so soll es sein
            }
        }
    }

    @Test
    fun wasKeineInstallationsdateiIstBringtNichts() {
        val plainZip = archive(entries = null)
        val candidates = mapOf(
            "leer" to ByteArray(0),
            "kurz" to bytes(10, 5),
            "zufall" to bytes(20_000, 6),
            "ohne-block" to plainZip,
        )
        for ((name, data) in candidates) {
            assertNull(name, topicOf(data, "$name.apk"))
            try {
                withTopic(data, "blackout-radar-beispiel", "$name-ziel.apk")
                fail("$name: In eine solche Datei lässt sich kein Thema legen")
            } catch (e: IOException) {
                // so soll es sein
            }
        }
        assertNull(ApkTopic.read(File(folder.root, "gibt-es-nicht.apk")))
    }

    @Test
    fun unstimmigeAngabenErgebenKeinThema() {
        val good = withTopic(archive(), "blackout-radar-beispiel")
        val blockStart = 5000
        val dirStart = blockStart + 4096
        fun broken(change: (ByteBuffer) -> Unit): ByteArray = good.copyOf().also { change(le(it)) }
        val cases = mapOf(
            "Länge vorne anders als hinten" to broken { it.putLong(blockStart, 4000L) },
            "Block größer als die Datei" to broken { it.putLong(dirStart - 24, 1L shl 40) },
            "Block reicht vor den Anfang der Datei" to broken { it.putLong(dirStart - 24, 10_000L) },
            "Eintrag länger als der Block" to broken { it.putLong(blockStart + 8, 5000L) },
            "Eintrag kürzer als seine Kennung" to broken { it.putLong(blockStart + 8, 3L) },
            "Schlusswort verändert" to broken { it.put(dirStart - 1, 0) },
            "Inhaltsverzeichnis endet nicht am Schluss" to broken { it.putInt(good.size - 22 + 12, 299) },
            "Inhaltsverzeichnis beginnt hinter der Datei" to broken { it.putInt(good.size - 22 + 16, -1) },
        )
        for ((name, data) in cases) assertNull(name, topicOf(data, "kaputt.apk"))
    }

    @Test
    fun beschaedigteDateienBringenDieAppNichtZuFall() {
        val good = withTopic(archive(), "blackout-radar-beispiel")
        val random = Random(7)
        val file = File(folder.root, "beschaedigt.apk")
        val copy = File(folder.root, "beschaedigt-kopie.apk")
        repeat(3000) { round ->
            val data = good.copyOf()
            // Ein bis drei Bytes im Block, im Inhaltsverzeichnis oder im Schluss verändern, manchmal das Ende abschneiden.
            repeat(1 + random.nextInt(3)) { data[5000 + random.nextInt(data.size - 5000)] = random.nextInt(256).toByte() }
            val cut = if (round % 10 == 0) random.nextInt(data.size) else data.size
            file.writeBytes(data.copyOf(cut))
            ApkTopic.read(file)  // darf alles liefern, aber nichts werfen
            try {
                ApkTopic.write(file, copy, "anderes-thema")
                assertEquals("Runde $round", "anderes-thema", ApkTopic.read(copy))
            } catch (e: IOException) {
                // eine unlesbare Vorlage wird abgelehnt
            }
        }
    }

    @Test
    fun echtesArchivBleibtLesbar() {
        // Ein echtes ZIP-Archiv, in das wie beim Signieren ein Block vor das Inhaltsverzeichnis kommt.
        val contents = mapOf("classes.dex" to bytes(3000, 8), "AndroidManifest.xml" to bytes(700, 9), "assets/www/app.js" to bytes(9000, 10))
        val zip = ByteArrayOutputStream()
        ZipOutputStream(zip).use { out ->
            for ((name, data) in contents) {
                out.putNextEntry(ZipEntry(name))
                out.write(data)
                out.closeEntry()
            }
        }
        val plain = zip.toByteArray()
        val endStart = plain.size - 22
        val dirStart = le(plain).getInt(endStart + 16)
        val block = block(usual)
        val signed = plain.copyOfRange(0, dirStart) + block + plain.copyOfRange(dirStart, endStart) +
            plain.copyOfRange(endStart, plain.size).also { le(it).putInt(16, dirStart + block.size) }

        val target = File(folder.root, "echt-mit-thema.apk")
        ApkTopic.write(file("echt.apk", signed), target, "blackout-radar-beispiel")
        assertEquals("blackout-radar-beispiel", ApkTopic.read(target))
        ZipFile(target).use { archive ->
            assertEquals(contents.keys, archive.entries().asSequence().map { it.name }.toSet())
            for ((name, data) in contents) {
                assertArrayEquals(name, data, archive.getInputStream(archive.getEntry(name)).use { it.readBytes() })
            }
        }
    }
}
