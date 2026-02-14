import time
import random
import re
import string
import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, StaleElementReferenceException

# --- Configuration ---
EXCEL_IN = "1993_dataset.xlsx"
EXCEL_OUT = "output_with_citations.xlsx"
BASE_URL = "https://scholar.google.com"
MATCH_THRESHOLD = 0.5  # e.g., 0.8 means 80% of the words in your input must be found in the title
WAIT_TIME = 15

# --- Helper Functions ---
def clean_and_tokenize(text):
    """
    Converts text to a set of lowercase words, removing punctuation.
    """
    if not text:
        return set()
    # Lowercase and remove punctuation
    text = str(text).lower()
    text = text.translate(str.maketrans('', '', string.punctuation))
    # Split into words and return as a set
    return set(text.split())

def get_word_overlap_score(query_text, result_text):
    """
    Returns score based on how many words from query_text exist in result_text.
    Score = (Matching Words) / (Total Words in Query)
    """
    query_words = clean_and_tokenize(query_text)
    result_words = clean_and_tokenize(result_text)
    
    if not query_words:
        return 0.0
        
    # Intersection: words present in both
    common_words = query_words.intersection(result_words)
    
    # Calculate percentage of query words found
    return len(common_words) / len(query_words)

def safe_sleep(a=2.0, b=4.0):
    time.sleep(random.uniform(a, b))

# --- Main Script ---

# 1. Load Excel
try:
    df = pd.read_excel(EXCEL_IN)
    print(f"Loaded {len(df)} rows.")
except FileNotFoundError:
    print(f"Error: {EXCEL_IN} not found.")
    exit()

# 2. Start browser
options = webdriver.ChromeOptions()
options.add_argument("--start-maximized")
driver = webdriver.Chrome(options=options)
wait = WebDriverWait(driver, WAIT_TIME)

all_years = set(range(1993, 2026)) 
row_data_list = [] 

for idx, row in df.iterrows():
    title = str(row.get("Title", ""))
    author = str(row.get("Author", ""))
    search_query = f"{title}, {author}"
    
    print(f"\n--- Processing Row {idx}: {title[:30]}... ---")
    
    row_result = {
        'total': 0,
        'scraped_url': 'N/A',
        'match_score': 0.0,
        'matched_title': 'N/A'
    }

    try:
        driver.get(BASE_URL)
        safe_sleep(1, 2)

        # 3. Type query
        search_box = wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "input[name='q']"))
        )
        search_box.clear()
        search_box.send_keys(search_query)
        search_box.send_keys(Keys.RETURN)
        safe_sleep(2, 3)

        # --- UPDATED: Loop by Index to avoid StaleElementReference ---
        # Get count of results first
        results_count = len(driver.find_elements(By.CSS_SELECTOR, ".gs_r.gs_or.gs_scl"))
        
        found_match = False
        
        # Iterate by index (i) instead of "for res in results"
        for i in range(results_count):
            try:
                # Re-fetch the list of results fresh from the DOM
                current_results = driver.find_elements(By.CSS_SELECTOR, ".gs_r.gs_or.gs_scl")
                
                # Safety check: if the list changed size unexpectedly
                if i >= len(current_results):
                    break
                    
                res = current_results[i]

                # --- UPDATED: Safe Text Extraction (ignoring SVG) ---
                try:
                    res_title_elem = res.find_element(By.CSS_SELECTOR, "h3.gs_rt")
                    
                    # Use JS to get text content excluding SVG tags to avoid hidden text
                    # res_title_text = driver.execute_script("""
                    #     var clone = arguments[0].cloneNode(true);
                    #     var svgs = clone.querySelectorAll('svg');
                    #     svgs.forEach(s => s.remove());
                    #     return clone.textContent;
                    # """, res_title_elem).strip()
                    res_title_text = res_title_elem.text
                    
                except NoSuchElementException:
                    continue # Skip if no title found

                # --- UPDATED: Word Match Logic ---
                # We compare Input Title vs Result Title (Author is usually separate)
                score = get_word_overlap_score(title, res_title_text)
                print(f"  Checking result {i+1}: '{res_title_text[:30]}...' | Match: {int(score*100)}%")

                if score < MATCH_THRESHOLD:
                    continue 

                row_result['scraped_url'] = driver.current_url
                # Check for "Cited by" link safely
                try:
                    cited_link = res.find_element(By.XPATH, ".//a[contains(., 'Cited by')]")
                except NoSuchElementException:
                    print("  -> Match found, but no 'Cited by' link. Skipping.")
                    continue

                # --- Match Confirmed ---
                found_match = True
                row_result['match_score'] = score
                row_result['matched_title'] = res_title_text
                
                # Get count text
                cited_text = cited_link.text
                match_count = re.search(r'\d+', cited_text)
                row_result['total'] = int(match_count.group()) if match_count else 0
                
                # Click Cited By
                cited_link.click()
                safe_sleep(2, 3)
                

                # Open Sidebar & Scrape
                try:
                    citations_btn = wait.until(
                        EC.element_to_be_clickable((By.ID, "gs_res_sb_hist_wrp"))
                    )
                    citations_btn.click()
                    safe_sleep(1, 2)
                    
                    bars = driver.find_elements(By.CSS_SELECTOR, "a.gs_hist_g_a")
                    for bar in bars:
                        y = int(bar.get_attribute("data-year"))
                        c = int(bar.get_attribute("data-count"))
                        row_result[y] = c
                except Exception:
                    pass # Histogram might not exist for all papers

                # Break the loop once we processed the correct paper
                break
                
            except StaleElementReferenceException:
                # If element goes stale during this specific iteration, just retry the next index
                print(f"  -> Stale element at index {i}, skipping...")
                continue
            except Exception as inner_e:
                print(f"  -> Error on result {i}: {inner_e}")
                continue

        if not found_match:
            print("  -> No suitable match found.")

    except Exception as e:
        print(f"Row {idx} Failed: {e}")
        safe_sleep(5, 10)

    row_data_list.append(row_result)

    # Cooldown every 10 or 100 row
    if idx + 1 % 100 == 0:
        print("Cooling down for 200-300s")
        safe_sleep(200, 300)
    if idx + 1 % 10 == 0:
        print("Cooling down for 10-15s")
        safe_sleep(10, 15)

driver.quit()

# 8. Merge and Save
print("\nMerging data...")
df['Scraped_URL'] = [d.get('scraped_url', '') for d in row_data_list]
df['Match_Score'] = [d.get('match_score', 0) for d in row_data_list]
df['Matched_Title'] = [d.get('matched_title', '') for d in row_data_list] # Verify what was matched
df['Total_Citations'] = [d.get('total', 0) for d in row_data_list]

for year in sorted(all_years):
    df[year] = [d.get(year, 0) for d in row_data_list]

df.to_excel(EXCEL_OUT, index=False)
print(f"Done! Saved to {EXCEL_OUT}")