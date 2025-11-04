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
from urllib.parse import urljoin

class ProductVerifier:
    def __init__(self, excel_path):
        self.excel_path = excel_path
        self.df = pd.read_excel(excel_path)
        if 'URL' not in self.df.columns:
            self.df['URL'] = ''
        self.df['URL'] = self.df['URL'].astype(str)
        self.df['Status'] = self.df['Status'].astype(str)
        
        # Define base URLs for different Amazon marketplaces
        self.retailer_urls = {
            'Amazon': {
                'CA': 'https://www.amazon.ca',
                'US': 'https://www.amazon.com',
                'UK': 'https://www.amazon.co.uk'
            }
        }
        
        # User agents for rotation
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Safari/605.1.15'
        ]

    def setup_driver(self):
        """Initialize headless Chrome with anti-detection measures"""
        options = webdriver.ChromeOptions()
        options.add_argument('--headless=new')
        options.add_argument('--no-sandbox')
        options.add_argument('--window-size=1920,1080')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_argument(f'--user-agent={random.choice(self.user_agents)}')
        service = Service(ChromeDriverManager().install())
        return webdriver.Chrome(service=service, options=options)

    def direct_asin_check(self, driver, asin, base_url):
        """Try to access the product directly using ASIN"""
        try:
            direct_url = f"{base_url}/dp/{asin}"
            driver.get(direct_url)
            time.sleep(random.uniform(2, 3))
            
            title = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.ID, "productTitle"))
            ).text
            print(f"✓ Found via direct ASIN: {title[:100]}...")
            return direct_url, "Found on retailer"
        except:
            return None, None

    def search_results_check(self, driver, asin, base_url):
        """Search for the product and check results"""
        try:
            search_url = f"{base_url}/s?k={asin}"
            driver.get(search_url)
            time.sleep(random.uniform(2, 3))
            
            results = WebDriverWait(driver, 10).until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div[data-asin]"))
            )
            
            # Get first 10 valid results
            valid_results = [r for r in results if r.get_attribute('data-asin')][:10]
            
            for result in valid_results:
                try:
                    result_asin = result.get_attribute('data-asin')
                    if result_asin.upper() == asin.upper():
                        url_elem = result.find_element(By.CSS_SELECTOR, "a[class*='a-link-normal'][href*='/dp/']")
                        return url_elem.get_attribute('href'), "Found on retailer"
                except:
                    continue
            
            return None, "Not found on retailer"
        except Exception as e:
            print(f"Search error: {str(e)}")
            return None, None

    def verify_product(self, driver, asin, retailer, market):
        """Verify a single product"""
        base_url = self.retailer_urls.get(retailer, {}).get(market)
        if not base_url:
            return None, f"Unsupported retailer/market: {retailer}/{market}"

        print(f"\nChecking ASIN '{asin}' on {retailer} {market}...")
        
        # Try direct ASIN lookup first
        url, status = self.direct_asin_check(driver, asin, base_url)
        if url:
            return url, status
            
        # If direct lookup fails, try search
        print("Direct lookup failed, trying search...")
        url, status = self.search_results_check(driver, asin, base_url)
        if url:
            return url, status
            
        return None, "Not found on retailer"

    def verify_products(self):
        """Verify all products in the Excel file"""
        driver = None
        try:
            driver = self.setup_driver()
            total = len(self.df)
            max_retries = 3
            
            for index, row in self.df.iterrows():
                asin = str(row['Product Name'])
                print(f"\nProduct {index + 1} of {total}")
                
                for attempt in range(max_retries):
                    try:
                        if attempt > 0:
                            print(f"Retry {attempt + 1}/{max_retries}")
                            driver.quit()
                            driver = self.setup_driver()
                            time.sleep(random.uniform(3, 5))
                        
                        url, status = self.verify_product(
                            driver,
                            asin,
                            str(row['Retailer']),
                            str(row['Market'])
                        )
                        
                        if url or status == "Not found on retailer":
                            break
                            
                    except Exception as e:
                        print(f"Error on attempt {attempt + 1}: {str(e)}")
                        status = "Error: Verification failed"
                        url = ""
                        if attempt < max_retries - 1:
                            continue
                
                # Update results
                self.df.at[index, 'Status'] = status
                self.df.at[index, 'URL'] = url if url else ''
                self.df.to_excel(self.excel_path, index=False)
                
                # Random delay between products
                if index < total - 1:
                    delay = random.uniform(3, 7)
                    time.sleep(delay)
                
        finally:
            if driver:
                driver.quit()
            print("\n✓ Verification completed!")

def main():
    excel_path = '/Users/arijitkumar/Documents/VSCode/Mondalez-NPD tracker.xlsx'
    verifier = ProductVerifier(excel_path)
    verifier.verify_products()

if __name__ == "__main__":
    main()
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
from urllib.parse import urljoin

class ProductVerifier:
    def __init__(self, excel_path):
        self.excel_path = excel_path
        self.df = pd.read_excel(excel_path)
        if 'URL' not in self.df.columns:
            self.df['URL'] = ''
        self.df['URL'] = self.df['URL'].astype(str)
        self.df['Status'] = self.df['Status'].astype(str)
        
        # Define base URLs for different Amazon marketplaces
        self.retailer_urls = {
            'Amazon': {
                'CA': 'https://www.amazon.ca',
                'US': 'https://www.amazon.com',
                'UK': 'https://www.amazon.co.uk'
            }
        }
        
        # User agents for rotation
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Safari/605.1.15'
        ]

    def setup_driver(self):
        """Initialize headless Chrome with anti-detection measures"""
        options = webdriver.ChromeOptions()
        options.add_argument('--headless=new')
        options.add_argument('--no-sandbox')
        options.add_argument('--window-size=1920,1080')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_argument(f'--user-agent={random.choice(self.user_agents)}')
        service = Service(ChromeDriverManager().install())
        return webdriver.Chrome(service=service, options=options)

    def direct_asin_check(self, driver, asin, base_url):
        """Try to access the product directly using ASIN"""
        try:
            direct_url = f"{base_url}/dp/{asin}"
            driver.get(direct_url)
            time.sleep(random.uniform(2, 3))
            
            title = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.ID, "productTitle"))
            ).text
            print(f"✓ Found via direct ASIN: {title[:100]}...")
            return direct_url, "Found on retailer"
        except:
            return None, None

    def search_results_check(self, driver, asin, base_url):
        """Search for the product and check results"""
        try:
            search_url = f"{base_url}/s?k={asin}"
            driver.get(search_url)
            time.sleep(random.uniform(2, 3))
            
            results = WebDriverWait(driver, 10).until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div[data-asin]"))
            )
            
            # Get first 10 valid results
            valid_results = [r for r in results if r.get_attribute('data-asin')][:10]
            
            for result in valid_results:
                try:
                    result_asin = result.get_attribute('data-asin')
                    if result_asin.upper() == asin.upper():
                        url_elem = result.find_element(By.CSS_SELECTOR, "a[class*='a-link-normal'][href*='/dp/']")
                        return url_elem.get_attribute('href'), "Found on retailer"
                except:
                    continue
            
            return None, "Not found on retailer"
        except Exception as e:
            print(f"Search error: {str(e)}")
            return None, None

    def verify_product(self, driver, asin, retailer, market):
        """Verify a single product"""
        base_url = self.retailer_urls.get(retailer, {}).get(market)
        if not base_url:
            return None, f"Unsupported retailer/market: {retailer}/{market}"

        print(f"\nChecking ASIN '{asin}' on {retailer} {market}...")
        
        # Try direct ASIN lookup first
        url, status = self.direct_asin_check(driver, asin, base_url)
        if url:
            return url, status
            
        # If direct lookup fails, try search
        print("Direct lookup failed, trying search...")
        url, status = self.search_results_check(driver, asin, base_url)
        if url:
            return url, status
            
        return None, "Not found on retailer"

    def verify_products(self):
        """Verify all products in the Excel file"""
        driver = None
        try:
            driver = self.setup_driver()
            total = len(self.df)
            max_retries = 3
            
            for index, row in self.df.iterrows():
                asin = str(row['Product Name'])
                print(f"\nProduct {index + 1} of {total}")
                
                for attempt in range(max_retries):
                    try:
                        if attempt > 0:
                            print(f"Retry {attempt + 1}/{max_retries}")
                            driver.quit()
                            driver = self.setup_driver()
                            time.sleep(random.uniform(3, 5))
                        
                        url, status = self.verify_product(
                            driver,
                            asin,
                            str(row['Retailer']),
                            str(row['Market'])
                        )
                        
                        if url or status == "Not found on retailer":
                            break
                            
                    except Exception as e:
                        print(f"Error on attempt {attempt + 1}: {str(e)}")
                        status = "Error: Verification failed"
                        url = ""
                        if attempt < max_retries - 1:
                            continue
                
                # Update results
                self.df.at[index, 'Status'] = status
                self.df.at[index, 'URL'] = url if url else ''
                self.df.to_excel(self.excel_path, index=False)
                
                # Random delay between products
                if index < total - 1:
                    delay = random.uniform(3, 7)
                    time.sleep(delay)
                
        finally:
            if driver:
                driver.quit()
            print("\n✓ Verification completed!")

def main():
    excel_path = '/Users/arijitkumar/Documents/VSCode/Mondalez-NPD tracker.xlsx'
    verifier = ProductVerifier(excel_path)
    verifier.verify_products()

if __name__ == "__main__":
    main()
