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
    page: 'welcome',   // ohne Ziel: 'welcome' (Alarm einschalten) oder 'private' (eigenen Radar verbinden)
    legal: null,       // offene Unterseite: 'impressum' oder 'datenschutz'
    backArmed: false,  // was die App über die Zurück-Geste zuletzt erfahren hat
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
    back: '<svg viewBox="0 0 24 24"><path d="M19 12H5"/><path d="m12 19-7-7 7-7"/></svg>',
    firma: '<svg viewBox="0 0 24 24"><rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/></svg>',
    globe: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><path d="M2 12h20"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10Z"/></svg>',
    call: '<svg viewBox="0 0 24 24"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92Z"/></svg>',
    mail: '<svg viewBox="0 0 24 24"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="m22 7-10 6L2 7"/></svg>',
    clock: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>',
  };
  // Das Zeichen der App, als Kachel mit runden Ecken. Es ist vom Logo des Betreibers abgeleitet: die zweigeteilte
  // Pille mit dem Verlauf, an der Stelle des Spalts steht der Blitz. LOGO für die Kopfzeile (ohne Schrift, die wäre
  // dort nicht lesbar), LOGO_BIG wie das App-Symbol am Startbildschirm (res/drawable/ic_launcher_foreground.xml,
  // die Buchstaben sind Pfade).
  const LOGO = '<svg class="logo" viewBox="16 16 76 76" aria-hidden="true"><rect x="16" y="16" width="76" height="76" rx="19" fill="#F5F9FF"/><defs><linearGradient id="logo-verlauf-s" gradientUnits="userSpaceOnUse" x1="0" y1="36" x2="0" y2="72"><stop offset="0" stop-color="#00D7FF"/><stop offset="1" stop-color="#001EAB"/></linearGradient></defs>' +
    '<path d="M40,36 L54.15,36 Q54.75,36 54.45,36.52 L43.24,56.31 Q42.94,56.84 43.54,56.84 L51.7,56.84 Q52.3,56.84 52.2,57.43 L49.8,71.41 Q49.7,72 49.1,72 L40,72 A18,18 0 0 1 40,36 Z M68,72 L52.46,72 Q51.86,72 52.18,71.49 L64.74,51.67 Q65.06,51.16 64.46,51.16 L55.88,51.16 Q55.28,51.16 55.34,50.57 L56.84,36.6 Q56.9,36 57.5,36 L68,36 A18,18 0 0 1 68,72 Z" fill="url(#logo-verlauf-s)"/>' +
    '</svg>';
  const LOGO_BIG = '<svg class="logo" viewBox="18 18 72 72" aria-hidden="true"><rect x="18" y="18" width="72" height="72" rx="18" fill="#F5F9FF"/><defs><linearGradient id="logo-verlauf" gradientUnits="userSpaceOnUse" x1="0" y1="45.17" x2="0" y2="62.83"><stop offset="0" stop-color="#00D7FF"/><stop offset="1" stop-color="#001EAB"/></linearGradient></defs>' +
    '<path d="M30.83,45.17 L60.75,45.17 Q61.1,45.17 60.93,45.47 L55.48,55.09 Q55.3,55.39 55.65,55.39 L59.54,55.39 Q59.89,55.39 59.84,55.74 L58.68,62.49 Q58.62,62.83 58.27,62.83 L30.83,62.83 A8.83,8.83 0 0 1 30.83,45.17 Z M77.17,62.83 L60.03,62.83 Q59.68,62.83 59.87,62.54 L65.97,52.9 Q66.16,52.61 65.81,52.61 L61.71,52.61 Q61.36,52.61 61.39,52.26 L62.12,45.51 Q62.15,45.17 62.5,45.17 L77.17,45.17 A8.83,8.83 0 0 1 77.17,62.83 Z" fill="url(#logo-verlauf)"/>' +
    '<path d="M30.32,56.83 L29.69,58.81 C29.63,58.98 29.47,59.1 29.29,59.1 L27.3,59.1 C27.16,59.1 27.04,59.03 26.96,58.92 C26.88,58.81 26.86,58.67 26.91,58.54 L30.2,49.05 C30.26,48.89 30.42,48.77 30.59,48.77 L32.93,48.77 C33.11,48.77 33.26,48.89 33.32,49.05 L36.62,58.54 C36.66,58.67 36.64,58.81 36.56,58.92 C36.48,59.03 36.36,59.1 36.22,59.1 L34.07,59.1 C33.89,59.1 33.73,58.98 33.68,58.81 L33.05,56.83 Z M31.02,54.47 L32.37,54.47 L31.7,52.35 Z" fill="#FFFFFF" fill-rule="evenodd"/>' +
    '<path d="M39.75,56 C39.72,55.79 39.55,55.63 39.33,55.63 L37.41,55.63 C37.3,55.63 37.19,55.67 37.11,55.76 C37.04,55.84 36.99,55.95 37,56.06 C37.02,56.57 37.14,57.03 37.35,57.43 C37.57,57.84 37.86,58.19 38.24,58.48 C38.61,58.76 39.05,58.97 39.56,59.12 C40.06,59.27 40.61,59.34 41.22,59.34 C41.86,59.34 42.43,59.26 42.94,59.11 C43.47,58.95 43.92,58.72 44.29,58.42 C44.67,58.12 44.97,57.74 45.17,57.3 C45.38,56.87 45.48,56.38 45.48,55.84 C45.48,55.42 45.42,55.04 45.3,54.71 C45.17,54.36 44.97,54.06 44.71,53.8 C44.45,53.54 44.13,53.33 43.74,53.15 C43.37,52.98 42.93,52.84 42.42,52.74 C42.42,52.74 41.28,52.49 41.28,52.49 C40.79,52.39 40.45,52.27 40.24,52.12 C40.11,52.02 40.04,51.9 40.04,51.74 C40.04,51.64 40.06,51.54 40.11,51.45 C40.16,51.36 40.23,51.28 40.32,51.22 C40.43,51.14 40.56,51.08 40.71,51.04 C40.88,51 41.06,50.97 41.27,50.97 C41.47,50.97 41.66,51 41.83,51.05 C41.98,51.09 42.12,51.15 42.23,51.24 C42.34,51.31 42.43,51.41 42.49,51.52 C42.56,51.62 42.6,51.73 42.61,51.86 C42.64,52.07 42.81,52.22 43.02,52.22 L44.89,52.22 C45,52.22 45.11,52.18 45.19,52.1 C45.27,52.02 45.31,51.91 45.31,51.8 C45.29,51.31 45.18,50.86 44.96,50.46 C44.75,50.06 44.46,49.71 44.1,49.42 C43.74,49.14 43.32,48.92 42.83,48.76 C42.35,48.61 41.83,48.53 41.26,48.53 C40.67,48.53 40.13,48.61 39.64,48.76 C39.14,48.92 38.71,49.15 38.36,49.44 C38,49.74 37.71,50.1 37.51,50.52 C37.32,50.94 37.22,51.4 37.22,51.91 C37.22,52.58 37.38,53.15 37.7,53.62 C38.16,54.31 38.96,54.79 40.12,55.03 C40.12,55.03 41.36,55.29 41.36,55.29 C41.36,55.29 41.36,55.29 41.36,55.29 C41.63,55.35 41.86,55.41 42.05,55.48 C42.21,55.54 42.35,55.61 42.46,55.69 C42.53,55.74 42.58,55.8 42.62,55.87 C42.65,55.93 42.67,56.01 42.67,56.09 C42.67,56.19 42.64,56.29 42.59,56.37 C42.53,56.47 42.45,56.55 42.35,56.63 C42.23,56.71 42.09,56.77 41.92,56.82 C41.74,56.87 41.54,56.89 41.32,56.89 C41.08,56.89 40.86,56.87 40.65,56.81 C40.47,56.77 40.3,56.7 40.17,56.61 C40.04,56.54 39.94,56.44 39.87,56.33 C39.8,56.23 39.76,56.12 39.75,56 Z" fill="#FFFFFF" fill-rule="evenodd"/>' +
    '<path d="M49.34,56.57 L53.22,56.57 C53.45,56.57 53.64,56.75 53.64,56.98 L53.64,58.68 C53.64,58.91 53.45,59.1 53.22,59.1 L46.94,59.1 C46.71,59.1 46.52,58.91 46.52,58.68 L46.52,49.19 C46.52,48.96 46.71,48.77 46.94,48.77 L53.22,48.77 C53.45,48.77 53.64,48.96 53.64,49.19 L53.64,50.89 C53.64,51.12 53.45,51.3 53.22,51.3 L49.34,51.3 L49.34,52.69 L52.98,52.69 C53.21,52.69 53.4,52.87 53.4,53.1 L53.4,54.68 C53.4,54.91 53.21,55.09 52.98,55.09 L49.34,55.09 Z" fill="#FFFFFF" fill-rule="evenodd"/>' +
    '<path d="M67.82,58.68 C67.82,58.91 68.01,59.1 68.24,59.1 L70.22,59.1 C70.45,59.1 70.64,58.91 70.64,58.68 L70.64,49.19 C70.64,48.96 70.45,48.77 70.22,48.77 L68.24,48.77 C68.01,48.77 67.82,48.96 67.82,49.19 Z" fill="#FFFFFF" fill-rule="evenodd"/>' +
    '<path d="M74.41,51.3 L71.98,51.3 C71.75,51.3 71.56,51.12 71.56,50.89 L71.56,49.19 C71.56,48.96 71.75,48.77 71.98,48.77 L79.66,48.77 C79.89,48.77 80.07,48.96 80.07,49.19 L80.07,50.89 C80.07,51.12 79.89,51.3 79.66,51.3 L77.23,51.3 L77.23,58.68 C77.23,58.91 77.04,59.1 76.81,59.1 L74.83,59.1 C74.6,59.1 74.41,58.91 74.41,58.68 Z" fill="#FFFFFF" fill-rule="evenodd"/>' +
    '</svg>';

  const LEVEL_NAME = { alarm: 'Alarm', warn: 'Warnung', ok: 'Entwarnung', info: 'Meldung', daily: 'Übersicht' };
  const TABS = ['lage', 'meldungen', 'app', 'firma'];
  const LEGAL_TITLE = { impressum: 'Impressum', datenschutz: 'Datenschutz' };
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
    renderLegal();
    renderModal();
  }

  /** Der Name des Anbieters, so wie ihn die App führt. */
  const brandName = () => (S.st && S.st.brand && S.st.brand.name) || '';

  /**
   * Sagt der App, ob die Zurück-Geste gerade in der Seite etwas zu tun hat: einen Dialog oder eine Unterseite
   * schließen, zur Willkommensseite oder zum Tab "Lage" zurück. Sonst schließt die Geste die App. Ab Android 13
   * muss die App das vor der Geste wissen, nicht erst in ihrem Augenblick.
   */
  function armBack() {
    const armed = !!(S.modal || S.legal || (S.shell ? S.tab !== 'lage' : canLeavePrivate()));
    if (armed === S.backArmed) return;
    S.backArmed = armed;
    N.backArmed(armed);
  }

  /** Auf der Seite "Eigenen Radar verbinden", solange dort nichts läuft: Zurück führt zur Willkommensseite. */
  function canLeavePrivate() {
    return S.page === 'private' && !S.setup.busy && !S.setup.result && !(S.st && S.st.hasTopic);
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

    for (const name of TABS) {
      sh.tabs[name].setAttribute('aria-selected', String(S.tab === name));
      sh.views[name].hidden = S.tab !== name;
    }
    if (S.tab === 'lage') renderLage(sh.views.lage);
    else if (S.tab === 'meldungen') renderMessages(sh.views.meldungen);
    else if (S.tab === 'firma') renderFirma(sh.views.firma);
    else renderApp(sh.views.app);
    armBack();
  }

  function buildShell() {
    document.body.classList.remove('setup-mode');
    app.textContent = '';
    const sh = { views: {}, tabs: {} };
    sh.pill = el('button', { class: 'pill', onclick: () => showTab('app'), 'aria-label': 'Verbindung' });
    sh.refresh = el('button', { class: 'icon-btn', 'aria-label': 'Aktualisieren', onclick: onRefresh }, icon('refresh'));
    const top = el('header', { class: 'top' },
      el('div', { class: 'brand', html: LOGO },
        el('div', { class: 'brand-text' }, el('h1', { text: 'Blackout-Radar' }),
          brandName() ? el('span', { class: 'by', text: 'von ' + brandName() }) : null)),
      sh.pill, sh.refresh);
    const main = el('main');
    for (const name of TABS) {
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
    tab('firma', 'Über uns', 'firma');
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
          st.public ? ' Der Radar läuft vermutlich gerade nicht, es kämen also auch keine Alarme.'
            : ' Die Überwachung bei GitHub läuft vermutlich nicht, es kämen also auch keine Alarme.'),
        // Nachsehen und neu starten kann nur, wer den Radar betreibt.
        st.public ? null : el('div', { class: 'note-actions' },
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
      el('button', { onclick: () => N.openUrl(statusUrl()) }, 'Bei GitHub öffnen'),
      byline()));
  }

  /** Wer hinter dem Dienst steht, als unaufdringliche Zeile. Ein Tipp führt zu "Über uns". */
  function byline() {
    if (!brandName()) return null;
    return el('button', { class: 'byline', onclick: () => showTab('firma') },
      el('span', { text: 'Ein Dienst von ' }), el('b', { text: brandName() }));
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
    const re = /\*\*(.+?)\*\*|\[([^\]]+)\]\((https?:\/\/[^\s)]+|mailto:[^\s)]+)\)/g;
    let last = 0, m;
    while ((m = re.exec(text))) {
      if (m.index > last) out.push(text.slice(last, m.index));
      if (m[1] != null) out.push(el('strong', { text: m[1] }));
      else {
        const url = m[3];
        // Die einzige E-Mail-Adresse in den Texten der App ist die des Anbieters: Dafür öffnet sich das E-Mail-Programm.
        const open = url.startsWith('mailto:') ? () => N.mailCompany('') : () => N.openUrl(url);
        out.push(el('a', { href: url, onclick: e => { e.preventDefault(); open(); } }, m[2]));
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
      st.public ? el('div', { class: 'kv-plain' }, el('span', { text: 'Alarm' }), el('span', { text: 'Öffentlicher Alarm' })) : [
        el('div', { class: 'kv-plain' }, el('span', { text: 'Server' }), el('span', { text: st.server.replace(/^https?:\/\//, '') })),
        el('div', { class: 'kv-plain' }, el('span', { text: 'Thema' }), el('span', { class: 'mono', text: st.topic }))],
      st.public ? el('div', { class: 'kv-plain' }, el('span', { text: 'Schutz' }), el('span', { text: 'Unterschrift des Radars geprüft' })) : null,
      el('div', { class: 'kv-plain' }, el('span', { text: 'Notweg' }), el('span', { text: fallbackState(st.fallback, now) })),
      c.state === 'connected' ? null : el('div', { class: 'stack' },
        el('button', { class: 'btn', onclick: () => { N.reconnect(); toast('Verbindung wird neu aufgebaut …'); } }, icon('refresh'), 'Jetzt neu verbinden')),
      more('notweg', 'Was ist der Notweg?',
        el('ul', null,
          el('li', { text: 'Der Radar führt im Lagebericht bei GitHub, welche Meldungen er verschickt hat. Die App vergleicht das etwa alle 15 Minuten mit dem, was über ntfy angekommen ist. Erreicht sie ntfy nicht, sieht sie etwa alle 5 Minuten nach.' }),
          el('li', { text: 'Fehlt eine Meldung, holt die App sie aus dem Lagebericht und meldet sich selbst, mit derselben Dringlichkeit. In der Liste trägt sie dann das Kennzeichen „Notweg“.' }),
          el('li', { text: 'Das hilft, wenn ntfy ausfällt' + (st.public ? ' oder wenn der Radar dort nichts loswird.'
            : ', wenn der Radar dort nichts loswird oder wenn das Thema an diesem Handy nicht stimmt.') +
            ' Der Notweg ist langsamer als der Push: meist einige Minuten, im ungünstigen Fall rund 20 Minuten. Ohne Internet am Handy hilft auch er nicht.' }))),
      st.public ? more('schutz', 'Kann jemand einen falschen Alarm schicken?',
        el('ul', null,
          el('li', { text: 'Nein. Jede Meldung des Radars trägt eine Unterschrift. Die App prüft sie und verwirft alles andere still: Es erscheint weder als Benachrichtigung noch in der Liste.' }),
          el('li', { text: 'Auch Dringlichkeit und Zeit einer Meldung stammen aus den unterschriebenen Angaben. Eine alte echte Meldung, die jemand noch einmal einspielt, läutet nicht ein zweites Mal.' }))) : null));

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
      toggle('watchMonitor', 'Warnen, wenn der Radar stillsteht', st.public
        ? 'Meldung, wenn der Radar seit 3 Stunden keinen neuen Lagebericht geliefert hat.'
        : 'Meldung, wenn bei GitHub seit 3 Stunden kein neuer Lagebericht entstanden ist.'),
      el('div', { class: 'stack' },
        el('button', { class: 'btn', onclick: testAlarm }, icon('zap'), 'Probealarm auf diesem Handy'),
        el('button', { class: 'btn', onclick: () => N.openNotificationSettings() }, 'Töne und Kanäle in Android einstellen')),
      st.public ? null : more('test', 'Testmeldung über den ganzen Weg',
        el('ul', null,
          el('li', { text: 'Der Probealarm prüft nur Ton und Anzeige auf dem Handy. Für den ganzen Weg vom Radar über ntfy bis hierher: bei GitHub unter Actions → Blackout-Radar → Run workflow die Aktion „test-push“ starten.' }),
          el('li', null, el('a', { href: '#', onclick: e => { e.preventDefault(); N.openUrl(actionsUrl()); } }, 'Actions bei GitHub öffnen'))))));

    // Weitere Handys. Zwei Wege: die App als Datei, die das Thema schon enthält, oder eine Nachricht mit Download und Thema.
    const byMessage = 'Am anderen Handy die App installieren, die ganze Nachricht kopieren, die App öffnen und auf ' +
      '„Eigenen Radar verbinden“ tippen: Sie trägt das Thema selbst ein, dort nur noch auf „Verbinden“ tippen.';
    if (st.public) v.append(recommendCard());
    else v.append(el('div', { class: 'card' },
      el('h3', { text: 'Weitere Handys' }),
      el('p', { class: 'small muted', text: 'Die App läuft auf beliebig vielen Handys. ' + (st.appFile
        ? 'Am einfachsten gibst du sie als Datei weiter, die dein Thema schon enthält. Am anderen Handy die Datei antippen, ' +
          'installieren und die App einmal öffnen: Sie richtet sich selbst ein, eingeben muss dort niemand etwas.'
        : 'Die Nachricht enthält den Download und das Thema. ' + byMessage) }),
      el('div', { class: 'stack' },
        st.appFile ? el('button', { class: 'btn primary', onclick: () => N.shareApp() }, icon('share'), 'App samt Thema weitergeben') : null,
        st.appFile ? el('button', { class: 'btn', onclick: () => N.share() }, 'Nur Nachricht mit Link weitergeben')
          : el('button', { class: 'btn', onclick: () => N.share() }, icon('share'), 'App und Thema weitergeben')),
      el('p', { class: 'small muted', text: 'Nur an Leute, denen du vertraust' + (st.appFile ? ', und nirgends öffentlich hochladen: Die Datei enthält das Thema. ' : ': ') +
        'Wer das Thema kennt, kann mitlesen und selbst Meldungen schicken.' }),
      st.appFile ? more('nachricht', 'Wann die Nachricht mit Link?',
        el('ul', null,
          el('li', { text: 'Manche Dienste nehmen keine App-Dateien an, zum Beispiel Gmail. Dann hilft die Nachricht: Sie enthält den Download und das Thema.' }),
          el('li', { text: byMessage }),
          el('li', { text: 'Die Datei enthält die Fassung der App, die auf diesem Handy läuft. Gibt es eine neuere, bietet die App am anderen Handy das Update von selbst an.' }))) : null));

    // Version
    const u = st.update;
    v.append(el('div', { class: 'card' },
      el('h3', { text: 'App' }),
      el('div', { class: 'kv-plain' }, el('span', { text: 'Version' }), el('span', { text: st.version + (st.debug ? ' (Testbau)' : '') })),
      st.play ? el('p', { class: 'small muted', text: 'Neue Versionen kommen über den Play Store.' }) : null,
      u.available ? note('info', 'info', 'Eine neue Version ist da. Nach dem Herunterladen die Datei antippen und „Aktualisieren“ wählen. ' +
        (st.public ? 'Die Einstellungen bleiben erhalten.' : 'Thema und Einstellungen bleiben erhalten.')) : null,
      el('div', { class: 'stack' },
        st.play ? null : u.available
          ? el('button', { class: 'btn primary', onclick: () => N.downloadUpdate() }, 'Neue Version herunterladen')
          : el('button', { class: 'btn', onclick: () => { N.checkUpdate(); toast('Suche nach neuer Version …'); } }, 'Nach neuer Version suchen'),
        el('button', { class: 'btn', onclick: () => N.openUrl(statusUrl()) }, 'Lagebericht bei GitHub', icon('ext')),
        st.public ? el('button', { class: 'btn', onclick: askOwn }, 'Eigenen Radar verbinden') : null,
        el('button', { class: 'btn danger', onclick: st.public ? askOff : askReset }, st.public ? 'Alarm ausschalten' : 'Thema ändern')),
      legalLinks()));

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

  /** Vergisst das Ziel und die Meldungen. Danach steht die Seite [page] offen: 'welcome' oder 'private'. */
  function forget(page) {
    S.setup = { busy: false, error: '', result: null, value: '', fromLink: false };
    S.page = page;
    N.resetTopic();
    refresh();
  }

  function askReset() {
    S.modal = {
      title: 'Thema ändern?',
      text: 'Die App vergisst das bisherige Thema und die gespeicherten Meldungen. Danach gibst du das neue Thema ein.',
      ok: 'Thema ändern',
      danger: true,
      onOk: () => forget('private'),
    };
    renderModal();
  }

  function askOff() {
    S.modal = {
      title: 'Alarm ausschalten?',
      text: 'Die App meldet sich dann nicht mehr und vergisst die gespeicherten Meldungen. Einschalten kannst du den Alarm jederzeit wieder.',
      ok: 'Ausschalten',
      danger: true,
      onOk: () => forget('welcome'),
    };
    renderModal();
  }

  /** Vom öffentlichen Alarm zum eigenen Radar: für Leute, die selbst einen Blackout-Radar betreiben. */
  function askOwn() {
    S.modal = {
      title: 'Eigenen Radar verbinden?',
      text: 'Das ist für Leute, die selbst einen Blackout-Radar betreiben. Der öffentliche Alarm wird ausgeschaltet, ' +
        'danach trägst du das Thema deines Radars ein.',
      ok: 'Weiter',
      onOk: () => forget('private'),
    };
    renderModal();
  }

  /** Die App weiterempfehlen. Ein Thema gibt es beim öffentlichen Alarm nicht weiterzugeben. */
  function recommendCard() {
    return el('div', { class: 'card' },
      el('h3', { text: 'App empfehlen' }),
      el('p', { class: 'small muted', text: 'Ein Alarm hilft am meisten, wenn ihn viele bekommen: Familie, Nachbarn, Kollegen. ' +
        'Die App ist kostenlos und braucht keine Anmeldung.' }),
      el('div', { class: 'stack' },
        el('button', { id: 'recommend', class: 'btn primary', onclick: () => N.recommend() }, icon('share'), 'App empfehlen')));
  }

  /** Verweise auf Datenschutz und Impressum. Beide Texte liegen in der App und öffnen sich ohne Netz. */
  function legalLinks() {
    return el('div', { class: 'legal-links' },
      el('button', { class: 'link-btn', onclick: () => openLegal('datenschutz') }, 'Datenschutz'),
      el('button', { class: 'link-btn', onclick: () => openLegal('impressum') }, 'Impressum'));
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
    // Läuft gerade ein Einrichten, bleibt die Seite stehen, von der aus es gestartet wurde.
    const page = r ? 'result' : (S.setup.busy ? (S.setup.public ? 'welcome' : 'private') : S.page);
    if (root.getAttribute('data-page') !== page) {
      root.textContent = '';
      root.setAttribute('data-page', page);
      window.scrollTo(0, 0);
      // In die Zwischenablage sieht die App nur, solange die Seite zum Verbinden des eigenen Radars offen ist.
      N.setupOpen(page === 'private');
    }
    if (r) renderResult(root, r);
    else if (page === 'private') renderPrivate(root);
    else renderWelcome(root);
    armBack();
  }

  /** Die erste Seite: den öffentlichen Alarm einschalten. Ein Tipp, einzugeben ist nichts. */
  function renderWelcome(root) {
    if (!document.getElementById('enable')) {
      root.textContent = '';
      const point = (ico, title, text) => el('li', null, icon(ico), el('div', null, el('b', { text: title }), el('span', { text: text })));
      root.append(
        el('div', { class: 'brand-big', html: LOGO_BIG },
          el('div', null, el('b', { text: 'Blackout-Radar' }),
            brandName() ? el('span', { class: 'by', text: 'von ' + brandName() }) : null)),
        el('h2', { text: 'Alarm bei großem Stromausfall' }),
        el('p', { class: 'lead', text: 'Fällt in Österreich großflächig der Strom aus, meldet sich dein Handy. ' +
          'Kostenlos und ohne Anmeldung.' }),
        el('ul', { class: 'points' },
          point('zap', 'Laut, auch bei Lautlos', 'Der Alarm läutet über die Wecker-Lautstärke, auch nachts.'),
          point('lage', 'Lagebericht in der App', 'Wo der Strom fehlt, seit wann und wie viele betroffen sind.'),
          point('shield', 'Ohne Konto, ohne Standort', 'Die App fragt nichts ab und verfolgt nichts.')),
        el('button', { id: 'enable', class: 'btn primary block big', onclick: enablePublic }, 'Alarm einschalten'),
        el('div', { id: 'setup-msg', class: 'msg-line' }),
        el('button', { id: 'own', class: 'link-btn block', onclick: openPrivate }, 'Eigenen Radar verbinden'),
        el('p', { class: 'fine', text: 'Der Blackout-Radar ist kein amtlicher Warndienst. Er wertet öffentliche Messdaten aus und kann ' +
          'sich irren oder ausfallen. Für Alarme braucht das Handy Internet.' }),
        legalLinks());
    }
    updateWelcome();
  }

  function updateWelcome() {
    const btn = document.getElementById('enable');
    const msg = document.getElementById('setup-msg');
    if (!btn || !msg) return;
    const busy = S.setup.busy;
    btn.disabled = busy;
    btn.textContent = busy ? 'Schalte ein …' : 'Alarm einschalten';
    document.getElementById('own').disabled = busy;
    msg.className = 'msg-line ' + (S.setup.error ? 'error' : 'info');
    msg.textContent = S.setup.error || '';
  }

  function enablePublic() {
    if (S.setup.busy) return;
    S.setup = { busy: true, error: '', result: null, value: '', fromLink: false, public: true };
    updateWelcome();
    N.enablePublic();
  }

  function openPrivate() {
    if (S.setup.busy) return;
    S.setup = { busy: false, error: '', result: null, value: '', fromLink: false };
    S.page = 'private';
    render();
  }

  function closePrivate() {
    if (!canLeavePrivate()) return;
    S.setup = { busy: false, error: '', result: null, value: '', fromLink: false };
    S.page = 'welcome';
    render();
  }

  /** Für Leute mit eigenem Radar: das Thema eintragen, an das ihr Radar seine Meldungen schickt. */
  function renderPrivate(root) {
    let input = document.getElementById('topic');
    if (!input) {
      root.textContent = '';
      input = el('input', {
        id: 'topic', class: 'topic', type: 'text', autocomplete: 'off', autocapitalize: 'none',
        autocorrect: 'off', spellcheck: 'false', enterkeyhint: 'go', placeholder: 'z. B. blackout-radar-…',
        'aria-label': 'Thema', onkeydown: e => { if (e.key === 'Enter') connect(); },
        oninput: () => { S.setup.error = ''; S.setup.fromCopy = false; S.setup.fromFile = false; S.setup.value = input.value; updateSetup(); },
      });
      input.value = S.setup.value;
      // add() lässt aus, was fehlt (den Knopf zur Installationsdatei). root.append() schriebe dafür das Wort "null" in die Seite.
      add(root, [
        el('button', { id: 'back', class: 'link-btn back', onclick: closePrivate }, icon('back'), 'Zurück'),
        el('div', { class: 'brand-big', html: LOGO_BIG }, el('b', { text: 'Blackout-Radar' })),
        el('h2', { text: 'Alarme auf dieses Handy holen' }),
        el('p', { class: 'lead', text: 'Trag das ntfy-Thema ein, an das der Radar seine Meldungen schickt. ' +
          'Es ist derselbe Name, den du am PC in ntfy verwendest.' }),
        el('label', { class: 'field', for: 'topic', text: 'Thema' }),
        input,
        el('div', { class: 'row' },
          el('button', { id: 'paste', class: 'btn', onclick: () => N.paste() }, icon('paste'), 'Einfügen'),
          el('button', { id: 'connect', class: 'btn primary', onclick: connect }, 'Verbinden')),
        // Die App kam als Datei samt Thema von einem anderen Handy: Nach "Thema ändern" führt hier ein Tipp zurück.
        S.st.builtIn ? el('button', { id: 'builtin', class: 'btn block', onclick: () => N.useBuiltIn() }, 'Thema aus der Installationsdatei verwenden') : null,
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
              'eine weitergegebene Nachricht des Blackout-Radars, alles andere lässt sie liegen.' })))]);
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
    document.getElementById('back').disabled = busy;
    const builtIn = document.getElementById('builtin');
    if (builtIn) builtIn.disabled = busy;
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
    if (r.public) {
      // Der öffentliche Alarm: Hier gibt es kein Thema, das falsch sein könnte.
      kind = r.offline ? 'info' : 'ok';
      title = 'Alarm ist eingeschaltet';
      const newest = S.msgs[0];
      text = r.offline
        ? 'Der Server war gerade nicht erreichbar. Die App verbindet sich von selbst, sobald das Netz da ist.'
        : 'Ab jetzt meldet sich dein Handy, sobald der Radar einen großen Stromausfall erkennt.' +
          (r.count > 0 && newest ? ' Die letzte Meldung: „' + newest.title + '“ (' + when(newest.time * 1000, now) + ').' : '') +
          ' Jeden Morgen um 7 Uhr kommt eine leise Übersicht.';
    } else if (r.offline) {
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
    } else if (S.setup.fromFile) {
      // Das Thema hat niemand getippt, es stammt von einem Handy, auf dem es läuft. Ein Tippfehler scheidet aus.
      kind = 'ok';
      title = 'Verbunden';
      text = 'In den letzten 12 Stunden kam auf diesem Thema nichts an. Das ist normal, solange der Radar nichts zu melden hat. ' +
        'Ab jetzt kommt jede neue Meldung sofort.';
    } else {
      kind = 'warn';
      title = 'Verbunden, aber noch keine Meldung';
      text = 'Auf diesem Thema kam in den letzten 12 Stunden nichts an. Wenn du am PC heute Meldungen bekommen hast, ' +
        'stimmt der Name nicht ganz. Ist das Thema neu, passt alles.';
    }
    root.append(el('div', { class: 'result ' + kind },
      el('div', { class: 'brand-big', html: LOGO_BIG }, el('b', { text: 'Blackout-Radar' })),
      el('span', { class: 'big-icon' }, icon(kind === 'warn' ? 'alert' : kind === 'ok' ? 'check' : 'wifi')),
      el('h2', { text: title }),
      el('p', { class: 'lead', text: text }),
      S.setup.fromFile ? el('p', { class: 'small muted', text: 'Das Thema stand schon in der Installationsdatei. Eingeben musstest du nichts.' }) : null,
      // Wer den Dienst bereitstellt, in dem Augenblick, in dem er zum ersten Mal etwas leistet.
      r.public && brandName() ? el('p', { class: 'small muted', text: 'Diesen Dienst stellt dir ' + brandName() + ' kostenlos bereit.' }) : null,
      S.st.perms.notifications && S.st.perms.battery ? null :
        el('p', { class: 'small muted', text: 'Gleich fragt Android nach zwei Erlaubnissen: Benachrichtigungen zeigen und im Hintergrund laufen. ' +
          'Bitte beide erlauben, sonst kommen Alarme nicht oder zu spät.' }),
      el('div', { class: 'stack' },
        el('button', { class: 'btn primary block', onclick: finishSetup }, kind === 'warn' ? 'Passt so, weiter' : 'Weiter'),
        kind === 'warn' ? el('button', { class: 'btn block', onclick: () => {
          S.setup = { busy: false, error: '', result: null, value: S.setup.value, fromLink: false };
          S.page = 'private';
          N.resetTopic();
          refresh();
        } }, 'Anderes Thema eingeben') : null)));
  }

  function finishSetup() {
    S.setup = { busy: false, error: '', result: null, value: '', fromLink: false };
    S.page = 'welcome';
    S.tab = 'lage';
    render();
    window.scrollTo(0, 0);
  }

  // ---------------------------------------------------------------- Über uns

  /** Wer die App anbietet. Das steht in einem eigenen Bereich, nie zwischen Lage und Meldungen. */
  function renderFirma(v) {
    if (v.firstChild) return;  // der Inhalt ändert sich nicht, solange die App läuft
    const b = S.st.brand || {};
    const service = text => el('li', { text: text });
    v.append(
      el('div', { class: 'firma-hero' },
        el('div', { class: 'firma-logo', html: LOGO_BIG }),
        el('div', null,
          el('h2', { text: b.name || '' }),
          el('p', { class: 'claim', text: 'Wir vernetzen Sie!' }),
          el('p', { class: 'sub', text: 'IT aus Tragwein im Mühlviertel, seit 2014.' }),
          el('button', { id: 'firma-web-top', class: 'btn light', onclick: () => N.openUrl(b.web) }, (b.web || '').replace(/^https?:\/\//, ''), icon('ext')))),

      el('div', { class: 'card' },
        el('h3', { text: 'Warum es diese App gibt' }),
        el('p', { class: 'small', text: 'Fällt der Strom aus, fällt zuerst die Technik aus: Internet, Telefon, Kameras, Heizungssteuerung. ' +
          'Mit genau dieser Technik arbeiten wir jeden Tag. Den Blackout-Radar haben wir für den eigenen Betrieb gebaut ' +
          'und stellen ihn allen kostenlos zur Verfügung.' })),

      // Das eine Angebot, das zum Anlass der App passt. Sachlich, ohne Versprechen zur Dauer.
      el('div', { class: 'card' },
        el('h3', { text: 'Damit Ihre Technik weiterläuft' }),
        el('p', { class: 'small', text: 'Eine USV (unterbrechungsfreie Stromversorgung) versorgt Ihre wichtigste Technik aus dem Akku weiter, ' +
          'wenn der Strom ausfällt. So bleiben Sie erreichbar und behalten den Überblick.' }),
        el('ul', { class: 'services' },
          service('Internet'),
          service('Netzwerk'),
          service('WLAN'),
          service('Kameras'),
          service('Telefonanlage')),
        el('p', { class: 'small muted', text: 'Wie lange die Technik durchhält, hängt von der Auslegung ab. Wir beraten Sie, was bei Ihnen sinnvoll ist.' }),
        el('div', { class: 'stack' },
          el('button', { id: 'firma-usv', class: 'btn primary', onclick: () => b.mail ? N.mailCompany('usv') : N.openUrl(b.contact) },
            icon('zap'), 'USV-Beratung anfragen'))),

      el('div', { class: 'card' },
        el('h3', { text: 'Was wir machen' }),
        el('ul', { class: 'services' },
          service('Internetanbindungen'),
          service('Netzwerke und Infrastruktur'),
          service('WLAN und Hotspots'),
          service('Telefonanlagen'),
          service('Überwachungssysteme'),
          service('Smart Home'),
          service('Service und IT-Handel')),
        el('p', { class: 'small muted', text: 'Ihr Partner in Sachen Netzwerk, Telefon, Überwachung, Smart Home und Internet. Wir beraten Sie gerne!' })),

      el('div', { class: 'card' },
        el('h3', { text: 'Kontakt' }),
        el('div', { class: 'stack first' },
          el('button', { id: 'firma-web', class: 'btn primary', onclick: () => N.openUrl(b.web) }, icon('globe'), 'Zur Homepage'),
          el('button', { id: 'firma-call', class: 'btn', onclick: () => N.callCompany() }, icon('call'), 'Anrufen: ' + b.phone),
          b.mail ? el('button', { id: 'firma-mail', class: 'btn', onclick: () => N.mailCompany('') }, icon('mail'), 'E-Mail schreiben')
            : el('button', { id: 'firma-contact', class: 'btn', onclick: () => N.openUrl(b.contact) }, icon('mail'), 'Nachricht schreiben')),
        el('p', { class: 'small muted hours' }, icon('clock', 'sm'),
          el('span', { text: 'Bürozeiten: Montag bis Donnerstag 9 bis 16 Uhr, Freitag 9 bis 12 Uhr.' }))),

      recommendCard(),

      el('div', { class: 'card' },
        el('h3', { text: 'Gut zu wissen' }),
        el('ul', { class: 'plain' },
          el('li', { text: 'Der Blackout-Radar ist kein amtlicher Warndienst und ersetzt keine Warnung der Behörden. Er wertet öffentliche ' +
            'Messdaten aus und kann sich irren oder ausfallen.' }),
          el('li', { text: 'Alarme brauchen Internet am Handy. Bei einem langen Stromausfall fällt auch das Mobilfunknetz nach einiger Zeit aus.' }),
          el('li', null, 'Der Quelltext von Radar und App ist offen: ',
            el('a', { href: '#', onclick: e => { e.preventDefault(); N.openUrl('https://github.com/' + S.st.repo); } }, 'bei GitHub ansehen'), '.')),
        legalLinks()));
  }

  // ------------------------------------------------- Impressum und Datenschutz

  function openLegal(name) {
    S.legal = name;
    renderLegal();
  }

  function closeLegal() {
    S.legal = null;
    renderLegal();
  }

  /** Zeigt Impressum oder Datenschutzerklärung über der Seite. Der Text liegt in der App, es braucht kein Netz. */
  function renderLegal() {
    const w = document.getElementById('legal');
    const name = S.legal;
    if (!name) {
      if (w.hasAttribute('data-name')) {
        w.textContent = '';
        w.removeAttribute('data-name');
        w.classList.remove('show');
        document.body.classList.remove('legal-open');
      }
      armBack();
      return;
    }
    if (w.getAttribute('data-name') !== name) {
      w.textContent = '';
      w.setAttribute('data-name', name);
      const body = el('div', { class: 'legal-body' });
      const text = N.legal(name);
      if (text) renderDoc(body, text);
      else body.append(el('p', { text: 'Der Text ließ sich nicht laden. Er steht auch im Netz.' }));
      const url = (S.st.legal || {})[name === 'impressum' ? 'imprint' : 'privacy'];
      add(w, [
        el('header', { class: 'top' },
          el('button', { class: 'icon-btn', 'aria-label': 'Zurück', onclick: closeLegal }, icon('back')),
          el('h1', { text: LEGAL_TITLE[name] || '' })),
        body,
        url ? el('div', { class: 'foot' },
          el('div', { text: 'Derselbe Text steht öffentlich im Netz.' }),
          el('button', { onclick: () => N.openUrl(url) }, 'Im Browser öffnen')) : null]);
      w.classList.add('show');
      document.body.classList.add('legal-open');
      w.scrollTop = 0;
    }
    armBack();
  }

  /** Setzt einen Text in Markdown um: Überschriften, Absätze, Listen, Fett und Verweise. Mehr brauchen die Rechtstexte nicht. */
  function renderDoc(root, md) {
    const lines = md.replace(/\r/g, '').split('\n');
    let i = 0;
    while (i < lines.length) {
      const line = lines[i];
      const head = /^(#{1,3}) +(.*)$/.exec(line);
      if (head) {
        root.append(el('h' + (head[1].length + 1), null, inline(head[2].trim())));
        i++;
        continue;
      }
      if (/^- /.test(line)) {
        const ul = el('ul');
        while (i < lines.length && /^- /.test(lines[i])) ul.append(el('li', null, inline(lines[i++].slice(2))));
        root.append(ul);
        continue;
      }
      if (!line.trim()) { i++; continue; }
      // Absatz: Zeilen, die mit zwei Leerzeichen enden, behalten ihren Umbruch (Anschriften).
      const para = el('p');
      let br = false;
      let first = true;
      while (i < lines.length && lines[i].trim() && !/^(#{1,3} |- )/.test(lines[i])) {
        const raw = lines[i++];
        if (!first) para.append(br ? el('br') : document.createTextNode(' '));
        add(para, inline(raw.trim()));
        br = / {2}$/.test(raw);
        first = false;
      }
      root.append(para);
    }
  }

  // ------------------------------------------------------------------ Dialog

  function renderModal() {
    const w = document.getElementById('modal');
    w.textContent = '';
    const m = S.modal;
    w.classList.toggle('show', !!m);
    if (!m) { armBack(); return; }
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
    armBack();
  }

  function closeModal() {
    S.modal = null;
    renderModal();
  }

  // ------------------------------------------------- Aufrufe aus der App

  window.BR = {
    changed: refresh,
    showTab(name) {
      if (TABS.indexOf(name) < 0) return;
      S.legal = null;
      // Ein Tipp auf eine Benachrichtigung beendet auch die Erfolgsseite nach dem Einrichten.
      if (S.setup.result && S.st && S.st.hasTopic) { S.setup.result = null; S.tab = name; render(); return; }
      renderLegal();
      showTab(name);
    },
    back() {
      if (S.modal) { closeModal(); return true; }
      if (S.legal) { closeLegal(); return true; }
      if (S.shell && S.tab !== 'lage') { showTab('lage'); return true; }
      if (!S.shell && canLeavePrivate()) { closePrivate(); return true; }
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
      S.setup.fromFile = false;
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
      S.setup.fromFile = false;
      S.setup.fromCopy = true;
      updateSetup();
    },
    onSetup(result) {
      S.setup.busy = false;
      if (result.ok) S.setup.result = result;
      else S.setup.error = result.error || 'Das hat nicht geklappt.';
      refresh();
      // Die Seite, von der aus eingerichtet wurde, zeigt die Fehlermeldung selbst.
      updateWelcome();
    },
    onUpdateChecked(ok) {
      refresh();
      if (!ok) toast('GitHub ist gerade nicht erreichbar.');
      else toast(S.st.update.available ? 'Eine neue Version ist da.' : 'Die App ist auf dem neuesten Stand.');
    },
    /**
     * Ein Thema kommt von außen: aus einem geöffneten Link der Form blackoutradar://abo/<thema>, oder (fromFile)
     * aus der Installationsdatei, mit der ein anderes Handy die App samt Thema weitergegeben hat.
     */
    offerTopic(topic, masked, same, fresh, fromFile) {
      if (same) { toast('Dieses Thema ist schon eingerichtet.'); return; }
      if (fresh) {
        // Die Datei meldet sich von selbst. Läuft schon ein Einrichten, hat das den Vorrang.
        if (fromFile && (S.setup.busy || S.setup.result)) return;
        // Noch nichts eingerichtet: gleich verbinden, so wie nach einem Tipp auf "Verbinden".
        S.setup = { busy: false, error: '', result: null, value: topic, fromLink: !fromFile, fromFile: !!fromFile };
        S.page = 'private';
        S.legal = null;
        const input = document.getElementById('topic');
        if (input) input.value = topic;
        render();
        connect();
        return;
      }
      S.modal = {
        title: 'Neues Thema übernehmen?',
        text: (fromFile ? 'Die Installationsdatei bringt ein anderes Thema mit (' : 'Der Link enthält ein anderes Thema (') + masked + '). ' +
          (S.st.public ? 'Bisher ist der öffentliche Alarm eingeschaltet. Die App schaltet ihn dann aus und vergisst die gespeicherten Meldungen.'
            : 'Bisher: ' + S.st.topic + '. Die App vergisst dann das bisherige Thema und die gespeicherten Meldungen.'),
        ok: 'Übernehmen',
        onOk: () => {
          S.setup = { busy: true, error: '', result: null, value: topic, fromLink: !fromFile, fromFile: !!fromFile };
          S.page = 'private';
          S.legal = null;
          render();
          N.setTopic(topic);
        },
      };
      renderModal();
    },
    /** Die Installationsdatei mit dem Thema ließ sich nicht schreiben oder keine App nimmt sie an. */
    onShareFailed() {
      toast('Die Datei ließ sich nicht weitergeben. Nimm die Nachricht mit Link.');
    },
  };

  // Zeiten wie "vor 3 min" und der Countdown bis zum nächsten Versuch bleiben aktuell.
  setInterval(() => { if (S.st && S.shell && S.tab !== 'meldungen' && S.tab !== 'firma') renderMain(); }, 20000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });

  refresh();
})();
