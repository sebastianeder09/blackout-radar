package io.github.sebastianeder09.blackoutradar

import android.content.Context
import java.io.IOException

/** Einrichten des Themas und Nachholen verpasster Meldungen. */
object Sync {
    class SetupResult(val ok: Boolean, val error: String = "", val count: Int = 0, val offline: Boolean = false)

    /** Schützt alles, was die Liste der Meldungen umbaut: Einrichten, Nachholen, Zustellen und den Notweg. */
    internal val lock = Any()

    /**
     * Übernimmt das Thema, lädt still, was der Server aus den letzten Stunden noch hat,
     * und startet die Verbindung. Läuft nie auf dem Hauptfaden.
     */
    fun setup(context: Context, input: String, allowHttp: Boolean = BuildConfig.DEBUG): SetupResult {
        val target = Ntfy.parseTarget(input, allowHttp)
            ?: return SetupResult(false, "Das sieht nicht nach einem Thema aus. Bitte nur den Themennamen " +
                "einfügen, ohne Leerzeichen. Erlaubt sind Buchstaben, Ziffern, Bindestrich und Unterstrich.")
        return connect(context, target)
    }

    /**
     * Schaltet den öffentlichen Alarm ein (siehe [PublicAlarm]): dasselbe wie [setup], nur mit dem festen
     * Thema für alle. Läuft nie auf dem Hauptfaden.
     */
    fun setupPublic(context: Context): SetupResult = connect(context, PublicAlarm.target(Store.get(context)))

    private fun connect(context: Context, target: Target): SetupResult {
        val store = Store.get(context)
        val nowSeconds = System.currentTimeMillis() / 1000L
        var arrived: List<Notice>? = null
        var offline = false
        try {
            arrived = poll(target, "all", 12_000)
        } catch (e: HttpStatusException) {
            if (e.code == 429 || e.code >= 500) offline = true
            else return SetupResult(false, "Der Server nimmt dieses Thema nicht an (Antwort ${e.code}).")
        } catch (e: IOException) {
            offline = true
        }
        var count = 0
        synchronized(lock) {
            store.target = target
            store.log.clear()
            store.sinceTime = nowSeconds
            arrived?.forEach { raw -> admit(store, target, raw)?.let { if (store.log.add(it)) count++ } }
            // Ab der letzten Zeile des Servers fragt die App weiter, auch wenn sie diese Zeile nicht zeigt.
            store.lastId = arrived?.lastOrNull()?.id
            // Ohne Antwort des Servers fehlt, was er von vorher noch hat. Das holt backfill nach.
            store.historyPending = arrived == null
        }
        // Ab jetzt gilt, was eingerichtet ist. Ein Thema aus der Installationsdatei meldet sich nicht noch einmal.
        AppFile.markSeen(context)
        AppState.messagesChanged()
        Starter.ensure(context)
        ListenerService.kick(force = true)
        return SetupResult(true, count = count, offline = offline)
    }

    /**
     * Was die App von einer Zeile des Servers gelten lässt. Beim eigenen Thema alles, so wie es kam. Beim
     * öffentlichen Alarm nur, was der Radar unterschrieben hat, und davon nur die unterschriebenen Angaben.
     */
    internal fun admit(store: Store, target: Target, raw: Notice): Notice? =
        if (target == PublicAlarm.target(store)) PublicAlarm.open(raw, target.topic) else raw

    /** Vergisst das Thema und alle Meldungen und beendet die Verbindung. */
    fun reset(context: Context) {
        val store = Store.get(context)
        synchronized(lock) {
            store.target = null
            store.lastId = null
            store.historyPending = false
            store.log.clear()
        }
        // Die Kopie der App zum Weitergeben enthält das bisherige Thema.
        AppFile.shareFile(context).delete()
        ListenerService.stop(context)
        Watchdog.disarm(context)
        AppState.messagesChanged()
    }

    /**
     * Fragt einmal nach, was seit der letzten Meldung gekommen ist, und zeigt es an.
     * Liefert die Zahl der neuen Meldungen oder -1, wenn der Server nicht erreichbar war.
     */
    fun catchUp(context: Context, timeoutMs: Int): Int {
        val store = Store.get(context)
        val target = store.target ?: return 0
        val since = store.lastId ?: store.sinceTime.toString()
        val notices = try {
            poll(target, since, timeoutMs)
        } catch (e: IOException) {
            return -1
        }
        var fresh = 0
        for (notice in notices) if (deliver(context, target, notice)) fresh++
        return fresh
    }

    /**
     * Holt nach, was der Server von vor dem Einrichten noch hat, falls er beim Einrichten nicht
     * erreichbar war. Diese Meldungen kommen still in die Liste: Sie waren schon alt, als das Handy
     * dazukam. Alles ab dem Einrichten liefert die Verbindung selbst, und das läutet.
     * Liefert false, wenn der Server noch immer nicht antwortet. Läuft nie auf dem Hauptfaden.
     */
    fun backfill(context: Context, timeoutMs: Int): Boolean {
        val store = Store.get(context)
        if (!store.historyPending) return true
        val target = store.target ?: return true
        val setupTime = store.sinceTime
        if (History.expired(System.currentTimeMillis() / 1000L, setupTime)) {
            store.historyPending = false
            return true
        }
        val notices = try {
            poll(target, "all", timeoutMs)
        } catch (e: IOException) {
            return false
        }
        var added = 0
        synchronized(lock) {
            // Wurde inzwischen neu eingerichtet oder zurückgesetzt, gehört die Antwort nicht mehr hierher.
            if (!store.historyPending || store.target != target || store.sinceTime != setupTime) return true
            val admitted = notices.mapNotNull { admit(store, target, it) }
            for (notice in History.before(admitted, setupTime)) if (store.log.add(notice)) added++
            store.historyPending = false
        }
        if (added > 0) AppState.messagesChanged()
        return true
    }

    /**
     * Nimmt eine Zeile auf, die ntfy unter dem Ziel [from] geliefert hat, und zeigt die Meldung an, falls sie
     * neu ist. Beim öffentlichen Alarm zählt nur, was der Radar unterschrieben hat (siehe [admit]).
     *
     * Hat die App dieselbe Meldung schon über den Notweg gezeigt (siehe [Fallback]), ersetzt die
     * Zustellung von ntfy diesen Eintrag still: Geläutet hat es dafür schon.
     */
    fun deliver(context: Context, from: Target, raw: Notice): Boolean {
        val store = Store.get(context)
        var fresh = false
        var shown: Notice? = null
        synchronized(lock) {
            // Wurde inzwischen ein anderes Ziel eingerichtet, gehört die Zeile nicht mehr hierher.
            if (store.target != from) return false
            // Auch eine verworfene Zeile ist verarbeitet: Die nächste Nachfrage beginnt nach ihr.
            store.lastId = raw.id
            val notice = admit(store, from, raw) ?: return false
            if (from == PublicAlarm.target(store)) {
                // Die Kennung besteht aus unterschriebenen Angaben und ist auf jedem Weg dieselbe.
                val known = store.log.find(notice.id)
                if (known == null) {
                    fresh = store.log.add(notice)
                    if (fresh) shown = notice
                } else if (known.fallback) {
                    fresh = store.log.replace(known.id, notice)
                }
            } else {
                val log = store.log.all()
                val twin = if (log.any { it.fallback }) Fallback.twin(log, notice, Fallback.zone(StatusRepo.cachedJson(store))) else null
                if (twin != null) {
                    fresh = store.log.replace(twin.id, notice)
                } else {
                    fresh = store.log.add(notice)
                    if (fresh) shown = notice
                }
            }
        }
        shown?.let { Alerts.show(context, it) }
        if (fresh) AppState.messagesChanged()
        return fresh
    }

    private fun poll(target: Target, since: String, timeoutMs: Int): List<Notice> {
        val body = Http.getText(Ntfy.pollUrl(target, since), timeoutMs)
        val notices = ArrayList<Notice>()
        for (line in body.lineSequence()) {
            val event = Ntfy.parseLine(line)
            if (event is StreamEvent.Message) notices.add(event.notice)
        }
        return notices
    }
}

/** Was beim Nachholen als Vorgeschichte gilt, also als Meldung von vor dem Einrichten. */
object History {
    /** So lange bewahrt ntfy.sh Meldungen auf. Danach gibt es nichts mehr nachzuholen. */
    const val KEPT_SECONDS = 12 * 60 * 60L

    /**
     * Die Meldungen von vor dem Einrichten. Was in derselben Sekunde oder später kam, bleibt der
     * Verbindung überlassen, damit ein Alarm nie still in der Liste landet.
     */
    fun before(notices: List<Notice>, setupSeconds: Long): List<Notice> = notices.filter { it.time < setupSeconds }

    fun expired(nowSeconds: Long, setupSeconds: Long): Boolean = nowSeconds - setupSeconds > KEPT_SECONDS
}
