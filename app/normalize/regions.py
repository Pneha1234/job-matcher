"""Region shortcuts used by remote eligibility and the location filter."""

EU = {
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE", "IT",
    "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE",
}  # fmt: skip
EEA = EU | {"NO", "IS", "LI"}
EUROPE = EEA | {
    "GB", "CH", "UA", "RS", "BA", "ME", "MK", "AL", "MD", "BY", "XK", "AD", "MC", "SM", "GE", "AM",
}  # fmt: skip
MIDDLE_EAST = {"AE", "SA", "QA", "KW", "BH", "OM", "IL", "JO", "LB", "TR", "EG", "IQ", "IR"}
AFRICA = {
    "ZA", "NG", "KE", "EG", "MA", "GH", "TN", "ET", "UG", "TZ", "RW", "SN", "CI", "DZ", "CM",
}  # fmt: skip
NORTH_AMERICA = {"US", "CA"}
LATAM = {
    "MX", "BR", "AR", "CL", "CO", "PE", "UY", "PY", "BO", "EC", "VE", "CR", "PA", "GT", "DO",
    "SV", "HN", "NI", "CU", "PR",
}  # fmt: skip
SOUTH_ASIA = {"IN", "NP", "BD", "LK", "PK", "BT", "MV"}
APAC = SOUTH_ASIA | {
    "AU", "NZ", "SG", "MY", "ID", "PH", "TH", "VN", "JP", "KR", "CN", "HK", "TW", "KH", "MM",
}  # fmt: skip

# Shortcut name -> countries. The UI's region chips use these keys.
REGIONS: dict[str, set[str]] = {
    "EU": EU,
    "EEA": EEA,
    "Europe": EUROPE,
    "DACH": {"DE", "AT", "CH"},
    "Benelux": {"BE", "NL", "LU"},
    "Nordics": {"SE", "NO", "DK", "FI", "IS"},
    "UK & Ireland": {"GB", "IE"},
    "North America": NORTH_AMERICA,
    "Americas": NORTH_AMERICA | LATAM,
    "LATAM": LATAM,
    "GCC": {"AE", "SA", "QA", "KW", "BH", "OM"},
    "Middle East": MIDDLE_EAST,
    "EMEA": EUROPE | MIDDLE_EAST | AFRICA,
    "Africa": AFRICA,
    "APAC": APAC,
    "Asia": APAC | MIDDLE_EAST,
    "South Asia": SOUTH_ASIA,
}

# Phrases in remote scopes -> region key.
REGION_WORDS = {
    "eu": "EU",
    "european union": "EU",
    "eea": "EEA",
    "europe": "Europe",
    "european": "Europe",
    "dach": "DACH",
    "benelux": "Benelux",
    "nordics": "Nordics",
    "nordic": "Nordics",
    "scandinavia": "Nordics",
    "uk & ireland": "UK & Ireland",
    "north america": "North America",
    "americas": "Americas",
    "latam": "LATAM",
    "latin america": "LATAM",
    "south america": "LATAM",
    "gcc": "GCC",
    "middle east": "Middle East",
    "mena": "Middle East",
    "emea": "EMEA",
    "africa": "Africa",
    "apac": "APAC",
    "asia pacific": "APAC",
    "asia": "Asia",
    "south asia": "South Asia",
}

WORLDWIDE_WORDS = {"worldwide", "anywhere", "global", "globally", "world", "international"}

# City groups offered as filter shortcuts (matched on resolved city names).
CITY_GROUPS: dict[str, set[str]] = {
    "Kathmandu Valley": {"Kathmandu", "Lalitpur", "Patan", "Bhaktapur", "Kirtipur"},
    "India metros": {
        "Bengaluru", "Mumbai", "New Delhi", "Delhi", "Gurugram", "Gurgaon", "Noida", "Pune",
        "Hyderabad", "Chennai", "Kolkata", "Ahmedabad",
    },  # fmt: skip
}


def countries_for(region: str) -> set[str]:
    return REGIONS.get(region, set())
