#!/usr/bin/env python3
"""
Diagnostic Script - Find out why products aren't being found

This script tests your product search queries and shows you exactly what's wrong.
"""

import sys
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import time
from urllib.parse import quote_plus
from rapidfuzz import fuzz
import re

def setup_driver():
    """Setup Chrome driver"""
    options = Options()
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)

def normalize_text(text):
    """Normalize text for comparison"""
    if not text:
        return ""
    text = re.sub(r'[^\w\s]', ' ', text.lower())
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def generate_queries(product_name):
    """Generate search queries"""
    queries = []
    
    # Extract brand and model
    if '|' in product_name:
        brand = product_name.split('|')[0].strip()
        after = product_name.split('|')[1].strip()
        if '-' in after:
            model = after.split('-')[0].strip()
        else:
            model = after.split(',')[0].strip()
        
        queries.append(f"{brand} {model}")
        print(f"  Query 1 (Brand+Model): {queries[-1]}")
    
    # Cleaned version
    cleaned = product_name.replace('|', ' ').replace(' - ', ' ')
    cleaned = re.sub(r'[™®©]', '', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    if cleaned not in queries and len(cleaned) < 80:
        queries.append(cleaned)
        print(f"  Query 2 (Cleaned): {queries[-1]}")
    
    # Original
    if product_name not in queries:
        queries.append(product_name)
        print(f"  Query 3 (Original): {queries[-1]}")
    
    return queries

def test_amazon_search(driver, product_name):
    """Test Amazon search for a product"""
    print(f"\n{'='*80}")
    print(f"TESTING: {product_name}")
    print(f"{'='*80}\n")
    
    queries = generate_queries(product_name)
    
    for i, query in enumerate(queries, 1):
        print(f"\n--- ATTEMPT {i}: {query[:60]}... ---")
        
        url = f"https://www.amazon.com/s?k={quote_plus(query)}"
        print(f"🔗 URL: {url}")
        
        try:
            driver.get(url)
            time.sleep(3)
            
            # Try multiple selectors
            selectors = [
                "div[data-component-type='s-search-result']",
                "[data-asin]:not([data-asin=''])",
                ".s-result-item[data-index]"
            ]
            
            found_products = []
            
            for selector in selectors:
                try:
                    elements = driver.find_elements(By.CSS_SELECTOR, selector)
                    if elements:
                        print(f"✅ Selector worked: {selector} ({len(elements)} elements)")
                        
                        # Extract titles
                        for elem in elements[:10]:
                            try:
                                title_elem = elem.find_element(By.CSS_SELECTOR, "h2 a span")
                                title = title_elem.text.strip()
                                link = elem.find_element(By.CSS_SELECTOR, "h2 a").get_attribute('href')
                                
                                if title and len(title) > 10:
                                    found_products.append((title, link))
                            except:
                                continue
                        
                        if found_products:
                            break
                    else:
                        print(f"❌ Selector failed: {selector} (0 elements)")
                except Exception as e:
                    print(f"❌ Selector error: {selector} - {e}")
            
            if found_products:
                print(f"\n✅ FOUND {len(found_products)} PRODUCTS:")
                
                # Show first 5 with match scores
                query_normalized = normalize_text(query)
                product_normalized = normalize_text(product_name)
                
                for j, (title, link) in enumerate(found_products[:5], 1):
                    title_normalized = normalize_text(title)
                    
                    # Calculate match scores
                    score1 = fuzz.token_sort_ratio(query_normalized, title_normalized)
                    score2 = fuzz.partial_ratio(query_normalized, title_normalized)
                    score3 = fuzz.token_set_ratio(query_normalized, title_normalized)
                    best_score = max(score1, score2, score3)
                    
                    # Also compare to original product name
                    orig_score = max(
                        fuzz.token_sort_ratio(product_normalized, title_normalized),
                        fuzz.partial_ratio(product_normalized, title_normalized),
                        fuzz.token_set_ratio(product_normalized, title_normalized)
                    )
                    
                    print(f"\n  {j}. {title[:80]}...")
                    print(f"     Query Match: {best_score:.1f}% | Original Match: {orig_score:.1f}%")
                    print(f"     URL: {link[:100]}...")
                    
                    # Show recommendation
                    if best_score >= 30:
                        print(f"     ✅ WOULD BE MATCHED (threshold: 30%)")
                    else:
                        print(f"     ❌ BELOW THRESHOLD (needs: 30%, got: {best_score:.1f}%)")
                
                # If best match is good enough, we can stop
                if found_products and best_score >= 30:
                    print(f"\n✅ SUCCESS: This query would find a match!")
                    return True
            else:
                print(f"❌ NO PRODUCTS EXTRACTED")
                print(f"   Possible issues:")
                print(f"   - Amazon changed their HTML structure")
                print(f"   - CAPTCHA is blocking")
                print(f"   - Product doesn't exist")
                print(f"\n   Page title: {driver.title}")
                if 'robot check' in driver.title.lower() or 'captcha' in driver.title.lower():
                    print(f"   ⚠️  CAPTCHA DETECTED - This is blocking your searches!")
        
        except Exception as e:
            print(f"❌ ERROR: {e}")
        
        time.sleep(2)
    
    print(f"\n❌ FAILED: No query variation found a good match")
    return False

def main():
    if len(sys.argv) < 2:
        print("Usage: python diagnose_issues.py 'Product Name'")
        print("\nExample:")
        print("  python diagnose_issues.py 'Meta | Ray-Ban Meta Vanguard - White, Prizm Black'")
        print("  python diagnose_issues.py 'iPhone 15 Pro Max 256GB'")
        sys.exit(1)
    
    product_name = sys.argv[1]
    
    print("\n" + "="*80)
    print("PRODUCT SEARCH DIAGNOSTIC TOOL")
    print("="*80)
    print("\nThis will:")
    print("  1. Generate multiple search queries for your product")
    print("  2. Search Amazon with each query")
    print("  3. Show what results are found")
    print("  4. Calculate match scores")
    print("  5. Explain why matches pass/fail")
    print("\n" + "="*80 + "\n")
    
    driver = setup_driver()
    
    try:
        test_amazon_search(driver, product_name)
        
        print("\n" + "="*80)
        print("DIAGNOSTIC COMPLETE")
        print("="*80)
        print("\nWhat to do next:")
        print("  - If you see CAPTCHA: Use undetected-chromedriver")
        print("  - If no products found: Product may not exist on retailer")
        print("  - If match scores are low (<30%): Product name doesn't match retailer listing")
        print("  - If selectors failed: Retailer changed their HTML (update selectors)")
        print("\n")
    
    finally:
        input("Press Enter to close browser...")
        driver.quit()

if __name__ == "__main__":
    main()
