from playwright.sync_api import sync_playwright
import csv
import re
import os

INPUT_CSV = "eci_candidates_with_neta.csv"

BASE_DIR = os.path.dirname(os.path.abspath(INPUT_CSV))
OUTPUT_CSV = os.path.join(BASE_DIR, "myneta_extracted_details.csv")

# ---------------- HELPERS ----------------
def safe_text(locator):
    try:
        return locator.first.inner_text().strip() if locator.count() else ""
    except:
        return ""

def extract_amount(text):
    """
    Extracts raw number from strings like:
    'Rs 2,60,000 ~2 Lacs+' -> 260000
    'Nil' -> 0

    Implementation notes:
    - Ignore anything after a tilde (~) which is an approximate alternate formatting.
    - Use the first numeric group on the left-hand side.
    """
    if not text or "nil" in text.lower():
        return 0

    # only consider the primary (left) value before any '~' approximate marker
    text = text.split('~', 1)[0]

    # remove commas and find the first numeric group
    cleaned = text.replace(",", "")
    nums = re.findall(r"\d+", cleaned)
    return int(nums[0]) if nums else 0

def extract_self_profession(raw):
    """
    Extracts ONLY self profession, removes spouse profession completely
    """
    if not raw:
        return ""

    text = raw.replace("\n", " ").strip()

    if "Self Profession:" in text:
        text = text.split("Self Profession:")[-1]

    if "Spouse Profession:" in text:
        text = text.split("Spouse Profession:")[0]

    return text.strip()

def extract_education_category(raw):
    """
    Extracts only education category.
    Stops at first quote, parenthesis, or the word ' from '.
    Returns a short category (e.g. 'Post Graduate', 'Doctorate', 'Graduate Professional', 'Literate', '10th Pass').
    """
    if not raw:
        return ""

    text = raw.replace("\n", " ").strip()

    if "Category:" not in text:
        return ""

    text = text.split("Category:", 1)[1].strip()

    # truncate at common delimiters
    delimiters = ['"', '(', ' from ', '\n']
    cut = len(text)
    for d in delimiters:
        idx = text.find(d)
        if idx != -1:
            cut = min(cut, idx)
    text = text[:cut].strip()

    # normalize whitespace
    text = re.sub(r'\s+', ' ', text)

    # return first two words (covers most categories like 'Post Graduate', 'Graduate Professional')
    tokens = text.split()
    if not tokens:
        return ""

    if len(tokens) == 1:
        result = tokens[0]
    else:
        # Collapse duplicate adjacent tokens like 'Literate Literate' -> 'Literate'
        if tokens[0].lower() == tokens[1].lower():
            result = tokens[0]
        else:
            result = ' '.join(tokens[:2])

    # preserve original casing to avoid mangling tokens like '10th'
    return result.strip()



def extract_income(page):
    """
    Extracts ONLY the numeric income (e.g. 70067)
    """
    try:
        td = page.locator("table#income_tax tbody tr td").nth(3)
        raw = td.locator("b").first.inner_text()
        nums = re.findall(r"\d+", raw.replace(",", ""))
        return int("".join(nums)) if nums else 0
    except:
        return 0
    
def additional_helpers():
    pass

def extract_criminal_cases(page):
    """
    Correct Crime-O-Meter extraction:
    - 'No criminal cases' -> 0
    - 'X criminal cases' -> X
    """
    try:
        text = page.locator("text=/criminal cases/i").first.inner_text().lower()

        if "no criminal" in text:
            return 0

        nums = re.findall(r"\d+", text)
        return int(nums[0]) if nums else 0
    except:
        return 0

# ---------------- MAIN ----------------

def format_unit(amount):
    """
    Formats an integer amount (rupees) into Indian-style units.
    Examples:
      60000 -> '60 Thousand'
      800000 -> '8 Lakhs'
      15000000 -> '1.5 Crore'
    """
    try:
        a = int(amount)
    except:
        return ""

    if a <= 0:
        return "0"

    # Crore (1 Crore = 10,000,000)
    if a >= 10_000_000:
        val = a // 10_000_000
        return f"{val} Crore"
    # Lakh (1 Lakh = 100,000)
    if a >= 100_000:
        val = a // 100_000
        return f"{val} Lakh"
    # Thousand
    if a >= 1_000:
        val = a // 1_000
        return f"{val} Thousand"

    return str(a)

def run_extraction():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()

        results = []

        with open(INPUT_CSV, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

        for row in rows:
            link = row.get("neta_link", "").strip()
            if not link:
                continue

            print("Opening:", link)
            page = context.new_page()
            page.goto(link, timeout=60000)
            page.wait_for_load_state("domcontentloaded")

            # ---------------- EDUCATION (CATEGORY ONLY) ----------------


            edu_raw = safe_text(
                page.locator(
                    "xpath=//h3[normalize-space()='Educational Details']/parent::*"
                )
            )
            education = extract_education_category(edu_raw)
            
            # ---------------- PROFESSION ----------------
            prof_raw = safe_text(
                page.locator("xpath=//p[b[normalize-space()='Self Profession:']]")
            )
            profession = extract_self_profession(prof_raw)

            # ---------------- ASSETS & LIABILITIES ----------------
            assets_text = safe_text(
                page.locator("xpath=//td[normalize-space()='Assets:']/following-sibling::td[1]")
            )
            liabilities_text = safe_text(
                page.locator("xpath=//td[normalize-space()='Liabilities:']/following-sibling::td[1]")
            )

            assets = extract_amount(assets_text)
            liabilities = extract_amount(liabilities_text)
            net_worth = max(assets - liabilities, 0)

            # ---------------- INCOME ----------------
            income = extract_income(page)

            # ---------------- CRIMINAL CASES ----------------
            criminal_cases = extract_criminal_cases(page)

            page.close()

            results.append({
                "Name": row["Name"],
                "Education": education,
                "Profession": profession,
                "Net_Worth": net_worth,
                "Networth Unit": format_unit(net_worth),
                "Income": income,
                "Income Unit": format_unit(income),
                "Criminal_Cases": criminal_cases
            })

            print("Extracted:", row["Name"])

        # ---------------- SAVE CSV ----------------


        with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "Name",
                    "Education",
                    "Profession",
                    "Net_Worth",
                    "Networth Unit",
                    "Income",
                    "Income Unit",
                    "Criminal_Cases"
                ]
            )
            writer.writeheader()
            writer.writerows(results)

        print("\nSaved:", OUTPUT_CSV)
        browser.close()


if __name__ == "__main__":
    run_extraction()
