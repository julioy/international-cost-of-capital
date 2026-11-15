# International Cost of Capital App

A Streamlit app that compares a project's **cost of equity, cost of debt and WACC in U.S. dollars and in the currency of any selected country**, following the method taught by Prof. Sergio Rebelo in Kellogg's International Finance course ("Designing cost of capital app").

## What it does

* Pick an **industry** and a **country**; adjust the **equity risk premium** and the **target debt share**.
* Switch the project **tax rate** between the U.S. rate and the selected country's rate (the same rate is used in both currencies).
* Optionally **override** any fetched input: unlevered beta, U.S. and foreign corporate tax rates, USD BBB spread, both 10-year yields, and the foreign-currency BBB spread (when that override is off the app shows the auto-calculated spread).
* Results side by side, a step-by-step walkthrough with the numbers plugged in, an **all-industry comparison**, plain-English assumptions, downloadable Excel/CSV results, and automatic sanity checks.

**Defaults:** Software (System & Application), United States, U.S. tax rate, 6.5% ERP, 30% debt.

## Data sources (fetched live, cached 6 hours, "Refresh market data" button)

| Input | Source |
|---|---|
| Unlevered industry beta | Aswath Damodaran, [betas.xls](https://pages.stern.nyu.edu/~adamodar/pc/datasets/betas.xls) ("Unlevered beta" column; falls back to the identical Betas.html page) |
| USD BBB spread | Aswath Damodaran, [ratings.html](https://pages.stern.nyu.edu/adamodar/New_Home_Page/datafile/ratings.html), Baa2/BBB row for large non-financial service firms |
| Corporate tax rates | OECD Corporate Tax Statistics, combined (central + sub-central) statutory CIT rate, latest year, read from the [OECD Data Explorer API](https://sdmx.oecd.org/public/rest/data/OECD.CTP.TPS,DSD_TAX_CIT@DF_CIT,/all?startPeriod=2022&format=csvfilewithlabels) that feeds the [report page](https://www.oecd.org/en/publications/corporate-tax-statistics-2024_9c27d6e8-en/full-report/statutory-corporate-income-tax-rates_440f9286.html) |
| 10-year government yields | [Trading Economics](https://tradingeconomics.com/bonds), scraped from each country's government-bond-yield page (the /bonds overview table now loads behind a bot check, the country pages carry the same quotes) |

If a source cannot be reached, the app uses a clearly labeled backup copy (with its date) and you can type your own value.

## Method

| Step | Formula |
|---|---|
| Relever beta | βE = βU [1 + (1 − τ) d/(1 − d)] |
| USD cost of equity | Re = Rf + βE × ERP |
| USD borrowing cost | Rd = Rf + s, after tax Rd(1 − τ) |
| Conversion factor | F = (1 + Rf\*)/(1 + Rf) |
| Foreign cost of equity | 1 + Re\* = (1 + Re) F |
| Foreign borrowing cost | 1 + Rd\* = (1 + Rd) F, so s\* = s F (or Rd\* = Rf\* + s\* if overridden) |
| WACC (each currency) | (1 − d) Re + d Rd (1 − τ) |

The class Colombia example (βU 0.80, d 30%, τ 35%, ERP 6.5%, Rf 4%, Rf\* 12%, s 1.5%) reproduces USD WACC 8.5265% and COP WACC 16.0670%; this is one of the automatic checks in the app.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```
