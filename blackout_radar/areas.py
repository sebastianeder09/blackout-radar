"""Gebiete: Namen (deutsch/englisch), grobe Einwohnerzahlen und Nachbarschaften.

Die Einwohnerzahlen sind gerundet (Millionen) und dienen nur der Größenschwelle
"wie viele Menschen sind grob betroffen". Sie sind keine amtliche Statistik.
"""
from __future__ import annotations

# ISO-3166-1 alpha-2: (deutscher Name, englischer Name, Einwohner in Millionen)
COUNTRIES: dict[str, tuple[str, str, float]] = {
    # Europa
    "AT": ("Österreich", "Austria", 9.2), "DE": ("Deutschland", "Germany", 84.5),
    "CH": ("Schweiz", "Switzerland", 9.0), "IT": ("Italien", "Italy", 58.9),
    "FR": ("Frankreich", "France", 68.4), "ES": ("Spanien", "Spain", 48.8),
    "PT": ("Portugal", "Portugal", 10.6), "NL": ("Niederlande", "Netherlands", 18.0),
    "BE": ("Belgien", "Belgium", 11.8), "LU": ("Luxemburg", "Luxembourg", 0.67),
    "DK": ("Dänemark", "Denmark", 6.0), "SE": ("Schweden", "Sweden", 10.6),
    "NO": ("Norwegen", "Norway", 5.6), "FI": ("Finnland", "Finland", 5.6),
    "IS": ("Island", "Iceland", 0.39), "IE": ("Irland", "Ireland", 5.3),
    "GB": ("Vereinigtes Königreich", "United Kingdom", 68.3), "PL": ("Polen", "Poland", 36.6),
    "CZ": ("Tschechien", "Czech Republic", 10.9), "SK": ("Slowakei", "Slovakia", 5.4),
    "HU": ("Ungarn", "Hungary", 9.6), "SI": ("Slowenien", "Slovenia", 2.1),
    "HR": ("Kroatien", "Croatia", 3.9), "BA": ("Bosnien und Herzegowina", "Bosnia", 3.2),
    "RS": ("Serbien", "Serbia", 6.6), "ME": ("Montenegro", "Montenegro", 0.62),
    "MK": ("Nordmazedonien", "North Macedonia", 1.8), "AL": ("Albanien", "Albania", 2.7),
    "XK": ("Kosovo", "Kosovo", 1.6), "GR": ("Griechenland", "Greece", 10.4),
    "BG": ("Bulgarien", "Bulgaria", 6.4), "RO": ("Rumänien", "Romania", 19.0),
    "MD": ("Moldau", "Moldova", 2.4), "UA": ("Ukraine", "Ukraine", 37.9),
    "BY": ("Belarus", "Belarus", 9.1), "LT": ("Litauen", "Lithuania", 2.9),
    "LV": ("Lettland", "Latvia", 1.9), "EE": ("Estland", "Estonia", 1.4),
    "RU": ("Russland", "Russia", 144.0), "TR": ("Türkei", "Turkey", 85.5),
    "CY": ("Zypern", "Cyprus", 1.3), "MT": ("Malta", "Malta", 0.56),
    "LI": ("Liechtenstein", "Liechtenstein", 0.04), "AD": ("Andorra", "Andorra", 0.08),
    "MC": ("Monaco", "Monaco", 0.04), "SM": ("San Marino", "San Marino", 0.03),
    # Amerika
    "US": ("USA", "United States", 340.0), "CA": ("Kanada", "Canada", 41.0),
    "MX": ("Mexiko", "Mexico", 130.0), "GT": ("Guatemala", "Guatemala", 18.0),
    "BZ": ("Belize", "Belize", 0.4), "HN": ("Honduras", "Honduras", 10.6),
    "SV": ("El Salvador", "El Salvador", 6.3), "NI": ("Nicaragua", "Nicaragua", 6.9),
    "CR": ("Costa Rica", "Costa Rica", 5.1), "PA": ("Panama", "Panama", 4.5),
    "CU": ("Kuba", "Cuba", 11.0), "HT": ("Haiti", "Haiti", 11.8),
    "DO": ("Dominikanische Republik", "Dominican Republic", 11.4), "JM": ("Jamaika", "Jamaica", 2.8),
    "PR": ("Puerto Rico", "Puerto Rico", 3.2), "TT": ("Trinidad und Tobago", "Trinidad and Tobago", 1.5),
    "BS": ("Bahamas", "Bahamas", 0.4), "BB": ("Barbados", "Barbados", 0.28),
    "CO": ("Kolumbien", "Colombia", 52.9), "VE": ("Venezuela", "Venezuela", 28.4),
    "EC": ("Ecuador", "Ecuador", 18.1), "PE": ("Peru", "Peru", 34.2),
    "BO": ("Bolivien", "Bolivia", 12.4), "BR": ("Brasilien", "Brazil", 212.0),
    "PY": ("Paraguay", "Paraguay", 6.9), "UY": ("Uruguay", "Uruguay", 3.4),
    "AR": ("Argentinien", "Argentina", 45.7), "CL": ("Chile", "Chile", 19.8),
    "GY": ("Guyana", "Guyana", 0.83), "SR": ("Suriname", "Suriname", 0.63),
    # Asien
    "CN": ("China", "China", 1410.0), "IN": ("Indien", "India", 1440.0),
    "PK": ("Pakistan", "Pakistan", 247.0), "BD": ("Bangladesch", "Bangladesh", 173.0),
    "LK": ("Sri Lanka", "Sri Lanka", 22.0), "NP": ("Nepal", "Nepal", 29.7),
    "BT": ("Bhutan", "Bhutan", 0.79), "MV": ("Malediven", "Maldives", 0.52),
    "AF": ("Afghanistan", "Afghanistan", 42.0), "IR": ("Iran", "Iran", 90.0),
    "IQ": ("Irak", "Iraq", 45.5), "SY": ("Syrien", "Syria", 24.0),
    "LB": ("Libanon", "Lebanon", 5.8), "JO": ("Jordanien", "Jordan", 11.4),
    "IL": ("Israel", "Israel", 9.8), "PS": ("Palästina", "Palestine", 5.4),
    "SA": ("Saudi-Arabien", "Saudi Arabia", 33.3), "YE": ("Jemen", "Yemen", 39.4),
    "OM": ("Oman", "Oman", 5.0), "AE": ("Vereinigte Arabische Emirate", "United Arab Emirates", 10.5),
    "QA": ("Katar", "Qatar", 2.9), "BH": ("Bahrain", "Bahrain", 1.6),
    "KW": ("Kuwait", "Kuwait", 4.9), "KZ": ("Kasachstan", "Kazakhstan", 20.3),
    "UZ": ("Usbekistan", "Uzbekistan", 36.4), "TM": ("Turkmenistan", "Turkmenistan", 7.4),
    "KG": ("Kirgisistan", "Kyrgyzstan", 7.1), "TJ": ("Tadschikistan", "Tajikistan", 10.4),
    "MN": ("Mongolei", "Mongolia", 3.5), "JP": ("Japan", "Japan", 124.0),
    "KR": ("Südkorea", "South Korea", 51.7), "KP": ("Nordkorea", "North Korea", 26.3),
    "TW": ("Taiwan", "Taiwan", 23.4), "HK": ("Hongkong", "Hong Kong", 7.5),
    "MO": ("Macau", "Macau", 0.7), "VN": ("Vietnam", "Vietnam", 100.0),
    "TH": ("Thailand", "Thailand", 71.7), "MM": ("Myanmar", "Myanmar", 54.5),
    "KH": ("Kambodscha", "Cambodia", 17.4), "LA": ("Laos", "Laos", 7.7),
    "MY": ("Malaysia", "Malaysia", 35.0), "SG": ("Singapur", "Singapore", 5.9),
    "ID": ("Indonesien", "Indonesia", 281.0), "PH": ("Philippinen", "Philippines", 115.0),
    "BN": ("Brunei", "Brunei", 0.46), "TL": ("Timor-Leste", "Timor-Leste", 1.4),
    "GE": ("Georgien", "Georgia", 3.7), "AM": ("Armenien", "Armenia", 3.0),
    "AZ": ("Aserbaidschan", "Azerbaijan", 10.2),
    # Afrika
    "EG": ("Ägypten", "Egypt", 114.0), "LY": ("Libyen", "Libya", 7.3),
    "TN": ("Tunesien", "Tunisia", 12.2), "DZ": ("Algerien", "Algeria", 46.2),
    "MA": ("Marokko", "Morocco", 37.7), "SD": ("Sudan", "Sudan", 50.0),
    "SS": ("Südsudan", "South Sudan", 11.5), "ET": ("Äthiopien", "Ethiopia", 129.0),
    "ER": ("Eritrea", "Eritrea", 3.5), "DJ": ("Dschibuti", "Djibouti", 1.2),
    "SO": ("Somalia", "Somalia", 18.4), "KE": ("Kenia", "Kenya", 55.3),
    "UG": ("Uganda", "Uganda", 48.7), "TZ": ("Tansania", "Tanzania", 66.6),
    "RW": ("Ruanda", "Rwanda", 14.0), "BI": ("Burundi", "Burundi", 13.6),
    "CD": ("DR Kongo", "DR Congo", 105.8), "CG": ("Kongo", "Republic of the Congo", 6.2),
    "GA": ("Gabun", "Gabon", 2.5), "GQ": ("Äquatorialguinea", "Equatorial Guinea", 1.8),
    "CM": ("Kamerun", "Cameroon", 28.4), "CF": ("Zentralafrikanische Republik", "Central African Republic", 5.2),
    "TD": ("Tschad", "Chad", 19.3), "NE": ("Niger", "Niger", 26.2),
    "NG": ("Nigeria", "Nigeria", 227.0), "BJ": ("Benin", "Benin", 14.1),
    "TG": ("Togo", "Togo", 9.3), "GH": ("Ghana", "Ghana", 33.8),
    "CI": ("Elfenbeinküste", "Ivory Coast", 31.2), "BF": ("Burkina Faso", "Burkina Faso", 23.0),
    "ML": ("Mali", "Mali", 23.8), "SN": ("Senegal", "Senegal", 18.1),
    "GM": ("Gambia", "Gambia", 2.7), "GW": ("Guinea-Bissau", "Guinea-Bissau", 2.2),
    "GN": ("Guinea", "Guinea", 14.4), "SL": ("Sierra Leone", "Sierra Leone", 8.5),
    "LR": ("Liberia", "Liberia", 5.5), "MR": ("Mauretanien", "Mauritania", 5.0),
    "CV": ("Kap Verde", "Cape Verde", 0.52), "ST": ("São Tomé und Príncipe", "Sao Tome and Principe", 0.23),
    "AO": ("Angola", "Angola", 36.7), "ZM": ("Sambia", "Zambia", 20.7),
    "ZW": ("Simbabwe", "Zimbabwe", 16.3), "MW": ("Malawi", "Malawi", 21.1),
    "MZ": ("Mosambik", "Mozambique", 33.6), "NA": ("Namibia", "Namibia", 3.0),
    "BW": ("Botswana", "Botswana", 2.5), "ZA": ("Südafrika", "South Africa", 63.0),
    "LS": ("Lesotho", "Lesotho", 2.3), "SZ": ("Eswatini", "Eswatini", 1.2),
    "MG": ("Madagaskar", "Madagascar", 31.2), "MU": ("Mauritius", "Mauritius", 1.26),
    "SC": ("Seychellen", "Seychelles", 0.12), "KM": ("Komoren", "Comoros", 0.85),
    # Ozeanien
    "AU": ("Australien", "Australia", 26.7), "NZ": ("Neuseeland", "New Zealand", 5.2),
    "PG": ("Papua-Neuguinea", "Papua New Guinea", 10.4), "FJ": ("Fidschi", "Fiji", 0.92),
    "SB": ("Salomonen", "Solomon Islands", 0.8), "VU": ("Vanuatu", "Vanuatu", 0.32),
    "WS": ("Samoa", "Samoa", 0.22), "TO": ("Tonga", "Tonga", 0.1),
}

# Österreichische Bundesländer nach ISO 3166-2:AT
REGIONS: dict[str, tuple[str, str, float]] = {
    "AT-1": ("Burgenland", "Burgenland", 0.30), "AT-2": ("Kärnten", "Carinthia", 0.57),
    "AT-3": ("Niederösterreich", "Lower Austria", 1.72), "AT-4": ("Oberösterreich", "Upper Austria", 1.53),
    "AT-5": ("Salzburg", "Salzburg", 0.57), "AT-6": ("Steiermark", "Styria", 1.27),
    "AT-7": ("Tirol", "Tyrol", 0.78), "AT-8": ("Vorarlberg", "Vorarlberg", 0.41),
    "AT-9": ("Wien", "Vienna", 2.0),
}

# Sondergebiete
SPECIAL: dict[str, tuple[str, str, float]] = {
    "EU-CE": ("Verbundnetz Kontinentaleuropa", "Continental Europe grid", 450.0),
}

_PAIRS = [
    ("AT", "DE"), ("AT", "CZ"), ("AT", "SK"), ("AT", "HU"), ("AT", "SI"), ("AT", "IT"), ("AT", "CH"), ("AT", "LI"),
    ("DE", "DK"), ("DE", "PL"), ("DE", "CZ"), ("DE", "CH"), ("DE", "FR"), ("DE", "LU"), ("DE", "BE"), ("DE", "NL"),
    ("CH", "FR"), ("CH", "IT"), ("CH", "LI"), ("IT", "FR"), ("IT", "SI"), ("IT", "SM"),
    ("FR", "ES"), ("FR", "AD"), ("FR", "MC"), ("FR", "LU"), ("FR", "BE"), ("ES", "PT"), ("ES", "AD"), ("ES", "MA"),
    ("BE", "LU"), ("BE", "NL"), ("DK", "SE"), ("DK", "NO"), ("SE", "NO"), ("SE", "FI"), ("NO", "FI"), ("FI", "EE"),
    ("PL", "CZ"), ("PL", "SK"), ("PL", "UA"), ("PL", "BY"), ("PL", "LT"), ("CZ", "SK"),
    ("SK", "UA"), ("SK", "HU"), ("HU", "UA"), ("HU", "RO"), ("HU", "RS"), ("HU", "HR"), ("HU", "SI"),
    ("SI", "HR"), ("HR", "RS"), ("HR", "BA"), ("HR", "ME"), ("BA", "RS"), ("BA", "ME"),
    ("RS", "RO"), ("RS", "BG"), ("RS", "MK"), ("RS", "XK"), ("RS", "ME"), ("ME", "XK"), ("ME", "AL"),
    ("XK", "AL"), ("XK", "MK"), ("MK", "AL"), ("MK", "GR"), ("MK", "BG"), ("AL", "GR"),
    ("GR", "BG"), ("GR", "TR"), ("BG", "RO"), ("BG", "TR"), ("RO", "UA"), ("RO", "MD"), ("MD", "UA"),
    ("UA", "BY"), ("UA", "RU"), ("BY", "LT"), ("BY", "LV"), ("BY", "RU"), ("LT", "LV"), ("LV", "EE"),
    ("LV", "RU"), ("EE", "RU"), ("GB", "IE"),
]
NEIGHBOURS: dict[str, set[str]] = {}
for _a, _b in _PAIRS:
    NEIGHBOURS.setdefault(_a, set()).add(_b)
    NEIGHBOURS.setdefault(_b, set()).add(_a)


def _entry(area: str):
    return COUNTRIES.get(area) or REGIONS.get(area) or SPECIAL.get(area)


def parent(area: str) -> str:
    """Staat, zu dem ein Gebiet gehört (Bundesland AT-4 gehört zu AT)."""
    if area in REGIONS:
        return area.split("-", 1)[0]
    return area


def name(area: str) -> str:
    entry = _entry(area)
    return entry[0] if entry else area


def name_en(area: str) -> str:
    entry = _entry(area)
    return entry[1] if entry else area


def population(area: str) -> int:
    entry = _entry(area)
    return int(entry[2] * 1_000_000) if entry else 0


def related(a: str, b: str) -> bool:
    """Wahr, wenn zwei Gebiete im selben Staat liegen oder die Staaten benachbart sind."""
    pa, pb = parent(a), parent(b)
    return pa == pb or pb in NEIGHBOURS.get(pa, ())


def search_names(area: str) -> list[str]:
    """Namen für die Mediensuche (deutsch und englisch, ohne Dubletten)."""
    entry = _entry(area)
    if not entry:
        return [area]
    return list(dict.fromkeys([entry[0], entry[1]]))
