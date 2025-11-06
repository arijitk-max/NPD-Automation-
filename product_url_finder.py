"""Universal product URL finder for multiple retailers.

This script reads an Excel tracker that contains product metadata (product name,
retailer, market, GTIN, etc.), searches the target retailer using Selenium, and
records the best matching product URL back into the file.

Key features
------------
* Supports Amazon marketplaces (US, CA, UK, MX) with automatic delivery
  location settings for the capital city of each market.
* Falls back to GTIN and product descriptions when ASINs are missing or look
  invalid.
* Extensible retailer framework – add new retailer clients by inheriting from
  `RetailerClient`.
* Fuzzy matching with heuristics for ASIN/GTIN, colour, size, and other
  attributes to avoid incorrect matches.

Usage example
-------------

```bash
pip install pandas selenium webdriver-manager rapidfuzz
python product_url_finder.py --excel /path/to/workbook.xlsx --sheet AMAZON --show-browser
```

The script updates (or creates) the columns `Status`, `URL`, `Found ASIN`, and
`Match Score` in-place.
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import quote_plus

import pandas as pd
from rapidfuzz import fuzz
from selenium import webdriver
from selenium.common.exceptions import (NoSuchElementException,
                                        TimeoutException, WebDriverException)
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.remote.webelement import WebElement
from webdriver_manager.chrome import ChromeDriverManager


# ---------------------------------------------------------------------------
# Data containers


@dataclass
class ProductRecord:
    index: int
    retailer: str
    market: str
    product_name: str
    gtin: str = ""
    asin: str = ""
    description: str = ""
    colour: str = ""
    size: str = ""


@dataclass
class SearchResult:
    title: str
    url: str
    source: str
    asin: Optional[str] = None
    score: float = 0.0


# ---------------------------------------------------------------------------
# Selenium driver management


class DriverManager:
    """Create and cache Chrome drivers per retailer key."""

    def __init__(self, show_browser: bool = False) -> None:
        self.show_browser = show_browser
        self._drivers: Dict[str, webdriver.Chrome] = {}

    def get(self, key: str) -> webdriver.Chrome:
        driver = self._drivers.get(key)
        if driver:
            return driver

        options = webdriver.ChromeOptions()
        if not self.show_browser:
            options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument(
            "--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        driver.set_page_load_timeout(30)

        self._drivers[key] = driver
        return driver

    def quit_all(self) -> None:
        for driver in self._drivers.values():
            try:
                driver.quit()
            except WebDriverException:
                pass
        self._drivers.clear()


# ---------------------------------------------------------------------------
# Retailer clients


class RetailerClient:
    """Base class that defines the interface for retailer search clients."""

    driver_key: str = "base"

    def __init__(self, driver_manager: DriverManager) -> None:
        self.driver_manager = driver_manager
        self._location_tokens: Dict[str, bool] = {}

    # Public API ----------------------------------------------------------

    def search(self, record: ProductRecord, search_terms: Sequence[str]) -> List[SearchResult]:
        driver = self.driver_manager.get(self.driver_key)
        self.ensure_location(driver, record.market)
        results: List[SearchResult] = []
        for term in search_terms:
            term = term.strip()
            if not term:
                continue
            results.extend(self._search_once(driver, term, record.market))
            if results:
                break  # Prefer the most specific term that returned results
        return results

    # Implementation hooks ------------------------------------------------

    def ensure_location(self, driver: webdriver.Chrome, market: str) -> None:
        """Override in subclasses if a delivery/location setting is required."""
        return None

    def _search_once(
        self, driver: webdriver.Chrome, term: str, market: str
    ) -> List[SearchResult]:
        raise NotImplementedError


class AmazonClient(RetailerClient):
    driver_key = "amazon"

    MARKET_CONFIG = {
        "US": {
            "base_url": "https://www.amazon.com",
            "zip": "10001",  # New York
            "language_param": "language=en_US",
        },
        "CA": {
            "base_url": "https://www.amazon.ca",
            "zip": "M5H 2N2",  # Toronto (financial district)
            "language_param": "language=en_CA",
        },
        "UK": {
            "base_url": "https://www.amazon.co.uk",
            "zip": "SW1A 1AA",  # London (Westminster)
            "language_param": "language=en_GB",
        },
        "MX": {
            "base_url": "https://www.amazon.com.mx",
            "zip": "01000",  # Ciudad de México
            "language_param": "language=es_MX",
        },
    }

    def ensure_location(self, driver: webdriver.Chrome, market: str) -> None:
        market = market.upper() or "US"
        if market in self._location_tokens:
            return

        config = self.MARKET_CONFIG.get(market)
        if not config:
            self._location_tokens[market] = True
            return

        base_url = config["base_url"]
        driver.get(base_url)
        time.sleep(2)

        try:
            link = driver.find_element(By.ID, "nav-global-location-popover-link")
            driver.execute_script("arguments[0].click();", link)
            time.sleep(1.5)

            zip_input = driver.find_element(By.ID, "GLUXZipUpdateInput")
            zip_input.clear()
            zip_input.send_keys(config["zip"])
            time.sleep(0.5)

            apply_btn = driver.find_element(By.ID, "GLUXZipUpdate")
            driver.execute_script("arguments[0].click();", apply_btn)
            time.sleep(2)
        except NoSuchElementException:
            # Fallback: store the preferred language/zip via cookies/localStorage
            try:
                host = base_url.split("//")[1].split("/")[0]
                domain = "." + "".join(host.split(".")[-2:])
                language_code = config["language_param"].split("=")[1]
                driver.execute_script(
                    """
                    document.cookie = arguments[0];
                    document.cookie = arguments[1];
                    localStorage.setItem('glow-zip', arguments[2]);
                    """,
                    f"lc-main=en_{market};domain={domain};path=/",
                    f"i18n-prefs={language_code};domain={domain};path=/",
                    config["zip"],
                )
            except WebDriverException:
                pass

        self._location_tokens[market] = True

    def _search_once(
        self, driver: webdriver.Chrome, term: str, market: str
    ) -> List[SearchResult]:
        market = market.upper() or "US"
        config = self.MARKET_CONFIG.get(market)
        if not config:
            return []

        base_url = config["base_url"]
        query = quote_plus(term)
        url = f"{base_url}/s?k={query}&{config['language_param']}"
        driver.get(url)
        time.sleep(random.uniform(1.5, 2.5))

        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div[data-asin]"))
            )
        except TimeoutException:
            return []

        results: List[SearchResult] = []
        elements = driver.find_elements(By.CSS_SELECTOR, "div[data-asin]")
        for element in elements:
            asin = element.get_attribute("data-asin") or ""
            if not asin or len(asin) != 10:
                continue

            try:
                title_span = element.find_element(By.CSS_SELECTOR, "h2 span")
                link = element.find_element(By.CSS_SELECTOR, "h2 a")
            except NoSuchElementException:
                continue

            title = title_span.text.strip()
            href = link.get_attribute("href")
            if not title or not href:
                continue

            clean_url = href.split("?")[0]
            results.append(
                SearchResult(
                    title=title,
                    url=clean_url,
                    source=f"Amazon {market}",
                    asin=asin.upper(),
                )
            )

            if len(results) >= 12:
                break

        return results


class WalmartClient(RetailerClient):
    driver_key = "walmart"

    BASE_URL = "https://www.walmart.com"
    DEFAULT_ZIP = "10001"  # New York

    def ensure_location(self, driver: webdriver.Chrome, market: str) -> None:
        if "US" in self._location_tokens:
            return

        driver.get(self.BASE_URL)
        time.sleep(2)
        try:
            driver.execute_script(
                "localStorage.setItem('storeZip', arguments[0]);", self.DEFAULT_ZIP
            )
            driver.execute_script(
                "localStorage.setItem('USStoreFinder.storeZipCode', arguments[0]);",
                self.DEFAULT_ZIP,
            )
            driver.execute_script(
                "document.cookie='store=NEWYORK;domain=.walmart.com;path=/';"
            )
        except WebDriverException:
            pass
        self._location_tokens["US"] = True

    def _search_once(
        self, driver: webdriver.Chrome, term: str, market: str
    ) -> List[SearchResult]:
        url = f"{self.BASE_URL}/search?q={quote_plus(term)}"
        driver.get(url)
        time.sleep(random.uniform(1.5, 2.5))

        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_all_elements_located(
                    (By.CSS_SELECTOR, "div[data-automation-id='productTile']")
                )
            )
        except TimeoutException:
            pass

        results: List[SearchResult] = []
        selectors = [
            "div[data-automation-id='productTile']",
            "div[data-item-id]",
            "div.search-result-gridview-item",
        ]

        elements: List[WebElement] = []
        for selector in selectors:
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
            if elements:
                break

        for element in elements:
            try:
                link = element.find_element(By.CSS_SELECTOR, "a[href]")
                title_elem = element.find_element(By.CSS_SELECTOR, "a span")
            except NoSuchElementException:
                continue

            title = title_elem.text.strip()
            href = link.get_attribute("href")
            if not title or not href:
                continue

            clean_url = href.split("?")[0]
            results.append(
                SearchResult(
                    title=title,
                    url=clean_url,
                    source="Walmart US",
                )
            )

            if len(results) >= 12:
                break

        return results


RETAILER_CLIENTS: Dict[Tuple[str, str], type[RetailerClient]] = {
    ("amazon", "US"): AmazonClient,
    ("amazon", "CA"): AmazonClient,
    ("amazon", "UK"): AmazonClient,
    ("amazon", "MX"): AmazonClient,
    ("walmart", "US"): WalmartClient,
}


# ---------------------------------------------------------------------------
# Matching heuristics


class ProductMatcher:
    def __init__(self, threshold: float = 70.0) -> None:
        self.threshold = threshold

    @staticmethod
    def _normalise(value: str) -> str:
        return " ".join(value.lower().strip().split())

    def score(self, record: ProductRecord, result: SearchResult) -> float:
        base = fuzz.token_set_ratio(record.product_name, result.title)

        bonus = 0
        penalty = 0

        if record.asin and result.asin and record.asin.upper() == result.asin.upper():
            bonus += 35

        if record.gtin and record.gtin in result.title:
            bonus += 20

        if record.colour:
            colour_tokens = [token for token in record.colour.lower().split() if len(token) > 2]
            for token in colour_tokens:
                if token in result.title.lower():
                    bonus += 5
                else:
                    penalty += 2

        if record.size and record.size.lower() not in result.title.lower():
            penalty += 5

        return base + bonus - penalty

    def select_best(self, record: ProductRecord, results: Iterable[SearchResult]) -> Optional[SearchResult]:
        best: Optional[SearchResult] = None
        best_score = 0.0
        for result in results:
            score = self.score(record, result)
            if score > best_score and score >= self.threshold:
                best_score = score
                result.score = score
                best = result
        return best


# ---------------------------------------------------------------------------
# Main verifier workflow


class ProductURLFinder:
    def __init__(
        self,
        excel_path: Path,
        sheet: Optional[str] = None,
        show_browser: bool = False,
        threshold: float = 70.0,
    ) -> None:
        self.excel_path = excel_path
        self.sheet_name = sheet
        self.show_browser = show_browser
        self.matcher = ProductMatcher(threshold=threshold)
        self.driver_manager = DriverManager(show_browser=show_browser)

        self.df = (
            pd.read_excel(excel_path, sheet_name=sheet)
            if sheet is not None
            else pd.read_excel(excel_path)
        )

        for column in ["Status", "URL", "Found ASIN", "Match Score"]:
            if column not in self.df.columns:
                self.df[column] = ""

    # High-level ---------------------------------------------------------

    def run(self) -> None:
        try:
            for idx, row in self.df.iterrows():
                record = self._build_record(idx, row)
                if not record.retailer or not record.product_name:
                    self._mark_error(idx, "Missing retailer or product name")
                    continue

                client = self._resolve_client(record.retailer, record.market)
                if client is None:
                    self._mark_error(idx, f"Unsupported retailer/market: {record.retailer}/{record.market}")
                    continue

                search_terms = self._build_search_terms(record, row)
                try:
                    results = client.search(record, search_terms)
                except Exception as exc:  # noqa: BLE001
                    self._mark_error(idx, f"Search failed: {exc}")
                    continue

                best = self.matcher.select_best(record, results)
                if best:
                    self.df.at[idx, "Status"] = "Found"
                    self.df.at[idx, "URL"] = best.url
                    self.df.at[idx, "Found ASIN"] = best.asin or ""
                    self.df.at[idx, "Match Score"] = round(best.score, 1)
                else:
                    self._mark_error(idx, "Not found")

                if idx % 5 == 0:
                    self._save_progress()
                time.sleep(random.uniform(1.0, 2.0))
        finally:
            self._save_progress()
            self.driver_manager.quit_all()

    # Internal helpers ---------------------------------------------------

    def _build_record(self, index: int, row: pd.Series) -> ProductRecord:
        retailer = self._clean_cell(row.get("Retailer"))
        market = self._clean_cell(row.get("Market")) or "US"
        name = self._clean_cell(row.get("Product Name"))

        asin = self._clean_cell(row.get("ASIN"))
        if asin and len(asin) != 10:
            asin = ""

        record = ProductRecord(
            index=index,
            retailer=retailer,
            market=market.upper(),
            product_name=name,
            gtin=self._clean_cell(row.get("GTIN")),
            asin=asin,
            description=self._clean_cell(row.get("Desc", row.get("Description"))),
            colour=self._clean_cell(row.get("Colour", row.get("Color"))),
            size=self._clean_cell(row.get("Size")),
        )
        return record

    def _build_search_terms(self, record: ProductRecord, row: pd.Series) -> List[str]:
        terms: List[str] = []

        if record.asin:
            terms.append(record.asin)

        terms.append(record.product_name)

        if record.gtin and record.gtin not in terms:
            terms.append(record.gtin)

        for column in ["Desc", "Description", "Short Description", "Alt Name", "Product Description"]:
            value = self._clean_cell(row.get(column))
            if value and value not in terms:
                terms.append(value)

        return terms

    @staticmethod
    def _clean_cell(value: object) -> str:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return ""
        if isinstance(value, str):
            value = value.strip()
            return "" if value.lower() == "nan" else value
        return str(value).strip()

    def _resolve_client(self, retailer: str, market: str) -> Optional[RetailerClient]:
        key = (retailer.lower(), market.upper())
        client_cls = RETAILER_CLIENTS.get(key)
        if not client_cls:
            # If no specific market entry, try retailer-only fallback
            client_cls = RETAILER_CLIENTS.get((retailer.lower(), "US"))
        if not client_cls:
            return None
        return client_cls(self.driver_manager)

    def _mark_error(self, idx: int, message: str) -> None:
        self.df.at[idx, "Status"] = message
        self.df.at[idx, "URL"] = ""
        self.df.at[idx, "Found ASIN"] = ""
        self.df.at[idx, "Match Score"] = ""

    def _save_progress(self) -> None:
        self.df.to_excel(self.excel_path, sheet_name=self.sheet_name, index=False)


# ---------------------------------------------------------------------------
# CLI utilities


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Find product URLs on retailer sites")
    parser.add_argument("--excel", required=True, help="Path to the Excel tracker")
    parser.add_argument("--sheet", help="Optional sheet name to process")
    parser.add_argument("--threshold", type=float, default=70.0, help="Match score threshold")
    parser.add_argument("--show-browser", action="store_true", help="Disable headless mode")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = parse_args(argv)
    excel_path = Path(args.excel).expanduser().resolve()
    if not excel_path.exists():
        print(f"Excel file not found: {excel_path}", file=sys.stderr)
        sys.exit(1)

    finder = ProductURLFinder(
        excel_path=excel_path,
        sheet=args.sheet,
        show_browser=args.show_browser,
        threshold=args.threshold,
    )
    finder.run()


if __name__ == "__main__":
    main()
