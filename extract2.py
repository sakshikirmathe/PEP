from playwright.sync_api import sync_playwright
import csv
import re
import os
import time
import urllib.parse
from difflib import SequenceMatcher


ECI_URL = "https://affidavit.eci.gov.in/"
MYNETA_URL = "https://www.myneta.info/"


# ---------------- HELPERS ----------------
def clean_name(raw_name):
    """Removes leading numbers like '1. ', '23. ' etc."""
    return re.sub(r"^\s*\d+\.\s*", "", raw_name).strip()

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


# ---------------- HELPERS (search robustness) ----------------
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


# ---------------- MAIN ----------------
with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    context = browser.new_context()
    

    ########################################
    # PHASE 1 — ECI SCRAPING
    ########################################
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

    wait_for_select_ready(page, "#phase")
    page.select_option("#phase", index=1)

    wait_for_select_ready(page, "#constId")
    page.select_option("#constId", index=1)

    page.click("button[name='submitName']")
    page.wait_for_timeout(1500)
    page.click("//button[.//h4[text()='Contesting']]")
    page.wait_for_timeout(1500)

    cards = page.locator("h4.bg-blu")
    MAX_ROWS = 10  # 🔴 increase later

    candidates = []
    total_cards = cards.count()
    for i in range(min(total_cards, MAX_ROWS)):
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

        father = address = gender = age = year = ""
        view_more = td.locator("a:has-text('View more')")

        if view_more.count():
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
            "neta_link": "",
        })

    ########################################
    # PHASE 2 — MYNETA LINK MAPPING (robust)
    ########################################
    myneta = context.new_page()
    myneta.goto(MYNETA_URL)
    myneta.wait_for_selector("input[name='q']")

    def search_myneta_for_candidate(page, name, constituency, year, max_retries=3):
        """Try multiple search approaches and use fuzzy matching to find best link."""
        from urllib.parse import quote_plus

        tried_urls = set()
        name_norm = normalize_text(name)
        const_norm = normalize_text(constituency)

        for attempt in range(1, max_retries + 1):
            # Primary: use site search box if present
            try:
                if page.locator("input[name='q']").count():
                    sb = page.locator("input[name='q']")
                    sb.fill("")
                    sb.fill(name)
                    sb.press("Enter")
                else:
                    page.goto(MYNETA_URL)
                    page.wait_for_selector("input[name='q']", timeout=5000)
                    sb = page.locator("input[name='q']")
                    sb.fill(name)
                    sb.press("Enter")
            except Exception:
                # ignore and fall through to direct search
                pass

            # Wait for results table to appear (or try direct search URL)
            try:
                page.wait_for_selector("table.w3-table > tbody > tr", timeout=7000)
            except Exception:
                # fallback to direct search URL
                q = quote_plus(name)
                url = MYNETA_URL + f"search.php?q={q}"
                if url not in tried_urls:
                    tried_urls.add(url)
                    try:
                        page.goto(url)
                        page.wait_for_selector("table.w3-table > tbody > tr", timeout=7000)
                    except Exception:
                        # try again after small backoff
                        time.sleep(1 + attempt)
                        continue
                else:
                    time.sleep(1 + attempt)
                    continue

            # stabilize rows count (wait until it stops changing)
            rows = page.locator("table.w3-table > tbody > tr")
            for _ in range(6):
                c1 = rows.count()
                page.wait_for_timeout(300)
                c2 = rows.count()
                if c1 == c2:
                    break

            # evaluate rows
            for i in range(rows.count()):
                r = rows.nth(i)
                try:
                    if r.locator("td").count() < 4 or r.locator("a").count() == 0:
                        continue
                    cname_raw = r.locator("a").first.inner_text().strip()
                    cconst_raw = r.locator("td:nth-child(3)").inner_text().strip()
                    election_raw = r.locator("td:nth-child(4)").inner_text().strip()
                except Exception:
                    continue

                cname = normalize_text(cname_raw)
                cconst = normalize_text(cconst_raw)

                # name match: exact substring OR fuzzy match above threshold
                name_sim = similar(name_norm, cname)
                name_ok = (name_norm in cname) or (name_sim >= 0.70)

                # constituency match: empty constituency is allowed, otherwise check substring or shared token
                const_ok = False
                if not const_norm:
                    const_ok = True
                else:
                    if const_norm in cconst:
                        const_ok = True
                    else:
                        # check token overlap
                        if len(set(const_norm.split()) & set(cconst.split())) > 0:
                            const_ok = True

                # year match: if year present in ECI record, ensure it appears in election column
                year_ok = True
                if year:
                    year_ok = str(year) in election_raw

                if name_ok and const_ok and year_ok:
                    link = r.locator("a").first.get_attribute("href")
                    if link and link.startswith("/"):
                        link = "https://www.myneta.info" + link
                    return link or ""

            # Not found yet — try broader query combining constituency
            if attempt == 1 and constituency:
                q = quote_plus(f"{name} {constituency}")
                url = MYNETA_URL + f"search.php?q={q}"
                if url not in tried_urls:
                    tried_urls.add(url)
                    try:
                        page.goto(url)
                        page.wait_for_selector("table.w3-table > tbody > tr", timeout=7000)
                        continue
                    except Exception:
                        pass

            # backoff and retry
            time.sleep(1 + attempt)

        # nothing matched after retries
        return ""

    # search for each candidate
    for c in candidates:
        link = search_myneta_for_candidate(myneta, c["Name"], c.get("Constituency", ""), c.get("Year", ""))
        c["neta_link"] = link or ""
        print("MyNeta:", c["Name"], c["neta_link"])


        

    ########################################
    # SAVE CSV
    ########################################
    output = "eci_candidates_with_neta.csv"
    if candidates:
        with open(output, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=candidates[0].keys())
            writer.writeheader()
            writer.writerows(candidates)
        print("\nSaved:", os.path.abspath(output))
    else:
        print("No candidates found; nothing to save.")

    browser.close()
