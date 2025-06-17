import pdfplumber
import re
import pandas as pd
import os
import streamlit as st

st.title("📄 PDF Invoice Extractor - United Medical Supply")

# File uploader
uploaded_files = st.file_uploader("Upload one or more PDF invoices", type="pdf", accept_multiple_files=True)

all_items = []
skipped_items_all = []

if uploaded_files:
    for uploaded_file in uploaded_files:
        pdf_file = uploaded_file.name
        print(f"\n📂 Processing: {pdf_file}")
        all_text = ""
        skipped_items = []

        # Step 1: Read full text
        with pdfplumber.open(uploaded_file) as pdf:
            for idx, page in enumerate(pdf.pages):
                print(f"📄 Reading page {idx + 1}")
                page_text = page.extract_text()
                if page_text:
                    all_text += page_text + "\n"

        lines = all_text.splitlines()

        invoice_number = None
        quantity_from_quantities_line = None

        for i, line in enumerate(lines):
            line = line.strip()

            # Extract Invoice number
            if re.search(r"Branch:\s*000\s+United Medical Supply Company", line, re.IGNORECASE):
                if i + 1 < len(lines):
                    candidate = lines[i + 1].strip()
                    if re.match(r"^\d{6,12}$", candidate):
                        invoice_number = candidate
                        print(f"🧾 Invoice #: {invoice_number}")

            # Capture quantity from "Quantities" section
            if "Quantities" in line and i + 1 < len(lines):
                qty_match = re.search(r"(\d+\.\d+)", lines[i + 1])
                if qty_match:
                    quantity_from_quantities_line = float(qty_match.group(1).strip())

            # Match full item line with item_id, uom, unit price and extended price
            item_line_match = re.search(
                r"\b(?P<item_id>[A-Z]{2,10}\d{2,})\b\s+(?P<uom>[A-Z]{2,3})\s+(?P<unit_price>\d+\.\d{2})\s+(?P<extended_price>\d+\.\d{2})",
                line
            )

            if item_line_match:
                item_id = item_line_match.group("item_id").strip()
                uom = item_line_match.group("uom")
                unit_price = float(item_line_match.group("unit_price"))
                extended_price = float(item_line_match.group("extended_price"))
                quantity = quantity_from_quantities_line if quantity_from_quantities_line else round(extended_price / unit_price, 2)

                # Look for description
                description = ""
                for offset in range(1, 4):
                    if i + offset < len(lines):
                        gl_line = lines[i + offset].strip()
                        if "GL-Code" in gl_line and "1.0" in gl_line:
                            desc_part = gl_line.split("1.0", 1)[-1].strip()
                            description = desc_part

                            # Look for unit/size info
                            if i + offset + 1 < len(lines):
                                next_line = lines[i + offset + 1].strip()
                                if re.search(r"\(?\d+/?\w+\)?", next_line):
                                    description += f" {next_line}"
                            break

                all_items.append({
                    "Invoice #": invoice_number,
                    "Item Number": item_id,
                    "Description": description,
                    "Quantity": quantity,
                    "UOM": uom,
                    "Unit Price": unit_price,
                    "Extended Price": extended_price,
                    "Source PDF": pdf_file
                })

            elif re.search(r"\bM?DL?OTC\d{4,}\w?\b", line):
                skipped_items.append(line)

        if skipped_items:
            skipped_items_all.extend([(pdf_file, line) for line in skipped_items])

    # Step 2: Build DataFrame and show results
    df = pd.DataFrame(all_items)
    df = df[["Source PDF", "Invoice #", "Item Number", "Description", "Quantity", "UOM", "Unit Price", "Extended Price"]]

    st.subheader("📊 Extracted Items")
    st.dataframe(df)

    if skipped_items_all:
        st.warning(f"⚠️ Skipped suspicious lines across all files: {len(skipped_items_all)}")
        for file, line in skipped_items_all[:10]:  # Preview first 10
            st.text(f"⛔ {file}: {line}")
    else:
        st.success("✅ No suspicious item-like lines were skipped.")
