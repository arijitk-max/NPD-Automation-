#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Comprehensive Product URL Finder

Updates:
    * Adds manual CAPTCHA handling so you can solve retailer challenges yourself
      (particularly on Harvey Norman) and resume scraping automatically.
    * Tightens product matching so only URLs whose product titles match the input
      product name (after normalization) are returned. Multiple matches are kept.
    * Keeps track of all scraped results for auditing while only persisting
      exact matches back to the Excel workbook.
    * Supports multiple retailer markets per row (Amazon AU/US, Walmart US, Target US,
      JB Hi-Fi, Harvey Norman) by reading the Retailer/Market columns in each tracker.

Usage:
    python comprehensive_product_finder.py --input input.xlsx --output results.xlsx [options]
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote_plus, urlparse

import pandas as pd
from rapidfuzz import fuzz
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

DEFAULT_CONFIG: Dict[str, object] = {
    "headless": True,
    "page_load_timeout": 30,
    "request_delay_seconds": (1.5, 3.5),
    "strict_match_threshold": 92,
    "allow_manual_captcha": True,
    "captcha_max_attempts": 3,
    "captcha_poll_delay": 4,
    "max_results_per_retailer": 5,
    "save_interval": 5,
    "user_agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}

RETAILERS: Dict[str, Dict[str, object]] = {
    # Amazon variants share selectors; host is injected per-market.
    "amazon": {
        "host": "www.amazon.com.au",
        "search_urls": ["https://{host}/s?k={query}"],
        "result_selector": "div[data-component-type='s-search-result']",
        "title_selector": "h2 a span",
        "link_selector": "h2 a",
        "sponsored_markers": ["sponsored", "ad", "advertisement"],
    },
    "jbhifi": {
        "domains": ["jbhifi.com.au"],
        "search_urls": [
            "https://www.jbhifi.com.au/search/?q={query}",
            "https://www.jbhifi.com.au/search?q={query}",
        ],
        "result_selector": ".product-tile, .product-item, .ProductTile, [data-product-id], li.product",
        "title_selector": ".product-title, .product-name, h2, h3, a.product-title",
        "link_selector": "a[href*='/product'], a[href*='/products']",
        "sponsored_markers": [],
    },
    "harveynorman": {
        "domains": ["harveynorman.com.au"],
        "search_urls": [
            "https://www.harveynorman.com.au/catalogsearch/result/?q={query}",
            "https://www.harveynorman.com.au/search?q={query}",
        ],
        "result_selector": ".product-item, .product, .product-tile, li.item, [data-product]",
        "title_selector": ".product-name, .product-title, h2, h3",
        "link_selector": "a[href*='/product']",
        "sponsored_markers": [],
    },
    "walmart_us": {
        "host": "www.walmart.com",
        "search_urls": ["https://{host}/search?q={query}"],
        "result_selector": "div.search-result-gridview-item-wrapper, div[data-automation-id='search-result-gridview-item'], div[data-item-id]",
        "title_selector": "a.product-title-link span, a[data-automation-id='product-title'] span, a[data-testid='product-title'] span",
        "link_selector": "a.product-title-link, a[data-automation-id='product-title'], a[data-testid='product-title']",
        "sponsored_markers": ["sponsored"],
    },
    "target_us": {
        "host": "www.target.com",
        "search_urls": ["https://{host}/s?searchTerm={query}"],
        "result_selector": "[data-test='product-card'], [data-test='productGrid'] [data-test='productCard']",
        "title_selector": "[data-test='product-title'], a[data-test='product-title']",
        "link_selector": "a[data-test='product-title']",
        "sponsored_markers": ["sponsored"],
    },
}


# -------------------------------------------------------------------------------------- #
# Helper utilities
# -------------------------------------------------------------------------------------- #


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def normalize_text(value: str) -> str:
    if not value:
        return ""
    cleaned = re.sub(r"[^\w\s]", " ", value.lower())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def clean_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


def random_delay(range_seconds: Tuple[float, float]) -> None:
    low, high = range_seconds
    time.sleep(random.uniform(low, high))


@dataclass
class SearchResult:
    url: str
    title: str
    retailer: str
    score: float = 0.0
    meta: Dict[str, str] = field(default_factory=dict)


@dataclass
class ProcessingResult:
    success: bool
    matches: List[SearchResult] = field(default_factory=list)
    all_results: List[SearchResult] = field(default_factory=list)
    message: str = ""


# -------------------------------------------------------------------------------------- #
# Selenium helpers
# -------------------------------------------------------------------------------------- #


class RetailerSearcher:
    """Encapsulates Selenium logic for retailer searches."""

    def __init__(self, config: Dict[str, object]):
        self.config = config
        self.driver = self._setup_driver()
        self.amazon_hosts_initialized: set[str] = set()

    # --------------------------- driver management ---------------------------------- #

    def _setup_driver(self) -> webdriver.Chrome:
        options = Options()
        if self.config.get("headless", True):
            options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-infobars")
        options.add_argument("--window-size=1920,1080")
        options.add_argument(f"--user-agent={self.config['user_agent']}")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

        prefs = {
            "credentials_enable_service": False,
            "profile.password_manager_enabled": False,
        }
        options.add_experimental_option("prefs", prefs)

        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        driver.set_page_load_timeout(int(self.config["page_load_timeout"]))
        return driver

    def close(self) -> None:
        try:
            if self.driver:
                self.driver.quit()
        except WebDriverException:
            pass

    # ------------------------------ captcha flow ----------------------------------- #

    def _detect_blockers(self) -> bool:
        """Return True if current page looks like a captcha / access denied."""
        try:
            body_text = self.driver.find_element(By.TAG_NAME, "body").text.lower()
        except Exception:
            body_text = ""
        page_source = ""
        try:
            page_source = self.driver.page_source.lower()
        except Exception:
            pass
        page_title = self.driver.title.lower() if self.driver.title else ""

        indicators = [
            "captcha",
            "verify you are human",
            "verification required",
            "access denied",
            "blocked",
            "not a robot",
            "unusual traffic",
            "imperva",
            "hcaptcha",
            "cloudflare",
        ]

        return any(
            indicator in body_text or indicator in page_source or indicator in page_title
            for indicator in indicators
        )

    def _wait_for_manual_captcha(self, retailer: str) -> bool:
        """Offer user a chance to solve captcha manually."""
        if not self.config.get("allow_manual_captcha", True):
            logging.warning("Manual CAPTCHA handling disabled. Skipping retailer %s.", retailer)
            return False

        if self.config.get("headless", True):
            logging.error(
                "CAPTCHA detected on %s while running headless. Re-run with --no-headless to solve it manually.",
                retailer,
            )
            return False

        attempts = int(self.config.get("captcha_max_attempts", 3))
        for attempt in range(1, attempts + 1):
            logging.warning(
                "CAPTCHA detected on %s. Solve it in the browser window, then press Enter "
                "(attempt %s/%s, or type 'skip' to bypass).",
                retailer,
                attempt,
                attempts,
            )
            try:
                user_input = input().strip().lower()
            except EOFError:
                user_input = ""

            if user_input == "skip":
                logging.warning("User skipped CAPTCHA for %s.", retailer)
                return False

            time.sleep(float(self.config.get("captcha_poll_delay", 4)))
            if not self._detect_blockers():
                logging.info("CAPTCHA cleared for %s.", retailer)
                return True

        logging.error("CAPTCHA still active after manual attempts on %s.", retailer)
        return False

    def _ensure_page_ready(self, retailer: str) -> bool:
        if self._detect_blockers():
            return self._wait_for_manual_captcha(retailer)
        return True

    # ------------------------------ extraction ------------------------------------- #

    def _prepare_amazon_au(self, host: str) -> None:
        """Best-effort location priming for Amazon AU hosts."""
        base_url = f"https://{host}/"
        logging.info("Preparing Amazon AU context for host %s", host)
        try:
            self.driver.get(base_url)
            time.sleep(1.5)
        except Exception as exc:
            logging.debug("Failed opening Amazon base page for %s: %s", host, exc)
            return

        # Attempt lightweight postcode update; ignore failures.
        try:
            self.driver.execute_script(
                """
                try {
                    fetch('https://%s/gp/delivery/ajax/address-change.html', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                        body: 'locationType=LOCATION_INPUT&zipCode=2000&storeContext=generic&deviceType=web&pageType=Detail&actionSource=glow',
                        credentials: 'include'
                    }).catch(() => {});
                } catch (e) {}
                """
                % host
            )
            time.sleep(1.0)
            self.driver.refresh()
            time.sleep(1.0)
        except Exception:
            pass

    def search_retailer(
        self, retailer: str, query: str, overrides: Optional[Dict[str, object]] = None
    ) -> List[SearchResult]:
        if retailer not in RETAILERS:
            logging.warning("Retailer %s is not configured.", retailer)
            return []

        base_config = RETAILERS[retailer]
        config = dict(base_config)
        if overrides:
            config.update(overrides)

        results: List[SearchResult] = []

        host = config.get("host")
        search_templates = config.get("search_urls", [])

        if not search_templates:
            logging.warning("No search URLs configured for %s.", retailer)
            return results

        for search_template in search_templates:
            url = search_template.format(query=quote_plus(query), host=host) if "{host}" in search_template else search_template.format(query=quote_plus(query))
            logging.info("Searching %s with query '%s' -> %s", retailer, query, url)

            try:
                random_delay(tuple(self.config["request_delay_seconds"]))
                self.driver.get(url)
            except TimeoutException:
                logging.warning("Timed out loading %s search page.", retailer)
                continue

            if retailer == "amazon":
                if host and host.endswith(".com.au") and host not in self.amazon_hosts_initialized:
                    self._prepare_amazon_au(host)
                    self.amazon_hosts_initialized.add(host)

            if not self._ensure_page_ready(retailer):
                logging.warning("Skipping %s due to unresolved CAPTCHA.", retailer)
                continue

            # Wait for results (or "no results" text).
            try:
                WebDriverWait(self.driver, 10).until(
                    lambda drv: drv.find_elements(By.CSS_SELECTOR, config["result_selector"])
                    or "no results" in drv.page_source.lower()
                )
            except TimeoutException:
                logging.debug("Result wait timed out for %s.", retailer)

            extracted = self._extract_results(retailer, config)
            results.extend(extracted)

            if extracted:
                break  # Use first successful search page

        # Deduplicate by URL
        seen_urls = set()
        unique_results: List[SearchResult] = []
        for result in results:
            if result.url not in seen_urls:
                seen_urls.add(result.url)
                unique_results.append(result)

        max_results = int(self.config["max_results_per_retailer"])
        trimmed_results = unique_results[:max_results]
        logging.info("Collected %s results for %s.", len(trimmed_results), retailer)
        return trimmed_results

    def _extract_results(self, retailer: str, retailer_config: Dict[str, object]) -> List[SearchResult]:
        results: List[SearchResult] = []
        elements = self.driver.find_elements(By.CSS_SELECTOR, retailer_config["result_selector"])

        if not elements:
            logging.debug("No result elements found on %s.", retailer)
            return results

        host = retailer_config.get("host", "")

        for element in elements:
            try:
                title = ""
                link = ""

                # Extract link and title
                link_candidates = element.find_elements(By.CSS_SELECTOR, retailer_config["link_selector"])
                for candidate in link_candidates:
                    link = candidate.get_attribute("href") or ""
                    if link:
                        title = candidate.text.strip() or title
                        break

                if not link:
                    link_tags = element.find_elements(By.TAG_NAME, "a")
                    for tag in link_tags:
                        href = tag.get_attribute("href") or ""
                        if "/dp/" in href or "/product" in href or "/products" in href:
                            link = href
                            title = tag.text.strip() or element.text.strip()
                            break

                if not link or not title:
                    continue

                url = clean_url(link)
                title = title.strip() or element.text.strip()
                if not title:
                    continue

                # Skip sponsored results when possible
                element_text = element.text.lower()
                if any(marker in element_text for marker in retailer_config["sponsored_markers"]):
                    continue

                metadata = {"host": host} if host else {}
                results.append(SearchResult(url=url, title=title, retailer=retailer, meta=metadata))
            except NoSuchElementException:
                continue
            except Exception as exc:
                logging.debug("Failed extracting element on %s: %s", retailer, exc)
                continue

        return results


# -------------------------------------------------------------------------------------- #
# Matching logic
# -------------------------------------------------------------------------------------- #


class ProductMatcher:
    def __init__(self, config: Dict[str, object], driver: Optional[webdriver.Chrome] = None):
        self.config = config
        self.driver = driver

    def _fetch_full_title(self, result: SearchResult) -> Optional[str]:
        if not self.driver:
            return None

        try:
            self.driver.get(result.url)
            wait = WebDriverWait(self.driver, 10)

            if result.retailer == "amazon":
                selectors = ["#productTitle", "span#productTitle", "h1.a-size-large"]
            elif result.retailer == "jbhifi":
                selectors = ["h1.product-title", "h1", ".product-title"]
            elif result.retailer == "harveynorman":
                selectors = ["h1", ".product-name", ".product-title"]
            elif result.retailer == "walmart_us":
                selectors = [
                    "h1.prod-ProductTitle div",
                    "h1[data-automation-id='product-title']",
                    "[data-testid='product-title']",
                ]
            elif result.retailer == "target_us":
                selectors = [
                    "h1[data-test='product-title']",
                    "h1[data-test='productTitle']",
                    "h1",
                ]
            else:
                selectors = ["h1", ".product-title", ".product-name"]

            for selector in selectors:
                try:
                    element = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
                    text = element.text.strip()
                    if text:
                        return text
                except TimeoutException:
                    continue

            # As a fallback use meta title
            return self.driver.title
        except Exception as exc:
            logging.debug("Failed fetching full title for %s: %s", result.url, exc)
            return None

    def _score_candidate(self, target_norm: str, candidate_norm: str) -> float:
        if not candidate_norm:
            return 0.0
        if candidate_norm == target_norm:
            return 100.0
        return float(fuzz.token_sort_ratio(candidate_norm, target_norm))

    def find_exact_matches(self, product_name: str, results: List[SearchResult]) -> List[SearchResult]:
        target_norm = normalize_text(product_name)
        threshold = float(self.config.get("strict_match_threshold", 92))

        matches: List[SearchResult] = []
        for result in results:
            candidate_norm = normalize_text(result.title)
            score = self._score_candidate(target_norm, candidate_norm)

            if score < threshold and self.driver:
                full_title = self._fetch_full_title(result)
                full_norm = normalize_text(full_title) if full_title else ""
                score = max(score, self._score_candidate(target_norm, full_norm))
                if full_title:
                    result.meta["full_title"] = full_title

            result.score = score

            if score >= threshold:
                matches.append(result)

        matches.sort(key=lambda r: r.score, reverse=True)
        return matches


# -------------------------------------------------------------------------------------- #
# Orchestrator
# -------------------------------------------------------------------------------------- #


class ProductURLFinder:
    def __init__(self, config: Dict[str, object]):
        self.config = config
        self.retailer_searcher = RetailerSearcher(config)
        self.matcher = ProductMatcher(config, driver=self.retailer_searcher.driver)

    def close(self) -> None:
        self.retailer_searcher.close()

    def process_excel_file(self, input_path: str, output_path: str, sheet_name: Optional[str] = None) -> None:
        if sheet_name:
            df = pd.read_excel(input_path, sheet_name=sheet_name)
        else:
            df = pd.read_excel(input_path)

        required_columns = ["Product Name", "Retailer"]
        for column in required_columns:
            if column not in df.columns:
                raise ValueError(f"Missing required column '{column}' in Excel file.")

        output_columns = [
            "Found URL",
            "Found Title",
            "Matched Retailer",
            "Match Score",
            "Matching URLs",
            "All Scraped Results",
            "Status",
        ]
        for column in output_columns:
            if column not in df.columns:
                df[column] = ""

        try:
            for index, row in df.iterrows():
                product_name = str(row["Product Name"]).strip()
                retailer_value = str(row["Retailer"]).strip()
                market_value = ""
                if "Market" in row.index and pd.notna(row["Market"]):
                    market_value = str(row["Market"]).strip()

                retailer_key, overrides = self._normalize_retailer(retailer_value, market_value)

                if not retailer_key:
                    logging.warning(
                        "Row %s: Unsupported retailer '%s' (market: '%s').",
                        index + 1,
                        retailer_value,
                        market_value,
                    )
                    result = ProcessingResult(
                        success=False,
                        matches=[],
                        all_results=[],
                        message=f"Unsupported retailer '{retailer_value}'",
                    )
                else:
                    logging.info("Processing row %s: %s (%s)", index + 1, product_name, retailer_key)
                    result = self._process_product(product_name, retailer_key, overrides)

                self._update_dataframe(df, index, result)

                if (index + 1) % int(self.config["save_interval"]) == 0:
                    df.to_excel(output_path, index=False)
                    logging.info("Progress saved after %s rows.", index + 1)

            df.to_excel(output_path, index=False)
            logging.info("Results saved to %s.", output_path)
        finally:
            self.close()

    def _process_product(
        self,
        product_name: str,
        retailer: str,
        overrides: Optional[Dict[str, object]] = None,
    ) -> ProcessingResult:
        if not product_name:
            return ProcessingResult(success=False, message="Empty product name.")
        if retailer not in RETAILERS:
            return ProcessingResult(success=False, message=f"Unsupported retailer '{retailer}'.")

        try:
            raw_results = self.retailer_searcher.search_retailer(retailer, product_name, overrides)
        except Exception as exc:
            logging.error("Search failure on %s: %s", retailer, exc)
            return ProcessingResult(success=False, message=str(exc))

        if not raw_results:
            return ProcessingResult(success=False, message="No results returned for search.", all_results=[])

        matches = self.matcher.find_exact_matches(product_name, raw_results)
        if not matches:
            return ProcessingResult(
                success=False,
                matches=[],
                all_results=raw_results,
                message="No strict matches for product title.",
            )

        return ProcessingResult(success=True, matches=matches, all_results=raw_results, message="Match found.")

    def _update_dataframe(self, df: pd.DataFrame, index: int, result: ProcessingResult) -> None:
        df.at[index, "Status"] = "SUCCESS" if result.success else f"ERROR: {result.message}"

        if not result.matches:
            df.at[index, "Found URL"] = ""
            df.at[index, "Found Title"] = ""
            df.at[index, "Matched Retailer"] = ""
            df.at[index, "Match Score"] = ""
            df.at[index, "Matching URLs"] = ""
        else:
            best = result.matches[0]
            df.at[index, "Found URL"] = best.url
            df.at[index, "Found Title"] = best.meta.get("full_title", best.title)
            df.at[index, "Matched Retailer"] = best.meta.get("host", best.retailer)
            df.at[index, "Match Score"] = f"{best.score:.1f}"
            df.at[index, "Matching URLs"] = "\n".join(
                f"{match.url} | {match.meta.get('full_title', match.title)} | {match.score:.1f}"
                for match in result.matches
            )

        # Persist all scraped results for audit
        serialisable_results = []
        for item in result.all_results:
            serialisable_results.append(
                {
                    "url": item.url,
                    "title": item.title,
                    "retailer": item.retailer,
                    "host": item.meta.get("host", ""),
                    "score": f"{item.score:.1f}",
                }
            )
        df.at[index, "All Scraped Results"] = json.dumps(serialisable_results)

    @staticmethod
    def _normalize_retailer(retailer: str, market: str = "") -> Tuple[Optional[str], Dict[str, object]]:
        combined = f"{retailer} {market}"
        tokens = [token for token in re.split(r"[\s\-\_/|,\.\(\)]+", combined.lower()) if token and token != "nan"]
        token_set = set(tokens)
        overrides: Dict[str, object] = {}

        if "amazon" in token_set:
            host = "www.amazon.com"
            if token_set & {"au", "aus", "australia"}:
                host = "www.amazon.com.au"
            elif token_set & {"ca", "canada"}:
                host = "www.amazon.ca"
            elif token_set & {"uk", "co", "gb", "united", "kingdom"}:
                host = "www.amazon.co.uk"
            overrides["host"] = host
            return "amazon", overrides

        if "walmart" in token_set:
            overrides["host"] = "www.walmart.com"
            return "walmart_us", overrides

        if "target" in token_set:
            overrides["host"] = "www.target.com"
            return "target_us", overrides

        if "jb" in token_set and "hi" in token_set:
            return "jbhifi", overrides

        if "harvey" in token_set and "norman" in token_set:
            return "harveynorman", overrides

        return None, overrides


# -------------------------------------------------------------------------------------- #
# Command line interface
# -------------------------------------------------------------------------------------- #


def parse_arguments(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Comprehensive Product URL Finder")
    parser.add_argument("--input", "-i", required=True, help="Input Excel file path.")
    parser.add_argument("--output", "-o", required=True, help="Output Excel file path.")
    parser.add_argument("--sheet", "-s", help="Optional sheet name.")
    parser.add_argument("--no-headless", action="store_true", help="Run Chrome in visible mode.")
    parser.add_argument(
        "--strict-threshold",
        type=float,
        default=DEFAULT_CONFIG["strict_match_threshold"],
        help="Minimum score (0-100) for accepting a match.",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging.")
    parser.add_argument(
        "--disable-manual-captcha",
        action="store_true",
        help="Disable manual CAPTCHA prompts (useful for fully automated pipelines).",
    )
    return parser.parse_args(argv)


def build_config_from_args(args: argparse.Namespace) -> Dict[str, object]:
    config = DEFAULT_CONFIG.copy()
    config["headless"] = not args.no_headless
    config["strict_match_threshold"] = args.strict_threshold
    config["allow_manual_captcha"] = not args.disable_manual_captcha

    if args.no_headless:
        logging.info("Running with visible browser windows (headless disabled).")

    if args.disable_manual_captcha:
        logging.info("Manual CAPTCHA prompts disabled.")

    return config


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_arguments(argv)
    setup_logging("DEBUG" if args.verbose else "INFO")

    if not os.path.exists(args.input):
        logging.error("Input file does not exist: %s", args.input)
        return 1

    config = build_config_from_args(args)

    finder = ProductURLFinder(config)
    try:
        finder.process_excel_file(args.input, args.output, sheet_name=args.sheet)
    except Exception as exc:
        logging.exception("Processing failed: %s", exc)
        return 1
    finally:
        finder.close()

    logging.info("Processing completed successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

