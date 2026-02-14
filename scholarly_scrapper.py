from scholarly import scholarly
from collections import Counter
import time
import random

# 1. Your list of papers (Title + Author helps accuracy)
papers_list = [
    {"title": "Deep Residual Learning for Image Recognition", "author": "He"},
    {"title": "Attention Is All You Need", "author": "Vaswani"},
    # Add your papers here
]

# Define the year range you are interested in
start_year = 1993
end_year = 2025
years_range = list(range(start_year, end_year + 1))

results_data = []

print(f"Starting scraping for {len(papers_list)} papers...")

for paper in papers_list:
    query = f"{paper['title']} {paper['author']}"
    print(f"\nSearching for: {paper['title']}...")

    try:
        # 1. Search for the publication
        search_query = scholarly.search_pubs(query)
        pub = next(search_query) # Get the first result
        
        # 2. Extract Basic Info
        title = pub['bib'].get('title', 'Unknown Title')
        total_citations = pub.get('num_citations', 0)
        print(f"  -- Found: {title}")
        print(f"  -- Total Citations: {total_citations}")

        # Initialize year counts with 0
        year_counts = {year: 0 for year in years_range}

        # 3. Get Year-wise Breakdown
        # We only do this if there are citations
        if total_citations > 0:
            print("  -- Fetching citation history (this may take time)...")
            
            # scholarly.citedby() returns a generator of papers that cite this one
            citations_generator = scholarly.citedby(pub)
            
            citation_years = []
            
            # Iterate through all citing papers
            for citing_paper in citations_generator:
                # Extract the year of the citing paper
                if 'pub_year' in citing_paper['bib']:
                    try:
                        year = int(citing_paper['bib']['pub_year'])
                        citation_years.append(year)
                    except ValueError:
                        pass
                
                # Sleep briefly to be nice to Google servers
                time.sleep(random.uniform(0.5, 1.5))

            # Count the years
            counts = Counter(citation_years)
            
            # Map to our target range (1993-2025)
            for year in years_range:
                year_counts[year] = counts.get(year, 0)
        
        # 4. Store the data
        paper_data = {
            "title": title,
            "total_citations": total_citations,
            "year_counts": year_counts
        }
        results_data.append(paper_data)
        
        print(f"  -- Done. Data collected.")

    except StopIteration:
        print("  -- Paper not found.")
    except Exception as e:
        print(f"  -- Error occurred: {str(e)}")

# 5. Output the results (e.g., print or save to CSV)
print("\n" + "="*30)
print("FINAL RESULTS")
print("="*30)
for res in results_data:
    print(f"\nPaper: {res['title']}")
    print(f"Total Citations: {res['total_citations']}")
    print("Year-wise Breakdown (1993-2025):")
    print(res['year_counts'])