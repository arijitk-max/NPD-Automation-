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
    "fuzzy_threshold": 70,  # Balanced threshold - finds more products while maintaining accuracy
    "request_delay": (1.0, 3.0),
    "page_load_timeout": 30,
    "max_retries": 3,
    "save_interval": 5,
    "max_results_per_retailer": 25,  # Only check first 25 non-sponsored results
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
            "https://www.staples.com/{query_plus}/directory_{query_double_encoded}"
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
    },
    "costco": {
        "domains": ["costco.com"],
        "search_urls": [
            "https://www.costco.com/CatalogSearch?dept=All&keyword={query}",
            "https://www.costco.com/CatalogSearch?keyword={query}"
        ],
        "product_selector": ".product, .product-tile, [data-automation-id='product-tile'], .product-list-item",
        "title_selector": ".description, .product-title, h3, a[data-automation-id='product-title']",
        "link_selector": "a",
        "sponsored_indicators": []
    },
    "costco-us": {
        "domains": ["costco.com"],
        "search_urls": [
            "https://www.costco.com/CatalogSearch?dept=All&keyword={query}",
            "https://www.costco.com/CatalogSearch?keyword={query}"
        ],
        "product_selector": ".product, .product-tile, [data-automation-id='product-tile'], .product-list-item",
        "title_selector": ".description, .product-title, h3, a[data-automation-id='product-title']",
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
    
    def search_retailer(self, retailer: str, query: str) -> List[SearchResult]:
        """Search a specific retailer for a product"""
        if retailer not in RETAILERS:
            logging.warning(f"Unknown retailer: {retailer}")
            return []
        # Never search retailers with raw GTIN-only strings
        if re.fullmatch(r"\d+", str(query).strip() or ""):
            logging.info("Skipping retailer search with numeric-only query (likely GTIN): %s", query)
            return []
        
        retailer_config = RETAILERS[retailer]
        results = []
        
        # Quick location check for Amazon AU - only change if India, accept if already Australia/2000
        # Note: This only runs for amazon-au, not for regular amazon (US)
        if retailer == "amazon-au":
            if not self.amazon_au_initialized:
                # Quick check - only set if India
                try:
                    self.driver.get("https://www.amazon.com.au/")
                    time.sleep(1.0)  # Faster check
                    try:
                        location_el = self.driver.find_element(By.CSS_SELECTOR, "span#glow-ingress-line2")
                        current_location = location_el.text.strip().lower()
                        # Accept if already Australia/2000/Parliament House
                        if any(indicator in current_location for indicator in ['2000', 'parliament', 'sydney', 'australia', 'au', 'nsw']):
                            logging.info(f"Location already set to Australia: {location_el.text.strip()}")
                            self.amazon_au_initialized = True
                        elif 'india' in current_location:
                            logging.info("Location is India, setting to Australia...")
                            self._quick_set_amazon_au(postcode="2000")
                            self.amazon_au_initialized = True
                        else:
                            # Unknown location, try quick set
                            self._quick_set_amazon_au(postcode="2000")
                            self.amazon_au_initialized = True
                    except:
                        # Element not found, try quick set anyway
                        self._quick_set_amazon_au(postcode="2000")
                        self.amazon_au_initialized = True
                except Exception as e:
                    logging.debug(f"Quick location check failed: {e}")
        
        # Set Amazon US location (postcode 07008)
        if retailer in ["amazon", "amazon-fresh"]:
            if not self.amazon_us_initialized:
                try:
                    self.driver.get("https://www.amazon.com/")
                    time.sleep(1.0)
                    try:
                        location_el = self.driver.find_element(By.CSS_SELECTOR, "span#glow-ingress-line2")
                        current_location = location_el.text.strip().lower()
                        # Accept if already US/07008
                        if any(indicator in current_location for indicator in ['07008', 'new jersey', 'nj', 'united states', 'us']):
                            logging.info(f"Location already set to US: {location_el.text.strip()}")
                            self.amazon_us_initialized = True
                        else:
                            # Set to US location
                            logging.info("Setting Amazon US location to postcode 07008...")
                            self._quick_set_amazon_us(postcode="07008")
                            self.amazon_us_initialized = True
                    except:
                        # Element not found, try quick set anyway
                        self._quick_set_amazon_us(postcode="07008")
                        self.amazon_us_initialized = True
                except Exception as e:
                    logging.debug(f"Quick Amazon US location check failed: {e}")

        for search_url in retailer_config['search_urls']:
            try:
                # Special handling for Staples URL format
                if retailer == "staples" and "{query_plus}" in search_url:
                    # Staples format: /{query_with_pluses}/directory_{double_encoded_query}
                    # First part: lowercase, replace spaces with +, keep other characters
                    query_plus = query.lower().replace(" ", "+")
                    # Second part: double URL encode the original query
                    query_double_encoded = quote_plus(quote_plus(query))
                    url = search_url.format(query_plus=query_plus, query_double_encoded=query_double_encoded)
                else:
                    url = search_url.format(query=quote_plus(query))
                logging.info(f"Searching {retailer}: {url}")
                
                # Add delay before navigation (longer for Harvey Norman to avoid bot detection)
                if retailer == "harveynorman":
                    pre_delay = random.uniform(3.0, 5.0)  # Longer pre-delay for Harvey Norman
                    logging.debug(f"Pre-navigation delay for Harvey Norman: {pre_delay:.1f}s")
                    time.sleep(pre_delay)
                elif retailer == "jbhifi":
                    delay = random.uniform(0.5, 1.0)  # Further reduced delay for JB Hi-Fi to speed up
                    time.sleep(delay)
                else:
                    delay = random.uniform(1.5, 2.5)
                    time.sleep(delay)
                
                self.driver.get(url)
                
                # Add delay after navigation to avoid rate limiting
                if retailer == "harveynorman":
                    post_delay = random.uniform(2.5, 4.0)  # Longer post-delay for Harvey Norman
                    time.sleep(post_delay)
                elif retailer == "jbhifi":
                    delay = random.uniform(0.5, 1.0)  # Further reduced delay for JB Hi-Fi to speed up
                    time.sleep(delay)
                else:
                    delay = random.uniform(1.0, 2.0)
                    time.sleep(delay)
                
                # Wait for page to be interactive
                try:
                    WebDriverWait(self.driver, 8).until(
                        lambda d: d.execute_script('return document.readyState') == 'complete'
                    )
                except:
                    pass
                
                # Wait for search results to load (retailer-specific with longer waits)
                try:
                    if retailer == "amazon":
                        # Wait for Amazon search results container
                        WebDriverWait(self.driver, 10).until(
                            lambda d: len(d.find_elements(By.CSS_SELECTOR, "[data-component-type='s-search-result'], .s-result-item, [data-asin]")) > 0
                        )
                        logging.debug("Amazon search results loaded")
                    elif retailer == "jbhifi":
                        # Wait for JB Hi-Fi results - optimized for speed
                        time.sleep(0.5)  # Minimal initial wait
                        try:
                            WebDriverWait(self.driver, 8).until(  # Reduced from 10 to 8
                                lambda d: len(d.find_elements(By.CSS_SELECTOR, ".product, .product-tile, .ProductTile, [data-product-id], a[href*='/products/'], a[href*='/product/'], [class*='Product'], [class*='product']")) > 0 or 
                                         "no results" in d.find_element(By.TAG_NAME, "body").text.lower() or
                                         "0 results" in d.find_element(By.TAG_NAME, "body").text.lower() or
                                         "did not match" in d.find_element(By.TAG_NAME, "body").text.lower()
                            )
                        except TimeoutException:
                            # Log what's actually on the page for debugging
                            try:
                                page_text = self.driver.find_element(By.TAG_NAME, "body").text[:500]
                                link_count = len(self.driver.find_elements(By.TAG_NAME, "a"))
                                logging.debug(f"JB Hi-Fi timeout - Page text preview: {page_text[:200]}... | Links: {link_count}")
                            except:
                                pass
                        time.sleep(0.3)  # Minimal wait for lazy loading
                        logging.debug("JB Hi-Fi search results loaded")
                    elif retailer == "harveynorman":
                        # Wait for Harvey Norman results - wait longer and add delays
                        # Add realistic mouse movements and delays to avoid bot detection
                        time.sleep(random.uniform(2.5, 4.0))  # Random delay to mimic human behavior
                        try:
                            # Simulate mouse movement (move cursor slightly)
                            self.driver.execute_script("document.dispatchEvent(new MouseEvent('mousemove', {view: window, bubbles: true, cancelable: true}));")
                            time.sleep(0.5)
                            
                            WebDriverWait(self.driver, 15).until(
                                lambda d: len(d.find_elements(By.CSS_SELECTOR, ".product, .product-item, .product-tile, [data-product], li.item, a[href*='/product']")) > 0 or
                                         "no results" in d.find_element(By.TAG_NAME, "body").text.lower() or
                                         "captcha" in d.find_element(By.TAG_NAME, "body").text.lower() or
                                         "security" in d.find_element(By.TAG_NAME, "body").text.lower() or
                                         "imperva" in d.find_element(By.TAG_NAME, "body").text.lower()
                            )
                        except TimeoutException:
                            pass  # Will be caught by captcha check below
                        time.sleep(random.uniform(1.5, 2.5))  # Extra random wait
                        logging.debug("Harvey Norman search results loaded")
                except Exception as e:
                    logging.debug(f"Wait for results timed out (this is okay if page loaded differently): {e}")
                
                # Scroll to trigger lazy loading (optimized delays for JB Hi-Fi to speed up)
                if retailer == "jbhifi":
                    self.driver.execute_script("window.scrollTo(0, 500);")
                    time.sleep(0.2)  # Minimal wait
                    self.driver.execute_script("window.scrollTo(0, 1000);")
                    time.sleep(0.1)  # Minimal wait
                else:
                    self.driver.execute_script("window.scrollTo(0, 500);")
                    time.sleep(1.0)  # Wait for lazy-loaded content
                    self.driver.execute_script("window.scrollTo(0, 1000);")
                    time.sleep(0.8)
                    self.driver.execute_script("window.scrollTo(0, 1500);")
                    time.sleep(0.5)
                
                # Debug: Log page info
                try:
                    page_title = self.driver.title
                    link_count = len(self.driver.find_elements(By.TAG_NAME, "a"))
                    logging.debug(f"Page title: {page_title}, Total links: {link_count}")
                except:
                    pass
                
                # Check for error messages, captchas, or no results
                try:
                    page_text = self.driver.find_element(By.TAG_NAME, "body").text.lower()
                    error_indicators = ['no results', 'no products found', 'try again', 'captcha', 'verify you are human', 'access denied', 'blocked']
                    if any(indicator in page_text for indicator in error_indicators):
                        logging.warning(f"⚠️ Possible error or blocking detected on {retailer} page")
                    if 'did not match any products' in page_text or 'no products' in page_text:
                        logging.info(f"Search query returned no results on {retailer}")
                except:
                    pass
                
                # Check for captcha/bot detection before extracting
                # But don't skip extraction - just log a warning and continue
                captcha_detected = self._check_captcha_or_blocked(retailer)
                if captcha_detected:
                    # If CAPTCHA detected, wait for user to solve it manually (if in non-headless mode)
                    if not self.config.get('headless', True):
                        # Longer wait for Harvey Norman (Imperva/hCaptcha can take longer)
                        wait_time = 30 if retailer == "harveynorman" else 10  # Increased wait for Harvey Norman
                        logging.warning(f"⚠️ CAPTCHA detected on {retailer}. Waiting {wait_time} seconds for manual solving...")
                        logging.warning(f"   Please solve the CAPTCHA in the browser window. The script will continue after {wait_time} seconds.")
                        time.sleep(wait_time)  # Wait for user to solve CAPTCHA
                        # Don't refresh - just wait a bit more and check if CAPTCHA is gone
                        time.sleep(2)  # Small delay to let page update after solving
                        # Re-check if CAPTCHA is still there (without refreshing, as that might trigger it again)
                        try:
                            captcha_still_there = self._check_captcha_or_blocked(retailer)
                            if captcha_still_there:
                                logging.warning(f"⚠️ CAPTCHA still detected after wait. Will attempt extraction anyway...")
                            else:
                                logging.info(f"✓ CAPTCHA appears to be solved. Continuing extraction...")
                        except:
                            logging.info(f"Continuing extraction (could not verify CAPTCHA status)...")
                    else:
                        # In headless mode, for Harvey Norman, try to wait a bit longer and retry
                        if retailer == "harveynorman":
                            logging.warning(f"⚠️ CAPTCHA detected on Harvey Norman in headless mode. Waiting 5 seconds and retrying...")
                            time.sleep(5)
                            # Try refreshing once
                            try:
                                self.driver.refresh()
                                time.sleep(3)
                            except:
                                pass
                        else:
                            # In headless mode for other retailers, log warning but still try to extract
                            logging.debug(f"⚠️ CAPTCHA or bot detection detected on {retailer} (likely false positive). Will attempt extraction anyway...")
                        # Don't skip - continue to extraction
                
                # Extract search results (limited to first N non-sponsored results)
                search_results = self._extract_search_results(retailer, retailer_config)
                # Filter out sponsored results and limit to first N non-sponsored
                total_results = len(search_results)
                non_sponsored = [r for r in search_results if not r.is_sponsored]
                max_results = self.config.get('max_results_per_retailer', 25)
                search_results = non_sponsored[:max_results]
                sponsored_count = total_results - len(non_sponsored)
                if sponsored_count > 0:
                    logging.info(f"Filtered out {sponsored_count} sponsored results, keeping {len(search_results)} non-sponsored")
                logging.info(f"Using {len(search_results)} non-sponsored results (max {max_results})")
                
                # Log diagnostic info for JB Hi-Fi
                if retailer == "jbhifi":
                    if search_results:
                        logging.info(f"✓ JB Hi-Fi: Found {len(search_results)} products (showing first 3):")
                        for i, r in enumerate(search_results[:3]):
                            logging.info(f"  {i+1}. {r.title[:70]}... | {r.url[:80]}...")
                    else:
                        logging.warning(f"⚠️ JB Hi-Fi: No products extracted. Checking page content...")
                        try:
                            # Diagnostic: check what's actually on the page
                            page_url = self.driver.current_url
                            page_title = self.driver.title
                            all_links = self.driver.find_elements(By.TAG_NAME, "a")
                            product_links = [l.get_attribute('href') for l in all_links if l.get_attribute('href') and ('/products/' in l.get_attribute('href') or '/product/' in l.get_attribute('href'))]
                            logging.warning(f"  Page URL: {page_url}")
                            logging.warning(f"  Page Title: {page_title}")
                            logging.warning(f"  Total links: {len(all_links)}, Product-like links: {len(product_links)}")
                            if product_links:
                                logging.warning(f"  Sample product URLs: {product_links[:3]}")
                        except Exception as e:
                            logging.debug(f"  Diagnostic failed: {e}")
                
                results.extend(search_results)
                
                # CRITICAL: If we found results, don't try other URLs - this saves a lot of time!
                if results:
                    logging.info(f"✓ Found {len(results)} results on first URL, skipping remaining URLs to save time")
                    break
                    
            except Exception as e:
                logging.error(f"Error searching {retailer} with query '{query}': {e}")
                continue
        
        return results

    def _quick_set_amazon_au(self, postcode: str = "2000") -> None:
        """Quick and simple location setter - only sets postcode, no city name."""
        logging.info(f"Quick setting Amazon AU location to postcode {postcode}")
        
        try:
            # Method 1: Direct API call via JavaScript (fastest)
            self.driver.get("https://www.amazon.com.au/")
            time.sleep(1.0)
            
            # Try JavaScript fetch to set location
            try:
                self.driver.execute_script(f"""
                    fetch('https://www.amazon.com.au/gp/delivery/ajax/address-change.html', {{
                        method: 'POST',
                        headers: {{'Content-Type': 'application/x-www-form-urlencoded'}},
                        body: 'locationType=LOCATION_INPUT&zipCode={postcode}&storeContext=generic&deviceType=web&pageType=Detail&actionSource=glow',
                        credentials: 'include'
                    }}).catch(() => {{}});
                """)
                time.sleep(1.5)
                self.driver.refresh()
                time.sleep(1.0)
                logging.info("Quick method: API call completed")
            except:
                pass
            
            # Method 2: Quick UI click if API didn't work
            try:
                # Find and click location link quickly
                wait = WebDriverWait(self.driver, 5)
                try:
                    location_link = wait.until(
                        EC.element_to_be_clickable((By.ID, "nav-global-location-popover-link"))
                    )
                    self.driver.execute_script("arguments[0].click();", location_link)
                    time.sleep(1.5)  # Wait for popup
                    
                    # Find postcode input and enter ONLY postcode (no city)
                    zip_input = wait.until(
                        EC.presence_of_element_located((By.ID, "GLUXZipUpdateInput"))
                    )
                    self.driver.execute_script("arguments[0].value = '';", zip_input)
                    zip_input.clear()
                    zip_input.send_keys(postcode)
                    time.sleep(0.5)
                    
                    # Click apply
                    apply_btn = wait.until(
                        EC.element_to_be_clickable((By.ID, "GLUXZipUpdate"))
                    )
                    apply_btn.click()
                    time.sleep(2.0)
                    logging.info("Quick method: UI interaction completed")
                except:
                    pass
            except:
                pass
            
            # Method 3: Cookies as fallback
            try:
                self.driver.add_cookie({'name': 'gl', 'value': 'AU', 'domain': '.amazon.com.au'})
                self.driver.refresh()
                time.sleep(1.0)
            except:
                pass
                
        except Exception as e:
            logging.debug(f"Quick location set failed: {e}")

    def _quick_set_amazon_us(self, postcode: str = "07008") -> None:
        """Quick and simple location setter for Amazon US - only sets postcode, no city name."""
        logging.info(f"Quick setting Amazon US location to postcode {postcode}")
        
        try:
            # Method 1: Direct API call via JavaScript (fastest)
            self.driver.get("https://www.amazon.com/")
            time.sleep(1.0)
            
            # Try JavaScript fetch to set location
            try:
                self.driver.execute_script(f"""
                    fetch('https://www.amazon.com/gp/delivery/ajax/address-change.html', {{
                        method: 'POST',
                        headers: {{'Content-Type': 'application/x-www-form-urlencoded'}},
                        body: 'locationType=LOCATION_INPUT&zipCode={postcode}&storeContext=generic&deviceType=web&pageType=Detail&actionSource=glow',
                        credentials: 'include'
                    }}).catch(() => {{}});
                """)
                time.sleep(1.5)
                self.driver.refresh()
                time.sleep(1.0)
                logging.info("Quick method: API call completed for Amazon US")
            except:
                pass
            
            # Method 2: Quick UI click if API didn't work
            try:
                # Find and click location link quickly
                wait = WebDriverWait(self.driver, 5)
                try:
                    location_link = wait.until(
                        EC.element_to_be_clickable((By.ID, "nav-global-location-popover-link"))
                    )
                    self.driver.execute_script("arguments[0].click();", location_link)
                    time.sleep(1.5)  # Wait for popup
                    
                    # Find postcode input and enter ONLY postcode (no city)
                    zip_input = wait.until(
                        EC.presence_of_element_located((By.ID, "GLUXZipUpdateInput"))
                    )
                    self.driver.execute_script("arguments[0].value = '';", zip_input)
                    zip_input.clear()
                    zip_input.send_keys(postcode)
                    time.sleep(0.5)
                    
                    # Click apply
                    apply_btn = wait.until(
                        EC.element_to_be_clickable((By.ID, "GLUXZipUpdate"))
                    )
                    apply_btn.click()
                    time.sleep(2.0)
                    logging.info("Quick method: UI interaction completed for Amazon US")
                except:
                    pass
            except:
                pass
            
            # Method 3: Cookies as fallback
            try:
                self.driver.add_cookie({'name': 'gl', 'value': 'US', 'domain': '.amazon.com'})
                self.driver.refresh()
                time.sleep(1.0)
            except:
                pass
                
        except Exception as e:
            logging.debug(f"Quick Amazon US location set failed: {e}")

    def _ensure_amazon_au_context(self, postcode: str = "2000") -> None:
        """Set Amazon AU delivery location to Sydney, Australia (postcode 2000).
        
        Uses a comprehensive approach: cookies + direct API call + UI interaction.
        """
        logging.info(f"Setting Amazon AU delivery location to postcode {postcode} (Sydney)")
        wait = WebDriverWait(self.driver, 10)
        
        try:
            # METHOD 1: Direct API call using requests (most reliable)
            try:
                logging.info("Method 1: Attempting direct API call to set location...")
                # Get session cookies from browser
                cookies_dict = {}
                for cookie in self.driver.get_cookies():
                    cookies_dict[cookie['name']] = cookie['value']
                
                # Make POST request to Amazon's location API
                api_url = "https://www.amazon.com.au/gp/delivery/ajax/address-change.html"
                headers = {
                    'User-Agent': self.config['user_agent'],
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'en-AU,en;q=0.9',
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'Origin': 'https://www.amazon.com.au',
                    'Referer': 'https://www.amazon.com.au/',
                }
                
                # First ensure we're on Amazon AU
                self.driver.get("https://www.amazon.com.au/")
                time.sleep(2.0)
                
                # Now try to set location via JavaScript fetch API
                js_result = self.driver.execute_script(f"""
                    return fetch('{api_url}', {{
                        method: 'POST',
                        headers: {{
                            'Content-Type': 'application/x-www-form-urlencoded',
                        }},
                        body: 'locationType=LOCATION_INPUT&zipCode={postcode}&storeContext=generic&deviceType=web&pageType=Detail&actionSource=glow',
                        credentials: 'include'
                    }}).then(r => r.ok).catch(() => false);
                """)
                
                if js_result:
                    self.driver.refresh()
                    time.sleep(2.0)
                    logging.info("Method 1: API call may have succeeded")
            except Exception as e:
                logging.debug(f"Method 1 (API call) failed: {e}")
            
            # METHOD 2: Comprehensive cookie setup
            try:
                logging.info("Method 2: Setting comprehensive cookies...")
                self.driver.get("https://www.amazon.com.au/")
                time.sleep(1.5)
                
                # Delete conflicting cookies
                cookies_to_delete = ['gl', 'ubid-main', 'session-id', 'csm-hit']
                for cookie_name in cookies_to_delete:
                    try:
                        self.driver.delete_cookie(cookie_name)
                    except:
                        pass
                
                # Set comprehensive Australia cookies
                aus_cookies = [
                    {'name': 'gl', 'value': 'AU', 'domain': '.amazon.com.au'},
                    {'name': 'lc-acbau', 'value': 'en_AU', 'domain': '.amazon.com.au'},
                    {'name': 'i18n-prefs', 'value': 'AUD', 'domain': '.amazon.com.au'},
                ]
                
                for cookie in aus_cookies:
                    try:
                        self.driver.add_cookie(cookie)
                    except Exception as e:
                        logging.debug(f"Could not add cookie {cookie['name']}: {e}")
                
                self.driver.refresh()
                time.sleep(2.0)
                logging.info("Method 2: Cookies set")
            except Exception as e:
                logging.debug(f"Method 2 (Cookies) failed: {e}")
            
            # METHOD 3: UI interaction - Click "Deliver to" and change location
            try:
                logging.info("Method 3: Attempting UI interaction...")
                self.driver.get("https://www.amazon.com.au/")
                time.sleep(3.0)
                
                # Strategy A: Find location link using explicit wait
                location_link = None
                location_selectors = [
                    (By.ID, "nav-global-location-popover-link"),
                    (By.XPATH, "//a[@id='nav-global-location-popover-link']"),
                    (By.XPATH, "//span[contains(text(), 'Deliver to')]/ancestor::a[1]"),
                    (By.XPATH, "//span[contains(text(), 'India')]/ancestor::a[1]"),
                    (By.CSS_SELECTOR, "a#nav-global-location-popover-link"),
                ]
                
                for selector_type, selector_value in location_selectors:
                    try:
                        location_link = wait.until(
                            EC.element_to_be_clickable((selector_type, selector_value))
                        )
                        if location_link:
                            break
                    except:
                        continue
                
                if not location_link:
                    # Try JavaScript approach
                    location_link = self.driver.execute_script("""
                        var link = document.querySelector('a#nav-global-location-popover-link');
                        if (link) return link;
                        var spans = document.querySelectorAll('span#glow-ingress-line2');
                        for (var s of spans) {
                            var parent = s.closest('a');
                            if (parent) return parent;
                        }
                        return null;
                    """)
                
                if location_link:
                    # Scroll into view and click
                    self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", location_link)
                    time.sleep(0.5)
                    
                    try:
                        location_link.click()
                    except:
                        self.driver.execute_script("arguments[0].click();", location_link)
                    
                    time.sleep(2.5)  # Wait for popup
                    logging.info("Method 3: Clicked location link")
                    
                    # Now find and fill postcode input
                    zip_input = None
                    zip_selectors = [
                        (By.ID, "GLUXZipUpdateInput"),
                        (By.NAME, "locationPostalCode"),
                        (By.XPATH, "//input[contains(@id, 'zip') or contains(@id, 'postal')]"),
                        (By.CSS_SELECTOR, "input[type='text'][name*='zip'], input[type='text'][name*='postal']"),
                    ]
                    
                    for selector_type, selector_value in zip_selectors:
                        try:
                            zip_input = wait.until(
                                EC.presence_of_element_located((selector_type, selector_value))
                            )
                            if zip_input and zip_input.is_displayed():
                                break
                        except:
                            zip_input = None
                            continue
                    
                    if zip_input:
                        # Clear and enter postcode
                        self.driver.execute_script("arguments[0].value = '';", zip_input)
                        zip_input.clear()
                        time.sleep(0.3)
                        zip_input.send_keys(postcode)
                        time.sleep(0.5)
                        logging.info(f"Method 3: Entered postcode {postcode}")
                        
                        # Find and click apply button
                        apply_btn = None
                        apply_selectors = [
                            (By.ID, "GLUXZipUpdate"),
                            (By.ID, "GLUXZipUpdate-announce"),
                            (By.XPATH, "//button[contains(text(), 'Apply')]"),
                            (By.XPATH, "//input[@type='submit']"),
                        ]
                        
                        for selector_type, selector_value in apply_selectors:
                            try:
                                apply_btn = wait.until(
                                    EC.element_to_be_clickable((selector_type, selector_value))
                                )
                                if apply_btn:
                                    break
                            except:
                                continue
                        
                        if apply_btn:
                            try:
                                apply_btn.click()
                            except:
                                self.driver.execute_script("arguments[0].click();", apply_btn)
                            time.sleep(3.0)
                            logging.info("Method 3: Clicked apply button")
                else:
                    logging.warning("Method 3: Could not find location link")
                    
            except Exception as e:
                logging.debug(f"Method 3 (UI interaction) failed: {e}")
            
            # METHOD 4: Direct URL with postcode
            try:
                logging.info("Method 4: Trying direct URL method...")
                url_with_location = f"https://www.amazon.com.au/?&location={postcode}"
                self.driver.get(url_with_location)
                time.sleep(2.0)
                logging.info("Method 4: Direct URL accessed")
            except Exception as e:
                logging.debug(f"Method 4 (Direct URL) failed: {e}")
            
            # METHOD 5: LocalStorage and sessionStorage manipulation
            try:
                logging.info("Method 5: Setting localStorage...")
                self.driver.execute_script(f"""
                    localStorage.setItem('a-state-postal-code', '{postcode}');
                    localStorage.setItem('a-state-global', 'AU');
                    localStorage.setItem('glow-customer-country-code', 'AU');
                    sessionStorage.setItem('glow-customer-country-code', 'AU');
                """)
                self.driver.refresh()
                time.sleep(2.0)
                logging.info("Method 5: localStorage set")
            except Exception as e:
                logging.debug(f"Method 5 (LocalStorage) failed: {e}")
            
            # FINAL VERIFICATION
            self.driver.get("https://www.amazon.com.au/")
            time.sleep(2.5)
            
            try:
                # Check current location
                location_text = ""
                try:
                    location_span = wait.until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "span#glow-ingress-line2"))
                    )
                    location_text = location_span.text.strip().lower()
                    logging.info(f"Final location check: '{location_text}'")
                except:
                    pass
                
                page_source = self.driver.page_source.lower()
                
                # Determine if location is correct
                is_india = 'india' in location_text or ('deliver to' in page_source and 'india' in location_text)
                is_australia = any([
                    '2000' in page_source,
                    'sydney' in page_source,
                    'australia' in location_text,
                    'au' in location_text and 'india' not in location_text,
                    'nsw' in location_text,
                    'new south wales' in location_text.lower(),
                ])
                
                if is_india:
                    logging.error("❌ Location is still set to India after all methods!")
                    logging.error("All location-setting methods have been exhausted.")
                elif is_australia:
                    logging.info(f"✓ SUCCESS: Location set to Sydney, Australia (postcode {postcode})")
                else:
                    logging.warning("⚠ Could not verify location, but methods executed")
                    
            except Exception as e:
                logging.debug(f"Final verification failed: {e}")
                
        except Exception as e:
            logging.error(f"Critical error in location setting: {e}")
            # Continue anyway - we tried our best
    
    def _check_captcha_or_blocked(self, retailer: str) -> bool:
        """Check if page shows CAPTCHA or bot detection"""
        try:
            page_text = self.driver.find_element(By.TAG_NAME, "body").text.lower()
            page_source = self.driver.page_source.lower()
            page_title = self.driver.title.lower()
            
            # Common CAPTCHA/bot detection indicators (including hCaptcha and Imperva)
            captcha_indicators = [
                'captcha', 'verify you are human', 'verify you\'re not a robot',
                'i am human', 'automated bot', 'access denied', 'blocked', 
                'security check', 'additional security check', 'unusual traffic', 
                'suspicious activity', 'please verify', 'human verification', 
                'cloudflare', 'challenge', 'ray id', 'hcaptcha', 'imperva',
                'protected and accelerated by imperva', 'virus and malware scan'
            ]
            
            # Retailer-specific checks
            if retailer == "harveynorman":
                # Harvey Norman specific patterns - Imperva/hCaptcha detection
                if any(ind in page_text or ind in page_title or ind in page_source for ind in captcha_indicators):
                    logging.warning(f"⚠️ CAPTCHA/Bot detection detected on Harvey Norman (likely Imperva/hCaptcha)")
                    return True
                # Check for Imperva-specific text
                if 'imperva' in page_source or 'additional security check' in page_text:
                    logging.warning(f"⚠️ Imperva security check detected on Harvey Norman")
                    return True
                # Check for hCaptcha checkbox
                try:
                    hcaptcha_checkbox = self.driver.find_elements(By.XPATH, 
                        "//*[contains(@class, 'hcaptcha') or contains(text(), 'I am human')]")
                    if hcaptcha_checkbox:
                        logging.warning(f"⚠️ hCaptcha challenge detected on Harvey Norman")
                        return True
                except:
                    pass
            
            # Generic checks - ONLY check visible text and title, NOT page_source (which has JS/CSS with "captcha" always)
            # page_source will always contain "captcha" in JavaScript code, causing false positives
            for indicator in captcha_indicators:
                # Only check visible text and title - NOT page_source
                if indicator in page_text or indicator in page_title:
                    # Double-check: is there actually a visible CAPTCHA element?
                    try:
                        visible_captcha = self.driver.find_elements(
                            By.XPATH, 
                            "//*[contains(@class, 'captcha') or contains(@id, 'captcha') or contains(@class, 'hcaptcha') or contains(@id, 'hcaptcha')]"
                        )
                        # Only return True if there's an actual visible CAPTCHA element
                        if visible_captcha:
                            # Check if it's actually visible (not hidden)
                            visible_count = 0
                            for elem in visible_captcha[:3]:  # Check first 3
                                try:
                                    if elem.is_displayed():
                                        visible_count += 1
                                except:
                                    pass
                            if visible_count > 0:
                                logging.warning(f"⚠️ CAPTCHA/Bot detection keyword '{indicator}' found on {retailer} with {visible_count} visible CAPTCHA element(s)")
                                return True
                            else:
                                logging.debug(f"⚠️ CAPTCHA keyword '{indicator}' found but CAPTCHA elements are hidden - likely false positive")
                        else:
                            # Word found but no visible CAPTCHA - definitely false positive
                            logging.debug(f"⚠️ CAPTCHA keyword '{indicator}' found in text but no visible CAPTCHA element - ignoring false positive")
                    except:
                        pass
            
            # Check for specific CAPTCHA elements (hCaptcha, reCAPTCHA, etc.)
            try:
                captcha_elements = self.driver.find_elements(
                    By.XPATH, 
                    "//*[contains(@class, 'captcha') or contains(@id, 'captcha') or contains(@class, 'hcaptcha') or contains(@id, 'hcaptcha') or contains(text(), 'captcha') or contains(text(), 'verify') or contains(text(), 'I am human')]"
                )
                if captcha_elements:
                    return True
            except:
                pass
            
            return False
        except Exception as e:
            logging.debug(f"Error checking for CAPTCHA: {e}")
            return False
    
    def _extract_search_results(self, retailer: str, config: Dict) -> List[SearchResult]:
        """Extract search results from retailer page"""
        results = []
        
        try:
            # Find product elements with multiple selector strategies
            product_elements = []
            
            # Try primary selector
            try:
                product_elements = self.driver.find_elements(By.CSS_SELECTOR, config['product_selector'])
                logging.debug(f"Found {len(product_elements)} product elements using primary selector")
            except Exception as e:
                logging.debug(f"Primary selector failed: {e}")
            
            # If no products found, try alternative selectors based on retailer
            if not product_elements:
                alternative_selectors = {
                    "amazon": [
                        "div[data-component-type='s-search-result']",
                        ".s-result-item",
                        "[data-index]",
                        ".s-card-container",
                        "[data-asin]",
                        ".s-main-slot .s-result-item",
                        "[data-cel-widget*='search_result']",
                        ".s-result-list .s-result-item"
                    ],
                    "jbhifi": [
                        ".product-tile",
                        ".product-item",
                        ".product",
                        "[data-product-id]",
                        ".ProductTile",
                        "li.product",
                        "[class*='Product']",
                        "[class*='product']",
                        "article[data-product]",
                        "div[data-product-id]",
                        "a[href*='/products/']",
                        "a[href*='/product/']"
                    ],
                    "harveynorman": [
                        ".product-item",
                        ".product",
                        ".product-tile",
                        "[data-product-id]",
                        "li.item"
                    ]
                }
                
                for alt_selector in alternative_selectors.get(retailer, []):
                    try:
                        product_elements = self.driver.find_elements(By.CSS_SELECTOR, alt_selector)
                        if product_elements:
                            logging.info(f"Found {len(product_elements)} products using alternative selector: {alt_selector}")
                            break
                    except:
                        continue
            
            # If still no products, use JavaScript to dynamically find product-like elements
            if not product_elements:
                logging.info(f"Trying JavaScript-based dynamic product detection for {retailer}...")
                try:
                    # First, diagnose what's on the page
                    page_info = self.driver.execute_script("""
                        return {
                            totalLinks: document.querySelectorAll('a').length,
                            productLinks: document.querySelectorAll('a[href*="/product"], a[href*="/dp/"], a[href*="/p-"], a[href*="/p/"], a[href*="item"]').length,
                            hasResults: document.body.innerText.includes('results') || document.body.innerText.includes('found'),
                            pageText: document.body.innerText.substring(0, 500)
                        };
                    """)
                    logging.info(f"Page diagnostic - Total links: {page_info.get('totalLinks', 0)}, Product-like links: {page_info.get('productLinks', 0)}")
                    
                    # Use JavaScript to find potential product elements with comprehensive search
                    js_products = self.driver.execute_script("""
                        var products = [];
                        var seenUrls = new Set();
                        var skipWords = ['view all', 'see more', 'load more', 'next', 'previous', 'cart', 'checkout', 'login', 'register', 'menu', 'home', 'account'];
                        
                        // Strategy 1: Find all links that look like product links
                        var productLinkSelectors = [
                            'a[href*="/product"]',
                            'a[href*="/dp/"]',
                            'a[href*="/gp/product"]',
                            'a[href*="/p-"]',
                            'a[href*="/p/"]',
                            'a[href*="item"]',
                            'a[href*="sku"]',
                            'a[data-asin]'
                        ];
                        
                        for (var sel of productLinkSelectors) {
                            var links = document.querySelectorAll(sel);
                            for (var i = 0; i < links.length && products.length < 30; i++) {
                                var link = links[i];
                                var text = (link.textContent || link.innerText || '').trim();
                                var href = link.href;
                                if (text.length > 10 && href && !seenUrls.has(href)) {
                                    var shouldSkip = skipWords.some(word => text.toLowerCase().includes(word));
                                    if (!shouldSkip) {
                                        seenUrls.add(href);
                                        products.push({
                                            title: text.substring(0, 200),
                                            url: href
                                        });
                                    }
                                }
                            }
                            if (products.length > 0) break;
                        }
                        
                        // Strategy 2: For Amazon specifically, look for data-asin attributes
                        if (products.length === 0 && window.location.hostname.includes('amazon')) {
                            var asinElements = document.querySelectorAll('[data-asin]:not([data-asin=""])');
                            for (var i = 0; i < Math.min(asinElements.length, 30); i++) {
                                var el = asinElements[i];
                                var link = el.querySelector('h2 a, .s-link-style a, a[href*="/dp/"]');
                                if (link) {
                                    var text = (link.textContent || link.innerText || '').trim();
                                    var href = link.href;
                                    if (text.length > 10 && href && !seenUrls.has(href)) {
                                        seenUrls.add(href);
                                        products.push({
                                            title: text.substring(0, 200),
                                            url: href
                                        });
                                    }
                                }
                            }
                        }
                        
                        // Strategy 3: Find elements with product-like classes/ids and extract links
                        if (products.length === 0) {
                            var containers = document.querySelectorAll('[class*="product" i], [class*="item" i], [id*="product" i], [id*="item" i], [data-product], [data-item], [data-sku]');
                            for (var i = 0; i < Math.min(containers.length, 50); i++) {
                                var container = containers[i];
                                var link = container.querySelector('a');
                                if (link) {
                                    var text = (link.textContent || link.innerText || container.textContent || '').trim();
                                    var href = link.href;
                                    if (text.length > 15 && href && !seenUrls.has(href)) {
                                        var shouldSkip = skipWords.some(word => text.toLowerCase().includes(word));
                                        if (!shouldSkip && href.length > 10) {
                                            seenUrls.add(href);
                                            products.push({
                                                title: text.substring(0, 200),
                                                url: href
                                            });
                                        }
                                    }
                                }
                            }
                        }
                        
                        // Strategy 4: Look for structured data (JSON-LD or microdata)
                        if (products.length === 0) {
                            var jsonLd = document.querySelectorAll('script[type="application/ld+json"]');
                            for (var i = 0; i < jsonLd.length; i++) {
                                try {
                                    var data = JSON.parse(jsonLd[i].textContent);
                                    if (data['@type'] === 'Product' || (Array.isArray(data) && data.some(item => item['@type'] === 'Product'))) {
                                        var prod = Array.isArray(data) ? data.find(item => item['@type'] === 'Product') : data;
                                        if (prod.name && prod.url) {
                                            products.push({
                                                title: prod.name,
                                                url: prod.url
                                            });
                                        }
                                    }
                                } catch(e) {}
                            }
                        }
                        
                        return products;
                    """)
                    
                    if js_products:
                        logging.info(f"JavaScript found {len(js_products)} potential products on {retailer}")
                        # Convert JavaScript results to SearchResult objects
                        for js_product in js_products:
                            try:
                                title = js_product.get('title', '').strip()
                                url = js_product.get('url', '')
                                if title and url and len(title) > 10:
                                    results.append(SearchResult(
                                        url=clean_url(url),
                                        title=title,
                                        retailer=retailer,
                                        variant="",
                                        score=0.0,
                                        is_sponsored=False
                                    ))
                            except:
                                continue
                        
                        if results:
                            logging.info(f"Successfully extracted {len(results)} products using JavaScript detection")
                            return results
                except Exception as e:
                    logging.debug(f"JavaScript detection failed: {e}")
                
                # Last resort: try to find ANY clickable elements with substantial text
                logging.info(f"Trying last-resort link detection for {retailer}...")
                try:
                    all_links = self.driver.find_elements(By.TAG_NAME, "a")
                    logging.debug(f"Found {len(all_links)} total links on page")
                    seen_urls = set()
                    for link in all_links[:50]:  # Check first 50 links
                        try:
                            text = link.text.strip()
                            href = link.get_attribute('href') or ''
                            href_clean = clean_url(href)
                            
                            # Look for product-like links
                            if (text and len(text) > 15 and href and href_clean not in seen_urls and
                                any(indicator in href.lower() for indicator in ['/product', '/dp/', '/p-', '/p/', 'item', 'sku', '/gp/product']) and
                                not any(skip in text.lower() for skip in ['view all', 'see more', 'load more', 'next page', 'previous', 'cart', 'checkout', 'login', 'register'])):
                                seen_urls.add(href_clean)
                                results.append(SearchResult(
                                    url=href_clean,
                                    title=text,
                                    retailer=retailer,
                                    variant="",
                                    score=0.0,
                                    is_sponsored=False
                                ))
                                if len(results) >= 15:
                                    break
                        except:
                            continue
                    if results:
                        logging.info(f"Found {len(results)} products using last-resort link detection")
                        return results
                except Exception as e:
                    logging.debug(f"Last-resort detection failed: {e}")
                
                if not results:
                    logging.warning(f"No product elements found on {retailer} page with any selector or method")
                    return results
            
            logging.info(f"Extracting products from {len(product_elements)} elements found on {retailer}")
            
            for element in product_elements:
                try:
                    # Check if it's sponsored (Amazon-specific check)
                    is_sponsored = False
                    if retailer == "amazon":
                        try:
                            # Check for sponsored indicators in Amazon structure
                            sponsored_elements = element.find_elements(By.XPATH, ".//span[contains(text(), 'Sponsored') or contains(text(), 'Ad')]")
                            if sponsored_elements:
                                is_sponsored = True
                            # Also check the parent structure
                            parent_text = element.text.lower()
                            if any(ind in parent_text for ind in ['sponsored', 'advertisement', 'ad']):
                                is_sponsored = True
                        except:
                            pass
                    else:
                        for indicator in config['sponsored_indicators']:
                            if indicator.lower() in element.text.lower():
                                is_sponsored = True
                                break
                    
                    # Skip sponsored results
                    if is_sponsored:
                        logging.debug(f"Skipping sponsored result on {retailer}")
                        continue
                    
                    # Extract title and link with multiple strategies
                    title = None
                    url = None
                    
                    # Retailer-specific extraction
                    if retailer == "amazon":
                        # Amazon-specific selectors
                        try:
                            # Method 1: Standard Amazon structure
                            h2_link = element.find_element(By.CSS_SELECTOR, "h2 a")
                            url = h2_link.get_attribute('href')
                            try:
                                title = h2_link.find_element(By.CSS_SELECTOR, "span").text.strip()
                            except:
                                title = h2_link.text.strip()
                        except:
                            try:
                                # Method 2: Any link with data-asin (Amazon product indicator)
                                asin_link = element.find_element(By.CSS_SELECTOR, "a[href*='/dp/'], a[href*='/gp/product/']")
                                url = asin_link.get_attribute('href')
                                title = asin_link.text.strip() or element.text.strip()
                            except:
                                pass
                    elif retailer == "jbhifi":
                        # JB Hi-Fi specific extraction - multiple strategies
                        try:
                            # Method 1: Try standard product tile structure
                            title_element = element.find_element(By.CSS_SELECTOR, ".product-title, .product-name, h2, h3, h4, a.product-title, a.product-name, [class*='title'], [class*='name']")
                            link_element = element.find_element(By.CSS_SELECTOR, "a")
                            title = title_element.text.strip()
                            url = link_element.get_attribute('href')
                            if not url or url == "#":
                                # Try to find absolute URL
                                url = link_element.get_attribute('href') or link_element.get_attribute('data-href')
                        except:
                            try:
                                # Method 2: Find link within product tile (any link with product in URL)
                                link = element.find_element(By.CSS_SELECTOR, "a[href*='/products/'], a[href*='/product/'], a[href*='jbhifi.com.au/products'], a[href*='jbhifi.com.au/product']")
                                url = link.get_attribute('href')
                                title = link.text.strip() or link.get_attribute('title') or element.text.strip()
                            except:
                                # Method 3: Extract from data attributes or any link
                                try:
                                    links = element.find_elements(By.TAG_NAME, "a")
                                    for link in links:
                                        href = link.get_attribute('href') or ''
                                        if '/products/' in href or '/product/' in href or ('jbhifi.com.au' in href and len(href.split('/')) > 4):
                                            url = href
                                            # Try to get title from link text, title attribute, or parent element
                                            title = (link.text.strip() or 
                                                   link.get_attribute('title') or 
                                                   link.get_attribute('aria-label') or
                                                   element.find_element(By.CSS_SELECTOR, "h2, h3, h4, [class*='title'], [class*='name']").text.strip() if element.find_elements(By.CSS_SELECTOR, "h2, h3, h4, [class*='title'], [class*='name']") else element.text.strip())
                                            break
                                except:
                                    # Method 4: Try JavaScript extraction if Selenium fails
                                    try:
                                        js_result = self.driver.execute_script("""
                                            var element = arguments[0];
                                            var link = element.querySelector('a[href*="/products/"], a[href*="/product/"]');
                                            if (link) {
                                                return {
                                                    url: link.href,
                                                    title: link.textContent.trim() || link.title || link.getAttribute('aria-label') || element.textContent.trim()
                                                };
                                            }
                                            return null;
                                        """, element)
                                        if js_result:
                                            url = js_result.get('url')
                                            title = js_result.get('title', '').strip()
                                    except:
                                        pass
                    
                    elif retailer == "harveynorman":
                        # Harvey Norman specific extraction
                        try:
                            # Method 1: Try standard product item structure
                            title_element = element.find_element(By.CSS_SELECTOR, ".product-name, .product-title, h2, h3, a.product-name")
                            link_element = element.find_element(By.CSS_SELECTOR, "a")
                            title = title_element.text.strip()
                            url = link_element.get_attribute('href')
                        except:
                            try:
                                # Method 2: Find product link
                                link = element.find_element(By.CSS_SELECTOR, "a[href*='/catalog/product'], a[href*='/product']")
                                url = link.get_attribute('href')
                                title = link.text.strip() or element.text.strip()
                            except:
                                # Method 3: Extract from any link in container
                                try:
                                    links = element.find_elements(By.TAG_NAME, "a")
                                    for link in links:
                                        href = link.get_attribute('href') or ''
                                        if '/product' in href:
                                            url = href
                                            title = link.text.strip() or element.find_element(By.TAG_NAME, "h2, h3, h4").text.strip()
                                            break
                                except:
                                    pass
                    else:
                        # Generic extraction for other retailers
                        try:
                            title_element = element.find_element(By.CSS_SELECTOR, config['title_selector'])
                            link_element = element.find_element(By.CSS_SELECTOR, config['link_selector'])
                            title = title_element.text.strip()
                            url = link_element.get_attribute('href')
                        except:
                            pass
                    
                    # Fallback: Try to find any link with text
                    if not title or not url:
                        try:
                            links = element.find_elements(By.TAG_NAME, "a")
                            for link in links:
                                link_text = link.text.strip()
                                link_href = link.get_attribute('href') or ''
                                # Prefer product-like URLs
                                if link_text and len(link_text) > 10 and link_href:
                                    if not url or any(indicator in link_href.lower() for indicator in ['/product', '/dp/', '/p-', '/p/', 'item']):
                                        title = link_text
                                        url = link_href
                                        break
                        except:
                            pass
                    
                    if title and url:
                        results.append(SearchResult(
                            url=clean_url(url),
                            title=title,
                            retailer=retailer,
                            variant="",  # Will be set later
                            score=0.0,
                            is_sponsored=is_sponsored
                        ))
                        logging.debug(f"Extracted product: {title[:50]}...")
                        
                except NoSuchElementException:
                    continue
                except Exception as e:
                    logging.debug(f"Error extracting product element: {e}")
                    continue
            
            logging.info(f"Successfully extracted {len(results)} products from {retailer}")
                    
        except Exception as e:
            logging.error(f"Error extracting search results from {retailer}: {e}")
        
        return results
    
    def close(self) -> None:
        """Close the WebDriver"""
        if self.driver:
            try:
                self.driver.quit()
            except Exception as e:
                logging.error(f"Error closing WebDriver: {e}")

# ==================== MATCHING LOGIC ====================

def extract_weight(product_name: str) -> Optional[float]:
    """Extract weight/size in ounces (oz) from product name"""
    if not product_name:
        return None
    
    # Pattern to match weight: "9.7 oz", "10.59oz", "32.28 oz", "20.13 oz", etc.
    # Also handle patterns like "9.7-oz", "10.59-oz"
    weight_patterns = [
        r'(\d+\.?\d*)\s*-?\s*oz',  # "9.7 oz", "10.59oz", "9.7-oz"
        r'(\d+\.?\d*)\s*ounce',     # "9.7 ounce"
    ]
    
    for pattern in weight_patterns:
        match = re.search(pattern, product_name, re.IGNORECASE)
        if match:
            try:
                weight = float(match.group(1))
                return weight
            except ValueError:
                continue
    
    return None

def extract_product_details(product_name: str) -> Dict[str, Any]:
    """Extract brand, model, color, and lens details from product name"""
    details = {
        'brand': '',
        'model': '',
        'color': '',
        'lens': '',
        'size': '',  # Add size field (Large, Small, etc.)
        'weight': None,  # Weight in ounces (oz)
        'generation': '',  # Gen 1, Gen 2, etc.
        'transitions_color': '',  # Exact Transitions color (e.g., "Graphite Green", "Sapphire")
        'prizm_color': '',  # Exact Prizm color (e.g., "Black", "24K", "Sapphire")
        'frame_color': '',  # Frame color (e.g., "Shiny Black", "White", "Matte Black")
        'lens_color': '',  # Simple lens color (e.g., "Green", "Clear") when not Transitions/Prizm
        'lens_type': '',  # Lens type (e.g., "Polarised", "Gradient") when not Transitions/Prizm
        'low_bridge_fit': False,  # Low Bridge Fit variant
        'flavor': '',  # Flavor/variety for candy (e.g., "Patriotic Mix", "Peanut", "Original")
        'count': None,  # Count/quantity (e.g., 115, 90, 48)
        'full_text': normalize_text(product_name)
    }
    
    # Extract weight
    details['weight'] = extract_weight(product_name)
    
    # Extract count/quantity for candy products (e.g., "115 ct", "48 ct", "90 ct")
    import re
    count_patterns = [
        r'(\d+)\s*ct',  # "115 ct", "48 ct"
        r'(\d+)\s*count',  # "115 count"
        r'pack\s*of\s*(\d+)',  # "Pack of 10"
        r'(\d+)\s*pieces',  # "270 pieces"
    ]
    for pattern in count_patterns:
        match = re.search(pattern, product_name, re.IGNORECASE)
        if match:
            try:
                details['count'] = int(match.group(1))
                break
            except:
                pass
    
    # Extract flavor/variety for candy products (NOT packaging terms like "bulk")
    flavor_keywords = [
        'patriotic', 'red white blue', 'holiday', 'christmas', 'valentine', 'easter',
        'peanut', 'peanut butter', 'almond', 'original', 'fruity', 'variety', 'assorted',
        'mix', 'mixed', 'minis', 'fun size', 'full size', 'king size', 'share size',
        'singles size', 'party size', 'wint-o-green', 'peppermint', 'spearmint',
        'bubblemint', 'cobalt', 'rain'
        # NOTE: 'bulk' is NOT a flavor - it's packaging, so removed
    ]
    product_lower = product_name.lower()
    for keyword in flavor_keywords:
        if keyword in product_lower:
            # Extract the flavor phrase (could be multi-word)
            if keyword in ['red white blue', 'peanut butter', 'fun size', 'full size', 'king size', 'share size', 'singles size', 'party size', 'wint-o-green']:
                details['flavor'] = keyword
                break
            else:
                # Single word flavor
                details['flavor'] = keyword
                break
    
    # Extract brand (usually first word before |)
    if '|' in product_name:
        parts = product_name.split('|')
        if len(parts) > 0:
            details['brand'] = normalize_text(parts[0].strip())
    
    # Extract model name (after | and before - or before common words like "Glasses", "with", etc.)
    if '|' in product_name:
        after_brand = product_name.split('|')[1].strip()
        
        # Try splitting by '-' first (most common pattern)
        if '-' in after_brand:
            model_part = after_brand.split('-')[0].strip()
            details['model'] = normalize_text(model_part)
        else:
            # If no '-', try to find model before common words
            # Common patterns: "Meta Vanguard Glasses", "Gascan Sunglasses", etc.
            model_end_patterns = ['Glasses', 'Sunglasses', 'Eyewear', 'with', ',', '(', '-']
            model_part = after_brand
            for pattern in model_end_patterns:
                if pattern in after_brand:
                    idx = after_brand.find(pattern)
                    if idx > 0:
                        model_part = after_brand[:idx].strip()
                        break
            
            # Clean up - remove extra words at end
            model_words = model_part.split()
            # Keep meaningful words (usually 1-3 words like "Meta Vanguard", "Gascan", etc.)
            if len(model_words) <= 4:  # Allow up to 4 words for models like "Meta Vanguard Low Bridge Fit"
                details['model'] = normalize_text(model_part)
            else:
                # If too many words, try to extract just the core model name (first 2-3 words typically)
                details['model'] = normalize_text(' '.join(model_words[:3]))
    
    # Extract color (usually after the MAIN - separator, which comes after model name)
    color_words = []
    
    # Find the main separator: look for pattern "Model - Color, Lens"
    # This should be after the brand/model part, not the brand name itself (e.g., "Ray-Ban" has a dash)
    if '|' in product_name:
        # If there's a pipe, work with the part after the brand
        after_brand = product_name.split('|')[1].strip() if len(product_name.split('|')) > 1 else product_name
        # Now find the MAIN dash (after model, before color)
        if '-' in after_brand:
            # Split by dash and take everything after the first dash as potential color
            parts = after_brand.split('-', 1)  # Split only on first dash
            if len(parts) > 1:
                color_text = parts[1].strip()
            else:
                color_text = ""
        else:
            # No dash after brand, check for comma separation
            if ',' in after_brand:
                parts = after_brand.split(',', 1)
                color_text = parts[0].strip() if len(parts) > 0 else ""
            else:
                color_text = ""
    elif '-' in product_name:
        # No pipe, so find the last significant dash (before color description)
        # For names like "Product Name - Color", the last dash before common color words
        color_parts = product_name.rsplit('-', 1)  # Split from right, take last part
        if len(color_parts) > 1:
            color_text = color_parts[1].strip()
        else:
            color_text = ""
    else:
        color_text = ""
    
    if color_text:
        # Handle comma-separated colors (e.g., "White, Prizm™ Black" or "Shiny Cosmic Blue, Transitions® Sapphire")
        # Universal extraction: works for all products
        if ',' in color_text:
            parts = color_text.split(',')
            # First part is usually the frame color (e.g., "White" or "Shiny Cosmic Blue")
            frame_color = parts[0].strip()
            # Extract all color words from frame color (e.g., "Shiny Cosmic Blue" -> ["shiny", "cosmic", "blue"] or "White" -> ["white"])
            frame_color_words = frame_color.split()
            for word in frame_color_words:
                word_clean = normalize_text(word.strip())
                if word_clean and len(word_clean) > 2:
                    color_words.append(word_clean)
            
            # For comma-separated, also check the second part for lens colors (Prizm/Transitions)
            # This ensures we get "Sapphire" from "White, Prizm™ Sapphire"
            if len(parts) > 1:
                lens_color_part = parts[1].strip()
                # Check if it contains Prizm or Transitions color info
                if 'Prizm' in lens_color_part or 'Transitions' in lens_color_part:
                    # Process this part as if it were in color_text (will be handled by code below)
                    pass
        else:
            # Extract frame color (before lens information)
            # Extract all words as potential colors (e.g., "Shiny Cosmic Blue" -> all words)
            if 'Prizm' in color_text:
                lens_start = color_text.find('Prizm')
                frame_color = color_text[:lens_start].strip()
            elif 'Transitions' in color_text:
                lens_start = color_text.find('Transitions')
                frame_color = color_text[:lens_start].strip()
            elif 'lenses' in color_text.lower():
                lens_start = color_text.lower().find('lenses')
                frame_color = color_text[:lens_start].strip()
            else:
                frame_color = color_text.strip()
            
            # Split frame color into words and add all meaningful ones
            if frame_color:
                frame_color_words = frame_color.split()
                for word in frame_color_words:
                    word_clean = normalize_text(word.strip())
                    if word_clean and len(word_clean) > 2:
                        color_words.append(word_clean)
        
        # Extract color from lens descriptions (Prizm, Transitions)
        # Universal extraction: works for both comma-separated and non-comma formats
        # Prizm colors (e.g., "Prizm™ Black", "Prizm™ 24K", "Prizm™ Sapphire")
        if 'Prizm' in color_text:
            prizm_part = color_text[color_text.find('Prizm'):]
            if '™' in prizm_part:
                after_tm = prizm_part.split('™')[1].strip()
                if after_tm:
                    # Extract color words after Prizm™ (e.g., "Sapphire" from "Prizm™ Sapphire")
                    # Handle both "Prizm™ Sapphire" and "Prizm™ Black, some text"
                    lens_color_parts = after_tm.split(',')[0].split()  # Take before any comma, then split words
                    # Take first 1-2 meaningful words
                    for part in lens_color_parts[:2]:
                        part_clean = normalize_text(part.strip())
                        if part_clean and len(part_clean) > 1:
                            color_words.append(part_clean)
        
        # Transitions colors (e.g., "Transitions® Sapphire", "Transitions® Graphite Green", "Transitions® Grey")
        if 'Transitions' in color_text:
            transitions_part = color_text[color_text.find('Transitions'):]
            if '®' in transitions_part:
                after_reg = transitions_part.split('®')[1].strip()
                # Extract color words from Transitions description
                # Could be "Sapphire", "Graphite Green", "Grey", "Amethyst", "Emerald", etc.
                transitions_colors = after_reg.split('lenses')[0].split('Lenses')[0].strip()
                # Split by spaces but keep multi-word colors together
                color_parts_in_lens = transitions_colors.split()
                for i, part in enumerate(color_parts_in_lens):
                    part_clean = normalize_text(part.strip())
                    if part_clean and len(part_clean) > 2:
                        color_words.append(part_clean)
    
    # Common color words list to help identify colors in the product name
    common_colors = ['white', 'black', 'grey', 'gray', 'green', 'blue', 'red', 'yellow', 'orange', 
                     'purple', 'violet', 'brown', 'pink', 'sapphire', 'emerald', 'amethyst', 'cosmic',
                     'matte', 'shiny', 'chalky', 'mystic', 'asteroid', 'graphite']
    
    # Also search for color words we might have missed, but ONLY in the color section (after the main separator)
    # Only search after the model part to avoid picking up colors from brand/model names
    color_section = ""
    if '|' in product_name:
        after_brand = product_name.split('|')[1].strip() if len(product_name.split('|')) > 1 else ""
        # Find the part after the model (after first dash or comma)
        if '-' in after_brand:
            color_section = after_brand.split('-', 1)[1] if len(after_brand.split('-', 1)) > 1 else ""
        elif ',' in after_brand:
            color_section = after_brand.split(',', 1)[1] if len(after_brand.split(',', 1)) > 1 else ""
        else:
            color_section = after_brand
    else:
        # Extract the last part after the last dash
        if '-' in product_name:
            color_section = product_name.rsplit('-', 1)[1] if len(product_name.rsplit('-', 1)) > 1 else ""
    
    color_section_lower = color_section.lower() if color_section else ""
    for color in common_colors:
        if color in color_section_lower and normalize_text(color) not in color_words:
            # Make sure it's not part of a model name (should already be filtered by color_section, but double-check)
            # Only add if it's in the color section (not in the model part)
            if color_section:
                color_words.append(normalize_text(color))
    
    # Remove duplicates and join
    unique_colors = []
    for color in color_words:
        if color and color not in unique_colors:
            unique_colors.append(color)
    
    details['color'] = ' '.join(unique_colors) if unique_colors else ''
    
    # Extract generation (Gen 1, Gen 2, etc.)
    gen_pattern = re.search(r'Gen\s*(\d+)', product_name, re.IGNORECASE)
    if gen_pattern:
        details['generation'] = f"Gen {gen_pattern.group(1)}"
    else:
        # Check for "(Gen 2)" pattern
        gen_pattern2 = re.search(r'\(Gen\s*(\d+)\)', product_name, re.IGNORECASE)
        if gen_pattern2:
            details['generation'] = f"Gen {gen_pattern2.group(1)}"
    
    # Extract size information (Large, Small, etc.)
    size_keywords = ['Large', 'Small', 'Medium', 'Standard', 'Oversized']
    product_upper = product_name  # Keep original case for size matching
    for size_keyword in size_keywords:
        if size_keyword in product_upper:
            details['size'] = size_keyword
            break
    
    # Extract Low Bridge Fit
    if 'low bridge fit' in product_name.lower() or 'low bridge' in product_name.lower():
        details['low_bridge_fit'] = True
    
    # Extract frame color (before lens/transitions)
    if '|' in product_name:
        after_brand = product_name.split('|')[1].strip() if len(product_name.split('|')) > 1 else product_name
        if '-' in after_brand:
            frame_part = after_brand.split('-')[1].strip() if len(after_brand.split('-', 1)) > 1 else ""
            # Frame color is before comma or before Transitions/Prizm
            if ',' in frame_part:
                frame_color = frame_part.split(',')[0].strip()
            elif 'Transitions' in frame_part:
                frame_color = frame_part[:frame_part.find('Transitions')].strip()
            elif 'Prizm' in frame_part:
                frame_color = frame_part[:frame_part.find('Prizm')].strip()
            else:
                frame_color = frame_part.split('lenses')[0].strip() if 'lenses' in frame_part else frame_part.strip()
            details['frame_color'] = normalize_text(frame_color)
    
    # Extract lens information and exact colors
    if 'Transitions' in product_name:
        # Extract exact Transitions color
        transitions_match = re.search(r'Transitions[®™]?\s+([A-Za-z\s]+?)(?:\s+lenses?|,|$)', product_name, re.IGNORECASE)
        if transitions_match:
            transitions_color = transitions_match.group(1).strip()
            details['transitions_color'] = normalize_text(transitions_color)
            details['lens'] = f"Transitions {transitions_color}"
        else:
            details['lens'] = "Transitions"
    elif 'Prizm' in product_name:
        # Extract exact Prizm color
        prizm_match = re.search(r'Prizm[™®]?\s+([A-Za-z0-9\s]+?)(?:\s*[,)]|$)', product_name, re.IGNORECASE)
        if prizm_match:
            prizm_color = prizm_match.group(1).strip()
            details['prizm_color'] = normalize_text(prizm_color)
            details['lens'] = f"Prizm {prizm_color}"
        else:
            details['lens'] = "Prizm"
    else:
        # Check for simple lens colors (e.g., "Green lenses", "Clear lenses" without Transitions/Prizm)
        # Pattern: "Green lenses", "Clear lenses" - must be after a comma
        simple_lens_match = re.search(r',\s*([A-Za-z]+)\s+lenses?', product_name, re.IGNORECASE)
        if simple_lens_match:
            simple_color = simple_lens_match.group(1).strip()
            # Only if it's a color word (not "Polarised", "Gradient", etc.)
            color_words_list = ['green', 'blue', 'red', 'black', 'clear', 'grey', 'gray', 'brown', 'yellow', 'orange', 'purple', 'pink']
            if simple_color.lower() in color_words_list:
                details['simple_lens_color'] = normalize_text(simple_color)
                details['lens'] = f"{simple_color} lenses"
        
        # Check for other lens types (Polarised, Gradient, etc.)
        lens_match = re.search(r'([A-Za-z\s]+?)\s+lenses?', product_name, re.IGNORECASE)
        if lens_match and not details.get('simple_lens_color'):
            lens_text = lens_match.group(1).strip()
            # Check if it's a lens type (Polarised, Gradient) or color (Green, Clear)
            lens_type_keywords = ['Polarised', 'Polarized', 'Gradient']
            if any(kw.lower() in lens_text.lower() for kw in lens_type_keywords):
                details['lens_type'] = normalize_text(lens_text)
                details['lens'] = normalize_text(lens_text)
            else:
                # It's a color name (Green, Clear, etc.)
                details['lens_color'] = normalize_text(lens_text)  # Store simple lens color
                details['lens'] = normalize_text(lens_text)
        else:
            # Check for other lens types
            lens_keywords = ['Polarised', 'Polarized', 'Gradient']
            for keyword in lens_keywords:
                if keyword in product_name:
                    keyword_idx = product_name.find(keyword)
                    lens_text = product_name[keyword_idx:].split(',')[0].split('lenses')[0].strip()
                    details['lens_type'] = normalize_text(lens_text)
                    details['lens'] = normalize_text(lens_text)
                    break
    
    return details

class ProductMatcher:
    """Handles fuzzy matching of products with color/variant awareness"""
    
    def __init__(self, config: Dict):
        self.config = config
        self.fuzzy_threshold = config.get('fuzzy_threshold', 60)
        self.driver = None  # Will be set if needed for description fetching
    
    def set_driver(self, driver):
        """Set WebDriver for fetching product descriptions"""
        self.driver = driver
    
    def _load_ml_models(self):
        """Lazy load ML models when needed"""
        if not self.ml_enabled or not self.ml_config:
            return
        
        try:
            # Load brand extractor
            if self.ml_config.get('brand_extractor', {}).get('enabled', False) and not self.brand_extractor:
                try:
                    from ml_models.brand_extractor import BrandExtractor
                    brand_cfg = self.ml_config['brand_extractor']
                    self.brand_extractor = BrandExtractor(
                        model_name=brand_cfg.get('model_name', 'google/flan-t5-base'),
                        device=brand_cfg.get('device')
                    )
                    logging.info("Brand extractor loaded")
                except Exception as e:
                    logging.warning(f"Could not load brand extractor: {e}")
            
            # Load NER extractor
            if self.ml_config.get('ner_extractor', {}).get('enabled', False) and not self.ner_extractor:
                try:
                    from ml_models.ner_extractor import NERExtractor
                    ner_cfg = self.ml_config['ner_extractor']
                    self.ner_extractor = NERExtractor(
                        model_name=ner_cfg.get('model_name', 'dslim/roberta-base-NER'),
                        device=ner_cfg.get('device')
                    )
                    logging.info("NER extractor loaded")
                except Exception as e:
                    logging.warning(f"Could not load NER extractor: {e}")
            
            # Load CLIP matcher
            if self.ml_config.get('clip_matcher', {}).get('enabled', False) and not self.clip_matcher:
                try:
                    from ml_models.clip_matcher import CLIPMatcher
                    clip_cfg = self.ml_config['clip_matcher']
                    self.clip_matcher = CLIPMatcher(
                        model_name=clip_cfg.get('model_name', 'ViT-B-32'),
                        pretrained=clip_cfg.get('pretrained', 'openai'),
                        device=clip_cfg.get('device')
                    )
                    logging.info("CLIP matcher loaded")
                except Exception as e:
                    logging.warning(f"Could not load CLIP matcher: {e}")
            
            # Load image embedder
            if self.ml_config.get('image_embedder', {}).get('enabled', False) and not self.image_embedder:
                try:
                    from ml_models.image_embedder import ImageEmbedder
                    img_cfg = self.ml_config['image_embedder']
                    self.image_embedder = ImageEmbedder(
                        model_name=img_cfg.get('model_name', 'microsoft/resnet-50'),
                        device=img_cfg.get('device')
                    )
                    logging.info("Image embedder loaded")
                except Exception as e:
                    logging.warning(f"Could not load image embedder: {e}")
            
            # Load OCR extractor
            if self.ml_config.get('ocr_extractor', {}).get('enabled', False) and not self.ocr_extractor:
                try:
                    from ml_models.ocr_extractor import OCRExtractor
                    ocr_cfg = self.ml_config['ocr_extractor']
                    self.ocr_extractor = OCRExtractor(
                        lang=ocr_cfg.get('lang', 'en'),
                        device=ocr_cfg.get('device')
                    )
                    logging.info("OCR extractor loaded")
                except Exception as e:
                    logging.warning(f"Could not load OCR extractor: {e}")
            
            # Load feature extractor
            if self.ml_config.get('feature_extractor', {}).get('enabled', False) and not self.feature_extractor:
                try:
                    from ml_models.feature_extractor import FeatureExtractor
                    feat_cfg = self.ml_config['feature_extractor']
                    self.feature_extractor = FeatureExtractor(
                        model_name=feat_cfg.get('model_name', 'meta-llama/Llama-2-7b-chat-hf'),
                        device=feat_cfg.get('device')
                    )
                    logging.info("Feature extractor loaded")
                except Exception as e:
                    logging.warning(f"Could not load feature extractor: {e}")
                    
        except Exception as e:
            logging.error(f"Error loading ML models: {e}")
    
    def _fetch_product_page_details(self, url: str, retailer: str) -> Dict[str, str]:
        """Fetch full product page details including title, description, and specifications"""
        if not self.driver:
            return {}
        
        details = {
            'full_title': '',
            'description': '',
            'specifications': '',
            'full_text': ''
        }
        
        try:
            if retailer in ["amazon", "amazon-fresh"]:
                self.driver.get(url)
                time.sleep(2.5)  # Wait for page load
                
                # Get full product title
                try:
                    title_selectors = [
                        "#productTitle",
                        "span#productTitle",
                        "h1.a-size-large",
                        ".a-size-large.product-title-word-break"
                    ]
                    for selector in title_selectors:
                        try:
                            title_elem = self.driver.find_element(By.CSS_SELECTOR, selector)
                            if title_elem:
                                details['full_title'] = title_elem.text.strip()
                                break
                        except:
                            continue
                except:
                    pass
                
                # Get product description and features
                description_parts = []
                try:
                    # Feature bullets
                    desc_selectors = [
                        "#feature-bullets ul li span.a-list-item",  # Bullet points
                        "#productDescription p",  # Product description paragraphs
                        ".a-unordered-list.a-vertical.a-spacing-mini li span",  # Feature list
                        "[data-feature-name='productDescription']",  # Description feature
                    ]
                    for selector in desc_selectors:
                        try:
                            desc_elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                            if desc_elements:
                                description_parts.extend([elem.text.strip() for elem in desc_elements[:10]])
                        except:
                            continue
                except:
                    pass
                
                # Get technical details/specifications
                try:
                    tech_table = self.driver.find_elements(By.CSS_SELECTOR, "#productDetails_techSpec_section_1 tr, .prodDetTable tr, #productDetails_technicalSpecifications_section_1 tr")
                    for row in tech_table[:30]:  # Get more rows for better coverage
                        try:
                            cells = row.find_elements(By.TAG_NAME, "td")
                            if len(cells) >= 2:
                                details['specifications'] += f"{cells[0].text.strip()}: {cells[1].text.strip()}\n"
                        except:
                            continue
                except:
                    pass
                
                # Also get variant information from Amazon (color options, etc.)
                try:
                    # Try to get color/style variations - improved selectors
                    variant_text_parts = []
                    
                    # Method 1: Color variations
                    color_selectors = [
                        "#variation_color_name ul li span.a-button-text",
                        "#variation_color_name ul li span",
                        "[data-csa-c-content-id='variation_color_name'] span",
                        "#variation_color_name .a-button-text",
                        ".a-button-text[data-csa-c-content-id='variation_color_name']"
                    ]
                    for selector in color_selectors:
                        try:
                            color_elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                            if color_elements:
                                variant_text_parts.append("Colors: " + " ".join([elem.text.strip() for elem in color_elements[:15]]))
                                break
                        except:
                            continue
                    
                    # Method 2: Style variations
                    style_selectors = [
                        "#variation_style_name ul li span.a-button-text",
                        "#variation_style_name ul li span",
                        "[data-csa-c-content-id='variation_style_name'] span",
                        "#variation_style_name .a-button-text"
                    ]
                    for selector in style_selectors:
                        try:
                            style_elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                            if style_elements:
                                variant_text_parts.append("Styles: " + " ".join([elem.text.strip() for elem in style_elements[:15]]))
                                break
                        except:
                            continue
                    
                    # Method 3: Get selected/active variant (what's currently shown)
                    try:
                        active_color = self.driver.find_elements(By.CSS_SELECTOR, "#variation_color_name .a-button-selected span, #variation_color_name .a-button-selected")
                        if active_color:
                            variant_text_parts.append("Active Color: " + active_color[0].text.strip())
                    except:
                        pass
                    
                    if variant_text_parts:
                        details['specifications'] += " ".join(variant_text_parts) + "\n"
                except:
                    pass
                
                # Get additional product info from A+ content or product description
                try:
                    # Look for key product details in the main content area
                    key_info_selectors = [
                        "#feature-bullets",
                        "#productDescription",
                        ".a-section.a-spacing-medium",
                        "[data-feature-name]"
                    ]
                    for selector in key_info_selectors:
                        try:
                            info_elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                            if info_elements:
                                for elem in info_elements[:3]:  # First 3 sections
                                    text = elem.text.strip()
                                    if text and len(text) > 20:  # Meaningful content
                                        details['specifications'] += f"{text[:200]}\n"  # Limit length
                                break
                        except:
                            continue
                except:
                    pass
                
                # Combine all text
                all_text_parts = [details['full_title']]
                all_text_parts.extend(description_parts)
                if details['specifications']:
                    all_text_parts.append(details['specifications'])
                details['full_text'] = " ".join(all_text_parts).lower()
                details['description'] = " ".join(description_parts[:5]).lower()  # First 5 description items
                
            elif retailer == "jbhifi":
                self.driver.get(url)
                time.sleep(2.0)
                
                # Get full product title
                try:
                    title_selectors = [
                        "h1.product-title",
                        "h1",
                        ".product-title",
                        "h1[class*='title']"
                    ]
                    for selector in title_selectors:
                        try:
                            title_elem = self.driver.find_element(By.CSS_SELECTOR, selector)
                            if title_elem:
                                details['full_title'] = title_elem.text.strip()
                                break
                        except:
                            continue
                except:
                    pass
                
                # Get product description
                try:
                    desc_selectors = [
                        ".product-description",
                        ".product-details",
                        "[class*='description']",
                        "[class*='details']"
                    ]
                    for selector in desc_selectors:
                        try:
                            desc_elem = self.driver.find_element(By.CSS_SELECTOR, selector)
                            if desc_elem:
                                details['description'] = desc_elem.text.strip().lower()
                                break
                        except:
                            continue
                except:
                    pass
                
                details['full_text'] = f"{details['full_title']} {details['description']}".lower()
            
            return details
        except Exception as e:
            logging.debug(f"Error fetching product page details from {url}: {e}")
            return {}
    
    def _fetch_product_description(self, url: str, retailer: str) -> str:
        """Fetch product description from URL to check for shiny/matte/graphite (legacy method)"""
        details = self._fetch_product_page_details(url, retailer)
        return details.get('description', '')
    
    def calculate_match_score(self, original_details: Dict, variant: str, result_title: str) -> float:
        """Calculate match score considering product type AND color/variant"""
        variant_text = normalize_text(result_title)
        original_text = original_details['full_text']
        
        # Base score from fuzzy matching
        base_score = fuzz.token_sort_ratio(variant_text, original_text)
        
        # Bonus for matching brand
        brand_bonus = 0
        if original_details['brand'] and original_details['brand'] in variant_text:
            brand_bonus = 5
        
        # CRITICAL: Model matching - required for high scores
        model_bonus = 0
        model_required = False
        if original_details['model']:
            model_lower = original_details['model'].lower()
            variant_lower = variant_text.lower()
            
            # Check if the FULL model name appears (required for high confidence)
            if model_lower in variant_lower:
                model_bonus = 30  # Very high bonus for exact model match
                model_required = True
            else:
                # Check if key model words appear (partial match)
                model_words = original_details['model'].split()
                matched_model_words = 0
                for word in model_words:
                    if len(word) > 3 and word.lower() in variant_lower:
                        matched_model_words += 1
                
                # If most model words match, give partial bonus
                if matched_model_words >= len(model_words) * 0.7:  # 70% of words match
                    model_bonus = 15
                elif matched_model_words > 0:
                    model_bonus = 5  # Small bonus for some match
                else:
                    # No model match - this is a problem
                    model_required = False  # Will apply penalty below
        
        # Critical: Bonus for matching color (check all color words)
        color_bonus = 0
        if original_details['color']:
            color_words = original_details['color'].split()
            matched_colors = 0
            variant_lower = variant_text.lower()
            
            # First, try to match multi-word colors (e.g., "Graphite Green", "Cosmic Blue")
            if len(color_words) >= 2:
                # Check for two-word color combinations
                for i in range(len(color_words) - 1):
                    two_word_color = f"{color_words[i]} {color_words[i+1]}"
                    if two_word_color.lower() in variant_lower:
                        matched_colors += 2
                        color_bonus += 25  # Higher bonus for exact multi-word match
                        # Mark these as matched
                        color_words[i] = ""
                        color_words[i+1] = ""
                        break
            
            # Then match individual color words
            for word in color_words:
                if word and len(word) > 2 and word.lower() in variant_lower:
                    matched_colors += 1
                    color_bonus += 12  # High weight per color word
            
            # Extra bonus if multiple colors match (e.g., "White" and "Black", or "Sapphire" and "Grey")
            if matched_colors > 1:
                color_bonus += 10
            
            # CRITICAL: Check for shiny/matte/graphite in product description if available
            # These are important variants that might not be in title but in description
            description_bonus = 0
            if hasattr(self, 'driver') and self.driver:
                # We'll check description later when we have URL access
                pass
            
            # Color matching is OPTIONAL - bonus if colors match, but only small penalty if they don't
            # Key colors are those longer than 3 chars or important words like "sapphire", "graphite"
            key_colors = [w for w in original_details['color'].split() if len(w) > 3 or w.lower() in ['blue', 'red', 'grey', 'gray', 'pink', 'sapphire', 'graphite', 'emerald']]
            matched_key_colors = sum(1 for key_color in key_colors if key_color.lower() in variant_lower)
            
            # Small penalty if no colors match (color is optional, not critical)
            if matched_colors == 0 and original_details['color']:
                color_bonus -= 5  # Small penalty - color matching is optional
        
        # Bonus for matching lens type
        lens_bonus = 0
        if original_details['lens']:
            lens_words = original_details['lens'].split()
            for word in lens_words:
                if len(word) > 3 and word.lower() in variant_text.lower():
                    lens_bonus += 10
                    break
        
        # CRITICAL: Heavy penalty if wrong model appears (e.g., "Gascan" when looking for "Vanguard")
        model_penalty = 0
        if original_details['model']:
            model_lower = original_details['model'].lower()
            variant_lower = variant_text.lower()
            
            # Common Oakley models to check (including all variants)
            common_oakley_models = ['Gascan', 'Holbrook', 'Frogskins', 'Radar', 'Jawbreaker', 'M Frame', 
                                   'HSTN', 'Vanguard', 'Meta Vanguard', 'Meta', 'Headliner', 'Fuel Cell',
                                   'Batwolf', 'Plank', 'Ten', 'Sliver', 'Crosshair', 'Wiretap', 'Oil Rig',
                                   'Flak', 'Flak 2.0', 'Flak XL', 'Flak Draft', 'Flak Draft XL']  # Added Flak variants
            
            # Also check for Ray-Ban models
            common_rayban_models = ['Aviator', 'Wayfarer', 'Wayfarer Large', 'Skyler', 'Clubmaster', 'RB3025', 'RB2140', 'RB3016',
                                  'Erika', 'Justin', 'New Wayfarer', 'Original Wayfarer', 'Headliner', 'Headliner Low Bridge']
            
            all_models = common_oakley_models + common_rayban_models
            
            for wrong_model in all_models:
                wrong_model_lower = wrong_model.lower()
                # If this wrong model appears but our expected model doesn't, apply heavy penalty
                if wrong_model_lower in variant_lower and wrong_model_lower not in model_lower:
                    # Double check: is our expected model also present? If not, this is definitely wrong
                    expected_in_result = any(
                        word.lower() in variant_lower 
                        for word in original_details['model'].split() 
                        if len(word) > 3
                    )
                    if not expected_in_result:
                        model_penalty = 50  # VERY heavy penalty - likely completely wrong product
                        break
                    elif wrong_model_lower != model_lower:  # Different model mentioned
                        model_penalty = 30  # Still heavy penalty
                        break
        
        # CRITICAL: Size matching - if size is specified, it must match
        size_penalty = 0
        if original_details.get('size'):
            expected_size = original_details['size'].lower()
            variant_upper = variant_text.upper()  # Check uppercase for "Large", "Small", etc.
            # Check if size appears in variant
            size_match = expected_size.capitalize() in variant_upper or expected_size.upper() in variant_upper
            if not size_match:
                # Heavy penalty if size doesn't match - this is wrong product
                size_penalty = 30
                logging.debug(f"Size mismatch: expected '{original_details['size']}' but not found in result")
        
        # CRITICAL: Flavor/variety matching for candy - EXACT match required
        flavor_penalty = 0
        if original_details.get('flavor'):
            expected_flavor = original_details['flavor'].lower()
            variant_lower = variant_text.lower()
            
            # EXACT match required - the exact flavor phrase must appear
            if expected_flavor not in variant_lower:
                # VERY heavy penalty if flavor doesn't match exactly - this is wrong product
                flavor_penalty = 50
                logging.debug(f"Flavor EXACT mismatch: expected '{original_details['flavor']}' but not found in result")
        
        # CRITICAL: Count matching for candy - if count is specified, it must match (within 10% tolerance)
        count_penalty = 0
        if original_details.get('count') is not None:
            expected_count = original_details['count']
            variant_lower = variant_text.lower()
            
            # Extract count from result
            import re
            result_count = None
            count_patterns = [
                r'(\d+)\s*ct',
                r'(\d+)\s*count',
                r'pack\s*of\s*(\d+)',
                r'(\d+)\s*pieces',
            ]
            for pattern in count_patterns:
                match = re.search(pattern, variant_text, re.IGNORECASE)
                if match:
                    try:
                        result_count = int(match.group(1))
                        break
                    except:
                        pass
            
            if result_count is not None:
                # Allow 10% tolerance for count differences
                count_diff = abs(expected_count - result_count)
                count_tolerance = max(1, int(expected_count * 0.1))  # At least 1, or 10% of expected
                
                if count_diff > count_tolerance:
                    # VERY heavy penalty if count doesn't match - this is wrong product
                    count_penalty = 50
                    logging.debug(f"Count mismatch: expected {expected_count} but found {result_count} (diff: {count_diff}, tolerance: {count_tolerance})")
            else:
                # If count is specified but not found in result, apply penalty
                # But only if the count is a significant part of the product (e.g., "115 ct" is important)
                if expected_count > 10:  # Only penalize for significant counts
                    count_penalty = 30
                    logging.debug(f"Count not found in result: expected {expected_count}")
        
        # Calculate final score with ML enhancements
        # Get scoring weights from config
        if self.ml_enabled and self.ml_config:
            weights = self.ml_config.get('scoring_weights', {})
            text_weight = weights.get('text_fuzzy', 0.4)
            attr_weight = weights.get('attribute_match', 0.2)
            visual_weight = weights.get('visual_similarity', 0.2)
            ocr_weight = weights.get('ocr_text_match', 0.1)
            brand_weight = weights.get('brand_match', 0.1)
            
            # Normalize base scores to 0-100
            text_score = base_score
            attr_score = (ml_attribute_score / 10) * 100  # Normalize to 0-100
            visual_score_norm = (visual_score / 20) * 100  # Normalize to 0-100
            ocr_score_norm = (ocr_score / 10) * 100  # Normalize to 0-100
            brand_score_norm = (ml_brand_score / 10) * 100  # Normalize to 0-100
            
            # Weighted combination
            ml_enhanced_score = (
                text_weight * text_score +
                attr_weight * attr_score +
                visual_weight * visual_score_norm +
                ocr_weight * ocr_score_norm +
                brand_weight * brand_score_norm
            )
            
            # Combine with traditional scoring
            traditional_score = base_score + brand_bonus + model_bonus + color_bonus + lens_bonus - model_penalty - size_penalty - flavor_penalty - count_penalty
            
            # Use ML-enhanced score if it's significantly better, otherwise use traditional
            if ml_enhanced_score > traditional_score + 5:
                final_score = min(100, ml_enhanced_score)
                logging.debug(f"Using ML-enhanced score: {final_score:.1f} (vs traditional: {traditional_score:.1f})")
            else:
                final_score = min(100, traditional_score)
        else:
            # Traditional scoring only
            final_score = min(100, base_score + brand_bonus + model_bonus + color_bonus + lens_bonus - model_penalty - size_penalty - flavor_penalty - count_penalty)
        
        return final_score
    
    def find_best_match(self, variants: List[str], search_results: List[SearchResult], original_product_name: str = "") -> Optional[SearchResult]:
        """Find the best matching product from search results, considering color/variant"""
        if not variants or not search_results:
            return None
        
        # Extract details from original product name if provided
        original_details = {}
        if original_product_name:
            original_details = extract_product_details(original_product_name)
            logging.debug(f"Extracted details - Brand: {original_details.get('brand')}, Model: {original_details.get('model')}, Color: {original_details.get('color')}, Lens: {original_details.get('lens')}, Generation: {original_details.get('generation')}, Transitions: {original_details.get('transitions_color')}, Frame: {original_details.get('frame_color')}")
        
        best_match = None
        best_score = 0
        best_variant = ""
        
        for result in search_results:
            # CRITICAL: Early rejection of accessories - check BEFORE any processing
            result_title_lower = result.title.lower()
            accessory_keywords = ['hibloks', 'clip-on', 'clip on', 'attachment', 'add-on', 'addon']
            is_accessory = False
            
            # Quick check on title first (fastest)
            for keyword in accessory_keywords:
                if keyword in result_title_lower:
                    # HIBLOKS is always an accessory
                    if keyword == 'hibloks':
                        logging.warning(f"❌ REJECTED (early): Accessory 'HIBLOKS' detected in title: {result.title[:60]}...")
                        is_accessory = True
                        break
                    # Clip-on with polarized is likely an accessory
                    elif keyword in ['clip-on', 'clip on'] and 'polarized' in result_title_lower:
                        logging.warning(f"❌ REJECTED (early): Accessory '{keyword}' detected in title: {result.title[:60]}...")
                        is_accessory = True
                        break
            
            if is_accessory:
                continue  # Skip this result entirely
            
            for variant in variants:
                # CRITICAL: For Amazon and Amazon Fresh with incomplete titles, fetch full product page EARLY to verify
                # Amazon search results often don't show full product details
                page_details = {}
                result_retailer = result.retailer if hasattr(result, 'retailer') else ""
                if result_retailer in ["amazon", "amazon-fresh"]:
                    # Always fetch for Amazon/Amazon Fresh to get complete product details
                    page_details = self._fetch_product_page_details(result.url, result_retailer)
                    if page_details.get('full_title'):
                        result_text = normalize_text(page_details['full_title'])
                        result_lower = result_text.lower()
                        # Use full title for all checks
                        logging.debug(f"Fetched full Amazon/Amazon Fresh title: {page_details['full_title'][:80]}...")
                    else:
                        result_text = normalize_text(result.title)
                        result_lower = result_text.lower()
                else:
                    result_text = normalize_text(result.title)
                    result_lower = result_text.lower()
                
                # Combine title and page details for comprehensive checking
                full_result_text = result_lower
                if page_details.get('full_text'):
                    full_result_text = page_details['full_text']
                elif page_details.get('description'):
                    full_result_text = f"{result_lower} {page_details['description']}"
                
                # Also check lens type in page details if available
                if page_details.get('specifications'):
                    full_result_text += " " + page_details['specifications'].lower()
                
                # CRITICAL: Check for accessories in full text (after fetching page details)
                full_text_lower = full_result_text.lower()
                for keyword in accessory_keywords:
                    if keyword in full_text_lower:
                        # Check if it's clearly an accessory pattern
                        accessory_patterns = [
                            rf'\b{re.escape(keyword)}\s+(?:for|compatible)',
                            rf'{re.escape(keyword)}\s+(?:clip|attachment)',
                            rf'polarized\s+{re.escape(keyword)}',  # "Polarized Clip"
                            rf'{re.escape(keyword)}\s+polarized',  # "HIBLOKS Polarized"
                        ]
                        for pattern in accessory_patterns:
                            if re.search(pattern, full_result_text, re.IGNORECASE):
                                logging.warning(f"❌ REJECTED: Accessory '{keyword}' detected in full text: {result.title[:60]}...")
                                is_accessory = True
                                break
                        if is_accessory:
                            break
                    if is_accessory:
                        break
                
                if is_accessory:
                    continue  # Skip this result
                
                # CRITICAL: Early rejection for Clear lenses - check URL and title BEFORE name matching
                # If looking for "Clear lenses", reject immediately if URL or title has Polarised/Gradient
                if original_details.get('simple_lens_color') and original_details['simple_lens_color'].lower() == 'clear':
                    # Check URL for lens type indicators (URLs often have lens info like "polarised-gradient-graphite")
                    result_url_lower = result.url.lower() if hasattr(result, 'url') and result.url else ""
                    if 'polarised' in result_url_lower or 'polarized' in result_url_lower or 'gradient' in result_url_lower:
                        logging.warning(f"❌ REJECTED (early): Looking for 'Clear lenses' but found Polarised/Gradient in URL: {result.url[:80] if result.url else 'N/A'}...")
                        continue
                    
                    # Check title for Polarised/Gradient
                    result_title_lower = result.title.lower()
                    if 'polarised' in result_title_lower or 'polarized' in result_title_lower or 'gradient' in result_title_lower:
                        logging.warning(f"❌ REJECTED (early): Looking for 'Clear lenses' but found Polarised/Gradient in title: {result.title[:60]}...")
                        continue
                
                # CRITICAL: Check if result name matches Excel product name
                # Use full_result_text (includes Amazon page details) for comprehensive check
                if original_product_name:
                    # Use full_result_text which includes page details (better for Amazon)
                    result_name_for_check = full_result_text.lower() if full_result_text else normalize_text(result.title).lower()
                    
                    # Extract key words from Excel name (brand, model, key features)
                    key_words = []
                    if original_details.get('brand'):
                        brand_words = original_details['brand'].lower().split()
                        key_words.extend([w for w in brand_words if len(w) > 2])
                    
                    if original_details.get('model'):
                        model_words = original_details['model'].lower().split()
                        # Exclude size words from required matching (size is optional variant)
                        size_words = ['large', 'small', 'medium', 'standard', 'oversized']
                        # Extract core model words (excluding size)
                        core_model_words = [w for w in model_words if len(w) > 3 and w not in size_words]
                        key_words.extend(core_model_words)
                    
                    # Add generation if present
                    if original_details.get('generation'):
                        gen_match = re.search(r'gen\s*(\d+)', original_details['generation'].lower())
                        if gen_match:
                            key_words.append(f"gen{gen_match.group(1)}")
                    
                    # Check if key words appear in result name (using full text for better accuracy)
                    if key_words:
                        matched_key_words = sum(1 for word in key_words if word in result_name_for_check)
                        
                        # Require at least 70% of key words to match (or at least 2 words if we have many)
                        min_required = max(1, int(len(key_words) * 0.7)) if len(key_words) > 2 else len(key_words)
                        
                        if matched_key_words < min_required:
                            logging.warning(f"❌ REJECTED: Result name doesn't match Excel product name. Excel: '{original_product_name[:60]}...' | Result: '{result.title[:60]}...' | Matched {matched_key_words}/{len(key_words)} key words")
                            continue  # Skip this result - name doesn't match
                        else:
                            logging.debug(f"✓ Name match check passed: {matched_key_words}/{len(key_words)} key words matched")
                
                # Calculate enhanced match score
                if original_details:
                    score = self.calculate_match_score(original_details, variant, result.title)
                else:
                    score = fuzz.token_sort_ratio(normalize_text(variant), normalize_text(result.title))
                
                # Log scores for debugging
                if score >= 50:
                    logging.debug(f"Match score: {score:.1f}% | Variant: {variant[:50]}... | Result: {result.title[:50]}...")
                
                # CRITICAL: Check for conflicting keywords - if result has keywords NOT in original, reject immediately
                if original_product_name:
                    original_lower = normalize_text(original_product_name).lower()
                    result_lower = full_result_text.lower()
                    
                    # Extract all significant identifying keywords from original
                    original_keywords = set()
                    
                    # Model names (critical - must match)
                    if original_details.get('model'):
                        model_words = original_details['model'].lower().split()
                        for word in model_words:
                            if len(word) > 3:  # Only meaningful words
                                original_keywords.add(word)
                    
                    # Lens types (critical - must match)
                    if original_details.get('lens_type'):
                        lens_type_words = original_details['lens_type'].lower().split()
                        for word in lens_type_words:
                            if len(word) > 3:
                                original_keywords.add(word)
                    if original_details.get('transitions_color'):
                        original_keywords.add('transitions')
                        trans_words = original_details['transitions_color'].lower().split()
                        for word in trans_words:
                            if len(word) > 2:
                                original_keywords.add(word)
                    if original_details.get('prizm_color'):
                        original_keywords.add('prizm')
                        prizm_words = original_details['prizm_color'].lower().split()
                        for word in prizm_words:
                            if len(word) > 2:
                                original_keywords.add(word)
                    if original_details.get('simple_lens_color'):
                        # For simple lens colors, add the color and mark that we're looking for simple (not Polarised/Transitions)
                        simple_color = original_details['simple_lens_color'].lower()
                        original_keywords.add(simple_color)
                        # Mark that we're NOT looking for Polarised/Transitions/Prizm
                        original_keywords.add('_simple_lens')  # Special marker
                    
                    # Generation
                    if original_details.get('generation'):
                        gen_match = re.search(r'gen\s*(\d+)', original_details['generation'].lower())
                        if gen_match:
                            original_keywords.add(f"gen{gen_match.group(1)}")
                    
                    # Size
                    if original_details.get('size'):
                        original_keywords.add(original_details['size'].lower())
                    
                    # Known conflicting keywords that indicate different products
                    conflicting_keywords = {
                        # Model conflicts
                        'vanguard': ['flak', 'gascan', 'holbrook', 'radar', 'jawbreaker'],
                        'flak': ['vanguard', 'gascan', 'holbrook'],
                        'wayfarer': ['skyler', 'aviator', 'clubmaster'],
                        'skyler': ['wayfarer', 'aviator'],
                        # Lens type conflicts
                        'clear': ['polarised', 'polarized', 'transitions', 'prizm', 'gradient'],
                        'polarised': ['clear'],  # If looking for Polarised, Clear is wrong
                        'transitions': ['clear', 'prizm'],  # If looking for Transitions, Clear/Prizm is wrong
                        'prizm': ['clear', 'transitions'],  # If looking for Prizm, Clear/Transitions is wrong
                        # Color conflicts (only if they're in lens descriptions, not frame)
                        'graphite': ['sapphire', 'emerald', 'amethyst'],  # For Transitions colors
                        'sapphire': ['graphite', 'emerald', 'amethyst'],
                    }
                    
                    # Check for conflicting keywords in result
                    for original_keyword in original_keywords:
                        if original_keyword.startswith('_'):  # Skip special markers
                            continue
                        
                        # Check if this keyword has known conflicts
                        if original_keyword in conflicting_keywords:
                            for conflicting_word in conflicting_keywords[original_keyword]:
                                # If conflicting word appears in result but original keyword doesn't appear in result
                                if conflicting_word in result_lower and original_keyword not in result_lower:
                                    score = 0
                                    logging.warning(f"❌ REJECTED: Conflicting keyword detected. Looking for '{original_keyword}' but found conflicting '{conflicting_word}' in result (not in original): {result.title[:60]}...")
                                    break
                            if score == 0:
                                break
                    
                    # Special check: If looking for simple lens color (e.g., "Clear"), reject if Polarised/Transitions/Prizm found
                    if '_simple_lens' in original_keywords:
                        if 'polarised' in result_lower or 'polarized' in result_lower:
                            if 'clear' not in result_lower or ('clear' in result_lower and 'polarised' in result_lower):
                                score = 0
                                logging.warning(f"❌ REJECTED: Looking for simple lens color but found Polarised in result (conflicting keyword): {result.title[:60]}...")
                                break
                        if 'transitions' in result_lower or 'prizm' in result_lower:
                            score = 0
                            logging.warning(f"❌ REJECTED: Looking for simple lens color but found Transitions/Prizm in result (conflicting keyword): {result.title[:60]}...")
                            break
                    
                    # Check for wrong model names in result that aren't in original
                    all_known_models = ['vanguard', 'flak', 'wayfarer', 'skyler', 'headliner', 'aviator', 'clubmaster',
                                       'gascan', 'holbrook', 'frogskins', 'radar', 'jawbreaker']
                    if original_details.get('model'):
                        expected_model_lower = original_details['model'].lower()
                        # Extract core model from expected
                        core_expected = None
                        for known_model in all_known_models:
                            if known_model in expected_model_lower:
                                core_expected = known_model
                                break
                        
                        # Check if result has a different model
                        if core_expected:
                            for wrong_model in all_known_models:
                                if wrong_model != core_expected and wrong_model in result_lower:
                                    # Check if expected model is NOT in result
                                    if core_expected not in result_lower:
                                        score = 0
                                        logging.warning(f"❌ REJECTED: Conflicting model detected. Looking for '{core_expected}' but found '{wrong_model}' in result (not in original): {result.title[:60]}...")
                                        break
                            if score == 0:
                                break
                
                if score == 0:
                    continue
                
                # CRITICAL: Check generation first - if generation doesn't match, reject immediately
                if original_details.get('generation'):
                    expected_gen = original_details['generation'].lower()
                    
                    # Extract generation from result (check both title and page details)
                    gen_in_result = re.search(r'gen\s*(\d+)', full_result_text)
                    if gen_in_result:
                        result_gen = f"gen {gen_in_result.group(1)}"
                        if result_gen != expected_gen:
                            score = 0  # REJECT if generation doesn't match
                            logging.warning(f"❌ REJECTED: Generation mismatch. Looking for '{original_details['generation']}' but found '{gen_in_result.group(1)}' in result: {result.title[:60]}...")
                            continue  # Skip this result
                    else:
                        # If we're looking for Gen 2 but result doesn't specify, check if it says Gen 1 explicitly
                        if 'gen 2' in expected_gen or 'gen2' in expected_gen:
                            # If result doesn't have generation but has "gen 1" pattern, reject
                            if re.search(r'gen\s*1\b', full_result_text):
                                score = 0
                                logging.warning(f"❌ REJECTED: Generation mismatch. Looking for Gen 2 but found Gen 1 in result: {result.title[:60]}...")
                                continue
                
                # CRITICAL: Check size - if size doesn't match, reject immediately
                if original_details.get('size'):
                    expected_size = original_details['size'].lower()
                    # Check in full_result_text (includes page details)
                    full_result_upper = full_result_text.upper()
                    size_match = expected_size.capitalize() in full_result_upper or expected_size.upper() in full_result_upper
                    if not size_match:
                        score = 0  # REJECT if size doesn't match
                        logging.warning(f"❌ REJECTED: Size mismatch. Looking for '{original_details['size']}' but not found in result (checked title + page): {result.title[:60]}...")
                        continue  # Skip this result
                
                # CRITICAL: Strict Transitions color matching - if looking for "Transitions Graphite Green", reject if only "Green" appears
                if original_details.get('transitions_color'):
                    expected_transitions = original_details['transitions_color'].lower()
                    
                    # Check if "Transitions" appears in result (use full_result_text which includes page details)
                    if 'transitions' in full_result_text:
                        # Extract Transitions color from result (check full text)
                        # Try multiple patterns to catch variations
                        transitions_patterns = [
                            r'transitions[®™]?\s+([a-z\s]+?)(?:\s+lenses?|,|$|\))',
                            r'transitions[®™]?\s+([a-z\s]+?)(?:\s*[/\)]|$)',
                            r'transitions[®™]?\s+([a-z]+)',
                        ]
                        transitions_match = None
                        for pattern in transitions_patterns:
                            transitions_match = re.search(pattern, full_result_text, re.IGNORECASE)
                            if transitions_match:
                                break
                        
                        if transitions_match:
                            result_transitions_color = normalize_text(transitions_match.group(1).strip())
                            # Require exact match or at least both words match for multi-word colors
                            if expected_transitions != result_transitions_color:
                                # For multi-word colors like "Graphite Green", check if both words are present
                                expected_words = expected_transitions.split()
                                result_words = result_transitions_color.split()
                                if len(expected_words) > 1:
                                    # Multi-word color - require all words to match
                                    all_words_match = all(word in result_transitions_color for word in expected_words)
                                    if not all_words_match:
                                        score = 0  # REJECT - wrong Transitions color
                                        logging.warning(f"❌ REJECTED: Transitions color mismatch. Looking for 'Transitions {original_details['transitions_color']}' but found 'Transitions {transitions_match.group(1).strip()}' in result: {result.title[:60]}...")
                                        continue
                                else:
                                    # Single word color - must match exactly
                                    score = 0  # REJECT - wrong Transitions color
                                    logging.warning(f"❌ REJECTED: Transitions color mismatch. Looking for 'Transitions {original_details['transitions_color']}' but found 'Transitions {transitions_match.group(1).strip()}' in result: {result.title[:60]}...")
                                    continue
                        else:
                            # Transitions mentioned but no color extracted - might be generic, reject to be safe
                            score = 0
                            logging.warning(f"❌ REJECTED: Looking for 'Transitions {original_details['transitions_color']}' but could not extract color from result: {result.title[:60]}...")
                            continue
                    else:
                        # No Transitions in result but we're looking for it - REJECT immediately
                        # This is critical - if we're looking for Transitions color, result MUST have Transitions
                        score = 0  # REJECT - Transitions required but not found
                        logging.warning(f"❌ REJECTED: Looking for 'Transitions {original_details['transitions_color']}' but 'Transitions' not found in result (checked title + page): {result.title[:60]}...")
                        continue
                
                # CRITICAL: If looking for simple lens color (e.g., "Green lenses" without Transitions), reject Transitions/Prizm results
                if original_details.get('simple_lens_color'):
                    expected_simple_color = original_details['simple_lens_color'].lower()
                    
                    # If result has Transitions or Prizm, reject it (we're looking for simple color)
                    if 'transitions' in full_result_text or 'prizm' in full_result_text:
                        score = 0  # REJECT - looking for simple color but found Transitions/Prizm
                        logging.warning(f"❌ REJECTED: Looking for simple '{original_details['simple_lens_color']} lenses' but found Transitions/Prizm in result: {result.title[:60]}...")
                        continue
                    
                    # Check if the simple color appears in result (without Transitions/Prizm)
                    # The color should appear as a standalone word or in "Green Lens" format
                    color_pattern = rf'\b{re.escape(expected_simple_color)}\b'
                    if not re.search(color_pattern, full_result_text):
                        score = 0  # REJECT - simple color not found
                        logging.warning(f"❌ REJECTED: Looking for simple '{original_details['simple_lens_color']} lenses' but color not found in result (checked title + page): {result.title[:60]}...")
                        continue
                
                # CRITICAL: If looking for Transitions/Prizm, reject simple color results
                if original_details.get('transitions_color') or original_details.get('prizm_color'):
                    # Check if result has simple lens color but we're looking for Transitions/Prizm
                    # Pattern: "Green Lens" or "Green lenses" without Transitions/Prizm
                    simple_color_pattern = r',\s*([a-z]+)\s+lens'
                    simple_match = re.search(simple_color_pattern, full_result_text)
                    if simple_match and 'transitions' not in full_result_text and 'prizm' not in full_result_text:
                        # This is a simple color lens, but we're looking for Transitions/Prizm - reject
                        score = 0
                        logging.warning(f"❌ REJECTED: Looking for Transitions/Prizm but found simple '{simple_match.group(1)} lens' in result: {result.title[:60]}...")
                        continue
                    
                    # Also check if result has "Green Lens" as a standalone (not Transitions Green)
                    # If we're looking for "Transitions Graphite Green" but result has just "Green Lens", reject
                    if original_details.get('transitions_color'):
                        expected_trans = original_details['transitions_color'].lower()
                        # Check if result has the color word but NOT as part of "Transitions [color]"
                        # Pattern: color word appears but not preceded by "transitions"
                        color_word = expected_trans.split()[0] if expected_trans.split() else expected_trans
                        if color_word in full_result_text:
                            # Check if "transitions" appears before this color
                            transitions_pos = full_result_text.find('transitions')
                            color_pos = full_result_text.find(color_word)
                            if transitions_pos == -1 or (color_pos < transitions_pos or color_pos > transitions_pos + 50):
                                # Color appears but not as part of "Transitions [color]" - reject
                                score = 0
                                logging.warning(f"❌ REJECTED: Looking for 'Transitions {original_details['transitions_color']}' but found standalone '{color_word}' without Transitions in result: {result.title[:60]}...")
                                continue
                
                # CRITICAL: Strict Prizm color matching
                if original_details.get('prizm_color'):
                    expected_prizm = original_details['prizm_color'].lower()
                    
                    # Color aliases/mappings (e.g., "24k" = "gold", "24k gold" = "gold")
                    prizm_color_aliases = {
                        '24k': ['gold', '24k gold', '24 karat'],
                        '24k gold': ['gold', '24k', '24 karat'],
                        'gold': ['24k', '24k gold', '24 karat'],
                        'black': ['dark', 'jet black'],
                        'sapphire': ['blue sapphire'],
                    }
                    
                    # Get all possible aliases for the expected color
                    expected_prizm_variants = [expected_prizm]
                    if expected_prizm in prizm_color_aliases:
                        expected_prizm_variants.extend(prizm_color_aliases[expected_prizm])
                    # Also check reverse mapping
                    for alias_key, alias_values in prizm_color_aliases.items():
                        if expected_prizm in alias_values:
                            expected_prizm_variants.append(alias_key)
                    
                    if 'prizm' in full_result_text:
                        # Extract Prizm color from result (check full text including page details)
                        # Try multiple patterns
                        prizm_patterns = [
                            r'prizm[™®]?\s+([a-z0-9\s]+?)(?:\s*[,)]|$)',
                            r'prizm[™®]?\s+([a-z0-9\s]+?)(?:\s*[/\)]|$)',
                            r'prizm[™®]?\s+([a-z]+)',
                        ]
                        prizm_match = None
                        for pattern in prizm_patterns:
                            prizm_match = re.search(pattern, full_result_text, re.IGNORECASE)
                            if prizm_match:
                                break
                        
                        if prizm_match:
                            result_prizm_color = normalize_text(prizm_match.group(1).strip())
                            
                            # Check if result color matches expected color or any of its aliases
                            color_matches = (
                                expected_prizm == result_prizm_color or
                                result_prizm_color in expected_prizm_variants or
                                any(alias in result_prizm_color for alias in expected_prizm_variants if len(alias) > 3) or
                                any(result_prizm_color in alias for alias in expected_prizm_variants if len(alias) > 3)
                            )
                            
                            if not color_matches:
                                score = 0  # REJECT - wrong Prizm color
                                logging.warning(f"❌ REJECTED: Prizm color mismatch. Looking for 'Prizm {original_details['prizm_color']}' (or aliases: {expected_prizm_variants}) but found 'Prizm {prizm_match.group(1).strip()}' in result: {result.title[:60]}...")
                                continue
                            else:
                                logging.debug(f"✓ Prizm color match: '{original_details['prizm_color']}' matched with '{prizm_match.group(1).strip()}' (using aliases)")
                        else:
                            # Prizm mentioned but no color extracted - might be generic, but check if our expected color appears elsewhere
                            if expected_prizm not in full_result_text and not any(alias in full_result_text for alias in expected_prizm_variants):
                                score = 0
                                logging.warning(f"❌ REJECTED: Looking for 'Prizm {original_details['prizm_color']}' but could not extract color from result: {result.title[:60]}...")
                                continue
                    else:
                        # No Prizm in result but we're looking for it - REJECT
                        score = 0
                        logging.warning(f"❌ REJECTED: Looking for 'Prizm {original_details['prizm_color']}' but 'Prizm' not found in result: {result.title[:60]}...")
                        continue
                
                # CRITICAL: If looking for simple lens color, also check lens_color field
                if original_details.get('lens_color') and not original_details.get('simple_lens_color'):
                    # Use lens_color if simple_lens_color is not set
                    original_details['simple_lens_color'] = original_details['lens_color']
                
                # CRITICAL: Strict simple lens color matching (e.g., "Green lenses" vs "Clear" vs "Polarised")
                if original_details.get('simple_lens_color'):
                    expected_simple_color = original_details['simple_lens_color'].lower()
                    
                    # REJECT if result has Transitions or Prizm (we're looking for simple color)
                    if 'transitions' in full_result_text or 'prizm' in full_result_text:
                        score = 0
                        logging.warning(f"❌ REJECTED: Looking for simple '{original_details['simple_lens_color']} lenses' but found Transitions/Prizm in result: {result.title[:60]}...")
                        continue
                    
                    # Check if the simple color appears in result (use full_result_text)
                    color_pattern = rf'\b{re.escape(expected_simple_color)}\b'
                    if not re.search(color_pattern, full_result_text):
                        score = 0
                        logging.warning(f"❌ REJECTED: Looking for simple '{original_details['simple_lens_color']} lenses' but color '{expected_simple_color}' not found in result (checked title + page): {result.title[:60]}...")
                        continue
                    
                    # CRITICAL: For "Clear" lenses, reject if any other color OR lens type is found
                    if expected_simple_color == 'clear':
                        # First, reject if Polarised/Polarized is found ANYWHERE (Clear lenses are never Polarised)
                        # Check title first (most reliable)
                        result_title_lower = result.title.lower()
                        if 'polarised' in result_title_lower or 'polarized' in result_title_lower:
                            score = 0
                            logging.warning(f"❌ REJECTED: Looking for 'Clear lenses' but found 'Polarised/Polarized' in title: {result.title[:60]}...")
                            continue
                        
                        # Also check full text for Polarised/Gradient/Transitions/Prizm
                        lens_type_keywords = ['polarised', 'polarized', 'gradient', 'transitions', 'prizm']
                        for lens_keyword in lens_type_keywords:
                            if lens_keyword in full_result_text:
                                # For "polarised" or "polarized", reject immediately (Clear is never Polarised)
                                if lens_keyword in ['polarised', 'polarized']:
                                    score = 0
                                    logging.warning(f"❌ REJECTED: Looking for 'Clear lenses' but found '{lens_keyword}' in result: {result.title[:60]}...")
                                    break
                                
                                # For other lens types, check if it's part of a lens description
                                lens_type_patterns = [
                                    rf'\b{re.escape(lens_keyword)}\s+[a-z\s]*lens',
                                    rf'/{re.escape(lens_keyword)}',
                                    rf'\([^)]*{re.escape(lens_keyword)}[^)]*\)',  # In parentheses like "(Black/Polarised)"
                                    rf'{re.escape(lens_keyword)}\s+gradient',  # "Polarised Gradient"
                                    rf'gradient\s+{re.escape(lens_keyword)}'  # "Gradient Polarised"
                                ]
                                for pattern in lens_type_patterns:
                                    if re.search(pattern, full_result_text, re.IGNORECASE):
                                        score = 0
                                        logging.warning(f"❌ REJECTED: Looking for 'Clear lenses' but found '{lens_keyword}' lens type in result: {result.title[:60]}...")
                                        break
                                if score == 0:
                                    break
                        if score == 0:
                            continue
                        
                        # Also check for other colors that would indicate wrong product
                        if score > 0:  # Only check colors if lens types didn't reject it
                            other_colors = ['green', 'black', 'grey', 'gray', 'blue', 'red', 'yellow', 'orange', 'purple', 'pink', 'brown', 'sapphire', 'emerald', 'amethyst', 'graphite']
                            for other_color in other_colors:
                                if other_color in full_result_text:
                                    # Check if this color is part of a lens description (not frame color)
                                    # Pattern: "Green Lens" or "Green lenses" or "/Green" (in product title format)
                                    lens_color_patterns = [
                                        rf'\b{re.escape(other_color)}\s+lens',
                                        rf'/{re.escape(other_color)}',
                                        rf'\([^)]*{re.escape(other_color)}[^)]*\)'  # In parentheses like "(Black/Green)"
                                    ]
                                    for pattern in lens_color_patterns:
                                        if re.search(pattern, full_result_text, re.IGNORECASE):
                                            score = 0
                                            logging.warning(f"❌ REJECTED: Looking for 'Clear lenses' but found '{other_color}' lens color in result: {result.title[:60]}...")
                                            break
                                    if score == 0:
                                        break
                        if score == 0:
                            continue
                
                # CRITICAL: Strict lens type matching (e.g., "Polarised Gradient Graphite" vs "Green")
                if original_details.get('lens_type'):
                    expected_lens_type = original_details['lens_type'].lower()
                    lens_type_words = expected_lens_type.split()
                    
                    # For multi-word lens types like "Polarised Gradient Graphite", require ALL words in sequence
                    if len(lens_type_words) > 1:
                        # Multi-word lens type (e.g., "polarised gradient graphite")
                        # CRITICAL: All key words must be present AND in the right context
                        key_words = [w for w in lens_type_words if len(w) > 3]  # Words longer than 3 chars
                        all_key_words_present = all(word in full_result_text for word in key_words)
                        
                        if not all_key_words_present:
                            score = 0  # REJECT - not all words present
                            logging.warning(f"❌ REJECTED: Lens type '{original_details['lens_type']}' not fully matched. Required words: {key_words}, but not all found in result: {result.title[:60]}...")
                            continue
                        
                        # Also check that they appear together (not scattered)
                        # For "Polarised Gradient Graphite", check if they appear in sequence
                        combined_pattern = r'polarised[®™\s]*gradient[®™\s]*graphite|polarized[®™\s]*gradient[®™\s]*graphite'
                        if 'polarised gradient graphite' in expected_lens_type or 'polarized gradient graphite' in expected_lens_type:
                            # Check title first (most reliable)
                            result_title_lower = result.title.lower()
                            if 'polarised gradient graphite' not in result_title_lower and 'polarized gradient graphite' not in result_title_lower:
                                # Check if just "Polarised" appears without "Gradient Graphite"
                                if ('polarised' in result_title_lower or 'polarized' in result_title_lower) and 'gradient' not in result_title_lower:
                                    score = 0  # REJECT - only "Polarised" found, not "Polarised Gradient Graphite"
                                    logging.warning(f"❌ REJECTED: Looking for 'Polarised Gradient Graphite' but only found 'Polarised' (missing Gradient Graphite) in title: {result.title[:60]}...")
                                    continue
                                elif ('polarised' in result_title_lower or 'polarized' in result_title_lower) and 'gradient' in result_title_lower and 'graphite' not in result_title_lower:
                                    score = 0  # REJECT - "Polarised Gradient" found but missing "Graphite"
                                    logging.warning(f"❌ REJECTED: Looking for 'Polarised Gradient Graphite' but missing 'Graphite' in title: {result.title[:60]}...")
                                    continue
                            
                            # Also check full text with regex pattern
                            if not re.search(combined_pattern, full_result_text, re.IGNORECASE):
                                # Check if just "Polarised" appears without "Gradient Graphite" in full text
                                if ('polarised' in full_result_text or 'polarized' in full_result_text) and 'gradient' not in full_result_text:
                                    score = 0  # REJECT - only "Polarised" found, not "Polarised Gradient Graphite"
                                    logging.warning(f"❌ REJECTED: Looking for 'Polarised Gradient Graphite' but only found 'Polarised' (missing Gradient Graphite) in full text: {result.title[:60]}...")
                                    continue
                                elif ('polarised' in full_result_text or 'polarized' in full_result_text) and 'gradient' in full_result_text and 'graphite' not in full_result_text:
                                    score = 0  # REJECT - "Polarised Gradient" found but missing "Graphite"
                                    logging.warning(f"❌ REJECTED: Looking for 'Polarised Gradient Graphite' but missing 'Graphite' in full text: {result.title[:60]}...")
                                    continue
                    else:
                        # Single word lens type
                        # Extract lens info from result (use full_result_text which includes page details)
                        lens_in_result = re.search(r'([a-z\s]+?)\s+lenses?', full_result_text)
                        if lens_in_result:
                            result_lens_text = normalize_text(lens_in_result.group(1).strip())
                            if expected_lens_type not in result_lens_text:
                                # Check if result has a color instead of lens type - this is wrong
                                common_colors = ['green', 'clear', 'black', 'grey', 'gray', 'blue', 'red', 'yellow', 'orange', 'purple', 'violet', 'brown', 'pink', 'sapphire', 'emerald', 'amethyst']
                                if any(color in result_lens_text for color in common_colors):
                                    score = 0  # REJECT - looking for lens type but found color
                                    logging.warning(f"❌ REJECTED: Looking for '{original_details['lens_type']}' but found color '{result_lens_text}' in result: {result.title[:60]}...")
                                    continue
                                else:
                                    score = 0  # REJECT - lens type doesn't match
                                    logging.warning(f"❌ REJECTED: Lens type mismatch. Looking for '{original_details['lens_type']}' but found '{result_lens_text}' in result: {result.title[:60]}...")
                                    continue
                        else:
                            # Check if lens type appears in full text (might not have "lenses" keyword)
                            if expected_lens_type not in full_result_text:
                                score = 0  # REJECT - lens type not found
                                logging.warning(f"❌ REJECTED: Lens type '{original_details['lens_type']}' not found in result (checked title + page): {result.title[:60]}...")
                                continue
                
                # CRITICAL: Frame color matching (e.g., "Shiny Black" vs "Matte Black" vs "Black")
                if original_details.get('frame_color'):
                    expected_frame = original_details['frame_color'].lower()
                    frame_words = expected_frame.split()
                    
                    # Check for exact frame color match or key words (use full_result_text)
                    # For "Shiny Black" or "Matte Black", require both words
                    if len(frame_words) > 1:
                        # Multi-word frame color (e.g., "Shiny Black", "Matte Black")
                        # Check if all key words are present
                        all_frame_words_present = all(word in full_result_text for word in frame_words if len(word) > 2)
                        if not all_frame_words_present:
                            # Check if it's a different finish (e.g., looking for "Shiny Black" but found "Matte Black")
                            finish_words = ['shiny', 'matte', 'glossy', 'chalky', 'mystic', 'cosmic', 'asteroid']
                            expected_finish = [w for w in frame_words if w in finish_words]
                            result_finish = [w for w in finish_words if w in full_result_text]
                            if expected_finish and result_finish and expected_finish != result_finish:
                                score = 0  # REJECT - different finish (Shiny vs Matte)
                                logging.warning(f"❌ REJECTED: Frame finish mismatch. Looking for '{original_details['frame_color']}' but found different finish in result: {result.title[:60]}...")
                                continue
                    else:
                        # Single word frame color - check if it appears
                        if expected_frame not in full_result_text:
                            score -= 10  # Small penalty for missing frame color
                
                # Note: Accessory checks are now done earlier in the function (before score calculation)
                # This section is intentionally removed to avoid duplicate checks
                
                # CRITICAL: Check Low Bridge Fit - if required, must be present
                if original_details.get('low_bridge_fit'):
                    # Must have "low bridge" or "low bridge fit" in result
                    if 'low bridge' not in full_result_text.lower():
                        score = 0  # REJECT - Low Bridge Fit required but not found
                        logging.warning(f"❌ REJECTED: Looking for 'Low Bridge Fit' but not found in result: {result.title[:60]}...")
                        continue
                else:
                    # If NOT looking for Low Bridge Fit, but result has it, that's okay (regular model can match)
                    # But if we're looking for regular model and result ONLY has Low Bridge Fit, might be wrong
                    # For now, we'll allow it but this could be refined
                    pass
                
                # CRITICAL: Require model match - reject completely different models
                # BUT: Only apply this for products that have model information (sunglasses, electronics, etc.)
                # For candy/food products, model validation doesn't apply
                if original_details.get('model'):
                    # Check if this is a sunglasses/electronics product (has model) vs candy/food (no model)
                    # For now, apply model validation only if model is significant (more than 2 chars and not just numbers)
                    model_value = original_details['model'].strip()
                    is_significant_model = len(model_value) > 2 and not model_value.replace(' ', '').isdigit()
                    
                    if is_significant_model:
                        # Use full_result_text for model checking (includes page details for Amazon)
                        model_lower = original_details['model'].lower()
                        
                        # Extract core model name (remove "gen 2", "low bridge fit", etc.)
                        core_model_words = []
                        for word in original_details['model'].split():
                            word_lower = word.lower()
                            # Skip common modifiers (but keep "low bridge fit" info separate)
                            if word_lower not in ['gen', '2', 'gen2', 'low', 'bridge', 'fit', 'large', '(gen', 'gen)', 'meta']:
                                if len(word) > 2:  # Skip very short words
                                    core_model_words.append(word_lower)
                        core_model = ' '.join(core_model_words) if core_model_words else model_lower
                        
                        # Check if core model appears in result (use full_result_text)
                        exact_model_match = core_model in full_result_text or model_lower in full_result_text
                        
                        # Check for individual model words (must have at least one key word)
                        model_keywords = [w for w in core_model_words if len(w) > 3]  # Words longer than 3 chars
                        matched_keywords = sum(1 for keyword in model_keywords if keyword in full_result_text)
                        partial_model_match = matched_keywords >= max(1, len(model_keywords))
                        
                        # Check for WRONG models (critical - reject if different model detected)
                        # Only check known sunglasses/electronics models
                        wrong_model_detected = False
                        all_known_models = [
                            'wayfarer', 'skyler', 'headliner', 'vanguard', 'aviator', 'clubmaster',
                            'gascan', 'holbrook', 'frogskins', 'radar', 'jawbreaker', 'flak', 'flak 2.0', 'flak xl'
                        ]
                        for wrong_model in all_known_models:
                            if wrong_model != core_model and wrong_model not in model_lower:
                                # Check if this wrong model appears in the result (use full_result_text)
                                if wrong_model in full_result_text:
                                    # But our expected model doesn't appear - this is wrong!
                                    if not exact_model_match and matched_keywords == 0:
                                        wrong_model_detected = True
                                        score = 0  # REJECT completely - different model
                                        logging.warning(f"❌ REJECTED: Wrong model detected. Looking for '{original_details['model']}' but found '{wrong_model}' in result: {result.title[:60]}...")
                                        break
                        
                        if not wrong_model_detected:
                            # For scores >= 60, require model match
                            if score >= 60:
                                if not exact_model_match and not partial_model_match:
                                    score -= 50  # Heavy penalty - likely wrong product
                                    logging.debug(f"Reduced score by 50 (to {score:.1f}%) - model '{original_details['model']}' (core: '{core_model}') not found in result")
                            
                            # For scores >= 70, require STRICT model match
                            if score >= 70 and not exact_model_match:
                                score -= 40  # Very heavy penalty for high-score but wrong model
                                logging.debug(f"Reduced score by 40 (to {score:.1f}%) - exact model '{original_details['model']}' not found")
                    else:
                        # Model is not significant (likely not a sunglasses/electronics product) - skip strict model validation
                        logging.debug(f"Skipping strict model validation for non-significant model: '{model_value}'")
                
                # CRITICAL: For low scores (50-65%), require STRICT matching on all critical attributes
                if score >= self.fuzzy_threshold:
                    # For scores below 65%, require ALL critical attributes to match
                    if score < 65:
                        strict_match_required = True
                        # Check if all critical attributes match
                        if original_details.get('generation'):
                            result_text = normalize_text(result.title)
                            result_lower = result_text.lower()
                            expected_gen = original_details['generation'].lower()
                            gen_in_result = re.search(r'gen\s*(\d+)', result_lower)
                            if not gen_in_result or f"gen {gen_in_result.group(1)}" != expected_gen:
                                strict_match_required = False
                        
                        if original_details.get('transitions_color') and strict_match_required:
                            result_text = normalize_text(result.title)
                            result_lower = result_text.lower()
                            if 'transitions' not in result_lower:
                                strict_match_required = False
                        
                        if original_details.get('lens_color') and strict_match_required:
                            result_text = normalize_text(result.title)
                            result_lower = result_text.lower()
                            expected_color = original_details['lens_color'].lower()
                            # Check if color appears in result
                            if expected_color not in result_lower:
                                strict_match_required = False
                        
                        if not strict_match_required:
                            logging.warning(f"❌ REJECTED: Low score ({score:.1f}%) and critical attributes don't match. Result: {result.title[:60]}...")
                            continue  # Skip this result - too low score without strict match
                
                # CRITICAL: Brand validation - MUST match exactly
                if original_details and original_details.get('brand'):
                    brand_lower = original_details['brand'].lower()
                    result_lower = full_result_text.lower()
                    # Brand must appear in result - strict requirement
                    if brand_lower not in result_lower:
                        logging.warning(f"❌ REJECTED: Brand mismatch. Expected: '{original_details['brand']}', Result: {result.title[:60]}...")
                        continue  # Skip this result - brand doesn't match
                    else:
                        logging.debug(f"✓ Brand match: '{original_details['brand']}' found in result")
                
                # CRITICAL: Weight validation - EXACT match required (NO tolerance)
                if original_details and original_details.get('weight') is not None:
                    original_weight = original_details['weight']
                    result_weight = extract_weight(result.title)
                    
                    if result_weight is not None:
                        # EXACT match required - no tolerance at all
                        weight_diff = abs(original_weight - result_weight)
                        if weight_diff > 0.01:  # Only allow floating point precision differences
                            logging.warning(f"❌ REJECTED: Weight EXACT mismatch. Original: {original_weight} oz, Result: {result_weight} oz (diff: {weight_diff:.2f} oz, EXACT match required). Result: {result.title[:60]}...")
                            continue  # Skip this result - weight doesn't match exactly
                        else:
                            logging.debug(f"✓ Weight EXACT match: {original_weight} oz = {result_weight} oz")
                    else:
                        # Weight specified but not found in result - reject
                        logging.warning(f"❌ REJECTED: Weight {original_weight} oz not found in result: {result.title[:60]}...")
                        continue
                
                # CRITICAL: Flavor/variety validation for candy - EXACT match required
                if original_details and original_details.get('flavor'):
                    expected_flavor = original_details['flavor'].lower()
                    result_lower = full_result_text.lower()
                    
                    # EXACT match required - no synonyms, the exact flavor phrase must appear
                    if expected_flavor not in result_lower:
                        logging.warning(f"❌ REJECTED: Flavor/variety EXACT mismatch. Expected: '{original_details['flavor']}', Result: {result.title[:60]}...")
                        continue  # Skip this result - flavor doesn't match exactly
                    else:
                        logging.debug(f"✓ Flavor EXACT match: '{original_details['flavor']}' found in result")
                
                # CRITICAL: Count validation for candy - reject if counts don't match (within 10% tolerance)
                if original_details and original_details.get('count') is not None:
                    expected_count = original_details['count']
                    result_lower = full_result_text.lower()
                    
                    # Extract count from result
                    import re
                    result_count = None
                    count_patterns = [
                        r'(\d+)\s*ct',
                        r'(\d+)\s*count',
                        r'pack\s*of\s*(\d+)',
                        r'(\d+)\s*pieces',
                    ]
                    for pattern in count_patterns:
                        match = re.search(pattern, result_lower)
                        if match:
                            try:
                                result_count = int(match.group(1))
                                break
                            except:
                                pass
                    
                    if result_count is not None:
                        # Adaptive tolerance: 10% for counts >20, 15% for smaller counts, minimum 2
                        if expected_count > 20:
                            count_tolerance = max(2, int(expected_count * 0.10))  # 10% for large counts
                        else:
                            count_tolerance = max(2, int(expected_count * 0.15))  # 15% for small counts
                        count_diff = abs(expected_count - result_count)
                        
                        if count_diff > count_tolerance:
                            logging.warning(f"❌ REJECTED: Count mismatch. Expected: {expected_count}, Result: {result_count} (diff: {count_diff}, tolerance: {count_tolerance}). Result: {result.title[:60]}...")
                            continue  # Skip this result - count doesn't match
                        else:
                            logging.debug(f"✓ Count match: {expected_count} ≈ {result_count} (within tolerance)")
                    elif expected_count > 10:  # Only require count match for significant counts
                        # If count is specified but not found, apply penalty but don't reject (might be in description)
                        logging.debug(f"⚠ Count not found in result title, but expected {expected_count}")
                
                # CRITICAL: Final validation before accepting match - prevent false positives
                # For simple lens colors, ensure the lens color actually matches
                if score > best_score and score >= self.fuzzy_threshold:
                    is_valid_final_match = True
                    
                    if original_details:
                        # Final check: If looking for simple lens color, ensure it's actually in the result
                        if original_details.get('simple_lens_color'):
                            expected_color = original_details['simple_lens_color'].lower()
                            # Check if the expected color appears in result (title or URL)
                            result_title_lower = result.title.lower()
                            result_url_lower = result.url.lower() if hasattr(result, 'url') and result.url else ""
                            
                            # For "Clear", make sure "clear" appears and NO other lens colors/types appear
                            if expected_color == 'clear':
                                if 'clear' not in result_title_lower and 'clear' not in result_url_lower:
                                    is_valid_final_match = False
                                    logging.debug(f"Final validation failed: 'Clear' not found in result title/URL")
                                # Double-check no Polarised/Gradient (should have been caught earlier, but check again)
                                if 'polarised' in result_title_lower or 'polarized' in result_title_lower or 'gradient' in result_title_lower:
                                    is_valid_final_match = False
                                    logging.debug(f"Final validation failed: Polarised/Gradient found when looking for Clear")
                            else:
                                # For other simple colors (Green, etc.), ensure the color appears
                                if expected_color not in result_title_lower and expected_color not in result_url_lower:
                                    is_valid_final_match = False
                                    logging.debug(f"Final validation failed: Expected color '{expected_color}' not found in result")
                        
                        # Final check: If looking for Transitions color, ensure it's in result
                        if original_details.get('transitions_color') and is_valid_final_match:
                            expected_trans = original_details['transitions_color'].lower()
                            result_title_lower = result.title.lower()
                            result_url_lower = result.url.lower() if hasattr(result, 'url') and result.url else ""
                            full_text_lower = full_result_text.lower()
                            
                            # Must have "transitions" in result
                            if 'transitions' not in result_title_lower and 'transitions' not in result_url_lower and 'transitions' not in full_text_lower:
                                is_valid_final_match = False
                                logging.debug(f"Final validation failed: 'Transitions' not found when looking for Transitions {expected_trans}")
                    
                    if is_valid_final_match:
                        best_score = score
                        best_match = result
                        best_variant = variant
                    else:
                        logging.debug(f"Final validation rejected match: {result.title[:60]}...")
        
        # If no match meets threshold, try with lower threshold but still consider color/model
        if not best_match and search_results:
            logging.info(f"No matches met threshold ({self.fuzzy_threshold}%), trying relaxed matching (found {len(search_results)} total results)")
            for result in search_results[:10]:  # Check first 10 results
                for variant in variants:
                    if original_details:
                        score = self.calculate_match_score(original_details, variant, result.title)
                    else:
                        score = fuzz.token_sort_ratio(normalize_text(variant), normalize_text(result.title))
                    
                    # CRITICAL: Apply same strict checks in fallback - generation, transitions, etc.
                    if original_details:
                        # Check generation in fallback
                        if original_details.get('generation'):
                            result_text = normalize_text(result.title)
                            result_lower = result_text.lower()
                            expected_gen = original_details['generation'].lower()
                            gen_in_result = re.search(r'gen\s*(\d+)', result_lower)
                            if gen_in_result:
                                result_gen = f"gen {gen_in_result.group(1)}"
                                if result_gen != expected_gen:
                                    continue  # Skip - wrong generation
                        
                        # Check Transitions color in fallback - STRICT: reject if not found
                        if original_details.get('transitions_color'):
                            result_text = normalize_text(result.title)
                            result_lower = result_text.lower()
                            expected_transitions = original_details['transitions_color'].lower()
                            if 'transitions' not in result_lower:
                                continue  # Skip - Transitions required but not found in result
                            transitions_match = re.search(r'transitions[®™]?\s+([a-z\s]+?)(?:\s+lenses?|,|$)', result_lower)
                            if transitions_match:
                                result_transitions_color = normalize_text(transitions_match.group(1).strip())
                                if expected_transitions != result_transitions_color:
                                    expected_words = expected_transitions.split()
                                    if len(expected_words) > 1:
                                        if not all(word in result_transitions_color for word in expected_words):
                                            continue  # Skip - wrong Transitions color (multi-word)
                                    else:
                                        continue  # Skip - wrong single-word Transitions color
                            else:
                                continue  # Skip - Transitions mentioned but no color extracted
                        
                        # Check simple lens color in fallback - STRICT: reject Transitions/Prizm
                        if original_details.get('simple_lens_color'):
                            result_text = normalize_text(result.title)
                            result_lower = result_text.lower()
                            if 'transitions' in result_lower or 'prizm' in result_lower:
                                continue  # Skip - looking for simple color but found Transitions/Prizm
                        
                        # Check size in fallback - STRICT: reject if size doesn't match
                        if original_details.get('size'):
                            result_text = normalize_text(result.title)
                            result_upper = result_text.upper()
                            expected_size = original_details['size'].lower()
                            size_match = expected_size.capitalize() in result_upper or expected_size.upper() in result_upper
                            if not size_match:
                                continue  # Skip - size required but not found
                    
                    # CRITICAL: In fallback, also check if result name matches Excel product name
                    if original_product_name:
                        excel_name_normalized = normalize_text(original_product_name)
                        result_name_normalized = normalize_text(result.title)
                        
                        # Extract key words from Excel name
                        key_words = []
                        if original_details.get('brand'):
                            brand_words = original_details['brand'].lower().split()
                            key_words.extend([w for w in brand_words if len(w) > 2])
                        
                        if original_details.get('model'):
                            model_words = original_details['model'].lower().split()
                            key_words.extend([w for w in model_words if len(w) > 3])
                        
                        if original_details.get('generation'):
                            gen_match = re.search(r'gen\s*(\d+)', original_details['generation'].lower())
                            if gen_match:
                                key_words.append(f"gen{gen_match.group(1)}")
                        
                        # Check if key words appear in result name
                        if key_words:
                            result_lower = result_name_normalized.lower()
                            matched_key_words = sum(1 for word in key_words if word in result_lower)
                            min_required = max(1, int(len(key_words) * 0.7)) if len(key_words) > 2 else len(key_words)
                            
                            if matched_key_words < min_required:
                                logging.debug(f"Rejected fallback: name doesn't match ({matched_key_words}/{len(key_words)} key words)")
                                continue  # Skip - name doesn't match
                    
                    # Only use fallback if score is decent (70+) and passed strict checks
                    if score > best_score and score >= 70:
                        result_text = normalize_text(result.title)
                        result_lower = result_text.lower()
                        
                        # Must have brand match for fallback
                        brand_match = False
                        if original_details.get('brand'):
                            brand_lower = original_details['brand'].lower()
                            brand_match = brand_lower in result_lower
                        else:
                            # If no brand extracted, accept any match with score >= 50
                            brand_match = True
                        
                        # Model match is preferred but not required for fallback
                        # BUT: Still reject completely different models even in fallback
                        model_match = True
                        wrong_model_in_fallback = False
                        if original_details.get('model'):
                            model_lower = original_details['model'].lower()
                            result_lower = result_text.lower()
                            
                            # Extract core model name (same as above)
                            core_model_words = []
                            for word in original_details['model'].split():
                                word_lower = word.lower()
                                if word_lower not in ['gen', '2', 'gen2', 'low', 'bridge', 'fit', 'large', '(gen', 'gen)', 'meta']:
                                    if len(word) > 2:
                                        core_model_words.append(word_lower)
                            core_model = ' '.join(core_model_words) if core_model_words else model_lower
                            
                            # CRITICAL: Check for wrong models even in fallback
                            all_known_models = [
                                'wayfarer', 'skyler', 'headliner', 'vanguard', 'aviator', 'clubmaster',
                                'gascan', 'holbrook', 'frogskins', 'radar', 'jawbreaker'
                            ]
                            for wrong_model in all_known_models:
                                if wrong_model != core_model and wrong_model not in model_lower:
                                    if wrong_model in result_lower:
                                        # Check if our expected model also appears
                                        if core_model not in result_lower and not any(w in result_lower for w in core_model_words if len(w) > 3):
                                            wrong_model_in_fallback = True
                                            logging.warning(f"❌ REJECTED in fallback: Wrong model '{wrong_model}' detected when looking for '{original_details['model']}'")
                                            break
                            
                            if not wrong_model_in_fallback:
                                # Check for exact or significant partial match
                                exact_match = model_lower in result_lower or core_model in result_lower
                                model_keywords = [w for w in core_model_words if len(w) > 3]
                                matched_keywords = sum(1 for keyword in model_keywords if keyword in result_lower)
                                partial_match = matched_keywords >= max(1, len(model_keywords) * 0.5) if model_keywords else False
                                model_match = exact_match or partial_match
                                
                                # If model doesn't match, give a small penalty but still consider it
                                if not model_match:
                                    score -= 10  # Small penalty for missing model
                                    logging.debug(f"Fallback: model mismatch, reduced score to {score:.1f}%")
                        
                        # Accept if brand matches (or no brand requirement) and score is still >= 65 after penalty
                        # BUT: Never accept if wrong model was detected - stricter for exact matching
                        if not wrong_model_in_fallback and brand_match and score >= 70:
                            best_score = score
                            best_match = result
                            best_variant = variant
                            logging.info(f"Using fallback match: {result.title[:60]}... (Score: {score:.1f}%, Brand: {brand_match}, Model: {model_match})")
                        else:
                            if wrong_model_in_fallback:
                                logging.debug(f"Rejected fallback: wrong model detected")
                            else:
                                logging.debug(f"Rejected fallback: brand_match={brand_match}, model_match={model_match}, score={score:.1f}%")
        
        # CRITICAL: Only return match if it meets accuracy requirements
        if best_match:
            # Require minimum score of 70 for accurate matching
            if best_score >= 70:
                # FINAL VALIDATION: Ensure ALL critical attributes match for absolute accuracy
                all_attributes_match = True
                validation_errors = []
                
                # 1. Brand must match
                if original_details and original_details.get('brand'):
                    brand_lower = original_details['brand'].lower()
                    result_lower = best_match.title.lower()
                    if brand_lower not in result_lower:
                        all_attributes_match = False
                        validation_errors.append(f"Brand '{original_details['brand']}' not found")
                
                # 2. Flavor must match EXACTLY (if specified) - no synonyms, exact match only
                if original_details and original_details.get('flavor'):
                    expected_flavor = original_details['flavor'].lower()
                    result_lower = best_match.title.lower()
                    # EXACT match required - the exact flavor phrase must appear
                    if expected_flavor not in result_lower:
                        all_attributes_match = False
                        validation_errors.append(f"Flavor '{original_details['flavor']}' not found (EXACT match required)")
                
                # 3. Count must match (if specified and significant)
                if original_details and original_details.get('count') is not None and original_details['count'] > 10:
                    import re
                    result_lower = best_match.title.lower()
                    result_count = None
                    count_patterns = [
                        r'(\d+)\s*ct',
                        r'(\d+)\s*count',
                        r'pack\s*of\s*(\d+)',
                    ]
                    for pattern in count_patterns:
                        match = re.search(pattern, result_lower)
                        if match:
                            try:
                                result_count = int(match.group(1))
                                break
                            except:
                                pass
                    if result_count is not None:
                        count_diff = abs(original_details['count'] - result_count)
                        # Adaptive tolerance: 10% for counts >20, 15% for smaller counts, minimum 2
                        if original_details['count'] > 20:
                            count_tolerance = max(2, int(original_details['count'] * 0.10))  # 10% for large counts
                        else:
                            count_tolerance = max(2, int(original_details['count'] * 0.15))  # 15% for small counts
                        if count_diff > count_tolerance:
                            all_attributes_match = False
                            validation_errors.append(f"Count mismatch: expected {original_details['count']}, found {result_count}")
                
                # 4. Weight must match EXACTLY (if specified) - NO tolerance
                if original_details and original_details.get('weight') is not None:
                    result_weight = extract_weight(best_match.title)
                    if result_weight is not None:
                        # EXACT match required - no tolerance at all
                        if abs(original_details['weight'] - result_weight) > 0.01:  # Only allow floating point precision differences
                            all_attributes_match = False
                            validation_errors.append(f"Weight mismatch: expected {original_details['weight']} oz, found {result_weight} oz (EXACT match required)")
                    else:
                        # Weight specified but not found in result - reject
                        all_attributes_match = False
                        validation_errors.append(f"Weight {original_details['weight']} oz not found in result")
                
                if all_attributes_match:
                    best_match.variant = best_variant
                    best_match.score = best_score
                    logging.info(f"✓ ABSOLUTE MATCH ACCEPTED: Score {best_score:.1f}% - All attributes validated: {best_match.title[:60]}...")
                    return best_match
                else:
                    logging.warning(f"❌ REJECTED: Score {best_score:.1f}% but validation failed: {', '.join(validation_errors)}. Result: {best_match.title[:60]}...")
                    return None
            else:
                logging.warning(f"Match found but score {best_score:.1f}% is below minimum 70% for accurate matching. Rejecting: {best_match.title[:60]}...")
                return None
        
        return None

# ==================== MAIN PROCESSOR ====================

class ProductURLFinder:
    """Main class that orchestrates the entire process"""
    
    def __init__(self, config: Dict = None):
        self.config = config or DEFAULT_CONFIG.copy()
        self.upc_scraper = UPCitemdbScraper(self.config)
        self.retailer_searcher = None
        self.matcher = ProductMatcher(self.config)
    
    def process_excel_file(self, input_file: str, output_file: str, sheet_name: str = None) -> None:
        """Process Excel file and find product URLs"""
        try:
            # Load Excel file
            if sheet_name:
                df = pd.read_excel(input_file, sheet_name=sheet_name)
            else:
                df = pd.read_excel(input_file)
            
            logging.info(f"Loaded {len(df)} rows from {input_file}")
            
            # Detect product name column (handle both "Product Name" and "Product Name/ID")
            product_name_col = None
            has_product_name_column = False
            if 'Product Name' in df.columns:
                product_name_col = 'Product Name'
                has_product_name_column = True
            elif 'Product Name/ID' in df.columns:
                product_name_col = 'Product Name/ID'
                has_product_name_column = False  # This column may contain IDs, not names
            else:
                raise ValueError("Missing required column: 'Product Name' or 'Product Name/ID'")
            
            # Store whether we have a "Product Name" column (not "Product Name/ID")
            # This determines if we should use UPCitemdb
            self.has_product_name_column = has_product_name_column
            logging.info(f"Product Name column detected: {product_name_col} (has_product_name_column={has_product_name_column})")
            
            # Ensure required columns exist - check for 'Retailer' or retailer column variations
            retailer_col = None
            if 'Retailer' in df.columns:
                retailer_col = 'Retailer'
            elif 'Instacart-Publix-US' in df.columns:
                retailer_col = 'Instacart-Publix-US'
            else:
                # Try to find any column that might contain retailer info
                for col in df.columns:
                    if 'retailer' in col.lower() or 'store' in col.lower():
                        retailer_col = col
                        break
            
            if retailer_col is None:
                raise ValueError("Missing required column: 'Retailer' (or similar retailer column)")
            
            # Rename the retailer column to 'Retailer' for consistency
            if retailer_col != 'Retailer':
                df = df.rename(columns={retailer_col: 'Retailer'})
                logging.info(f"Using column '{retailer_col}' as 'Retailer' column")
            
            # Add output columns if they don't exist
            output_columns = ['Found URL', 'Found Title', 'Matched Retailer', 'Matched Variant', 'Match Score', 'Status']
            for col in output_columns:
                if col not in df.columns:
                    df[col] = ""
            
            # Store the product name column name for use in _process_row
            self.product_name_column = product_name_col
            
            # Initialize retailer searcher
            self.retailer_searcher = RetailerSearcher(self.config)
            
            try:
                # Process each row
                for index, row in df.iterrows():
                    try:
                        result = self._process_row(row)
                        self._update_dataframe(df, index, result)
                        
                        # Save progress periodically
                        if (index + 1) % self.config['save_interval'] == 0:
                            df.to_excel(output_file, index=False)
                            logging.info(f"Progress saved at row {index + 1}")
                        
                    except Exception as e:
                        logging.error(f"Error processing row {index}: {e}")
                        self._update_dataframe(df, index, ProcessingResult(
                            success=False,
                            error=str(e)
                        ))
                
                # Final save
                df.to_excel(output_file, index=False)
                logging.info(f"Results saved to {output_file}")
                
            finally:
                if self.retailer_searcher:
                    self.retailer_searcher.close()
                    
        except Exception as e:
            logging.error(f"Error processing Excel file: {e}")
            raise
    
    def _process_row(self, row: pd.Series) -> ProcessingResult:
        """Process a single row - PRIMARY APPROACH: Search retailers using product names"""
        # Get product name from the detected column (handles both "Product Name" and "Product Name/ID")
        product_name_col = getattr(self, 'product_name_column', 'Product Name')
        product_name = str(row.get(product_name_col, '')).strip()
        
        # Check if we're using "Product Name/ID" column (indicates we might have IDs instead of names)
        is_product_id_column = (product_name_col == 'Product Name/ID')
        
        # Also check if there's a separate "Product Name/ID" or "Product Name" column that might have additional info
        product_name_id = ""
        # Check for both columns regardless of which one was detected as primary
        if 'Product Name/ID' in row.index:
            product_name_id_val = str(row.get('Product Name/ID', '')).strip()
            if product_name_id_val and product_name_id_val != product_name:
                product_name_id = product_name_id_val
        if 'Product Name' in row.index and not product_name_id:
            product_name_val = str(row.get('Product Name', '')).strip()
            if product_name_val and product_name_val != product_name:
                product_name_id = product_name_val
        
        gtin = extract_gtin(row.get('GTIN', ''))
        retailer = str(row.get('Retailer', '')).strip().lower()
        
        if not product_name:
            return ProcessingResult(success=False, error="No product name provided")
        
        if not retailer:
            return ProcessingResult(success=False, error="No retailer specified")
        
        # Normalize retailer name
        normalized_retailer = self._normalize_retailer_name(retailer)
        if normalized_retailer is None:
            return ProcessingResult(success=False, error=f"Retailer '{retailer}' not configured/supported")
        if normalized_retailer not in RETAILERS:
            return ProcessingResult(success=False, error=f"Unknown retailer: {normalized_retailer}")
        retailer = normalized_retailer
        
        # ========== PRIMARY APPROACH: Search retailers using product names ==========
        # Step 1: Prepare search queries from product names
        # IMPORTANT: Only use UPCitemdb if there is NO "Product Name" column in Excel
        search_queries = []
        original_product_name = product_name  # Keep original for matching
        
        # Check if we have a "Product Name" column (not "Product Name/ID")
        has_product_name_col = getattr(self, 'has_product_name_column', False)
        
        if has_product_name_col:
            # We have "Product Name" column - use it directly, NO UPCitemdb
            if not is_product_id(product_name):
                search_queries.append(product_name)
                logging.info(f"Using product name from Excel (Product Name column exists): {product_name[:60]}...")
            else:
                logging.warning(f"Product name is an ID '{product_name}' but Product Name column exists - skipping search")
        else:
            # NO "Product Name" column - we may need UPCitemdb to get product names from GTIN
            if not is_product_id(product_name):
                # Product name/ID column has a real name, use it
                search_queries.append(product_name)
                logging.info(f"Using product name from Excel: {product_name[:60]}...")
            else:
                # Product name/ID column has an ID - use UPCitemdb to get product name from GTIN
                if gtin:
                    logging.info(f"No 'Product Name' column found. Product Name/ID is an ID '{product_name}'. Using UPCitemdb to get product name from GTIN {gtin}...")
                    try:
                        product_variations = self.upc_scraper.search_by_gtin(gtin)
                        if product_variations:
                            # Use UPCitemdb variations as search queries
                            search_queries.extend(product_variations[:self.config.get('max_variants', 8)])
                            logging.info(f"✓ Retrieved {len(product_variations)} product name variations from UPCitemdb: {product_variations[:3]}")
                            # Update original_product_name for matching
                            original_product_name = product_variations[0] if product_variations else product_name
                        else:
                            logging.warning(f"Could not retrieve product names from UPCitemdb for GTIN {gtin}")
                    except Exception as e:
                        logging.error(f"Error retrieving product names from UPCitemdb: {e}")
                else:
                    logging.warning(f"Product Name/ID is an ID '{product_name}' but no GTIN available - cannot use UPCitemdb")
        
        # Step 3: If we still don't have any searchable queries, try direct URL methods for known product IDs as last resort
        if not search_queries and is_product_id(product_name):
            logging.info(f"No searchable product names found, trying direct URL methods for product ID: {product_name}")
            
            # Special handling for Amazon ASINs - construct direct URL
            if retailer in ['amazon', 'amazon-fresh'] and is_amazon_asin(product_name):
                asin = product_name.upper()
                direct_url = f"https://www.amazon.com/dp/{asin}"
                logging.info(f"Amazon ASIN detected, using direct URL: {direct_url}")
                
                # Try to fetch the product page to get title
                try:
                    if self.retailer_searcher and self.retailer_searcher.driver:
                        self.retailer_searcher.driver.get(direct_url)
                        time.sleep(2.0)
                        
                        # Try to get product title
                        try:
                            from selenium.webdriver.common.by import By
                            title_elem = self.retailer_searcher.driver.find_element(By.CSS_SELECTOR, "#productTitle")
                            product_title = title_elem.text.strip()
                            
                            # Verify it's a valid product page (not error page)
                            if product_title and len(product_title) > 5:
                                logging.info(f"✓ Found product via ASIN: {product_title[:60]}...")
                                return ProcessingResult(
                                    success=True,
                                    url=direct_url,
                                    title=product_title,
                                    retailer=retailer,
                                    variant=product_name,
                                    score=100.0  # Direct match via ASIN
                                )
                        except:
                            pass
                        
                        # If we can't get title, still return the URL (it's a direct match)
                        logging.info(f"✓ Using ASIN direct URL (could not fetch title)")
                        return ProcessingResult(
                            success=True,
                            url=direct_url,
                            title=f"Product {asin}",
                            retailer=retailer,
                            variant=product_name,
                            score=100.0
                        )
                except Exception as e:
                    logging.warning(f"Error accessing ASIN URL: {e}")
                    # Fall through to try GTIN lookup
            
            # Special handling for Walgreens product IDs - construct direct URL
            if retailer == 'walgreens' and is_walgreens_product_id(product_name):
                walgreens_id = product_name.upper()
                # Walgreens URL pattern: https://www.walgreens.com/store/c/ID={product-id}-product
                direct_url = f"https://www.walgreens.com/store/c/ID={walgreens_id}-product"
                logging.info(f"Walgreens product ID detected, using direct URL: {direct_url}")
                
                # Try to fetch the product page to get title
                try:
                    if self.retailer_searcher and self.retailer_searcher.driver:
                        self.retailer_searcher.driver.get(direct_url)
                        time.sleep(2.0)
                        
                        # Try to get product title
                        try:
                            from selenium.webdriver.common.by import By
                            # Walgreens product title selectors
                            title_selectors = [
                                "h1.product-title",
                                "h1",
                                ".product-title",
                                "[data-testid='product-title']",
                                ".product-name"
                            ]
                            product_title = None
                            for selector in title_selectors:
                                try:
                                    title_elem = self.retailer_searcher.driver.find_element(By.CSS_SELECTOR, selector)
                                    product_title = title_elem.text.strip()
                                    if product_title and len(product_title) > 5:
                                        break
                                except:
                                    continue
                            
                            # Verify it's a valid product page (not error page)
                            if product_title and len(product_title) > 5:
                                logging.info(f"✓ Found product via Walgreens ID: {product_title[:60]}...")
                                return ProcessingResult(
                                    success=True,
                                    url=direct_url,
                                    title=product_title,
                                    retailer=retailer,
                                    variant=product_name,
                                    score=100.0  # Direct match via product ID
                                )
                        except Exception as e:
                            logging.debug(f"Could not extract title from Walgreens page: {e}")
                        
                        # Check if page loaded successfully (not 404 or error)
                        page_source = self.retailer_searcher.driver.page_source.lower()
                        if 'product' in page_source or 'add to cart' in page_source or 'price' in page_source:
                            # Looks like a valid product page, even if we couldn't get title
                            logging.info(f"✓ Using Walgreens direct URL (valid product page detected)")
                            return ProcessingResult(
                                success=True,
                                url=direct_url,
                                title=f"Product {walgreens_id}",
                                retailer=retailer,
                                variant=product_name,
                                score=100.0
                            )
                        else:
                            logging.warning(f"Walgreens URL may be invalid (404 or error page)")
                except Exception as e:
                    logging.warning(f"Error accessing Walgreens product ID URL: {e}")
                    # Fall through to try GTIN lookup or search
            
            # Special handling for Target product IDs - construct direct URL
            if retailer == 'target' and is_target_product_id(product_name):
                target_id = product_name.upper()
                # Target URL pattern: https://www.target.com/p/-/A-{ID} or https://www.target.com/p/{product-name}/-/A-{ID}
                # Remove A- prefix if present, then add it back
                clean_id = target_id.replace('A-', '').replace('A_', '')
                direct_url = f"https://www.target.com/p/-/A-{clean_id}"
                logging.info(f"Target product ID detected, using direct URL: {direct_url}")
                
                try:
                    if self.retailer_searcher and self.retailer_searcher.driver:
                        self.retailer_searcher.driver.get(direct_url)
                        time.sleep(2.0)
                        
                        try:
                            from selenium.webdriver.common.by import By
                            title_selectors = ["h1", "[data-test='product-title']", ".product-title"]
                            product_title = None
                            for selector in title_selectors:
                                try:
                                    title_elem = self.retailer_searcher.driver.find_element(By.CSS_SELECTOR, selector)
                                    product_title = title_elem.text.strip()
                                    if product_title and len(product_title) > 5:
                                        break
                                except:
                                    continue
                            
                            if product_title and len(product_title) > 5:
                                logging.info(f"✓ Found product via Target ID: {product_title[:60]}...")
                                return ProcessingResult(
                                    success=True,
                                    url=direct_url,
                                    title=product_title,
                                    retailer=retailer,
                                    variant=product_name,
                                    score=100.0
                                )
                        except:
                            pass
                        
                        page_source = self.retailer_searcher.driver.page_source.lower()
                        if 'product' in page_source or 'add to cart' in page_source:
                            logging.info(f"✓ Using Target direct URL (valid product page detected)")
                            return ProcessingResult(
                                success=True,
                                url=direct_url,
                                title=f"Product {target_id}",
                                retailer=retailer,
                                variant=product_name,
                                score=100.0
                            )
                except Exception as e:
                    logging.warning(f"Error accessing Target product ID URL: {e}")
            
            # Special handling for Instacart product IDs - construct direct URL
            if retailer == 'instacart-publix' and is_instacart_product_id(product_name):
                instacart_id = product_name.strip()
                # Instacart URL pattern: https://www.instacart.com/products/{id}-product-name
                # We'll use just the ID and let Instacart redirect
                direct_url = f"https://www.instacart.com/products/{instacart_id}"
                logging.info(f"Instacart product ID detected, using direct URL: {direct_url}")
                
                try:
                    if self.retailer_searcher and self.retailer_searcher.driver:
                        self.retailer_searcher.driver.get(direct_url)
                        time.sleep(2.0)
                        
                        # Check if valid product page
                        page_source = self.retailer_searcher.driver.page_source.lower()
                        current_url = self.retailer_searcher.driver.current_url
                        
                        if 'products' in current_url and ('add to cart' in page_source or 'price' in page_source):
                            try:
                                from selenium.webdriver.common.by import By
                                title_elem = self.retailer_searcher.driver.find_element(By.CSS_SELECTOR, "h1, .product-title, [data-testid='product-title']")
                                product_title = title_elem.text.strip()
                                if product_title and len(product_title) > 5:
                                    logging.info(f"✓ Found product via Instacart ID: {product_title[:60]}...")
                                    return ProcessingResult(
                                        success=True,
                                        url=current_url,
                                        title=product_title,
                                        retailer=retailer,
                                        variant=product_name,
                                        score=100.0
                                    )
                            except:
                                pass
                            
                            logging.info(f"✓ Using Instacart direct URL (valid product page detected)")
                            return ProcessingResult(
                                success=True,
                                url=current_url,
                                title=f"Product {instacart_id}",
                                retailer=retailer,
                                variant=product_name,
                                score=100.0
                            )
                except Exception as e:
                    logging.warning(f"Error accessing Instacart product ID URL: {e}")
            
            # Special handling for CVS product IDs - try direct URL
            if retailer == 'cvs' and is_cvs_product_id(product_name):
                cvs_id = product_name.strip()
                # CVS URL pattern: https://www.cvs.com/store/product/{product-name}/ID={id}
                # Try direct search with ID first, or construct URL
                direct_url = f"https://www.cvs.com/store/product/cvs-product/ID={cvs_id}"
                logging.info(f"CVS product ID detected, attempting direct URL: {direct_url}")
                
                try:
                    if self.retailer_searcher and self.retailer_searcher.driver:
                        self.retailer_searcher.driver.get(direct_url)
                        time.sleep(2.0)
                        
                        page_source = self.retailer_searcher.driver.page_source.lower()
                        current_url = self.retailer_searcher.driver.current_url
                        
                        if 'product' in current_url and 'access denied' not in page_source:
                            try:
                                from selenium.webdriver.common.by import By
                                title_elem = self.retailer_searcher.driver.find_element(By.CSS_SELECTOR, "h1, .product-title")
                                product_title = title_elem.text.strip()
                                if product_title and len(product_title) > 5:
                                    logging.info(f"✓ Found product via CVS ID: {product_title[:60]}...")
                                    return ProcessingResult(
                                        success=True,
                                        url=current_url,
                                        title=product_title,
                                        retailer=retailer,
                                        variant=product_name,
                                        score=100.0
                                    )
                            except:
                                pass
                except Exception as e:
                    logging.warning(f"Error accessing CVS product ID URL: {e}")
            
            # Special handling for Walmart product IDs - try direct URL
            if retailer == 'walmart' and is_walmart_product_id(product_name):
                walmart_id = product_name.strip()
                # Walmart URL pattern: https://www.walmart.com/ip/{product-name}/{id}
                direct_url = f"https://www.walmart.com/ip/{walmart_id}"
                logging.info(f"Walmart product ID detected, attempting direct URL: {direct_url}")
                
                try:
                    if self.retailer_searcher and self.retailer_searcher.driver:
                        self.retailer_searcher.driver.get(direct_url)
                        time.sleep(2.0)
                        
                        page_source = self.retailer_searcher.driver.page_source.lower()
                        current_url = self.retailer_searcher.driver.current_url
                        
                        if '/ip/' in current_url and 'robot' not in page_source and 'captcha' not in page_source:
                            try:
                                from selenium.webdriver.common.by import By
                                title_elem = self.retailer_searcher.driver.find_element(By.CSS_SELECTOR, "h1[itemprop='name'], h1.prod-ProductTitle")
                                product_title = title_elem.text.strip()
                                if product_title and len(product_title) > 5:
                                    logging.info(f"✓ Found product via Walmart ID: {product_title[:60]}...")
                                    return ProcessingResult(
                                        success=True,
                                        url=current_url,
                                        title=product_title,
                                        retailer=retailer,
                                        variant=product_name,
                                        score=100.0
                                    )
                            except:
                                pass
                except Exception as e:
                    logging.warning(f"Error accessing Walmart product ID URL: {e}")
            
            # Special handling for HEB product IDs - try direct URL
            if retailer == 'heb' and is_heb_product_id(product_name):
                heb_id = product_name.strip()
                # HEB URL pattern: https://www.heb.com/product-detail/{product-name-slug}/{id}
                # Try multiple URL patterns since we don't have the product name slug
                url_patterns = [
                    f"https://www.heb.com/product-detail/product/{heb_id}",
                    f"https://www.heb.com/product-detail/{heb_id}",
                ]
                
                for direct_url in url_patterns:
                    logging.info(f"HEB product ID detected, attempting direct URL: {direct_url}")
                    
                    try:
                        if self.retailer_searcher and self.retailer_searcher.driver:
                            self.retailer_searcher.driver.get(direct_url)
                            time.sleep(2.0)
                            
                            page_source = self.retailer_searcher.driver.page_source.lower()
                            current_url = self.retailer_searcher.driver.current_url
                            
                            # Check if we got redirected to a valid product page
                            if 'product-detail' in current_url and 'access denied' not in page_source and '404' not in page_source and 'not found' not in page_source:
                                try:
                                    from selenium.webdriver.common.by import By
                                    title_elem = self.retailer_searcher.driver.find_element(By.CSS_SELECTOR, "h1, .product-title, [data-testid='product-title']")
                                    product_title = title_elem.text.strip()
                                    if product_title and len(product_title) > 5:
                                        logging.info(f"✓ Found product via HEB ID: {product_title[:60]}...")
                                        return ProcessingResult(
                                            success=True,
                                            url=current_url,
                                            title=product_title,
                                            retailer=retailer,
                                            variant=product_name,
                                            score=100.0
                                        )
                                except:
                                    pass
                    except Exception as e:
                        logging.debug(f"HEB URL pattern failed: {e}")
                        continue
                
                logging.warning(f"Could not access HEB product via direct URL, will try search instead")
            
            # Special handling for Sam's Club product IDs - try direct URL
            if retailer == 'sams-club' and is_sams_club_product_id(product_name):
                sams_id = product_name.strip()
                # Sam's Club URL pattern: https://www.samsclub.com/ip/{product-name-slug}/{id}
                # Try multiple URL patterns since we don't have the product name slug
                url_patterns = [
                    f"https://www.samsclub.com/ip/Product/{sams_id}",
                    f"https://www.samsclub.com/ip/{sams_id}",
                ]
                
                for direct_url in url_patterns:
                    logging.info(f"Sam's Club product ID detected, attempting direct URL: {direct_url}")
                    
                    try:
                        if self.retailer_searcher and self.retailer_searcher.driver:
                            self.retailer_searcher.driver.get(direct_url)
                            time.sleep(2.0)
                            
                            page_source = self.retailer_searcher.driver.page_source.lower()
                            current_url = self.retailer_searcher.driver.current_url
                            
                            # Check if we got redirected to a valid product page
                            if '/ip/' in current_url and 'robot' not in page_source and 'captcha' not in page_source and '404' not in page_source:
                                try:
                                    from selenium.webdriver.common.by import By
                                    title_elem = self.retailer_searcher.driver.find_element(By.CSS_SELECTOR, "h1, .sc-product-header-title, [data-testid='product-title']")
                                    product_title = title_elem.text.strip()
                                    if product_title and len(product_title) > 5:
                                        logging.info(f"✓ Found product via Sam's Club ID: {product_title[:60]}...")
                                        return ProcessingResult(
                                            success=True,
                                            url=current_url,
                                            title=product_title,
                                            retailer=retailer,
                                            variant=product_name,
                                            score=100.0
                                        )
                                except:
                                    pass
                    except Exception as e:
                        logging.debug(f"Sam's Club URL pattern failed: {e}")
                        continue
                
                logging.warning(f"Could not access Sam's Club product via direct URL")
            
            # If direct URL methods failed, return NOT_FOUND
            return ProcessingResult(success=False, error="NOT_FOUND")
        
        # Step 4: Search retailers with all prepared search queries
        if not search_queries:
            logging.warning(f"No search queries available for product: {product_name}")
            return ProcessingResult(success=False, error="NOT_FOUND")
        
        logging.info(f"Processing: {original_product_name} | Product Name/ID: {product_name_id if product_name_id else 'N/A'} | GTIN: {gtin} | Retailer: {retailer}")
        logging.info(f"Search queries prepared: {len(search_queries)} queries")
        
        # Search with all available queries
        all_search_results = []
        for query in search_queries:
            if not query or len(query.strip()) < 3:
                continue
            
            # Skip searching with numeric-only IDs (they won't work)
            if re.fullmatch(r"\d+", str(query).strip()):
                logging.info(f"Skipping search with numeric-only ID: {query}")
                continue
                
            logging.info(f"Searching retailer with query: {query[:60]}...")
            try:
                search_results = self.retailer_searcher.search_retailer(retailer, query)
                if search_results:
                    logging.info(f"Found {len(search_results)} search results for '{query[:60]}...' on {retailer}")
                    all_search_results.extend(search_results)
                else:
                    logging.debug(f"No search results for '{query[:60]}...' on {retailer}")
                    # NOTE: No fallback/variant searches - only searching exact product name from Excel
            except Exception as e:
                logging.error(f"Error searching retailer {retailer} for '{query}': {e}")
        
        # Remove duplicate results (same URL)
        seen_urls = set()
        unique_results = []
        for result in all_search_results:
            if result.url not in seen_urls:
                seen_urls.add(result.url)
                unique_results.append(result)
        all_search_results = unique_results
        
        logging.info(f"Total unique search results collected: {len(all_search_results)} for {original_product_name}")
        
        # Now find the best match from all results, using original product name for matching
        if all_search_results:
            # Log some sample results for debugging
            if len(all_search_results) > 0:
                logging.debug(f"Sample search results (first 3):")
                for i, result in enumerate(all_search_results[:3]):
                    logging.debug(f"  {i+1}. {result.title[:80]}... | {result.url[:80]}...")
            
            # Use original product name and all search queries for matching
            best_match = self.matcher.find_best_match(search_queries, all_search_results, original_product_name=original_product_name)
            
            if best_match:
                logging.info(f"✓ Found match: {best_match.title[:80]}... (Score: {best_match.score:.1f}%)")
                return ProcessingResult(
                    success=True,
                    url=best_match.url,
                    title=best_match.title,
                    retailer=best_match.retailer,
                    variant=best_match.variant,
                    score=best_match.score
                )
            else:
                logging.warning(f"No products matched the requirements for: {original_product_name} (searched {len(all_search_results)} results)")
        else:
            logging.warning(f"No search results found for any variant on {retailer} for: {original_product_name}")
        
        # Distinguish between "not found" (product doesn't exist on retailer) vs actual errors
        if all_search_results:
            # We had search results but none matched - product not found on retailer
            return ProcessingResult(success=False, error="NOT_FOUND")
        else:
            # No search results at all - could be search issue or product not available
            return ProcessingResult(success=False, error="NOT_FOUND")
    
    def process_multiple_excel_files(self, file_paths: List[str], output_suffix: str = "_results") -> None:
        """Process multiple Excel files and save results with suffix"""
        for input_file in file_paths:
            try:
                # Generate output filename
                base_name = os.path.splitext(input_file)[0]
                output_file = f"{base_name}{output_suffix}.xlsx"
                
                logging.info(f"Processing file: {input_file} -> {output_file}")
                self.process_excel_file(input_file, output_file)
                logging.info(f"Completed processing: {output_file}")
            except Exception as e:
                logging.error(f"Error processing file {input_file}: {e}")
                continue
    
    def _normalize_retailer_name(self, retailer: str) -> str:
        """
        Normalize retailer name to match configuration keys in RETAILERS dict.
        This function maps various retailer name formats from Excel sheets to the correct retailer key.
        To add support for a new retailer, add it to the RETAILERS dict and add a mapping here.
        """
        retailer_lower = retailer.lower().strip()
        
        # Remove common separators and normalize
        retailer_lower = retailer_lower.replace('-', ' ').replace('_', ' ').replace("'", '').replace("'s", '')
        
        # Map common variations to retailer keys (case-insensitive matching)
        # Amazon variants
        if 'amazon' in retailer_lower:
            if 'fresh' in retailer_lower:
                return 'amazon-fresh'
            elif 'au' in retailer_lower or 'australia' in retailer_lower:
                return 'amazon-au'
            else:
                return 'amazon'
        
        # Major US Retailers
        elif 'target' in retailer_lower:
            return 'target'
        elif 'walmart' in retailer_lower:
            return 'walmart'
        elif 'cvs' in retailer_lower:
            return 'cvs'
        elif 'walgreens' in retailer_lower:
            return 'walgreens'
        elif 'kroger' in retailer_lower:
            return 'kroger'
        elif 'albertsons' in retailer_lower:
            return 'albertsons'
        elif 'giant' in retailer_lower and 'eagle' in retailer_lower:
            return 'giant-eagle'
        elif 'gopuff' in retailer_lower or 'go puff' in retailer_lower:
            return 'gopuff'
        elif 'heb' in retailer_lower:
            return 'heb'
        elif 'hyvee' in retailer_lower or 'hy-vee' in retailer_lower or 'hy vee' in retailer_lower:
            return 'hyvee'
        elif 'instacart' in retailer_lower and 'publix' in retailer_lower:
            return 'instacart-publix'
        elif 'meijer' in retailer_lower:
            return 'meijer'
        elif 'staples' in retailer_lower:
            return 'staples'
        elif 'wegmans' in retailer_lower:
            return 'wegmans'
        elif 'bjs' in retailer_lower or 'bj' in retailer_lower:
            return 'bjs'
        elif 'sam' in retailer_lower and 'club' in retailer_lower:
            return 'sams-club'
        elif 'shoprite' in retailer_lower or 'shop rite' in retailer_lower:
            return 'shoprite'
        
        # Australian Retailers
        elif 'jb' in retailer_lower and 'hi' in retailer_lower:
            return 'jbhifi'
        elif 'harvey' in retailer_lower and 'norman' in retailer_lower:
            return 'harveynorman'
        elif 'costco' in retailer_lower:
            # Handle both "costco" and "costco-us"
            return 'costco'
        
        # If no match found, try direct lookup (for exact matches)
        if retailer_lower in RETAILERS:
            return retailer_lower
        
        # Log warning for unrecognized retailers
        logging.warning(f"Retailer '{retailer}' not recognized. Please add it to RETAILERS dict and _normalize_retailer_name function.")
        return None
    
    def _update_dataframe(self, df: pd.DataFrame, index: int, result: ProcessingResult) -> None:
        """Update dataframe with processing result"""
        if result.success:
            df.at[index, 'Found URL'] = result.url
            df.at[index, 'Found Title'] = result.title
            df.at[index, 'Matched Retailer'] = result.retailer
            df.at[index, 'Matched Variant'] = result.variant
            df.at[index, 'Match Score'] = result.score
            df.at[index, 'Status'] = 'SUCCESS'
        else:
            # Distinguish between NOT_FOUND and actual errors
            if result.error == "NOT_FOUND":
                df.at[index, 'Found URL'] = ""  # Ensure URL is empty for not found
                df.at[index, 'Found Title'] = ""
                df.at[index, 'Match Score'] = 0
                df.at[index, 'Status'] = 'NOT_FOUND'
            else:
                df.at[index, 'Found URL'] = ""  # Ensure URL is empty for errors
                df.at[index, 'Found Title'] = ""
                df.at[index, 'Match Score'] = 0
                df.at[index, 'Status'] = f'ERROR: {result.error}'

# ==================== COMMAND LINE INTERFACE ====================

def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description='Comprehensive Product URL Finder',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Process specific files
  python compre_produt.py --files COb-4759.xlsx COB-4816.xlsx
  
  # Process all Excel files in current directory
  python compre_produt.py --process-all
  
  # Process a single file
  python compre_produt.py --input file.xlsx --output results.xlsx
        """
    )
    
    input_group = parser.add_mutually_exclusive_group(required=False)
    input_group.add_argument('--input', '-i', help='Input Excel file path (requires --output)')
    input_group.add_argument('--process-all', action='store_true', help='Process all Excel files in current directory')
    input_group.add_argument('--files', nargs='+', help='Process specific Excel files (space-separated, e.g., --files file1.xlsx file2.xlsx)')
    
    parser.add_argument('--output', '-o', help='Output Excel file path (required if --input is used)')
    parser.add_argument('--sheet', '-s', help='Sheet name (if not specified, uses first sheet)')
    parser.add_argument('--headless', action='store_true', help='Run in headless mode (default: True)')
    parser.add_argument('--no-headless', action='store_true', help='Disable headless mode (show browser window)')
    parser.add_argument('--threshold', '-t', type=float, default=70, help='Fuzzy matching threshold (0-100, default: 70 for balanced accuracy and coverage)')
    parser.add_argument('--max-variants', type=int, default=8, help='Maximum number of variants to try')
    parser.add_argument('--delay', type=float, default=2.0, help='Delay between requests (seconds)')
    parser.add_argument('--verbose', '-v', action='store_true', help='Enable verbose logging')
    
    return parser.parse_args()

def main():
    """Main function"""
    args = parse_arguments()
    
    # Setup logging
    log_level = "DEBUG" if args.verbose else "INFO"
    setup_logging(log_level)
    
    # Create configuration
    config = DEFAULT_CONFIG.copy()
    # Headless mode: default is True, can be disabled with --no-headless
    if args.no_headless:
        config['headless'] = False
    elif args.headless:
        config['headless'] = True
    # Otherwise, keep the default from DEFAULT_CONFIG (which is True)
    config['fuzzy_threshold'] = args.threshold
    config['max_variants'] = args.max_variants
    config['request_delay'] = (args.delay * 0.5, args.delay * 1.5)
    
    # Create processor
    processor = ProductURLFinder(config)
    
    try:
        # Process multiple files if requested
        if args.process_all:
            # Find all Excel files in current directory
            current_dir = os.getcwd()
            excel_files = [f for f in os.listdir(current_dir) if f.endswith(('.xlsx', '.xls')) and not f.endswith('_results.xlsx')]
            if excel_files:
                logging.info(f"Found {len(excel_files)} Excel files to process: {excel_files}")
                processor.process_multiple_excel_files(excel_files)
            else:
                logging.warning("No Excel files found in current directory")
        elif args.files:
            # Process specific files
            processor.process_multiple_excel_files(args.files)
        elif args.input:
            # Process single file
            if not args.output:
                logging.error("--output is required when using --input")
                sys.exit(1)
            processor.process_excel_file(args.input, args.output, args.sheet)
        else:
            # No input specified - show usage
            logging.error("No input specified. Please use one of the following options:")
            logging.error("  --input <file> --output <file>  : Process a single file")
            logging.error("  --files <file1> <file2> ...     : Process multiple specific files")
            logging.error("  --process-all                   : Process all Excel files in current directory")
            sys.exit(1)
        
        logging.info("Processing completed successfully!")
    except Exception as e:
        logging.error(f"Processing failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()