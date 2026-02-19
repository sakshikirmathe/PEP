import pandas as pd

# Load files
eci = pd.read_csv("eci_candidates_with_neta.csv")
neta = pd.read_csv("myneta_extracted_details.csv")

# Merge on Name
merged = pd.merge(
    eci,
    neta,
    on="Name",     # common column
    how="left"     # keeps all ECI rows
)

# Save result
merged.to_csv("eci_with_myneta_merged.csv", index=False)

print("Merged successfully.")
