# Die Brücke zur Oberfläche wird nur über Namen aus JavaScript aufgerufen.
-keepclassmembers class io.github.sebastianeder09.blackoutradar.MainActivity$Bridge {
    @android.webkit.JavascriptInterface <methods>;
}
-keepattributes JavascriptInterface
