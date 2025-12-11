# Troubleshooting Guide

## Common Issues and Solutions

### Installation Issues

#### Issue: `pip install` fails with "No module named pip"
**Solution:**
```bash
# Download get-pip.py
curl https://bootstrap.pypa.io/get-pip.py -o get-pip.py

# Install pip
python3 get-pip.py

# Try again
pip install -r requirements.txt
```

#### Issue: `selenium` or `webdriver-manager` installation fails
**Solution:**
```bash
# Upgrade pip first
pip install --upgrade pip setuptools wheel

# Try installing packages one by one
pip install pandas
pip install selenium
pip install webdriver-manager
pip install rapidfuzz
pip install beautifulsoup4
pip install requests
pip install openpyxl
pip install selenium-stealth
```

#### Issue: "ChromeDriver executable not found"
**Solution:**
```bash
# The script uses webdriver-manager which auto-downloads ChromeDriver
# But ensure Chrome/Chromium is installed first

# Ubuntu/Debian
sudo apt-get update
sudo apt-get install chromium-browser

# Mac
brew install --cask google-chrome

# Or manually install Chrome from google.com/chrome
```

---

### Runtime Issues

#### Issue: "CAPTCHA detected" or "Bot detection"
**Symptoms:** Script stops, logs show "CAPTCHA detected" or "Bot detection"

**Solutions:**

1. **Increase delays:**
   ```bash
   python comprehensive_product_finder.py --input input.xlsx --output results.xlsx --delay 5
   ```

2. **Use non-headless mode (allows manual CAPTCHA solving):**
   ```bash
   python comprehensive_product_finder.py --input input.xlsx --output results.xlsx --no-headless
   ```
   When CAPTCHA appears, solve it manually in the browser window.

3. **Process in smaller batches:**
   - Split large Excel files into smaller files (10-20 rows each)
   - Process one at a time with delays between files

4. **Try again later:**
   - Some retailers have stricter rate limiting at certain times
   - Try during off-peak hours

#### Issue: All products show "NOT_FOUND"
**Symptoms:** Every row shows `Status: NOT_FOUND`, but products exist

**Possible Causes & Solutions:**

1. **Retailer name mismatch:**
   ```
   Check: Is your retailer name spelled correctly?
   ✓ Correct: "Amazon", "jbhifi", "Target"
   ✗ Wrong: "Amazn", "JB-HiFi", "target.com"
   ```

2. **Product names are actually IDs:**
   ```
   If your "Product Name" column has values like:
   - B01N5IB20Q (ASIN)
   - PROD6381251 (Walgreens ID)
   - A-53280541 (Target ID)
   
   Solution: Rename column to "Product Name/ID" and ensure GTIN column is filled
   ```

3. **Match threshold too high:**
   ```bash
   # Lower the threshold
   python comprehensive_product_finder.py --input input.xlsx --output results.xlsx --threshold 50
   ```

4. **Product genuinely doesn't exist:**
   - Manually search the retailer website
   - Check if product is available in that region
   - Verify retailer actually sells that product

#### Issue: Wrong products matched
**Symptoms:** Found products don't match input products

**Solutions:**

1. **Make product names more specific:**
   ```
   Instead of: "Sunglasses"
   Use: "Ray-Ban | Wayfarer - Black, Clear lenses"
   
   Instead of: "Chocolate"
   Use: "Cadbury Dairy Milk - 180g"
   ```

2. **Increase match threshold:**
   ```bash
   python comprehensive_product_finder.py --input input.xlsx --output results.xlsx --threshold 75
   ```

3. **Include critical details:**
   - Brand name
   - Model name
   - Size/weight
   - Color/variant
   - Generation (if applicable)

#### Issue: "Error: Verification failed"
**Symptoms:** Rows show `Status: ERROR: Verification failed`

**Solutions:**

1. **Check internet connection**

2. **Verify retailer website is accessible:**
   - Open retailer website in browser
   - Check if website is down or blocking your IP

3. **Check logs for details:**
   ```bash
   tail -50 product_finder.log
   ```

4. **Try with verbose logging:**
   ```bash
   python comprehensive_product_finder.py --input input.xlsx --output results.xlsx --verbose
   ```

5. **Restart and retry failed rows:**
   - Script saves progress automatically
   - Re-run with same output file to retry failed rows

---

### Excel File Issues

#### Issue: "Missing required column: 'Product Name'"
**Solution:**
```
Ensure your Excel file has one of these columns:
- "Product Name" (for product names)
- "Product Name/ID" (for names or IDs)

Check for:
- Spelling errors
- Extra spaces
- Case sensitivity (should be exact)
```

#### Issue: "Missing required column: 'Retailer'"
**Solution:**
```
Add a "Retailer" column with values like:
- Amazon
- Target
- jbhifi
- harveynorman

See EXCEL_FORMAT_GUIDE.md for complete list
```

#### Issue: Excel file won't open after processing
**Solution:**
```bash
# Make a backup first
cp results.xlsx results_backup.xlsx

# Try opening with pandas to check for corruption
python3 << EOF
import pandas as pd
df = pd.read_excel('results.xlsx')
print(df.head())
EOF

# If corrupted, process original file again
```

---

### Performance Issues

#### Issue: Script is very slow
**Causes & Solutions:**

1. **Too many variants being tried:**
   ```bash
   # Reduce max_variants (default is 1, which is optimal)
   python comprehensive_product_finder.py --input input.xlsx --output results.xlsx --max-variants 1
   ```

2. **Delays are too long:**
   ```bash
   # Reduce delay (but risk rate limiting)
   python comprehensive_product_finder.py --input input.xlsx --output results.xlsx --delay 1.5
   ```

3. **Checking too many results:**
   - Edit DEFAULT_CONFIG in script
   - Reduce `max_results_per_retailer` from 5 to 3

4. **Retailer websites are slow:**
   - Harvey Norman, JB Hi-Fi sometimes load slowly
   - This is normal, be patient

#### Issue: Script uses too much memory
**Solutions:**

1. **Process in smaller batches:**
   ```bash
   # Split large Excel files
   # Process 50-100 rows at a time
   ```

2. **Close other applications**

3. **Use headless mode (default):**
   ```bash
   # Headless uses less memory
   python comprehensive_product_finder.py --input input.xlsx --output results.xlsx
   # (--headless is default, no flag needed)
   ```

---

### Retailer-Specific Issues

#### Amazon: "Location set to India" or wrong country
**Solution:**
- Script automatically sets location (AU: 2000, US: 07008)
- If still wrong, use `--no-headless` and manually change location
- Check logs for "Location already set" messages

#### JB Hi-Fi: No products found
**Solutions:**
1. Check product names are spelled correctly (Australian English)
2. JB Hi-Fi detection is strict - use exact product names
3. Try searching manually on jbhifi.com.au first
4. Check logs for extraction errors

#### Harvey Norman: Frequent bot detection
**Solutions:**
1. Harvey Norman has Imperva/hCaptcha protection
2. Use longer delays: `--delay 8`
3. Use `--no-headless` to solve CAPTCHA manually
4. Process very small batches (5-10 rows)
5. Try again later (off-peak hours)

#### Walgreens/CVS: Product IDs not working
**Solution:**
```
Walgreens IDs: PROD6381251 or 300462397
CVS IDs: 230355

Ensure:
1. Column is named "Product Name/ID"
2. IDs are correct format
3. GTIN column is filled (for name lookup if needed)
```

---

### Debugging Tips

#### Enable verbose logging
```bash
python comprehensive_product_finder.py --input input.xlsx --output results.xlsx --verbose
```

#### Check logs
```bash
# View last 100 lines
tail -100 product_finder.log

# Search for errors
grep -i error product_finder.log

# Search for specific product
grep -i "product name" product_finder.log
```

#### Run in non-headless mode
```bash
python comprehensive_product_finder.py --input input.xlsx --output results.xlsx --no-headless
```
Watch the browser window to see what's happening.

#### Test with one row
1. Create a test Excel file with just 1 row
2. Run the script
3. Check if it works
4. If it works, the issue is with data format

#### Test specific retailer
1. Create test file with just one retailer
2. Verify retailer name is correct
3. Check if that retailer's website is accessible

---

### Getting Help

If you've tried everything and still have issues:

1. **Check logs carefully:**
   ```bash
   cat product_finder.log | less
   ```

2. **Verify your setup:**
   - Python 3.8+
   - All requirements installed
   - Chrome/Chromium installed
   - Excel file format correct

3. **Simplify the problem:**
   - Test with 1 row
   - Test with 1 retailer
   - Test with simple product name

4. **Document the issue:**
   - What command did you run?
   - What was the error message?
   - What does the log say?
   - Can you reproduce it?

5. **Check for known issues:**
   - Review this troubleshooting guide
   - Check COMPREHENSIVE_FINDER_README.md
   - Review EXCEL_FORMAT_GUIDE.md
