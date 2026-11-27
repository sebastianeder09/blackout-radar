package io.github.sebastianeder09.blackoutradar

import android.content.Context
import org.json.JSONArray
import org.json.JSONException
import org.json.JSONObject
import java.time.DateTimeException
import java.time.Instant
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.format.DateTimeParseException

/**
 * Eine Meldung, wie der Radar sie im Lagebericht führt (status.json, Schlüssel "notices").
 * [time] ist der Zeitpunkt, zu dem der Radar sie erstellt hat, in Sekunden seit 1970.
 * [handedOver] ist wahr, wenn der Radar sie an ntfy übergeben konnte.
 */
data class Posted(
    val key: String,
    val time: Long,
    val title: String,
    val body: String,
    val level: String,
    val handedOver: Boolean,
) {
    /**
     * Unter dieser Kennung steht die Meldung in der Liste, wenn sie über den Notweg kam. Die Zeit gehört
     * dazu: Käme derselbe Schlüssel später noch einmal, wäre das eine neue Meldung, und die muss läuten.
     */
    val id: String get() = Fallback.ID_PREFIX + time + ":" + key.ifEmpty { title }
}

/**
 * Der Notweg.
 *
 * Der Radar führt im Lagebericht die Meldungen, die er verschickt hat. Die App vergleicht sie mit dem,
 * was über ntfy angekommen ist. Was fehlt, holt sie aus dem Lagebericht und zeigt es selbst an, mit
 * derselben Dringlichkeit. So kommt ein Alarm auch an, wenn ntfy ausfällt, wenn der Radar dort nichts
 * loswird oder wenn das Thema am Handy nicht stimmt. Der Lagebericht liegt bei GitHub und hängt nicht an ntfy.
 *
 * Im Zweifel läutet die App lieber einmal zu viel: Passt eine angekommene Meldung nicht sicher zu einer
 * Meldung des Radars, gilt die Meldung des Radars als nicht angekommen.
 */
object Fallback {
    /** Der Radar konnte die Meldung nicht an ntfy übergeben. */
    const val VIA_RADAR = "radar"

    /** ntfy war von diesem Handy aus nicht erreichbar. */
    const val VIA_NET = "netz"

    /** ntfy hat geantwortet, unter dem Thema dieses Handys lag die Meldung aber nicht. */
    const val VIA_TOPIC = "thema"

    const val ID_PREFIX = "notweg:"

    /** Uhren gehen nie ganz gleich: So viel früher, als der Radar sie erstellt hat, darf eine Zustellung datiert sein. */
    const val EARLY_S = 120L

    /**
     * So lange nach dem Erstellen stellt der Radar ohne Vermerk zu. Ab 20 Minuten Verzug setzt er
     * "Verspätet zugestellt, erstellt am …" vor den Text, dazu kommt die Dauer eines Laufs.
     */
    const val ON_TIME_S = 32 * 60L

    /**
     * Ältere Meldungen holt der Notweg nicht mehr. Die Grenze liegt knapp unter der Zeit, die ntfy
     * Meldungen aufbewahrt: Bis dahin lässt sich dort nachfragen, ob eine Meldung nur noch unterwegs ist.
     */
    const val MAX_AGE_S = History.KEPT_SECONDS - 30 * 60L

    private const val CHANNEL = "ntfy"

    /** Der Radar kürzt Titel erst ab 240 Bytes. Kürzer als das hier ist ein gekürzter Titel nie. */
    private const val CLIPPED_MIN = 50
    private const val NO_TEXT = "Den Wortlaut führt der Lagebericht bei dieser Meldung nicht. Einzelheiten stehen im Lagebericht."
    private val DEFAULT_ZONE: ZoneId = ZoneId.of("Europe/Vienna")
    private val LATE = Regex("^Verspätet zugestellt, erstellt am (\\d{2}\\.\\d{2}\\. \\d{2}:\\d{2}) Uhr\\.")
    private val STAMP = DateTimeFormatter.ofPattern("dd.MM. HH:mm")
    private val SPACES = Regex("\\s+")
    private val PRIORITY = mapOf("alarm" to 5, "warn" to 4, "info" to 3, "ok" to 3, "daily" to 2)
    private val TAGS = mapOf("alarm" to "rotating_light", "warn" to "warning", "info" to "zap",
        "ok" to "white_check_mark", "daily" to "bar_chart")

    // ------------------------------------------------------------------ Lesen

    /**
     * Die Meldungen des Radars aus status.json, soweit sie für ntfy bestimmt waren.
     * null, wenn der Lagebericht (noch) keine Meldungen führt.
     */
    fun parse(statusJson: String?): List<Posted>? {
        if (statusJson == null) return null
        val array = try {
            JSONObject(statusJson).optJSONArray("notices")
        } catch (e: JSONException) {
            null
        } ?: return null
        val result = ArrayList<Posted>()
        for (i in 0 until array.length()) {
            val item = array.optJSONObject(i) ?: continue
            val title = text(item, "title")
            val time = seconds(text(item, "t"))
            if (title.isEmpty() || time <= 0L) continue
            val handedOver = CHANNEL in strings(item.optJSONArray("delivered"))
            // Nennt der Radar ntfy bei einer Meldung gar nicht, war sie nicht für den Push gedacht
            // (im Radar lässt sich etwa die tägliche Übersicht für ntfy abschalten).
            if (!handedOver && CHANNEL !in strings(item.optJSONArray("pending"))) continue
            result.add(Posted(
                key = text(item, "key"),
                time = time,
                title = title,
                body = text(item, "body"),
                level = text(item, "level").ifEmpty { "info" },
                handedOver = handedOver,
            ))
        }
        return result
    }

    /** Die Zeitzone, in der der Radar seine Texte schreibt. */
    fun zone(statusJson: String?): ZoneId {
        if (statusJson == null) return DEFAULT_ZONE
        return try {
            ZoneId.of(JSONObject(statusJson).optString("timezone"))
        } catch (e: JSONException) {
            DEFAULT_ZONE
        } catch (e: DateTimeException) {
            DEFAULT_ZONE
        }
    }

    private fun text(json: JSONObject, key: String): String = if (json.isNull(key)) "" else json.optString(key, "")

    private fun strings(array: JSONArray?): List<String> {
        if (array == null) return emptyList()
        return (0 until array.length()).map { array.optString(it) }
    }

    private fun seconds(iso: String): Long = try {
        Instant.parse(iso).epochSecond
    } catch (e: DateTimeParseException) {
        try {
            OffsetDateTime.parse(iso).toEpochSecond()
        } catch (e2: DateTimeParseException) {
            0L
        }
    }

    // -------------------------------------------------------------- Vergleichen

    /**
     * Ist [arrived] der Titel, unter dem ntfy die Meldung mit dem Titel [posted] zustellt? Leerzeichen zählen
     * nicht. Sehr lange Titel kürzt der Radar für ntfy und hängt " …" an: Dann genügt der gleiche Anfang.
     */
    fun sameTitle(posted: String, arrived: String): Boolean {
        val full = posted.trim().replace(SPACES, " ")
        val seen = arrived.trim().replace(SPACES, " ")
        if (full == seen) return true
        if (!seen.endsWith("…")) return false
        val stem = seen.dropLast(1).trimEnd()
        return stem.length >= CLIPPED_MIN && full.startsWith(stem)
    }

    /**
     * Ist [arrived] die Zustellung der Meldung, die der Radar um [postedTime] mit [postedTitle] erstellt hat?
     *
     * Der Titel muss gleich sein. Dazu muss die Zeit passen: Entweder kam die Meldung pünktlich, oder sie
     * trägt den Vermerk des Radars für verspätete Zustellung, und der nennt genau diese Minute. Eine Meldung
     * mit gleichem Titel von Stunden später ist eine neue Meldung und muss läuten.
     */
    fun same(postedTime: Long, postedTitle: String, arrived: Notice, zone: ZoneId): Boolean {
        if (arrived.fallback || !sameTitle(postedTitle, arrived.title)) return false
        val delay = arrived.time - postedTime
        val stamp = lateStamp(arrived)
        if (stamp != null) return delay >= -EARLY_S && stamp == stamp(postedTime, zone)
        return delay in -EARLY_S..ON_TIME_S
    }

    /** Die Minute aus dem Vermerk "Verspätet zugestellt, erstellt am …", wenn die Meldung ihn trägt. */
    fun lateStamp(arrived: Notice): String? = LATE.find(arrived.message)?.groupValues?.get(1)

    /** Zeitpunkt so, wie der Radar ihn in den Vermerk "Verspätet zugestellt" schreibt. */
    fun stamp(seconds: Long, zone: ZoneId): String = STAMP.format(Instant.ofEpochSecond(seconds).atZone(zone))

    /**
     * Die Meldungen des Radars, die auf diesem Handy fehlen, älteste zuerst.
     *
     * Nicht dazu zählt, was vor dem Einrichten kam (das ist Vorgeschichte) und was älter ist, als ntfy
     * Meldungen aufbewahrt. Jede angekommene Meldung deckt höchstens eine Meldung des Radars ab: Schickt
     * der Radar zweimal denselben Titel und kommt nur eine an, fehlt die andere.
     */
    fun missing(posted: List<Posted>, log: List<Notice>, setupSeconds: Long, nowSeconds: Long, zone: ZoneId): List<Posted> {
        val arrived = log.filter { !it.fallback }.sortedBy { it.time }
        val shown = log.filter { it.fallback }.mapTo(HashSet()) { it.id }
        val wanted = posted.filter { it.time >= setupSeconds && nowSeconds - it.time <= MAX_AGE_S }.sortedBy { it.time }
        val used = HashSet<String>()
        val covered = HashSet<Posted>()
        // Zuerst die verspäteten Zustellungen: Ihr Vermerk nennt die Meldung genau. Danach die pünktlichen.
        // So nimmt keine pünktliche Zustellung einer verspäteten die Meldung weg.
        for (late in listOf(true, false)) {
            for (item in wanted) {
                if (item in covered) continue
                val match = arrived.firstOrNull {
                    it.id !in used && (lateStamp(it) != null) == late && same(item.time, item.title, it, zone)
                } ?: continue
                used.add(match.id)
                covered.add(item)
            }
        }
        return wanted.filter { it !in covered && it.id !in shown }
    }

    /**
     * Der Eintrag, den die App über den Notweg angelegt hat und dessen Zustellung über ntfy jetzt mit
     * [arrived] doch noch kommt. Gibt es mehrere, zählt der älteste: Zustellungen kommen der Reihe nach.
     */
    fun twin(log: List<Notice>, arrived: Notice, zone: ZoneId): Notice? =
        log.filter { it.fallback && same(it.time, it.title, arrived, zone) }.minByOrNull { it.time }

    /** Die Meldung des Radars so, wie die App sie anzeigt und aufbewahrt. */
    fun notice(posted: Posted, via: String, click: String): Notice = Notice(
        id = posted.id,
        time = posted.time,
        title = posted.title,
        message = posted.body.ifBlank { NO_TEXT },
        priority = PRIORITY[posted.level] ?: 3,
        tags = listOfNotNull(TAGS[posted.level]),
        click = click,
        via = via,
    )

    /** Der Grund in Worten, für die Benachrichtigung und die Liste der Meldungen. */
    fun reason(via: String): String = when (via) {
        "" -> ""
        VIA_RADAR -> "Über den Notweg aus dem Lagebericht. Der Radar konnte diese Meldung nicht an ntfy übergeben."
        VIA_NET -> "Über den Notweg aus dem Lagebericht. ntfy war von diesem Handy aus nicht erreichbar."
        VIA_TOPIC -> "Über den Notweg aus dem Lagebericht. ntfy hat geantwortet, unter dem Thema dieses Handys lag die " +
            "Meldung dort aber nicht. Kommt das öfter vor, stimmt das Thema nicht mit dem des Radars überein."
        else -> "Über den Notweg aus dem Lagebericht."
    }

    // ------------------------------------------------------------------ Ablauf

    /**
     * Lädt den Lagebericht neu und gleicht ihn ab. Liefert die Zahl der Meldungen, die über den Notweg
     * kamen, oder null, wenn der Lagebericht nicht zu laden war. Läuft nie auf dem Hauptfaden.
     */
    fun sync(context: Context, timeoutMs: Int = 15_000): Int? {
        if (!StatusRepo.refresh(context, timeoutMs)) return null
        return check(context, timeoutMs)
    }

    /**
     * Gleicht den aufbewahrten Lagebericht mit den angekommenen Meldungen ab und zeigt an, was fehlt.
     * Der Lagebericht muss dafür gerade erst geladen worden sein: Nur dann lag jede Meldung, die der
     * Radar an ntfy übergeben hat, dort schon vor der Nachfrage dieser Funktion.
     */
    fun check(context: Context, timeoutMs: Int): Int {
        val store = Store.get(context)
        val target = store.target ?: return 0
        val setup = store.sinceTime
        val json = StatusRepo.cachedJson(store)
        val posted = parse(json)
        store.fallbackReady = posted != null
        if (posted == null) return 0
        val zone = zone(json)
        val now = System.currentTimeMillis() / 1000L
        // Der Radar hat übergeben, hier fehlt es: zuerst bei ntfy nachfragen. Kommt die Meldung so, läutet sie
        // wie gewohnt. Antwortet ntfy und die Meldung fehlt weiter, liegt sie dort nicht unter diesem Thema.
        val open = missing(posted, store.log.all(), setup, now, zone)
        val reachable = open.any { it.handedOver } && Sync.catchUp(context, timeoutMs) >= 0
        val shown = ArrayList<Notice>()
        synchronized(Sync.lock) {
            // Wurde inzwischen neu eingerichtet, gehört der Abgleich nicht mehr hierher.
            if (store.target != target || store.sinceTime != setup) return 0
            for (item in missing(posted, store.log.all(), setup, now, zone)) {
                // Nur was schon vor der Nachfrage fehlte: Für alles andere wurde ntfy noch nicht gefragt.
                if (item !in open) continue
                val via = if (!item.handedOver) VIA_RADAR else if (reachable) VIA_TOPIC else VIA_NET
                val notice = notice(item, via, StatusRepo.pageUrl())
                if (store.log.add(notice)) shown.add(notice)
            }
        }
        for (notice in shown) Alerts.show(context, notice)
        if (shown.isNotEmpty()) AppState.messagesChanged()
        store.fallbackCheckedAt = System.currentTimeMillis()
        AppState.changed()
        return shown.size
    }
}
