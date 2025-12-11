#!/bin/bash

echo "=============================================="
echo "NPD Automation - Setup Script"
echo "=============================================="
echo ""

# Check Python version
echo "Checking Python version..."
python3 --version

if [ $? -ne 0 ]; then
    echo "❌ Python 3 is not installed. Please install Python 3.8 or higher."
    exit 1
fi

echo "✓ Python 3 found"
echo ""

# Create virtual environment
echo "Creating virtual environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "✓ Virtual environment created"
else
    echo "✓ Virtual environment already exists"
fi
echo ""

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip

# Install requirements
echo ""
echo "Installing dependencies..."
pip install -r requirements.txt

if [ $? -eq 0 ]; then
    echo ""
    echo "✓ All dependencies installed successfully!"
else
    echo ""
    echo "❌ Failed to install dependencies"
    exit 1
fi

# Check Chrome/Chromium
echo ""
echo "Checking for Chrome/Chromium..."
if command -v google-chrome &> /dev/null || command -v chromium-browser &> /dev/null; then
    echo "✓ Chrome/Chromium found"
else
    echo "⚠️  Chrome/Chromium not found"
    echo "   Please install Chrome or Chromium:"
    echo "   Ubuntu/Debian: sudo apt-get install chromium-browser"
    echo "   Mac: brew install --cask google-chrome"
fi

echo ""
echo "=============================================="
echo "Setup Complete!"
echo "=============================================="
echo ""
echo "Next steps:"
echo "1. Activate virtual environment: source venv/bin/activate"
echo "2. Prepare your Excel file (see EXCEL_FORMAT_GUIDE.md)"
echo "3. Run the script:"
echo "   python comprehensive_product_finder.py --input input.xlsx --output results.xlsx"
echo ""
echo "For help:"
echo "   python comprehensive_product_finder.py --help"
echo ""
echo "Documentation:"
echo "   - COMPREHENSIVE_FINDER_README.md"
echo "   - EXCEL_FORMAT_GUIDE.md"
echo ""
