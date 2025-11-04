import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import time
import random
from urllib.parse import quote_plus, urljoin


class ProductVerifier:
    """Verify Amazon product URLs from an Excel tracker."""

    def __init__(self, excel_path, sheet_name=None):
        self.excel_path = excel_path
        self.sheet_name = sheet_name
        self.df = (
            pd.read_excel(excel_path, sheet_name=sheet_name)
            if sheet_name is not None
            else pd.read_excel(excel_path)
        )

        for column in ["URL", "Status", "Found ASIN"]:
            if column not in self.df.columns:
                self.df[column] = ""
        self.df["URL"] = self.df["URL"].astype(str)
        self.df["Status"] = self.df["Status"].astype(str)
        self.df["Found ASIN"] = self.df["Found ASIN"].astype(str)

        # Determine which columns contain ASINs and product names
        self.asin_column = self._pick_first_existing(
            ["ASIN", "Asin", "asin", "Product ASIN"]
        )
        if self.asin_column is None and "Product Name" in self.df.columns:
            # Legacy trackers stored ASINs in Product Name
            self.asin_column = "Product Name"

        self.name_column = self._pick_first_existing(
            ["Product Name", "Name", "Title", "Product"]
        )

        # Define base URLs for different Amazon marketplaces
        self.retailer_urls = {
            "Amazon": {
                "CA": "https://www.amazon.ca",
                "US": "https://www.amazon.com",
                "UK": "https://www.amazon.co.uk",
                "MX": "https://www.amazon.com.mx",
            }
        }

        # User agents for rotation
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) Version/16.5 Safari/605.1.15",
        ]

    # ------------------------------------------------------------------
    # Helpers
    def _pick_first_existing(self, candidates):
        for column in candidates:
            if column in self.df.columns:
                return column
        return None

    @staticmethod
    def _clean_cell(value):
        if pd.isna(value):
            return ""
        return str(value).strip()

    @staticmethod
    def _normalise_asin(candidate):
        candidate = ProductVerifier._clean_cell(candidate).upper()
        if len(candidate) == 10 and candidate.isalnum():
            return candidate
        return ""

    def _build_search_terms(self, row, asin):
        terms = []
        if asin:
            terms.append(asin)

        if self.name_column is not None:
            name_value = self._clean_cell(row.get(self.name_column, ""))
            if name_value and name_value != asin:
                terms.append(name_value)

        gtin_value = self._clean_cell(row.get("GTIN", ""))
        if gtin_value and gtin_value not in terms:
            terms.append(gtin_value)

        return terms

    @staticmethod
    def _extract_product_link(result, base_url, asin):
        link = None
        for selector in [
            "a.a-link-normal.s-no-outline",
            "a.a-link-normal[href*='/dp/']",
            "a[href*='/dp/']",
        ]:
            try:
                link = result.find_element(By.CSS_SELECTOR, selector)
                if link:
                    break
            except NoSuchElementException:
                continue

        if link:
            href = link.get_attribute("href")
            if href:
                return href.split("?")[0]

        if asin:
            return urljoin(base_url, f"/dp/{asin}")
        return None

    @staticmethod
    def _extract_title(result):
        for selector in [
            "span.a-size-medium",
            "span.a-size-base-plus",
            "h2 a span",
        ]:
            try:
                text = result.find_element(By.CSS_SELECTOR, selector).text.strip()
                if text:
                    return text
            except NoSuchElementException:
                continue
        return ""

    # ------------------------------------------------------------------
    # Selenium setup
    def setup_driver(self):
        """Initialize headless Chrome with anti-detection measures."""
        options = webdriver.ChromeOptions()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument(f"--user-agent={random.choice(self.user_agents)}")
        service = Service(ChromeDriverManager().install())
        return webdriver.Chrome(service=service, options=options)

    # ------------------------------------------------------------------
    # Verification routines
    def direct_asin_check(self, driver, asin, base_url):
        """Try to access the product directly using the ASIN."""
        try:
            direct_url = f"{base_url}/dp/{asin}"
            driver.get(direct_url)
            time.sleep(random.uniform(2, 3))

            WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.ID, "productTitle"))
            )
            print(f"✓ Found via direct ASIN {asin}.")
            return direct_url, f"Found via ASIN {asin}", asin
        except TimeoutException:
            return None, "Product title not found", asin
        except Exception as exc:  # noqa: BLE001
            print(f"Direct lookup error for {asin}: {exc}")
            return None, "Direct lookup error", asin

    def search_results_check(self, driver, base_url, search_term, target_asin=None):
        """Search for the product using a term and optionally match a target ASIN."""
        try:
            search_url = f"{base_url}/s?k={quote_plus(search_term)}"
            driver.get(search_url)
            time.sleep(random.uniform(2, 3))

            results = WebDriverWait(driver, 10).until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div[data-asin]"))
            )

            valid_results = [r for r in results if self._normalise_asin(r.get_attribute("data-asin"))]

            def iterate(candidates, allow_any=False):
                for result in candidates:
                    result_asin = self._normalise_asin(result.get_attribute("data-asin"))
                    if not result_asin:
                        continue
                    if target_asin and not allow_any and result_asin != target_asin:
                        continue
                    link = self._extract_product_link(result, base_url, result_asin)
                    if not link:
                        continue
                    title = self._extract_title(result)
                    status = f"Found via search term '{search_term}'"
                    return link, status, result_asin, title
                return None

            # Prefer matches to the expected ASIN
            matched = iterate(valid_results)
            if matched:
                return matched

            # If no explicit ASIN match, allow the top result
            fallback = iterate(valid_results, allow_any=True)
            if fallback:
                return fallback

            return None, f"No results for '{search_term}'", target_asin, ""
        except TimeoutException:
            return None, f"Search timed out for '{search_term}'", target_asin, ""
        except Exception as exc:  # noqa: BLE001
            print(f"Search error for '{search_term}': {exc}")
            return None, f"Search error for '{search_term}'", target_asin, ""

    def verify_product(self, driver, asin, search_terms, retailer, market):
        base_url = self.retailer_urls.get(retailer, {}).get(market)
        if not base_url:
            return None, f"Unsupported retailer/market: {retailer}/{market}", asin

        print(f"\nChecking retailer={retailer}, market={market}, asin='{asin}'...")

        # Try direct ASIN lookup first if we have a valid ASIN
        if asin:
            url, status, found_asin = self.direct_asin_check(driver, asin, base_url)
            if url:
                return url, status, found_asin
            print("Direct lookup failed, moving to search.")

        # Try search terms in order (asin, product name, gtin...)
        for term in search_terms:
            url, status, found_asin, _ = self.search_results_check(
                driver,
                base_url,
                term,
                target_asin=asin if asin else None,
            )
            if url:
                return url, status, found_asin

        return None, "Not found on retailer", asin

    # ------------------------------------------------------------------
    # Main loop
    def verify_products(self):
        driver = None
        try:
            driver = self.setup_driver()
            total = len(self.df)
            max_retries = 3

            for index, row in self.df.iterrows():
                asin_candidate = (
                    self._clean_cell(row[self.asin_column])
                    if self.asin_column is not None
                    else ""
                )
                asin = self._normalise_asin(asin_candidate)
                search_terms = self._build_search_terms(row, asin)
                if not search_terms:
                    print(f"Row {index + 1}: no search terms available; skipping.")
                    self.df.at[index, "Status"] = "No identifier provided"
                    self.df.at[index, "URL"] = ""
                    self.df.at[index, "Found ASIN"] = ""
                    continue

                retailer = self._clean_cell(row.get("Retailer", "Amazon")) or "Amazon"
                market = self._clean_cell(row.get("Market", "")) or "US"

                print(f"\nProduct {index + 1} of {total} — search terms: {search_terms}")

                url = ""
                status = "Not found on retailer"
                found_asin = asin

                unsupported_status = f"Unsupported retailer/market: {retailer}/{market}"

                for attempt in range(max_retries):
                    try:
                        if attempt > 0:
                            print(f"Retry {attempt + 1}/{max_retries}...")
                            driver.quit()
                            driver = self.setup_driver()
                            time.sleep(random.uniform(3, 5))

                        url, status, found_asin = self.verify_product(
                            driver,
                            asin,
                            search_terms,
                            retailer,
                            market,
                        )

                        if url or status in {"Not found on retailer", unsupported_status}:
                            break
                    except Exception as exc:  # noqa: BLE001
                        print(f"Error on attempt {attempt + 1}: {exc}")
                        status = "Error: verification failed"
                        url = ""
                        if attempt < max_retries - 1:
                            continue

                self.df.at[index, "Status"] = status
                self.df.at[index, "URL"] = url if url else ""
                self.df.at[index, "Found ASIN"] = found_asin or ""
                self.df.to_excel(self.excel_path, index=False)

                if index < total - 1:
                    time.sleep(random.uniform(3, 7))

            print("\n✓ Verification completed!")
        finally:
            if driver:
                driver.quit()


def main():
    excel_path = "/path/to/your/tracker.xlsx"  # Update to the path of your spreadsheet
    sheet_name = "COB-4739"  # Set to None for the first sheet
    verifier = ProductVerifier(excel_path, sheet_name=sheet_name)
    verifier.verify_products()


if __name__ == "__main__":
    main()
