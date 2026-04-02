🗳️ PEP (Political Enrichment Pipeline)
A complete data pipeline to scrape, enrich, and analyze Indian election candidate data by combining sources like ECI affidavits and MyNeta.

🚀 Overview
PEP is an end-to-end automation pipeline that:
-Scrapes candidate data from the Election Commission of India (ECI)
-Maps candidates to their MyNeta profiles
-Extracts financial, criminal, and educational details
-Enriches addresses with city & pincode using AI
-Merges everything into a structured dataset

🧱 Project Structure
.
├── unified_scraper.py        # 🔥 Full pipeline (recommended entry point)
├── extract2.py              # Phase 1 + 2 (ECI + MyNeta link mapping)
├── extract_from_myneta.py   # Phase 3 (Detailed extraction)
├── enrich_addresses.py      # Address enrichment (AI-based)
├── edge_case_tester.py      # Debugging & matching improvements
├── input/
│   └── eci_candidates_with_neta.csv
├── output/
│   ├── merged_candidates.csv
│   ├── myneta_extracted_details.csv
│   └── eci_candidates_filled.csv
└── requirements.txt

⚙️ Pipeline Breakdown

1️⃣ ECI Scraping
Scrapes candidate-level data including:
Name, Party, Status
Constituency, State
Address, Age, Gender
Affidavit links
👉 Implemented in: extract2.py

2️⃣ MyNeta Link Mapping
Matches candidates with their MyNeta profiles using:
Fuzzy name matching
Constituency filtering
Election year validation
👉 Logic reused in: edge_case_tester.py

3️⃣ MyNeta Data Extraction
Extracts structured insights:
💰 Net Worth (Assets - Liabilities)
💼 Profession
🎓 Education category
⚖️ Criminal cases
📈 Income
👉 Implemented in: extract_from_myneta.py

4️⃣ Address Enrichment (AI ✨)
Uses LLM to extract:
City (Tehsil)
6-digit Pincode
👉 Implemented in: enrich_addresses.py

5️⃣ Final Merge
Combines all datasets into a single unified dataset.
👉 Done in: unified_scraper.py


🧪 How to Run
1. Install dependencies
pip install -r requirements.txt
playwright install

2. Run full pipeline
python unified_scraper.py

3. Optional Steps
python extract2.py                # ECI + MyNeta links
python extract_from_myneta.py    # Detailed extraction
python enrich_addresses.py       # Address enrichment

Output Files
File	                        Description
eci_candidates_with_neta.csv	Base dataset with MyNeta links
myneta_extracted_details.csv	Extracted financial + criminal data
merged_candidates.csv	        Final enriched dataset
eci_candidates_filled.csv	    Address enriched dataset

⚠️ Notes
Playwright runs in non-headless mode by default (for debugging)
MyNeta scraping depends on page structure — may break if UI changes
AI enrichment requires a valid API key in enrich_addresses.py

🔐 Configuration

Update API key in:
API_KEY = "your_api_key_here"