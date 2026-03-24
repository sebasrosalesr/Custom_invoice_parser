import streamlit as st
import pdfplumber
import re
import pandas as pd

st.title("📄 PDF Invoice Extractor - Medline")

uploaded_files = st.file_uploader(
    "Upload Medline PDF invoices",
    type="pdf",
    accept_multiple_files=True
)

all_items = []


def extract_invoice_date(lines):
    """Find the first invoice date in the PDF text."""
    for line in lines:
        line = line.strip()
        match = re.match(r"^\S+\s+(\d{2}/\d{2}/\d{4})\s+(\d{9,12})$", line)
        if match:
            return match.group(1)
    return None


def extract_amount_due_fallback(lines, start_index):
    """
    Try to capture invoice total near 'AMOUNT DUE'.
    Looks ahead a few lines in case PDF text is split oddly.
    """
    for j in range(start_index, min(start_index + 4, len(lines))):
        amount_match = re.search(r"\$?\(?([\d,]+\.\d{2})\)?", lines[j])
        if amount_match:
            return float(amount_match.group(1).replace(",", ""))
    return None


if uploaded_files:
    for uploaded_file in uploaded_files:
        pdf_file = uploaded_file.name
        st.write(f"📂 Processing: {pdf_file}")

        all_text = ""

        with pdfplumber.open(uploaded_file) as pdf:
            for idx, page in enumerate(pdf.pages):
                st.write(f"📄 Reading page {idx + 1}")
                page_text = page.extract_text()
                if page_text:
                    all_text += page_text + "\n"

        lines = all_text.splitlines()
        invoice_date = extract_invoice_date(lines)

        current_invoice = None
        current_total = None
        i = 0

        while i < len(lines):
            line = lines[i].strip()

            # Detect invoice number
            invoice_match = re.search(r"\b(\d{9,12})\b$", line)
            if invoice_match:
                current_invoice = invoice_match.group(1)
                st.write(f"🧾 Invoice #: {current_invoice}")
                current_total = None

            # Detect total amount near AMOUNT DUE
            if "AMOUNT DUE" in line.upper():
                detected_total = extract_amount_due_fallback(lines, i + 1)
                if detected_total is not None:
                    current_total = detected_total
                    st.write(f"💵 Total for invoice {current_invoice}: {current_total}")

            # Match item line
            item_match = re.match(
                r"^\d+\s+"
                r"(?P<qty>\d+\.\d{2})\s+"
                r"(?P<uom>\w+)\s+"
                r"(?P<inv_qty>\d+\.\d{2})\s+"
                r"(?P<item>[A-Z0-9\-]+)"
                r"(?:[A-Z])?"
                r"(?:\s+(?:TE\s+)?(?P<delivery>\d{5,}))?"
                r"(?:\s+(?P<unit_price>[\d,]+\.\d{2}))?"
                r"(?:\s+(?P<amount>[\d,]+\.\d{2}))?",
                line
            )

            if item_match:
                qty = float(item_match.group("qty"))
                uom = item_match.group("uom")
                item_num = item_match.group("item").strip("-.,").upper()
                delivery = item_match.group("delivery")

                unit_price_str = item_match.group("unit_price")
                amount_str = item_match.group("amount")

                unit_price = float(unit_price_str.replace(",", "")) if unit_price_str else None
                amount = float(amount_str.replace(",", "")) if amount_str else None

                description = ""
                if i + 1 < len(lines):
                    next_line = lines[i + 1].strip()
                    if next_line.startswith("/"):
                        description = next_line[1:].strip()
                        i += 1

                if current_invoice:
                    all_items.append({
                        "PDF File": pdf_file,
                        "Invoice #": current_invoice,
                        "Invoice Date": invoice_date,
                        "Item Number": item_num,
                        "Description": description,
                        "Quantity": qty,
                        "UOM": uom,
                        "Unit Price": unit_price,
                        "Spend": amount,
                        "Total Invoice": current_total,
                        "Delivery #": delivery
                    })
                else:
                    st.warning(f"⚠️ Skipped item — no invoice number set for: {item_num}")

            i += 1

    df_all = pd.DataFrame(all_items)

    if not df_all.empty:
        # Fallback: if Total Invoice is missing, fill it with sum of Spend per invoice
        computed_totals = (
            df_all.groupby("Invoice #", dropna=False)["Spend"]
            .sum(min_count=1)
            .reset_index()
            .rename(columns={"Spend": "Computed Total Invoice"})
        )

        df_all = df_all.merge(computed_totals, on="Invoice #", how="left")
        df_all["Total Invoice"] = df_all["Total Invoice"].fillna(df_all["Computed Total Invoice"])
        df_all.drop(columns=["Computed Total Invoice"], inplace=True)

        # Optional validation check: compare extracted total vs computed spend total
        validation = (
            df_all.groupby("Invoice #", dropna=False)
            .agg(
                Extracted_Total=("Total Invoice", "first"),
                Summed_Spend=("Spend", lambda x: x.sum(min_count=1))
            )
            .reset_index()
        )

        validation["Difference"] = validation["Extracted_Total"] - validation["Summed_Spend"]
        validation["Difference"] = validation["Difference"].round(2)

        mismatches = validation[
            validation["Extracted_Total"].notna() &
            validation["Summed_Spend"].notna() &
            (validation["Difference"].abs() > 0.01)
        ]

        st.subheader("📊 Extracted Items")
        st.dataframe(df_all)

        csv = df_all.to_csv(index=False).encode("utf-8")
        st.download_button(
            "📥 Download CSV",
            data=csv,
            file_name="medline_items_extracted.csv",
            mime="text/csv"
        )

        if df_all["Spend"].isna().any():
            st.warning("⚠️ Some items are missing Spend values:")
            st.dataframe(
                df_all[df_all["Spend"].isna()][["Invoice #", "Item Number", "Description"]]
            )

        if df_all["Total Invoice"].isna().any():
            st.warning("⚠️ Some invoices still have missing Total Invoice values after fallback:")
            st.dataframe(
                df_all[df_all["Total Invoice"].isna()][["Invoice #"]].drop_duplicates()
            )

        if not mismatches.empty:
            st.warning("⚠️ Some invoices have a mismatch between Total Invoice and summed Spend:")
            st.dataframe(mismatches)

    else:
        st.error("❌ No valid items extracted from the uploaded PDFs.")
