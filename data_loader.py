"""
Data Loader: Load NSE stock OHLCV data from CSV files.

Handles the standard format used in VSAScanner:
  date,open,high,low,close,volume
  
All lowercase column names, dates in YYYY-MM-DD format.
"""

import pandas as pd
from pathlib import Path
from typing import Dict, Optional


def load_stock_data(filepath: str) -> pd.DataFrame:
    """
    Load a single stock's OHLCV data from CSV.
    
    Args:
        filepath: path to CSV file
    
    Returns:
        DataFrame with 'date' index and columns: open, high, low, close, volume
    
    Raises:
        FileNotFoundError: if file doesn't exist
        ValueError: if data format is invalid
    """
    try:
        df = pd.read_csv(filepath)
    except FileNotFoundError:
        raise FileNotFoundError(f"Data file not found: {filepath}")
    
    # Normalize column names to lowercase
    df.columns = df.columns.str.lower()
    
    # Validate required columns
    required = {'date', 'open', 'high', 'low', 'close', 'volume'}
    if not required.issubset(set(df.columns)):
        raise ValueError(f"CSV must contain columns: {required}. Found: {set(df.columns)}")
    
    # Parse date and set as index
    df['date'] = pd.to_datetime(df['date'])
    df = df.set_index('date')
    df = df.sort_index()
    
    # Basic validation
    if len(df) == 0:
        raise ValueError("CSV is empty")
    
    if (df['high'] < df['low']).any():
        raise ValueError("Found bars where high < low")
    
    if (df['close'] > df['high']).any() or (df['close'] < df['low']).any():
        raise ValueError("Found bars where close is outside high-low range")
    
    # Select and reorder columns
    df = df[['open', 'high', 'low', 'close', 'volume']]
    
    return df


def load_multiple_stocks(data_dir: str, tickers: list) -> Dict[str, pd.DataFrame]:
    """
    Load multiple stocks from a directory.
    
    Args:
        data_dir: directory containing CSV files (e.g., 'data/' or 'stocks/')
        tickers: list of ticker symbols (e.g., ['HDFCBANK', 'RELIANCE', 'TATASTEEL'])
    
    Returns:
        Dictionary mapping ticker -> DataFrame
    
    Example:
        data = load_multiple_stocks('data/', ['HDFCBANK', 'RELIANCE'])
    """
    data = {}
    
    for ticker in tickers:
        # Try different file patterns (order matters: most specific first)
        patterns = [
            f"{data_dir}/{ticker}.NS.csv",      # HDFCBANK.NS.csv (NSE standard)
            f"{data_dir}/{ticker.upper()}.csv", # HDFCBANK.csv (uppercase)
            f"{data_dir}/{ticker}.csv",         # As-is
            f"{data_dir}/{ticker.lower()}.csv", # hdfcbank.csv (lowercase)
        ]
        
        filepath = None
        for pattern in patterns:
            if Path(pattern).exists():
                filepath = pattern
                break
        
        if filepath is None:
            print(f"⚠ Skipped {ticker}: no data file found")
            print(f"  Looked for: {patterns[0]}, {patterns[1]}, {patterns[2]}")
            continue
        
        try:
            df = load_stock_data(filepath)
            data[ticker] = df
            print(f"✓ Loaded {ticker}: {len(df)} bars from {df.index[0].date()} to {df.index[-1].date()}")
            print(f"  File: {Path(filepath).name}")
        except (FileNotFoundError, ValueError) as e:
            print(f"✗ Failed to load {ticker}: {e}")
    
    return data
