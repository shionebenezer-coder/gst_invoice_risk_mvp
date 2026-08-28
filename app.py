import os
from datetime import date
import pandas as pd
import streamlit as st

try:
    from google import genai
except Exception:
    genai = None

st.set_page_config(page_title="Invoice Risk & Collections MVP", layout="wide")

st.title("Invoice Risk & Collections MVP")
st.caption(
    "Upload invoices and buyer payment history, score collection risk, "
    "generate collection messages, and flag invoices that may be suitable for discounting."
)

# ----------------------------
# Helpers
# ----------------------------

def normalize_gstin(value):
    if pd.isna(value):
        return ""
    return str(value).strip().upper()

def risk_score(row):
    """
    Heuristic MVP score, 0-100.
    Higher = higher collection risk.
    Replace with a trained model once you have enough repayment data.
    """
    score = 0.0

    days_overdue = max(float(row.get("days_overdue", 0) or 0), 0)
    avg_delay = max(float(row.get("avg_payment_delay_days", 0) or 0), 0)
    late_ratio = min(max(float(row.get("late_payment_ratio", 0) or 0), 0), 1)
    disputes = max(float(row.get("dispute_count", 0) or 0), 0)
    prior_defaults = max(float(row.get("prior_default_count", 0) or 0), 0)
    gst_status = str(row.get("gst_status", "UNKNOWN")).upper()

    score += min(days_overdue / 90, 1) * 30
    score += min(avg_delay / 60, 1) * 20
    score += late_ratio * 20
    score += min(disputes / 5, 1) * 10
    score += min(prior_defaults / 3, 1) * 15

    if gst_status not in {"ACTIVE", "VALID"}:
        score += 5

    return round(min(score, 100), 1)

def risk_band(score):
    if score >= 70:
        return "High"
    if score >= 40:
        return "Medium"
    return "Low"

def suggested_action(row):
    score = row["risk_score"]
    overdue = float(row.get("days_overdue", 0) or 0)

    if score >= 70:
        return "Immediate phone + email escalation; pause new unsecured credit; review financing/insurance."
    if score >= 40:
        return "Send firm reminder; schedule follow-up in 3 days; tighten future credit terms."
    if overdue > 0:
        return "Send friendly reminder and confirm expected payment date."
    return "No collection action yet; monitor."

def discounting_flag(row):
    amount = float(row.get("invoice_amount", 0) or 0)
    score = row["risk_score"]
    overdue = float(row.get("days_overdue", 0) or 0)

    if amount >= 100000 and score < 70 and overdue <= 30:
        return "Potential candidate"
    return "Review manually"

def fallback_message(row, tone):
    buyer = row.get("buyer_name", "Customer")
    invoice = row.get("invoice_number", "")
    amount = row.get("invoice_amount", "")
    due = row.get("due_date", "")
    overdue = int(float(row.get("days_overdue", 0) or 0))

    if tone == "Friendly":
        return (
            f"Hello {buyer}, this is a reminder that invoice {invoice} for ₹{amount} "
            f"was due on {due}. It is currently {overdue} day(s) overdue. "
            "Could you please confirm the expected payment date? Thank you."
        )
    if tone == "Firm":
        return (
            f"Hello {buyer}, invoice {invoice} for ₹{amount} remains unpaid "
            f"{overdue} day(s) after its due date ({due}). Please arrange payment "
            "or share a confirmed payment date today."
        )
    return (
        f"Dear {buyer}, our records show invoice {invoice} for ₹{amount} remains outstanding "
        f"{overdue} day(s) beyond the due date of {due}. Please treat this as an escalation "
        "and confirm settlement arrangements immediately."
    )

def ai_message(row, tone):
    if genai is None or not os.getenv("GEMINI_API_KEY"):
        return fallback_message(row, tone)

    try:
        client = genai.Client()
        prompt = f"""
Write a short B2B invoice collection message for an Indian SME.
Tone: {tone}
Buyer: {row.get('buyer_name')}
Invoice number: {row.get('invoice_number')}
Invoice amount INR: {row.get('invoice_amount')}
Due date: {row.get('due_date')}
Days overdue: {row.get('days_overdue')}
Risk band: {row.get('risk_band')}

Requirements:
- Professional, concise, non-threatening.
- Ask for payment or a confirmed payment date.
- Do not invent legal claims.
- Do not mention AI or risk scoring.
"""
        response = client.models.generate_content(
            model="gemini-flash-latest",
            contents=prompt
        )
        return response.text.strip()
    except Exception:
        return fallback_message(row, tone)

# ----------------------------
# Sidebar
# ----------------------------

st.sidebar.header("Data")
st.sidebar.write(
    "For this MVP, GST status is supplied in your buyer/payment-history file. "
    "A production version should use an authorized GST data provider/API rather than scraping."
)

invoice_file = st.sidebar.file_uploader("Invoices CSV", type=["csv"])
history_file = st.sidebar.file_uploader("Buyer history CSV", type=["csv"])

st.sidebar.markdown("**Required invoice columns**")
st.sidebar.code(
    "invoice_number,buyer_name,gstin,invoice_amount,invoice_date,due_date",
    language="text"
)

st.sidebar.markdown("**Required buyer-history columns**")
st.sidebar.code(
    "gstin,gst_status,avg_payment_delay_days,late_payment_ratio,dispute_count,prior_default_count",
    language="text"
)

# ----------------------------
# User data
# ----------------------------

if invoice_file is None or history_file is None:
    st.info("Upload your invoices and buyer payment history from the sidebar to begin.")
    st.stop()

invoices = pd.read_csv(invoice_file)
history = pd.read_csv(history_file)

# ----------------------------
# Validation and scoring
# ----------------------------

required_invoice = {
    "invoice_number", "buyer_name", "gstin",
    "invoice_amount", "invoice_date", "due_date"
}
required_history = {
    "gstin", "gst_status", "avg_payment_delay_days",
    "late_payment_ratio", "dispute_count", "prior_default_count"
}

missing_i = required_invoice - set(invoices.columns)
missing_h = required_history - set(history.columns)

if missing_i:
    st.error(f"Invoices CSV is missing columns: {sorted(missing_i)}")
    st.stop()

if missing_h:
    st.error(f"Buyer history CSV is missing columns: {sorted(missing_h)}")
    st.stop()

invoices["gstin"] = invoices["gstin"].map(normalize_gstin)
history["gstin"] = history["gstin"].map(normalize_gstin)

invoices["due_date"] = pd.to_datetime(invoices["due_date"], errors="coerce")
invoices["invoice_date"] = pd.to_datetime(invoices["invoice_date"], errors="coerce")

today = pd.Timestamp(date.today())
invoices["days_overdue"] = (today - invoices["due_date"]).dt.days.clip(lower=0)

df = invoices.merge(history, on="gstin", how="left")

for col, default in {
    "gst_status": "UNKNOWN",
    "avg_payment_delay_days": 0,
    "late_payment_ratio": 0,
    "dispute_count": 0,
    "prior_default_count": 0
}.items():
    df[col] = df[col].fillna(default)

df["risk_score"] = df.apply(risk_score, axis=1)
df["risk_band"] = df["risk_score"].map(risk_band)
df["suggested_action"] = df.apply(suggested_action, axis=1)
df["invoice_discounting"] = df.apply(discounting_flag, axis=1)

# ----------------------------
# Dashboard
# ----------------------------

total_outstanding = df["invoice_amount"].sum()
high_risk_amount = df.loc[df["risk_band"] == "High", "invoice_amount"].sum()
overdue_amount = df.loc[df["days_overdue"] > 0, "invoice_amount"].sum()

c1, c2, c3, c4 = st.columns(4)
c1.metric("Invoices", len(df))
c2.metric("Outstanding", f"₹{total_outstanding:,.0f}")
c3.metric("Overdue", f"₹{overdue_amount:,.0f}")
c4.metric("High-risk exposure", f"₹{high_risk_amount:,.0f}")

st.subheader("Risk dashboard")

display_cols = [
    "invoice_number", "buyer_name", "gstin", "invoice_amount",
    "due_date", "days_overdue", "gst_status",
    "risk_score", "risk_band", "invoice_discounting", "suggested_action"
]

st.dataframe(
    df[display_cols].sort_values(["risk_score", "days_overdue"], ascending=False),
    use_container_width=True,
    hide_index=True
)

csv = df.to_csv(index=False).encode("utf-8")
st.download_button(
    "Download scored invoices",
    data=csv,
    file_name="scored_invoices.csv",
    mime="text/csv"
)

# ----------------------------
# Collections workflow
# ----------------------------

st.subheader("Collection message generator")

selected_invoice = st.selectbox(
    "Choose invoice",
    df["invoice_number"].astype(str).tolist()
)

tone = st.selectbox("Tone", ["Friendly", "Firm", "Escalation"])

selected = df[df["invoice_number"].astype(str) == str(selected_invoice)].iloc[0]

if st.button("Generate collection message"):
    message = ai_message(selected, tone)
    st.text_area("Message", message, height=180)

# ----------------------------
# Financing placeholder
# ----------------------------

st.subheader("Invoice-discounting triage")
st.write(
    "This MVP only flags invoices for review. A production system would connect to "
    "licensed banks/NBFCs/TReDS participants and show actual eligibility, pricing, and consent flows."
)

candidates = df[df["invoice_discounting"] == "Potential candidate"][
    ["invoice_number", "buyer_name", "invoice_amount", "days_overdue", "risk_score"]
]

if len(candidates):
    st.dataframe(candidates, use_container_width=True, hide_index=True)
else:
    st.info("No invoices currently meet the simple MVP criteria.")
