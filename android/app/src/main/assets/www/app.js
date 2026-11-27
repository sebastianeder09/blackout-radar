'use strict';
/*
 * Oberfläche der App. Läuft in der WebView und lädt nichts aus dem Netz:
 * Alle Daten kommen über die Brücke "Native" (MainActivity.Bridge).
 * Umgekehrt ruft die App Funktionen von window.BR auf.
 */
(function () {
  const N = window.Native;
  if (!N) return;

  const app = document.getElementById('app');
  const DAY = 86400000;
  const STALE_MS = 3 * 3600000;

  const S = {
    st: null,          // Zustand der App
    msgs: [],          // Meldungen, neueste zuerst
    status: null,      // status.json
    md: '',            // status.md
    revM: -1,
    revS: -1,
    tab: 'lage',
    scroll: {},
    open: loadOpen(),  // offene Abschnitte des Lageberichts
    expanded: new Set(),
    setup: { busy: false, error: '', result: null, value: '', fromLink: false },
    modal: null,
    shell: null,
    refreshTimer: 0,
  };

  // ------------------------------------------------------------------ Symbole

  const ICON = {
    lage: '<svg viewBox="0 0 24 24"><path d="M3 12h4l3-8 4 16 3-8h4"/></svg>',
    bell: '<svg viewBox="0 0 24 24"><path d="M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/></svg>',
    phone: '<svg viewBox="0 0 24 24"><rect x="6" y="2" width="12" height="20" rx="2.5"/><path d="M11 18h2"/></svg>',
    refresh: '<svg viewBox="0 0 24 24"><path d="M21 12a9 9 0 1 1-2.64-6.36"/><path d="M21 3v6h-6"/></svg>',
    check: '<svg viewBox="0 0 24 24"><path d="M20 6 9 17l-5-5"/></svg>',
    x: '<svg viewBox="0 0 24 24"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>',
    alert: '<svg viewBox="0 0 24 24"><path d="m21.7 18-8-14a2 2 0 0 0-3.4 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.7-3Z"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>',
    zap: '<svg viewBox="0 0 24 24"><path d="M13 2 3 14h9l-1 8 10-12h-9z"/></svg>',
    shield: '<svg viewBox="0 0 24 24"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"/><path d="m9 12 2 2 4-4"/></svg>',
    info: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>',
    chev: '<svg viewBox="0 0 24 24"><path d="m9 18 6-6-6-6"/></svg>',
    ext: '<svg viewBox="0 0 24 24"><path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/></svg>',
    paste: '<svg viewBox="0 0 24 24"><rect x="8" y="2" width="8" height="4" rx="1"/><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/></svg>',
    wifi: '<svg viewBox="0 0 24 24"><path d="M12 20h.01"/><path d="M2 8.8a15 15 0 0 1 20 0"/><path d="M5 12.9a10 10 0 0 1 14 0"/><path d="M8.5 16.4a5 5 0 0 1 7 0"/></svg>',
    share: '<svg viewBox="0 0 24 24"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><path d="m8.6 13.5 6.8 4"/><path d="m15.4 6.5-6.8 4"/></svg>',
  };
  // Dasselbe Zeichen wie das App-Symbol (res/drawable/ic_launcher_foreground.xml), als Kachel mit runden Ecken.
  const LOGO = '<svg class="logo" viewBox="14 14 80 80" aria-hidden="true"><rect x="14" y="14" width="80" height="80" rx="20" fill="#E1F0FF"/>' +
    '<path d="M24,54 a30,30 0 1,0 60,0 a30,30 0 1,0 -60,0" fill="none" stroke="#008FFF" stroke-width="2.4" stroke-opacity="0.22"/>' +
    '<path d="M31.5,54 a22.5,22.5 0 1,0 45,0 a22.5,22.5 0 1,0 -45,0" fill="#D4EAFF"/>' +
    '<path d="M57.28,34.32 L43.34,56.46 L52.36,56.46 L49.08,73.68 L64.66,51.54 L55.23,51.54 Z" fill="#008FFF" stroke="#008FFF" stroke-width="2.6" stroke-linejoin="round"/></svg>';

  const LEVEL_NAME = { alarm: 'Alarm', warn: 'Warnung', ok: 'Entwarnung', info: 'Meldung', daily: 'Übersicht' };
  const OPEN_DEFAULT = { 'Laufende Ereignisse': true, 'Kürzlich beendet': true };

  // ------------------------------------------------------------------- Helfer

  function el(tag, props) {
    const e = document.createElement(tag);
    if (props) {
      for (const k of Object.keys(props)) {
        const v = props[k];
        if (v == null || v === false) continue;
        if (k === 'class') e.className = v;
        else if (k === 'text') e.textContent = v;
        else if (k === 'html') e.innerHTML = v;  // nur für die festen Symbole oben
        else if (k.slice(0, 2) === 'on') e.addEventListener(k.slice(2), v);
        else e.setAttribute(k, v === true ? '' : String(v));
      }
    }
    for (let i = 2; i < arguments.length; i++) add(e, arguments[i]);
    return e;
  }

  function add(parent, kid) {
    if (kid == null || kid === false) return;
    if (Array.isArray(kid)) { kid.forEach(k => add(parent, k)); return; }
    parent.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }

  function icon(name, cls) {
    return el('span', { class: 'ico' + (cls ? ' ' + cls : ''), html: ICON[name], 'aria-hidden': 'true' });
  }

  const pad = n => String(n).padStart(2, '0');
  const WD = ['So.', 'Mo.', 'Di.', 'Mi.', 'Do.', 'Fr.', 'Sa.'];
  const WD_EN = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

  // Alle Uhrzeiten in österreichischer Zeit, so wie der Radar sie in seinen Texten schreibt.
  // Sonst stünden auf einem Handy mit anderer Zeitzone zwei verschiedene Zeiten nebeneinander.
  let ZONE = null;
  try {
    ZONE = new Intl.DateTimeFormat('en-GB', {
      timeZone: 'Europe/Vienna', hourCycle: 'h23', weekday: 'short',
      year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
    });
  } catch (e) {
    ZONE = null;  // sehr alte WebView: dann gilt die Zeit des Handys
  }

  /** Zerlegt einen Zeitpunkt: { y, mo, d, h, mi, wd } mit zweistelligen Texten und dem Wochentag 0 bis 6. */
  function local(ms) {
    const d = new Date(ms);
    if (ZONE) {
      const p = {};
      for (const part of ZONE.formatToParts(d)) p[part.type] = part.value;
      return { y: p.year, mo: p.month, d: p.day, h: p.hour === '24' ? '00' : p.hour, mi: p.minute, wd: WD_EN.indexOf(p.weekday) };
    }
    return { y: String(d.getFullYear()), mo: pad(d.getMonth() + 1), d: pad(d.getDate()), h: pad(d.getHours()), mi: pad(d.getMinutes()), wd: d.getDay() };
  }

  function clock(ms) {
    const t = local(ms);
    return t.h + ':' + t.mi;
  }

  function sameDay(a, b) {
    const x = local(a), y = local(b);
    return x.y === y.y && x.mo === y.mo && x.d === y.d;
  }

  function dayLabel(ms, now) {
    if (sameDay(ms, now)) return 'Heute';
    if (sameDay(ms, now - DAY)) return 'Gestern';
    const t = local(ms);
    return WD[t.wd] + ', ' + t.d + '.' + t.mo + '.' + t.y;
  }

  /** Zeitpunkt mit Tag, wenn er nicht heute war: "11:05" oder "Gestern 23:10". */
  function when(ms, now) {
    return sameDay(ms, now) ? clock(ms) + ' Uhr' : dayLabel(ms, now) + ', ' + clock(ms) + ' Uhr';
  }

  /** Zeitspanne wie im Lagebericht: "45 min", "3 h 05 min", "2 T 4 h". */
  function span(ms) {
    const m = Math.max(0, Math.floor(ms / 60000));
    if (m < 60) return m + ' min';
    const h = Math.floor(m / 60);
    if (h < 48) return h + ' h ' + pad(m % 60) + ' min';
    return Math.floor(h / 24) + ' T ' + (h % 24) + ' h';
  }

  function ago(ms) {
    if (ms < 60000) return 'gerade eben';
    return 'vor ' + span(ms);
  }

  function people(n) {
    if (n >= 1e6) return (n / 1e6).toFixed(1).replace('.', ',') + ' Mio.';
    const r = n >= 10000 ? Math.round(n / 1000) * 1000 : Math.round(n / 100) * 100;
    return r.toLocaleString('de-AT');
  }

  function plural(n, one, many) { return n + ' ' + (n === 1 ? one : many); }

  function parseJson(text, fallback) {
    if (!text) return fallback;
    try { return JSON.parse(text); } catch (e) { return fallback; }
  }

  function loadOpen() {
    try { return JSON.parse(localStorage.getItem('offen') || '{}') || {}; } catch (e) { return {}; }
  }

  function saveOpen() {
    try { localStorage.setItem('offen', JSON.stringify(S.open)); } catch (e) { /* egal */ }
  }

  let toastTimer = 0;
  function toast(text) {
    const t = document.getElementById('toast');
    t.textContent = text;
    t.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.remove('show'), 3400);
  }

  const statusUrl = () => 'https://github.com/' + S.st.repo + '/blob/state/status.md';
  const actionsUrl = () => 'https://github.com/' + S.st.repo + '/actions/workflows/monitor.yml';
  const isStatusLink = url => !!url && url.indexOf('/blob/state/status.md') >= 0;

  // ----------------------------------------------------------- Daten holen

  function refresh() {
    const st = parseJson(N.state(), null);
    if (!st) return;
    S.st = st;
    if (st.messagesRev !== S.revM) {
      const first = S.revM < 0;
      const before = S.msgs.length ? S.msgs[0].id : null;
      S.revM = st.messagesRev;
      S.msgs = parseJson(N.messages(), []);
      // Kommt eine neue Meldung, liegt kurz danach auch ein neuer Lagebericht bei GitHub.
      if (!first && S.msgs.length && S.msgs[0].id !== before) scheduleStatusRefresh();
    }
    if (st.statusRev !== S.revS) {
      S.revS = st.statusRev;
      const raw = parseJson(N.status(), {});
      S.status = parseJson(raw.json, null);
      S.md = raw.md || '';
    }
    render();
  }

  function scheduleStatusRefresh() {
    clearTimeout(S.refreshTimer);
    S.refreshTimer = setTimeout(() => N.refreshStatus(), 45000);
  }

  // ---------------------------------------------------------------- Aufbau

  function render() {
    const st = S.st;
    document.documentElement.setAttribute('data-theme', st.dark ? 'dark' : 'light');
    if (!st.hasTopic || S.setup.busy || S.setup.result) {
      renderSetup();
    } else {
      renderMain();
    }
    renderModal();
  }

  function renderMain() {
    if (!S.shell) buildShell();
    const sh = S.shell;
    const st = S.st;

    // Verbindung oben rechts
    const c = st.conn.state;
    const pill = c === 'connected' ? ['ok', 'Verbunden'] : c === 'connecting' ? ['warn', 'Verbindet'] :
      c === 'waiting' ? ['alarm', 'Getrennt'] : ['alarm', 'Aus'];
    sh.pill.className = 'pill ' + pill[0];
    sh.pill.textContent = '';
    add(sh.pill, [el('span', { class: 'dot' }), pill[1]]);
    sh.refresh.classList.toggle('spin', !!st.status.loading);

    // Punkt am Tab "App", wenn dort etwas zu tun ist
    const todo = !st.perms.notifications || !st.perms.battery || st.perms.alarmMuted || st.update.available;
    sh.appDot.hidden = !todo;

    for (const name of ['lage', 'meldungen', 'app']) {
      sh.tabs[name].setAttribute('aria-selected', String(S.tab === name));
      sh.views[name].hidden = S.tab !== name;
    }
    if (S.tab === 'lage') renderLage(sh.views.lage);
    else if (S.tab === 'meldungen') renderMessages(sh.views.meldungen);
    else renderApp(sh.views.app);
  }

  function buildShell() {
    document.body.classList.remove('setup-mode');
    app.textContent = '';
    const sh = { views: {}, tabs: {} };
    sh.pill = el('button', { class: 'pill', onclick: () => showTab('app'), 'aria-label': 'Verbindung' });
    sh.refresh = el('button', { class: 'icon-btn', 'aria-label': 'Aktualisieren', onclick: onRefresh }, icon('refresh'));
    const top = el('header', { class: 'top' },
      el('div', { class: 'brand', html: LOGO }, el('h1', { text: 'Blackout-Radar' })),
      sh.pill, sh.refresh);
    const main = el('main');
    for (const name of ['lage', 'meldungen', 'app']) {
      sh.views[name] = el('section', { class: 'view', 'aria-label': name });
      main.append(sh.views[name]);
    }
    const nav = el('nav', { class: 'tabs' });
    const tab = (name, label, ico) => {
      const b = el('button', { onclick: () => showTab(name), 'aria-selected': 'false' }, icon(ico), el('span', { text: label }));
      sh.tabs[name] = b;
      nav.append(b);
      return b;
    };
    tab('lage', 'Lage', 'lage');
    tab('meldungen', 'Meldungen', 'bell');
    tab('app', 'App', 'phone');
    sh.appDot = el('span', { class: 'badge-dot', hidden: true });
    sh.tabs.app.append(sh.appDot);
    app.append(top, main, nav);
    S.shell = sh;
  }

  function showTab(name) {
    if (!S.shell) { S.tab = name; return; }
    if (name === S.tab) { window.scrollTo(0, 0); return; }
    S.scroll[S.tab] = window.scrollY;
    S.tab = name;
    renderMain();
    window.scrollTo(0, S.scroll[name] || 0);
  }

  function onRefresh() {
    N.refreshStatus();
    if (S.st.conn.state !== 'connected') N.reconnect();
    toast('Wird aktualisiert …');
  }

  // ------------------------------------------------------------------- Lage

  function renderLage(v) {
    v.textContent = '';
    const s = S.status;
    const st = S.st;
    const now = Date.now();
    if (!s) {
      v.append(el('div', { class: 'hero info' },
        el('div', { class: 'hero-head' },
          el('span', { class: 'hero-icon' }, icon(st.status.loading ? 'refresh' : 'info', st.status.loading ? 'spin' : '')),
          el('div', null,
            el('h2', { text: st.status.loading ? 'Lagebericht wird geladen …' : 'Noch kein Lagebericht' }),
            el('div', { class: 'stand', text: st.status.error || 'Er erscheint, sobald das Handy online ist.' })))));
      return;
    }

    const generated = Date.parse(s.generated_at) || 0;
    const age = now - generated;
    const active = s.active || [];

    const stale = age >= STALE_MS;
    // Antwortet keine Messquelle in Europa mehr, heißt "nichts erkannt" nicht mehr "alles in Ordnung".
    const silent = europeSilent(s);
    const hero = el('div', { class: 'hero ' + (active.length ? 'alarm' : stale ? 'stale' : silent ? 'warn' : 'ok') });
    const title = active.length
      ? (active.length === 1 ? (active[0].kind === 'frequency' ? 'Laufende Störung' : 'Laufender Stromausfall')
        : active.length + ' laufende Ereignisse')
      : stale ? 'Zuletzt keine größeren Stromausfälle'
        : silent ? 'Lage unklar: Messquellen in Europa antworten nicht' : 'Keine größeren Stromausfälle erkannt';
    let stand = 'Stand ' + when(generated, now) + ' · ' + ago(age);
    if (st.status.loading) stand += ' · wird aktualisiert';
    hero.append(el('div', { class: 'hero-head' },
      el('span', { class: 'hero-icon' }, icon(active.length || (silent && !stale) ? 'alert' : 'shield')),
      el('div', null, el('h2', { text: title }), el('div', { class: 'stand', text: stand }))));
    if (active.length) {
      const list = el('ul', { class: 'events' });
      for (const ev of active) {
        const start = Date.parse(ev.started_at) || now;
        let line = 'seit ' + when(start, now) + ', Dauer bisher ' + span(now - start);
        if (ev.affected_people >= 100) line += ' · rund ' + people(ev.affected_people) + ' Betroffene';
        list.append(el('li', null, el('strong', { text: ev.headline }), el('span', { text: line })));
      }
      hero.append(list);
    }
    v.append(hero);

    if (st.status.error) {
      v.append(note('info', 'wifi', st.status.error + ' Gezeigt wird der Stand von ' + when(generated, now) + '.'));
    }
    // Verstummen alle Messquellen in Europa zugleich, kann das selbst das Zeichen eines großen Ausfalls sein.
    // Der Wortlaut folgt dem Lagebericht des Radars, der diesen Hinweis unter "Aktuell" führt.
    if (silent) {
      const quiet = ((s.europe || {}).hosts || []).filter(h => h.reached === false && h.label).map(h => h.label);
      v.append(note('warn', 'alert', [
        el('p', null,
          el('b', { text: 'Seit ' + when(silent, now) + ' antwortet keine der Messquellen in Europa.' }),
          (quiet.length ? ' Still sind: ' + quiet.join(', ') + '.' : '') +
          ' Quellen außerhalb Europas antworten. Das passt zu einem großflächigen Strom- oder Netzausfall in Europa, ' +
          'kann aber auch eine gestörte Verbindung zwischen den USA und Europa sein.')]));
    }
    if (stale) {
      v.append(note('warn', 'alert', [
        el('p', null, el('b', { text: 'Der Lagebericht ist ' + span(age) + ' alt.' }),
          ' Die Überwachung bei GitHub läuft vermutlich nicht, es kämen also auch keine Alarme.'),
        el('div', { class: 'note-actions' },
          el('button', { class: 'btn', onclick: () => N.openUrl(actionsUrl()) }, 'Bei GitHub nachsehen', icon('ext')))]));
    }

    // Letzte Meldung der letzten 24 Stunden, ohne die tägliche Übersicht
    const latest = S.msgs.find(m => m.level !== 'daily' && now - m.time * 1000 < DAY);
    if (latest) {
      v.append(el('button', { class: 'latest lvl-' + latest.level, onclick: () => showTab('meldungen') },
        el('div', { class: 'latest-text' },
          el('b', { text: (latest.symbols ? latest.symbols + ' ' : '') + (latest.title || 'Blackout-Radar') }),
          el('span', { text: 'Letzte Meldung · ' + (LEVEL_NAME[latest.level] || 'Meldung') + ' · ' + when(latest.time * 1000, now) })),
        icon('chev')));
    }

    renderReport(v, S.md);

    v.append(el('div', { class: 'foot' },
      el('div', { text: 'Lagebericht des Blackout-Radars, alle 5 Minuten neu.' }),
      el('button', { onclick: () => N.openUrl(statusUrl()) }, 'Bei GitHub öffnen')));
  }

  /** Aufklappbarer Hinweis, der beim Neuzeichnen offen bleibt, wenn er offen war. */
  function more(key, summary, content) {
    const d = el('details', { class: 'more', open: !!S.open['more:' + key] },
      el('summary', { text: summary }), content);
    d.addEventListener('toggle', () => { S.open['more:' + key] = d.open; });
    return d;
  }

  /** Seit wann keine Messquelle in Europa mehr antwortet (Millisekunden), sonst 0. */
  function europeSilent(s) {
    return s && s.europe && s.europe.silent_since ? (Date.parse(s.europe.silent_since) || 0) : 0;
  }

  function note(kind, ico, content) {
    return el('div', { class: 'note ' + kind }, icon(ico), el('div', null, content));
  }

  /** Zusatz rechts im Kopf eines zugeklappten Abschnitts. */
  function sectionHint(title) {
    const s = S.status || {};
    if (title === 'Unter Beobachtung') {
      const n = (s.watching || []).length;
      return n ? [plural(n, 'Störung', 'Störungen'), ''] : null;
    }
    if (title === 'Kennzahlen') {
      const f = (s.figures || []).find(x => x.label.indexOf('Netzfrequenz') === 0);
      return f ? [f.value.split(' (')[0], ''] : null;
    }
    if (title === 'Statistik') {
      const w = (s.statistics || []).find(x => x.days === 30);
      return w ? [plural(w.outages, 'Ausfall', 'Ausfälle') + ' in 30 Tagen', ''] : null;
    }
    if (title === 'Datenquellen') {
      const src = s.sources || [];
      const bad = src.filter(x => String(x.state || '').indexOf('gestört') === 0).length;
      const ok = src.filter(x => x.ok).length;
      if (bad) return [bad + ' gestört', 'alarm'];
      return src.length && ok === src.length ? ['alle in Ordnung', ''] : null;
    }
    if (title === 'Kürzlich beendet') {
      const n = (s.recently_ended || []).length;
      return n ? [String(n), ''] : null;
    }
    return null;
  }

  /** Setzt status.md in Abschnitte zum Auf- und Zuklappen um. */
  function renderReport(v, md) {
    const lines = md.replace(/\r/g, '').split('\n');
    const silent = europeSilent(S.status);
    let current = '';     // Überschrift des aktuellen Abschnitts, so wie sie im Lagebericht steht
    let body = null;      // Inhalt des aktuellen Abschnitts
    let target = null;    // aktueller Block darin (Ereignis oder Unterabschnitt)
    const into = () => target || body;
    let i = 0;
    while (i < lines.length) {
      const line = lines[i];
      if (/^# /.test(line) || /^Stand: /.test(line)) { i++; continue; }
      if (/^## /.test(line)) {
        let title = line.slice(3).trim();
        current = title;
        // "Aktuell" ohne laufende Ereignisse sagt nur, was oben schon steht.
        if (title === 'Aktuell') {
          if (!(S.status && (S.status.active || []).length)) {
            i++;
            while (i < lines.length && !/^## /.test(lines[i])) i++;
            continue;
          }
          title = 'Laufende Ereignisse';
        }
        body = section(v, title);
        target = null;
        i++;
        continue;
      }
      if (!body) { i++; continue; }
      if (/^### /.test(line)) {
        const text = line.slice(4).trim();
        const kind = text.indexOf('🔴') === 0 ? 'alarm' : text.indexOf('🟢') === 0 ? 'ok' :
          text.indexOf('⚪') === 0 ? 'muted' : 'plain';
        target = el('div', { class: 'event ' + kind });
        target.append(el(kind === 'plain' ? 'h4' : 'h3', { class: kind === 'plain' ? 'sub-title' : null }, inline(text)));
        body.append(target);
        i++;
        continue;
      }
      if (/^\|/.test(line)) {
        const rows = [];
        while (i < lines.length && /^\|/.test(lines[i])) rows.push(cells(lines[i++]));
        into().append(table(rows));
        continue;
      }
      if (/^- /.test(line)) {
        const ul = el('ul');
        while (i < lines.length && /^- /.test(lines[i])) ul.append(el('li', null, inline(lines[i++].slice(2))));
        into().append(ul);
        continue;
      }
      if (!line.trim()) { i++; continue; }
      // Dass die Messquellen in Europa verstummt sind, steht schon oben auf der Seite.
      if (silent && current === 'Aktuell' && line.indexOf('⚠') === 0 && line.indexOf('Messquellen in Europa') > 0) { i++; continue; }
      // Absatz: Zeilen, die mit zwei Leerzeichen enden, behalten ihren Umbruch.
      const p = el('p');
      let br = false;
      let first = true;
      while (i < lines.length && lines[i].trim() && !/^(#{1,3} |\||- )/.test(lines[i])) {
        const raw = lines[i++];
        if (!first) p.append(br ? el('br') : document.createTextNode(' '));
        add(p, inline(raw.trim()));
        br = / {2}$/.test(raw);
        first = false;
      }
      into().append(p);
    }
  }

  function section(v, title) {
    const open = title in S.open ? S.open[title] : !!OPEN_DEFAULT[title];
    const hint = sectionHint(title);
    const d = el('details', { class: 'sec', open: open });
    d.append(el('summary', null,
      el('span', { class: 'title', text: title }),
      hint ? el('span', { class: 'hint' + (hint[1] ? ' ' + hint[1] : ''), text: hint[0] }) : null,
      icon('chev', 'chev')));
    const body = el('div', { class: 'sec-body' });
    d.append(body);
    d.addEventListener('toggle', () => { S.open[title] = d.open; saveOpen(); });
    v.append(d);
    return body;
  }

  function cells(line) {
    return line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(c => c.trim());
  }

  /** Tabellen fürs Handy: zwei Spalten als Liste, drei als Tabelle, mehr als Zeilenblöcke. */
  function table(rows) {
    const head = rows[0] || [];
    const body = rows.slice(1).filter(r => !r.every(c => /^:?-+:?$/.test(c)));
    if (head.length === 2) {
      return el('div', { class: 'kvs' }, body.map(r => el('div', { class: 'kv' },
        el('div', { class: 'k' }, inline(r[0] || '')), el('div', { class: 'v' }, inline(r[1] || '')))));
    }
    if (head.length === 3) {
      return el('table', { class: 'tbl' },
        el('thead', null, el('tr', null, head.map(h => el('th', { text: h })))),
        el('tbody', null, body.map(r => el('tr', null, head.map((_, j) => el('td', null, inline(r[j] || '')))))));
    }
    return el('div', { class: 'rows' }, body.map(r => {
      const meta = el('div', { class: 'rc-meta' });
      let n = 0;
      for (let j = 1; j < head.length; j++) {
        const value = (r[j] || '').trim();
        if (!value || value === '–') continue;
        if (n++) meta.append(el('span', { class: 'sep', text: '·' }));
        const cls = /^in Ordnung/.test(value) ? ' ok' : /^gestört/.test(value) ? ' alarm' : '';
        meta.append(el('span', null, head[j] + ': ', el('span', { class: 'val' + cls }, inline(value))));
      }
      return el('div', { class: 'rc' }, el('div', { class: 'rc-title' }, inline(r[0] || '')), n ? meta : null);
    }));
  }

  /** Fett und Verweise aus Markdown, alles andere bleibt Text. */
  function inline(text) {
    const out = [];
    const re = /\*\*(.+?)\*\*|\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g;
    let last = 0, m;
    while ((m = re.exec(text))) {
      if (m.index > last) out.push(text.slice(last, m.index));
      if (m[1] != null) out.push(el('strong', { text: m[1] }));
      else {
        const url = m[3];
        out.push(el('a', { href: url, onclick: e => { e.preventDefault(); N.openUrl(url); } }, m[2]));
      }
      last = re.lastIndex;
    }
    if (last < text.length) out.push(text.slice(last));
    return out;
  }

  // -------------------------------------------------------------- Meldungen

  function renderMessages(v) {
    v.textContent = '';
    const now = Date.now();
    const st = S.st;
    if (st.conn.state !== 'connected') {
      v.append(note('warn', 'wifi', 'Gerade keine Verbindung zu ntfy. Was in der Zwischenzeit kommt, ' +
        'holt die App nach, sobald die Verbindung wieder steht.' +
        // Der Notweg läuft nur, wenn der Radar seine Meldungen im Lagebericht führt.
        (st.fallback && st.fallback.ready ? ' Bis dahin sieht sie alle paar Minuten im Lagebericht nach (Notweg).' : '')));
    }
    if (!S.msgs.length) {
      v.append(el('div', { class: 'empty' }, icon('bell'),
        el('h3', { text: 'Noch keine Meldungen' }),
        el('p', { text: 'Sobald der Radar etwas meldet, erscheint es hier und als Benachrichtigung. ' +
          'Jeden Morgen um 7 Uhr kommt eine leise Übersicht.' })));
      return;
    }
    let lastDay = '';
    for (const m of S.msgs) {
      const label = dayLabel(m.time * 1000, now);
      if (label !== lastDay) {
        v.append(el('h3', { class: 'day', text: label }));
        lastDay = label;
      }
      v.append(messageCard(m));
    }
    v.append(el('div', { class: 'foot', text: 'Die App behält die letzten 300 Meldungen.' }));
  }

  function messageCard(m) {
    const lines = (m.message || '').split('\n').filter(l => l.trim());
    const long = lines.length > 4 || (m.message || '').length > 380;
    const open = S.expanded.has(m.id);
    const body = el('div', { class: 'msg-body' });
    let ul = null;
    for (const line of (long && !open) ? lines.slice(0, 3) : lines) {
      if (line.indexOf('• ') === 0) {
        if (!ul) { ul = el('ul'); body.append(ul); }
        ul.append(el('li', { text: line.slice(2) }));
        continue;
      }
      ul = null;
      if (line.indexOf('» ') === 0) body.append(el('blockquote', { text: line.slice(2) }));
      else body.append(el('p', { text: line }));
    }
    const actions = el('div', { class: 'msg-actions' });
    if (long) {
      actions.append(el('button', {
        class: 'link-btn', text: open ? 'Weniger anzeigen' : 'Ganze Meldung',
        onclick: () => { open ? S.expanded.delete(m.id) : S.expanded.add(m.id); renderMain(); },
      }));
    }
    if (isStatusLink(m.click)) actions.append(el('button', { class: 'link-btn', text: 'Zum Lagebericht', onclick: () => showTab('lage') }));
    else if (/^https?:\/\//.test(m.click || '')) actions.append(el('button', { class: 'link-btn', text: 'Link öffnen', onclick: () => N.openUrl(m.click) }));
    return el('article', { class: 'msg lvl-' + m.level },
      el('div', { class: 'msg-head' }, el('span', { text: clock(m.time * 1000) }),
        el('span', { class: 'badge', text: LEVEL_NAME[m.level] || 'Meldung' }),
        m.via ? el('span', { class: 'badge way', text: 'Notweg' }) : null),
      el('h4', { text: (m.symbols ? m.symbols + ' ' : '') + (m.title || 'Blackout-Radar') }),
      body,
      // Kam die Meldung nicht über ntfy, steht hier, warum die App sie aus dem Lagebericht geholt hat.
      m.via ? el('p', { class: 'msg-way', text: m.viaText || 'Über den Notweg aus dem Lagebericht.' }) : null,
      actions.childNodes.length ? actions : null);
  }

  // -------------------------------------------------------------------- App

  function renderApp(v) {
    v.textContent = '';
    const st = S.st;
    const c = st.conn;
    const now = Date.now();

    // Verbindung
    const state = {
      connected: ['ok', 'Verbunden', 'Seit ' + when(c.since, now) + '. Meldungen kommen sofort an.'],
      connecting: ['warn', 'Verbindung wird aufgebaut', c.detail || 'Einen Moment …'],
      waiting: ['alarm', 'Keine Verbindung', c.detail],
      stopped: ['alarm', 'Nicht aktiv', 'Der Hintergrunddienst läuft nicht. Android hat ihn beendet oder nicht starten lassen.'],
    }[c.state] || ['alarm', c.state, ''];
    let retry = '';
    if (c.state === 'waiting' && c.nextRetryAt) {
      const s = Math.round((c.nextRetryAt - now) / 1000);
      retry = s > 0 ? ' Nächster Versuch in ' + (s >= 90 ? Math.round(s / 60) + ' min' : s + ' s') + '.' : ' Nächster Versuch läuft.';
    }
    v.append(el('div', { class: 'card' },
      el('div', { class: 'status-line ' + state[0] }, el('span', { class: 'dot' }), el('b', { text: state[1] })),
      el('p', { class: 'small muted', text: (state[2] || '') + retry }),
      el('div', { class: 'kv-plain' }, el('span', { text: 'Server' }), el('span', { text: st.server.replace(/^https?:\/\//, '') })),
      el('div', { class: 'kv-plain' }, el('span', { text: 'Thema' }), el('span', { class: 'mono', text: st.topic })),
      el('div', { class: 'kv-plain' }, el('span', { text: 'Notweg' }), el('span', { text: fallbackState(st.fallback, now) })),
      c.state === 'connected' ? null : el('div', { class: 'stack' },
        el('button', { class: 'btn', onclick: () => { N.reconnect(); toast('Verbindung wird neu aufgebaut …'); } }, icon('refresh'), 'Jetzt neu verbinden')),
      more('notweg', 'Was ist der Notweg?',
        el('ul', null,
          el('li', { text: 'Der Radar führt im Lagebericht bei GitHub, welche Meldungen er verschickt hat. Die App vergleicht das etwa alle 15 Minuten mit dem, was über ntfy angekommen ist. Erreicht sie ntfy nicht, sieht sie etwa alle 5 Minuten nach.' }),
          el('li', { text: 'Fehlt eine Meldung, holt die App sie aus dem Lagebericht und meldet sich selbst, mit derselben Dringlichkeit. In der Liste trägt sie dann das Kennzeichen „Notweg“.' }),
          el('li', { text: 'Das hilft, wenn ntfy ausfällt, wenn der Radar dort nichts loswird oder wenn das Thema an diesem Handy nicht stimmt. Der Notweg ist langsamer als der Push: meist einige Minuten, im ungünstigen Fall rund 20 Minuten. Ohne Internet am Handy hilft auch er nicht.' })))));

    // Erlaubnisse
    const p = st.perms;
    const checks = [
      [p.notifications, 'Benachrichtigungen',
        p.notifications ? 'Erlaubt. Android zeigt Alarme an.' : 'Nicht erlaubt. Ohne diese Erlaubnis zeigt Android keine Alarme an.',
        'Erlauben', () => N.requestNotifications()],
      [p.battery, 'Hintergrund',
        p.battery ? 'Ausnahme von der Akku-Optimierung ist erteilt. Die Verbindung hält auch, wenn das Handy ruht.'
          : 'Die Akku-Optimierung ist aktiv. Android trennt dann die Verbindung, wenn das Handy ruht, und Alarme kommen zu spät.',
        'Erlauben', () => N.requestBattery()],
      [!p.alarmMuted, 'Alarm-Kanal',
        p.alarmMuted ? 'Der Kanal „Alarm“ ist in den Android-Einstellungen ausgeschaltet.' : 'Eingeschaltet.',
        'Öffnen', () => N.openNotificationSettings()],
    ];
    const allOk = checks.every(x => x[0]);
    v.append(el('div', { class: 'card' },
      el('h3', { text: allOk ? 'Alarme kommen sicher an' : 'Damit Alarme sicher ankommen' }),
      checks.map(([ok, title, text, label, act]) => el('div', { class: 'check ' + (ok ? 'ok' : 'bad') },
        el('span', { class: 'mark' }, icon(ok ? 'check' : 'x')),
        el('div', { class: 'check-text' }, el('b', { text: title }), el('span', { text: text })),
        ok ? null : el('button', { class: 'btn primary', text: label, onclick: act }))),
      more('akku', 'Weitere Stromsparfunktionen (Samsung, Xiaomi und andere)',
        el('ul', null,
          el('li', { text: 'Manche Hersteller beenden Apps trotz Ausnahme. Bei Samsung: Einstellungen → Akku → Hintergrundnutzungslimits, die App dort unter „Nie ruhende Apps“ eintragen.' }),
          el('li', null, 'Anleitungen für jeden Hersteller: ',
            el('a', { href: '#', onclick: e => { e.preventDefault(); N.openUrl('https://dontkillmyapp.com/'); } }, 'dontkillmyapp.com')),
          el('li', { text: 'Die Dauermeldung „Blackout-Radar wacht“ verlangt Android für Apps, die im Hintergrund warten. Sie lässt sich in den Benachrichtigungs-Einstellungen beim Kanal „Verbindung“ ausblenden.' })))));

    // Alarm
    const set = st.settings;
    const toggle = (key, title, text) => el('label', { class: 'setting' },
      el('div', { class: 'setting-text' }, el('b', { text: title }), el('span', { text: text })),
      el('span', { class: 'switch' },
        el('input', { type: 'checkbox', checked: !!set[key], onchange: e => N.setSetting(key, e.target.checked) }),
        el('span', { class: 'track' }), el('span', { class: 'thumb' })));
    v.append(el('div', { class: 'card' },
      el('h3', { text: 'Alarm' }),
      toggle('loudAlarm', 'Laut, auch bei Lautlos', 'Ein großer Stromausfall in Österreich läutet über die Wecker-Lautstärke, auch bei „Nicht stören“.'),
      toggle('repeatAlarm', 'Alarmton wiederholen', 'Läutet weiter, bis du die Meldung öffnest oder wegwischst.'),
      toggle('watchMonitor', 'Warnen, wenn der Radar stillsteht', 'Meldung, wenn bei GitHub seit 3 Stunden kein neuer Lagebericht entstanden ist.'),
      el('div', { class: 'stack' },
        el('button', { class: 'btn', onclick: testAlarm }, icon('zap'), 'Probealarm auf diesem Handy'),
        el('button', { class: 'btn', onclick: () => N.openNotificationSettings() }, 'Töne und Kanäle in Android einstellen')),
      more('test', 'Testmeldung über den ganzen Weg',
        el('ul', null,
          el('li', { text: 'Der Probealarm prüft nur Ton und Anzeige auf dem Handy. Für den ganzen Weg vom Radar über ntfy bis hierher: bei GitHub unter Actions → Blackout-Radar → Run workflow die Aktion „test-push“ starten.' }),
          el('li', null, el('a', { href: '#', onclick: e => { e.preventDefault(); N.openUrl(actionsUrl()); } }, 'Actions bei GitHub öffnen'))))));

    // Weitere Handys
    v.append(el('div', { class: 'card' },
      el('h3', { text: 'Weitere Handys' }),
      el('p', { class: 'small muted', text: 'Die App läuft auf beliebig vielen Handys. Die Nachricht enthält den Download und das Thema. ' +
        'Am anderen Handy die App installieren, die ganze Nachricht kopieren und die App öffnen: ' +
        'Sie trägt das Thema selbst ein, dort nur noch auf „Verbinden“ tippen.' }),
      el('div', { class: 'stack' },
        el('button', { class: 'btn', onclick: () => N.share() }, icon('share'), 'App und Thema weitergeben')),
      el('p', { class: 'small muted', text: 'Nur an Leute, denen du vertraust: Wer das Thema kennt, kann mitlesen und selbst Meldungen schicken.' })));

    // Version
    const u = st.update;
    v.append(el('div', { class: 'card' },
      el('h3', { text: 'App' }),
      el('div', { class: 'kv-plain' }, el('span', { text: 'Version' }), el('span', { text: st.version + (st.debug ? ' (Testbau)' : '') })),
      u.available ? note('info', 'info', 'Eine neue Version ist da. Nach dem Herunterladen die Datei antippen und „Aktualisieren“ wählen. Thema und Einstellungen bleiben erhalten.') : null,
      el('div', { class: 'stack' },
        u.available
          ? el('button', { class: 'btn primary', onclick: () => N.downloadUpdate() }, 'Neue Version herunterladen')
          : el('button', { class: 'btn', onclick: () => { N.checkUpdate(); toast('Suche nach neuer Version …'); } }, 'Nach neuer Version suchen'),
        el('button', { class: 'btn', onclick: () => N.openUrl(statusUrl()) }, 'Lagebericht bei GitHub', icon('ext')),
        el('button', { class: 'btn danger', onclick: askReset }, 'Thema ändern'))));

    v.append(el('div', { class: 'foot', text: 'ntfy.sh hebt Meldungen 12 Stunden auf. War das Handy länger ohne Netz, fehlen ältere Meldungen hier. Der Lagebericht zeigt trotzdem den aktuellen Stand.' }));
  }

  /** Stand des Notwegs in wenigen Worten, für die Karte der Verbindung. */
  function fallbackState(f, now) {
    if (!f || !f.checkedAt) return 'noch kein Abgleich';
    if (!f.ready) return 'wartet auf den Radar';
    return 'bereit · Abgleich ' + when(f.checkedAt, now);
  }

  function testAlarm() {
    if (!S.st.perms.notifications) {
      toast('Benachrichtigungen sind nicht erlaubt.');
      N.requestNotifications();
      return;
    }
    N.testAlarm();
    toast('Probealarm geschickt.');
  }

  function askReset() {
    S.modal = {
      title: 'Thema ändern?',
      text: 'Die App vergisst das bisherige Thema und die gespeicherten Meldungen. Danach gibst du das neue Thema ein.',
      ok: 'Thema ändern',
      danger: true,
      onOk: () => {
        S.setup = { busy: false, error: '', result: null, value: '', fromLink: false };
        N.resetTopic();
        refresh();
      },
    };
    renderModal();
  }

  // -------------------------------------------------------------- Einrichten

  function renderSetup() {
    S.shell = null;
    let root = document.getElementById('setup');
    if (!root) {
      document.body.classList.add('setup-mode');
      app.textContent = '';
      root = el('div', { id: 'setup', class: 'setup' });
      app.append(root);
      window.scrollTo(0, 0);
    }
    const r = S.setup.result;
    if (r) { renderResult(root, r); return; }
    let input = document.getElementById('topic');
    if (!input) {
      root.textContent = '';
      input = el('input', {
        id: 'topic', class: 'topic', type: 'text', autocomplete: 'off', autocapitalize: 'none',
        autocorrect: 'off', spellcheck: 'false', enterkeyhint: 'go', placeholder: 'z. B. blackout-radar-…',
        'aria-label': 'Thema', onkeydown: e => { if (e.key === 'Enter') connect(); },
        oninput: () => { S.setup.error = ''; S.setup.fromCopy = false; S.setup.value = input.value; updateSetup(); },
      });
      input.value = S.setup.value;
      root.append(
        el('div', { class: 'brand-big', html: LOGO }, el('b', { text: 'Blackout-Radar' })),
        el('h2', { text: 'Alarme auf dieses Handy holen' }),
        el('p', { class: 'lead', text: 'Trag das ntfy-Thema ein, an das der Radar seine Meldungen schickt. ' +
          'Es ist derselbe Name, den du am PC in ntfy verwendest.' }),
        el('label', { class: 'field', for: 'topic', text: 'Thema' }),
        input,
        el('div', { class: 'row' },
          el('button', { id: 'paste', class: 'btn', onclick: () => N.paste() }, icon('paste'), 'Einfügen'),
          el('button', { id: 'connect', class: 'btn primary', onclick: connect }, 'Verbinden')),
        el('div', { id: 'setup-msg', class: 'msg-line' }),
        note('info', 'shield', 'Das Thema wirkt wie ein Passwort: Wer es kennt, kann mitlesen. ' +
          'Die App speichert es nur auf diesem Handy und schickt es nur an ntfy.sh.'),
        more('wo', 'Wo finde ich das Thema?',
          el('ul', null,
            el('li', { text: 'Hat dir jemand die App weitergegeben? Dann die ganze Nachricht kopieren und wieder hierher wechseln: ' +
              'Die App erkennt sie und trägt das Thema selbst ein. Klappt das nicht, tippe auf „Einfügen“.' }),
            el('li', { text: 'Am PC auf ntfy.sh/app steht es links in der Liste der abonnierten Themen.' }),
            el('li', { text: 'Am einfachsten schickst du es dir selbst per E-Mail oder Messenger, kopierst es hier am Handy und tippst auf „Einfügen“.' }),
            el('li', { text: 'Es genügt der Name. Eine ganze Adresse wie https://ntfy.sh/… geht auch.' }),
            el('li', { text: 'Solange diese Seite offen ist, sieht die App in die Zwischenablage. Sie übernimmt daraus nur ' +
              'eine weitergegebene Nachricht des Blackout-Radars, alles andere lässt sie liegen.' }))));
    }
    updateSetup();
  }

  function updateSetup() {
    const input = document.getElementById('topic');
    const btn = document.getElementById('connect');
    const msg = document.getElementById('setup-msg');
    if (!input || !btn || !msg) return;
    const busy = S.setup.busy;
    input.disabled = busy;
    btn.disabled = busy || !input.value.trim();
    btn.textContent = busy ? 'Verbinde …' : 'Verbinden';
    document.getElementById('paste').disabled = busy;
    msg.className = 'msg-line ' + (S.setup.error ? 'error' : 'info');
    msg.textContent = S.setup.error ||
      (busy ? 'Frage bei ntfy.sh nach, was auf diesem Thema zuletzt kam …' :
        S.setup.fromLink ? 'Aus dem Link übernommen. Tippe auf „Verbinden“.' :
          S.setup.fromCopy ? 'Aus der kopierten Nachricht übernommen. Tippe auf „Verbinden“.' : '');
  }

  function connect() {
    const input = document.getElementById('topic');
    const value = (input ? input.value : S.setup.value).trim();
    if (!value || S.setup.busy) return;
    S.setup.value = value;
    S.setup.busy = true;
    S.setup.error = '';
    if (input) input.blur();
    updateSetup();
    N.setTopic(value);
  }

  function renderResult(root, r) {
    root.textContent = '';
    const now = Date.now();
    let kind, title, text;
    if (r.offline) {
      kind = 'info';
      title = 'Gespeichert';
      text = 'ntfy.sh war gerade nicht erreichbar. Die App verbindet sich von selbst, sobald das Netz da ist, ' +
        'und holt dann die Meldungen der letzten 12 Stunden nach.';
    } else if (r.count > 0) {
      const newest = S.msgs[0];
      kind = 'ok';
      title = 'Verbunden';
      text = plural(r.count, 'Meldung', 'Meldungen') + ' der letzten 12 Stunden gefunden' +
        (newest ? ', die neueste: „' + newest.title + '“ (' + when(newest.time * 1000, now) + ').' : '.') +
        ' Ab jetzt kommt jede neue Meldung sofort.';
    } else {
      kind = 'warn';
      title = 'Verbunden, aber noch keine Meldung';
      text = 'Auf diesem Thema kam in den letzten 12 Stunden nichts an. Wenn du am PC heute Meldungen bekommen hast, ' +
        'stimmt der Name nicht ganz. Ist das Thema neu, passt alles.';
    }
    root.append(el('div', { class: 'result ' + kind },
      el('div', { class: 'brand-big', html: LOGO }, el('b', { text: 'Blackout-Radar' })),
      el('span', { class: 'big-icon' }, icon(kind === 'warn' ? 'alert' : kind === 'ok' ? 'check' : 'wifi')),
      el('h2', { text: title }),
      el('p', { class: 'lead', text: text }),
      S.st.perms.notifications && S.st.perms.battery ? null :
        el('p', { class: 'small muted', text: 'Gleich fragt Android nach zwei Erlaubnissen: Benachrichtigungen zeigen und im Hintergrund laufen. ' +
          'Bitte beide erlauben, sonst kommen Alarme nicht oder zu spät.' }),
      el('div', { class: 'stack' },
        el('button', { class: 'btn primary block', onclick: finishSetup }, kind === 'warn' ? 'Passt so, weiter' : 'Weiter'),
        kind === 'warn' ? el('button', { class: 'btn block', onclick: () => {
          S.setup = { busy: false, error: '', result: null, value: S.setup.value, fromLink: false };
          N.resetTopic();
          refresh();
        } }, 'Anderes Thema eingeben') : null)));
  }

  function finishSetup() {
    S.setup = { busy: false, error: '', result: null, value: '', fromLink: false };
    S.tab = 'lage';
    render();
    window.scrollTo(0, 0);
  }

  // ------------------------------------------------------------------ Dialog

  function renderModal() {
    const w = document.getElementById('modal');
    w.textContent = '';
    const m = S.modal;
    w.classList.toggle('show', !!m);
    if (!m) return;
    const box = el('div', { class: 'modal', role: 'dialog', 'aria-modal': 'true' },
      el('h3', { text: m.title }),
      el('p', { text: m.text }),
      el('div', { class: 'row end' },
        el('button', { class: 'btn', text: m.cancel || 'Abbrechen', onclick: closeModal }),
        el('button', {
          class: 'btn ' + (m.danger ? 'danger' : 'primary'), text: m.ok,
          onclick: () => { const f = m.onOk; closeModal(); f(); },
        })));
    box.addEventListener('click', e => e.stopPropagation());
    w.onclick = closeModal;
    w.append(box);
  }

  function closeModal() {
    S.modal = null;
    renderModal();
  }

  // ------------------------------------------------- Aufrufe aus der App

  window.BR = {
    changed: refresh,
    showTab(name) {
      if (['lage', 'meldungen', 'app'].indexOf(name) < 0) return;
      // Ein Tipp auf eine Benachrichtigung beendet auch die Erfolgsseite nach dem Einrichten.
      if (S.setup.result && S.st && S.st.hasTopic) { S.setup.result = null; S.tab = name; render(); return; }
      showTab(name);
    },
    back() {
      if (S.modal) { closeModal(); return true; }
      if (S.shell && S.tab !== 'lage') { showTab('lage'); return true; }
      return false;
    },
    onPaste(text) {
      const input = document.getElementById('topic');
      const value = String(text || '').trim();
      if (!input) return;
      if (!value) { S.setup.error = 'Die Zwischenablage ist leer.'; updateSetup(); return; }
      input.value = value;
      S.setup.value = value;
      S.setup.error = '';
      S.setup.fromLink = false;
      S.setup.fromCopy = false;
      updateSetup();
    },
    /**
     * Auf der Einrichtungsseite lag die weitergegebene Nachricht eines anderen Handys in der Zwischenablage.
     * Die App trägt das Thema ein. Verbinden tippt der Mensch selbst, und was er schon eingetragen hat, bleibt.
     */
    onCopied(topic) {
      const input = document.getElementById('topic');
      if (!input || S.setup.busy || S.setup.result || input.value.trim()) return;
      input.value = topic;
      S.setup.value = topic;
      S.setup.error = '';
      S.setup.fromLink = false;
      S.setup.fromCopy = true;
      updateSetup();
    },
    onSetup(result) {
      S.setup.busy = false;
      if (result.ok) S.setup.result = result;
      else S.setup.error = result.error || 'Das hat nicht geklappt.';
      refresh();
    },
    onUpdateChecked(ok) {
      refresh();
      if (!ok) toast('GitHub ist gerade nicht erreichbar.');
      else toast(S.st.update.available ? 'Eine neue Version ist da.' : 'Die App ist auf dem neuesten Stand.');
    },
    /** Ein Link der Form blackoutradar://abo/<thema> wurde geöffnet. */
    offerTopic(topic, masked, same, fresh) {
      if (same) { toast('Dieses Thema ist schon eingerichtet.'); return; }
      if (fresh) {
        // Noch nichts eingerichtet: gleich verbinden, so wie nach einem Tipp auf "Verbinden".
        S.setup = { busy: false, error: '', result: null, value: topic, fromLink: true };
        const input = document.getElementById('topic');
        if (input) input.value = topic;
        render();
        connect();
        return;
      }
      S.modal = {
        title: 'Neues Thema übernehmen?',
        text: 'Der Link enthält ein anderes Thema (' + masked + '). Bisher: ' + S.st.topic + '. ' +
          'Die App vergisst dann das bisherige Thema und die gespeicherten Meldungen.',
        ok: 'Übernehmen',
        onOk: () => {
          S.setup = { busy: true, error: '', result: null, value: topic, fromLink: true };
          render();
          N.setTopic(topic);
        },
      };
      renderModal();
    },
  };

  // Zeiten wie "vor 3 min" und der Countdown bis zum nächsten Versuch bleiben aktuell.
  setInterval(() => { if (S.st && S.shell && S.tab !== 'meldungen') renderMain(); }, 20000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });

  refresh();
})();
