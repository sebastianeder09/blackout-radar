package io.github.sebastianeder09.blackoutradar

import java.io.File
import java.io.IOException
import java.io.OutputStream
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * Das Thema in der Installationsdatei der App.
 *
 * Die Datei bei GitHub ist für alle dieselbe und enthält kein Thema. Gibt ein eingerichtetes Handy die App
 * weiter, legt es sein Thema in eine Kopie der eigenen Installationsdatei. Die App am anderen Handy liest es
 * beim ersten Start aus ihrer Datei und richtet sich selbst ein, eintippen muss dort niemand etwas.
 *
 * Der Platz dafür ist der Signaturblock ("APK Signing Block"). Er steht zwischen den Dateien des Archivs und
 * dem Inhaltsverzeichnis. Die Signatur deckt die Dateien, das Inhaltsverzeichnis und den Schluss des Archivs
 * ab, vom Block selbst nur ihren eigenen Eintrag. Einträge mit unbekannter Kennung überliest Android. Die
 * Kopie bleibt deshalb gültig signiert: Sie lässt sich installieren und auch über eine vorhandene Fassung
 * spielen. Am Programm ändert sich dabei kein Byte.
 *
 * Aufbau des Blocks: seine Länge (8 Bytes), dann Einträge aus Länge (8), Kennung (4) und Inhalt, dann noch
 * einmal die Länge (8) und das Schlusswort "APK Sig Block 42" (16). Alle Zahlen stehen mit dem niedrigsten
 * Byte zuerst. Das Signierwerkzeug füllt den Block mit einem leeren Eintrag auf ein Vielfaches von 4096 Bytes
 * auf. In diesen Platz passt das Thema, die Datei wird dabei nicht größer.
 *
 * Diese Datei kennt Android nicht, damit die Tests auf dem Rechner laufen.
 */
object ApkTopic {
    /** Kennung des Eintrags mit dem Thema ("BRK1"). */
    const val ID = 0x42524B31

    /** Mehr als das fasst der Eintrag nicht. Ein Themenname hat höchstens 64 Zeichen, mit eigenem Server etwas mehr. */
    const val MAX_BYTES = 512

    /** Kennung des leeren Eintrags, mit dem das Signierwerkzeug den Block auffüllt. */
    private const val PADDING_ID = 0x42726577
    private const val PAGE = 4096

    /** So beginnt der Schluss eines Archivs ("End of Central Directory"). Ohne Kommentar ist er 22 Bytes lang. */
    private const val END_SIGNATURE = 0x06054B50
    private const val END_SIZE = 22
    private const val MAX_COMMENT = 0xFFFF

    /** Größer ist kein Signaturblock. Schützt vor unsinnigen Längenangaben in einer beschädigten Datei. */
    private const val MAX_BLOCK = 16L * 1024 * 1024
    private val MAGIC = "APK Sig Block 42".toByteArray(Charsets.US_ASCII)

    private class Entry(val id: Int, val value: ByteArray)

    /** Wo in der Datei was steht: Anfang des Signaturblocks, des Inhaltsverzeichnisses und des Schlusses. */
    private class Layout(val blockStart: Long, val dirStart: Long, val endStart: Long, val entries: List<Entry>)

    /**
     * Liest das Thema aus einer Installationsdatei. Null, wenn sie keines enthält, wenn sie nicht signiert
     * oder nicht so aufgebaut ist wie erwartet, oder wenn sie sich nicht lesen lässt.
     */
    fun read(apk: File): String? = try {
        RandomAccessFile(apk, "r").use { file ->
            val value = layout(file)?.entries?.firstOrNull { it.id == ID }?.value
            if (value == null || value.isEmpty() || value.size > MAX_BYTES) null else String(value, Charsets.UTF_8)
        }
    } catch (e: IOException) {
        null
    }

    /**
     * Schreibt nach [target] eine Kopie von [source], die [text] als Thema enthält. Ein Thema, das die Vorlage
     * schon mitbringt, wird ersetzt. Alles außerhalb des Signaturblocks bleibt Byte für Byte gleich, im
     * Schluss des Archivs ändert sich höchstens die Angabe, wo das Inhaltsverzeichnis beginnt.
     */
    @Throws(IOException::class)
    fun write(source: File, target: File, text: String) {
        val value = text.toByteArray(Charsets.UTF_8)
        if (value.isEmpty() || value.size > MAX_BYTES) throw IOException("Das Thema ist leer oder zu lang")
        RandomAccessFile(source, "r").use { file ->
            val layout = layout(file) ?: throw IOException("Die Installationsdatei hat keinen lesbaren Signaturblock")
            val block = block(layout.entries.filter { it.id != ID && it.id != PADDING_ID } + Entry(ID, value))
            val dirStart = layout.blockStart + block.size
            if (dirStart > 0xFFFFFFFFL) throw IOException("Die Installationsdatei ist zu groß")
            val end = ByteArray((file.length() - layout.endStart).toInt())
            file.seek(layout.endStart)
            file.readFully(end)
            ByteBuffer.wrap(end).order(ByteOrder.LITTLE_ENDIAN).putInt(16, dirStart.toInt())
            target.outputStream().buffered().use { out ->
                copy(file, 0L, layout.blockStart, out)
                out.write(block)
                copy(file, layout.dirStart, layout.endStart, out)
                out.write(end)
            }
        }
    }

    /** Baut den Signaturblock aus seinen Einträgen und füllt ihn auf, so wie es das Signierwerkzeug tut. */
    private fun block(entries: List<Entry>): ByteArray {
        var size = 8 + 24
        for (entry in entries) size += 12 + entry.value.size
        var padding = 0
        if (size % PAGE != 0) {
            padding = PAGE - size % PAGE
            if (padding < 12) padding += PAGE  // auch ein leerer Eintrag braucht 12 Bytes
            size += padding
        }
        val buffer = ByteBuffer.allocate(size).order(ByteOrder.LITTLE_ENDIAN)
        buffer.putLong(size - 8L)
        for (entry in entries) {
            buffer.putLong(entry.value.size + 4L)
            buffer.putInt(entry.id)
            buffer.put(entry.value)
        }
        if (padding > 0) {
            buffer.putLong(padding - 8L)
            buffer.putInt(PADDING_ID)
            buffer.position(buffer.position() + padding - 12)
        }
        buffer.putLong(size - 8L)
        buffer.put(MAGIC)
        return buffer.array()
    }

    /** Liest den Aufbau der Datei. Null, wenn sie kein Archiv mit Signaturblock ist oder die Angaben nicht zusammenpassen. */
    private fun layout(file: RandomAccessFile): Layout? {
        val endStart = findEnd(file) ?: return null
        val end = read(file, endStart, END_SIZE)
        val dirSize = end.getInt(12).toLong() and 0xFFFFFFFFL
        val dirStart = end.getInt(16).toLong() and 0xFFFFFFFFL
        // Android verlangt dasselbe: Das Inhaltsverzeichnis endet genau dort, wo der Schluss beginnt.
        if (dirStart + dirSize != endStart || dirStart < 8 + 24) return null
        val footer = read(file, dirStart - 24, 24)
        for (i in MAGIC.indices) if (footer.get(8 + i) != MAGIC[i]) return null
        val size = footer.getLong(0)
        if (size < 24 || size > MAX_BLOCK) return null
        val blockStart = dirStart - size - 8
        if (blockStart < 0) return null
        val block = read(file, blockStart, (size + 8).toInt())
        if (block.getLong(0) != size) return null
        val entries = ArrayList<Entry>()
        var pos = 8
        val stop = block.capacity() - 24
        while (pos < stop) {
            if (stop - pos < 12) return null
            val length = block.getLong(pos)
            if (length < 4 || length > stop - pos - 8) return null
            val value = ByteArray(length.toInt() - 4)
            block.position(pos + 12)
            block.get(value)
            entries.add(Entry(block.getInt(pos + 8), value))
            pos += 8 + length.toInt()
        }
        return Layout(blockStart, dirStart, endStart, entries)
    }

    /**
     * Sucht den Schluss des Archivs von hinten. Er steht ganz am Ende, hinter ihm folgt höchstens sein eigener
     * Kommentar, und dessen Länge muss genau bis zum Ende der Datei reichen.
     */
    private fun findEnd(file: RandomAccessFile): Long? {
        val length = file.length()
        if (length < END_SIZE) return null
        val size = minOf(length, (END_SIZE + MAX_COMMENT).toLong()).toInt()
        val tail = read(file, length - size, size)
        for (pos in size - END_SIZE downTo 0) {
            if (tail.getInt(pos) == END_SIGNATURE && (tail.getShort(pos + 20).toInt() and 0xFFFF) == size - pos - END_SIZE) {
                return length - size + pos
            }
        }
        return null
    }

    private fun read(file: RandomAccessFile, position: Long, size: Int): ByteBuffer {
        val bytes = ByteArray(size)
        file.seek(position)
        file.readFully(bytes)
        return ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN)
    }

    private fun copy(file: RandomAccessFile, from: Long, to: Long, out: OutputStream) {
        val buffer = ByteArray(64 * 1024)
        var left = to - from
        file.seek(from)
        while (left > 0) {
            val count = file.read(buffer, 0, minOf(left, buffer.size.toLong()).toInt())
            if (count < 0) throw IOException("Die Installationsdatei endet zu früh")
            out.write(buffer, 0, count)
            left -= count
        }
    }
}
