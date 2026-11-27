package io.github.sebastianeder09.blackoutradar

import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL

/** Der Server hat geantwortet, aber nicht mit 200. */
class HttpStatusException(val code: Int) : IOException("HTTP $code")

object Http {
    val USER_AGENT: String = "BlackoutRadar-App/" + BuildConfig.VERSION_NAME + " (Android)"
    private const val MAX_BYTES = 2 * 1024 * 1024

    fun open(url: String, connectTimeoutMs: Int, readTimeoutMs: Int): HttpURLConnection {
        val connection = URL(url).openConnection() as HttpURLConnection
        connection.connectTimeout = connectTimeoutMs
        connection.readTimeout = readTimeoutMs
        connection.useCaches = false
        connection.setRequestProperty("User-Agent", USER_AGENT)
        return connection
    }

    /** Lädt eine kleine Textdatei. Wirft IOException bei Netzfehlern und HttpStatusException bei Fehlerantworten. */
    fun getText(url: String, timeoutMs: Int = 15_000, accept: String? = null): String {
        val connection = open(url, timeoutMs, timeoutMs)
        if (accept != null) connection.setRequestProperty("Accept", accept)
        try {
            val code = connection.responseCode
            if (code != 200) throw HttpStatusException(code)
            connection.inputStream.use { stream ->
                val out = java.io.ByteArrayOutputStream()
                val buffer = ByteArray(16 * 1024)
                while (true) {
                    val n = stream.read(buffer)
                    if (n < 0) break
                    out.write(buffer, 0, n)
                    if (out.size() > MAX_BYTES) throw IOException("Antwort zu groß")
                }
                return out.toString("UTF-8")
            }
        } finally {
            connection.disconnect()
        }
    }
}
