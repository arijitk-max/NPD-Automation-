# NPD-Automation

NPD automation process for finding product URLs across multiple retailers.

## Tools

### 1. automation_v2.py
Simple product verifier for Amazon marketplaces (CA, US, UK) using ASINs.

### 2. comprehensive_product_finder.py
Advanced product URL finder supporting 25+ retailers with:
- UPCitemdb integration
- Fuzzy matching
- Multi-retailer support
- Progress tracking

See [COMPREHENSIVE_FINDER_README.md](COMPREHENSIVE_FINDER_README.md) for detailed documentation.

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run comprehensive finder
python comprehensive_product_finder.py --input input.xlsx --output results.xlsx

# See help
python comprehensive_product_finder.py --help
```

## Documentation

- [Comprehensive Finder README](COMPREHENSIVE_FINDER_README.md)
- [Excel Format Guide](EXCEL_FORMAT_GUIDE.md)
- [Requirements](requirements.txt)
