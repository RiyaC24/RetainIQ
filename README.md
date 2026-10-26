# RetainIQ — Customer Retention Analytics

RetainIQ is a beginner-friendly **Data Analytics** project that turns customer transaction data into understandable retention insights.

## Why this project exists

A business may have thousands of transactions but still not know:

- Which customers are active?
- Which customers may need attention?
- Which customers are valuable?
- How are revenue and customer activity changing over time?
- Why was a customer flagged?
- Which customers should the business review first?

RetainIQ answers these questions from an uploaded CSV or Excel transaction file.

## Features

1. **Interactive analytics dashboard** — customer count, revenue/spend, average order value, repeat-customer rate and risk counts.
2. **Customer segmentation** — Loyal / high value, Active, At risk and Inactive groups.
3. **Explainable risk analysis** — shows the evidence behind a risk label instead of only showing a score.
4. **Own dataset upload** — CSV, XLSX and XLS files; users select the relevant columns, so column names do not need to be identical to the sample.
5. **Revenue and activity trends** — monthly customer and transaction trends, plus revenue when an amount column is available.
6. **Actionable reports** — priority customer list and downloadable CSV/TXT reports.
7. **Data quality checks** — unreadable dates, missing customer IDs and future-dated rows are surfaced.
8. **Relative RFM-style score** — combines recency, frequency and monetary value when spending data exists. It is an explainable analytics score, not a machine-learning churn prediction.

## What data should I upload?

Best input: **one row per transaction or order line**.

Required:
- A customer ID or consistent customer name
- A transaction/purchase/activity date

Optional:
- Amount/revenue/price
- Order ID/invoice number
- Product category

Example:

```text
customer_id,order_date,order_amount,order_id,category
C001,2026-10-20,1250,O1001,Electronics
C001,2026-09-14,650,O0990,Electronics
C002,2026-07-01,900,O0980,Home
```

The application lets you map your own column names. It cannot intelligently analyze an unrelated file with no customer identifier or date; those fields are necessary for customer retention analysis.

## How the risk labels work

Default thresholds:

- **Active:** activity within 45 days
- **At risk:** 45–89 days since activity
- **Inactive:** 90+ days since activity
- **Loyal / high value:** recent activity plus relatively strong purchase frequency and RFM score

The thresholds can be changed in the dashboard.

The app also considers purchase frequency and spending when explaining risk. These labels are **business indicators, not proof of churn**. A real churn prediction model would require historical labeled data and validation.

## How the analytics work

RetainIQ summarizes transactions at customer level and calculates:

- First activity
- Last activity
- Days since last activity
- Transaction rows
- Orders, when an order ID is available
- Total spending, when an amount column is available
- Average order value
- Repeat-customer rate
- Relative RFM-style score
- Segment and risk reason

It also creates monthly activity/revenue trends and category summaries when category data is available.

## Tools — in simple words

- **Python:** main programming language.
- **pandas:** reads, cleans and analyzes tables.
- **Streamlit:** creates the browser dashboard from Python, so this simplified version does not need React or Node.js.
- **openpyxl:** lets the app read Excel `.xlsx` files.
- **CSV/Excel:** input formats for business data.

This version deliberately avoids unnecessary infrastructure. It does not need a database, Docker, API keys or cloud services.

## Run on Windows

Install Python 3.10+.

Open PowerShell in this project folder:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Then open the URL shown in the terminal, normally `http://localhost:8501`.

## Project structure

```text
RetainIQ_Simple/
├── app.py
├── requirements.txt
├── README.md
└── sample_data/
    └── sample_transactions.csv
```

## Good interview explanation

> “I built RetainIQ as a customer retention analytics tool. The user can upload a transaction dataset, map the customer and date columns, and optionally provide order, amount and category columns. The application cleans the data, calculates customer-level metrics such as recency, frequency and spending, segments customers into understandable groups, explains why customers may need attention, shows revenue and activity trends, and exports the results. I kept the risk logic transparent instead of claiming that a simple rule is an AI churn prediction.”
