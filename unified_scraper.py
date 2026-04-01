from playwright.sync_api import sync_playwright
import csv
import re
import os
import time
import urllib.parse
from difflib import SequenceMatcher
import pandas as pd


ECI_URL = "https://affidavit.eci.gov.in/"
MYNETA_URL = "https://www.myneta.info/"


# ============================================================
# HELPERS FROM extract2.py
# ============================================================

def clean_name(raw_name):
    """
    - Removes leading numbering like '1. ', '23. '
    - Normalizes 'Dr.', 'DR.', 'dr.' prefix to 'DR'
    - Removes relational suffixes like S/O, D/O, W/O
    """
    if not raw_name:
        return ""
    name = raw_name.strip()
    # Remove leading numbering
    name = re.sub(r"^\s*\d+\.\s*", "", name)
    # Normalize DR prefix (Dr., DR., dr. -> DR)
    name = re.sub(r"^(dr)\.\s*", "DR ", name, flags=re.IGNORECASE)
    # Remove relational suffixes (S/O, D/O, W/O and variants)
    name = re.split(
        r"\s+(S\/O|D\/O|W\/O)\s*[-:]?\s*",
        name,
        flags=re.IGNORECASE
    )[0]
    return name.strip()


def extract_year(text):
    m = re.search(r"\b(19|20)\d{2}\b", text)
    return m.group(0) if m else ""


def wait_for_select_ready(page, selector, timeout=30000):
    """Wait until a select has more than one option (helper for dependent selects)."""
    elapsed = 0
    while elapsed < timeout:
        if page.locator(f"{selector} option").count() > 1:
            # small pause to let the page update
            page.wait_for_timeout(500)
            return
        elapsed += 500
        page.wait_for_timeout(500)
    raise TimeoutError(f"{selector} not ready")


def normalize_text(s: str) -> str:
    """Lowercase, remove punctuation, and collapse whitespace."""
    if not s:
        return ""
    s = re.sub(r"[^\w\s]", "", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s)
    return s.strip().lower()


def similar(a: str, b: str) -> float:
    """Return similarity ratio between two strings (0..1)."""
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def clean_name_for_search(raw_name):
    if not raw_name:
        return ""

    name = raw_name.strip()

    # remove numbering like "1. "
    name = re.sub(r"^\s*\d+\.\s*", "", name)

    # remove everything after '('
    name = re.split(r"\(", name)[0]

    # remove ALIAS and everything after it
    name = re.split(r"\bALIAS\b", name, flags=re.IGNORECASE)[0]

    # remove @ and everything after it
    name = re.split(r"@", name)[0]

    # remove weird encoded quotes and everything after them
    name = re.split(r"[â€˜â€™'`]", name)[0]

    # convert MD. -> MD
    name = re.sub(r"\bMD\.\b", "MD", name, flags=re.IGNORECASE)

    # remove remaining dots
    name = name.replace(".", "")

    # remove extra spaces
    name = re.sub(r"\s+", " ", name)

    return name.strip()


def clean_constituency_for_search(constituency):
    if not constituency:
        return ""

    constituency = constituency.strip()

    if constituency.upper() == "BHOREY":
        return "BHORE (SC)"

    return constituency


# ============================================================
# HELPERS FROM extract_from_myneta.py
# ============================================================

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


# ============================================================
# MERGE HELPERS (from merge.py)
# ============================================================

def clean_name_for_merge(name):
    """Normalize names for matching during merge"""
    if pd.isna(name):
        return ""
    return (
        str(name)
        .lower()
        .replace(".", "")
        .replace(",", "")
        .strip()
    )


# ============================================================
# MAIN EXECUTION
# ============================================================

def main():
    print("=" * 70)
    print("UNIFIED SCRAPER - ECI + MyNeta Extraction + Merge")
    print("=" * 70)
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()

        # ========================================
        # PHASE 1: ECI SCRAPING
        # ========================================
        print("\n[PHASE 1] Starting ECI Scraping...")
        
        page = context.new_page()
        page.goto(ECI_URL)
        page.wait_for_selector("#electionType")

        # Fixed dropdown selections (test mode)
        page.select_option("#electionType", index=0)
        page.wait_for_timeout(1000)

        wait_for_select_ready(page, "#election")
        page.select_option("#election", index=1)

        wait_for_select_ready(page, "#states")
        page.select_option("#states", index=1)
        page.click("button[name='submitName']")
        page.wait_for_timeout(1500)
        page.click("//button[.//h4[text()='Contesting']]")
        page.wait_for_timeout(1500)

        MAX_ROWS = 4000

        candidates = []
        rows_extracted = 0

        while rows_extracted < MAX_ROWS:
            cards = page.locator("h4.bg-blu")
            total_cards = cards.count()
            
            for i in range(total_cards):
                if rows_extracted >= MAX_ROWS:
                    break
                    
                card = cards.nth(i)
                raw_name = card.inner_text().strip()
                name = clean_name(raw_name)
                td = card.locator("xpath=ancestor::td")

                party = td.locator(
                    "xpath=.//p[strong[normalize-space()='Party :']]"
                ).first.inner_text().replace("Party :", "").strip()
                status = td.locator(
                    "xpath=.//p[strong[normalize-space()='Status :']]"
                ).first.inner_text().replace("Status :", "").strip()
                state = td.locator(
                    "xpath=.//p[strong[normalize-space()='State :']]"
                ).first.inner_text().replace("State :", "").strip()
                constituency = td.locator(
                    "xpath=.//p[strong[normalize-space()='Constituency :']]"
                ).first.inner_text().replace("Constituency :", "").strip()

                father = address = gender = age = year = eci_link = ""
                view_more = td.locator("a:has-text('View more')")

                if view_more.count():
                    eci_link = view_more.first.get_attribute("href") or ""
                    with context.expect_page() as p2:
                        view_more.first.click()
                    profile = p2.value
                    profile.wait_for_load_state("domcontentloaded")

                    father = profile.locator(
                        "xpath=//div[@class='form-group'][.//p[contains(normalize-space(),'Father')]]//div[@class='col-sm-6']/p"
                    ).first.inner_text().strip()
                    address = profile.locator(
                        "xpath=//div[@class='form-group'][.//p[normalize-space()='Address:']]//div[@class='col-sm-6']/p"
                    ).first.inner_text().strip()
                    gender = profile.locator(
                        "xpath=//div[@class='form-group'][.//p[normalize-space()='Gender:']]//div[@class='col-sm-6']/p"
                    ).first.inner_text().strip()
                    age = profile.locator(
                        "xpath=//div[@class='form-group'][.//p[normalize-space()='Age:']]//div[@class='col-sm-6']/p"
                    ).first.inner_text().strip()

                    uploaded_text = profile.locator(
                        "xpath=//div[@class='row'][.//p[strong[normalize-space()='Application Uploaded:']]]"
                        "/div[@class='col-sm-6'][2]//p"
                    ).first.inner_text().strip()
                    year = extract_year(uploaded_text)

                    profile.close()    
                    
                print("ECI:", name, year)
                candidates.append({
                    "Name": name,
                    "Party": party,
                    "Status": status,
                    "State": state,
                    "Constituency": constituency,
                    "Father/Husband": father,
                    "Address": address,
                    "Gender": gender,
                    "Age": age,
                    "Year": year,
                    "eci_link": eci_link,
                    "neta_link": "",
                })
                rows_extracted += 1

            # Check for "Next" button to load more rows
            next_button = page.locator("a:has-text('Next')")
            if next_button.count() > 0 and rows_extracted < MAX_ROWS:
                try:
                    next_button.first.click()
                    page.wait_for_timeout(1500)
                    continue
                except Exception:
                    break
            else:
                break

        print(f"[PHASE 1] Extracted {len(candidates)} candidates from ECI")

        # ========================================
        # PHASE 2: MYNETA LINK MAPPING
        # ========================================
        print("\n[PHASE 2] Starting MyNeta Link Mapping...")
        
        myneta = context.new_page()
        myneta.goto(MYNETA_URL)
        myneta.wait_for_selector("input[name='q']")

        def search_myneta_for_candidate(page, name, constituency, year):
            """Simpler search that uses the clean helpers and a single attempt."""
            name_norm = normalize_text(name)
            const_norm = normalize_text(constituency)

            # always reset to homepage first
            page.goto(MYNETA_URL)
            page.wait_for_selector("input[name='q']", timeout=5000)

            sb = page.locator("input[name='q']")
            sb.fill("")
            sb.fill(name)
            sb.press("Enter")

            page.wait_for_timeout(1500)
            rows = page.locator("table.w3-table tbody tr")

            if rows.count() == 0:
                return ""

            for i in range(rows.count()):
                r = rows.nth(i)
                if r.locator("td").count() < 4 or r.locator("a").count() == 0:
                    continue

                cname_raw = r.locator("a").first.inner_text().strip()
                cconst_raw = r.locator("td:nth-child(3)").inner_text().strip()
                election_raw = r.locator("td:nth-child(4)").inner_text().strip()

                cname = normalize_text(cname_raw)
                cconst = normalize_text(cconst_raw)

                name_sim = similar(name_norm, cname)
                name_ok = (name_norm in cname) or (name_sim >= 0.70)

                const_ok = False
                if not const_norm:
                    const_ok = True
                elif const_norm in cconst:
                    const_ok = True
                elif len(set(const_norm.split()) & set(cconst.split())) > 0:
                    const_ok = True

                year_ok = True
                if year:
                    year_ok = str(year) in election_raw

                if name_ok and const_ok and year_ok:
                    link = r.locator("a").first.get_attribute("href")
                    if link and link.startswith("/"):
                        link = "https://www.myneta.info" + link
                    return link or ""

            return ""

        # search for each candidate
        for c in candidates:
            # skip ones that already have a link
            if c.get("neta_link"):
                continue

            original_name = c["Name"]
            search_name = clean_name_for_search(original_name)
            search_const = clean_constituency_for_search(c.get("Constituency", ""))

            print("Original:", original_name)
            print("Searching as:", search_name)

            link = search_myneta_for_candidate(
                myneta,
                search_name,
                search_const,
                c.get("Year", "")
            )

            c["neta_link"] = link or ""
            print("Found:", link)
            print("MyNeta:", c["Name"], c["neta_link"])
            print("-" * 50)

        print(f"[PHASE 2] MyNeta link mapping complete")

        # ========================================
        # PHASE 3: EXTRACT MYNETA DETAILS
        # ========================================
        print("\n[PHASE 3] Starting MyNeta Details Extraction...")
        
        myneta_results = []

        for c in candidates:
            link = c.get("neta_link", "").strip()
            if not link:
                continue

            print("Opening:", link)
            page = context.new_page()
            try:
                page.goto(link, timeout=60000)
                page.wait_for_load_state("domcontentloaded")

                # EDUCATION (CATEGORY ONLY)
                edu_raw = safe_text(
                    page.locator(
                        "xpath=//h3[normalize-space()='Educational Details']/parent::*"
                    )
                )
                education = extract_education_category(edu_raw)
                
                # PROFESSION
                prof_raw = safe_text(
                    page.locator("xpath=//p[b[normalize-space()='Self Profession:']]")
                )
                profession = extract_self_profession(prof_raw)

                # ASSETS & LIABILITIES
                assets_text = safe_text(
                    page.locator("xpath=//td[normalize-space()='Assets:']/following-sibling::td[1]")
                )
                liabilities_text = safe_text(
                    page.locator("xpath=//td[normalize-space()='Liabilities:']/following-sibling::td[1]")
                )

                assets = extract_amount(assets_text)
                liabilities = extract_amount(liabilities_text)
                net_worth = max(assets - liabilities, 0)

                # INCOME
                income = extract_income(page)

                # CRIMINAL CASES
                criminal_cases = extract_criminal_cases(page)

                myneta_results.append({
                    "Name": c["Name"],
                    "Education": education,
                    "Profession": profession,
                    "Net_Worth": net_worth,
                    "Networth Unit": format_unit(net_worth),
                    "Income": income,
                    "Income Unit": format_unit(income),
                    "Criminal_Cases": criminal_cases
                })

                print("Extracted:", c["Name"])
            except Exception as e:
                print(f"Error extracting {c['Name']}: {e}")
            finally:
                page.close()

        print(f"[PHASE 3] Extracted details for {len(myneta_results)} candidates")

        browser.close()

        # ========================================
        # PHASE 4: MERGE ALL DATA
        # ========================================
        print("\n[PHASE 4] Merging Data...")
        
        # Convert candidates to DataFrame
        eci_df = pd.DataFrame(candidates)
        
        # Convert myneta results to DataFrame
        myneta_df = pd.DataFrame(myneta_results)

        # Normalize names for matching
        eci_df["match_name"] = eci_df["Name"].apply(clean_name_for_merge)
        myneta_df["match_name"] = myneta_df["Name"].apply(clean_name_for_merge)

        merged_rows = []

        i = 0
        j = 0

        while i < len(eci_df) and j < len(myneta_df):
            e_name = eci_df.loc[i, "match_name"]
            m_name = myneta_df.loc[j, "match_name"]

            if e_name == m_name:
                merged = {**eci_df.loc[i].to_dict(), **myneta_df.loc[j].to_dict()}
                merged_rows.append(merged)

                i += 1
                j += 1

            else:
                # skip ECI row until names match
                merged = eci_df.loc[i].to_dict()
                merged_rows.append(merged)
                i += 1

        # If ECI still has remaining rows
        while i < len(eci_df):
            merged_rows.append(eci_df.loc[i].to_dict())
            i += 1

        merged_df = pd.DataFrame(merged_rows)

        # drop helper column
        merged_df = merged_df.drop(columns=["match_name"], errors="ignore")

        # ========================================
        # SAVE ALL OUTPUT FILES
        # ========================================
        print("\n[SAVING] Writing output files...")
        
        # Save ECI with MyNeta links
        eci_output = "eci_candidates_with_neta.csv"
        eci_df.to_csv(eci_output, index=False, encoding="utf-8")
        print(f"✓ Saved: {os.path.abspath(eci_output)}")

        # Save MyNeta extracted details
        myneta_output = "myneta_extracted_details.csv"
        myneta_df.to_csv(myneta_output, index=False, encoding="utf-8")
        print(f"✓ Saved: {os.path.abspath(myneta_output)}")

        # Save merged result
        merged_output = "merged_candidates.csv"
        merged_df.to_csv(merged_output, index=False, encoding="utf-8")
        print(f"✓ Saved: {os.path.abspath(merged_output)}")

        print("\n" + "=" * 70)
        print("Pipeline Complete!")
        print(f"Total candidates processed: {len(merged_df)}")
        print("=" * 70)


if __name__ == "__main__":
    main()
