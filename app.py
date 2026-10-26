from __future__ import annotations

import io
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

st.set_page_config(page_title="RetainIQ | Customer Retention Analytics", page_icon="📊", layout="wide")

st.title("📊 RetainIQ")
st.caption("Customer Retention Analytics — turn transaction data into clear customer insights.")
st.info("RetainIQ analyzes the file you upload. It does not claim that a customer has definitely churned. Risk labels are explainable business rules based on the data available.")

# ----------------------------- Helpers -----------------------------

def load_file(file):
    if file.name.lower().endswith(".csv"):
        try:
            return pd.read_csv(file)
        except UnicodeDecodeError:
            file.seek(0)
            return pd.read_csv(file, encoding="latin-1")
    return pd.read_excel(file)


def clean_number(series):
    return pd.to_numeric(
        series.astype(str)
        .str.replace(r"[₹$,£€\s]", "", regex=True)
        .str.replace(",", "", regex=False),
        errors="coerce",
    )


def guess_column(columns, keywords):
    for col in columns:
        normalized = str(col).strip().lower().replace(" ", "_")
        if any(k in normalized for k in keywords):
            return col
    return columns[0] if columns else None


def money(value):
    if pd.isna(value):
        return "—"
    return f"{value:,.2f}"


def make_analysis(raw, customer_col, date_col, amount_col, order_col, category_col, analysis_date, risk_days, inactive_days):
    data = raw.copy()
    data.columns = [str(c).strip() for c in data.columns]
    data["_customer"] = data[customer_col].astype("string").str.strip()
    data["_date"] = pd.to_datetime(data[date_col], errors="coerce")
    data.loc[data["_customer"].isin(["", "nan", "None", "<NA>"]), "_customer"] = pd.NA
    data["_amount"] = clean_number(data[amount_col]) if amount_col != "(Not available)" else pd.NA
    if order_col != "(Not available)":
        data["_order"] = data[order_col].astype("string").str.strip()
    else:
        data["_order"] = pd.NA
    if category_col != "(Not available)":
        data["_category"] = data[category_col].astype("string").str.strip()
    else:
        data["_category"] = pd.NA

    rows_in = len(data)
    invalid_date_rows = int(data["_date"].isna().sum())
    missing_customer_rows = int(data["_customer"].isna().sum())
    data = data.dropna(subset=["_customer", "_date"]).copy()
    snapshot = pd.Timestamp(analysis_date) + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
    future_rows = int((data["_date"] > snapshot).sum())
    data = data[data["_date"] <= snapshot].copy()
    if data.empty:
        raise ValueError("No usable transactions occur on or before the selected analysis date.")

    grouped = data.groupby("_customer", dropna=True)
    customers = grouped.agg(
        transaction_rows=("_date", "count"),
        first_activity=("_date", "min"),
        last_activity=("_date", "max"),
    ).reset_index().rename(columns={"_customer": "customer"})

    # Distinct orders when an order/invoice column is available; otherwise transaction rows.
    if order_col != "(Not available)":
        order_counts = data.groupby("_customer")["_order"].nunique(dropna=True).rename("orders").reset_index()
        customers = customers.merge(order_counts, left_on="customer", right_on="_customer", how="left").drop(columns=["_customer"])
        customers["orders"] = customers["orders"].fillna(customers["transaction_rows"]).astype(int)
    else:
        customers["orders"] = customers["transaction_rows"]

    customers["days_since_activity"] = (
        snapshot.normalize() - customers["last_activity"].dt.normalize()
    ).dt.days.clip(lower=0).astype(int)

    if amount_col != "(Not available)":
        spend = data.groupby("_customer")["_amount"].sum(min_count=1).rename("total_spent").reset_index()
        customers = customers.merge(spend, left_on="customer", right_on="_customer", how="left").drop(columns=["_customer"])
    else:
        customers["total_spent"] = pd.NA

    customers["avg_order_value"] = customers["total_spent"] / customers["orders"].replace(0, pd.NA)

    # Frequency and monetary ranks are relative to the uploaded dataset.
    freq_rank = customers["orders"].rank(pct=True, method="average")
    if customers["total_spent"].notna().any():
        monetary_rank = pd.to_numeric(customers["total_spent"], errors="coerce").rank(pct=True, method="average")
    else:
        monetary_rank = pd.Series(0.5, index=customers.index)
    recency_rank = 1 - customers["days_since_activity"].rank(pct=True, method="average")

    customers["rfm_score"] = ((recency_rank + freq_rank + monetary_rank) / 3 * 100).round(1)

    def status(row):
        # Transparent rules: recency is primary; low frequency/spend adds risk when historical data supports it.
        if row.days_since_activity >= inactive_days:
            return "Inactive"
        if row.days_since_activity >= risk_days:
            return "At risk"
        if row.orders >= customers["orders"].median() and row.rfm_score >= 65:
            return "Loyal / high value"
        return "Active"

    customers["segment"] = customers.apply(status, axis=1)

    median_orders = max(float(customers["orders"].median()), 1.0)
    median_spend = pd.to_numeric(customers["total_spent"], errors="coerce").median() if customers["total_spent"].notna().any() else None

    def reason(row):
        reasons = []
        if row.days_since_activity >= inactive_days:
            reasons.append(f"no activity for {row.days_since_activity} days")
        elif row.days_since_activity >= risk_days:
            reasons.append(f"{row.days_since_activity} days since last activity")
        if row.orders < median_orders and row.days_since_activity >= risk_days:
            reasons.append("below-median purchase frequency")
        if median_spend is not None and pd.notna(row.total_spent) and row.total_spent < median_spend and row.days_since_activity >= risk_days:
            reasons.append("below-median spending")
        if not reasons:
            reasons.append("recent or healthy purchase activity")
        return "; ".join(reasons)

    customers["risk_reason"] = customers.apply(reason, axis=1)
    customers["suggested_action"] = customers["segment"].map({
        "Loyal / high value": "Protect the relationship with loyalty benefits or personalized recommendations.",
        "Active": "Keep engaged with relevant products and good service.",
        "At risk": "Review recent behavior and consider a relevant reminder or offer.",
        "Inactive": "Prioritize a win-back campaign and investigate why activity stopped.",
    })

    customers = customers.sort_values(["segment", "days_since_activity", "total_spent"], ascending=[True, False, False]).reset_index(drop=True)

    # Monthly trends.
    trend = data.copy()
    trend["month"] = trend["_date"].dt.to_period("M").astype(str)
    monthly = trend.groupby("month").agg(
        transactions=("_date", "count"),
        customers=("_customer", "nunique"),
    ).reset_index()
    if amount_col != "(Not available)":
        revenue = trend.groupby("month")["_amount"].sum(min_count=1).rename("revenue").reset_index()
        monthly = monthly.merge(revenue, on="month", how="left")
    else:
        monthly["revenue"] = pd.NA

    category_summary = None
    if category_col != "(Not available)":
        category_summary = data.groupby("_category", dropna=False).agg(
            transactions=("_date", "count"),
            customers=("_customer", "nunique"),
        ).reset_index().rename(columns={"_category": "category"})
        if amount_col != "(Not available)":
            rev = data.groupby("_category")["_amount"].sum(min_count=1).rename("revenue").reset_index().rename(columns={"_category": "category"})
            category_summary = category_summary.merge(rev, on="category", how="left")

    total_spent = pd.to_numeric(customers["total_spent"], errors="coerce").sum(min_count=1)
    repeat_rate = (customers["orders"] >= 2).mean() * 100
    avg_order_value = total_spent / customers["orders"].sum() if pd.notna(total_spent) and customers["orders"].sum() else None

    return {
        "customers": customers,
        "monthly": monthly,
        "category": category_summary,
        "rows_in": rows_in,
        "valid_rows": len(data),
        "invalid_date_rows": invalid_date_rows,
        "missing_customer_rows": missing_customer_rows,
        "future_rows": future_rows,
        "snapshot": analysis_date.isoformat(),
        "amount_available": amount_col != "(Not available)",
        "order_available": order_col != "(Not available)",
        "category_available": category_col != "(Not available)",
        "total_spent": total_spent,
        "repeat_rate": repeat_rate,
        "avg_order_value": avg_order_value,
        "risk_days": int(risk_days),
        "inactive_days": int(inactive_days),
    }


def report_text(result):
    c = result["customers"]
    counts = c["segment"].value_counts()
    lines = [
        "RetainIQ — Customer Retention Analytics Report",
        f"Analysis date: {result['snapshot']}",
        "",
        "KEY FINDINGS",
        f"Customers analyzed: {len(c):,}",
        f"Total recorded spending: {money(result['total_spent'])}",
        f"Average order value: {money(result['avg_order_value'])}",
        f"Repeat-customer rate: {result['repeat_rate']:.1f}%",
        f"At risk: {int(counts.get('At risk', 0)):,}",
        f"Inactive: {int(counts.get('Inactive', 0)):,}",
        f"Loyal / high value: {int(counts.get('Loyal / high value', 0)):,}",
        "",
        "BUSINESS INTERPRETATION",
        "At-risk and inactive labels are rule-based indicators. They should be investigated rather than treated as proof of churn.",
        "Prioritize customers using both risk evidence and business value; for example, a high-spending customer with a long purchase gap may deserve earlier attention.",
    ]
    return "\n".join(lines)


# ----------------------------- Sidebar -----------------------------
with st.sidebar:
    st.header("How RetainIQ works")
    st.markdown("1. Upload a transaction file.\n2. Match the columns.\n3. RetainIQ cleans and summarizes the data.\n4. Review KPIs, segments, trends and customer reasons.\n5. Download the results.")
    st.markdown("---")
    st.caption("Best input: one row per transaction/order line with a customer identifier and transaction date. Amount, order ID and category are optional.")

uploaded = st.file_uploader("Upload customer transaction data", type=["csv", "xlsx", "xls"], help="Use your own CSV/Excel file or try the included sample data.")

if uploaded is None:
    st.subheader("Start with the included sample data")
    st.write("The sample file demonstrates the structure. Your own compatible CSV or Excel file can be analyzed the same way.")
    sample_path = Path(__file__).parent / "sample_data" / "sample_transactions.csv"
    if sample_path.exists():
        sample = pd.read_csv(sample_path)
        st.dataframe(sample, use_container_width=True, hide_index=True)
        st.download_button("Download sample CSV", sample.to_csv(index=False).encode("utf-8"), "retainiq_sample_transactions.csv", "text/csv")
    st.markdown("### What makes this useful?")
    st.markdown("- **Dashboard:** see the business picture quickly.\n- **Segmentation:** understand different customer groups.\n- **Explainable risk:** see why a customer was flagged.\n- **Trends:** compare activity and revenue over time.\n- **Own data:** upload a compatible CSV/Excel file.\n- **Reports:** download customer-level results for further analysis.")
    st.stop()

try:
    raw = load_file(uploaded)
except Exception as exc:
    st.error(f"I couldn't open this file. Please try a CSV or Excel file. Details: {exc}")
    st.stop()

if raw.empty:
    st.error("This file has no rows. Upload a file that contains transaction records.")
    st.stop()

raw.columns = [str(c).strip() for c in raw.columns]
columns = list(raw.columns)

st.subheader("1. Connect your dataset")
st.write("Tell RetainIQ which columns represent the customer, transaction date and optional business fields. Your column names do not have to match the examples.")

customer_guess = guess_column(columns, ["customer_id", "customer", "client_id", "user_id", "buyer", "customer_name"])
date_guess = guess_column(columns, ["order_date", "invoice_date", "purchase_date", "transaction_date", "date", "created_at", "activity_date"])
amount_guess = guess_column(columns, ["amount", "sales", "revenue", "total", "price", "value", "order_amount"])
order_guess = guess_column(columns, ["order_id", "invoice", "invoice_no", "transaction_id", "order_number"])
category_guess = guess_column(columns, ["category", "product_category", "segment", "product"])

c1, c2, c3 = st.columns(3)
with c1:
    customer_col = st.selectbox("Customer ID / name *", columns, index=columns.index(customer_guess))
with c2:
    date_col = st.selectbox("Transaction / activity date *", columns, index=columns.index(date_guess))
with c3:
    amount_options = ["(Not available)"] + columns
    amount_col = st.selectbox("Amount / revenue", amount_options, index=(amount_options.index(amount_guess) if amount_guess in amount_options else 0))

c4, c5, c6 = st.columns(3)
with c4:
    order_options = ["(Not available)"] + columns
    order_col = st.selectbox("Order / invoice ID", order_options, index=(order_options.index(order_guess) if order_guess in order_options else 0))
with c5:
    category_options = ["(Not available)"] + columns
    category_col = st.selectbox("Product category", category_options, index=(category_options.index(category_guess) if category_guess in category_options else 0))
with c6:
    risk_days = st.number_input("At-risk after (days)", min_value=1, max_value=3650, value=45)

inactive_days = st.number_input("Inactive after (days)", min_value=2, max_value=3650, value=90)
if inactive_days <= risk_days:
    st.error("Inactive days must be greater than At-risk days.")
    st.stop()

parsed_dates = pd.to_datetime(raw[date_col], errors="coerce")
valid_dates = parsed_dates.dropna()
if valid_dates.empty:
    st.error("No readable dates were found in the selected date column. Choose another date column or fix the date format.")
    st.stop()

latest_date = valid_dates.max().date()
analysis_date = st.date_input("Analysis date", value=latest_date, help="Defaults to the latest date in your file. Use today's date when the uploaded data is current and you want current inactivity.")

with st.expander("Preview uploaded data"):
    st.write(f"**{len(raw):,} rows × {len(raw.columns):,} columns**")
    st.dataframe(raw.head(20), use_container_width=True, hide_index=True)

if st.button("🔎 Analyze customer data", type="primary", use_container_width=True):
    try:
        result = make_analysis(raw, customer_col, date_col, amount_col, order_col, category_col, analysis_date, risk_days, inactive_days)
        st.session_state["retainiq_result"] = result
    except Exception as exc:
        st.error(str(exc))
        st.stop()

if "retainiq_result" not in st.session_state:
    st.info("Click **Analyze customer data** to generate the dashboard.")
    st.stop()

result = st.session_state["retainiq_result"]
customers = result["customers"].copy()

st.divider()
st.header("2. Executive dashboard")

count_by_segment = customers["segment"].value_counts()
total_customers = len(customers)
total_spent = result["total_spent"]
at_risk_count = int(count_by_segment.get("At risk", 0))
inactive_count = int(count_by_segment.get("Inactive", 0))

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Customers", f"{total_customers:,}")
k2.metric("Revenue / spend", money(total_spent) if result["amount_available"] else "Not available")
k3.metric("Avg order value", money(result["avg_order_value"]) if result["amount_available"] else "Not available")
k4.metric("Repeat customers", f"{result['repeat_rate']:.1f}%")
k5.metric("At risk + inactive", f"{at_risk_count + inactive_count:,}")

st.caption(f"Analysis date: {result['snapshot']} · At risk: {result['risk_days']}–{result['inactive_days'] - 1} days · Inactive: {result['inactive_days']}+ days")

# Segmentation chart
st.subheader("Customer segments")
segment_counts = count_by_segment.reindex(["Loyal / high value", "Active", "At risk", "Inactive"]).fillna(0).astype(int)
st.bar_chart(segment_counts)

# Trends
st.subheader("3. Revenue and customer activity trends")
monthly = result["monthly"].copy()
if not monthly.empty:
    if result["amount_available"]:
        trend_view = monthly.set_index("month")[["revenue", "customers"]]
        st.line_chart(trend_view)
    else:
        st.line_chart(monthly.set_index("month")[["customers", "transactions"]])
else:
    st.info("Not enough dated records to create a trend.")

if result["category_available"] and result["category"] is not None:
    st.subheader("Category performance")
    st.dataframe(result["category"], use_container_width=True, hide_index=True)

st.subheader("4. Customer risk investigation")
st.write("Use the filters to find customers that need attention. Every risk label includes an explanation based on the uploaded data.")

f1, f2 = st.columns([1, 2])
with f1:
    status_filter = st.multiselect("Segments", ["Loyal / high value", "Active", "At risk", "Inactive"], default=["At risk", "Inactive"])
with f2:
    search = st.text_input("Search customer ID / name")

view = customers[customers["segment"].isin(status_filter)].copy()
if search.strip():
    view = view[view["customer"].astype(str).str.contains(search.strip(), case=False, na=False)]

show_cols = ["customer", "segment", "risk_reason", "orders", "transaction_rows", "last_activity", "days_since_activity", "rfm_score", "total_spent", "suggested_action"]
display = view[show_cols].rename(columns={
    "customer": "Customer",
    "segment": "Segment",
    "risk_reason": "Why flagged",
    "orders": "Orders",
    "transaction_rows": "Rows",
    "last_activity": "Last activity",
    "days_since_activity": "Days since activity",
    "rfm_score": "RFM score",
    "total_spent": "Total spent",
    "suggested_action": "Suggested action",
})
display["Last activity"] = pd.to_datetime(display["Last activity"]).dt.strftime("%Y-%m-%d")
if "Total spent" in display:
    display["Total spent"] = pd.to_numeric(display["Total spent"], errors="coerce").round(2)
st.dataframe(display, use_container_width=True, hide_index=True)

st.subheader("5. What should the business do?")
priority = customers[customers["segment"].isin(["At risk", "Inactive"])].copy()
if not priority.empty:
    high_value_priority = priority.sort_values(["total_spent", "days_since_activity"], ascending=[False, False]).head(10)
    st.write("**Priority list:** start by reviewing high-value customers who also show a long activity gap.")
    pcols = ["customer", "segment", "days_since_activity", "total_spent", "risk_reason", "suggested_action"]
    st.dataframe(high_value_priority[pcols].rename(columns={"customer":"Customer","segment":"Segment","days_since_activity":"Days since activity","total_spent":"Total spent","risk_reason":"Evidence","suggested_action":"Next action"}), use_container_width=True, hide_index=True)
else:
    st.success("No customers are currently in the At risk or Inactive groups under the selected thresholds.")

st.subheader("6. Data quality checks")
q1, q2, q3, q4 = st.columns(4)
q1.metric("Rows uploaded", f"{result['rows_in']:,}")
q2.metric("Rows analyzed", f"{result['valid_rows']:,}")
q3.metric("Unreadable dates", f"{result['invalid_date_rows']:,}")
q4.metric("Missing customer", f"{result['missing_customer_rows']:,}")
if result["future_rows"]:
    st.warning(f"{result['future_rows']:,} rows occur after the selected analysis date and were excluded.")

with st.expander("How RetainIQ decides the labels"):
    st.markdown(f"""
- **Loyal / high value:** recent activity plus relatively strong purchase frequency and overall RFM score.
- **Active:** activity within the last **{result['risk_days']} days**.
- **At risk:** no recorded activity for **{result['risk_days']}–{result['inactive_days'] - 1} days**.
- **Inactive:** no recorded activity for **{result['inactive_days']}+ days**.
- **Why flagged:** uses the customer's recency and, where available, purchase frequency and spending compared with the uploaded dataset.

These are transparent indicators, not proof of churn. If the dataset contains only one snapshot per customer, the app cannot measure a true decline in purchase frequency.
""")

st.subheader("7. Download your analysis")
all_csv = customers.to_csv(index=False).encode("utf-8-sig")
priority_csv = priority.to_csv(index=False).encode("utf-8-sig") if not priority.empty else b""
report = report_text(result).encode("utf-8")
d1, d2, d3 = st.columns(3)
d1.download_button("⬇️ All customer results", all_csv, "retainiq_customer_results.csv", "text/csv", use_container_width=True)
d2.download_button("⬇️ At-risk / inactive list", priority_csv, "retainiq_priority_customers.csv", "text/csv", use_container_width=True)
d3.download_button("⬇️ Business summary", report, "retainiq_business_report.txt", "text/plain", use_container_width=True)

st.caption("RetainIQ is an analytics aid. Validate the results against your business context before contacting customers or making decisions.")
