"""
International Cost of Capital App
Compares a project's cost of equity, cost of debt and WACC in U.S. dollars and in the
currency of a selected country, following Prof. Sergio Rebelo's method
(Kellogg International Finance, "Designing cost of capital app", slides 572 to 587).

Data sources (fetched live, cached for 6 hours, refresh button clears the cache):
  * Unlevered industry betas ........ Aswath Damodaran, betas.xls (U.S. industries)
  * BBB (Baa2) USD borrowing spread .. Aswath Damodaran, ratings.html (large non-financial firms)
  * Corporate tax rates ............. OECD Corporate Tax Statistics, combined statutory CIT rate
  * 10-year government bond yields .. Trading Economics country bond pages
"""

import io
import re
import datetime as dt

import altair as alt
import numpy as np
import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup

# ==== CORE (pure Python, no Streamlit calls) ==================================

BETAS_XLS_URL = "https://pages.stern.nyu.edu/~adamodar/pc/datasets/betas.xls"
BETAS_HTML_URL = "https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/Betas.html"
RATINGS_URL = "https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/ratings.html"
OECD_PAGE_URL = (
    "https://www.oecd.org/en/publications/corporate-tax-statistics-2024_9c27d6e8-en/"
    "full-report/statutory-corporate-income-tax-rates_440f9286.html"
)
OECD_API_URL = (
    "https://sdmx.oecd.org/public/rest/data/OECD.CTP.TPS,DSD_TAX_CIT@DF_CIT,/all"
    "?startPeriod=2022&format=csvfilewithlabels"
)
TE_BONDS_URL = "https://tradingeconomics.com/bonds"
TE_COUNTRY_URL = "https://tradingeconomics.com/{slug}/government-bond-yield"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

DEFAULT_INDUSTRY = "Software (System & Application)"
DEFAULT_COUNTRY = "United States"

# name: (Trading Economics slug, ISO3 code used by OECD, currency code, currency name)
COUNTRIES = {
    "United States": ("united-states", "USA", "USD", "U.S. dollars"),
    "Australia": ("australia", "AUS", "AUD", "Australian dollars"),
    "Austria": ("austria", "AUT", "EUR", "euros"),
    "Belgium": ("belgium", "BEL", "EUR", "euros"),
    "Brazil": ("brazil", "BRA", "BRL", "Brazilian reais"),
    "Canada": ("canada", "CAN", "CAD", "Canadian dollars"),
    "Chile": ("chile", "CHL", "CLP", "Chilean pesos"),
    "China": ("china", "CHN", "CNY", "Chinese yuan"),
    "Colombia": ("colombia", "COL", "COP", "Colombian pesos"),
    "Croatia": ("croatia", "HRV", "EUR", "euros"),
    "Czech Republic": ("czech-republic", "CZE", "CZK", "Czech koruna"),
    "Denmark": ("denmark", "DNK", "DKK", "Danish kroner"),
    "Finland": ("finland", "FIN", "EUR", "euros"),
    "France": ("france", "FRA", "EUR", "euros"),
    "Germany": ("germany", "DEU", "EUR", "euros"),
    "Greece": ("greece", "GRC", "EUR", "euros"),
    "Hong Kong": ("hong-kong", "HKG", "HKD", "Hong Kong dollars"),
    "Hungary": ("hungary", "HUN", "HUF", "Hungarian forint"),
    "Iceland": ("iceland", "ISL", "ISK", "Icelandic kronur"),
    "India": ("india", "IND", "INR", "Indian rupees"),
    "Indonesia": ("indonesia", "IDN", "IDR", "Indonesian rupiah"),
    "Ireland": ("ireland", "IRL", "EUR", "euros"),
    "Israel": ("israel", "ISR", "ILS", "Israeli shekels"),
    "Italy": ("italy", "ITA", "EUR", "euros"),
    "Japan": ("japan", "JPN", "JPY", "Japanese yen"),
    "Kenya": ("kenya", "KEN", "KES", "Kenyan shillings"),
    "Lithuania": ("lithuania", "LTU", "EUR", "euros"),
    "Malaysia": ("malaysia", "MYS", "MYR", "Malaysian ringgit"),
    "Mexico": ("mexico", "MEX", "MXN", "Mexican pesos"),
    "Netherlands": ("netherlands", "NLD", "EUR", "euros"),
    "New Zealand": ("new-zealand", "NZL", "NZD", "New Zealand dollars"),
    "Nigeria": ("nigeria", "NGA", "NGN", "Nigerian naira"),
    "Norway": ("norway", "NOR", "NOK", "Norwegian kroner"),
    "Pakistan": ("pakistan", "PAK", "PKR", "Pakistani rupees"),
    "Peru": ("peru", "PER", "PEN", "Peruvian soles"),
    "Philippines": ("philippines", "PHL", "PHP", "Philippine pesos"),
    "Poland": ("poland", "POL", "PLN", "Polish zloty"),
    "Portugal": ("portugal", "PRT", "EUR", "euros"),
    "Romania": ("romania", "ROU", "RON", "Romanian lei"),
    "Singapore": ("singapore", "SGP", "SGD", "Singapore dollars"),
    "Slovakia": ("slovakia", "SVK", "EUR", "euros"),
    "Slovenia": ("slovenia", "SVN", "EUR", "euros"),
    "South Africa": ("south-africa", "ZAF", "ZAR", "South African rand"),
    "South Korea": ("south-korea", "KOR", "KRW", "Korean won"),
    "Spain": ("spain", "ESP", "EUR", "euros"),
    "Sweden": ("sweden", "SWE", "SEK", "Swedish kronor"),
    "Switzerland": ("switzerland", "CHE", "CHF", "Swiss francs"),
    "Thailand": ("thailand", "THA", "THB", "Thai baht"),
    "Turkey": ("turkey", "TUR", "TRY", "Turkish lira"),
    "United Kingdom": ("united-kingdom", "GBR", "GBP", "British pounds"),
    "Vietnam": ("vietnam", "VNM", "VND", "Vietnamese dong"),
    "Zambia": ("zambia", "ZMB", "ZMW", "Zambian kwacha"),
}

# ---- Backup snapshots (used ONLY if a live fetch fails; clearly labeled in the app) ----
SNAPSHOT_YIELD_DATE = "Nov 13, 2026"
SNAPSHOT_YIELDS = {  # Trading Economics 10Y yields, percent
    "United States": 5.1450, "United Kingdom": 5.3377, "Japan": 2.8616, "Australia": 5.1290,
    "Germany": 3.3762, "Brazil": 15.3350, "India": 7.3120, "Canada": 3.8560, "Italy": 4.4370,
    "France": 4.9210, "South Africa": 8.6750, "China": 1.6181, "Switzerland": 0.5626,
    "Mexico": 9.3080, "Netherlands": 3.4768, "New Zealand": 4.7462, "Portugal": 3.8186,
    "South Korea": 3.9870, "Spain": 3.9442, "Greece": 4.2636, "Turkey": 33.5200,
    "Finland": 3.7611, "Lithuania": 4.3250, "Norway": 4.3842, "Poland": 6.3350,
    "Romania": 7.1200, "Slovakia": 4.3050, "Slovenia": 3.9140, "Sweden": 3.0980,
    "Hungary": 5.5249, "Iceland": 6.8100, "Ireland": 3.5391, "Austria": 3.6096,
    "Belgium": 4.3545, "Croatia": 3.8668, "Czech Republic": 5.2222, "Denmark": 3.1693,
    "Peru": 6.2600, "Chile": 6.0100, "Colombia": 12.6980, "Singapore": 2.3296,
    "Thailand": 1.9950, "Vietnam": 4.5726, "Hong Kong": 3.9940, "Indonesia": 7.6070,
    "Israel": 4.1830, "Malaysia": 3.8628, "Pakistan": 12.6040, "Philippines": 7.7670,
    "Zambia": 14.7400, "Kenya": 12.5000, "Nigeria": 16.5980,
}
SNAPSHOT_TAX = {  # OECD combined statutory CIT rate, percent, (year)
    "USA": (25.5285, 2026), "GBR": (25, 2026), "JPN": (29.74, 2026), "AUS": (30, 2026),
    "DEU": (30.133026, 2026), "BRA": (34, 2026), "IND": (25.17, 2026), "CAN": (26, 2026),
    "ITA": (27.81, 2026), "FRA": (36.13, 2026), "ZAF": (27, 2026), "CHN": (25, 2026),
    "CHE": (19.471871, 2026), "MEX": (30, 2026), "NLD": (25.8, 2026), "NZL": (28, 2026),
    "PRT": (29.5, 2026), "KOR": (27.5, 2026), "ESP": (25, 2026), "GRC": (22, 2026),
    "TUR": (25, 2025), "FIN": (20, 2026), "LTU": (17, 2026), "NOR": (22, 2026),
    "POL": (19, 2026), "ROU": (16, 2026), "SVK": (24, 2026), "SVN": (22, 2026),
    "SWE": (20.6, 2026), "HUN": (9, 2026), "ISL": (20, 2026), "IRL": (12.5, 2026),
    "AUT": (23, 2026), "BEL": (25, 2026), "HRV": (18, 2026), "CZE": (21, 2026),
    "DNK": (22, 2026), "PER": (29.5, 2026), "CHL": (27, 2026), "COL": (35, 2025),
    "SGP": (17, 2026), "THA": (20, 2026), "VNM": (20, 2026), "HKG": (16.5, 2026),
    "IDN": (22, 2026), "ISR": (23, 2025), "MYS": (24, 2026), "PAK": (29, 2026),
    "PHL": (25, 2026), "ZMB": (30, 2026), "KEN": (30, 2026), "NGA": (30, 2026),
}
SNAPSHOT_BBB = (1.11, "January 2026")
SNAPSHOT_BETA_DATE = "January 2026"
SNAPSHOT_BETAS = {
    "Advertising": 0.93, "Aerospace/Defense": 0.85, "Air Transport": 0.70, "Apparel": 0.76,
    "Auto & Truck": 1.27, "Auto Parts": 1.02, "Bank (Money Center)": 0.34,
    "Banks (Regional)": 0.29, "Beverage (Alcoholic)": 0.61, "Beverage (Soft)": 0.56,
    "Broadcasting": 0.29, "Brokerage & Investment Banking": 0.58, "Building Materials": 0.93,
    "Business & Consumer Services": 0.77, "Cable TV": 0.35, "Chemical (Basic)": 0.58,
    "Chemical (Diversified)": 0.37, "Chemical (Specialty)": 0.79, "Coal & Related Energy": 1.02,
    "Computer Services": 0.92, "Computers/Peripherals": 1.31, "Construction Supplies": 1.02,
    "Diversified": 0.79, "Drugs (Biotechnology)": 1.03, "Drugs (Pharmaceutical)": 0.89,
    "Education": 0.66, "Electrical Equipment": 1.15, "Electronics (Consumer & Office)": 0.83,
    "Electronics (General)": 0.90, "Engineering/Construction": 1.09, "Entertainment": 0.74,
    "Environmental & Waste Services": 0.81, "Farming/Agriculture": 0.81,
    "Financial Svcs. (Non-bank & Insurance)": 0.32, "Food Processing": 0.46,
    "Food Wholesalers": 0.64, "Furn/Home Furnishings": 0.62, "Green & Renewable Energy": 0.46,
    "Healthcare Products": 0.83, "Healthcare Support Services": 0.69,
    "Heathcare Information and Technology": 0.99, "Homebuilding": 0.78,
    "Hospitals/Healthcare Facilities": 0.55, "Hotel/Gaming": 0.83, "Household Products": 0.72,
    "Information Services": 0.74, "Insurance (General)": 0.56, "Insurance (Life)": 0.43,
    "Insurance (Prop/Cas.)": 0.44, "Investments & Asset Management": 0.53, "Machinery": 0.87,
    "Metals & Mining": 0.96, "Office Equipment & Services": 0.98, "Oil/Gas (Integrated)": 0.27,
    "Oil/Gas (Production and Exploration)": 0.56, "Oil/Gas Distribution": 0.47,
    "Oilfield Svcs/Equip.": 0.74, "Packaging & Container": 0.72, "Paper/Forest Products": 0.72,
    "Power": 0.31, "Precious Metals": 0.79, "Publishing & Newspapers": 0.48, "R.E.I.T.": 0.39,
    "Real Estate (Development)": 0.48, "Real Estate (General/Diversified)": 0.58,
    "Real Estate (Operations & Services)": 0.81, "Recreation": 0.70, "Reinsurance": 0.44,
    "Restaurant/Dining": 0.77, "Retail (Automotive)": 0.70, "Retail (Building Supply)": 1.31,
    "Retail (Distributors)": 0.78, "Retail (General)": 0.76, "Retail (Grocery and Food)": 0.80,
    "Retail (REITs)": 0.44, "Retail (Special Lines)": 0.95, "Rubber& Tires": 0.14,
    "Semiconductor": 1.49, "Semiconductor Equip": 1.35, "Shipbuilding & Marine": 0.64,
    "Shoe": 0.93, "Software (Entertainment)": 1.01, "Software (Internet)": 1.55,
    "Software (System & Application)": 1.23, "Steel": 0.90, "Telecom (Wireless)": 0.39,
    "Telecom. Equipment": 0.86, "Telecom. Services": 0.37, "Tobacco": 0.68,
    "Transportation": 0.68, "Transportation (Railroads)": 0.81, "Trucking": 0.85,
    "Utility (General)": 0.15, "Utility (Water)": 0.28,
}

MONTHS = ("January|February|March|April|May|June|July|August|September|"
          "October|November|December")


def _get(url, timeout=30):
    r = requests.get(url, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    return r


def _to_float(x):
    """Parse '1.11%', '0.93', 1.2 etc. into a float (no % scaling). None if impossible."""
    if x is None:
        return None
    if isinstance(x, (int, float, np.floating)) and not pd.isna(x):
        return float(x)
    m = re.search(r"-?\d+(?:\.\d+)?", str(x).replace(",", ""))
    return float(m.group()) if m else None


def _damodaran_date(html_text):
    m = re.search(r"as of\s+((?:%s)\s+\d{4})" % MONTHS, html_text, re.I)
    return m.group(1) if m else None


def parse_betas_excel(content):
    """Return (DataFrame[Industry, Firms, Unlevered beta], date_text) from betas.xls bytes."""
    sheets = pd.read_excel(io.BytesIO(content), sheet_name=None, header=None)
    for _, raw in sheets.items():
        hdr_idx = None
        for i in range(min(len(raw), 40)):
            if any(str(v).strip().lower() == "industry name" for v in raw.iloc[i].values):
                hdr_idx = i
                break
        if hdr_idx is None:
            continue
        header = [str(v).strip() for v in raw.iloc[hdr_idx].values]
        low = [h.lower() for h in header]
        c_ind = low.index("industry name")
        c_beta = next(i for i, h in enumerate(low) if h == "unlevered beta")
        c_n = next((i for i, h in enumerate(low) if h.startswith("number of firms")), None)
        body = raw.iloc[hdr_idx + 1:]
        rows = []
        for _, r in body.iterrows():
            name = r.iloc[c_ind]
            beta = _to_float(r.iloc[c_beta])
            if pd.isna(name) or beta is None or str(name).strip() == "":
                continue
            rows.append({
                "Industry": str(name).strip(),
                "Firms": _to_float(r.iloc[c_n]) if c_n is not None else None,
                "Unlevered beta": beta,
            })
        df = pd.DataFrame(rows)
        # Date: look above the header for a datetime cell or a cell mentioning "date"
        date_txt = None
        for i in range(hdr_idx):
            vals = list(raw.iloc[i].values)
            for j, v in enumerate(vals):
                if isinstance(v, (dt.datetime, pd.Timestamp)):
                    date_txt = pd.Timestamp(v).strftime("%B %d, %Y")
                elif isinstance(v, str) and "date" in v.lower():
                    after = [w for w in vals[j + 1:] if not pd.isna(w)]
                    if after:
                        w = after[0]
                        if isinstance(w, (dt.datetime, pd.Timestamp)):
                            date_txt = pd.Timestamp(w).strftime("%B %d, %Y")
                        elif isinstance(w, (int, float)) and 20000 < w < 80000:
                            date_txt = (dt.datetime(1899, 12, 30) + dt.timedelta(days=float(w))).strftime("%B %d, %Y")
                        else:
                            date_txt = str(w)
                    else:
                        mm = re.search(r"(%s)\s+\d{1,2},?\s+\d{4}|(%s)\s+\d{4}" % (MONTHS, MONTHS), v)
                        if mm:
                            date_txt = mm.group(0)
                if date_txt:
                    break
            if date_txt:
                break
        if len(df) > 20:
            return df, date_txt
    raise ValueError("Could not find the 'Industry Name' table in betas.xls")


def parse_betas_html(html_text):
    soup = BeautifulSoup(html_text, "lxml")
    rows = []
    header = None
    for tr in soup.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        if not cells:
            continue
        if header is None and any(c.lower() == "industry name" for c in cells):
            header = [c.lower() for c in cells]
            continue
        if header and len(cells) >= len(header) - 1:
            try:
                b = _to_float(cells[header.index("unlevered beta")])
                n = _to_float(cells[header.index("number of firms")])
            except ValueError:
                continue
            if b is not None and cells[0]:
                rows.append({"Industry": cells[0], "Firms": n, "Unlevered beta": b})
    if len(rows) < 20:
        raise ValueError("Beta table not found in Betas.html")
    return pd.DataFrame(rows), _damodaran_date(html_text)


def parse_bbb_spread(html_text):
    """Spread (in percent) on the first Baa2/BBB row = large non-financial service firms."""
    soup = BeautifulSoup(html_text, "lxml")
    for tr in soup.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        for i, c in enumerate(cells):
            if c.replace(" ", "").upper() == "BAA2/BBB":
                for nxt in cells[i + 1:]:
                    v = _to_float(nxt)
                    if v is not None:
                        return v, _damodaran_date(html_text)
    raise ValueError("Baa2/BBB row not found")


def parse_oecd_csv(text):
    """Latest combined statutory CIT rate per ISO3 -> (percent, year)."""
    df = pd.read_csv(io.StringIO(text))
    df = df[(df["MEASURE"] == "CIT_C") & (df["TARGETING"] == "ST")]
    df = df.dropna(subset=["OBS_VALUE"])
    df["TIME_PERIOD"] = df["TIME_PERIOD"].astype(int)
    df = df.sort_values("TIME_PERIOD").groupby("REF_AREA").tail(1)
    return {r.REF_AREA: (float(r.OBS_VALUE), int(r.TIME_PERIOD)) for r in df.itertuples()}


def parse_te_country_page(html_text):
    """Return (yield_percent, date_text) from a Trading Economics government-bond-yield page."""
    soup = BeautifulSoup(html_text, "lxml")
    value = None
    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            tds = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
            if tds and re.search(r"\b10Y\b", tds[0]):
                for t in tds[1:]:
                    v = _to_float(t)
                    if v is not None:
                        value = v
                        break
            if value is not None:
                break
        if value is not None:
            break
    meta = soup.find("meta", attrs={"name": "description"})
    desc = meta.get("content", "") if meta else ""
    if value is None:
        m = re.search(r"10Y[^%]*?\bto\s+(-?\d+(?:\.\d+)?)%", desc)
        if m:
            value = float(m.group(1))
    if value is None:
        raise ValueError("10Y yield not found on page")
    m = re.search(r"on\s+((?:%s)\s+\d{1,2},\s+\d{4})" % MONTHS, desc)
    return value, (m.group(1) if m else None)


def compute(beta_u, tax, d, erp, rf_us, rf_fx, s_usd, s_fx_override=None):
    """All rates as decimals. Implements Prof. Rebelo's app method (slides 576 to 585)."""
    de = d / (1 - d)                                   # D/E = d/(1-d)
    beta_e = beta_u * (1 + (1 - tax) * de)             # relever
    factor = (1 + rf_fx) / (1 + rf_us)                 # F = (1+Rf*)/(1+Rf)
    re_usd = rf_us + beta_e * erp                      # CAPM in USD
    rd_usd = rf_us + s_usd                             # USD borrowing rate
    re_fx = (1 + re_usd) * factor - 1                  # (1+Re*) = (1+Re) F
    if s_fx_override is None:
        rd_fx = (1 + rd_usd) * factor - 1              # same factor on gross borrowing rate
        s_fx = rd_fx - rf_fx                           # = s * F
    else:
        s_fx = s_fx_override
        rd_fx = rf_fx + s_fx
    out = {
        "de": de, "beta_e": beta_e, "factor": factor, "dep": factor - 1,
        "re_usd": re_usd, "re_fx": re_fx,
        "s_usd": s_usd, "s_fx": s_fx,
        "rd_usd": rd_usd, "rd_fx": rd_fx,
        "rd_at_usd": rd_usd * (1 - tax), "rd_at_fx": rd_fx * (1 - tax),
    }
    out["wacc_usd"] = (1 - d) * re_usd + d * out["rd_at_usd"]
    out["wacc_fx"] = (1 - d) * re_fx + d * out["rd_at_fx"]
    return out


def run_checks(beta_u, tax, d, erp, rf_us, rf_fx, s_usd):
    """The four verification tests from the assignment, run live on the current inputs."""
    checks = []
    col = compute(0.80, 0.35, 0.30, 0.065, 0.04, 0.12, 0.015)
    ok = abs(col["wacc_usd"] - 0.085265) < 5e-7 and abs(col["wacc_fx"] - 0.160670) < 5e-7 \
        and abs(col["re_fx"] - 0.1916) < 5e-7 and abs(col["rd_fx"] - 0.136154) < 5e-7
    checks.append(("Reproduces the class Colombia example (USD WACC 8.5265%, COP WACC 16.0670%)",
                   ok, f"USD WACC {col['wacc_usd']:.4%}, COP WACC {col['wacc_fx']:.4%}, "
                       f"COP equity {col['re_fx']:.4%}, COP debt {col['rd_fx']:.4%}"))
    eq = compute(beta_u, tax, d, erp, rf_us, rf_us, s_usd)
    ok = all(abs(eq[a] - eq[b]) < 1e-12 for a, b in
             [("re_usd", "re_fx"), ("rd_usd", "rd_fx"), ("wacc_usd", "wacc_fx")])
    checks.append(("Equal government yields give equal results in both currencies "
                   "(spread override off)", ok,
                   f"WACC {eq['wacc_usd']:.4%} vs {eq['wacc_fx']:.4%}"))
    z = compute(beta_u, tax, 0.0, erp, rf_us, rf_fx, s_usd)
    ok = abs(z["wacc_usd"] - z["re_usd"]) < 1e-12 and abs(z["wacc_fx"] - z["re_fx"]) < 1e-12
    checks.append(("Zero debt makes WACC equal to the cost of equity", ok,
                   f"USD {z['wacc_usd']:.4%} = {z['re_usd']:.4%}; "
                   f"foreign {z['wacc_fx']:.4%} = {z['re_fx']:.4%}"))
    a = compute(beta_u, tax, d, erp, rf_us, rf_fx, s_usd)
    b = compute(beta_u, tax, d, erp, rf_us, rf_fx, s_usd, s_fx_override=0.10)
    ok = all(abs(a[k] - b[k]) < 1e-12 for k in ("re_usd", "rd_usd", "rd_at_usd", "wacc_usd"))
    checks.append(("Overriding the foreign-currency spread leaves USD results unchanged", ok,
                   f"USD WACC {a['wacc_usd']:.4%} (auto) vs {b['wacc_usd']:.4%} (10% override); "
                   f"foreign WACC moves {a['wacc_fx']:.4%} to {b['wacc_fx']:.4%}"))
    return checks


# ==== UI =======================================================================

st.set_page_config(page_title="International Cost of Capital", page_icon="🌍", layout="wide")

USD_COLOR = "#2a78d6"
FX_COLOR = "#eb6834"

st.markdown(
    f"""
<style>
.block-container {{padding-top: 2rem; max-width: 1250px;}}
.hero {{background: linear-gradient(120deg,#0f2a4a 0%,#1d4f86 60%,#2a78d6 100%);
        color: white; padding: 1.4rem 1.6rem; border-radius: 16px; margin-bottom: 1rem;}}
.hero h1 {{color: white; font-size: 2.0rem; margin: 0 0 .3rem 0;}}
.hero p {{color: #e6eefb; margin: 0; font-size: 1.02rem;}}
.card {{border-radius: 16px; padding: 1.1rem 1.3rem; background: var(--secondary-background-color);
        border-top: 6px solid var(--accent); height: 100%;}}
.card .label {{font-size: .85rem; letter-spacing: .04em; text-transform: uppercase; opacity: .75;}}
.card .big {{font-size: 2.6rem; font-weight: 700; line-height: 1.1; margin: .2rem 0;}}
.card .sub {{font-size: .95rem; opacity: .85;}}
.card table {{width: 100%; margin-top: .6rem; font-size: .95rem; border-collapse: collapse;}}
.card td {{padding: .25rem 0; border: none;}}
.card td.v {{text-align: right; font-weight: 600;}}
.pill {{display:inline-block; padding: .1rem .55rem; border-radius: 999px; font-size: .78rem;
        font-weight: 600; margin-left: .3rem;}}
.live {{background:#dff5e1; color:#11631b;}}
.snap {{background:#fff1d6; color:#7a4b00;}}
.man {{background:#e6e3fb; color:#3b2ea3;}}
.note {{border-left: 4px solid {FX_COLOR}; background: var(--secondary-background-color);
        padding: .8rem 1rem; border-radius: 8px; margin: .8rem 0;}}
</style>
""",
    unsafe_allow_html=True,
)


# ---- Cached fetchers --------------------------------------------------------------
@st.cache_data(ttl=6 * 3600, show_spinner=False)
def load_betas():
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    try:
        df, date_txt = parse_betas_excel(_get(BETAS_XLS_URL).content)
        if not date_txt:
            try:
                date_txt = _damodaran_date(_get(BETAS_HTML_URL).text)
            except Exception:
                pass
        return {"df": df, "date": date_txt or "latest file", "status": "live",
                "src": "Damodaran betas.xls", "url": BETAS_XLS_URL, "fetched": stamp, "err": None}
    except Exception as e1:
        try:
            df, date_txt = parse_betas_html(_get(BETAS_HTML_URL).text)
            return {"df": df, "date": date_txt or "latest page", "status": "live",
                    "src": "Damodaran Betas.html (same data as betas.xls)", "url": BETAS_HTML_URL,
                    "fetched": stamp, "err": f"xls read failed: {e1}"}
        except Exception as e2:
            df = pd.DataFrame({"Industry": list(SNAPSHOT_BETAS), "Firms": None,
                               "Unlevered beta": list(SNAPSHOT_BETAS.values())})
            return {"df": df, "date": SNAPSHOT_BETA_DATE, "status": "snapshot",
                    "src": "Damodaran (built-in backup copy)", "url": BETAS_XLS_URL,
                    "fetched": stamp, "err": f"{e1} / {e2}"}


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def load_bbb():
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    try:
        r = _get(RATINGS_URL)
        text = r.content.decode("utf-8", errors="ignore")
        v, date_txt = parse_bbb_spread(text)
        return {"value": v / 100, "date": date_txt or "latest page", "status": "live",
                "fetched": stamp, "err": None}
    except Exception as e:
        return {"value": SNAPSHOT_BBB[0] / 100, "date": SNAPSHOT_BBB[1], "status": "snapshot",
                "fetched": stamp, "err": str(e)}


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def load_tax():
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    try:
        rates = parse_oecd_csv(_get(OECD_API_URL, timeout=60).text)
        if "USA" not in rates:
            raise ValueError("USA missing from OECD response")
        return {"rates": rates, "status": "live", "fetched": stamp, "err": None}
    except Exception as e:
        return {"rates": SNAPSHOT_TAX, "status": "snapshot", "fetched": stamp, "err": str(e)}


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def load_yield(country):
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    slug = COUNTRIES[country][0]
    url = TE_COUNTRY_URL.format(slug=slug)
    try:
        v, date_txt = parse_te_country_page(_get(url, timeout=25).text)
        return {"value": v / 100, "date": date_txt or "latest quote", "status": "live",
                "url": url, "fetched": stamp, "err": None}
    except Exception as e:
        return {"value": SNAPSHOT_YIELDS[country] / 100, "date": SNAPSHOT_YIELD_DATE,
                "status": "snapshot", "url": url, "fetched": stamp, "err": str(e)}


def pct(x, n=2):
    return f"{x * 100:.{n}f}%"


def pill(status):
    return {"live": '<span class="pill live">● Live</span>',
            "snapshot": '<span class="pill snap">● Backup copy</span>',
            "manual": '<span class="pill man">● Your input</span>'}[status]


# ---- Header -----------------------------------------------------------------------
st.markdown(
    """
<div class="hero">
  <h1>🌍 International Cost of Capital</h1>
  <p>What yearly return should a project earn to be worth doing? This app answers that in
  <b>U.S. dollars</b> and in the <b>local currency</b> of any country you pick, using live market data.</p>
</div>
""",
    unsafe_allow_html=True,
)

with st.spinner("Fetching the latest market data..."):
    betas = load_betas()
    bbb = load_bbb()
    tax = load_tax()

beta_df = betas["df"]
industries = beta_df["Industry"].tolist()

# ---- Sidebar ----------------------------------------------------------------------
with st.sidebar:
    if st.button("🔄 Refresh market data", use_container_width=True,
                 help="Fetch the newest betas, spreads, tax rates and bond yields."):
        st.cache_data.clear()
        st.rerun()

    st.header("1 · Your project")
    industry = st.selectbox("Industry", industries,
                            index=industries.index(DEFAULT_INDUSTRY) if DEFAULT_INDUSTRY in industries else 0)
    country_names = list(COUNTRIES)
    country = st.selectbox("Country (local currency)", country_names,
                           index=country_names.index(DEFAULT_COUNTRY))
    slug, iso3, ccy, ccy_name = COUNTRIES[country]

    st.header("2 · Assumptions")
    erp = st.number_input("Equity risk premium (%)", min_value=0.0, max_value=20.0, value=6.5,
                          step=0.1, help="Extra yearly return investors demand for holding stocks "
                                         "instead of government bonds. Class default: 6.5%.") / 100
    d = st.slider("Debt share of financing (%)", min_value=0, max_value=90, value=30, step=1,
                  help="Target D/(D+E). Class default: 30% debt, 70% equity.") / 100
    tax_choice = st.radio("Which corporate tax rate applies?",
                          ["U.S. rate", f"{country} rate"], horizontal=True,
                          help="The same rate is used for both currencies.")

    st.header("3 · Override the data (optional)")
    st.caption("Switch any item on to type your own number instead of the fetched one.")

    us_y = load_yield("United States")
    fx_y = load_yield(country) if country != "United States" else us_y
    beta_auto = float(beta_df.loc[beta_df["Industry"] == industry, "Unlevered beta"].iloc[0])
    tax_us_auto = tax["rates"].get("USA", SNAPSHOT_TAX["USA"])
    tax_fx_auto = tax["rates"].get(iso3, SNAPSHOT_TAX.get(iso3, (np.nan, None)))

    def override(label, auto_value, key, fmt_pct=True, step=0.01, help_txt=None):
        on = st.toggle(label, key=f"t_{key}", help=help_txt)
        if on:
            shown = auto_value * 100 if fmt_pct else auto_value
            v = st.number_input(f"{label} {'(%)' if fmt_pct else ''}", value=float(round(shown, 4)),
                                step=step, key=f"n_{key}", format="%.4f")
            return (v / 100 if fmt_pct else v), True
        return auto_value, False

    beta_u, beta_man = override("Unlevered beta", beta_auto, "beta", fmt_pct=False,
                                help_txt=f"Fetched: {beta_auto:.4f} for {industry}")
    tax_us, tax_us_man = override("U.S. corporate tax rate", tax_us_auto[0] / 100, "taxus")
    tax_fx, tax_fx_man = override(f"{country} corporate tax rate", tax_fx_auto[0] / 100, "taxfx")
    s_usd, s_usd_man = override("USD BBB borrowing spread", bbb["value"], "susd")
    rf_us, rf_us_man = override("U.S. 10-year yield", us_y["value"], "rfus")
    rf_fx, rf_fx_man = override(f"{country} 10-year yield", fx_y["value"], "rffx")

    tau = tax_us if tax_choice == "U.S. rate" else tax_fx
    auto_res = compute(beta_u, tau, d, erp, rf_us, rf_fx, s_usd)
    fx_sp_on = st.toggle(f"{ccy} borrowing spread", key="t_sfx",
                         help="Off = calculated automatically from the USD spread.")
    if fx_sp_on:
        s_fx_in = st.number_input(f"{ccy} borrowing spread (%)", value=float(round(auto_res["s_fx"] * 100, 4)),
                                  step=0.01, format="%.4f", key="n_sfx") / 100
    else:
        s_fx_in = None
        st.caption(f"Auto-calculated {ccy} spread: **{pct(auto_res['s_fx'], 4)}** "
                   f"(= USD spread × (1+{ccy} yield)/(1+U.S. yield))")

if np.isnan(tau):
    st.error(f"OECD has no tax rate for {country}. Switch on the tax override and enter one.")
    st.stop()

res = compute(beta_u, tau, d, erp, rf_us, rf_fx, s_usd, s_fx_in)
same_ccy = country == "United States"
fx_label = f"{ccy_name} ({ccy})" if not same_ccy else "U.S. dollars (USD), same country"

# ---- Headline cards ------------------------------------------------------------------
c1, c2 = st.columns(2)
for col, title, accent, keyset in [
    (c1, "In U.S. dollars (USD)", USD_COLOR, "usd"),
    (c2, f"In {fx_label}", FX_COLOR, "fx"),
]:
    with col:
        st.markdown(
            f"""
<div class="card" style="--accent:{accent}">
  <div class="label">{title}</div>
  <div class="big">{pct(res['wacc_' + keyset])}</div>
  <div class="sub">WACC: the minimum yearly return the project must earn</div>
  <table>
    <tr><td>Cost of equity (what shareholders expect)</td><td class="v">{pct(res['re_' + keyset])}</td></tr>
    <tr><td>Borrowing rate before tax</td><td class="v">{pct(res['rd_' + keyset])}</td></tr>
    <tr><td>Borrowing rate after tax savings</td><td class="v">{pct(res['rd_at_' + keyset])}</td></tr>
  </table>
</div>""",
            unsafe_allow_html=True,
        )

if same_ccy:
    st.markdown('<div class="note">You picked the United States, so both columns match. '
                'Choose another country in the sidebar to see the local-currency version.</div>',
                unsafe_allow_html=True)
else:
    direction = "lose" if res["dep"] > 0 else "gain"
    st.markdown(
        f'<div class="note"><b>Why the numbers differ:</b> {country}\'s 10-year bond pays '
        f'{pct(rf_fx)} versus {pct(rf_us)} in the U.S. Markets read that gap as the {ccy} expected to '
        f'{direction} about <b>{pct(abs(res["dep"]))} per year</b> against the dollar, so returns in '
        f'{ccy} must be higher (or lower) by that amount to be worth the same in dollars. '
        f'Same project, same risk, different measuring stick.</div>',
        unsafe_allow_html=True)

tabs = st.tabs(["📊 Results", "🧮 Step by step", "🏭 All industries", "📚 Data & sources",
                "📝 Assumptions", "✅ Checks"])

# ---- Results tab -----------------------------------------------------------------------
with tabs[0]:
    rows = [
        ("Cost of equity", res["re_usd"], res["re_fx"]),
        ("Risk-free rate (10-year government yield)", rf_us, rf_fx),
        ("Borrowing spread", res["s_usd"], res["s_fx"]),
        ("Pretax borrowing cost", res["rd_usd"], res["rd_fx"]),
        ("After-tax borrowing cost", res["rd_at_usd"], res["rd_at_fx"]),
        ("WACC", res["wacc_usd"], res["wacc_fx"]),
    ]
    res_df = pd.DataFrame(rows, columns=["Measure", "USD", ccy if not same_ccy else "USD (selected)"])
    left, right = st.columns([1.1, 1])
    with left:
        st.subheader("Side-by-side results")
        show = res_df.copy()
        for c in show.columns[1:]:
            show[c] = show[c].map(lambda x: pct(x, 4))
        st.dataframe(show, hide_index=True, use_container_width=True)
        st.caption(f"Project tax rate: {pct(tau)} ({tax_choice}). Debt share {pct(d, 0)}, "
                   f"equity risk premium {pct(erp, 1)}. Levered beta {res['beta_e']:.4f}.")
    with right:
        st.subheader("Picture it")
        chart_df = pd.DataFrame({
            "Measure": ["Cost of equity", "After-tax debt", "WACC"] * 2,
            "Currency": ["USD"] * 3 + [ccy if not same_ccy else "USD (selected)"] * 3,
            "Rate": [res["re_usd"], res["rd_at_usd"], res["wacc_usd"],
                     res["re_fx"], res["rd_at_fx"], res["wacc_fx"]],
        })
        chart_df["Label"] = chart_df["Rate"].map(lambda x: pct(x, 1))
        base = alt.Chart(chart_df).encode(
            x=alt.X("Measure:N", sort=["Cost of equity", "After-tax debt", "WACC"], title=None,
                    axis=alt.Axis(labelAngle=0)),
            xOffset=alt.XOffset("Currency:N"),
            y=alt.Y("Rate:Q", axis=alt.Axis(format="%", grid=True, gridOpacity=0.3), title=None),
            color=alt.Color("Currency:N", scale=alt.Scale(range=[USD_COLOR, FX_COLOR]),
                            legend=alt.Legend(orient="top", title=None)),
            tooltip=["Currency", "Measure", alt.Tooltip("Rate:Q", format=".4%")],
        )
        bars = base.mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
        labels = base.mark_text(dy=-8, fontSize=12).encode(text="Label:N", color=alt.value("#52514e"))
        st.altair_chart((bars + labels).properties(height=320), use_container_width=True)

    inputs_df = pd.DataFrame([
        ("Industry", industry, ""), ("Country", country, ""),
        ("Unlevered beta", f"{beta_u:.4f}", "manual" if beta_man else betas["status"]),
        ("Levered (equity) beta", f"{res['beta_e']:.4f}", "calculated"),
        ("Debt share d", pct(d, 0), "your choice"),
        ("Equity risk premium", pct(erp, 2), "your choice"),
        ("Project tax rate", pct(tau, 4), tax_choice),
        ("U.S. 10-year yield", pct(rf_us, 4), "manual" if rf_us_man else us_y["status"]),
        (f"{country} 10-year yield", pct(rf_fx, 4), "manual" if rf_fx_man else fx_y["status"]),
        ("USD BBB spread", pct(s_usd, 4), "manual" if s_usd_man else bbb["status"]),
        (f"{ccy} BBB spread", pct(res["s_fx"], 4), "manual" if fx_sp_on else "auto-calculated"),
        ("Conversion factor F", f"{res['factor']:.6f}", "calculated"),
    ], columns=["Input", "Value", "Source / status"])

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        res_df.to_excel(xw, sheet_name="Results", index=False)
        inputs_df.to_excel(xw, sheet_name="Inputs", index=False)
    d1, d2 = st.columns(2)
    d1.download_button("⬇️ Download results (Excel)", buf.getvalue(),
                       file_name=f"cost_of_capital_{slug}_{dt.date.today()}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       use_container_width=True)
    d2.download_button("⬇️ Download results (CSV)",
                       pd.concat([res_df.rename(columns={"Measure": "Item"}),
                                  inputs_df.rename(columns={"Input": "Item"})]).to_csv(index=False),
                       file_name=f"cost_of_capital_{slug}_{dt.date.today()}.csv", mime="text/csv",
                       use_container_width=True)

# ---- Step-by-step tab ------------------------------------------------------------------
with tabs[1]:
    st.subheader("How the numbers are built")
    st.markdown("**Step 1. Add the effect of debt to the industry's business risk (relever beta)**")
    st.latex(r"\beta_E=\beta_U\left[1+(1-\tau)\frac{d}{1-d}\right]="
             rf"{beta_u:.4f}\left[1+(1-{tau:.4f})\times{res['de']:.4f}\right]={res['beta_e']:.4f}")
    st.markdown("**Step 2. Cost of equity in USD (CAPM, U.S. yield as risk-free rate)**")
    st.latex(rf"R_e=R_f+\beta_E\times ERP={rf_us:.4%}+{res['beta_e']:.4f}\times{erp:.2%}={res['re_usd']:.4%}".replace("%", r"\%"))
    st.markdown("**Step 3. Borrowing cost in USD and the tax saving on interest**")
    st.latex(rf"R_d=R_f+s={rf_us:.4%}+{s_usd:.4%}={res['rd_usd']:.4%},\quad R_d(1-\tau)={res['rd_at_usd']:.4%}".replace("%", r"\%"))
    st.markdown("**Step 4. WACC in USD**")
    st.latex(rf"WACC=(1-d)R_e+d\,R_d(1-\tau)={1-d:.2f}\times{res['re_usd']:.4%}+{d:.2f}\times{res['rd_at_usd']:.4%}={res['wacc_usd']:.4%}".replace("%", r"\%"))
    st.markdown(f"**Step 5. Conversion factor from bond yields (relative PPP + Fisher)**")
    st.latex(rf"F=\frac{{1+R_f^*}}{{1+R_f}}=\frac{{1+{rf_fx:.4%}}}{{1+{rf_us:.4%}}}={res['factor']:.6f}".replace("%", r"\%"))
    st.markdown(f"**Step 6. Cost of equity in {ccy}**")
    st.latex(rf"R_e^*=(1+R_e)F-1=(1+{res['re_usd']:.4%})\times{res['factor']:.6f}-1={res['re_fx']:.4%}".replace("%", r"\%"))
    st.markdown(f"**Step 7. Borrowing cost in {ccy}**")
    if fx_sp_on:
        st.latex(rf"R_d^*=R_f^*+s^*_{{manual}}={rf_fx:.4%}+{res['s_fx']:.4%}={res['rd_fx']:.4%}".replace("%", r"\%"))
    else:
        st.latex(rf"R_d^*=(1+R_d)F-1={res['rd_fx']:.4%},\quad s^*=R_d^*-R_f^*=s\,F={res['s_fx']:.4%}".replace("%", r"\%"))
    st.latex(rf"R_d^*(1-\tau)={res['rd_at_fx']:.4%}".replace("%", r"\%"))
    st.markdown(f"**Step 8. WACC in {ccy}** (same debt share and tax rate)")
    st.latex(rf"WACC^*={1-d:.2f}\times{res['re_fx']:.4%}+{d:.2f}\times{res['rd_at_fx']:.4%}={res['wacc_fx']:.4%}".replace("%", r"\%"))
    st.caption("Calculations keep full precision; displayed numbers are rounded.")

# ---- All industries tab --------------------------------------------------------------
with tabs[2]:
    st.subheader("Every industry, same country and assumptions")
    st.caption("Uses each industry's fetched unlevered beta (your beta override applies only to "
               "the selected industry above) with the current tax rate, debt share, ERP, yields and spreads.")
    all_rows = []
    for r in beta_df.itertuples(index=False):
        b = beta_u if (r.Industry == industry and beta_man) else r[2]
        x = compute(b, tau, d, erp, rf_us, rf_fx, s_usd, s_fx_in)
        all_rows.append({"Industry": r.Industry, "Unlevered beta": b, "Levered beta": x["beta_e"],
                         "Cost of equity USD": x["re_usd"], f"Cost of equity {ccy}": x["re_fx"],
                         "WACC USD": x["wacc_usd"], f"WACC {ccy}": x["wacc_fx"]})
    all_df = pd.DataFrame(all_rows)
    all_df = all_df[~all_df["Industry"].str.startswith("Total Market")]
    wacc_cols = ["WACC USD"] + ([f"WACC {ccy}"] if not same_ccy else [])
    metric = st.radio("Rank industries by", wacc_cols, horizontal=True)
    all_df = all_df.sort_values(metric, ascending=False)
    all_df["Selected"] = np.where(all_df["Industry"] == industry, "Your industry", "Other")
    bar = alt.Chart(all_df).mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4).encode(
        y=alt.Y("Industry:N", sort="-x", title=None, axis=alt.Axis(labelLimit=260)),
        x=alt.X(f"{metric}:Q", axis=alt.Axis(format="%", orient="top", gridOpacity=0.3), title=metric),
        color=alt.Color("Selected:N", scale=alt.Scale(domain=["Your industry", "Other"],
                                                      range=[FX_COLOR, USD_COLOR]),
                        legend=alt.Legend(orient="top", title=None)),
        tooltip=["Industry", alt.Tooltip("Unlevered beta:Q", format=".2f"),
                 alt.Tooltip(f"{metric}:Q", format=".2%")],
    ).properties(height=max(400, 17 * len(all_df)))
    g1, g2 = st.columns([1.15, 1])
    with g1:
        st.altair_chart(bar, use_container_width=True)
    with g2:
        fmt = {c: st.column_config.NumberColumn(c, format="%.2f%%") for c in all_df.columns
               if c.startswith(("Cost", "WACC"))}
        disp = all_df.drop(columns=["Selected"]).copy()
        for c in fmt:
            disp[c] = disp[c] * 100
        st.dataframe(disp, hide_index=True, use_container_width=True, height=900,
                     column_config={**fmt,
                                    "Unlevered beta": st.column_config.NumberColumn(format="%.2f"),
                                    "Levered beta": st.column_config.NumberColumn(format="%.2f")})
        st.download_button("⬇️ Download all industries (CSV)",
                           all_df.drop(columns=["Selected"]).to_csv(index=False),
                           file_name=f"all_industries_{slug}_{dt.date.today()}.csv", mime="text/csv",
                           use_container_width=True)

# ---- Data & sources tab -------------------------------------------------------------
with tabs[3]:
    st.subheader("Where every number comes from")
    us_tax_y = tax_us_auto[1]
    fx_tax_y = tax_fx_auto[1]
    src_rows = [
        ("Unlevered beta", f"{beta_auto:.4f} ({industry})", betas["src"], betas["date"], betas["url"], betas["status"]),
        ("USD BBB spread", pct(bbb["value"], 2), "Damodaran ratings.html, Baa2/BBB, large non-financial firms",
         bbb["date"], RATINGS_URL, bbb["status"]),
        ("U.S. corporate tax", pct(tax_us_auto[0] / 100, 2), "OECD Corporate Tax Statistics (combined statutory rate)",
         str(us_tax_y), OECD_PAGE_URL, tax["status"]),
        (f"{country} corporate tax", pct(tax_fx_auto[0] / 100, 2) if not np.isnan(tax_fx_auto[0]) else "n/a",
         "OECD Corporate Tax Statistics (combined statutory rate)", str(fx_tax_y), OECD_PAGE_URL, tax["status"]),
        ("U.S. 10-year yield", pct(us_y["value"], 4), "Trading Economics", us_y["date"], us_y["url"], us_y["status"]),
        (f"{country} 10-year yield", pct(fx_y["value"], 4), "Trading Economics", fx_y["date"], fx_y["url"], fx_y["status"]),
    ]
    html = ["<table style='width:100%'><tr><th>Input</th><th>Fetched value</th><th>Source</th>"
            "<th>Data date</th><th>Status</th></tr>"]
    for n, v, s, dte, u, stt in src_rows:
        html.append(f"<tr><td>{n}</td><td><b>{v}</b></td><td><a href='{u}' target='_blank'>{s}</a></td>"
                    f"<td>{dte}</td><td>{pill(stt)}</td></tr>")
    html.append("</table>")
    st.markdown("".join(html), unsafe_allow_html=True)
    st.caption(f"Last fetched: betas {betas['fetched']}, spread {bbb['fetched']}, tax {tax['fetched']}, "
               f"yields {us_y['fetched']}. Data is cached for 6 hours; use **Refresh market data** for a new pull. "
               "OECD rates are read from the OECD Data Explorer API "
               f"([link]({OECD_API_URL})), the same database behind the OECD report page. "
               f"Trading Economics bond overview: [{TE_BONDS_URL}]({TE_BONDS_URL}).")
    st.markdown(f'{pill("live")} fetched just now from the source &nbsp; {pill("snapshot")} source '
                f'unreachable, so a stored copy is used (date shown) &nbsp; {pill("manual")} you typed it',
                unsafe_allow_html=True)
    errs = [(n, e) for n, e in [("Betas", betas["err"]), ("BBB spread", bbb["err"]), ("Tax", tax["err"]),
                                 ("U.S. yield", us_y["err"]), (f"{country} yield", fx_y["err"])] if e]
    if errs:
        with st.expander("Technical details on fetch problems"):
            for n, e in errs:
                st.write(f"**{n}:** {e}")

# ---- Assumptions tab --------------------------------------------------------------
with tabs[4]:
    st.subheader("The main assumptions, in plain English")
    st.markdown(f"""
- **Risk is measured against the U.S. stock market.** We use CAPM with the U.S. 10-year Treasury as the risk-free rate and a {pct(erp, 1)} equity risk premium.
- **U.S. industry betas stand in for project risk.** Damodaran's unlevered beta captures the business risk of the industry; we add back debt at your target debt share.
- **Government bond yields are the risk-free rates.** In some countries these also include liquidity, term and default premia.
- **Currencies are linked through inflation.** Equal real interest rates (Fisher) plus relative purchasing power parity mean the yield gap equals expected depreciation, so we scale returns by F = (1+R*f)/(1+Rf).
- **No extra country risk premium** is added to the cost of equity; currency risk is treated as diversifiable.
- **The foreign borrowing spread** is, by default, the USD BBB spread scaled by the same factor F. You can override it.
- **Financing and taxes:** the debt share stays constant, interest deductions are fully usable right away, the same tax rate applies in both currencies, and debt has zero beta when unlevering.

*Method: Prof. Sergio Rebelo, Kellogg International Finance, "Designing cost of capital app."*
""")

# ---- Checks tab ---------------------------------------------------------------------
with tabs[5]:
    st.subheader("Automatic sanity checks")
    st.caption("These run on your current inputs every time the page updates.")
    for name, ok, detail in run_checks(beta_u, tau, d, erp, rf_us, rf_fx, s_usd):
        (st.success if ok else st.error)(f"{'✅' if ok else '❌'} **{name}**  \n{detail}")
