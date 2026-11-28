package io.github.sebastianeder09.blackoutradar

import android.Manifest
import android.annotation.SuppressLint
import android.annotation.TargetApi
import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.ClipData
import android.content.ClipDescription
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.res.Configuration
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.view.View
import android.view.ViewGroup
import android.view.WindowInsets
import android.view.WindowInsetsController
import android.webkit.JavascriptInterface
import android.webkit.RenderProcessGoneDetail
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import android.window.OnBackInvokedCallback
import android.window.OnBackInvokedDispatcher
import org.json.JSONObject
import java.io.IOException
import java.util.UUID

/**
 * Das einzige Fenster der App. Die Oberfläche ist eine eingebaute Seite (assets/www),
 * die in einer WebView läuft. Sie lädt nichts aus dem Netz: Alle Daten holt dieser Teil
 * hier und reicht sie über die Brücke "Native" an die Seite.
 */
class MainActivity : Activity() {

    private lateinit var store: Store
    private lateinit var root: FrameLayout
    private var webView: WebView? = null
    private val handler = Handler(Looper.getMainLooper())
    private var pageReady = false
    private var pendingTab: String? = null
    private var pendingOffer: Target? = null
    private var clipSeenAt = 0L
    private var clipWanted = false
    private var notifyQueued = false
    private var backGesture: BackGesture? = null

    private val stateListener: () -> Unit = {
        handler.post {
            // Mehrere Änderungen kurz hintereinander ergeben nur einen Anstoß.
            if (!notifyQueued) {
                notifyQueued = true
                handler.postDelayed({
                    notifyQueued = false
                    js("window.BR&&BR.changed()")
                }, 80L)
            }
        }
    }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        store = Store.get(this)
        pendingTab = intent?.getStringExtra(EXTRA_TAB)
        pendingOffer = linkTarget(intent)

        val view = WebView(this)
        webView = view
        root = FrameLayout(this)
        root.addView(view, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
        setContentView(root)
        applyColors()
        root.setOnApplyWindowInsetsListener { target, insets -> applyInsets(target, insets) }

        WebView.setWebContentsDebuggingEnabled(BuildConfig.DEBUG)
        view.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            allowFileAccess = false
            allowContentAccess = false
            setSupportZoom(false)
            cacheMode = WebSettings.LOAD_NO_CACHE
            safeBrowsingEnabled = false  // die Seite kommt aus der App selbst, nicht aus dem Netz
            textZoom = (resources.configuration.fontScale * 100).toInt().coerceIn(85, 160)
        }
        view.overScrollMode = View.OVER_SCROLL_NEVER
        view.isVerticalScrollBarEnabled = false
        view.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                // Die Seite verlässt die App nie. Verweise öffnet der Browser des Handys.
                openExternal(request.url.toString())
                return true
            }

            override fun onPageFinished(view: WebView, url: String) {
                pageReady = true
                pendingTab?.let { showTab(it) }
                pendingTab = null
                val link = pendingOffer
                pendingOffer = null
                // Ein Link, den der Mensch gerade angetippt hat, geht dem Thema aus der Installationsdatei vor.
                if (link != null) offerTopic(link) else if (!offerBuiltIn()) offerCopied()
            }

            override fun onRenderProcessGone(view: WebView, detail: RenderProcessGoneDetail): Boolean {
                // Android hat den Darstellungsprozess beendet (meist Speichermangel): Fenster neu aufbauen.
                pageReady = false
                root.removeView(view)
                view.destroy()
                webView = null
                recreate()
                return true
            }
        }
        view.addJavascriptInterface(Bridge(), "Native")
        view.loadDataWithBaseURL(BASE_URL, buildPage(), "text/html", "UTF-8", null)

        AppState.addListener(stateListener)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        linkTarget(intent)?.let { target ->
            if (pageReady) offerTopic(target) else pendingOffer = target
        }
        val tab = intent.getStringExtra(EXTRA_TAB) ?: return
        if (pageReady) showTab(tab) else pendingTab = tab
    }

    /**
     * Liest das Thema aus einem Link wie blackoutradar://abo/thema oder blackoutradar://abo?thema=thema.
     * Die Fassung aus dem Play Store meldet sich für solche Links gar nicht an (das tut nur das Manifest der
     * Fassung von GitHub). Kommt trotzdem einer an, gilt er nicht: Diese Fassung kennt nur den öffentlichen Alarm.
     */
    private fun linkTarget(intent: Intent?): Target? {
        if (PublicAlarm.ONLY) return null
        val data = intent?.data ?: return null
        if (intent.action != Intent.ACTION_VIEW) return null
        return Ntfy.parseLink(data.toString())
    }

    /**
     * Ist noch kein Thema eingerichtet, verbindet die App sofort: Ein Tipp auf den Link genügt.
     * Ein bestehendes Thema ersetzt sie nur nach Rückfrage. [fromFile] sagt der Seite, dass das Thema
     * nicht aus einem Link stammt, sondern aus der Installationsdatei.
     */
    private fun offerTopic(target: Target, fromFile: Boolean = false) {
        val current = store.target
        // Das ganze Ziel, nicht nur der Name: Bei einem eigenen Server gehört die Adresse dazu.
        val topic = quote(Ntfy.plain(target))
        val masked = quote(Ntfy.mask(target.topic))
        js("window.BR&&BR.offerTopic($topic,$masked,${current == target},${current == null},$fromFile)")
    }

    /**
     * Die Installationsdatei bringt ein Thema mit, weil ein anderes Handy die App samt Thema weitergegeben hat
     * (siehe [ApkTopic]). Ist noch nichts eingerichtet, verbindet die App damit sofort: Eintippen muss niemand
     * etwas. Ein bestehendes Thema ersetzt sie nur nach Rückfrage, und die stellt sie je Datei nur einmal.
     * Liefert true, wenn die Seite jetzt mit diesem Thema befasst ist.
     */
    private fun offerBuiltIn(): Boolean {
        val target = AppFile.pending(this) ?: return false
        val current = store.target
        if (current != null) {
            // Wie auch immer die Antwort ausfällt: Dieselbe Datei fragt kein zweites Mal.
            AppFile.markSeen(this)
            if (current == target) return false
        }
        offerTopic(target, fromFile = true)
        return true
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus) offerCopied()
    }

    /**
     * Die Seite zum Verbinden des eigenen Radars ist offen: Hat der Mensch die weitergegebene Nachricht eines
     * anderen Handys kopiert, trägt die App das Thema daraus selbst ins Feld ein. Verbinden tippt er selbst. Aus
     * der Zwischenablage zählt nur der Link der App. Alles andere darin bleibt unberührt und verlässt diese
     * Funktion nicht.
     *
     * Android lässt eine App nur in die Zwischenablage sehen, solange ihr Fenster vorn ist, und zeigt ab
     * Android 12 kurz an, dass sie es getan hat. Deshalb sieht die App jeden Inhalt nur einmal an, und nur
     * solange diese eine Seite offen ist ([clipWanted]). Wer nur den öffentlichen Alarm einschaltet, dessen
     * Zwischenablage sieht die App nie an.
     */
    private fun offerCopied(again: Boolean = true) {
        if (!pageReady || !clipWanted || !hasWindowFocus() || store.target != null) return
        // Bringt die Installationsdatei das Thema mit, braucht es die Zwischenablage nicht.
        if (AppFile.pending(this) != null) return
        val text = try {
            val clipboard = getSystemService(ClipboardManager::class.java) ?: return
            val about = clipboard.primaryClipDescription
            if (about == null) {
                // Leer, oder Android zählt das Fenster noch nicht als vorn: gleich noch ein Mal nachsehen.
                if (again) handler.postDelayed({ offerCopied(again = false) }, 500L)
                return
            }
            if (!about.hasMimeType(ClipDescription.MIMETYPE_TEXT_PLAIN) && !about.hasMimeType(ClipDescription.MIMETYPE_TEXT_HTML)) return
            // Ohne Zeitangabe (0) lässt sich nicht sagen, ob es noch derselbe Inhalt ist: dann lieber noch einmal ansehen.
            if (about.timestamp != 0L && about.timestamp == clipSeenAt) return
            val clip = clipboard.primaryClip ?: return
            clipSeenAt = about.timestamp
            if (clip.itemCount > 0) clip.getItemAt(0).text?.toString() else null
        } catch (e: RuntimeException) {
            null  // Android gibt die Zwischenablage gerade nicht her
        } ?: return
        val target = Ntfy.sharedTarget(text, BuildConfig.DEBUG) ?: return
        js("window.BR&&BR.onCopied(${quote(Ntfy.plain(target))})")
    }

    /**
     * Lädt den Lagebericht für die Anzeige und gleicht ihn dabei mit den angekommenen Meldungen ab (Notweg).
     * Ein unerwarteter Fehler darin darf die App nicht beenden: Die Verbindung zu ntfy läuft im selben Prozess.
     */
    private fun loadStatus(app: Context) {
        try {
            Fallback.sync(app)
        } catch (e: RuntimeException) {
            // Die Anzeige bleibt beim letzten Stand. Der Wächter gleicht in ein paar Minuten wieder ab.
        }
    }

    override fun onResume() {
        super.onResume()
        webView?.onResume()
        if (Starter.ensure(this) && AppState.conn != AppState.Conn.CONNECTED) ListenerService.kick(force = false)
        js("window.BR&&BR.changed()")
        val now = System.currentTimeMillis()
        val app = applicationContext
        if (now - store.statusFetchedAt > 2 * 60_000L && !AppState.statusLoading) {
            Thread({ loadStatus(app) }, "lagebericht").start()
        }
        if (Updates.ENABLED && now - store.updateCheckedAt > Updates.CHECK_EVERY_MS) {
            Thread({ Updates.check(app) }, "update").start()
        }
    }

    override fun onPause() {
        webView?.onPause()
        super.onPause()
    }

    override fun onDestroy() {
        AppState.removeListener(stateListener)
        handler.removeCallbacksAndMessages(null)
        armBack(false)
        webView?.let {
            root.removeView(it)
            it.destroy()
        }
        webView = null
        super.onDestroy()
    }

    override fun onConfigurationChanged(newConfig: Configuration) {
        super.onConfigurationChanged(newConfig)
        applyColors()
        js("window.BR&&BR.changed()")
    }

    /**
     * Die Zurück-Geste ab Android 13. Dort fragt Android nicht mehr im Augenblick der Geste, ob die App sie
     * selbst behandelt: Die App meldet das vorher an. Die Seite sagt deshalb laufend, ob sie gerade etwas zum
     * Zurückgehen hat (ein Dialog, eine Unterseite, ein anderer Tab als "Lage"). Sonst schließt die Geste die App.
     */
    private fun armBack(armed: Boolean) {
        if (Build.VERSION.SDK_INT < 33) return
        if (armed && backGesture == null) {
            backGesture = BackGesture(this) { js("window.BR&&BR.back()") }
        } else if (!armed) {
            backGesture?.release()
            backGesture = null
        }
    }

    @Deprecated("Android ruft das bis einschließlich Version 12 für die Zurück-Geste auf, danach gilt armBack.")
    override fun onBackPressed() {
        val view = webView
        if (view == null || !pageReady) {
            @Suppress("DEPRECATION")
            super.onBackPressed()
            return
        }
        view.evaluateJavascript("window.BR?BR.back():false") { handled ->
            if (handled != "true") {
                @Suppress("DEPRECATION")
                super.onBackPressed()
            }
        }
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == REQUEST_NOTIFICATIONS) {
            js("window.BR&&BR.changed()")
            if (askBatteryNext) {
                askBatteryNext = false
                if (!batteryExempt()) requestBattery()
            }
        }
    }

    // ------------------------------------------------------------------ Darstellung

    private fun isDark(): Boolean =
        (resources.configuration.uiMode and Configuration.UI_MODE_NIGHT_MASK) == Configuration.UI_MODE_NIGHT_YES

    private fun applyColors() {
        val dark = isDark()
        // Kopf- und Fußleiste der Seite haben diese Farbe, so gehen sie nahtlos in die Leisten von Android über.
        val background = if (dark) 0xFF161B22.toInt() else 0xFFFFFFFF.toInt()
        root.setBackgroundColor(background)
        webView?.setBackgroundColor(background)
        @Suppress("DEPRECATION")
        run {
            window.statusBarColor = background
            window.navigationBarColor = background
        }
        if (Build.VERSION.SDK_INT >= 30) {
            val light = WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS or
                WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS
            window.insetsController?.setSystemBarsAppearance(if (dark) 0 else light, light)
        } else {
            @Suppress("DEPRECATION")
            window.decorView.systemUiVisibility =
                if (dark) 0 else View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR or View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR
        }
    }

    /** Hält den Inhalt frei von Statusleiste, Navigationsleiste und Tastatur. */
    private fun applyInsets(target: View, insets: WindowInsets): WindowInsets {
        if (Build.VERSION.SDK_INT >= 30) {
            val bars = insets.getInsets(WindowInsets.Type.systemBars() or WindowInsets.Type.displayCutout() or
                WindowInsets.Type.ime())
            target.setPadding(bars.left, bars.top, bars.right, bars.bottom)
            return WindowInsets.CONSUMED
        }
        @Suppress("DEPRECATION")
        target.setPadding(insets.systemWindowInsetLeft, insets.systemWindowInsetTop,
            insets.systemWindowInsetRight, insets.systemWindowInsetBottom)
        @Suppress("DEPRECATION")
        return insets.consumeSystemWindowInsets()
    }

    private fun buildPage(): String {
        fun asset(name: String): String = assets.open("www/$name").bufferedReader(Charsets.UTF_8).use { it.readText() }
        val nonce = UUID.randomUUID().toString().replace("-", "")
        return asset("index.html")
            .replace("__NONCE__", nonce)
            .replace("/*__CSS__*/", asset("app.css"))
            .replace("/*__JS__*/", asset("app.js"))
    }

    private fun js(code: String) {
        if (pageReady) webView?.evaluateJavascript(code, null)
    }

    /** Text als JavaScript-Zeichenkette, sicher gegen alles, was darin stehen kann. */
    private fun quote(text: String): String =
        JSONObject.quote(text).replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")

    private fun showTab(tab: String) {
        js("window.BR&&BR.showTab(${quote(tab)})")
    }

    // ------------------------------------------------------------------ Erlaubnisse

    private var askBatteryNext = false

    private fun notificationsGranted(): Boolean =
        Build.VERSION.SDK_INT < 33 || checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED

    private fun batteryExempt(): Boolean =
        getSystemService(android.os.PowerManager::class.java)?.isIgnoringBatteryOptimizations(packageName) ?: true

    /** Nach dem Einrichten: erst die Benachrichtigungen, danach die Ausnahme von der Akku-Optimierung. */
    private fun askPermissionsOnce() {
        if (store.askedPermissions) return
        if (Build.VERSION.SDK_INT >= 33 && !notificationsGranted()) {
            askBatteryNext = true
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), REQUEST_NOTIFICATIONS)
        } else if (!batteryExempt()) {
            requestBattery()
        }
        store.askedPermissions = true
    }

    private fun requestNotifications() {
        if (Build.VERSION.SDK_INT >= 33 && !notificationsGranted()) {
            // Nach zweimaligem Ablehnen zeigt Android die Frage nicht mehr. Dann helfen nur die Einstellungen.
            val blocked = store.askedPermissions && !shouldShowRequestPermissionRationale(Manifest.permission.POST_NOTIFICATIONS)
            store.askedPermissions = true
            if (blocked) openNotificationSettings()
            else requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), REQUEST_NOTIFICATIONS)
        } else {
            openNotificationSettings()
        }
    }

    @SuppressLint("BatteryLife")
    private fun requestBattery() {
        try {
            startActivity(Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:$packageName")))
        } catch (e: ActivityNotFoundException) {
            try {
                startActivity(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
            } catch (e2: ActivityNotFoundException) {
                // Dieses Gerät kennt die Einstellung nicht.
            }
        }
    }

    private fun openNotificationSettings() {
        try {
            startActivity(Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS)
                .putExtra(Settings.EXTRA_APP_PACKAGE, packageName))
        } catch (e: ActivityNotFoundException) {
            // siehe requestBattery
        }
    }

    private fun openExternal(url: String) {
        if (!url.startsWith("https://") && !url.startsWith("http://")) return
        try {
            startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
        } catch (e: ActivityNotFoundException) {
            // kein Browser eingerichtet
        }
    }

    // ------------------------------------------------------------------ Brücke zur Seite

    /** Was die Seite aufrufen darf. Die Aufrufe kommen auf einem eigenen Faden an, nicht auf dem Hauptfaden. */
    private inner class Bridge {
        @JavascriptInterface
        fun state(): String = StateJson.build(applicationContext, isDark()).toString()

        @JavascriptInterface
        fun messages(): String {
            val array = org.json.JSONArray()
            for (notice in store.log.all()) {
                array.put(notice.toJson().put("level", notice.level).put("symbols", Ntfy.emoji(notice.tags))
                    .put("viaText", Fallback.reason(notice.via, notice.public)))
            }
            return array.toString()
        }

        @JavascriptInterface
        fun status(): String = JSONObject()
            .put("json", StatusRepo.cachedJson(store) ?: "")
            .put("md", StatusRepo.cachedMarkdown(store) ?: "")
            .toString()

        @JavascriptInterface
        fun paste() {
            runOnUiThread {
                val clip = try {
                    getSystemService(ClipboardManager::class.java)?.primaryClip
                } catch (e: RuntimeException) {
                    null
                }
                val text = if (clip != null && clip.itemCount > 0) clip.getItemAt(0).coerceToText(this@MainActivity).toString() else ""
                // Aus einer weitergegebenen Nachricht zählt nur der Link der App, der Rest ist Anleitung.
                val shared = Ntfy.sharedTarget(text, BuildConfig.DEBUG)
                js("window.BR&&BR.onPaste(${quote(shared?.let { Ntfy.plain(it) } ?: text.take(500))})")
            }
        }

        @JavascriptInterface
        fun setTopic(text: String) {
            connect("einrichten") { Sync.setup(it, text) }
        }

        /** Schaltet den öffentlichen Alarm ein: das feste Thema für alle. Einzugeben ist dafür nichts. */
        @JavascriptInterface
        fun enablePublic() {
            connect("einschalten") { Sync.setupPublic(it) }
        }

        private fun connect(name: String, setup: (Context) -> Sync.SetupResult) {
            val app = applicationContext
            Thread({
                val result = setup(app)
                val json = JSONObject().put("ok", result.ok).put("error", result.error)
                    .put("count", result.count).put("offline", result.offline)
                    .put("public", result.ok && PublicAlarm.active(store))
                runOnUiThread {
                    js("window.BR&&BR.onSetup($json)")
                    if (result.ok) askPermissionsOnce()
                }
                if (result.ok) loadStatus(app)
            }, name).start()
        }

        @JavascriptInterface
        fun resetTopic() {
            Sync.reset(applicationContext)
        }

        /** Öffnet die Auswahl von Android (Messenger, E-Mail …) mit Download und Thema für ein weiteres Handy. */
        @JavascriptInterface
        fun share() {
            val target = store.target ?: return
            val send = Intent(Intent.ACTION_SEND)
                .setType("text/plain")
                .putExtra(Intent.EXTRA_TEXT, Ntfy.shareText(target, Updates.DOWNLOAD_URL))
            runOnUiThread {
                try {
                    startActivity(Intent.createChooser(send, "Weitergeben"))
                } catch (e: ActivityNotFoundException) {
                    // Dieses Gerät hat keine App, die Text annimmt.
                }
            }
        }

        /**
         * Empfiehlt die App weiter: Android zeigt seine Auswahl mit einem kurzen Text und dem Weg zur App.
         * Ein Thema steht nicht darin. Wer die App so bekommt, schaltet den öffentlichen Alarm selbst ein.
         */
        @JavascriptInterface
        fun recommend() {
            val send = Intent(Intent.ACTION_SEND)
                .setType("text/plain")
                .putExtra(Intent.EXTRA_TEXT, "Blackout-Radar: Alarm aufs Handy bei einem großen Stromausfall in Österreich. " +
                    "Kostenlos und ohne Anmeldung, von ${Brand.NAME}.\n\n${Updates.DOWNLOAD_URL}")
            runOnUiThread {
                try {
                    startActivity(Intent.createChooser(send, "App empfehlen"))
                } catch (e: ActivityNotFoundException) {
                    // Dieses Gerät hat keine App, die Text annimmt.
                }
            }
        }

        /**
         * Gibt die App selbst weiter: als Installationsdatei, die das Thema dieses Handys schon enthält (siehe
         * [ApkTopic]). Android zeigt seine Auswahl (Messenger, Quick Share, Bluetooth …). Lesen darf die Datei
         * nur die App, die der Mensch dort wählt.
         */
        @JavascriptInterface
        fun shareApp() {
            val target = store.target ?: return
            val app = applicationContext
            Thread({
                val written = try {
                    AppFile.writeShare(app, target)
                    true
                } catch (e: IOException) {
                    false
                }
                runOnUiThread {
                    if (!written) {
                        js("window.BR&&BR.onShareFailed()")
                        return@runOnUiThread
                    }
                    val uri = AppFile.shareUri(app)
                    val send = Intent(Intent.ACTION_SEND)
                        .setType(AppFile.MIME)
                        .putExtra(Intent.EXTRA_STREAM, uri)
                        .putExtra(Intent.EXTRA_TEXT, AppFile.SHARE_TEXT)
                        .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                    // Mit dieser Angabe gilt die Leseerlaubnis auch für die Auswahl von Android, die den Namen der Datei zeigt.
                    send.clipData = ClipData(AppFile.SHARE_NAME, arrayOf(AppFile.MIME), ClipData.Item(AppFile.SHARE_TEXT, null, null, uri))
                    try {
                        startActivity(Intent.createChooser(send, "App samt Thema weitergeben"))
                    } catch (e: ActivityNotFoundException) {
                        js("window.BR&&BR.onShareFailed()")
                    }
                }
            }, "weitergeben").start()
        }

        /** Auf der Seite zum Einrichten: das Thema nehmen, das die Installationsdatei mitgebracht hat. */
        @JavascriptInterface
        fun useBuiltIn() {
            runOnUiThread {
                val target = AppFile.builtIn(applicationContext)
                if (target != null && store.target == null) offerTopic(target, fromFile = true)
            }
        }

        @JavascriptInterface
        fun refreshStatus() {
            val app = applicationContext
            Thread({ loadStatus(app) }, "lagebericht").start()
        }

        @JavascriptInterface
        fun reconnect() {
            runOnUiThread {
                if (Starter.ensure(this@MainActivity)) ListenerService.kick(force = AppState.conn == AppState.Conn.CONNECTED)
            }
        }

        @JavascriptInterface
        fun requestNotifications() {
            runOnUiThread { this@MainActivity.requestNotifications() }
        }

        @JavascriptInterface
        fun requestBattery() {
            runOnUiThread { this@MainActivity.requestBattery() }
        }

        @JavascriptInterface
        fun openNotificationSettings() {
            runOnUiThread { this@MainActivity.openNotificationSettings() }
        }

        @JavascriptInterface
        fun testAlarm() {
            Alerts.showTest(applicationContext)
        }

        @JavascriptInterface
        fun setSetting(key: String, value: Boolean) {
            when (key) {
                "loudAlarm" -> store.loudAlarm = value
                "repeatAlarm" -> store.repeatAlarm = value
                "watchMonitor" -> {
                    store.watchMonitor = value
                    if (!value) Alerts.cancelStale(applicationContext)
                }
            }
            AppState.changed()
        }

        @JavascriptInterface
        fun openUrl(url: String) {
            runOnUiThread { openExternal(url) }
        }

        @JavascriptInterface
        fun checkUpdate() {
            val app = applicationContext
            Thread({
                val ok = Updates.check(app)
                runOnUiThread { js("window.BR&&BR.onUpdateChecked($ok)") }
            }, "update").start()
        }

        @JavascriptInterface
        fun downloadUpdate() {
            if (Updates.ENABLED) runOnUiThread { openExternal(Updates.DOWNLOAD_URL) }
        }

        /** Impressum oder Datenschutzerklärung, so wie sie in der App liegen (Markdown), siehe [Legal]. */
        @JavascriptInterface
        fun legal(name: String): String = Legal.text(applicationContext, name)

        /** Die Seite sagt, ob die Seite zum Verbinden des eigenen Radars offen ist, siehe [offerCopied]. */
        @JavascriptInterface
        fun setupOpen(open: Boolean) {
            runOnUiThread {
                clipWanted = open
                if (open) offerCopied()
            }
        }

        /** Die Seite sagt, ob sie gerade etwas zum Zurückgehen hat, siehe [armBack]. */
        @JavascriptInterface
        fun backArmed(armed: Boolean) {
            runOnUiThread { armBack(armed && pageReady) }
        }

        /** Öffnet das Telefon mit der Nummer des Anbieters. Gewählt wird erst, wenn der Mensch dort bestätigt. */
        @JavascriptInterface
        fun callCompany() {
            runOnUiThread { openIntent(Intent(Intent.ACTION_DIAL, Uri.parse("tel:" + Brand.PHONE_DIAL))) }
        }

        /**
         * Öffnet das E-Mail-Programm mit der Adresse des Anbieters. [about] sagt, worum es geht ("usv" für die
         * Beratung zur Stromversorgung), und steht dann im Betreff. Abgeschickt wird nichts von selbst.
         */
        @JavascriptInterface
        fun mailCompany(about: String) {
            if (Brand.MAIL.isEmpty()) return
            val subject = if (about == "usv") "Anfrage USV-Beratung (über die App Blackout-Radar)" else "Anfrage über die App Blackout-Radar"
            runOnUiThread {
                openIntent(Intent(Intent.ACTION_SENDTO, Uri.parse("mailto:" + Brand.MAIL)).putExtra(Intent.EXTRA_SUBJECT, subject))
            }
        }
    }

    private fun openIntent(intent: Intent) {
        try {
            startActivity(intent)
        } catch (e: ActivityNotFoundException) {
            // Dieses Gerät hat keine App dafür.
        }
    }

    companion object {
        const val EXTRA_TAB = "tab"
        private const val REQUEST_NOTIFICATIONS = 1
        private const val BASE_URL = "https://blackout-radar.invalid/"
    }
}

/**
 * Die Anmeldung für die Zurück-Geste ab Android 13, siehe MainActivity.armBack. In einer eigenen Klasse,
 * damit ältere Android-Fassungen die neuen Klassen gar nicht erst laden.
 */
@TargetApi(33)
private class BackGesture(private val activity: Activity, onBack: () -> Unit) {
    private val callback = OnBackInvokedCallback { onBack() }

    init {
        activity.onBackInvokedDispatcher.registerOnBackInvokedCallback(OnBackInvokedDispatcher.PRIORITY_DEFAULT, callback)
    }

    fun release() {
        activity.onBackInvokedDispatcher.unregisterOnBackInvokedCallback(callback)
    }
}
