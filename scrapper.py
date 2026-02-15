import time
import random
import re
import string
import logging
import difflib
import pandas as pd
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, StaleElementReferenceException

# --- Configuration ---
EXCEL_IN = "input.xlsx"
# EXCEL_IN = "1992_dataset_full.xlsx"
EXCEL_OUT = "output_with_citations.xlsx"
BASE_URL = "https://scholar.google.com"
MATCH_THRESHOLD = 0.4
WAIT_TIME = 15
SAVE_INTERVAL = 10  # Save progress every N rows

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("scraper.log"),
        logging.StreamHandler()
    ]
)

# --- Helper Functions ---
def is_captcha_present(driver):
    try:
        # 1. Check for the generic "unusual traffic" text in the body
        page_text = driver.find_element(By.TAG_NAME, "body").text.lower()
        if "unusual traffic" in page_text or "not a robot" in page_text:
            return True

        # 2. Check for the specific CAPTCHA form ID often used by Google
        # This ID wraps the captcha box
        captcha_box = driver.find_elements(By.ID, "gs_captcha_ccl") 
        if len(captcha_box) > 0:
            return True

        # 3. Check for the reCAPTCHA iframe specifically
        # (This requires switching frames sometimes, but presence is a good indicator)
        iframes = driver.find_elements(By.XPATH, "//iframe[contains(@src, 'google.com/recaptcha')]")
        if len(iframes) > 0:
            return True

        return False

    except Exception:
        return False

def clean_and_tokenize(text):
    if not text:
        return set()
    text = str(text).lower()
    text = text.translate(str.maketrans('', '', string.punctuation))
    return set(text.split())

def normalize_text(text):
    if not text:
        return ""
    text = str(text).lower()
    return text.translate(str.maketrans('', '', string.punctuation))

def get_word_overlap_score(query_text, result_text):
    query_words = clean_and_tokenize(query_text)
    result_words = clean_and_tokenize(result_text)
    
    if not query_words:
        return 0.0
        
    common_words = query_words.intersection(result_words)
    seq = difflib.SequenceMatcher(None, normalize_text(query_text), normalize_text(result_text))
    return max(len(common_words) / len(query_words), seq.ratio())

def safe_sleep(min_sec=2.0, max_sec=4.0):
    time.sleep(random.uniform(min_sec, max_sec))

def save_progress(df, data_list, all_years, filename):
    """Merges current data list into DataFrame and saves to Excel."""
    try:
        # Create a copy to avoid messing with the main loop logic if save fails
        temp_df = df.copy()
        
        # We need to ensure the list length matches the dataframe or handle partial updates
        # Since we append sequentially, we can map data_list index to DataFrame index
        # This assumes data_list corresponds to the first N rows of df
        
        processed_count = len(data_list)
        if processed_count == 0:
            return

        # Initialize columns if not present
        cols = ['Scraped_URL', 'Match_Score', 'Matched_Title', 'Total_Citations'] + list(all_years)
        for col in cols:
            if col not in temp_df.columns:
                temp_df[col] = None

        # Update rows
        for i, data in enumerate(data_list):
            temp_df.at[i, 'Scraped_URL'] = data.get('scraped_url')
            temp_df.at[i, 'Match_Score'] = data.get('match_score')
            temp_df.at[i, 'Matched_Title'] = data.get('matched_title')
            temp_df.at[i, 'Total_Citations'] = data.get('total')
            for year in all_years:
                temp_df.at[i, year] = data.get(year, 0)
        
        temp_df.to_excel(filename, index=False)
        logging.info(f"Progress saved to {filename}")
    except Exception as e:
        logging.error(f"Failed to save progress: {e}")

# --- Main Script ---

# 1. Load Excel
try:
    df = pd.read_excel(EXCEL_IN)
    logging.info(f"Loaded {len(df)} rows from {EXCEL_IN}")
except FileNotFoundError:
    logging.error(f"Error: {EXCEL_IN} not found.")
    exit()

# 2. Start browser
options = webdriver.ChromeOptions()
options.add_argument("--start-maximized")
driver = webdriver.Chrome(options=options)
wait = WebDriverWait(driver, WAIT_TIME)

all_years = sorted(list(range(1992, 2026)))
row_data_list = [] 
idx = 0

while idx < len(df):
    row = df.iloc[idx]
    title = str(row.get("Title", "")).strip().replace('\n', ' ')
    author = str(row.get("Author", "")).strip().replace('\n', ' ')
    search_query = f"{title}, {author}"
    
    logging.info(f"Processing Row {idx + 1}/{len(df)}: {title[:40]}...")
    
    row_result = {
        'total': 0, 'scraped_url': 'N/A', 
        'match_score': 0.0, 'matched_title': 'N/A'
    }

    try:
        driver.get(BASE_URL)
        safe_sleep(1.5, 2.5)

        # 3. Type query
        search_box = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "input[name='q']")))
        search_box.clear()
        search_box.send_keys(search_query)
        search_box.send_keys(Keys.RETURN)
        safe_sleep(2, 3)

        # Check for immediate robot/captcha detection on load
        if is_captcha_present(driver):
            input("Solve the captcha and press enter")
            continue
    
        # 4. Get Results
        results_elements = driver.find_elements(By.CSS_SELECTOR, ".gs_r.gs_or.gs_scl")
        results_count = len(results_elements)

        if results_count == 0:
            logging.info("No results found for query.")
            # Move to next row, append empty result
            row_data_list.append(row_result)
            idx += 1
            continue

        found_match = False
        
        # Iterate through results using index to handle stale elements
        for i in range(results_count):
            try:
                # Refresh elements list
                current_results = driver.find_elements(By.CSS_SELECTOR, ".gs_r.gs_or.gs_scl")
                if i >= len(current_results): break
                
                res = current_results[i]

                # Extract Title (Remove SVG)
                try:
                    res_title_elem = res.find_element(By.CSS_SELECTOR, "h3.gs_rt")
                    res_title_text = driver.execute_script("""
                        var clone = arguments[0].cloneNode(true);
                        var svgs = clone.querySelectorAll('svg');
                        svgs.forEach(s => s.remove());
                        return clone.textContent;
                    """, res_title_elem).strip()
                except NoSuchElementException:
                    continue

                # Calculate Match Score
                score = get_word_overlap_score(title, res_title_text)
                
                if score < MATCH_THRESHOLD:
                    logging.debug(f"Skipping match {score:.2f}: {res_title_text[:30]}")
                    continue 

                logging.info(f"Match Found ({score:.2f}): {res_title_text[:40]}")

                # Check for Citation Link
                try:
                    cited_link = res.find_element(By.XPATH, ".//a[contains(., 'Cited by')]")
                except NoSuchElementException:
                    logging.info("Paper found, but has 0 citations (no link).")
                    row_result['match_score'] = score
                    row_result['matched_title'] = res_title_text
                    # Stop checking other results, we found the paper
                    found_match = True
                    break 

                # Populate Result
                found_match = True
                row_result['match_score'] = score
                row_result['matched_title'] = res_title_text
                
                count_match = re.search(r'\d+', cited_link.text)
                row_result['total'] = int(count_match.group()) if count_match else 0
                
                # Navigate to Citation Page
                cited_link.click()
                safe_sleep(2, 3)
                row_result['scraped_url'] = driver.current_url

                # Open Histogram Sidebar
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
                except TimeoutException:
                    logging.debug("Histogram button not found (common for low citations).")
                except Exception as e:
                    logging.warning(f"Error scraping histogram: {e}")

                break # Exit result loop after successful scrape

            except StaleElementReferenceException:
                logging.warning(f"Stale element at index {i}, retrying next loop...")
                continue
            except Exception as e:
                logging.error(f"Error processing result {i}: {e}")
                continue

        if not found_match:
            logging.info("No suitable match found above threshold.")

        row_data_list.append(row_result)
        idx += 1 # Only increment after full processing

    except Exception as e:
        logging.critical(f"Critical error on Row {idx}: {e}")
        # Save work before crashing or waiting
        save_progress(df, row_data_list, all_years, EXCEL_OUT)
        safe_sleep(10, 20)
        # We generally increment idx here to skip the broken row, 
        # or you can choose to not increment to retry.
        # Choosing to skip to avoid infinite loops on bad data:
        row_data_list.append(row_result)
        idx += 1

    # --- Post-Row Tasks ---
    
    # Save periodically
    if idx % SAVE_INTERVAL == 0:
        save_progress(df, row_data_list, all_years, EXCEL_OUT)
        
    # Rate Limiting
    if idx % 100 == 0:
        logging.info("Long cooldown (3-5 mins) to satisfy Scholar gods...")
        safe_sleep(200, 300)
    elif idx % 10 == 0:
        logging.info("Short cooldown (10-15s)...")
        safe_sleep(10, 15)

# Final Save
driver.quit()
save_progress(df, row_data_list, all_years, EXCEL_OUT)
logging.info("Job Complete.")