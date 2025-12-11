# Excel File Format Guide

## Input File Structure

### Required Columns

#### Option 1: With Product Names
```
| Product Name                                          | GTIN          | Retailer |
|------------------------------------------------------|---------------|----------|
| Ray-Ban | Wayfarer - Black, Clear lenses                | 8056597625296 | Amazon   |
| Oakley | Gascan - Matte Black, Prizm™ Black              | 888392491955  | jbhifi   |
```

#### Option 2: With Product IDs (requires GTIN for name lookup)
```
| Product Name/ID | GTIN          | Retailer |
|----------------|---------------|----------|
| B01N5IB20Q     | 8056597625296 | Amazon   |
| PROD6381251    | 8056597625296 | Walgreens |
```

### Column Descriptions

**Product Name** or **Product Name/ID** (Required)
- Full product name with details (preferred)
- OR Product ID (ASIN, etc.) - requires GTIN for name lookup

**GTIN** (Optional but recommended)
- UPC, EAN, or other Global Trade Item Number
- Used for UPCitemdb product name lookup
- Format: numeric string (8-14 digits)

**Retailer** (Required)
- Retailer name (case-insensitive)
- Supported values:
  * Amazon: "Amazon", "amazon", "amazon-us"
  * Amazon AU: "Amazon-AU", "amazon-au"
  * Amazon Fresh: "Amazon-Fresh", "amazon-fresh"
  * Target: "Target", "target"
  * Walmart: "Walmart", "walmart"
  * CVS: "CVS", "cvs"
  * Walgreens: "Walgreens", "walgreens"
  * JB Hi-Fi: "JB Hi-Fi", "jbhifi", "jb hifi"
  * Harvey Norman: "Harvey Norman", "harveynorman"
  * (See README for complete list)

## Output File Structure

The script adds these columns:

```
| Found URL | Found Title | Matched Retailer | Matched Variant | Match Score | Status |
|-----------|-------------|------------------|-----------------|-------------|--------|
| https://... | Product Title | amazon | Variant name | 95.5 | SUCCESS |
```

**Found URL**
- Direct link to product page
- Empty if not found

**Found Title**
- Product title from retailer website
- Shows actual product name found

**Matched Retailer**
- Retailer where product was found
- Should match input retailer

**Matched Variant**
- Product name variation that was matched
- Shows which search query found the product

**Match Score**
- Fuzzy matching score (0-100)
- Higher = better match
- Threshold default: 60

**Status**
- `SUCCESS`: Product found
- `NOT_FOUND`: Product doesn't exist on retailer
- `ERROR: [message]`: Technical error occurred

## Example Files

### Example 1: Sunglasses
```excel
Product Name                                          | GTIN          | Retailer    | Found URL | Status
----------------------------------------------------|---------------|-------------|-----------|----------
Ray-Ban | Wayfarer - Black, Clear lenses            | 8056597625296 | Amazon      | https://...| SUCCESS
Oakley | Gascan - Matte Black, Prizm™ Black          | 888392491955  | jbhifi      | https://...| SUCCESS
Ray-Ban | Skyler - White, Transitions® Sapphire      | 8056597621588 | Amazon-AU   | https://...| SUCCESS
Oakley | Headliner - Matte Black, Clear lenses       | 888392478955  | harveynorman|          | NOT_FOUND
```

### Example 2: Food Products
```excel
Product Name/ID                    | GTIN          | Retailer        | Found URL | Status
----------------------------------|---------------|-----------------|-----------|----------
Cadbury Dairy Milk 180g           | 9310015123456 | Target          | https://...| SUCCESS
B07FKMT7YT                        | 123456789012  | Amazon          | https://...| SUCCESS
300462397                         | 987654321098  | Walgreens       | https://...| SUCCESS
```

### Example 3: Mixed Products
```excel
Product Name                      | GTIN          | Retailer | Found URL | Match Score | Status
---------------------------------|---------------|----------|-----------|-------------|----------
Sony WH-1000XM5                  | 4548736134850 | Target   | https://...| 92.5       | SUCCESS
Apple AirPods Pro (Gen 2)        | 194253397472  | Walmart  | https://...| 88.0       | SUCCESS
Samsung Galaxy Buds2             | 8806092628403 | Amazon   |           | 0          | NOT_FOUND
```

## Product Name Best Practices

### Sunglasses/Eyewear Format
```
Brand | Model - Frame Color, Lens Description
```

Examples:
- `Ray-Ban | Wayfarer - Shiny Black, Clear lenses`
- `Oakley | Gascan - Matte Black, Prizm™ 24K`
- `Ray-Ban | Skyler - White, Transitions® Sapphire`
- `Oakley | Flak 2.0 XL - Polished Black, Polarised`

### Electronics Format
```
Brand Model - Specifications
```

Examples:
- `Sony WH-1000XM5 - Black, Wireless`
- `Apple AirPods Pro (Gen 2)`
- `Samsung Galaxy S23 - 128GB, Phantom Black`

### Food/Grocery Format
```
Brand Product Name - Size/Weight
```

Examples:
- `Cadbury Dairy Milk - 180g`
- `Coca-Cola Zero Sugar - 12 Pack`
- `Oreo Original - Family Size 19.1oz`

## Common Issues

### Issue: All Products Show "NOT_FOUND"

**Possible Causes:**
1. Retailer name doesn't match configuration
2. Product names are actually IDs but column is "Product Name"
3. Product truly doesn't exist on that retailer

**Solutions:**
1. Check retailer name spelling
2. If column contains IDs, rename to "Product Name/ID" and provide GTINs
3. Try searching manually on retailer website

### Issue: Wrong Products Matched

**Possible Causes:**
1. Product names too generic
2. Match threshold too low
3. Missing important details (size, color, etc.)

**Solutions:**
1. Add more details to product names
2. Increase `--threshold` to 70 or 80
3. Include size/color/generation in product name

### Issue: "ERROR: Verification failed"

**Possible Causes:**
1. Bot detection / CAPTCHA
2. Retailer website down
3. Network issues

**Solutions:**
1. Try again later
2. Use `--no-headless` to see what's happening
3. Increase delays with `--delay 5`

## Data Validation Tips

Before running:
1. **Check retailer names** - Must match supported retailers
2. **Verify GTINs** - Should be 8-14 digits
3. **Review product names** - Include brand, model, key features
4. **Remove duplicates** - Same product+retailer combinations
5. **Check for special characters** - May cause issues in URLs

## Retailer-Specific Tips

### Amazon
- Include generation (Gen 1, Gen 2)
- Specify marketplace (US vs AU)
- ASINs work as Product Name/ID

### JB Hi-Fi / Harvey Norman
- Use Australian English spellings
- Include full product names
- Expect longer search times

### Food Retailers (Kroger, HEB, etc.)
- Include weight/size in product name
- Use common names, not marketing names
- GTINs highly recommended

### Specialty Retailers
- Staples: Include "Pack of X" if applicable
- Walgreens: Include brand and size
- Target: Include color/style variations
