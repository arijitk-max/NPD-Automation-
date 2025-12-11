#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Comprehensive Product URL Finder

This script automates the process of finding product URLs on various retailers by:
1. Searching UPCitemdb.com for product information using GTIN or product names
2. Extracting product name variations from search results
3. Searching retailers (Amazon, JB Hi-Fi, Harvey Norman) for these variations
4. Finding exact matches using fuzzy matching
5. Updating Excel sheets with found URLs

Features:
- Robust UPCitemdb scraping (GTIN and product name search)
- Multi-retailer support with configurable search strategies
- Intelligent fuzzy matching for product name variations
- Comprehensive error handling and logging
- Progress tracking and resume capability
- Configurable search parameters and thresholds

Usage:
    python comprehensive_product_finder.py --input "input.xlsx" --output "results.xlsx"
"""

import os
import re
import sys
import time
import json
import logging
import argparse
import random
from typing import List, Dict, Optional, Tuple, Set, Any
from dataclasses import dataclass
from urllib.parse import urlparse, urlencode, quote_plus

import pandas as pd
import requests
from bs4 import BeautifulSoup
from rapidfuzz import fuzz
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import NoSuchElementException, WebDriverException, TimeoutException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# Try to import selenium-stealth for better bot detection evasion
try:
    from selenium_stealth import stealth
    STEALTH_AVAILABLE = True
except ImportError:
    STEALTH_AVAILABLE = False
    # Note: logging will be imported later, so we'll handle the warning in _setup_driver

# ==================== CONFIGURATION ====================

# Default configuration
DEFAULT_CONFIG = {
    "headless": True,  # Run headless - no browser window
    "max_variants": 1,  # Only search once with original product name
    "fuzzy_threshold": 60,  # Lowered from 85 to catch more matches
    "request_delay": (1.0, 3.0),
    "page_load_timeout": 30,
    "max_retries": 3,
    "save_interval": 5,
    "max_results_per_retailer": 5,  # Only check first 5 non-sponsored results
    "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# Retailer configurations
# To add a new retailer, simply add a new entry with the following structure:
# "retailer-key": {
#     "domains": ["domain.com"],
#     "search_urls": ["https://www.domain.com/search?q={query}"],
#     "product_selector": "CSS selector for product containers",
#     "title_selector": "CSS selector for product titles",
#     "link_selector": "CSS selector for product links",
#     "sponsored_indicators": ["Sponsored", "Ad"]  # Keywords that indicate sponsored results
# }
RETAILERS = {
    # Amazon variants
    "amazon": {
        "domains": ["amazon.com"],
        "search_urls": [
            "https://www.amazon.com/s?k={query}"
        ],
        "product_selector": "div[data-component-type='s-search-result']",
        "title_selector": "h2 a span",
        "link_selector": "h2 a",
        "sponsored_indicators": ["Sponsored", "Ad", "Advertisement"]
    },
    "amazon-au": {
        "domains": ["amazon.com.au"],
        "search_urls": [
            "https://www.amazon.com.au/s?k={query}"
        ],
        "product_selector": "div[data-component-type='s-search-result']",
        "title_selector": "h2 a span",
        "link_selector": "h2 a",
        "sponsored_indicators": ["Sponsored", "Ad", "Advertisement"]
    },
    "amazon-fresh": {
        "domains": ["amazon.com"],
        "search_urls": [
            "https://www.amazon.com/alm/storefront?almBrandId=QW1hem9uIEZyZXNo&k={query}",
            "https://www.amazon.com/s?k={query}&i=amazonfresh"
        ],
        "product_selector": "div[data-component-type='s-search-result']",
        "title_selector": "h2 a span",
        "link_selector": "h2 a",
        "sponsored_indicators": ["Sponsored", "Ad", "Advertisement"]
    },
    
    # Major US Retailers
    "target": {
        "domains": ["target.com"],
        "search_urls": [
            "https://www.target.com/s?searchTerm={query}"
        ],
        "product_selector": "[data-test='product-card'], .ProductCard, [class*='ProductCard']",
        "title_selector": "[data-test='product-title'], h3, .product-title",
        "link_selector": "a",
        "sponsored_indicators": []
    },
    "walmart": {
        "domains": ["walmart.com"],
        "search_urls": [
            "https://www.walmart.com/search?q={query}"
        ],
        "product_selector": "[data-testid='item-stack'], .search-result-gridview-item",
        "title_selector": ".product-title, h3, [data-automation-id='product-title']",
        "link_selector": "a",
        "sponsored_indicators": ["Sponsored"]
    },
    "cvs": {
        "domains": ["cvs.com"],
        "search_urls": [
            "https://www.cvs.com/search?searchTerm={query}"
        ],
        "product_selector": ".product-tile, .product-item, [data-testid='product-tile']",
        "title_selector": ".product-title, h3, .product-name",
        "link_selector": "a",
        "sponsored_indicators": []
    },
    "walgreens": {
        "domains": ["walgreens.com"],
        "search_urls": [
            "https://www.walgreens.com/search/results.jsp?Ntt={query}"
        ],
        "product_selector": ".product-container, .product-tile, [data-testid='product-tile']",
        "title_selector": ".product-title, h3, .product-name",
        "link_selector": "a",
        "sponsored_indicators": []
    },
    "kroger": {
        "domains": ["kroger.com"],
        "search_urls": [
            "https://www.kroger.com/search?query={query}"
        ],
        "product_selector": ".ProductCard, .product-tile, [data-testid='product-card']",
        "title_selector": ".product-title, h3, .product-name",
        "link_selector": "a",
        "sponsored_indicators": []
    },
    "albertsons": {
        "domains": ["albertsons.com"],
        "search_urls": [
            "https://www.albertsons.com/shop/search-results.html?q={query}"
        ],
        "product_selector": ".product-tile, .product-item, [data-testid='product-tile']",
        "title_selector": ".product-title, h3, .product-name",
        "link_selector": "a",
        "sponsored_indicators": []
    },
    "giant-eagle": {
        "domains": ["gianteagle.com"],
        "search_urls": [
            "https://www.gianteagle.com/shop/search?q={query}"
        ],
        "product_selector": ".product-tile, .product-item, [data-testid='product-tile']",
        "title_selector": ".product-title, h3, .product-name",
        "link_selector": "a",
        "sponsored_indicators": []
    },
    "gopuff": {
        "domains": ["gopuff.com"],
        "search_urls": [
            "https://www.gopuff.com/search?query={query}"
        ],
        "product_selector": ".product-tile, .product-item, [data-testid='product-tile']",
        "title_selector": ".product-title, h3, .product-name",
        "link_selector": "a",
        "sponsored_indicators": []
    },
    "heb": {
        "domains": ["heb.com"],
        "search_urls": [
            "https://www.heb.com/search/?q={query}"
        ],
        "product_selector": ".product-tile, .product-item, [data-testid='product-tile']",
        "title_selector": ".product-title, h3, .product-name",
        "link_selector": "a",
        "sponsored_indicators": []
    },
    "hyvee": {
        "domains": ["hy-vee.com"],
        "search_urls": [
            "https://www.hy-vee.com/shop/search?q={query}"
        ],
        "product_selector": ".product-tile, .product-item, [data-testid='product-tile']",
        "title_selector": ".product-title, h3, .product-name",
        "link_selector": "a",
        "sponsored_indicators": []
    },
    "instacart-publix": {
        "domains": ["instacart.com"],
        "search_urls": [
            "https://www.instacart.com/store/publix/search_v3/{query}"
        ],
        "product_selector": ".product-tile, .product-item, [data-testid='product-tile']",
        "title_selector": ".product-title, h3, .product-name",
        "link_selector": "a",
        "sponsored_indicators": []
    },
    "meijer": {
        "domains": ["meijer.com"],
        "search_urls": [
            "https://www.meijer.com/shopping/search.html?q={query}"
        ],
        "product_selector": ".product-tile, .product-item, [data-testid='product-tile']",
        "title_selector": ".product-title, h3, .product-name",
        "link_selector": "a",
        "sponsored_indicators": []
    },
    "staples": {
        "domains": ["staples.com"],
        "search_urls": [
            "https://www.staples.com/s/{query}",
            "https://www.staples.com/search?query={query}"
        ],
        "product_selector": ".product-tile, .product-item, [data-testid='product-tile'], .srp-product-item, .product-card, [class*='ProductCard']",
        "title_selector": ".product-title, h3, .product-name, [data-testid='product-title'], a[href*='/product']",
        "link_selector": "a",
        "sponsored_indicators": []
    },
    "wegmans": {
        "domains": ["wegmans.com"],
        "search_urls": [
            "https://www.wegmans.com/products/search.html?q={query}"
        ],
        "product_selector": ".product-tile, .product-item, [data-testid='product-tile']",
        "title_selector": ".product-title, h3, .product-name",
        "link_selector": "a",
        "sponsored_indicators": []
    },
    "bjs": {
        "domains": ["bjs.com"],
        "search_urls": [
            "https://www.bjs.com/search/{query}"
        ],
        "product_selector": ".product-tile, .product-item, [data-testid='product-tile']",
        "title_selector": ".product-title, h3, .product-name",
        "link_selector": "a",
        "sponsored_indicators": []
    },
    "sams-club": {
        "domains": ["samsclub.com"],
        "search_urls": [
            "https://www.samsclub.com/s/{query}"
        ],
        "product_selector": ".product-tile, .product-item, [data-testid='product-tile']",
        "title_selector": ".product-title, h3, .product-name",
        "link_selector": "a",
        "sponsored_indicators": []
    },
    "shoprite": {
        "domains": ["shoprite.com"],
        "search_urls": [
            "https://www.shoprite.com/sm/pickup/rsid/3000/search.html?q={query}"
        ],
        "product_selector": ".product-tile, .product-item, [data-testid='product-tile']",
        "title_selector": ".product-title, h3, .product-name",
        "link_selector": "a",
        "sponsored_indicators": []
    },
    
    # Australian Retailers
    "jbhifi": {
        "domains": ["jbhifi.com.au"],
        "search_urls": [
            "https://www.jbhifi.com.au/search/?q={query}",
            "https://www.jbhifi.com.au/search?q={query}",
            "https://www.jbhifi.com.au/search?query={query}"
        ],
        "product_selector": ".product-tile, .product-item, .ProductTile, [data-product-id], li.product",
        "title_selector": ".product-title, .product-name, h2, h3, a.product-title",
        "link_selector": "a",
        "sponsored_indicators": []
    },
    "harveynorman": {
        "domains": ["harveynorman.com.au"],
        "search_urls": [
            "https://www.harveynorman.com.au/catalogsearch/result/?q={query}",
            "https://www.harveynorman.com.au/search?q={query}"
        ],
        "product_selector": ".product-item, .product-tile",
        "title_selector": ".product-name, .product-title",
        "link_selector": "a",
        "sponsored_indicators": []
    }
}

# ==================== DATA STRUCTURES ====================

@dataclass
class ProductInfo:
    """Container for product information"""
    name: str
    gtin: Optional[str] = None
    retailer: str = ""
    original_name: str = ""

@dataclass
class SearchResult:
    """Container for search results"""
    url: str
    title: str
    retailer: str
    variant: str
    score: float
    is_sponsored: bool = False

@dataclass
class ProcessingResult:
    """Container for processing results"""
    success: bool
    url: str = ""
    title: str = ""
    retailer: str = ""
    variant: str = ""
    score: float = 0.0
    error: str = ""

# ==================== UTILITY FUNCTIONS ====================

def setup_logging(level: str = "INFO") -> None:
    """Setup logging configuration"""
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('product_finder.log'),
            logging.StreamHandler(sys.stdout)
        ]
    )

def normalize_text(text: str) -> str:
    """Normalize text for comparison"""
    if not text:
        return ""
    
    # Convert to lowercase and remove special characters
    text = re.sub(r'[^\w\s]', ' ', text.lower())
    text = re.sub(r'\s+', ' ', text).strip()
    
    return text

def extract_gtin(text: str) -> Optional[str]:
    """Extract GTIN from text"""
    if not text:
        return None
    
    # Remove all non-digits
    digits = re.sub(r'\D', '', str(text))
    
    # Check if it's a valid GTIN length
    if 8 <= len(digits) <= 14:
        return digits
    
    return None

def is_amazon_asin(text: str) -> bool:
    """Check if text is an Amazon ASIN"""
    if not text:
        return False
    text = str(text).strip().upper()
    # ASINs are 10 characters, alphanumeric, often start with B
    return len(text) == 10 and text.isalnum() and (text.startswith('B') or text.isdigit())

def is_walgreens_product_id(text: str) -> bool:
    """Check if text is a Walgreens product ID"""
    if not text:
        return False
    text = str(text).strip().upper()
    
    # Walgreens IDs can be:
    # - Numeric: 300462397, 300446423
    # - Alphanumeric starting with PROD: PROD6381251, prod6381498
    if text.startswith('PROD') and len(text) > 8:
        return True
    if text.isdigit() and len(text) >= 6 and len(text) <= 12:
        return True
    
    return False

def is_target_product_id(text: str) -> bool:
    """Check if text is a Target product ID (A-XXXXXXXX format)"""
    if not text:
        return False
    text = str(text).strip().upper()
    # Target IDs: A-53280541, A-87620145, A-90037671
    return text.startswith('A-') and len(text) >= 10 and text.replace('A-', '').isdigit()

def is_instacart_product_id(text: str) -> bool:
    """Check if text is an Instacart product ID"""
    if not text:
        return False
    text = str(text).strip()
    # Instacart IDs: 16295990, 78733, 20226744 (numeric, 5-8 digits)
    return text.isdigit() and 5 <= len(text) <= 8

def is_cvs_product_id(text: str) -> bool:
    """Check if text is a CVS product ID"""
    if not text:
        return False
    text = str(text).strip()
    # CVS IDs: 230355 (numeric, 5-7 digits typically)
    return text.isdigit() and 5 <= len(text) <= 8

def is_walmart_product_id(text: str) -> bool:
    """Check if text is a Walmart product ID"""
    if not text:
        return False
    text = str(text).strip()
    # Walmart IDs: 578410887 (numeric, 8-12 digits)
    return text.isdigit() and 8 <= len(text) <= 12

def is_heb_product_id(text: str) -> bool:
    """Check if text is an HEB product ID"""
    if not text:
        return False
    text = str(text).strip()
    # HEB IDs: 15145015 (numeric, 7-9 digits)
    return text.isdigit() and 7 <= len(text) <= 9

def is_hyvee_product_id(text: str) -> bool:
    """Check if text is a HyVee product ID"""
    if not text:
        return False
    text = str(text).strip()
    # HyVee IDs: 2608138, 2602336 (numeric, 6-8 digits)
    return text.isdigit() and 6 <= len(text) <= 8

def is_meijer_product_id(text: str) -> bool:
    """Check if text is a Meijer product ID"""
    if not text:
        return False
    text = str(text).strip().upper()
    # Meijer IDs: P4000052550, P4000052557 (starts with P followed by digits)
    return text.startswith('P') and len(text) > 8 and text[1:].isdigit()

def is_sams_club_product_id(text: str) -> bool:
    """Check if text is a Sam's Club product ID"""
    if not text:
        return False
    text = str(text).strip()
    # Sam's Club IDs: 4000004432, 15366017660 (numeric, 9-11 digits)
    return text.isdigit() and 9 <= len(text) <= 11

def is_gopuff_product_id(text: str) -> bool:
    """Check if text is a GoPuff product ID"""
    if not text:
        return False
    text = str(text).strip()
    # GoPuff IDs: 228282 (numeric, 5-7 digits)
    return text.isdigit() and 5 <= len(text) <= 7

def is_product_id(text: str) -> bool:
    """Check if text looks like a product ID rather than a product name"""
    if not text:
        return False
    text = str(text).strip()
    
    # If it's very short and mostly numeric/alphanumeric, likely an ID
    if len(text) < 15:
        # Check if it's mostly alphanumeric with few spaces
        if text.replace(' ', '').isalnum() and text.count(' ') < 2:
            # If it's all uppercase or all digits, likely an ID
            if text.isupper() or text.isdigit():
                return True
    
    # Amazon ASINs
    if is_amazon_asin(text):
        return True
    
    # Walgreens product IDs
    if is_walgreens_product_id(text):
        return True
    
    # Target product IDs
    if is_target_product_id(text):
        return True
    
    # Instacart product IDs
    if is_instacart_product_id(text):
        return True
    
    # CVS product IDs
    if is_cvs_product_id(text):
        return True
    
    # Walmart product IDs
    if is_walmart_product_id(text):
        return True
    
    # HEB product IDs
    if is_heb_product_id(text):
        return True
    
    # HyVee product IDs
    if is_hyvee_product_id(text):
        return True
    
    # Meijer product IDs
    if is_meijer_product_id(text):
        return True
    
    # Sam's Club product IDs
    if is_sams_club_product_id(text):
        return True
    
    # GoPuff product IDs
    if is_gopuff_product_id(text):
        return True
    
    # Very short numeric IDs
    if len(text) < 10 and text.isdigit():
        return True
    
    return False

def random_delay(min_delay: float = 1.0, max_delay: float = 3.0) -> None:
    """Add random delay to mimic human behavior"""
    delay = random.uniform(min_delay, max_delay)
    time.sleep(delay)

def clean_url(url: str) -> str:
    """Clean and normalize URL"""
    if not url:
        return ""
    
    # Remove fragments and normalize
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

# ==================== UPCITEMDB SCRAPING ====================

class UPCitemdbScraper:
    """Handles scraping of UPCitemdb.com for product information"""
    
    def __init__(self, config: Dict):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': config['user_agent'],
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
        })
    
    def search_by_gtin(self, gtin: str) -> List[str]:
        """Search UPCitemdb by GTIN and extract product name variations"""
        url = f"https://www.upcitemdb.com/upc/{gtin}"
        logging.info(f"Searching UPCitemdb by GTIN: {url}")
        
        try:
            response = self.session.get(url, timeout=20)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            return self._extract_variations(soup)
            
        except requests.RequestException as e:
            logging.error(f"Error searching UPCitemdb by GTIN {gtin}: {e}")
            return []
    
    def search_by_name(self, product_name: str) -> List[str]:
        """Search UPCitemdb by product name and extract variations"""
        search_url = f"https://www.upcitemdb.com/search?q={quote_plus(product_name)}"
        logging.info(f"Searching UPCitemdb by name: {search_url}")
        
        try:
            response = self.session.get(search_url, timeout=20)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')

            # Prefer: click into the first UPC result page to get authoritative variants
            first_upc_link = soup.find('a', href=re.compile(r'^/upc/\d+'))
            if first_upc_link and first_upc_link.get('href'):
                try:
                    upc_href = first_upc_link.get('href')
                    upc_url = f"https://www.upcitemdb.com{upc_href}"
                    logging.info(f"Following first UPC result: {upc_url}")
                    detail = self.session.get(upc_url, timeout=20)
                    detail.raise_for_status()
                    detail_soup = BeautifulSoup(detail.content, 'html.parser')
                    variants = self._extract_variations(detail_soup)
                    if variants:
                        return variants
                except Exception as e:
                    logging.warning(f"Failed to follow UPC detail from search: {e}")

            # Fallback: extract potential titles directly from the search results page
            return self._extract_variations(soup)
            
        except requests.RequestException as e:
            logging.error(f"Error searching UPCitemdb by name '{product_name}': {e}")
            return []
    
    def _extract_variations(self, soup: BeautifulSoup) -> List[str]:
        """Extract product name variations from UPCitemdb page"""
        variations = set()
        
        try:
            # Method 1: Look for the "Product Name Variations" section specifically
            # This section appears as: "has following Product Name Variations:" followed by an <ol>
            variations_heading = soup.find(string=re.compile(r'Product Name Variations', re.I))
            if variations_heading:
                # Find the parent element and then look for the ordered list
                parent = variations_heading.find_parent()
                if parent:
                    ol_element = parent.find_next('ol')
                    if ol_element:
                        for li in ol_element.find_all('li'):
                            text = li.get_text(strip=True)
                            # Remove leading numbers like "1. " or "2. "
                            text = re.sub(r'^\d+\.\s*', '', text).strip()
                            if text and len(text) > 5:
                                variations.add(text)
            
            # Method 2: Look for ordered list of variations (fallback)
            if not variations:
                ol_element = soup.find('ol')
                if ol_element:
                    for li in ol_element.find_all('li'):
                        text = li.get_text(strip=True)
                        text = re.sub(r'^\d+\.\s*', '', text).strip()
                        if text and len(text) > 5:
                            variations.add(text)
            
            # Method 3: Look for main product title (h1)
            main_title = soup.find('h1')
            if main_title:
                title = main_title.get_text(strip=True)
                if title and len(title) > 5:
                    variations.add(title)
            
            # Method 4: Look for product names in shopping info table
            # Find the "Shopping Info" section table
            shopping_table = soup.find('table')
            if shopping_table:
                for row in shopping_table.find_all('tr'):
                    cells = row.find_all(['td', 'th'])
                    for cell in cells:
                        text = cell.get_text(strip=True)
                        # Look for product names (not just numbers or short text)
                        if text and len(text) > 10 and not text.isdigit():
                            # Check if it looks like a product name
                            if any(char.isalpha() for char in text):
                                variations.add(text)
            
            # Method 5: Look for product titles in links (search results)
            for link in soup.find_all('a', href=re.compile(r'/upc/')):
                title = link.get_text(strip=True)
                if title and len(title) > 5:
                    variations.add(title)
            
        except Exception as e:
            logging.error(f"Error extracting variations: {e}")
        
        # Filter out junk/non-product strings
        junk_patterns = [
            r'^Country of Registration',
            r'^Last Scanned',
            r'^upcitemdb$',
            r'^United States$',
            r'^\d+$',  # Pure numbers
            r'^[:\-]\s*$',  # Just separators
            r'^Brand:',  # Metadata fields
            r'^EAN-13:',
            r'^UPC-A:',
            r'^\s*>\s*$',  # Just arrows
        ]
        
        # Clean and filter variations
        cleaned_variations = []
        for v in variations:
            v = v.strip()
            # Skip if too short
            if len(v) < 5:
                continue
            # Skip if matches junk patterns
            if any(re.match(pattern, v, re.I) for pattern in junk_patterns):
                continue
            # Skip if it's mostly special characters
            if len(re.sub(r'\w', '', v)) > len(v) * 0.5:
                continue
            # Must have at least some letters
            if not any(c.isalpha() for c in v):
                continue
            cleaned_variations.append(v)
        
        # Remove duplicates, limit, and return
        result = list(dict.fromkeys(cleaned_variations))[:self.config['max_variants']]
        logging.info(f"Found {len(result)} product variations: {result[:3]}..." if len(result) > 3 else f"Found {len(result)} product variations: {result}")
        return result

# ==================== RETAILER SEARCH ====================

class RetailerSearcher:
    """Handles searching retailers for products"""
    
    def __init__(self, config: Dict):
        self.config = config
        self.driver = None
        self.amazon_au_initialized = False
        self.amazon_us_initialized = False
        self._setup_driver()
    
    def _setup_driver(self) -> None:
        """Setup Chrome WebDriver with anti-bot detection measures"""
        try:
            chrome_options = Options()
            if self.config['headless']:
                chrome_options.add_argument("--headless=new")
            
            # Anti-bot detection measures
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-blink-features=AutomationControlled")
            chrome_options.add_argument(f"--user-agent={self.config['user_agent']}")
            chrome_options.add_argument("--window-size=1920,1080")
            
            # Additional stealth options to avoid detection
            chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
            chrome_options.add_experimental_option('useAutomationExtension', False)
            chrome_options.add_argument("--disable-blink-features=AutomationControlled")
            chrome_options.add_argument("--disable-infobars")
            chrome_options.add_argument("--disable-extensions")
            chrome_options.add_argument("--no-first-run")
            chrome_options.add_argument("--no-default-browser-check")
            chrome_options.add_argument("--disable-default-apps")
            
            # Language and locale settings (Australia)
            chrome_options.add_argument("--lang=en-AU")
            chrome_options.add_argument("--accept-lang=en-AU,en;q=0.9")
            
            # Additional anti-detection: disable automation flags
            prefs = {
                "credentials_enable_service": False,
                "profile.password_manager_enabled": False,
                "profile.default_content_setting_values.notifications": 2
            }
            chrome_options.add_experimental_option("prefs", prefs)
            
            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=chrome_options)
            self.driver.set_page_load_timeout(self.config['page_load_timeout'])
            
            # Use selenium-stealth if available for better bot detection evasion
            if STEALTH_AVAILABLE:
                try:
                    stealth(
                        self.driver,
                        languages=["en-US", "en"],
                        vendor="Google Inc.",
                        platform="Win32",
                        webgl_vendor="Intel Inc.",
                        renderer="Intel Iris OpenGL Engine",
                        fix_hairline=True,
                    )
                    logging.info("✓ Selenium-stealth enabled for better bot detection evasion")
                except Exception as e:
                    logging.warning(f"Failed to apply selenium-stealth: {e}, using fallback methods")
                    # Fallback to manual stealth scripts
                    self._apply_manual_stealth()
            else:
                # Fallback: Execute manual stealth scripts
                logging.debug("Selenium-stealth not available, using manual stealth methods. Install with: pip install selenium-stealth")
                self._apply_manual_stealth()
        except Exception as e:
            logging.error(f"Error setting up WebDriver: {e}")
            raise
    
    def _apply_manual_stealth(self) -> None:
        """Apply manual stealth techniques when selenium-stealth is not available"""
        try:
            # Execute script to remove webdriver property and add realistic properties
            self.driver.execute_cdp_cmd('Network.setUserAgentOverride', {
                "userAgent": self.config['user_agent']
            })
            # Remove webdriver property
            self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            # Add realistic Chrome properties
            self.driver.execute_script("""
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [1, 2, 3, 4, 5]
                });
                Object.defineProperty(navigator, 'languages', {
                    get: () => ['en-US', 'en']
                });
                window.chrome = { runtime: {} };
            """)
        except Exception as e:
            logging.debug(f"Manual stealth application failed: {e}")
    
    def close(self) -> None:
        """Close the WebDriver"""
        if self.driver:
            try:
                self.driver.quit()
            except Exception as e:
                logging.error(f"Error closing WebDriver: {e}")

if __name__ == "__main__":
    main()
