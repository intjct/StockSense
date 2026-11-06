# Entry point used to build StockSense.exe with PyInstaller.
import sys

from stocksense.app import main

if __name__ == "__main__":
    sys.exit(main())
