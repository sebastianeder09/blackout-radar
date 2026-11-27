package io.github.sebastianeder09.blackoutradar

import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.atomic.AtomicInteger

/** Der flüchtige Zustand der App: Verbindung und Zähler, an denen die Oberfläche Änderungen erkennt. */
object AppState {
    enum class Conn { STOPPED, CONNECTING, CONNECTED, WAITING }

    @Volatile var conn: Conn = Conn.STOPPED
        private set

    /** Seit wann der Zustand gilt, in Millisekunden seit 1970. */
    @Volatile var connSince: Long = 0L
        private set

    /** Grund der letzten Störung in Worten, leer wenn alles läuft. */
    @Volatile var connDetail: String = ""
        private set

    /** Wann der nächste Versuch startet, 0 wenn keiner geplant ist. */
    @Volatile var nextRetryAt: Long = 0L
        private set

    /** Letztes Lebenszeichen des Servers nach der Uhr, die auch im Schlaf des Geräts weiterläuft. */
    @Volatile var lastActivityElapsed: Long = 0L

    private val messagesCounter = AtomicInteger()
    private val statusCounter = AtomicInteger()

    /** Steigt mit jeder neuen Meldung. */
    val messagesRev: Int get() = messagesCounter.get()

    /** Steigt mit jedem neu geladenen Lagebericht. */
    val statusRev: Int get() = statusCounter.get()

    @Volatile var statusLoading: Boolean = false
    @Volatile var statusError: String = ""

    private val listeners = CopyOnWriteArrayList<() -> Unit>()

    fun setConn(state: Conn, detail: String = "", nextRetryAt: Long = 0L, now: Long = System.currentTimeMillis()) {
        if (state != conn) connSince = now
        conn = state
        connDetail = detail
        this.nextRetryAt = nextRetryAt
        changed()
    }

    fun messagesChanged() {
        messagesCounter.incrementAndGet()
        changed()
    }

    fun statusChanged() {
        statusCounter.incrementAndGet()
        changed()
    }

    fun addListener(listener: () -> Unit) {
        listeners.add(listener)
    }

    fun removeListener(listener: () -> Unit) {
        listeners.remove(listener)
    }

    fun changed() {
        for (listener in listeners) listener()
    }
}
