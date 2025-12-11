#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IMPROVED Product URL Finder - Addresses 50% failure rate issues

Key Improvements:
1. Progressive query simplification (simple → complex)
2. Better CSS selectors with fallbacks
3. Lower fuzzy matching threshold (30% instead of 60%)
4. Extended wait times for dynamic content
5. Result validation to prevent false positives
6. More aggressive retry logic
7. Better error recovery
"""

import os
import re
import sys
import time
import logging
import argparse
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from urllib.parse import quote_plus
import random

import pandas as pd
from bs4 import BeautifulSoup
from rapidfuzz import fuzz
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# Try undetected_chromedriver
try:
    import undetected_chromedriver as uc
    UNDETECTED_AVAILABLE = True
except ImportError:
    UNDETECTED_AVAILABLE = False
    print("⚠️  Install undetected_chromedriver for better results: pip install undetected-chromedriver")

# ==================== CONFIGURATION ====================

DEFAULT_CONFIG = {
    "headless": True,
    "fuzzy_threshold": 30,  # LOWERED from 60 - catches more valid matches
    "request_delay": (0.5, 1.5),  # REDUCED for faster processing
    "page_load_timeout": 30,  # INCREASED for slow-loading sites
    "max_retries": 3,  # INCREASED retry attempts
    "save_interval": 5,
    "max_results_per_retailer": 30,  # INCREASED to check more results
    "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "scroll_wait": 2.0,  # Wait for lazy-loaded content
    "dynamic_content_wait": 3.0  # Extra wait for JS-rendered content
}

# IMPROVED: More comprehensive selectors with fallbacks
RETAILERS = {
    "amazon": {
        "domains": ["amazon.com"],
        "search_urls": ["https://www.amazon.com/s?k={query}"],
        # Multiple selectors - tries all until one works
        "product_selectors": [
            "div[data-component-type='s-search-result']",
            "[data-asin]:not([data-asin=''])",
            ".s-result-item[data-index]",
            "[data-cel-widget*='search_result']"
        ],
        "title_selectors": [
            "h2 a span",
            "h2.a-size-mini span",
            ".a-size-medium.a-text-normal",
            "h2 span"
        ],
        "link_selectors": [
            "h2 a",
            "a.a-link-normal[href*='/dp/']",
            "a[href*='/gp/product/']"
        ]
    },
    "walmart": {
        "domains": ["walmart.com"],
        "search_urls": ["https://www.walmart.com/search?q={query}"],
        "product_selectors": [
            "[data-testid='item-stack']",
            ".search-result-gridview-item",
            "[data-item-id]"
        ],
        "title_selectors": [
            ".product-title",
            "h3",
            "[data-automation-id='product-title']"
        ],
        "link_selectors": ["a"]
    },
    "target": {
        "domains": ["target.com"],
        "search_urls": ["https://www.target.com/s?searchTerm={query}"],
        "product_selectors": [
            "[data-test='product-card']",
            ".ProductCard",
            "[class*='ProductCard']"
        ],
        "title_selectors": [
            "[data-test='product-title']",
            "h3",
            ".product-title"
        ],
        "link_selectors": ["a"]
    }
}

# ==================== DATA STRUCTURES ====================

@dataclass
class SearchResult:
    url: str
    title: str
    retailer: str
    score: float = 0.0
    variant: str = ""

@dataclass
class ProcessingResult:
    success: bool
    url: str = ""
    title: str = ""
    retailer: str = ""
    variant: str = ""
    score: float = 0.0
    error: str = ""

# ==================== UTILITY FUNCTIONS ====================

def setup_logging(level: str = "INFO"):
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('improved_finder.log'),
            logging.StreamHandler(sys.stdout)
        ]
    )

def normalize_text(text: str) -> str:
    """Normalize text for comparison"""
    if not text:
        return ""
    text = re.sub(r'[^\w\s]', ' ', text.lower())
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def extract_product_details(product_name: str) -> Dict:
    """Extract brand, model, color from product name"""
    details = {
        'brand': '',
        'model': '',
        'color': '',
        'full_text': normalize_text(product_name)
    }
    
    # Extract brand (before | or first word)
    if '|' in product_name:
        details['brand'] = normalize_text(product_name.split('|')[0].strip())
    else:
        details['brand'] = normalize_text(product_name.split()[0])
    
    # Extract model (after brand, before color indicators)
    if '|' in product_name:
        after_brand = product_name.split('|')[1].strip()
        if '-' in after_brand:
            details['model'] = normalize_text(after_brand.split('-')[0].strip())
        else:
            details['model'] = normalize_text(after_brand.split(',')[0].strip())
    
    # Extract color (after - or ,)
    color_match = re.search(r'[-,]\s*([A-Za-z\s]+)', product_name)
    if color_match:
        details['color'] = normalize_text(color_match.group(1).strip())
    
    return details

# CRITICAL FIX: Progressive query generation
def generate_search_queries(product_name: str) -> List[str]:
    """Generate queries from SIMPLE to COMPLEX for better success rate"""
    queries = []
    details = extract_product_details(product_name)
    
    # Query 1: Brand + Model ONLY (most reliable for retailers)
    if details['brand'] and details['model']:
        queries.append(f"{details['brand']} {details['model']}")
        logging.info(f"📝 Query 1 (Brand+Model): {queries[-1]}")
    
    # Query 2: Brand + Model + first color word
    if details['brand'] and details['model'] and details['color']:
        first_color = details['color'].split()[0]
        query = f"{details['brand']} {details['model']} {first_color}"
        if query not in queries:
            queries.append(query)
            logging.info(f"📝 Query 2 (Brand+Model+Color): {queries[-1]}")
    
    # Query 3: Remove special characters from full name
    cleaned = product_name.replace('|', ' ').replace(' - ', ' ')
    cleaned = re.sub(r'[™®©]', '', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    if cleaned not in queries and len(cleaned) < 80:
        queries.append(cleaned)
        logging.info(f"📝 Query 3 (Cleaned full): {queries[-1][:60]}...")
    
    # Query 4: First 50 characters (avoid over-specific queries)
    if len(product_name) > 50:
        short = product_name[:50].strip()
        short = re.sub(r'[™®©|]', '', short).strip()
        if short not in queries:
            queries.append(short)
            logging.info(f"📝 Query 4 (Truncated): {queries[-1]}...")
    
    # Query 5: Original as last resort
    if product_name not in queries:
        queries.append(product_name)
        logging.info(f"📝 Query 5 (Original): {queries[-1][:60]}...")
    
    logging.info(f"✅ Generated {len(queries)} search queries")
    return queries[:5]  # Max 5 attempts

# ==================== RETAILER SEARCH ====================

class ImprovedRetailerSearcher:
    def __init__(self, config: Dict):
        self.config = config
        self.driver = None
        self._setup_driver()
    
    def _setup_driver(self):
        """Setup Chrome with undetected_chromedriver if available"""
        if UNDETECTED_AVAILABLE:
            try:
                options = uc.ChromeOptions()
                if self.config['headless']:
                    options.add_argument("--headless=new")
                options.add_argument("--no-sandbox")
                options.add_argument("--disable-dev-shm-usage")
                options.add_argument("--window-size=1920,1080")
                
                self.driver = uc.Chrome(options=options, use_subprocess=False)
                self.driver.set_page_load_timeout(self.config['page_load_timeout'])
                logging.info("✅ Using undetected_chromedriver (best for avoiding blocks)")
                return
            except Exception as e:
                logging.warning(f"Undetected driver failed: {e}, using regular driver")
        
        # Fallback to regular Chrome
        options = Options()
        if self.config['headless']:
            options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1920,1080")
        options.add_argument(f"--user-agent={self.config['user_agent']}")
        
        service = Service(ChromeDriverManager().install())
        self.driver = webdriver.Chrome(service=service, options=options)
        self.driver.set_page_load_timeout(self.config['page_load_timeout'])
        logging.info("✅ Using standard ChromeDriver")
    
    def search_retailer(self, retailer: str, query: str) -> List[SearchResult]:
        """Search retailer with improved extraction"""
        if retailer not in RETAILERS:
            logging.warning(f"❌ Unknown retailer: {retailer}")
            return []
        
        config = RETAILERS[retailer]
        results = []
        
        for search_url in config['search_urls']:
            try:
                url = search_url.format(query=quote_plus(query))
                logging.info(f"🔍 Searching: {url[:100]}...")
                
                # Navigate with retry
                max_nav_retries = 3
                for attempt in range(max_nav_retries):
                    try:
                        self.driver.get(url)
                        break
                    except Exception as e:
                        if attempt < max_nav_retries - 1:
                            logging.warning(f"Navigation attempt {attempt+1} failed, retrying...")
                            time.sleep(2)
                        else:
                            raise
                
                # CRITICAL: Wait for dynamic content
                time.sleep(self.config['dynamic_content_wait'])
                
                # Wait for page to be fully loaded
                try:
                    WebDriverWait(self.driver, 10).until(
                        lambda d: d.execute_script('return document.readyState') == 'complete'
                    )
                except:
                    pass
                
                # CRITICAL: Scroll to trigger lazy loading
                self._scroll_to_load_content()
                
                # Extract results with multiple selector attempts
                search_results = self._extract_results_multi_selector(retailer, config)
                
                if search_results:
                    logging.info(f"✅ Found {len(search_results)} results")
                    results.extend(search_results)
                    break  # Success, no need to try other URLs
                else:
                    logging.warning(f"⚠️  No results extracted for query: {query[:60]}")
            
            except Exception as e:
                logging.error(f"❌ Search error: {e}")
                continue
        
        return results
    
    def _scroll_to_load_content(self):
        """Scroll page to trigger lazy-loaded content"""
        try:
            # Scroll in stages
            for scroll_position in [500, 1000, 1500, 2000]:
                self.driver.execute_script(f"window.scrollTo(0, {scroll_position});")
                time.sleep(self.config['scroll_wait'])
        except:
            pass
    
    def _extract_results_multi_selector(self, retailer: str, config: Dict) -> List[SearchResult]:
        """Try multiple selectors until we find products"""
        results = []
        
        # Try each product selector
        for product_selector in config.get('product_selectors', [config.get('product_selector', '')]):
            try:
                elements = self.driver.find_elements(By.CSS_SELECTOR, product_selector)
                if elements:
                    logging.info(f"✅ Found {len(elements)} elements with selector: {product_selector}")
                    results = self._extract_from_elements(elements, config, retailer)
                    if results:
                        return results  # Success!
            except Exception as e:
                logging.debug(f"Selector failed: {product_selector} - {e}")
                continue
        
        # If no selector worked, try JavaScript extraction as last resort
        if not results:
            logging.warning("⚠️  All CSS selectors failed, trying JavaScript extraction...")
            results = self._extract_with_javascript(retailer)
        
        return results
    
    def _extract_from_elements(self, elements: list, config: Dict, retailer: str) -> List[SearchResult]:
        """Extract product info from elements"""
        results = []
        
        for element in elements[:self.config['max_results_per_retailer']]:
            try:
                title = None
                url = None
                
                # Try each title selector
                for title_selector in config.get('title_selectors', [config.get('title_selector', '')]):
                    try:
                        title_elem = element.find_element(By.CSS_SELECTOR, title_selector)
                        title = title_elem.text.strip()
                        if title:
                            break
                    except:
                        continue
                
                # Try each link selector
                for link_selector in config.get('link_selectors', [config.get('link_selector', '')]):
                    try:
                        link_elem = element.find_element(By.CSS_SELECTOR, link_selector)
                        url = link_elem.get_attribute('href')
                        if url:
                            break
                    except:
                        continue
                
                if title and url and len(title) > 10:
                    results.append(SearchResult(
                        url=url,
                        title=title,
                        retailer=retailer
                    ))
                    logging.debug(f"  ✓ {title[:60]}...")
            
            except Exception as e:
                logging.debug(f"Element extraction error: {e}")
                continue
        
        return results
    
    def _extract_with_javascript(self, retailer: str) -> List[SearchResult]:
        """Last resort: use JavaScript to find product links"""
        try:
            js_products = self.driver.execute_script("""
                var products = [];
                var links = document.querySelectorAll('a[href*="/dp/"], a[href*="/product"], a[href*="/p/"]');
                
                for (var i = 0; i < Math.min(links.length, 30); i++) {
                    var link = links[i];
                    var text = link.textContent.trim();
                    var href = link.href;
                    
                    if (text.length > 15 && href && href.includes('http')) {
                        products.push({
                            title: text.substring(0, 200),
                            url: href
                        });
                    }
                }
                return products;
            """)
            
            results = []
            for p in js_products:
                results.append(SearchResult(
                    url=p['url'],
                    title=p['title'],
                    retailer=retailer
                ))
            
            if results:
                logging.info(f"✅ JavaScript extraction found {len(results)} products")
            return results
        
        except Exception as e:
            logging.error(f"JavaScript extraction failed: {e}")
            return []
    
    def close(self):
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass

# ==================== MATCHING LOGIC ====================

class ImprovedMatcher:
    def __init__(self, config: Dict):
        self.config = config
        self.fuzzy_threshold = config.get('fuzzy_threshold', 30)
    
    def find_best_match(self, queries: List[str], results: List[SearchResult], 
                       original_name: str, brand: str = None) -> Optional[SearchResult]:
        """Find best match with validation"""
        if not queries or not results:
            return None
        
        best_match = None
        best_score = 0
        
        original_details = extract_product_details(original_name)
        original_lower = normalize_text(original_name)
        
        for result in results:
            result_lower = normalize_text(result.title)
            
            # VALIDATION 1: Check if result is valid product
            if not self._is_valid_result(result):
                logging.debug(f"  ❌ Invalid result: {result.title[:50]}")
                continue
            
            # Calculate match scores for all queries
            max_score = 0
            best_query = ""
            
            for query in queries:
                query_lower = normalize_text(query)
                
                # Try multiple fuzzy matching algorithms
                token_sort = fuzz.token_sort_ratio(query_lower, result_lower)
                partial = fuzz.partial_ratio(query_lower, result_lower)
                token_set = fuzz.token_set_ratio(query_lower, result_lower)
                
                # Use the best score
                score = max(token_sort, partial, token_set)
                
                if score > max_score:
                    max_score = score
                    best_query = query
            
            # VALIDATION 2: Brand must match if specified
            if brand:
                brand_lower = normalize_text(brand)
                if brand_lower not in result_lower:
                    # Try partial match
                    brand_score = fuzz.partial_ratio(brand_lower, result_lower)
                    if brand_score < 70:
                        logging.debug(f"  ❌ Brand mismatch: expected '{brand}' in '{result.title[:50]}'")
                        continue
            
            # VALIDATION 3: Check for model match if specified
            if original_details['model']:
                model_lower = original_details['model']
                model_words = model_lower.split()
                matched_words = sum(1 for w in model_words if len(w) > 3 and w in result_lower)
                
                # Require at least 50% of model words to match
                if model_words and matched_words < len(model_words) * 0.5:
                    logging.debug(f"  ❌ Model mismatch: '{original_details['model']}' not in '{result.title[:50]}'")
                    continue
            
            # Accept if score meets lowered threshold
            if max_score >= self.fuzzy_threshold and max_score > best_score:
                best_score = max_score
                best_match = result
                best_match.score = max_score
                best_match.variant = best_query
                logging.info(f"  ✅ Match: {max_score:.1f}% - {result.title[:60]}...")
        
        return best_match
    
    def _is_valid_result(self, result: SearchResult) -> bool:
        """Validate result quality"""
        # Check 1: Title must be reasonable length
        if len(result.title) < 10:
            return False
        
        # Check 2: URL must be valid product URL
        url_lower = result.url.lower()
        valid_patterns = ['/dp/', '/product', '/p/', '/gp/product', '/item']
        if not any(pattern in url_lower for pattern in valid_patterns):
            return False
        
        # Check 3: Title must not be just a product ID
        if re.match(r'^[A-Z0-9-]{10,}$', result.title):
            return False
        
        # Check 4: Detect common false positives
        title_lower = result.title.lower()
        false_positives = [
            'gift card', 'subscription', 'add-on item',
            'clip-on', 'attachment', 'case only', 
            'cable only', 'charger only'
        ]
        if any(fp in title_lower for fp in false_positives):
            return False
        
        return True

# ==================== MAIN PROCESSOR ====================

class ImprovedProductFinder:
    def __init__(self, config: Dict = None):
        self.config = config or DEFAULT_CONFIG.copy()
        self.searcher = None
        self.matcher = ImprovedMatcher(self.config)
    
    def process_excel_file(self, input_file: str, output_file: str):
        """Process Excel file"""
        try:
            df = pd.read_excel(input_file)
            logging.info(f"📊 Loaded {len(df)} rows from {input_file}")
            
            # Detect column names (case-insensitive)
            product_col = self._find_column(df, ['product name', 'product name/id', 'product'])
            retailer_col = self._find_column(df, ['retailer', 'store'])
            brand_col = self._find_column(df, ['brand', 'manufacturer'])
            
            if not product_col:
                raise ValueError("❌ Cannot find product name column")
            if not retailer_col:
                raise ValueError("❌ Cannot find retailer column")
            
            # Add output columns
            for col in ['Found URL', 'Found Title', 'Match Score', 'Status']:
                if col not in df.columns:
                    df[col] = ""
            
            # Initialize searcher
            self.searcher = ImprovedRetailerSearcher(self.config)
            
            # Process rows
            success_count = 0
            fail_count = 0
            
            for index, row in df.iterrows():
                try:
                    logging.info(f"\n{'='*80}")
                    logging.info(f"Processing row {index + 1}/{len(df)}")
                    
                    result = self._process_row(row, product_col, retailer_col, brand_col)
                    
                    if result.success:
                        df.at[index, 'Found URL'] = result.url
                        df.at[index, 'Found Title'] = result.title
                        df.at[index, 'Match Score'] = f"{result.score:.1f}%"
                        df.at[index, 'Status'] = 'SUCCESS'
                        success_count += 1
                        logging.info(f"✅ SUCCESS: {result.title[:60]}...")
                    else:
                        df.at[index, 'Status'] = f"FAILED: {result.error}"
                        df.at[index, 'Found URL'] = ""
                        df.at[index, 'Found Title'] = ""
                        df.at[index, 'Match Score'] = ""
                        fail_count += 1
                        logging.warning(f"❌ FAILED: {result.error}")
                    
                    # Save progress
                    if (index + 1) % self.config['save_interval'] == 0:
                        df.to_excel(output_file, index=False)
                        logging.info(f"💾 Progress saved ({success_count} success, {fail_count} failed)")
                
                except Exception as e:
                    logging.error(f"❌ Error on row {index}: {e}")
                    df.at[index, 'Status'] = f"ERROR: {str(e)}"
                    fail_count += 1
            
            # Final save
            df.to_excel(output_file, index=False)
            
            # Summary
            total = len(df)
            success_rate = (success_count / total * 100) if total > 0 else 0
            logging.info(f"\n{'='*80}")
            logging.info(f"🎯 FINAL RESULTS:")
            logging.info(f"   Total: {total}")
            logging.info(f"   ✅ Success: {success_count} ({success_rate:.1f}%)")
            logging.info(f"   ❌ Failed: {fail_count} ({100-success_rate:.1f}%)")
            logging.info(f"   💾 Saved to: {output_file}")
            logging.info(f"{'='*80}\n")
        
        finally:
            if self.searcher:
                self.searcher.close()
    
    def _find_column(self, df: pd.DataFrame, names: List[str]) -> Optional[str]:
        """Find column name (case-insensitive)"""
        for col in df.columns:
            if col.lower().strip() in [n.lower().strip() for n in names]:
                return col
        return None
    
    def _process_row(self, row, product_col: str, retailer_col: str, brand_col: str = None) -> ProcessingResult:
        """Process single row with progressive query attempts"""
        product_name = str(row.get(product_col, '')).strip()
        retailer = str(row.get(retailer_col, '')).strip().lower()
        brand = str(row.get(brand_col, '')).strip() if brand_col else None
        
        if not product_name:
            return ProcessingResult(success=False, error="No product name")
        
        if not retailer:
            return ProcessingResult(success=False, error="No retailer specified")
        
        # Normalize retailer name
        if retailer not in RETAILERS:
            # Try to match
            for key in RETAILERS.keys():
                if key in retailer or retailer in key:
                    retailer = key
                    break
            else:
                return ProcessingResult(success=False, error=f"Unsupported retailer: {retailer}")
        
        logging.info(f"🔍 Product: {product_name[:60]}...")
        logging.info(f"🏪 Retailer: {retailer}")
        if brand:
            logging.info(f"🏷️  Brand: {brand}")
        
        # CRITICAL: Generate progressive queries
        queries = generate_search_queries(product_name)
        
        # Try each query until we get results
        all_results = []
        for i, query in enumerate(queries, 1):
            logging.info(f"\n🔄 Attempt {i}/{len(queries)}: Searching with query...")
            
            try:
                results = self.searcher.search_retailer(retailer, query)
                
                if results:
                    logging.info(f"✅ Query {i} found {len(results)} results")
                    all_results.extend(results)
                    
                    # Try matching with current results
                    best_match = self.matcher.find_best_match(
                        queries[:i],  # Use all queries tried so far
                        results,
                        product_name,
                        brand
                    )
                    
                    if best_match and best_match.score >= self.config['fuzzy_threshold']:
                        return ProcessingResult(
                            success=True,
                            url=best_match.url,
                            title=best_match.title,
                            retailer=retailer,
                            variant=best_match.variant,
                            score=best_match.score
                        )
                else:
                    logging.warning(f"⚠️  Query {i} returned no results")
            
            except Exception as e:
                logging.error(f"❌ Query {i} failed: {e}")
            
            # Small delay between queries
            time.sleep(random.uniform(1, 2))
        
        # No match found
        if all_results:
            return ProcessingResult(
                success=False,
                error=f"Found {len(all_results)} products but none matched criteria (threshold: {self.config['fuzzy_threshold']}%)"
            )
        else:
            return ProcessingResult(
                success=False,
                error="No search results found (product may not exist on retailer)"
            )

# ==================== COMMAND LINE ====================

def main():
    parser = argparse.ArgumentParser(description='Improved Product URL Finder')
    parser.add_argument('--input', '-i', required=True, help='Input Excel file')
    parser.add_argument('--output', '-o', required=True, help='Output Excel file')
    parser.add_argument('--threshold', '-t', type=float, default=30, help='Match threshold (default: 30)')
    parser.add_argument('--headless', action='store_true', help='Run headless (default: True)')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose logging')
    
    args = parser.parse_args()
    
    # Setup logging
    setup_logging("DEBUG" if args.verbose else "INFO")
    
    # Create config
    config = DEFAULT_CONFIG.copy()
    config['headless'] = args.headless or config['headless']
    config['fuzzy_threshold'] = args.threshold
    
    # Process
    finder = ImprovedProductFinder(config)
    finder.process_excel_file(args.input, args.output)

if __name__ == "__main__":
    main()
