package io.github.sebastianeder09.blackoutradar

import org.json.JSONArray
import org.json.JSONException
import org.json.JSONObject
import java.net.URLDecoder
import java.net.URLEncoder

/** Wohin die App sich verbindet: Server und Thema. */
data class Target(val server: String, val topic: String)

/**
 * Eine Meldung, wie ntfy sie liefert. [time] in Sekunden seit 1970.
 * [via] ist leer, wenn sie über ntfy kam. Sonst nennt es den Grund, aus dem die App sie
 * über den Notweg aus dem Lagebericht geholt hat, siehe [Fallback].
 */
data class Notice(
    val id: String,
    val time: Long,
    val title: String,
    val message: String,
    val priority: Int,
    val tags: List<String>,
    val click: String,
    val via: String = "",
) {
    /** alarm | warn | ok | info | daily, so wie der Radar die Meldung eingestuft hat. */
    val level: String
        get() = when {
            priority >= 5 -> "alarm"
            priority == 4 -> "warn"
            "white_check_mark" in tags -> "ok"
            priority == 3 -> "info"
            else -> "daily"
        }

    /** Wahr, wenn die Meldung nicht über ntfy kam, sondern über den Notweg. */
    val fallback: Boolean get() = via.isNotEmpty()

    /** Wahr, wenn die Meldung aus dem öffentlichen Alarm stammt (siehe [PublicAlarm.id]). */
    val public: Boolean get() = id.startsWith(PublicAlarm.ID_PREFIX)

    fun toJson(): JSONObject = JSONObject()
        .put("id", id)
        .put("time", time)
        .put("title", title)
        .put("message", message)
        .put("priority", priority)
        .put("tags", JSONArray(tags))
        .put("click", click)
        .put("via", via)

    companion object {
        fun fromJson(json: JSONObject): Notice? {
            val id = text(json, "id")
            if (id.isEmpty()) return null
            val tags = ArrayList<String>()
            val array = json.optJSONArray("tags")
            if (array != null) {
                for (i in 0 until array.length()) {
                    val tag = array.optString(i)
                    if (tag.isNotEmpty()) tags.add(tag)
                }
            }
            return Notice(
                id = id,
                time = json.optLong("time", 0L),
                title = text(json, "title"),
                message = text(json, "message"),
                priority = json.optInt("priority", 3).coerceIn(1, 5),
                tags = tags,
                click = text(json, "click"),
                via = text(json, "via"),
            )
        }

        /** Wie optString, aber ein JSON-null wird nicht zum Text "null". */
        private fun text(json: JSONObject, key: String): String =
            if (json.isNull(key)) "" else json.optString(key, "")
    }
}

/** Die Dringlichkeiten des Radars und wie ntfy sie kennzeichnet (im Radar: NTFY_PRIORITY und NTFY_TAGS). */
object Levels {
    private val PRIORITY = mapOf("alarm" to 5, "warn" to 4, "info" to 3, "ok" to 3, "daily" to 2)
    private val TAGS = mapOf("alarm" to "rotating_light", "warn" to "warning", "info" to "zap",
        "ok" to "white_check_mark", "daily" to "bar_chart")

    /** Eine unbekannte Dringlichkeit gilt als gewöhnliche Meldung. */
    fun priority(level: String): Int = PRIORITY[level] ?: 3

    fun tags(level: String): List<String> = listOfNotNull(TAGS[level])
}

/** Eine Zeile aus dem Datenstrom von ntfy. */
sealed class StreamEvent {
    data object Open : StreamEvent()
    data object Keepalive : StreamEvent()
    data class Message(val notice: Notice) : StreamEvent()
    data object Other : StreamEvent()
}

object Ntfy {
    const val DEFAULT_SERVER = "https://ntfy.sh"

    /** So beginnt ein Link, der die App mit einem Thema einrichtet. */
    const val LINK_PREFIX = "blackoutradar://abo"

    private val TOPIC = Regex("[-_A-Za-z0-9]{1,64}")
    private val LINK = Regex("blackoutradar://[^\\s<>\"']+", RegexOption.IGNORE_CASE)
    private val HOST = Regex("[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?(:[0-9]{1,5})?")
    private val EMOJI = mapOf(
        "rotating_light" to "🚨",
        "warning" to "⚠️",
        "zap" to "⚡",
        "white_check_mark" to "✅",
        "bar_chart" to "📊",
    )

    /**
     * Liest das Thema aus dem, was der Mensch eingefügt hat. Erlaubt sind der reine
     * Themenname, eine Adresse wie https://ntfy.sh/thema oder ntfy://ntfy.sh/thema und
     * ein Link der App, auch mitten in einer weitergegebenen Nachricht.
     * Unverschlüsselte Adressen (http) gelten nur im Testbau.
     */
    fun parseTarget(input: String, allowHttp: Boolean = false): Target? {
        findLink(input)?.let { return parseLink(it, allowHttp) }
        val text = input.trim().trim('`', '"', '\'', '<', '>', '.', ',', ';', '„', '“', '”', '«', '»')
        if (text.isEmpty() || text.any { it.isWhitespace() }) return null
        var scheme = "https"
        var rest = text
        var explicitHost = false
        val schemeEnd = text.indexOf("://")
        if (schemeEnd >= 0) {
            scheme = when (text.substring(0, schemeEnd).lowercase()) {
                "https", "ntfy" -> "https"
                "http" -> if (allowHttp) "http" else return null
                else -> return null
            }
            rest = text.substring(schemeEnd + 3)
            explicitHost = true
        }
        rest = rest.substringBefore('?').substringBefore('#').trim('/')
        val parts = rest.split('/')
        return when {
            !explicitHost && parts.size == 1 && TOPIC.matches(parts[0]) -> Target(DEFAULT_SERVER, parts[0])
            parts.size == 2 && (explicitHost || '.' in parts[0]) && HOST.matches(parts[0]) && TOPIC.matches(parts[1]) ->
                Target("$scheme://${parts[0].lowercase()}", parts[1])
            else -> null
        }
    }

    /** Der Link der App in einem Text, etwa in einer weitergegebenen Nachricht. */
    fun findLink(text: String): String? = LINK.find(text)?.value?.trimEnd('.', ',', ';', ')')

    /**
     * Liest das Ziel aus einem Link der App: blackoutradar://abo/thema, blackoutradar://abo?thema=…
     * (dort darf auch eine ganze Adresse stehen) oder kurz blackoutradar://thema.
     */
    fun parseLink(link: String, allowHttp: Boolean = false): Target? {
        val text = link.trim()
        if (!text.startsWith("blackoutradar://", ignoreCase = true)) return null
        val rest = text.substring("blackoutradar://".length).substringBefore('#')
        val query = rest.substringAfter('?', "")
        val named = query.split('&').firstOrNull { it.startsWith("thema=") }?.substringAfter('=')
        if (named != null) {
            val value = try {
                URLDecoder.decode(named, "UTF-8")
            } catch (e: IllegalArgumentException) {
                return null
            }
            // Ein Link im Link ergibt keinen Sinn und soll auch keine Schleife auslösen.
            return if (findLink(value) != null) null else parseTarget(value, allowHttp)
        }
        val parts = rest.substringBefore('?').trim('/').split('/')
        val topic = when {
            parts.size == 2 && parts[0].equals("abo", ignoreCase = true) -> parts[1]
            parts.size == 1 && !parts[0].equals("abo", ignoreCase = true) -> parts[0]
            else -> return null
        }
        return if (TOPIC.matches(topic)) Target(DEFAULT_SERVER, topic) else null
    }

    /** Das Ziel so, wie man es ins Feld "Thema" schreibt: der Name, bei einem eigenen Server die Adresse. */
    fun plain(target: Target): String =
        if (target.server == DEFAULT_SERVER) target.topic else "${target.server}/${target.topic}"

    /** Link, der auf einem weiteren Handy dasselbe Thema einrichtet. */
    fun link(target: Target): String =
        if (target.server == DEFAULT_SERVER) "$LINK_PREFIX/${target.topic}"
        else "$LINK_PREFIX?thema=" + URLEncoder.encode(plain(target), "UTF-8")

    /**
     * Nachricht zum Weitergeben an ein weiteres Handy. Wer sie dort kopiert und in der App die Seite zum
     * Verbinden des eigenen Radars öffnet, findet das Thema schon im Feld ([sharedTarget]) und tippt nur noch
     * auf "Verbinden".
     */
    fun shareText(target: Target, downloadUrl: String): String =
        "Blackout-Radar: Alarm aufs Handy bei einem großen Stromausfall.\n\n" +
            "1. App herunterladen und installieren:\n$downloadUrl\n\n" +
            "2. Diese ganze Nachricht kopieren, die App öffnen und auf „Eigenen Radar verbinden“ tippen. " +
            "Sie trägt das Thema selbst ein, du tippst nur noch auf „Verbinden“.\n\n" +
            link(target)

    /**
     * Das Ziel aus einer weitergegebenen Nachricht ([shareText]), wie sie in der Zwischenablage liegt. Es zählt
     * nur der Link der App, der Rest ist Anleitung. Anderer Text ergibt nichts, auch ein bloßer Themenname
     * oder eine Adresse: Was der Mensch sonst kopiert hat, geht die App nichts an.
     */
    fun sharedTarget(text: String, allowHttp: Boolean = false): Target? = findLink(text)?.let { parseLink(it, allowHttp) }

    /** Dauerverbindung: liefert zuerst alles seit [since], danach jede neue Meldung sofort. */
    fun streamUrl(target: Target, since: String): String = "${target.server}/${target.topic}/json?since=$since"

    /** Einmalige Abfrage: liefert alles seit [since] und endet. */
    fun pollUrl(target: Target, since: String): String = streamUrl(target, since) + "&poll=1"

    fun parseLine(line: String): StreamEvent? {
        if (line.isBlank()) return null
        val json = try {
            JSONObject(line)
        } catch (e: JSONException) {
            return null
        }
        return when (json.optString("event")) {
            "open" -> StreamEvent.Open
            "keepalive" -> StreamEvent.Keepalive
            // Was über ntfy kommt, kam nie über den Notweg, egal was in der Zeile steht.
            "message" -> Notice.fromJson(json)?.let { StreamEvent.Message(it.copy(via = "")) } ?: StreamEvent.Other
            else -> StreamEvent.Other
        }
    }

    /** Zeigt vom Thema nur Anfang und Ende, weil es wie ein Passwort wirkt. */
    fun mask(topic: String): String =
        if (topic.length <= 10) "•".repeat(topic.length) else topic.take(4) + "…" + topic.takeLast(3)

    /** Die Symbole, die ntfy aus den Schlagworten einer Meldung macht. */
    fun emoji(tags: List<String>): String = tags.mapNotNull { EMOJI[it] }.joinToString(" ")

    fun displayTitle(notice: Notice): String {
        val title = notice.title.ifBlank { "Blackout-Radar" }
        val symbols = emoji(notice.tags)
        return if (symbols.isEmpty()) title else "$symbols $title"
    }
}

/** Wartezeit zwischen zwei Verbindungsversuchen. */
object Backoff {
    private val STEPS_S = longArrayOf(2, 4, 8, 15, 30, 60, 120, 300)
    const val RATE_LIMIT_MS = 10 * 60_000L

    /** [attempt] zählt ab 1. [jitter] zwischen 0 und 1 streut die Wartezeit um bis zu 20 %. */
    fun delayMs(attempt: Int, rateLimited: Boolean = false, jitter: Double = 0.0): Long {
        if (rateLimited) return RATE_LIMIT_MS
        val index = (attempt - 1).coerceIn(0, STEPS_S.size - 1)
        val base = STEPS_S[index] * 1000L
        return base + (base * 0.2 * jitter.coerceIn(0.0, 1.0)).toLong()
    }
}
