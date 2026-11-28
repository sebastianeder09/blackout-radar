// Sucht in der Seite der App nach Text, der nur aus "null", "undefined", "NaN" oder "[object Object]" besteht.
// So ein Text ist nie gewollt. Er entsteht, wenn der Aufbau der Seite einen fehlenden Wert als Text einfügt:
// Element.append(null) schreibt das Wort "null" in die Seite. emulator.sh wertet das über seite.py aus und
// erwartet die Antwort "sauber". Sonst nennt die Antwort den Text und das Element, in dem er steht.
(() => {
  const stray = /^(null|undefined|NaN|\[object Object\])$/;
  const found = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const text = node.textContent.trim();
    if (!stray.test(text)) continue;
    const parent = node.parentElement;
    found.push('"' + text + '" in <' + parent.tagName.toLowerCase() + (parent.id ? ' id=' + parent.id : '') +
      (parent.className ? ' class=' + parent.className : '') + '>');
  }
  return found.length ? 'FEHLER: ' + found.join(', ') : 'sauber';
})()
