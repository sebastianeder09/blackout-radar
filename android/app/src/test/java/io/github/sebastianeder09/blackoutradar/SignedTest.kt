package io.github.sebastianeder09.blackoutradar

import org.json.JSONObject
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.math.BigInteger
import java.util.Base64

/** Ein Beispiel aus tests/data/unterschrift.json: dieselbe Datei, mit der sich der Radar selbst prüft. */
class Vector(json: JSONObject) {
    val name: String = json.getString("name")
    val topic: String = json.getString("topic")
    val title: String = json.getString("title")
    val click: String = json.getString("click")
    val message: String = json.getString("message")
    val valid: Boolean = json.getBoolean("valid")
    val expect: JSONObject? = json.optJSONObject("expect")

    /** Die Meldung so, wie ntfy sie liefert, angenommen zum Zeitpunkt [time]. Vorrang und Zeichen setzt, wer sendet. */
    fun raw(time: Long, priority: Int = 3, tags: List<String> = emptyList()) =
        Notice("ntfy-" + name.hashCode(), time, title, message, priority, tags, click)

    override fun toString(): String = name
}

/** Die gemeinsamen Beispiele von Radar und App. */
object Vectors {
    private val document: JSONObject by lazy { JSONObject(find("tests/data/unterschrift.json").readText(Charsets.UTF_8)) }

    /** Der Testschlüssel, dessen geheimer Teil allgemein bekannt ist. Die echte App nimmt ihn nie an. */
    val keys: Map<String, String> by lazy {
        val json = document.getJSONObject("keys")
        json.keys().asSequence().associateWith { json.getString(it) }
    }

    val cases: List<Vector> by lazy {
        val array = document.getJSONArray("cases")
        (0 until array.length()).map { Vector(array.getJSONObject(it)) }
    }

    fun case(name: String): Vector = cases.first { it.name == name }

    /** Die Datei liegt im Repository oberhalb der App. Gesucht wird vom Arbeitsordner des Tests aufwärts. */
    private fun find(path: String): File {
        System.getProperty("br.repo")?.takeIf { it.isNotEmpty() }?.let { return File(it, path) }
        var folder: File? = File("").absoluteFile
        while (folder != null) {
            val file = File(folder, path)
            if (file.isFile) return file
            folder = folder.parentFile
        }
        throw IllegalStateException("$path nicht gefunden, gesucht ab ${File("").absolutePath}")
    }
}

/** Die Unterschrift des öffentlichen Alarms: Die App muss genau so urteilen wie der Radar. */
class SignedTest {
    private val n = BigInteger("ffffffff00000000ffffffffffffffffbce6faada7179e84f3b9cac2fc632551", 16)

    private fun unseal(case: Vector, message: String = case.message, title: String = case.title) =
        Signed.unseal(Vectors.keys, case.topic, title, message, case.click)

    private fun hex(text: String) = ByteArray(text.length / 2) { text.substring(2 * it, 2 * it + 2).toInt(16).toByte() }

    /** Die Unterschrift aus der letzten Zeile der Meldung. */
    private fun signature(case: Vector): ByteArray =
        Base64.getUrlDecoder().decode(case.message.substringAfterLast('\n').substringAfterLast('.'))

    /** Die Daten, über die der Radar unterschrieben hat. */
    private fun signedData(case: Vector): ByteArray {
        val meta = case.message.substringAfterLast('\n').split('.')[1]
        val body = case.message.substringBeforeLast('\n', "").trimEnd('\n')
        return listOf("blackout-radar/1", case.topic, meta, case.title, case.click, body).joinToString("\n").toByteArray()
    }

    @Test
    fun urteiltWieDerRadar() {
        assertTrue("zu wenige Beispiele", Vectors.cases.size >= 30)
        assertTrue(Vectors.cases.count { it.valid } >= 10)
        for (case in Vectors.cases) {
            val result = unseal(case)
            assertEquals(case.name, case.valid, result != null)
            val expect = case.expect
            assertEquals(case.name, case.valid, expect != null)
            if (result == null || expect == null) continue
            assertEquals(case.name, expect.getString("k"), result.key)
            assertEquals(case.name, expect.getLong("t"), result.time)
            assertEquals(case.name, expect.getString("l"), result.level)
            assertEquals(case.name, expect.getString("i"), result.ident)
            assertEquals(case.name, expect.getString("body"), result.body)
        }
    }

    @Test
    fun derTextEndetVorDerUnterschrift() {
        val result = unseal(Vectors.case("gültig"))!!
        assertFalse(result.body.contains("br1."))
        assertFalse(result.body.endsWith("\n"))
        assertTrue(result.body.startsWith("Seit 12:00 Uhr"))
        assertEquals("", unseal(Vectors.case("gültig, ohne Text"))!!.body)
    }

    @Test
    fun ohneBekanntenSchluesselGiltNichts() {
        val case = Vectors.case("gültig")
        assertNotNull(unseal(case))
        assertNull(Signed.unseal(emptyMap(), case.topic, case.title, case.message, case.click))
        // Derselbe Schlüssel unter einem anderen Namen: Die Meldung nennt den Namen, und der ist unterschrieben.
        assertNull(Signed.unseal(mapOf("k1" to Vectors.keys.getValue("test")), case.topic, case.title, case.message, case.click))
        // Ein Eintrag, der kein Punkt der Kurve ist, nimmt nichts an.
        assertNull(Signed.unseal(mapOf("test" to "04" + "00".repeat(64)), case.topic, case.title, case.message, case.click))
    }

    @Test
    fun halbesZeichenpaarWirdNichtZumFragezeichen() {
        // Ein halbes Zeichenpaar lässt sich nicht als UTF-8 schreiben. Würde es beim Prüfen stillschweigend zu einem
        // Fragezeichen, gälte die Unterschrift einer Meldung mit Fragezeichen auch für die veränderte.
        val case = Vectors.case("gültig, Fragezeichen im Text")
        assertNotNull(unseal(case))
        val changed = case.message.replace('?', '\ud83d')
        assertNotEquals(case.message, changed)
        assertNull(unseal(case, message = changed))
        assertNull(unseal(case, title = case.title + "\udc00"))
    }

    @Test
    fun eingebauteSchluessel() {
        assertTrue("k1" in Signed.KEYS)
        for ((name, point) in Signed.KEYS) {
            assertTrue(name, Regex("[a-z0-9]{1,8}").matches(name))
            assertNotNull(name, Signed.publicKey(point))
        }
        // Den Testschlüssel kennt jeder. Nur der Testbau nimmt ihn an.
        assertEquals(BuildConfig.DEBUG, Signed.TEST_KEY_NAME in Signed.KEYS)
        assertEquals(Signed.TEST_KEY, Vectors.keys["test"])
        assertNotEquals(Signed.TEST_KEY, Signed.KEYS["k1"])
        assertEquals(if (BuildConfig.DEBUG) 2 else 1, Signed.KEYS.size)
    }

    @Test
    fun schluesselMussAufDerKurveLiegen() {
        val good = Signed.TEST_KEY
        assertNotNull(Signed.publicKey(good))
        assertNotNull(Signed.publicKey(good.uppercase()))
        assertNull(Signed.publicKey(""))
        assertNull(Signed.publicKey("04" + "00".repeat(64)))
        assertNull(Signed.publicKey(good.dropLast(2)))
        assertNull(Signed.publicKey(good + "00"))
        assertNull(Signed.publicKey("03" + good.substring(2)))        // andere Schreibweise des Punkts
        assertNull(Signed.publicKey(good.dropLast(1) + "8"))          // um ein Bit daneben
        assertNull(Signed.publicKey(good.dropLast(1) + "x"))          // kein Hex
        assertNull(Signed.publicKey(good.dropLast(1)))                // ungerade Länge
        // Koordinate so groß wie der Modulus der Kurve oder größer
        assertNull(Signed.publicKey("04" + "ffffffff00000001000000000000000000000000ffffffffffffffffffffffff" + good.substring(66)))
    }

    @Test
    fun formDerUnterschrift() {
        assertEquals(BigInteger.ONE to BigInteger.valueOf(0x80), Signed.parseDer(hex("300702010102020080")))
        assertArrayEquals(hex("300702010102020080"), Signed.der(BigInteger.ONE, BigInteger.valueOf(0x80)))
        assertNull(Signed.parseDer(hex("30080201010203000080")))   // überflüssiges Nullbyte
        assertNull(Signed.parseDer(hex("3006020101020180")))       // negative Zahl
        assertEquals(BigInteger.ONE to BigInteger.ONE, Signed.parseDer(hex("3006020101020101")))
        assertNull(Signed.parseDer(hex("3005020101020101")))       // Länge zu klein angegeben
        assertNull(Signed.parseDer(hex("30060201010201")))         // abgeschnitten
        assertNull(Signed.parseDer(hex("300602010102010100")))     // etwas hinter der Folge
        assertNull(Signed.parseDer(hex("300702010102010100")))     // etwas hinter den beiden Zahlen
        assertNull(Signed.parseDer(hex("3106020101020101")))       // keine Folge
        assertNull(Signed.parseDer(hex("3006030101020101")))       // keine Zahl
        assertNull(Signed.parseDer(hex("30050200020101")))         // Zahl ohne Inhalt
        assertNull(Signed.parseDer(hex("3003020101")))             // nur eine Zahl
        assertNull(Signed.parseDer(ByteArray(0)))
        assertNull(Signed.parseDer(hex("30")))
        assertNull(Signed.parseDer(hex("308106020101020101")))     // Länge in der langen Form
        assertNull(Signed.parseDer(hex("3027" + "0222" + "01" + "00".repeat(33) + "020101")))  // Zahl länger als 33 Bytes
        val big = n - BigInteger.ONE
        assertEquals(72, Signed.der(big, big).size)
        assertEquals(big to big, Signed.parseDer(Signed.der(big, big)))
        assertEquals(BigInteger.ONE to BigInteger.ONE, Signed.parseDer(Signed.der(BigInteger.ONE, BigInteger.ONE)))
    }

    @Test
    fun jedesGeaenderteBitMachtDieUnterschriftUngueltig() {
        val case = Vectors.case("gültig")
        val key = Signed.publicKey(Vectors.keys.getValue("test"))!!
        val data = signedData(case)
        val good = signature(case)
        assertTrue(Signed.verify(key, data, good))
        assertFalse(Signed.verify(key, data + 0x20, good))
        assertFalse(Signed.verify(Signed.publicKey(Signed.KEYS.getValue("k1"))!!, data, good))
        for (position in good.indices) {
            val damaged = good.copyOf()
            damaged[position] = (damaged[position].toInt() xor 0x01).toByte()
            assertFalse("Byte $position", Signed.verify(key, data, damaged))
        }
        assertFalse(Signed.verify(key, data, ByteArray(0)))
        assertFalse(Signed.verify(key, data, good + 0))
    }

    @Test
    fun zahlenAusserhalbDesBereichsGeltenNie() {
        val case = Vectors.case("gültig")
        val key = Signed.publicKey(Vectors.keys.getValue("test"))!!
        val data = signedData(case)
        val (r, s) = Signed.parseDer(signature(case))!!
        assertTrue(Signed.verify(key, data, Signed.der(r, s)))
        // Zu (r, s) gilt auch (r, n - s): die zweite Form derselben Unterschrift.
        assertTrue(Signed.verify(key, data, Signed.der(r, n - s)))
        assertFalse(Signed.verify(key, data, Signed.der(BigInteger.ZERO, s)))
        assertFalse(Signed.verify(key, data, Signed.der(r, BigInteger.ZERO)))
        assertFalse(Signed.verify(key, data, Signed.der(r, n)))
        assertFalse(Signed.verify(key, data, Signed.der(n, s)))
        assertFalse(Signed.verify(key, data, Signed.der(r + n, s)))
        assertFalse(Signed.verify(key, data, Signed.der(r, s + n)))
        assertFalse(Signed.verify(key, data, Signed.der(s, r)))
    }

    @Test
    fun zeilenumbruchInTitelOderLinkGiltNie() {
        val case = Vectors.case("gültig")
        assertNull(unseal(case, title = case.title + "\r"))
        assertNull(unseal(case, title = case.title + "\n"))
        assertNull(Signed.unseal(Vectors.keys, case.topic, case.title, case.message, case.click + "\n"))
    }
}
