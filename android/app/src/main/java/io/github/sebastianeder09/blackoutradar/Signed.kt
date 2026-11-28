package io.github.sebastianeder09.blackoutradar

import org.json.JSONException
import org.json.JSONObject
import java.math.BigInteger
import java.nio.ByteBuffer
import java.nio.CharBuffer
import java.nio.charset.CharacterCodingException
import java.nio.charset.CodingErrorAction
import java.security.GeneralSecurityException
import java.security.KeyFactory
import java.security.PublicKey
import java.security.Signature
import java.security.spec.X509EncodedKeySpec
import java.util.Base64

/**
 * Was eine unterschriebene Meldung über sich sagt, nachdem ihre Unterschrift geprüft ist.
 * [time] ist der Zeitpunkt, zu dem der Radar die Meldung erstellt hat, in Sekunden seit 1970.
 * [ident] ist der Schlüssel, unter dem der Radar die Meldung führt. [body] ist der Text ohne die Zeile
 * mit der Unterschrift.
 */
data class Sealed(val key: String, val time: Long, val level: String, val ident: String, val body: String)

/**
 * Prüft die Unterschrift des öffentlichen Alarms.
 *
 * Das öffentliche Thema bei ntfy kann jeder lesen und jeder beschreiben. Der Radar unterschreibt deshalb jede
 * Meldung (blackout_radar/sign.py), die App kennt nur den öffentlichen Schlüssel und verwirft alles, was nicht
 * dazu passt. Verfahren: ECDSA mit der Kurve P-256 und SHA-256, das prüft Android mit Bordmitteln.
 *
 * Eine unterschriebene Meldung trägt als letzte Zeile ihres Textes `br1.<Angaben>.<Unterschrift>`, beides
 * base64url ohne Füllzeichen. Die Angaben sind JSON: `{"k": Name des Schlüssels, "t": Zeit, "l": Dringlichkeit,
 * "i": Schlüssel der Meldung}`. Die Unterschrift deckt Thema, Angaben, Titel, Link und Text ab.
 *
 * Diese Datei urteilt genau wie `sign.unseal` im Radar. Beide prüfen dieselben Beispiele:
 * tests/data/unterschrift.json.
 */
object Signed {
    private const val DOMAIN = "blackout-radar/1"

    /**
     * Öffentliche Schlüssel, deren Unterschrift die App annimmt (Name -> Punkt der Kurve, unkomprimiert,
     * hexadezimal). Dieselben Werte stehen im Radar in `sign.PUBLIC_KEYS`. Der Schlüssel "test" ist der
     * Beispielschlüssel aus RFC 6979, sein geheimer Teil ist allgemein bekannt: Ihn nimmt nur der Testbau an.
     */
    val KEYS: Map<String, String> = LinkedHashMap<String, String>().apply {
        put("k1", "04b81db61af18d998f74e1530279007b00c56b947532f8e6aa6c5a344cc4de0817" +
            "ddd8e9f6ad66f8e226627f7999783343a4653d11f364c79a79753fb2ad9d2ef0")
        if (BuildConfig.DEBUG) put(TEST_KEY_NAME, TEST_KEY)
    }

    const val TEST_KEY_NAME = "test"
    const val TEST_KEY = "0460fed4ba255a9d31c961eb74c6356d68c049b8923b61fa6ce669622e60f29fb6" +
        "7903fe1008b8bc99a41ae9e95628bc64f2f1b20c2d7e9f5177a3c294d4462299"

    private val LINE = Regex("br1\\.([A-Za-z0-9_-]{8,600})\\.([A-Za-z0-9_-]{16,128})")

    /** Die Zeit einer Meldung ist eine ganze Zahl von Sekunden seit 1970, kleiner als dieser Wert (wie im Radar). */
    private const val MAX_TIME = 1L shl 53

    // Kurve P-256 (secp256r1)
    private val P = BigInteger("ffffffff00000001000000000000000000000000ffffffffffffffffffffffff", 16)
    private val B = BigInteger("5ac635d8aa3a93e7b3ebbd55769886bc651d06b0cc53b0f63bce3c3e27d2604b", 16)
    private val N = BigInteger("ffffffff00000000ffffffffffffffffbce6faada7179e84f3b9cac2fc632551", 16)

    /** Kopf eines öffentlichen Schlüssels dieser Kurve in der Form, die Android liest (SubjectPublicKeyInfo). */
    private val SPKI_HEAD = hex("3059301306072a8648ce3d020106082a8648ce3d030107034200")

    private val parsed = HashMap<String, PublicKey?>()

    /**
     * Prüft eine Meldung, die unter [topic] mit [title], [message] und [click] angekommen ist.
     * Liefert ihre Angaben samt Text, oder null, wenn die Unterschrift fehlt oder nicht passt.
     */
    fun unseal(keys: Map<String, String>, topic: String, title: String, message: String, click: String): Sealed? {
        val cut = message.lastIndexOf('\n')
        val match = LINE.matchEntire(message.substring(cut + 1)) ?: return null
        // Ein Zeilenumbruch in Titel oder Link ließe Text von einem Feld ins andere wandern, ohne dass sich die
        // unterschriebenen Daten ändern. Der Radar schickt so etwas nie.
        if (title.any { it == '\r' || it == '\n' } || click.any { it == '\r' || it == '\n' }) return null
        val body = (if (cut < 0) "" else message.substring(0, cut)).trimEnd('\n')
        val meta = match.groupValues[1]
        val fields: JSONObject
        val signature: ByteArray
        try {
            fields = JSONObject(utf8(Base64.getUrlDecoder().decode(meta)) ?: return null)
            signature = Base64.getUrlDecoder().decode(match.groupValues[2])
        } catch (e: IllegalArgumentException) {
            return null
        } catch (e: JSONException) {
            return null
        }
        val name = fields.opt("k") as? String ?: return null
        val point = keys[name] ?: return null
        val number = fields.opt("t")
        if (number !is Int && number !is Long) return null
        val time = (number as Number).toLong()
        if (time < 0 || time >= MAX_TIME) return null
        val level = fields.opt("l") as? String ?: return null
        val ident = fields.opt("i") as? String ?: return null
        val key = publicKey(point) ?: return null
        val data = bytes(listOf(DOMAIN, topic, meta, title, click, body).joinToString("\n")) ?: return null
        if (!verify(key, data, signature)) return null
        return Sealed(name, time, level, ident, body)
    }

    /** Prüft eine Unterschrift in DER über [data]. */
    fun verify(key: PublicKey, data: ByteArray, signature: ByteArray): Boolean {
        val (r, s) = parseDer(signature) ?: return false
        if (r.signum() <= 0 || s.signum() <= 0 || r >= N || s >= N) return false
        return try {
            val check = Signature.getInstance("SHA256withECDSA")
            check.initVerify(key)
            check.update(data)
            // In der einen Form, die jede Android-Fassung gleich liest, nicht so, wie sie angekommen ist.
            check.verify(der(r, s))
        } catch (e: GeneralSecurityException) {
            false
        }
    }

    /** Der öffentliche Schlüssel aus seiner hexadezimalen Form, oder null, wenn er nicht auf der Kurve liegt. */
    @Synchronized
    fun publicKey(point: String): PublicKey? {
        if (parsed.containsKey(point)) return parsed[point]
        val key = try {
            val raw = hex(point)
            if (raw.size != 65 || raw[0] != 4.toByte() || !onCurve(raw)) null
            else KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(SPKI_HEAD + raw))
        } catch (e: IllegalArgumentException) {
            null
        } catch (e: GeneralSecurityException) {
            null
        }
        parsed[point] = key
        return key
    }

    private fun onCurve(raw: ByteArray): Boolean {
        val x = BigInteger(1, raw.copyOfRange(1, 33))
        val y = BigInteger(1, raw.copyOfRange(33, 65))
        if (x >= P || y >= P) return false
        val right = x.multiply(x).multiply(x).subtract(x.multiply(BigInteger.valueOf(3))).add(B).mod(P)
        return y.multiply(y).mod(P) == right
    }

    /** Liest eine Unterschrift in DER. Streng: Was nicht genau passt, gilt als ungültig. */
    internal fun parseDer(raw: ByteArray): Pair<BigInteger, BigInteger>? {
        if (raw.size < 2 || raw[0] != 0x30.toByte()) return null
        val total = raw[1].toInt() and 0xFF
        if (total != raw.size - 2 || total > 0x7F) return null
        val numbers = ArrayList<BigInteger>(2)
        var pos = 2
        repeat(2) {
            if (pos + 2 > raw.size || raw[pos] != 0x02.toByte()) return null
            val size = raw[pos + 1].toInt() and 0xFF
            if (size == 0 || size > 33 || pos + 2 + size > raw.size) return null
            val first = raw[pos + 2].toInt() and 0xFF
            if ((first and 0x80) != 0) return null
            // überflüssiges Nullbyte
            if (size > 1 && first == 0 && (raw[pos + 3].toInt() and 0x80) == 0) return null
            numbers.add(BigInteger(1, raw.copyOfRange(pos + 2, pos + 2 + size)))
            pos += 2 + size
        }
        return if (pos == raw.size) numbers[0] to numbers[1] else null
    }

    /** Eine Unterschrift in DER. BigInteger setzt das führende Nullbyte selbst, wenn das oberste Bit gesetzt ist. */
    internal fun der(r: BigInteger, s: BigInteger): ByteArray {
        val first = r.toByteArray()
        val second = s.toByteArray()
        val body = byteArrayOf(0x02, first.size.toByte()) + first + byteArrayOf(0x02, second.size.toByte()) + second
        return byteArrayOf(0x30, body.size.toByte()) + body
    }

    /**
     * Text als UTF-8, oder null, wenn er sich so nicht schreiben lässt (ein halbes Zeichenpaar). Stillschweigend
     * ein Fragezeichen daraus zu machen hieße: Die Unterschrift einer Meldung mit Fragezeichen gälte auch für die
     * veränderte.
     */
    private fun bytes(text: String): ByteArray? = try {
        val buffer = Charsets.UTF_8.newEncoder()
            .onMalformedInput(CodingErrorAction.REPORT)
            .onUnmappableCharacter(CodingErrorAction.REPORT)
            .encode(CharBuffer.wrap(text))
        ByteArray(buffer.remaining()).also { buffer.get(it) }
    } catch (e: CharacterCodingException) {
        null
    }

    /** Text aus UTF-8, oder null, wenn die Bytes kein gültiges UTF-8 sind. */
    private fun utf8(raw: ByteArray): String? = try {
        Charsets.UTF_8.newDecoder()
            .onMalformedInput(CodingErrorAction.REPORT)
            .onUnmappableCharacter(CodingErrorAction.REPORT)
            .decode(ByteBuffer.wrap(raw)).toString()
    } catch (e: CharacterCodingException) {
        null
    }

    private fun hex(text: String): ByteArray {
        require(text.length % 2 == 0) { "ungerade Länge" }
        return ByteArray(text.length / 2) {
            val high = Character.digit(text[2 * it], 16)
            val low = Character.digit(text[2 * it + 1], 16)
            require(high >= 0 && low >= 0) { "kein Hex-Zeichen" }
            (high * 16 + low).toByte()
        }
    }
}
