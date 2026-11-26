"""Ortsnamen in Schlagzeilen erkennen: Staaten, Einwohnerbezeichnungen, große Städte.

Dient nur dazu, einen Medienbericht einem Staat zuzuordnen (für Oberösterreich
auch dem Bundesland). Die Liste ist bewusst grob. Mehrdeutige Namen fehlen
absichtlich, zum Beispiel Georgia (Staat und US-Bundesstaat), Jordan, Chad, Niger. Städte, die es
auch in den USA gibt (Naples, Venice, St. Petersburg, Melbourne, Odessa), stehen nur in der
Schreibweise ihres Landes in der Liste.
"""
from __future__ import annotations

import re

from . import areas

SKIP = {"Georgia", "Jordan", "Chad", "Niger", "Tschad"}

# Gebiet: weitere Schreibweisen, Einwohnerbezeichnungen, Regionen und Städte
_ALIASES = """
AT-4: Oberösterreich|Upper Austria|Linz|Wels|Steyr|Mühlviertel|Innviertel|Traunviertel|Hausruckviertel
AT: Austrian|Autriche|Wien|Vienna|Graz|Salzburg|Innsbruck|Klagenfurt|Tirol|Tyrol|Steiermark|Kärnten|Vorarlberg|Burgenland|Niederösterreich
DE: German|Allemagne|Alemania|Germania|Berlin|München|Munich|Hamburg|Frankfurt|Köln|Cologne|Stuttgart|Bayern|Bavaria
CH: Swiss|Suisse|Suiza|Svizzera|Zürich|Zurich|Genf|Geneva|Genève|Basel
IT: Italian|Italia|Italie|Rom|Rome|Roma|Milano|Mailand|Napoli|Neapel|Turin|Torino|Sicily|Sicilia|Sizilien|Sardinia|Sardegna|Sardinien|Südtirol|Venedig|Venezia
FR: French|Francia|França|Paris|Marseille|Lyon|Toulouse|Bordeaux|Cannes
ES: España|Spanish|Espagne|Spagna|Espanha|Madrid|Barcelona|Sevilla|Seville|Andalucía|Cataluña|Catalonia|Canarias|Canary Islands|Kanaren|Tenerife|Teneriffa|Mallorca
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
NZ: Auckland|Christchurch
US: United States|Estados Unidos|États-Unis|New Mexico|New England|Panama City|Texas|California|Kalifornien|Florida|New York|Louisiana|Michigan|Ohio|Pennsylvania|Illinois|North Carolina|South Carolina|Virginia|Tennessee|Kentucky|Alabama|Mississippi|Oklahoma|Arkansas|Missouri|Wisconsin|Minnesota|Colorado|Arizona|Nevada|Oregon|Massachusetts|New Jersey|Maryland|Hawaii|Alaska|Houston|Dallas|Chicago|Los Angeles|San Francisco|San Diego|Seattle|Miami|Atlanta|Detroit|Boston|Philadelphia|New Orleans|Las Vegas
CA: Canadian|Canadá|Ontario|Quebec|Québec|British Columbia|Alberta|Manitoba|Nova Scotia|Toronto|Montreal|Montréal|Vancouver|Calgary|Ottawa
MX: México|Mexique|Mexican|Mexico City|Ciudad de México|Yucatán|Nuevo León|Monterrey|Guadalajara
CU: Cuban|La Habana|Havana|Havanna
DO: República Dominicana|Dominican Republic|Santo Domingo
HT: Haïti|Haití
VE: Venezuelan|Caracas|Maracaibo
CO: Colombian|Colômbia|Bogotá|Bogota|Medellín
EC: Ecuadorian|Quito|Guayaquil
PE: Perú|Peruvian
BO: Bolivian
CL: Chilean|Santiago de Chile
AR: Argentine|Argentinian|Buenos Aires
BR: Brasil|Brazilian|Brésil|São Paulo|Sao Paulo|Rio de Janeiro|Brasília|Amapá|Roraima|Minas Gerais
PY: Paraguayan|Asunción
UY: Uruguayan|Montevideo
PA: Panamá
HN: Honduran|Tegucigalpa
GT: Guatemalan
NI: Nicaraguan
"""

# Wer nur als Handelnder vorkommt ("Russia strikes ...", "blames US"), ist nicht betroffen.
_ACTOR_AFTER = re.compile(
    r"(?:'s|’s|s)?\s+(?:air\s?|drone\s|missile\s)?(?:strikes?|attacks?|attacked|bombs?|bombing|bombardment|shelling|"
    r"missiles?|drones?|sanctions|embargo|blockade|offensive|Angriffe?n?|Luftangriffe?n?|Beschuss|Sanktionen|"
    r"ataques?|bombardeos?|sanciones|bloqueo|frappes?|attaques?)\b", re.IGNORECASE)
_ACTOR_BEFORE = re.compile(r"(?:blames?|blaming|accuses?|beschuldigt|culpa a|acusa a|accuse)\s+(?:the\s+)?$",
                           re.IGNORECASE)


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
    known = {name: code for name, code in names.items() if code in areas.COUNTRIES or code in areas.REGIONS}
    pattern = "|".join(re.escape(name) for name in sorted(known, key=len, reverse=True))
    return known, re.compile(rf"(?<!\w)(?:{pattern})(?!\w)(?!-(?:led|backed|based|built|made|style|owned|born|installed|controlled|occupied|annexed|held|appointed|linked|aligned)\b)")


_NAMES, _PATTERN = _build()


def find(text: str) -> list[str]:
    """Gebiete, die in einer Schlagzeile als betroffen genannt werden, in der Reihenfolge des Auftretens."""
    found = []
    for match in _PATTERN.finditer(text):
        if _ACTOR_AFTER.match(text, match.end()) or _ACTOR_BEFORE.search(text[: match.start()]):
            continue
        code = _NAMES[match.group(0)]
        if code not in found:
            found.append(code)
    # Ein Bundesland schließt den Staat ein: "Linz, Österreich" zählt nur für das Bundesland.
    return [code for code in found if not any(other != code and areas.parent(other) == code for other in found)]
