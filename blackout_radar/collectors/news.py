"""Medienberichte über Stromausfälle (Google News als RSS-Suche, dazu Feeds großer Medien aus Übersee).

Vier Wege:
  Vorrang    feste Suchen für Vorrang-Gebiete (Oberösterreich, Österreich). Für Oberösterreich
             zählt schon ein Bericht.
  Welt       Suche nach großen Ausfällen in mehreren Sprachen. Das Gebiet wird aus der
             Schlagzeile gelesen. Es zählt erst, wenn mehrere Medien berichten.
  Nachweis   gezielte Suche zu Gebieten, in denen ein Messsignal anschlägt.
  Feeds      die Welt-Nachrichten großer Medien in Amerika, Asien und Australien, reihum
             abgefragt. Sie hängen weder an Google noch an Europa: Fällt dort großflächig der
             Strom aus, berichten sie weiter. Gezählt wird wie bei der Welt-Suche.

Aus den Berichten je Gebiet entsteht ein Medien-Signal (media_outage) mit geschätzter
Größe: Zahlen aus der Schlagzeile ("20.000 Haushalte"), "landesweit" oder die Breite der
Berichterstattung.

Was nichts auslöst:
  - Vorsorge, Übungen, Warnungen, geplante Abschaltungen, Romane und Filme.
  - Im Deutschen das Wort "Blackout" allein. Es steht dort fast immer für Vorsorge und
    Szenarien, ein echter Ausfall heißt "Stromausfall" oder "ohne Strom".
  - Aufarbeitung und Wiederherstellung ("Nach Stromausfall: ...", "Strom wieder da").
  - Berichte über Ursache und Ermittlungen, wenn die Lage im Gebiet schon bekannt ist. Am Tag
    des Ausfalls steht die Ursache dagegen oft schon in der ersten Schlagzeile ("Stromstörung
    in Linz: Polizei ermittelt"), dann zählt der Bericht als Erstbericht.
  - Ein einzelner Bericht, dessen Schlagzeile keinen Ort nennt. Er wurde nur von der Suche
    einem Gebiet zugeordnet, deshalb braucht es ein zweites Medium.
  - Bei der Österreich-Suche jede Schlagzeile, die keinen Ort in Österreich nennt. Die Suche
    findet auch Auslandsberichte österreichischer Medien ("Stürme an US-Ostküste: Fast eine
    Million ohne Strom").
  - Folgen, Ursache und Kritik ("... nach Stromausfall", "Staatsschutz ermittelt"), wenn es
    im Gebiet in den letzten Tagen schon Berichte über einen Stromausfall gab.

Orte in Österreich: Nennt eine Schlagzeile aus einer Österreich-Suche keinen bekannten Ort, entscheidet
das amtliche Gemeindeverzeichnis (gazetteer.austria). "Stromausfall in Tragwein" zählt damit für
Oberösterreich, "Stromausfälle in Lieboch" (Steiermark) für Österreich und nicht für Oberösterreich.

Die RSS-Suche von Google News ist für Feed-Leser gedacht und nicht garantiert. Dieses
Programm fragt sie sparsam ab (wenige Suchen je Lauf).
"""
from __future__ import annotations

import html
import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

from .. import areas, gazetteer, http
from ..http import HttpError
from ..model import UTC, Signal, fmt_people, iso, parse_ts

log = logging.getLogger("blackout_radar")

SOURCE = "news"   # einzelner Bericht
MEDIA = "media"   # verdichtetes Signal je Gebiet
GOOGLE_NEWS = "https://news.google.com/rss/search"
PAUSE_SECONDS = 1.0  # Abstand zwischen zwei Suchen
FEED_MAX_BYTES = 3_000_000  # größere Antworten werden nicht gelesen
GOOGLE, FEEDS = "Google News", "Feeds aus Übersee"

POWER_WORDS = re.compile(
    r"blackout|black-out|power outages?|power cuts?|power failure|without power|without electricity|"
    r"(?:loses?|lost) power|grid collaps|grid fail|plunged into darkness|"
    r"stromausf[aä]ll|stromstörung|stromunterbrechung|ohne strom|strom weg|kein strom|"
    r"apag[oó]n|apagones|cortes? de luz|cortes? de energ|sin luz|sin energ[ií]a|sin electricidad|"
    r"colapso (?:del sistema )?el[eé]ctrico|apag[aã]o|apagões|sem energia|sem luz|"
    r"panne de courant|panne d.électricité|panne géante|coupure de courant|coupure d.électricité|sans électricité|"
    r"senza corrente|senza elettricità|stroomstoring|stroomuitval|strømbrud|strömavbrott|awaria prądu|"
    r"výpadek proudu|áramszünet|pană de curent|elektrik kesintisi|отключени|блэкаут|відключенн|"
    r"انقطاع الكهرباء|停电|停電|정전|mất điện|pemadaman listrik", re.IGNORECASE)

# Deutsche Wörter für einen tatsächlichen Ausfall ("Blackout" allein zählt im Deutschen nicht)
GERMAN_OUTAGE = re.compile(
    r"stromausf[aä]ll|stromstörung|stromunterbrechung|ohne strom|strom weg|kein strom", re.IGNORECASE)

# Zählt nie: Vorsorge und Übungen, Warnungen, geplante Abschaltungen, Romane und Filme,
# "Blackout" im übertragenen Sinn
EXCLUDE = re.compile(
    r"vorsorge|übung|ratgeber|was tun|jahrestag|planspiel|simulation|simulier|checkliste|podcast|quiz|testalarm|"
    r"probealarm|vortrag|infoabend|wie wahrscheinlich|unwahrscheinlich|notfallplan|vorbereit|"
    r"bereite[nt]? sich|\brüste[nt]\b|gerüstet|wappne|vorr[aä]t|sollten sie|\btipps?\b|\bstudie|umfrage|"
    r"\bwürden?\b|\bwäre\b|szenario|ernstfall|\bprobt\b|geprobt|\büb(?:t|en)\b|geübt|angst vor|sorgen? vor|"
    r"für den fall|im falle?\b|was passiert|wenn der strom|leuchtt[uü]rm|zivilschutzverband|zivilschutztag|"
    r"workshop|schulung|versicherung|kampagne|broschüre|gefahr eines|"
    r"blackout[“”\"']?-(?!nacht|chaos|drama|schock|hit|stricken|struck)|"
    r"preparedness|\bdrill|anniversary|how to prepare|simulacro|aniversario|"
    r"\b(?:threatens?|could|might|warns?|warning|risk of|at risk|fears?|looms?|braces?|plans? for|"
    r"droht|drohen|könnte|warnt|warnung|riesgo|podría|advierte|amenaza|peligro|risque|pourrait|rischio)\b|"
    r"geplant|angekündigt|wartungsarbeit|scheduled|planned|programad|preventivo|mantenimiento|horarios|"
    r"colonias|maintenance|rolling blackouts?|load.?shedding|"
    r"thriller|\broman\b|elsberg|spielfilm|kinofilm|hörspiel|\bkrimi\b|\bdoku\b|dokumentation|tv-tipp|buchtipp|"
    r"streaming|\bnovel\b|\bmovie\b|\bfilm\b|book review|"
    r"(?:media|news|internet|communications?|information|tv|broadcast|radio|digital|sports?) blackout|"
    r"blackout (?:tuesday|wednesday|friday|challenge|dates?|curtains?|blinds?|restrictions?|rules?|policy)|"
    r"\b(?:nfl|nba|mlb|nhl)\b|"
    r"apagón (?:informativo|digital|analógico|mediático|de internet)|"
    r"microsoft|cloud|\baws\b|azure|playstation|xbox|whatsapp|instagram|facebook|netflix|youtube|"
    r"airspace|skies|internetausfall|mobilfunk", re.IGNORECASE)

# Aufarbeitung und Wiederherstellung: zählt als Beleg, löst aber nie etwas aus
FOLLOWUP = re.compile(
    r"^nach\b.*(?:stromausfall|stromstörung|blackout)|bilanz|konsequenz|entschädigung|prozess|urteil|"
    r"gericht|rückblick|analyse|kommentar|interview|\bschutz|lehren|aufarbeitung|"
    r"tag danach|nachwehen|chronologie|protokoll einer|so erlebte|bisher bekannt|was wir wissen|"
    r"wieder (?:da|hergestellt|versorgt|am netz)|behoben|entwarnung|"
    r"kritik|kritisier|vorw[uü]rf|fahrlässig|rücktritt|debatte|landtag|sondersitzung|\b(?:övp|spö|fpö|neos|kpö)\b|"
    r"nachspiel|schadeners|schadensers|millionenschaden|schadenssumme|schadenshöhe|schaden in (?:millionen|höhe)|"
    r"hintergr[uü]nd|faktencheck|fragen und antworten|wie sicher|wie es dazu|"
    r"^after\b.*(?:blackout|outage)|restor|back online|power returns|power is back|"
    r"report finds|lessons|year after|explained|what we know|"
    r"compensation|lawsuit|\bcourt\b|aftermath|recover|death toll|timeline|"
    r"restablec|restitu|vuelve la luz|regresa la luz|recupera|"
    r"tras el (?:último |gran |masivo )?apagón|después del apagón|donde comenzó|exigirá|pronunciamiento|"
    r"restabelec|após o apagão|depois do apagão|"
    r"rétabli|après la panne|ripristin|dopo il (?:maxi[- ])?blackout", re.IGNORECASE)

# Ursache und Ermittlungen: am Tag des Ausfalls oft schon in der ersten Schlagzeile, Tage später
# Aufarbeitung. Ob so ein Bericht etwas auslöst, hängt davon ab, ob die Lage schon bekannt ist.
CAUSE = re.compile(
    r"ermittel|ermittlung|staatsschutz|sabotage|sachbeschädigung|vorsatz|anschlag|rätsel|"
    r"polizei|kripo|kriminalamt|verfassungsschutz|täter|flüchtig|fahndung|"
    r"ursache(?! (?:noch |weiter |bislang |bisher |derzeit |zunächst )?(?:unklar|unbekannt|offen))|"
    r"festgenommen|verdächtig|investigat|inquiry|\bprobe\b|what caused|caused by|blam(?:es|ed|ing)|"
    r"investig|hipótesis|causas? del|responsables|atribu[iy]e?|causas? do|enquête|indagin", re.IGNORECASE)

# Folgen: "Verkehrschaos nach Stromausfall" steht am Tag des Ausfalls in der Zeitung, "Kritik nach
# Stromausfall" in den Tagen danach. Zählt deshalb wie ein Bericht über die Ursache.
AFTER = re.compile(
    r"\bnach (?:dem |einem |der |einer |den )?(?:[\w-]+ ){0,2}(?:stromausf[aä]ll|stromstörung|blackout)|"
    r"\b(?:after|following) (?:the |a |an )?(?:[\w-]+ ){0,2}(?:blackout|power outage|power cut|outage)",
    re.IGNORECASE)

NATIONWIDE = re.compile(
    r"nationwide|countrywide|country-wide|entire country|whole country|across the country|"
    r"national (?:electric |electrical |power |electricity )?grid collaps|landesweit|bundesweit|im ganzen land|"
    r"todo el país|a nivel nacional|apagón nacional|tout le pays|em todo o país|apagão nacional|"
    r"in tutto il paese", re.IGNORECASE)
# "Alles ohne Strom", ohne das Land zu nennen. In kleinen Staaten ist damit das Land gemeint ("apagón general
# en Cuba"), in großen meist eine Region, Stadt oder Insel ("apagão geral afeta Manaus", "island-wide outage
# on Oahu", "Ganz Berlin ohne Strom"). Dort zählt es nur als großer Ausfall.
WHOLE_AREA = re.compile(
    r"entire island|whole island|island-?wide|grid collapse|total blackout|complete blackout|"
    r"completely without power|ganz \w+ ohne strom|apagón (?:general|total)|colapso (?:total|del sistema)|"
    r"apagão (?:geral|total)", re.IGNORECASE)
WHOLE_AREA_MAX_POPULATION = 30_000_000
# Ausfall in ganz Europa. Die Schlagzeile muss den Ausfall selbst so nennen ("europaweiter Stromausfall",
# "ganz Europa ohne Strom"), nicht nur seine Folgen ("Stromausfall: Zugverkehr europaweit gestört").
# "Across Europe" fehlt mit Absicht: So heißt es auch bei einem Sturm über mehreren Ländern.
_OUT_DE = r"(?:stromausf[aä]lle?s?|stromstörung(?:en)?|blackouts?)"
_DARK_DE = r"(?:ohne strom|kein strom|stromlos|im dunkeln|dunkel|finster)"
_OUT_EN = r"(?:blackouts?|power outages?|outages?|power cuts?|power failures?|grid collapse|grid failure)"
_DARK_EN = r"(?:without power|without electricity|in(?:to)? (?:the )?dark(?:ness)?|loses? power|lost power)"
_ALL_EN = r"(?:all of europe|the whole of europe|whole of europe|the entire continent|entire continent)"
EUROPE_WIDE = re.compile(
    rf"europa-?weite[rnms]? (?:[\w-]+ )?{_OUT_DE}|europa-?weit (?:{_DARK_DE}|{_OUT_DE})|"
    rf"{_OUT_DE} (?:in|legt|trifft|erfasst|lähmt) ganz europa|ganz europa (?:[\w-]+ ){{0,2}}{_DARK_DE}|"
    rf"(?:europe|continent)-wide (?:[\w-]+ )?{_OUT_EN}|"
    rf"{_OUT_EN} (?:[\w-]+ ){{0,2}}{_ALL_EN}|{_ALL_EN} (?:[\w-]+ ){{0,2}}{_DARK_EN}|"
    r"apagón (?:[\w-]+ )?en toda europa|toda europa (?:[\w-]+ )?(?:sin luz|sin electricidad|a oscuras)|"
    r"(?:panne|coupure)[^,.;:!?]{0,40}dans toute l.europe|toute l.europe (?:[\w-]+ ){0,2}(?:sans électricité|dans le noir)|"
    r"(?:blackout|black-out) in tutta (?:l.)?europa|tutta (?:l.)?europa (?:[\w-]+ )?(?:senza corrente|senza elettricità|al buio)",
    re.IGNORECASE)
# Eigene Namen großer Staaten, soweit sie vom deutschen und englischen abweichen
_OWN_NAMES = {"ES": "España", "MX": "México", "BR": "Brasil", "PE": "Perú", "IT": "Italia", "TR": "Türkiye"}

# Wörter, die einen Ausfall als groß beschreiben, ohne eine Zahl zu nennen
BIG_WORDS = re.compile(
    r"massive|major|widespread|huge|vast|large-scale|sweeping|großflächig|flächendeckend|massiv|riesig|"
    r"masivo|generalizado|gran apagón|mega ?apagón|géante|généralisée|grande apagão|maxi[- ]?blackout|"
    r"großer stromausfall|großen stromausfall", re.IGNORECASE)

_HOUSEHOLDS = (r"haushalte|households|homes|customers|kunden|anlagen|clientes|usuarios|hogares|abonnés|"
               r"foyers|utenti|famiglie")
_PERSONS = r"menschen|people|personen|einwohner|residents|personas|habitantes|pessoas|personnes|persone"
_MONEY = r"(?!\s*(?:de\s+)?(?:euros?|dollars?|dólares|usd|eur|€|\$|pesos|reais|pounds?|franken))"
_MILLION = re.compile(
    rf"(\d+(?:[.,]\d+)?)\s*(?:million|millionen|mio\.?|millones|millón|milhões|milhão|millions|milioni|milione)"
    rf"\b{_MONEY}"
    rf"(?:\s+(?:de\s+|d')?({_HOUSEHOLDS}))?", re.IGNORECASE)
_COUNT = re.compile(rf"(\d{{1,3}}(?:[.,\s]\d{{3}})+|\d{{4,7}})\s*({_HOUSEHOLDS}|{_PERSONS})", re.IGNORECASE)
_HOUSEHOLD_WORD = re.compile(_HOUSEHOLDS, re.IGNORECASE)
# Mengenangaben in Worten, die erste passende zählt ("halbe Million" steht deshalb vor "eine Million").
# Die Werte sind vorsichtige Untergrenzen.
_WORD_COUNTS = (
    (re.compile(rf"\b(?:millions|millionen|millones|milhões|milioni)\b{_MONEY}", re.IGNORECASE), 2_000_000),
    (re.compile(r"half a million|halbe million|medio millón|meio milhão", re.IGNORECASE), 500_000),
    (re.compile(rf"\b(?:eine|einer|a|one|un|um)\s+(?:million|millón|milhão|milione)\b{_MONEY}", re.IGNORECASE),
     1_000_000),
    (re.compile(r"hundreds of thousands|hunderttausende|cientos de miles|centenares de miles|"
                r"centenas de milhares|centaines de milliers|centinaia di migliaia", re.IGNORECASE), 200_000),
    (re.compile(r"tens of thousands|zehntausende|decenas de miles|dezenas de milhares|"
                r"dizaines de milliers|decine di migliaia", re.IGNORECASE), 20_000),
    (re.compile(r"\b(?:thousands|tausende|miles de|milhares|milliers|migliaia)\b", re.IGNORECASE), 2_000),
)

GERMAN = {"AT", "DE", "CH", "LI"}
SPANISH = {"ES", "MX", "AR", "CL", "CO", "PE", "VE", "EC", "BO", "PY", "UY", "CU", "DO", "PA", "HN", "GT",
           "NI", "CR", "SV", "PR"}


def count_people(title: str) -> int | None:
    """Liest eine Betroffenenzahl aus einer Schlagzeile. Ein Haushalt oder Kunde zählt als zwei Menschen."""
    best = 0
    for match in _MILLION.finditer(title):
        value = float(match.group(1).replace(",", "."))
        best = max(best, int(value * 1_000_000 * (2 if match.group(2) else 1)))
    for match in _COUNT.finditer(title):
        value = int(re.sub(r"\D", "", match.group(1)))
        best = max(best, value * (2 if _HOUSEHOLD_WORD.fullmatch(match.group(2)) else 1))
    if not best:
        for pattern, value in _WORD_COUNTS:
            if pattern.search(title):
                best = value
                break
    return best or None


def relevant(title: str, language: str = "") -> bool:
    """Wahr, wenn eine Schlagzeile von einem tatsächlichen Stromausfall handelt."""
    if not POWER_WORDS.search(title) or EXCLUDE.search(title):
        return False
    return not language.startswith("de") or bool(GERMAN_OUTAGE.search(title))


def phase(title: str) -> str:
    """Art des Berichts: "lead" Erstbericht, "cause" Ursache, Ermittlungen und Folgen, "follow" Aufarbeitung."""
    if FOLLOWUP.search(title):
        return "follow"
    return "cause" if CAUSE.search(title) or AFTER.search(title) else "lead"


def nationwide(title: str, area: str) -> bool:
    """Wahr, wenn die Schlagzeile einen Ausfall im ganzen Gebiet beschreibt."""
    if area == areas.EUROPE_WIDE:
        return bool(EUROPE_WIDE.search(title))
    if NATIONWIDE.search(title):
        return True
    if not WHOLE_AREA.search(title):
        return False
    if 0 < areas.population(area) <= WHOLE_AREA_MAX_POPULATION:
        return True
    # Großer Staat: nur, wenn die Schlagzeile den Staat selbst nennt ("Ganz Deutschland ohne Strom")
    names = {areas.name(area), areas.name_en(area), _OWN_NAMES.get(area, "")} - {""}
    return any(re.search(rf"(?<!\w){re.escape(name)}(?!\w)", title, re.IGNORECASE) for name in names)


_SECOND_LEVEL = {"co", "com", "org", "net", "gov", "gv", "ac", "or", "edu", "ne", "go"}


def medium(host: str) -> str:
    """Kürzt eine Adresse auf das Medium: ooe.orf.at und kaernten.orf.at sind beide orf.at."""
    parts = host.lower().removeprefix("www.").split(".")
    keep = 3 if len(parts) >= 3 and len(parts[-1]) == 2 and parts[-2] in _SECOND_LEVEL else 2
    return ".".join(parts[-keep:])


def fetch(query: str, language: str, country: str, edition: str | None = None) -> list[dict]:
    text = http.get_text(GOOGLE_NEWS, timeout=20, params={
        "q": query, "hl": language, "gl": country, "ceid": edition or f"{country}:{language}"})
    items = []
    for node in ET.fromstring(text).iter("item"):
        title = (node.findtext("title") or "").strip()
        source = node.find("source")
        name = (source.text or "").strip() if source is not None else ""
        site = medium(urlsplit(source.get("url") or "").netloc) if source is not None else ""
        try:
            when = parsedate_to_datetime(node.findtext("pubDate") or "")
        except (TypeError, ValueError):
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        if name and title.endswith(" - " + name):
            title = title[: -len(name) - 3].strip()
        items.append({"title": title, "domain": site or name or "?", "when": when,
                      "url": (node.findtext("link") or "").strip()})
    return items


def _when(text: str | None):
    """Zeitangabe eines Feed-Eintrags: RSS schreibt sie nach RFC 822, Atom nach ISO 8601."""
    text = (text or "").strip()
    if not text:
        return None
    try:
        when = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        try:
            when = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    return when if when.tzinfo else when.replace(tzinfo=UTC)


def parse_feed(raw: bytes, domain: str) -> list[dict]:
    """Einträge eines RSS- oder Atom-Feeds. Gelesen werden Bytes, damit die Kodierung aus dem XML-Kopf gilt."""
    items = []
    for node in ET.fromstring(raw.lstrip()).iter():
        if node.tag.rsplit("}", 1)[-1] not in ("item", "entry"):
            continue
        fields: dict[str, str] = {}
        for child in node:
            name = child.tag.rsplit("}", 1)[-1]
            if name == "link" and child.get("href"):  # Atom
                if child.get("rel", "alternate") == "alternate":
                    fields.setdefault("link", child.get("href").strip())
            elif name in ("title", "link", "pubDate", "published", "updated", "date"):
                fields.setdefault(name, "".join(child.itertext()).strip())
        when = _when(fields.get("pubDate") or fields.get("published") or fields.get("date") or fields.get("updated"))
        title = " ".join(html.unescape(fields.get("title", "")).split())
        if title and when:  # ohne Zeitangabe lässt sich nicht sagen, ob der Bericht neu ist
            items.append({"title": title, "domain": domain, "when": when, "url": fields.get("link", "")})
    return items


def feed_query(feed: dict) -> dict:
    """Abfrage zu einem Feed aus der Konfiguration. Ohne Angabe gilt er als englisch."""
    return {"hl": "en", **feed, "feed": True}


def fetch_feed(feed: dict) -> list[dict]:
    _, _, raw = http.request(feed["url"], timeout=15, limit=FEED_MAX_BYTES)
    return parse_feed(raw, feed.get("domain") or medium(urlsplit(feed["url"]).netloc))


def confirm_query(area: str) -> dict:
    """Suche, die zu einem Gebiet mit Messsignal Berichte über einen Stromausfall findet."""
    parent = areas.parent(area)
    names = " OR ".join(f'"{name}"' for name in areas.search_names(area))
    if parent in GERMAN:
        country = parent if parent != "LI" else "CH"
        return {"q": f'(Stromausfall OR Blackout OR "ohne Strom") ({names})', "hl": "de", "gl": country, "area": area}
    if parent in SPANISH:
        return {"q": f'(apagón OR "sin luz" OR "corte de energía") ({names})', "hl": "es-419", "gl": "US",
                "ceid": "US:es-419", "area": area}
    return {"q": f'("power outage" OR blackout OR "power cut" OR "without power") ({names})',
            "hl": "en-US", "gl": "US", "ceid": "US:en", "area": area}


def _note(stories: dict, area: str, item: dict, named: bool = True) -> None:
    """Trägt einen Erstbericht in die Lage des Gebiets ein. named: die Schlagzeile nennt das Gebiet selbst."""
    when = iso(item["when"])
    story = stories.setdefault(area, {"first": when, "last": when, "domains": {}, "named": {}, "people": None,
                                      "nationwide": False, "big": False, "top": item["title"], "active": False})
    story["first"] = min(story["first"], when)
    if when >= story["last"]:
        story["last"], story["top"] = when, item["title"]
    story["domains"][item["domain"]] = max(story["domains"].get(item["domain"], ""), when)
    if named:
        story.setdefault("named", {})[item["domain"]] = when
    people = count_people(item["title"])
    if people:
        story["people"] = max(story["people"] or 0, people)
    if nationwide(item["title"], area):
        story["nationwide"] = True
    # Wer "Europa" als betroffen nennt, meint keinen örtlichen Ausfall.
    if BIG_WORDS.search(item["title"]) or WHOLE_AREA.search(item["title"]) or area == areas.EUROPE_WIDE:
        story["big"] = True


def _signal(area: str, story: dict, cfg: dict) -> Signal:
    count = len(story["domains"])
    population = areas.population(area)
    people = story["people"]
    detail = "1 Medium berichtet" if count == 1 else f"{count} Medien berichten"
    if story["nationwide"] and population:
        people = max(people or 0, population // 2)
        if area == areas.EUROPE_WIDE:
            detail += ", europaweiter Ausfall laut Schlagzeilen"
        else:
            detail += ", landesweiter Ausfall laut Schlagzeilen" if areas.parent(area) == area \
                else ", flächendeckender Ausfall laut Schlagzeilen"
    elif people:
        detail += f", rund {fmt_people(people)} Betroffene laut Schlagzeilen"
    elif story.get("big") and count >= cfg["big_sources"] and population:
        people = min(1_000_000, population // 2)  # viele Medien, großer Ausfall, aber keine Zahl
        detail += ", großer Ausfall laut Schlagzeilen, Zahl unbekannt"
    else:
        detail += ", Größe unbekannt"
    if people and population:
        people = min(people, population)
    severity = round(people / population, 4) if people and population else None
    return Signal(MEDIA, "media_outage", area, observed_at=parse_ts(story["last"]), active=True,
                  severity=severity, started_at=parse_ts(story["first"]), confirmed_power=True, detail=detail,
                  metrics={"sources": count, "people": people, "nationwide": story["nationwide"]})


def _opens(stories: dict, closed: dict, area: str, when, window, settled: bool) -> bool:
    """Wahr, wenn ein Bericht über Ursache oder Ermittlungen noch zum Beginn eines Ausfalls gehört."""
    if not settled or area in closed:
        return False  # Vorgeschichte unbekannt (Neustart) oder Lage dort schon beendet: Aufarbeitung
    story = stories.get(area)
    return story is None or when <= parse_ts(story["first"]) + window


def _austrian(fixed: str, title: str, lands: frozenset) -> list:
    """Ordnet eine Schlagzeile aus einer Österreich-Suche über das amtliche Gemeindeverzeichnis zu.

    lands sind die Bundesländer mit eigener Suche (Oberösterreich), fixed ist das Gebiet der Suche. Liegt ein
    genannter Ort eindeutig in einem dieser Bundesländer, zählt der Bericht dafür. Sonst zählt er für
    Österreich. Ausnahme: Einen Namen, den es auch im Bundesland der Suche gibt ("Neumarkt" in der Suche für
    Oberösterreich), entscheidet das Verzeichnis nicht. Dort ordnet wie bisher die Suche zu.
    """
    certain, possible = gazetteer.austria(title)
    own = sorted(certain & lands)
    if own:
        return own
    if not certain and fixed in possible:
        return []
    return ["AT"] if certain or possible else []


def _targets(query: dict, title: str, language: str, lands: frozenset = frozenset()) -> tuple[list, list]:
    """Gebiete, denen ein Bericht zugeordnet wird, und die Gebiete, die seine Schlagzeile selbst nennt."""
    named = gazetteer.find(title, language)
    fixed = query.get("area")
    if fixed and areas.parent(fixed) == "AT" and named in ([], ["AT"]):
        # Kein bekannter Ort oder nur "Österreich": Das Gemeindeverzeichnis weiß es oft genauer.
        local = _austrian(fixed, title, lands)
        if local and (not named or local != ["AT"]):
            named = local
    if fixed and not named:
        # Schlagzeile ohne Ort: Die Suche ordnet sie zu. Eine weite Suche ("... Österreich") findet aber
        # auch Auslandsberichte heimischer Medien, dort zählt nur, was den Ort nennt.
        return ([] if query.get("named_only") else [fixed]), named
    # Nennt die Schlagzeile ein anderes Gebiet als die Suche, gilt die Schlagzeile.
    return ([fixed] if fixed in named else named), named


def _remember(stories: dict, closed: dict, targets: list, when) -> None:
    """Merkt vor, dass es in einem Gebiet ohne offene Lage vor kurzem einen Ausfall gab.

    Berichte über Ursache, Ermittlungen und Folgen gelten dort danach als Aufarbeitung und beginnen
    keine neue Lage (so lange wie nach dem Ende einer Lage, siehe followup_days).
    """
    for area in targets:
        # Auch neben einer Lage, die noch nicht zählt (ein einzelner Bericht ohne Ort): Sonst ginge die
        # Vorgeschichte des Gebiets verloren.
        if not (stories.get(area) or {}).get("active"):
            closed[area] = max(closed.get(area, ""), iso(when))


def _label(query: dict) -> str:
    """Kurzname einer Abfrage für Protokoll und Hinweis."""
    if query.get("feed"):
        return f"Feed {query.get('domain') or urlsplit(query['url']).netloc}"
    return GOOGLE


def _all_feeds(cursor: dict, context: dict) -> bool:
    """Wahr bei Verdacht auf einen großen Ausfall in Europa: Dann kommen alle Feeds in jedem Lauf an die Reihe.

    Der Verdacht besteht, wenn die Messquellen in Europa schweigen oder die Netzfrequenz ausschlägt (context
    "wide"), oder sobald ein erstes Medium "Europa" als betroffen nennt.
    """
    return bool(context.get("wide")) or areas.EUROPE_WIDE in (cursor.get("stories") or {})


def _plan(cfg: dict, cursor: dict, context: dict) -> list[dict]:
    """Abfragen dieses Laufs: Vorrang-Suchen, Welt-Suchen und Feeds reihum, Nachweis-Suchen."""
    plan = list(cfg.get("priority_queries") or [])
    world = cfg.get("world_queries") or []
    if world:
        start = cursor.get("rotation", 0) % len(world)
        plan += [world[(start + step) % len(world)] for step in range(min(cfg["world_per_run"], len(world)))]
        cursor["rotation"] = (start + cfg["world_per_run"]) % len(world)
    plan += [confirm_query(area) for area in (context.get("active_areas") or [])[: cfg["max_areas_per_run"]]]
    feeds = cfg.get("feeds") or []
    if feeds:
        start = cursor.get("feed_rotation", 0) % len(feeds)
        count = min(cfg.get("feeds_per_run", 0), len(feeds))
        if count and _all_feeds(cursor, context):
            count = len(feeds)
        plan += [feed_query(feeds[(start + step) % len(feeds)]) for step in range(count)]
        cursor["feed_rotation"] = (start + count) % len(feeds)
    return plan


def collect(cfg: dict, cursor: dict, now, context: dict) -> list[Signal]:
    stories = cursor.setdefault("stories", {})
    closed = cursor.setdefault("closed", {})  # Gebiet -> letzter Bericht einer beendeten Lage
    max_age = timedelta(minutes=cfg["max_age_minutes"])
    # Nach einem Neustart ist unbekannt, was in den Stunden davor war.
    settled = now - parse_ts(cursor.setdefault("since", iso(now))) >= max_age
    fixed_queries = cfg.get("priority_queries") or []
    # Gebiete mit eigener Suche: dort reichen weniger Medien
    first_hand = {query["area"]: int(query.get("min_sources", cfg["priority_min_sources"]))
                  for query in fixed_queries if query.get("area")}
    lands = frozenset(area for area in first_hand if area in areas.REGIONS)  # Bundesländer mit eigener Suche

    plan = _plan(cfg, cursor, context)
    signals, errors = [], []
    # Einmalig eine Woche zurückschauen. Sonst zählt die Aufarbeitung eines Ausfalls aus den Tagen davor
    # ("Staatsschutz ermittelt nach Stromausfall in Linz") als neuer Ausfall. Der Merker heißt seit dem
    # Gemeindeverzeichnis "lookback": Damit holt auch ein laufender Radar die Rückschau einmal nach.
    lookback = not cursor.get("lookback")
    if lookback:
        plan = [dict(query, days=cfg["followup_days"]) for query in fixed_queries] + plan
    failed = False
    tried, broken = {GOOGLE: 0, FEEDS: 0}, {GOOGLE: 0, FEEDS: 0}
    for index, query in enumerate(plan):
        path = FEEDS if query.get("feed") else GOOGLE
        if index and PAUSE_SECONDS and path == GOOGLE:
            time.sleep(PAUSE_SECONDS)
        days = query.get("days", 1)
        language = query.get("hl", "de")
        tried[path] += 1
        try:
            if path == FEEDS:
                items = fetch_feed(query)
            else:
                items = fetch(f"{query['q']} when:{days}d", language, query.get("gl", "AT"), query.get("ceid"))
        except (HttpError, ET.ParseError) as err:
            errors.append(f"{_label(query)}: {err}")
            broken[path] += 1
            failed = failed or days > 1
            # Ins Protokoll, damit sich nachzählen lässt, wie oft eine Abfrage abgewiesen wird.
            log.warning("Medien: Abfrage fehlgeschlagen (%s%s): %s", _label(query),
                        f", Gebiet {query['area']}" if query.get("area") else "", err)
            continue
        if days > 1:
            for item in items:
                if now - item["when"] > max_age and relevant(item["title"], language):
                    _remember(stories, closed, _targets(query, item["title"], language, lands)[0], item["when"])
            continue
        for item in sorted(items, key=lambda entry: entry["when"]):
            title = item["title"]
            if item["when"] > now + timedelta(minutes=10) or not relevant(title, language):
                continue
            targets, named = _targets(query, title, language, lands)
            if now - item["when"] > max_age:
                _remember(stories, closed, targets, item["when"])  # zu alt, um etwas auszulösen
                continue
            kind = phase(title)
            for area in targets:
                lead = kind == "lead" or (
                    kind == "cause" and _opens(stories, closed, area, item["when"], max_age, settled))
                signals.append(Signal(SOURCE, "news", area, observed_at=item["when"], active=False, detail=title,
                                      url=item["url"], metrics={"domain": item["domain"], "power": True,
                                                                "lead": lead}))
                if lead:
                    _note(stories, area, item, named=area in named)
            if kind == "follow":
                _remember(stories, closed, targets, item["when"])

    quiet = timedelta(hours=cfg["quiet_hours"])
    for area, story in list(stories.items()):
        last = parse_ts(story["last"])
        if now - last > quiet:
            if story["active"]:
                closed[area] = story["last"]
                signals.append(Signal(MEDIA, "media_outage", area, observed_at=now, active=False, severity=0.0,
                                      started_at=parse_ts(story["first"]), ended_at=last,
                                      detail="keine neuen Medienberichte"))
            del stories[area]
            continue
        needed = first_hand.get(area, cfg["world_min_sources"])
        # Berichte, die das Gebiet selbst nennen, zählen voll. Sonst braucht es ein Medium mehr.
        enough = len(story.get("named") or {}) >= needed or len(story["domains"]) > needed
        if story["active"] or enough:
            story["active"] = True
            signals.append(_signal(area, story, cfg))
    keep = timedelta(days=cfg["followup_days"])
    for area in [area for area, last in closed.items() if now - parse_ts(last) > keep]:
        del closed[area]

    if lookback and not failed:
        cursor["lookback"] = iso(now)
        cursor.pop("history", None)  # so hieß der Merker vor dem Gemeindeverzeichnis
    cursor["note"] = "; ".join(sorted(set(errors)))
    cursor["degraded"] = ""
    if plan and len(errors) == len(plan):
        raise HttpError(cursor["note"])
    # Fällt ein ganzer Weg aus, läuft der andere weiter. Der Ausfall soll trotzdem sichtbar sein: Die
    # Suchen für Oberösterreich und Österreich laufen nur über Google News.
    down = [path for path in (GOOGLE, FEEDS) if tried[path] and broken[path] == tried[path]]
    if down:
        cursor["degraded"] = f"{' und '.join(down)} ohne Antwort ({cursor['note']})"[:300]
    cursor["data_time"] = iso(now)
    return signals
