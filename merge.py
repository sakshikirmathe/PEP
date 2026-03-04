import pandas as pd

# Load files
eci = pd.read_csv("eci_candidates_with_neta.csv")
myneta = pd.read_csv("myneta_extracted_details.csv")

# normalize names for matching
def clean_name(name):
    if pd.isna(name):
        return ""
    return (
        str(name)
        .lower()
        .replace(".", "")
        .replace(",", "")
        .strip()
    )

eci["match_name"] = eci["Name"].apply(clean_name)
myneta["match_name"] = myneta["Name"].apply(clean_name)

merged_rows = []

i = 0
j = 0

while i < len(eci) and j < len(myneta):

    e_name = eci.loc[i, "match_name"]
    m_name = myneta.loc[j, "match_name"]

    if e_name == m_name:
        merged = {**eci.loc[i].to_dict(), **myneta.loc[j].to_dict()}
        merged_rows.append(merged)

        i += 1
        j += 1

    else:
        # skip ECI row until names match
        merged = eci.loc[i].to_dict()
        merged_rows.append(merged)
        i += 1


# If ECI still has remaining rows
while i < len(eci):
    merged_rows.append(eci.loc[i].to_dict())
    i += 1

merged_df = pd.DataFrame(merged_rows)

# drop helper column
merged_df = merged_df.drop(columns=["match_name"], errors="ignore")

# save result
merged_df.to_csv("merged_candidates.csv", index=False)

print("Merge complete. Output saved as merged_candidates.csv")