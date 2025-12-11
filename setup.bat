@echo off
echo ==============================================
echo NPD Automation - Setup Script (Windows)
echo ==============================================
echo.

:: Check Python version
echo Checking Python version...
python --version
if errorlevel 1 (
    echo X Python is not installed. Please install Python 3.8 or higher.
    pause
    exit /b 1
)
echo * Python found
echo.

:: Create virtual environment
echo Creating virtual environment...
if not exist "venv" (
    python -m venv venv
    echo * Virtual environment created
) else (
    echo * Virtual environment already exists
)
echo.

:: Activate virtual environment
echo Activating virtual environment...
call venv\Scripts\activate.bat

:: Upgrade pip
echo Upgrading pip...
python -m pip install --upgrade pip

:: Install requirements
echo.
echo Installing dependencies...
pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo X Failed to install dependencies
    pause
    exit /b 1
)

echo.
echo * All dependencies installed successfully!

:: Check Chrome
echo.
echo Checking for Chrome...
where chrome >nul 2>&1
if errorlevel 1 (
    echo ! Chrome not found
    echo   Please install Google Chrome from https://www.google.com/chrome/
) else (
    echo * Chrome found
)

echo.
echo ==============================================
echo Setup Complete!
echo ==============================================
echo.
echo Next steps:
echo 1. Activate virtual environment: venv\Scripts\activate.bat
echo 2. Prepare your Excel file (see EXCEL_FORMAT_GUIDE.md)
echo 3. Run the script:
echo    python comprehensive_product_finder.py --input input.xlsx --output results.xlsx
echo.
echo For help:
echo    python comprehensive_product_finder.py --help
echo.
echo Documentation:
echo    - COMPREHENSIVE_FINDER_README.md
echo    - EXCEL_FORMAT_GUIDE.md
echo.
pause
