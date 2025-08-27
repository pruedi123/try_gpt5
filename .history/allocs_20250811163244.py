"""
Unified module for extracting and aggregating Equity/Fixed allocations from PDFs,
adapted from the standalone toolkit.
"""

import os
import re
import sys
import csv
import glob
import argparse

import PyPDF2

# Patterns to capture dollar amounts after labels
LABEL_PATTERNS = {
    "equity": re.compile(r"(?i)\bEquity\b[^0-9\-]*([\$]?\s?[\d,]+(?:\.\d{1,2})?)"),
    "fixed_income": re.compile(r"(?i)\bFixed\s*Income\b[^0-9\-]*([\$]?\s?[\d,]+(?:\.\d{1,2})?)"),
    "cash": re.compile(r"(?i)\bCash\b[^0-9\-]*([\$]?\s?[\d,]+(?:\.\d{1,2})?)"),
    "total": re.compile(r"(?i)\bTotal\b[^0-9\-]*([\$]?\s?[\d,]+(?:\.\d{1,2})?)"),
}
NUMBER_CLEAN = re.compile(r"[^\d\.-]")

def parse_amounts(text: str):
    """Return dict with floats for equity, fixed_income, cash, total (None if missing)."""
    out = {"equity": None, "fixed_income": None, "cash": None, "total": None}
    for k, pat in LABEL_PATTERNS.items():
        m = pat.search(text)
        if m:
            raw = m.group(1)
            try:
                out[k] = float(NUMBER_CLEAN.sub("", raw))
            except ValueError:
                out[k] = None
    # If total missing but components present, compute
    if out["total"] is None and all(out[x] is not None for x in ("equity", "fixed_income", "cash")):
        out["total"] = (out["equity"] or 0) + (out["fixed_income"] or 0) + (out["cash"] or 0)
    # If exactly one component missing and total present, infer it
    comps = ["equity", "fixed_income", "cash"]
    known = [c for c in comps if out[c] is not None]
    if out["total"] is not None and len(known) == 2:
        missing = [c for c in comps if out[c] is None][0]
        out[missing] = out["total"] - sum(out[c] for c in known)
    return out

def extract_text_from_pdf(pdf_path):
    """
    Extracts text from a PDF file.
    """
    text = ""
    with open(pdf_path, 'rb') as file:
        reader = PyPDF2.PdfReader(file)
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
    return text

def aggregate_allocations_from_pdfs(pdf_files):
    """
    Aggregates allocation data from a list of PDF files.
    Returns a dictionary mapping file names to their allocation dictionaries.
    """
    results = {}
    for pdf_file in pdf_files:
        text = extract_text_from_pdf(pdf_file)
        amounts = parse_amounts(text)
        equity = amounts.get("equity")
        fixed_income = amounts.get("fixed_income")
        cash = amounts.get("cash")
        total = amounts.get("total")
        if total and equity is not None and fixed_income is not None and cash is not None and total != 0:
            pct_equity = (equity / total) * 100.0
            pct_fixed_incl_cash = ((fixed_income + cash) / total) * 100.0
        else:
            pct_equity = None
            pct_fixed_incl_cash = None
        results[os.path.basename(pdf_file)] = {"Equity": pct_equity, "Fixed": pct_fixed_incl_cash}
    return results

def write_aggregated_allocations_to_csv(aggregated_data, output_file):
    """
    Writes aggregated allocation data to a CSV file.
    """
    with open(output_file, 'w', newline='') as csvfile:
        fieldnames = ['File', 'Equity', 'Fixed']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for filename, allocations in aggregated_data.items():
            writer.writerow({
                'File': filename,
                'Equity': allocations.get('Equity', None),
                'Fixed': allocations.get('Fixed', None)
            })

def main():
    parser = argparse.ArgumentParser(description='Aggregate Equity/Fixed allocations from PDF files.')
    default_input_dir = os.path.join(os.path.dirname(__file__), "Downloads_2025-08-11")
    parser.add_argument(
        'input_dir',
        nargs='?',
        default=default_input_dir,
        help=f'Directory containing PDF files to process (default: Downloads_2025-08-11 folder in this project)'
    )
    parser.add_argument('-o', '--output', default='aggregated_allocations.csv',
                        help='Output CSV file name (default: aggregated_allocations.csv)')
    args = parser.parse_args()

    pdf_files = glob.glob(os.path.join(args.input_dir, '*.pdf'))
    if not pdf_files:
        print(f"No PDF files found in directory: {args.input_dir}")
        sys.exit(1)

    aggregated_data = aggregate_allocations_from_pdfs(pdf_files)
    write_aggregated_allocations_to_csv(aggregated_data, args.output)
    print(f"Aggregated allocation data written to {args.output}")

if __name__ == '__main__':
    main()
