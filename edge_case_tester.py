from playwright.sync_api import sync_playwright
import csv
import re
from difflib import SequenceMatcher

MYNETA_URL = "https://www.myneta.info/"
INPUT_FILE = "eci_candidates_with_neta.csv"
OUTPUT_FILE = "eci_candidates_with_neta_updated.csv"


# ---------------- HELPERS ----------------

def normalize_text(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"[^\w\s]", "", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip().lower()


def similar(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


# 🔥 Clean name ONLY for searching
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


# ---------------- MYNETA SEARCH FUNCTION (FAST VERSION) ----------------

def search_myneta_for_candidate(page, name, constituency, year):
    name_norm = normalize_text(name)
    const_norm = normalize_text(constituency)

    # 🔥 ALWAYS reset to homepage first
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

# ---------------- MAIN ----------------

# Read CSV
candidates = []
with open(INPUT_FILE, "r", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
        candidates.append(row)


with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()

    page.goto(MYNETA_URL)
    page.wait_for_selector("input[name='q']")

    for c in candidates:

        # 🔥 Skip already found ones
        if c.get("neta_link"):
            continue

        original_name = c["Name"]
        search_name = clean_name_for_search(original_name)
        search_const = clean_constituency_for_search(c.get("Constituency", ""))

        print("Original:", original_name)
        print("Searching as:", search_name)

        link = search_myneta_for_candidate(
            page,
            search_name,
            search_const,
            c.get("Year", "")
        )

        c["neta_link"] = link or ""
        print("Found:", link)
        print("-" * 50)

    browser.close()


# Save Updated CSV
with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=candidates[0].keys())
    writer.writeheader()
    writer.writerows(candidates)

print("\nSaved:", OUTPUT_FILE)