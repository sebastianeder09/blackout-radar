"""Ortsnamen in Schlagzeilen erkennen: Staaten, Einwohnerbezeichnungen, große Städte.

Dient nur dazu, einen Medienbericht einem Staat zuzuordnen (für Oberösterreich
auch dem Bundesland). Die Liste ist bewusst grob. Mehrdeutige Namen fehlen
absichtlich, zum Beispiel Georgia (Staat und US-Bundesstaat), Jordan, Chad, Niger. Städte, die es
auch in den USA gibt (Naples, Venice, St. Petersburg, Melbourne, Odessa), stehen nur in der
Schreibweise ihres Landes in der Liste. Die Kurzformen der USA ("US", "U.S.", "USA") zählen nur
als Ortsangabe, nicht für den Handelnden ("US-Sanktionen", "US embassy urges ...").

Für Österreich ist die Liste dichter: Je mehr Orte außerhalb Oberösterreichs bekannt sind,
desto seltener wird ein Bericht aus einem anderen Bundesland Oberösterreich zugeschlagen.

"Europa" und Teile davon ("Südeuropa", "Balkans") zählen als eigenes Gebiet, aber nur, wenn die
Schlagzeile sonst kein Gebiet nennt ("Massive blackout hits Europe"). Mit einem Land in derselben
Schlagzeile ist das Land gemeint ("Spain blackout: Europe's worst power outage"). Als Teil eines Namens
oder als Besitzer zählt Europa nicht ("Europa League", "Europas größtes Atomkraftwerk ohne Strom").

Für Suchen innerhalb Österreichs gibt es dazu das amtliche Gemeindeverzeichnis (austria()): Es sagt,
in welchem Bundesland ein Ort liegt, den die Liste hier nicht kennt.
"""
from __future__ import annotations

import re

from . import areas, gemeindeliste

SKIP = {"Georgia", "Jordan", "Chad", "Niger", "Tschad"}

# Gebiet: weitere Schreibweisen, Einwohnerbezeichnungen, Regionen und Städte
_ALIASES = """
AT-4: Oberösterreich|Upper Austria|Linz|Wels|Steyr|Mühlviertel|Innviertel|Traunviertel|Hausruckviertel|Oberösterreichs|OÖ|Linzer|Welser|Steyrer|Mühlviertler|Innviertler|Urfahr|Kleinmünchen|Ebelsberg|Leonding|Traun|Ansfelden|Pasching|Hörsching|Marchtrenk|Enns|Braunau|Ried im Innkreis|Bezirk Ried|Schärding|Vöcklabruck|Gmunden|Bad Ischl|Kirchdorf an der Krems|Bezirk Kirchdorf|Freistadt|Perg|Bezirk Rohrbach|Eferding|Grieskirchen|Attnang-Puchheim|Mauthausen|Gallneukirchen|Salzkammergut
AT: Austrian|Autriche|Wien|Vienna|Graz|Salzburg|Innsbruck|Klagenfurt|Tirol|Tyrol|Steiermark|Kärnten|Vorarlberg|Burgenland|Niederösterreich|Österreichs|Lower Austria|Styria|Carinthia|NÖ|Wiener Neustadt|Wiener|St. Pölten|Sankt Pölten|Krems|Amstetten|Mödling|Klosterneuburg|Waldviertel|Weinviertel|Mostviertel|Eisenstadt|Grazer|Leoben|Kapfenberg|Obersteiermark|Kärntner|Villach|Wolfsberg|Osttirol|Lienz|Kufstein|Kitzbühel|Bregenz|Dornbirn|Feldkirch|Bludenz|Pinzgau|Pongau|Lungau|Flachgau|Tennengau|Zillertal|Ötztal|Außerfern|Lavanttal|Gailtal|Bregenzerwald|Montafon|Mürztal|Oststeiermark|Weststeiermark|Südsteiermark|Südburgenland|Mittelburgenland|Nordburgenland|Seewinkel|Industrieviertel|Ausseerland
EU: Europa|Europas|Europe|European|Europe-wide|europaweit|europaweite|europaweiter|europaweiten|europaweitem|europaweites|Europaweiter|Europaweite|Europaweit|Mitteleuropa|Mitteleuropas|Zentraleuropa|Westeuropa|Westeuropas|Südeuropa|Südeuropas|Osteuropa|Südosteuropa|Nordeuropa|Kontinentaleuropa|Balkan|Balkans|Westbalkan|Skandinavien|Scandinavia|Baltikum|Baltics|Baltic states
DE: German|Allemagne|Alemania|Germania|Berlin|München|Munich|Hamburg|Frankfurt|Köln|Cologne|Stuttgart|Bayern|Bavaria|Europa-Park|Europapark
CH: Swiss|Suisse|Suiza|Svizzera|Zürich|Zurich|Genf|Geneva|Genève|Basel
IT: Italian|Italia|Italie|Rom|Rome|Roma|Milano|Mailand|Napoli|Neapel|Turin|Torino|Sicily|Sicilia|Sizilien|Sardinia|Sardegna|Sardinien|Südtirol|Venedig|Venezia
FR: French|Francia|França|Paris|Marseille|Lyon|Toulouse|Bordeaux|Cannes
ES: España|Spanish|Espagne|Spagna|Espanha|Iberian Peninsula|Iberische Halbinsel|Península Ibérica|Madrid|Barcelona|Sevilla|Seville|Andalucía|Cataluña|Catalonia|Canarias|Canary Islands|Kanaren|Tenerife|Teneriffa|Mallorca|Málaga|Bilbao|Zaragoza|Galicia|Asturias|Extremadura|Castilla
PT: Portuguese|Portogallo|Lisbon|Lisboa|Lissabon
GB: Britain|UK|U.K.|England|Scotland|Wales|Northern Ireland|London|Heathrow|Großbritannien|Schottland|Royaume-Uni|Reino Unido|Gran Bretaña
IE: Irish|Dublin
NL: Dutch|Pays-Bas|Países Bajos|Amsterdam|Rotterdam
BE: Belgian|Belgique|Bélgica|Brussels|Brüssel|Bruxelles
DK: Danish|Copenhagen|Kopenhagen
SE: Swedish|Stockholm
NO: Norwegian|Oslo
FI: Finnish|Helsinki
PL: Polish|Pologne|Polonia|Warsaw|Warschau
CZ: Czech|Czechia|Prague|Prag
SK: Slovak|Bratislava
HU: Hungarian|Budapest
SI: Slovenian|Ljubljana
HR: Croatian|Zagreb|Dalmatia|Dalmatien|Dubrovnik
RS: Serbian|Belgrade|Belgrad
BA: Bosnia and Herzegovina|Bosnian|Sarajevo
ME: Montenegrin|Podgorica
MK: Skopje
AL: Albanian|Tirana
XK: Pristina
GR: Greek|Grèce|Grecia|Athens|Athen|Thessaloniki|Crete|Kreta
BG: Bulgarian|Sofia
RO: Romanian|Bucharest|Bukarest
MD: Moldovan|Chisinau|Chișinău|Transnistria|Transnistrien
UA: Ukrainian|Ucrania|Kyiv|Kiev|Kiew|Kharkiv|Charkiw|Odesa|Dnipro|Lviv|Lwiw|Zaporizhzhia|Saporischschja|Kherson|Cherson|Mykolaiv
UA-43: Crimea|Crimean|Krim|Crimée|Crimeia|Sevastopol|Sewastopol|Simferopol
RU: Rusia|Russie|Moscow|Moskau|Sankt Petersburg|Belgorod
BY: Belarusian|Minsk
LT: Lithuanian|Vilnius
LV: Latvian|Riga
EE: Estonian|Tallinn
TR: Türkiye|Turkish|Turquía|Turquie|Istanbul|Ankara|Izmir
CY: Cypriot|Nicosia
MT: Maltese|Valletta
IL: Tel Aviv
PS: Gaza|Gazastreifen|West Bank|Westjordanland
LB: Lebanese|Liban|Líbano|Beirut
SY: Syrian|Damascus|Damaskus|Aleppo
IQ: Iraqi|Baghdad|Bagdad|Basra
IR: Iranian|Irán|Tehran|Teheran
SA: Saudi|Riyadh|Riad
AE: UAE|Dubai|Abu Dhabi
YE: Yemeni|Sanaa|Aden
JO: Amman
EG: Egyptian|Egipto|Égypte|Cairo|Kairo
LY: Libyan|Tripoli|Tripolis|Benghazi
TN: Tunisian|Tunisie|Tunis
DZ: Algerian|Algérie|Argelia|Algiers|Algier
MA: Moroccan|Maroc|Marruecos|Casablanca|Rabat
NG: Nigerian|Lagos|Abuja
GH: Ghanaian|Accra
KE: Kenyan|Nairobi
TZ: Tanzanian|Dar es Salaam|Zanzibar
UG: Ugandan|Kampala
ET: Ethiopian|Addis Ababa
SD: Sudanese|Khartoum
ZA: South African|Sudáfrica|Afrique du Sud|Eskom|Johannesburg|Cape Town|Kapstadt|Durban|Pretoria
ZW: Zimbabwean|Harare
ZM: Zambian|Lusaka
MZ: Mozambican|Maputo
AO: Angolan|Luanda
CD: DR Congo|DRC|RDC|Kinshasa
SN: Senegalese|Sénégal|Dakar
CI: Ivory Coast|Côte d'Ivoire|Abidjan
CM: Cameroonian|Cameroun|Yaoundé|Douala
ML: Bamako
MW: Malawian|Lilongwe
MG: Antananarivo
NA: Namibian|Windhoek
PK: Pakistani|Pakistán|Karachi|Lahore|Islamabad|Sindh|Balochistan
IN: Mumbai|Delhi|Bengaluru|Bangalore|Chennai|Kolkata|Hyderabad|Kerala|Tamil Nadu|Maharashtra|Uttar Pradesh
BD: Bangladeshi|Bangladés|Dhaka
LK: Sri Lankan|Colombo
NP: Nepali|Kathmandu
AF: Afghan|Kabul
MM: Burma|Yangon
TH: Thai|Bangkok
VN: Vietnamese|Hanoi|Ho Chi Minh
KH: Cambodian|Phnom Penh
MY: Malaysian|Kuala Lumpur|Sabah|Sarawak
ID: Indonesian|Jakarta|Bali|Sumatra|Sulawesi
PH: Philippine|Filipinas|Manila|Luzon|Mindanao|Visayas|Cebu|Panay
CN: Beijing|Peking|Shanghai|Guangdong|Shenzhen|Sichuan
TW: Taiwanese|Taipei
JP: Japanese|Japón|Japon|Tokyo|Tokio|Osaka|Hokkaido
KR: Seoul
KP: Pyongyang
KZ: Kazakh|Almaty|Astana
UZ: Uzbek|Tashkent|Taschkent
KG: Kyrgyz|Bishkek|Bischkek
TJ: Tajik|Dushanbe
AZ: Azerbaijani|Baku
AM: Armenian|Yerevan|Eriwan
GE: Tbilisi|Tiflis
AU: Australian|Sydney|Brisbane|Adelaide|Queensland|New South Wales|Tasmania|Western Australia|South Australia
NZ: Auckland|Christchurch|South Island|North Island
US: United States|Estados Unidos|États-Unis|Etats-Unis|Vereinigte Staaten|Vereinigten Staaten|Stati Uniti|U.S.|US|EE.UU.|EE. UU.|EEUU|EUA|Midwest|Long Island|Staten Island|New Mexico|New England|Panama City|Texas|California|Kalifornien|Florida|New York|Louisiana|Michigan|Ohio|Pennsylvania|Illinois|North Carolina|South Carolina|Virginia|Tennessee|Kentucky|Alabama|Mississippi|Oklahoma|Arkansas|Missouri|Wisconsin|Minnesota|Colorado|Arizona|Nevada|Oregon|Massachusetts|New Jersey|Maryland|Hawaii|Alaska|Houston|Dallas|Chicago|Los Angeles|San Francisco|San Diego|Seattle|Miami|Atlanta|Detroit|Boston|Philadelphia|New Orleans|Las Vegas|Indiana|Iowa|Kansas|Nebraska|Utah|Idaho|Montana|Wyoming|Connecticut|Maine|Vermont|New Hampshire|Rhode Island|Delaware|West Virginia|North Dakota|South Dakota|Phoenix|Denver|Austin|San Antonio|Charlotte|Nashville|Memphis|Pittsburgh|Cleveland|Minneapolis|St. Louis|Tampa|Orlando
CA: Canadian|Canadá|Ontario|Quebec|Québec|British Columbia|Alberta|Manitoba|Nova Scotia|Vancouver Island|Toronto|Montreal|Montréal|Vancouver|Calgary|Ottawa
MX: México|Mexique|Mexican|Mexico City|Ciudad de México|Yucatán|Nuevo León|Monterrey|Guadalajara|mexicano|mexicana|CDMX|Puebla|Jalisco|Veracruz|Chiapas|Oaxaca|Sonora|Sinaloa|Tamaulipas|Chihuahua|Coahuila|Quintana Roo|Cancún|Tijuana|Baja California|Campeche|Tabasco|Michoacán|Guanajuato|Querétaro
CU: Cuban|La Habana|Havana|Havanna|cubano|cubana|Santiago de Cuba|Holguín|Matanzas|Camagüey
DO: República Dominicana|Dominican Republic|Santo Domingo
HT: Haïti|Haití
VE: Venezuelan|Caracas|Maracaibo|venezolano|venezolana|Zulia|Táchira|Corpoelec
CO: Colombian|Colômbia|Bogotá|Bogota|Medellín|colombiano|colombiana|Nariño|Putumayo|Caquetá|Huila|Cauca|Pasto|Barranquilla|Antioquia
EC: Ecuadorian|Quito|Guayaquil|ecuatoriano|ecuatoriana
PE: Perú|Peruvian|peruano|peruana|Lima|Arequipa|Cusco|Piura
BO: Bolivian
CL: Chilean|Santiago de Chile|chileno|chilena|Valparaíso|Antofagasta|Biobío
AR: Argentine|Argentinian|Buenos Aires|argentino|Salta|Mendoza|Tucumán|Rosario|AMBA|Jujuy|Neuquén|La Plata|Mar del Plata|Edesur|Edenor
BR: Brasil|Brazilian|Brésil|São Paulo|Sao Paulo|Rio de Janeiro|Brasília|Amapá|Roraima|Minas Gerais|brasileiro|brasileira|Bahia|Pernambuco|Ceará|Pará|Maranhão|Goiás|Mato Grosso|Rio Grande do Sul|Santa Catarina|Recife|Fortaleza|Manaus|Belo Horizonte|Curitiba|Porto Alegre
PY: Paraguayan|Asunción
UY: Uruguayan|Montevideo
PA: Panamá
HN: Honduran|Tegucigalpa
GT: Guatemalan
NI: Nicaraguan
"""

# Wer nur als Handelnder vorkommt ("Russia strikes ...", "blames US"), ist nicht betroffen.
_ACTOR_AFTER = re.compile(
    r"(?:'s|’s|s)?\s+(?:air\s?|drone\s|missile\s|oil\s|fuel\s|energy\s|trade\s|economic\s|naval\s)?"
    r"(?:strikes?|attacks?|attacked|bombs?|bombing|bombardment|shelling|"
    r"missiles?|drones?|sanctions|embargo|blockade|offensive|Angriffe?n?|Luftangriffe?n?|Beschuss|Sanktionen|"
    r"ataques?|bombardeos?|sanciones|bloqueo|frappes?|attaques?)\b", re.IGNORECASE)
_ACTOR_BEFORE = re.compile(r"(?:blames?|blaming|accuses?|beschuldigt|culpa a|acusa a|accuse)\s+(?:the\s+)?$",
                           re.IGNORECASE)

# Kurzformen der USA stehen in Schlagzeilen oft nur für den Handelnden oder Beobachter ("Cuba blackout:
# US embassy urges ...", "US-Sanktionen"). Als Ort zählen sie nur allein in der Schlagzeile, nach einem
# Verhältniswort ("in the US", "en EE.UU.") oder als Teil einer Ortsangabe ("US-Ostküste", "US Midwest").
_SHORT = {"US", "U.S.", "USA", "EE.UU.", "EE. UU.", "EEUU", "EUA"}
_PLACE_AFTER = re.compile(
    r"[-\s](?:Ostküste|Westküste|Golfküste|Küste|Bundesstaat(?:en|es)?|Staat(?:en)?|Südstaaten|Stadt|Städten?|"
    r"Metropole|Großstadt|Millionenstadt|East Coast|West Coast|Gulf Coast|Northeast|Southeast|Midwest|South|"
    r"states?|cit(?:y|ies)|mainland)\b")
_PLACE_BEFORE = re.compile(
    r"\b(?:in|in the|in den|across the|throughout the|over the|an der|an die|vor der|en|en los|nos|negli)\s+$",
    re.IGNORECASE)
_MONEY_AFTER = re.compile(r"\$|[-\s](?:dollars?|d[oó]lares)\b", re.IGNORECASE)
# Deutsche Namen, die im Englischen ein gewöhnliches Wort sind ("Island-wide blackout hits Puerto Rico")
_GERMAN_ONLY = {"Island"}

# "Europa" ist oft nur Teil eines Namens, der Besitzer von etwas Einzelnem oder der Handelnde ("Europa League",
# "Europa-Center", "Europas größtes Atomkraftwerk ohne Strom", "European Union", "Zugverkehr europaweit
# gestört"). Als Gebiet zählt es nur, wo der Kontinent selbst als Ort des Ausfalls gemeint ist.
_EU_BASE = {"Europa", "Europe"}
# Eigennamen: Wörter mit Bindestrich außer "Europa-Blackout", dazu bekannte Namen mit Leerzeichen
_EU_NAME_AFTER = re.compile(
    r"-(?!(?:Blackout|Stromausfall|Stromausfälle)\b)[^\W\d_]|"
    r"\s+(?:League|Conference|Park|Passage|Cent(?:er|re)|Clipper|Cup|Tour|Hotel|Galerie|Arena|Palast|Point|Press|"
    r"[12])\b")
# Besitzanzeigend ("Europas", "Europe's"), als Eigenschaftswort ("European") und als Umstandswort ("europaweit")
# zählt es nur direkt vor dem Netz, dem Ausfall oder einer Mehrzahl von Orten ...
_EU_WEAK = {"European", "Europas", "Mitteleuropas", "Westeuropas", "Südeuropas"}
_EU_WEAK_START = ("europaweit", "europe-wide")
_EU_POSSESSIVE = re.compile(r"'s|’s")
_EU_PLACE_AFTER = re.compile(
    r"(?:'s|’s)?\s+(?:(?:massive|major|huge|widespread|biggest|largest|worst|grö(?:ß|ss)te[rsn]?|massive[rsn]?|"
    r"gro(?:ß|ss)e[rsn]?|schwerste[rsn]?)\s+)?"
    r"(?:(?:power|electricity|electrical|energy)\s+(?:grids?|outages?|cuts?|failures?|blackouts?)|grids?|"
    r"blackouts?|outages?|Stromnetz|Netz|Stromversorgung|Stromausf[aä]lle?|Stromstörung(?:en)?|ohne Strom|"
    r"kein Strom|countries|nations|cities|capitals)\b", re.IGNORECASE)
# ... im Deutschen auch nach einer Teilangabe ("in weiten Teilen Europas", "im Süden Europas").
_EU_PART_BEFORE = re.compile(
    r"\b(?:Teile[n]?|Hälfte|Großteil|Westen|Osten|Norden|Süden|Mitte|Länder[n]?|Staaten|Regionen|Städte[n]?)\s+$")


def _continent(text: str, match) -> bool:
    """Wahr, wenn mit "Europa" der Kontinent als Ort gemeint ist, nicht ein Name, Besitzer oder Handelnder."""
    name, rest = match.group(0), text[match.end():]
    if name in _EU_WEAK or name.lower().startswith(_EU_WEAK_START) or _EU_POSSESSIVE.match(rest):
        return bool(_EU_PLACE_AFTER.match(rest) or _EU_PART_BEFORE.search(text[: match.start()]))
    return name not in _EU_BASE or not _EU_NAME_AFTER.match(rest)


def _build():
    names: dict[str, str] = {}
    for code, (german, english, _) in {**areas.COUNTRIES, **areas.REGIONS}.items():
        if code in areas.REGIONS and code != "AT-4":
            continue  # übrige Teilgebiete kommen nur über die Liste oben (Bundesländer zählen als Österreich)
        for name in (german, english):
            if name not in SKIP:
                names.setdefault(name, code)
    for line in _ALIASES.strip().splitlines():
        code, _, rest = line.partition(":")
        for name in rest.split("|"):
            if name.strip():
                names[name.strip()] = code.strip()
    known = {name: code for name, code in names.items()
             if code in areas.COUNTRIES or code in areas.REGIONS or code == areas.EUROPE_WIDE}
    pattern = "|".join(re.escape(name) for name in sorted(known, key=len, reverse=True))
    return known, re.compile(rf"(?<!\w)(?:{pattern})(?!\w)(?!-(?:led|backed|based|built|made|style|owned|born|installed|controlled|occupied|annexed|held|appointed|linked|aligned)\b)")


_NAMES, _PATTERN = _build()


def find(text: str, language: str = "") -> list[str]:
    """Gebiete, die in einer Schlagzeile als betroffen genannt werden, in der Reihenfolge des Auftretens.

    language ist die Sprache der Suche, die die Schlagzeile geliefert hat (leer: unbekannt).
    """
    foreign = bool(language) and not language.startswith("de")
    found, short = [], []
    for match in _PATTERN.finditer(text):
        if _ACTOR_AFTER.match(text, match.end()) or _ACTOR_BEFORE.search(text[: match.start()]):
            continue
        name, code = match.group(0), _NAMES[match.group(0)]
        if foreign and name in _GERMAN_ONLY:
            continue
        if code == areas.EUROPE_WIDE and not _continent(text, match):
            continue
        if name in _SHORT:
            place = _PLACE_AFTER.match(text, match.end())
            if _MONEY_AFTER.match(text, match.end()) or (text[match.end(): match.end() + 1] == "-" and not place):
                continue  # "US$ 5 Millionen", "US-Präsident", "US-Sanktionen"
            if not place and not _PLACE_BEFORE.search(text[: match.start()]):
                if code not in short:
                    short.append(code)  # zählt nur, wenn die Schlagzeile sonst kein Gebiet nennt
                continue
        if code not in found:
            found.append(code)
    found = found or short
    if len(found) > 1 and areas.EUROPE_WIDE in found:
        found.remove(areas.EUROPE_WIDE)  # mit einem Land in der Schlagzeile ist das Land gemeint
    # Ein Bundesland schließt den Staat ein: "Linz, Österreich" zählt nur für das Bundesland.
    return [code for code in found if not any(other != code and areas.parent(other) == code for other in found)]


# --------------------------------------------------------------- Gemeinden in Österreich
# Namen, die allein nichts aussagen: Wörter der Alltagssprache ("in weiten Teilen", "Straßen", "Brand"),
# häufige Familiennamen, bekanntere Orte gleichen Namens im Ausland und Vorsilben von Doppelnamen.
# Mit vollem Namen ("Brand-Nagelberg", "Langen bei Bregenz") werden diese Gemeinden trotzdem erkannt.
_NOT_ALONE = set("""
allerheiligen anger baden berg bergland bernstein brand brixen deutsch dorf dörfl fügen gaming going griffen
gross gutenberg hartl hochburg höchst höfen kaisers kammern kasten klaus klein krakau krumau landl landstrasse
langen malta manning maria markt mining mühlen münster neubau obdach oberdorf polling raab ratten schützen
sonntag spital spitz stall strassburg strassen strengen strobl stronach stumm thüringen treffen trieben weiden weiler
weiten werfen wiesen winden
""".split())
# Orte in Oberösterreich, deren Name allein auch einen bekannteren oder grenznahen Ort anderswo meint: in Bayern
# (Pfarrkirchen, Burgkirchen, Taufkirchen, Kirchheim), Stadtteile (Graz-Liebenau, Berlin-Lichtenberg,
# Hamburg-Ohlsdorf), Ortsteile in anderen Bundesländern (Wartberg im Mürztal, Rosenau am Sonntagberg, Pichl
# bei Schladming). Auch sie zählen nur mit vollem Namen. Das Verzeichnis kennt Gemeinden, keine Ortsteile:
# Gleichnamige Ortsteile anderswo, die hier fehlen, werden Oberösterreich zugeordnet.
_NOT_ALONE |= set("""
altenberg altheim aspach auerbach burgkirchen haibach haslach hofkirchen holzhausen innere-stadt julbach
kirchham kirchheim lichtenberg liebenau mühlheim ohlsdorf pfarrkirchen pichl puchheim rosenau rossbach
schleissheim steinbach steinhaus taufkirchen thalheim trattenbach wartberg weissenbach
""".split())
_NOT_ALONE |= {"st gotthard", "innere stadt"}  # Gotthard in der Schweiz, "Innere Stadt" gibt es auch in Linz und Graz
_MIN_LETTERS = 5      # kürzere Namen sind meist auch gewöhnliche Wörter (Au, Egg, Hof, Zell, Haus)
_GENITIVE_LETTERS = 7  # "Tragweins" zählt wie "Tragwein", "Pergs" und "Welser" nicht
_JOINERS = {"am", "im", "an", "bei", "in", "ob"}
_AT_WORD = re.compile(r"[^\W\d_]+(?:-[^\W\d_]+)*")
_DISTRICT_WORDS = {"bezirks": "bezirk", "bezirkes": "bezirk", "bezirke": "bezirk", "bezirken": "bezirk"}


def _plain(text: str) -> str:
    """Einheitliche Schreibweise: klein, "Sankt" und "St." gleich, ohne Satzzeichen ("St. Georgen" -> "st georgen")."""
    text = re.sub(r"\b(?:sankt|skt)\b\.?", "st", text.casefold())
    return " ".join(_AT_WORD.findall(text.replace(".", " ")))


def _short(name: str) -> str:
    """Name ohne Zusatz: "Neumarkt im Mühlkreis" -> "Neumarkt", "Sankt Josef (Weststeiermark)" -> "Sankt Josef"."""
    words = re.sub(r"\s*\(.*?\)", "", name).split()
    for index, word in enumerate(words):
        if index and (word.casefold() in _JOINERS or re.match(r"a\.[a-z]\.", word.casefold())):
            return " ".join(words[:index])
    return " ".join(words)


def _build_austria() -> tuple[dict, int]:
    table: dict[str, set] = {}

    def add(key: str, land: str) -> None:
        key = _plain(key)
        if key:
            table.setdefault(key, set()).add(land)

    for land, names in gemeindeliste.GEMEINDEN.items():
        for name in names.split("|"):
            short = _short(name)
            add(name, land)
            add(short, land)
            if "-" in short:  # Doppelnamen: "Zwettl-Niederösterreich" heißt im Alltag "Zwettl"
                for part in short.split("-"):
                    add(part, land)
    for name in gemeindeliste.WIEN.split("|"):
        add(name, "AT-9")
        if "-" in name:
            for part in name.split("-"):
                add(part, "AT-9")
    usable = {key: lands for key, lands in table.items()
              if key not in _NOT_ALONE and (" " in key or "-" in key or len(key) >= _MIN_LETTERS)}
    # Bezirke zählen mit dem Wort davor ("Bezirk Ried", "Bezirk Horn"), dann auch mit kurzem oder mehrdeutigem Namen
    for land, names in gemeindeliste.BEZIRKE.items():
        for name in names.split("|"):
            name = re.sub(r"\((?:Stadt|Land)\)$|\s(?:Stadt|Land)$|^Stadt\s", "", name).strip()
            for form in {name, _short(name), _short(name).split("-")[0]}:
                usable.setdefault("bezirk " + _plain(form), set()).add(land)
            if "-" in name or len(_plain(name)) >= 10:  # "Bruck-Mürzzuschlag", "Südoststeiermark"
                usable.setdefault(_plain(name), set()).add(land)
    return usable, max(len(key.split()) for key in usable)


_AT_NAMES, _AT_WORDS = _build_austria()


def austria(text: str) -> tuple[set, set]:
    """Bundesländer, deren Gemeinden, Bezirke oder Wiener Bezirke ein Text nennt (amtliches Gemeindeverzeichnis).

    Liefert (sicher, möglich): "sicher" sind Bundesländer, in denen ein genannter Name eindeutig liegt.
    "möglich" sind die Bundesländer zu Namen, die es in mehreren gibt ("Neumarkt", "Kirchberg").
    Nur für Berichte gedacht, die eine Suche in Österreich geliefert hat: Viele Namen gibt es auch im Ausland.
    """
    tokens = [_DISTRICT_WORDS.get(token, token) for token in _plain(text).split()]
    certain, possible = set(), set()
    index = 0
    while index < len(tokens):
        for length in range(min(_AT_WORDS, len(tokens) - index), 0, -1):
            lands = _AT_NAMES.get(" ".join(tokens[index: index + length]))
            if lands is None and length == 1:
                lands = _single(tokens[index])
            if lands:
                (certain if len(lands) == 1 else possible).update(lands)
                index += length - 1
                break
        index += 1
    return certain, possible - certain


def _single(token: str) -> set | None:
    """Ein einzelnes Wort: Teile eines Bindestrich-Worts ("Wien-Favoriten") und der Wesfall ("Tragweins")."""
    if "-" in token:
        found = set()
        for part in token.split("-"):
            found |= _AT_NAMES.get(part) or set()
        return found or None
    if token.endswith("s") and len(token) >= _GENITIVE_LETTERS:
        return _AT_NAMES.get(token[:-1])
    return None
