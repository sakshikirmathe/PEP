from playwright.sync_api import sync_playwright
import csv
import re
import os

ECI_URL = "https://affidavit.eci.gov.in/"
MYNETA_URL = "https://www.myneta.info/"

# ---------------- HELPERS ----------------
def clean_name(raw_name):
    """
    Removes leading numbers like '1. ', '23. ' etc.
    """
    return re.sub(r"^\s*\d+\.\s*", "", raw_name).strip()

def extract_year(text):
    m = re.search(r"\b(19|20)\d{2}\b", text)
    return m.group(0) if m else ""

def wait_for_select_ready(page, selector, timeout=30000):
    elapsed = 0
    while elapsed < timeout:
        if page.locator(f"{selector} option").count() > 1:
            return
        page.wait_for_timeout(500)
        elapsed += 500
    raise TimeoutError(f"{selector} not ready")

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
    MAX_ROWS = 10   # 🔴 increase later
    candidates = []

    for i in range(min(cards.count(), MAX_ROWS)):
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
            "neta_link": ""
        })

    ########################################
    # PHASE 2 — MYNETA LINK MAPPING
    ########################################
    myneta = context.new_page()
    myneta.goto(MYNETA_URL)
    myneta.wait_for_selector("input[name='q']")

    search_box = myneta.locator("input[name='q']")

    for c in candidates:
        search_box.fill("")
        search_box.fill(c["Name"])
        search_box.press("Enter")
        myneta.wait_for_timeout(3000)

        rows = myneta.locator("table.w3-table tbody tr")

        for i in range(rows.count()):
            r = rows.nth(i)
            try:
                cname = r.locator("a").inner_text().lower()
                cconst = r.locator("td:nth-child(3)").inner_text().lower()
                election = r.locator("td:nth-child(4)").inner_text()

                if (
                    c["Name"].lower() in cname
                    and c["Constituency"].lower() in cconst
                    and c["Year"] in election
                ):
                    link = r.locator("a").get_attribute("href")
                    if link.startswith("/"):
                        link = "https://www.myneta.info" + link
                    c["neta_link"] = link
                    break
            except:
                continue

        print("MyNeta:", c["Name"], c["neta_link"])

    ########################################
    # SAVE CSV
    ########################################
    output = "eci_candidates_with_neta.csv"
    with open(output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=candidates[0].keys())
        writer.writeheader()
        writer.writerows(candidates)

    print("\nSaved:", os.path.abspath(output))
    browser.close()
