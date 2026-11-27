// Prüft in der Seite der App, ob der Rahmen sitzt: Kopfzeile oben, Leiste unten, nichts ragt
// seitlich hinaus. emulator.sh wertet das über seite.py aus und erwartet eine Antwort, die mit
// "ok" beginnt. Die Maße in Klammern dienen dem Nachsehen im Protokoll.
(() => {
  const box = selector => {
    const element = document.querySelector(selector);
    return element ? element.getBoundingClientRect() : null;
  };
  const head = box('header.top');
  const tabs = box('nav.tabs');
  const problems = [];
  if (!head) problems.push('Kopfzeile fehlt');
  else if (Math.round(head.top) !== 0) problems.push('Kopfzeile nicht am oberen Rand');
  if (!tabs) problems.push('Leiste fehlt');
  else if (Math.abs(tabs.bottom - innerHeight) > 1) problems.push('Leiste nicht am unteren Rand');
  if (document.documentElement.scrollWidth > innerWidth) problems.push('Seite breiter als der Bildschirm');
  return (problems.length ? 'FEHLER: ' + problems.join(', ') : 'ok') +
    ' (Seite ' + innerWidth + ' x ' + innerHeight + ', Bildschirm ' + screen.width + ' x ' + screen.height +
    ', Faktor ' + devicePixelRatio + ')';
})()
