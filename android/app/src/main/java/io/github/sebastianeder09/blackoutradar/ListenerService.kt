package io.github.sebastianeder09.blackoutradar

import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.ConnectivityManager
import android.net.Network
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import android.os.SystemClock
import java.io.IOException
import java.net.HttpURLConnection
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone
import java.util.concurrent.Semaphore
import java.util.concurrent.TimeUnit
import javax.net.ssl.SSLException

/**
 * Hält die Verbindung zum ntfy-Server offen, damit ein Alarm sofort ankommt.
 *
 * Android lässt eine App nur dann dauerhaft im Hintergrund laufen, wenn sie das mit einer
 * Dauermeldung anzeigt. Bricht die Verbindung ab, baut der Dienst sie neu auf und holt
 * nach, was in der Zwischenzeit gekommen ist. Der Server schickt etwa jede Minute ein
 * Lebenszeichen. Bleibt es aus, gilt die Verbindung als tot.
 */
class ListenerService : Service() {

    private class Outcome(val connected: Boolean, val rateLimited: Boolean, val detail: String)

    private lateinit var store: Store
    private var wakeLock: PowerManager.WakeLock? = null
    private var worker: Thread? = null
    private var callbackRegistered = false
    private val signal = Semaphore(0)

    @Volatile private var stopped = false
    @Volatile private var connection: HttpURLConnection? = null
    @Volatile private var network: Network? = null
    @Volatile private var disconnectedSince = 0L
    @Volatile private var lastLabel = ""

    private val networkCallback = object : ConnectivityManager.NetworkCallback() {
        override fun onAvailable(net: Network) {
            val previous = network
            network = net
            // Neues Netz (WLAN statt Mobilfunk oder umgekehrt): Die alte Verbindung hängt am alten Netz.
            if (net != previous) kickInternal(force = previous != null)
        }

        override fun onLost(net: Network) {
            if (net == network) {
                network = null
                kickInternal(force = true)
            }
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        store = Store.get(this)
        Alerts.createChannels(this)
        wakeLock = getSystemService(PowerManager::class.java)
            ?.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "BlackoutRadar:Verbindung")
            ?.apply { setReferenceCounted(false) }
        current = this
        running = true
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (!enterForeground()) {
            // Android verweigert den Start aus dem Hintergrund. Der Wächter fragt dann in Abständen nach.
            stopSelf()
            return START_NOT_STICKY
        }
        if (store.target == null) {
            stopSelf()
            return START_NOT_STICKY
        }
        Watchdog.arm(this)
        registerNetworkCallback()
        startWorker()
        return START_STICKY
    }

    override fun onDestroy() {
        stopped = true
        running = false
        if (current === this) current = null
        if (callbackRegistered) {
            try {
                getSystemService(ConnectivityManager::class.java)?.unregisterNetworkCallback(networkCallback)
            } catch (e: RuntimeException) {
                // war schon abgemeldet
            }
            callbackRegistered = false
        }
        closeConnection()
        wake()
        releaseWake()
        AppState.setConn(AppState.Conn.STOPPED)
        super.onDestroy()
    }

    private fun enterForeground(): Boolean = try {
        val notification = Alerts.service(this, label())
        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(Alerts.ID_SERVICE, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
        } else {
            startForeground(Alerts.ID_SERVICE, notification)
        }
        true
    } catch (e: RuntimeException) {
        false
    }

    private fun registerNetworkCallback() {
        if (callbackRegistered) return
        try {
            getSystemService(ConnectivityManager::class.java)?.registerDefaultNetworkCallback(networkCallback)
            callbackRegistered = true
        } catch (e: RuntimeException) {
            // Ohne Rückmeldung zum Netz bleibt der Wiederaufbau über Wartezeiten und den Wächter.
        }
    }

    private fun startWorker() {
        if (worker?.isAlive == true) return
        stopped = false
        worker = Thread({
            try {
                loop()
            } finally {
                // Endet der Faden unerwartet, beendet sich der Dienst. Der Wächter startet ihn dann neu.
                if (!stopped) stopSelf()
            }
        }, "ntfy-verbindung").apply {
            isDaemon = true
            start()
        }
    }

    private fun loop() {
        var attempt = 0
        disconnectedSince = System.currentTimeMillis()
        while (!stopped) {
            val target = store.target
            if (target == null) {
                stopped = true
                stopSelf()
                break
            }
            val startedAt = SystemClock.elapsedRealtime()
            val outcome = listen(target)
            if (stopped) break
            if (outcome.connected) {
                disconnectedSince = System.currentTimeMillis()
                // War die Verbindung eine Weile stabil, beginnen die Wartezeiten wieder klein.
                if (SystemClock.elapsedRealtime() - startedAt > 60_000L) attempt = 0
            }
            attempt++
            val delay = Backoff.delayMs(attempt, outcome.rateLimited, Math.random())
            AppState.setConn(AppState.Conn.WAITING, outcome.detail, System.currentTimeMillis() + delay)
            updateLabel()
            try {
                // Wer drängt (Netz ist wieder da, der Wächter weckt, die App wird geöffnet), verkürzt die Wartezeit.
                if (signal.tryAcquire(delay, TimeUnit.MILLISECONDS) && !outcome.rateLimited) attempt = 0
            } catch (e: InterruptedException) {
                break
            }
        }
        AppState.setConn(AppState.Conn.STOPPED)
    }

    private fun listen(target: Target): Outcome {
        var connected = false
        var conn: HttpURLConnection? = null
        acquireWake(45_000L)
        AppState.setConn(AppState.Conn.CONNECTING, AppState.connDetail)
        updateLabel()
        try {
            val since = store.lastId ?: store.sinceTime.toString()
            conn = Http.open(Ntfy.streamUrl(target, since), CONNECT_TIMEOUT_MS, READ_TIMEOUT_MS)
            // Ohne Kompression, damit jede Zeile sofort ankommt und nicht in einem Puffer wartet.
            conn.setRequestProperty("Accept-Encoding", "identity")
            connection = conn
            val code = conn.responseCode
            if (code != 200) {
                return Outcome(false, code == 429, when (code) {
                    429 -> "Der Server bremst, weil zu viele Anfragen kamen."
                    401, 403 -> "Der Server verweigert den Zugriff auf dieses Thema."
                    else -> "Der Server antwortet mit Fehler $code."
                })
            }
            connected = true
            touch()
            AppState.setConn(AppState.Conn.CONNECTED)
            updateLabel()
            releaseWake()
            conn.inputStream.bufferedReader(Charsets.UTF_8).use { reader ->
                while (!stopped) {
                    val line = reader.readLine() ?: break
                    touch()
                    val event = Ntfy.parseLine(line)
                    if (event is StreamEvent.Message) {
                        acquireWake(20_000L)
                        try {
                            Sync.deliver(this, event.notice)
                        } finally {
                            releaseWake()
                        }
                    }
                }
            }
            return Outcome(true, false, "Der Server hat die Verbindung beendet.")
        } catch (e: IOException) {
            return Outcome(connected, false, describe(e))
        } catch (e: RuntimeException) {
            return Outcome(connected, false, "Unerwarteter Fehler (${e.javaClass.simpleName}).")
        } finally {
            connection = null
            try {
                conn?.disconnect()
            } catch (e: RuntimeException) {
                // nichts mehr zu schließen
            }
            releaseWake()
        }
    }

    private fun describe(e: IOException): String = when (e) {
        is UnknownHostException -> "Kein Netz, oder der Server ist nicht erreichbar."
        is SocketTimeoutException -> "Der Server hat sich nicht mehr gemeldet."
        is SSLException -> "Die gesicherte Verbindung kam nicht zustande."
        else -> "Die Verbindung wurde unterbrochen."
    }

    private fun touch() {
        AppState.lastActivityElapsed = SystemClock.elapsedRealtime()
    }

    private fun label(): String = when {
        AppState.conn == AppState.Conn.CONNECTED -> "Verbunden. Meldungen kommen sofort an."
        AppState.connDetail.isEmpty() -> "Verbindung wird aufgebaut …"
        else -> "Keine Verbindung seit ${clock(disconnectedSince)} Uhr. Die App versucht es weiter."
    }

    private fun updateLabel() {
        val text = label()
        if (text == lastLabel) return
        lastLabel = text
        Alerts.updateService(this, text)
    }

    /** Uhrzeit in österreichischer Zeit, so wie überall in der App und in den Texten des Radars. */
    private fun clock(ms: Long): String = SimpleDateFormat("HH:mm", Locale.GERMANY)
        .apply { timeZone = TimeZone.getTimeZone("Europe/Vienna") }
        .format(Date(ms))

    private fun kickInternal(force: Boolean) {
        if (force) closeConnection()
        wake()
    }

    private fun wake() {
        if (signal.availablePermits() == 0) signal.release()
    }

    /** Schließt die Verbindung von außen. Der Arbeitsfaden bemerkt das und baut sie neu auf. */
    private fun closeConnection() {
        val conn = connection ?: return
        // Auf einem eigenen Faden: Das Schließen einer gesicherten Verbindung spricht mit dem Netz.
        Thread({
            try {
                conn.disconnect()
            } catch (e: RuntimeException) {
                // schon geschlossen
            }
        }, "ntfy-schliessen").start()
    }

    private fun acquireWake(timeoutMs: Long) {
        try {
            wakeLock?.acquire(timeoutMs)
        } catch (e: RuntimeException) {
            // ohne Wachhalten geht es auch, nur langsamer
        }
    }

    private fun releaseWake() {
        try {
            wakeLock?.let { if (it.isHeld) it.release() }
        } catch (e: RuntimeException) {
            // war schon abgelaufen
        }
    }

    companion object {
        private const val CONNECT_TIMEOUT_MS = 20_000
        private const val READ_TIMEOUT_MS = 120_000

        /** So lange ohne Lebenszeichen, dann gilt eine Verbindung als tot. */
        const val STALE_AFTER_MS = 4 * 60_000L

        @Volatile var running = false
            private set

        @Volatile private var current: ListenerService? = null

        /** Startet den Dienst. Liefert false, wenn Android den Start aus dem Hintergrund ablehnt. */
        fun start(context: Context): Boolean = try {
            context.startForegroundService(Intent(context, ListenerService::class.java))
            true
        } catch (e: RuntimeException) {
            false
        }

        fun stop(context: Context) {
            context.stopService(Intent(context, ListenerService::class.java))
        }

        /**
         * Drängt den Dienst zu einem neuen Versuch. Mit [force] wird auch eine bestehende
         * Verbindung geschlossen und neu aufgebaut.
         */
        fun kick(force: Boolean) {
            current?.kickInternal(force)
        }
    }
}
