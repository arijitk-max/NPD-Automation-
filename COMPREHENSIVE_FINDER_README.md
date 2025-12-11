# Comprehensive Product URL Finder

## Overview
This script automates finding product URLs across 25+ retailers by searching with product names/GTINs and using intelligent fuzzy matching.

## Supported Retailers

### US Retailers
- **Amazon** (amazon, amazon-fresh)
- **Target**
- **Walmart**
- **CVS**
- **Walgreens**
- **Kroger**
- **Albertsons**
- **Giant Eagle**
- **GoPuff**
- **HEB**
- **Hy-Vee**
- **Instacart-Publix**
- **Meijer**
- **Staples**
- **Wegmans**
- **BJ's**
- **Sam's Club**
- **ShopRite**

### Australian Retailers
- **JB Hi-Fi** (jbhifi)
- **Harvey Norman** (harveynorman)
- **Amazon Australia** (amazon-au)

## Installation

```bash
# Install dependencies
pip install -r requirements.txt

# Note: Chrome/Chromium browser required for Selenium
```

## Excel File Format

Your input Excel file should have these columns:

| Column | Required | Description |
|--------|----------|-------------|
| Product Name or Product Name/ID | Yes | Product name or product ID |
| GTIN | Optional | UPC/EAN code (used for UPCitemdb lookup) |
| Retailer | Yes | Retailer name (e.g., "Amazon", "Target") |

Output columns added:
- **Found URL**: Product URL found
- **Found Title**: Product title from retailer
- **Matched Retailer**: Retailer where product was found
- **Matched Variant**: Product variant that matched
- **Match Score**: Fuzzy match score (0-100)
- **Status**: SUCCESS, NOT_FOUND, or ERROR message

## Usage

### Process Single File
```bash
python comprehensive_product_finder.py --input input.xlsx --output results.xlsx
```

### Process Multiple Files
```bash
python comprehensive_product_finder.py --files file1.xlsx file2.xlsx file3.xlsx
```

### Process All Excel Files in Directory
```bash
python comprehensive_product_finder.py --process-all
```

### Advanced Options
```bash
# Disable headless mode (show browser)
python comprehensive_product_finder.py --input input.xlsx --output results.xlsx --no-headless

# Adjust fuzzy matching threshold (default: 60)
python comprehensive_product_finder.py --input input.xlsx --output results.xlsx --threshold 70

# Increase variants to try (default: 1)
python comprehensive_product_finder.py --input input.xlsx --output results.xlsx --max-variants 5

# Enable verbose logging
python comprehensive_product_finder.py --input input.xlsx --output results.xlsx --verbose
```

## How It Works

1. **Product Name Resolution**
   - If Excel has "Product Name" column: Uses names directly
   - If only "Product Name/ID" with IDs: Uses UPCitemdb to get product names from GTIN
   - Supports direct product IDs (ASINs, etc.) for certain retailers

2. **Retailer Search**
   - Searches retailer websites using Selenium
   - Filters out sponsored results
   - Extracts product information from search results
   - Handles bot detection with stealth techniques

3. **Fuzzy Matching**
   - Extracts product details (brand, model, color, size, etc.)
   - Compares with search results using fuzzy matching
   - Applies strict validation rules:
     * Model must match
     * Size must match (if specified)
     * Color variants validated
     * Lens types matched (for glasses)
     * Generation checked (Gen 1 vs Gen 2)
     * Rejects accessories and wrong variants

4. **Results & Progress**
   - Saves progress every 5 rows (configurable)
   - Creates detailed logs in `product_finder.log`
   - Updates Excel file with found URLs and match scores

## Retailer-Specific Features

### Amazon (US/AU/Fresh)
- Automatic location setting (AU: postcode 2000, US: 07008)
- ASIN direct URL support
- Comprehensive page detail fetching
- Sponsored result filtering

### Product ID Support
Direct URL construction for:
- Amazon ASINs (B0xxxxxxxxx)
- Walgreens IDs (PROD123456 or numeric)
- Target IDs (A-12345678)
- Walmart IDs (numeric 8-12 digits)
- And more...

## Configuration

Key settings in `DEFAULT_CONFIG`:
```python
{
    "headless": True,  # Run without browser window
    "max_variants": 1,  # Product name variations to try
    "fuzzy_threshold": 60,  # Match score threshold (0-100)
    "request_delay": (1.0, 3.0),  # Random delay between requests
    "page_load_timeout": 30,  # Page load timeout (seconds)
    "max_retries": 3,  # Retry attempts
    "save_interval": 5,  # Save progress every N rows
    "max_results_per_retailer": 5  # Results to check per retailer
}
```

## Adding New Retailers

To add a new retailer:

1. Add retailer configuration to `RETAILERS` dict:
```python
"new-retailer": {
    "domains": ["example.com"],
    "search_urls": ["https://www.example.com/search?q={query}"],
    "product_selector": ".product-item",  # CSS selector
    "title_selector": ".product-title",
    "link_selector": "a",
    "sponsored_indicators": ["Sponsored", "Ad"]
}
```

2. Add retailer name mapping in `_normalize_retailer_name()`:
```python
elif 'example' in retailer_lower:
    return 'new-retailer'
```

## Troubleshooting

### Bot Detection / CAPTCHA
- Script includes anti-bot measures (selenium-stealth, user agents)
- If CAPTCHA appears, try:
  * Increasing delays with `--delay 5`
  * Using `--no-headless` to solve manually
  * Adding more random delays in code

### No Results Found
- Check retailer name matches configuration
- Verify product name is not an ID (unless "Product Name/ID" column)
- Try lowering `--threshold 50`
- Check `product_finder.log` for details

### Import Errors
```bash
# Make sure all dependencies installed
pip install --upgrade -r requirements.txt

# Install Chrome/Chromium
# Ubuntu/Debian: sudo apt-get install chromium-browser
# Mac: brew install --cask google-chrome
```

## Performance Tips

1. **Faster Processing**
   - Use product IDs when possible (instant direct URLs)
   - Lower `max_results_per_retailer` to 3
   - Process files individually rather than --process-all

2. **Better Match Rates**
   - Ensure Product Name is accurate and complete
   - Include GTIN for UPCitemdb lookups
   - Use descriptive product names with brand/model

3. **Avoid Rate Limiting**
   - Increase `--delay` to 3-5 seconds
   - Process in smaller batches
   - Use headless mode (default)

## Logs

- **product_finder.log**: Detailed execution log
  * Search queries and results
  * Match scores and decisions
  * Errors and warnings
  * CAPTCHA/bot detection events

## Examples

### Sunglasses with Variants
```
Product Name: "Ray-Ban | Wayfarer Low Bridge Fit - White, Transitions® Sapphire"
Retailer: "amazon"
→ Finds exact variant with Transitions Sapphire lenses
```

### Candy Products
```
Product Name: "Cadbury Dairy Milk Chocolate Bar 180g"
GTIN: "9310015123456"
Retailer: "target"
→ Uses GTIN to get product variations, then searches Target
```

### Using ASINs (Direct)
```
Product Name/ID: "B01N5IB20Q"
Retailer: "Amazon"
→ Direct URL: https://www.amazon.com/dp/B01N5IB20Q
```

## Notes

- **First Run**: WebDriver installation may take a minute
- **Rate Limiting**: Random delays prevent rate limiting
- **Progress**: Results saved periodically (default: every 5 rows)
- **Sponsored Results**: Automatically filtered out
- **NOT_FOUND vs ERROR**: NOT_FOUND means product doesn't exist on retailer, ERROR means technical issue
