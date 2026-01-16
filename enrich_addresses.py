import pandas as pd
from google import genai
from google.genai import types
import time
import json
import os
import re

# 1. Configuration
API_KEY = ""
INPUT_PATH = r"D:\Automation2\eci_candidates_with_neta.csv"
OUTPUT_PATH = r"D:\Automation2\eci_candidates_filled.csv"

# Initialize the new Client
client = genai.Client(api_key=API_KEY)

def process_address_batches():
    if not os.path.exists(INPUT_PATH):
        print(f"File not found: {INPUT_PATH}")
        return

    df = pd.read_csv(INPUT_PATH)
    addresses = df['Address'].tolist()
    all_results = []
    
    batch_size = 20

    for i in range(0, len(addresses), batch_size):
        batch = addresses[i : i + batch_size]
        print(f"Processing batch {i//batch_size + 1} ({len(batch)} items)...")

        prompt = f"""Extract the City (Tehsil) and 6-digit Pincode for these Indian addresses.
Return a JSON array of objects with keys "city" and "pincode", one object per address in the same order as input.
Return ONLY the JSON array and nothing else.
Example: [{{"city":"Koilwar","pincode":"802121"}}]
Addresses: {batch}
"""

        try:
            response = client.models.generate_content(
                model='gemini-3-flash-preview',
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type='application/json',
                    temperature=0.0
                )
            )

            # Best-effort ways to extract raw text from response
            raw = getattr(response, 'text', None) or getattr(response, 'content', None) or str(response)
            print(f"RAW RESPONSE (batch {i//batch_size + 1}): {raw}")

            # Try to extract JSON array substring between first '[' and last ']'
            json_text = None
            first = raw.find('[')
            last = raw.rfind(']')
            if first != -1 and last != -1 and last > first:
                json_text = raw[first:last+1]
            else:
                # Try other fields the SDK might expose
                parsed = getattr(response, 'parsed', None)
                if isinstance(parsed, (str, bytes)):
                    json_text = parsed
                elif hasattr(response, 'candidates'):
                    try:
                        candidate_texts = []
                        for c in response.candidates:
                            cand_text = getattr(c, 'text', None) or getattr(c, 'content', None) or str(c)
                            candidate_texts.append(cand_text)
                        json_text = ''.join(candidate_texts)
                    except Exception:
                        json_text = raw

            # Parse JSON or fallback
            try:
                batch_data = json.loads(json_text) if json_text else []
                if not isinstance(batch_data, list):
                    raise ValueError('Parsed JSON is not a list')
            except Exception as e2:
                print(f"JSON parse failed for batch {i}: {e2}")
                # Fallback: extract 6-digit pincodes from the original addresses
                batch_data = []
                for addr_text in batch:
                    m = re.search(r"\b\d{6}\b", addr_text)
                    pincode = m.group(0) if m else "N/A"
                    batch_data.append({"city": "N/A", "pincode": pincode})

            # Normalize length: ensure one result per input address
            if len(batch_data) < len(batch):
                batch_data.extend([{"city": "N/A", "pincode": "N/A"}] * (len(batch) - len(batch_data)))
            elif len(batch_data) > len(batch):
                batch_data = batch_data[:len(batch)]

            all_results.extend(batch_data)

        except Exception as e:
            print(f"Error in batch {i}: {e}")
            # fallback: try to extract pincode from original addresses with regex
            fallback = []
            for addr_text in batch:
                m = re.search(r"\b\d{6}\b", addr_text)
                pincode = m.group(0) if m else "N/A"
                fallback.append({"city": "N/A", "pincode": pincode})
            all_results.extend(fallback)

        # 4-second sleep to stay safe on Free Tier (15 RPM)
        time.sleep(4) 

    # Map results back to the dataframe
    # We use a loop to handle cases where the model might return fewer items than requested
    # Final validation: ensure pincodes are 6-digit; if not, try to extract from the original address
    cities = []
    pincodes = []

    def is_valid_pincode(p):
        return isinstance(p, str) and re.fullmatch(r'\d{6}', p)

    for idx, addr in enumerate(addresses):
        res = all_results[idx] if idx < len(all_results) else {}
        city = res.get('city', 'N/A') if isinstance(res, dict) else 'N/A'
        pincode = res.get('pincode', '') if isinstance(res, dict) else ''

        # If the pincode is missing or invalid, try regex on the original address
        if not is_valid_pincode(pincode):
            m = re.search(r"\b\d{6}\b", addr)
            pincode = m.group(0) if m else 'N/A'

        cities.append(city)
        pincodes.append(pincode)

    df['City'] = cities
    df['Pincode'] = pincodes

    df.to_csv(OUTPUT_PATH, index=False)
    print(f"Completed! File saved to {OUTPUT_PATH}")

if __name__ == "__main__":
    process_address_batches()