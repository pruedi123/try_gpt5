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
from collections import defaultdict

import PyPDF2

# Regex patterns for extracting allocation data
ALLOCATION_PATTERN = re.compile(r'(Equity|Fixed).*?(\d{1,3}\.?\d*)%', re.IGNORECASE)
PAGE_HEADER_PATTERN = re.compile(r'Page \d+ of \d+', re.IGNORECASE)

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

def parse_allocations(text):
    """
    Parses allocation percentages from extracted text.
    Returns a dictionary with keys 'Equity' and 'Fixed' and their aggregated percentages.
    """
    allocations = defaultdict(float)
    for match in ALLOCATION_PATTERN.finditer(text):
        category = match.group(1).capitalize()
        percentage = float(match.group(2))
        allocations[category] += percentage
    return allocations

def aggregate_allocations_from_pdfs(pdf_files):
    """
    Aggregates allocation data from a list of PDF files.
    Returns a dictionary mapping file names to their allocation dictionaries.
    """
    results = {}
    for pdf_file in pdf_files:
        text = extract_text_from_pdf(pdf_file)
        allocations = parse_allocations(text)
        results[os.path.basename(pdf_file)] = allocations
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
                'Equity': allocations.get('Equity', 0.0),
                'Fixed': allocations.get('Fixed', 0.0)
            })

def main():
    parser = argparse.ArgumentParser(description='Aggregate Equity/Fixed allocations from PDF files.')
    parser.add_argument('input_dir', nargs='?', default='/Downloads_2025-08-11', help='Directory containing PDF files to process (default: /Downloads_2025-08-11)')
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
