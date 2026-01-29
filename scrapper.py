import time, random
import re
import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

EXCEL_IN = "1993_dataset.xlsx"
EXCEL_OUT = "output_with_citations.xlsx"
BASE_URL = "https://scholar.google.com"

wait_time = 15

# 1. Load Excel
df = pd.read_excel(EXCEL_IN)   # assumes columns: 'Title', 'Author'

# 2. Start browser
options = webdriver.ChromeOptions()
options.add_argument("--start-maximized")
# options.add_argument("--headless=new")  # enable later if needed
driver = webdriver.Chrome(options=options)
wait = WebDriverWait(driver, wait_time)

def safe_sleep(a=1.0, b=3.0):
    time.sleep(random.uniform(a, b))

all_years = set(range(1993, 2026)) #1993-2025
row_year_dicts = []

for idx, row in df.iterrows():
    title = str(row["Title"])
    author = str(row["Author"])
    query = f"{title} {author}"

    try:
        driver.get(BASE_URL)
        safe_sleep(1, 2)

        # 3. Type query in search box and submit
        search_box = wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "input[name='q']"))
        )
        search_box.clear()
        search_box.send_keys(query)
        search_box.send_keys(Keys.RETURN)
        safe_sleep(1, 2)

        # 4. Click the "Cited by" link for the first result
        cited_link = wait.until(
            EC.element_to_be_clickable(
                (By.XPATH, "//a[contains(., 'Cited by')]")
            )
        )
        text = cited_link.text  # "Cited by 123"
        match = re.search(r'\d+', text)

        cited_count = int(match.group()) if match else 0

        cited_link.click()
        safe_sleep(1, 2)

        # 5. Open sidebar with year‑wise citations
        citations_btn = wait.until(
            EC.element_to_be_clickable((By.ID, "gs_res_sb_hist_wrp"))
        )
        citations_btn.click()

        # 6. Scrape year‑wise citation counts from table
        # Example for Scholar‑like hist: spans with years and counts. [web:8]
        year_elems = wait.until(
            EC.presence_of_all_elements_located(
                (By.CSS_SELECTOR, ".gs_hist_g_t")  # year labels
            )
        )

        bars = driver.find_elements(By.CSS_SELECTOR, "a.gs_hist_g_a")
 
        year_counts = {}
        year_counts['total'] = cited_count
        for bar in bars:
            year = int(bar.get_attribute("data-year"))
            count = int(bar.get_attribute("data-count"))
            year_counts[year] = count
            # all_years.add(year)
            # print(f"{year} : {count}")

        row_year_dicts.append(year_counts)

        # basic rate‑limit friendliness
        print(f"{idx} Done {author}")
        safe_sleep(2, 5)
        wait_time = 15

        if idx % 10 == 0:
            safe_sleep(10, 15)

    except Exception as e:
        print(f"Row {idx} failed: {e}")
        row_year_dicts.append({})      # keep alignment
        wait_time *= 2
        safe_sleep(wait_time, wait_time + 5)

driver.quit()

# 7. Merge back into DataFrame as columns Year_YYYY
for year in sorted(all_years):
    df[year] = [
        row_dict.get(year, 0) for row_dict in row_year_dicts
    ]

df['total_citation_count'] = [row_dict.get('total', 0) for row_dict in row_year_dicts]

# 8. Save to Excel
df.to_excel(EXCEL_OUT, index=False)
