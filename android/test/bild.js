// Fragt die Seite der App, ob sie gerade gezeichnet wird. emulator.sh wertet das über seite.py aus.
// Antwort "Bild nach <ms> ms", sobald nach dem Aufruf ein ganzes Bild entstanden ist, sonst "kein Bild".
// Eine WebView, die sich für unsichtbar hält, zeichnet nicht: Dann stünde am Handy ein alter Stand.
new Promise(resolve => {
  const start = performance.now();
  const state = () => ' (Sichtbarkeit: ' + document.visibilityState + ')';
  const timer = setTimeout(() => resolve('kein Bild in 4 s' + state()), 4000);
  requestAnimationFrame(() => requestAnimationFrame(() => {
    clearTimeout(timer);
    resolve('Bild nach ' + Math.round(performance.now() - start) + ' ms' + state());
  }));
})
