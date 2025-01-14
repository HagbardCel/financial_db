#!/usr/bin/env python3
import pandas as pd
import pandas_datareader.data as web
from datetime import datetime

def fetch_treasury_rates(start_date=datetime(1934, 1, 1), end_date=datetime.now()):
    """
    Fetches historical treasury rates for various maturities from FRED.
    Returns a DataFrame with rates for all available treasury durations.
    
    Parameters:
    -----------
    start_date : datetime, optional
        Start date for data retrieval. Defaults to 1934-01-01 (earliest available data)
    end_date : datetime, optional
        End date for data retrieval. Defaults to current date
        
    Returns:
    --------
    pandas.DataFrame
        DataFrame containing treasury rates for different maturities
    """
    # Treasury rate series IDs from FRED
    series_ids = {
        '1M': 'DGS1MO',    # 1-Month Treasury Bill
        '3M': 'DTB3',      # 3-Month Treasury Bill
        '6M': 'DTB6',      # 6-Month Treasury Bill
        '1Y': 'DGS1',      # 1-Year Treasury Rate
        '2Y': 'DGS2',      # 2-Year Treasury Rate
        '3Y': 'DGS3',      # 3-Year Treasury Rate
        '5Y': 'DGS5',      # 5-Year Treasury Rate
        '7Y': 'DGS7',      # 7-Year Treasury Rate
        '10Y': 'DGS10',    # 10-Year Treasury Rate
        '20Y': 'DGS20',    # 20-Year Treasury Rate
        '30Y': 'DGS30'     # 30-Year Treasury Rate
    }
    
    # Fetch data for each maturity
    df_list = []
    for maturity, series_id in series_ids.items():
        try:
            df = web.DataReader(series_id, 'fred', start_date, end_date)
            df.columns = [maturity]
            df_list.append(df)
        except Exception as e:
            print(f"Error fetching {maturity} treasury rate: {e}")
    
    # Combine all rates into a single DataFrame
    if df_list:
        rates_df = pd.concat(df_list, axis=1)
        rates_df.index = pd.to_datetime(rates_df.index)
        return rates_df
    else:
        raise Exception("Failed to fetch any treasury rates")

def write_treasury_rates_to_db(rates_df):
    """
    Writes treasury rates data to the interest_rates table in the database.
    
    Parameters:
    -----------
    rates_df : pandas.DataFrame
        DataFrame containing treasury rates for different maturities
    """
    # Prepare data for database insertion
    records = []
    
    for date in rates_df.index:
        for maturity in rates_df.columns:
            rate = rates_df.loc[date, maturity]
            if pd.notna(rate):  # Only insert non-null values
                records.append({
                    'date': date.date(),
                    'region': 'US',
                    'rate_type': 'Treasury',
                    'maturity': maturity,
                    'interest_rate': float(rate),
                    'currency': 'USD'
                })
    
    if records:
        # Convert to DataFrame for bulk insertion
        df_to_insert = pd.DataFrame(records)
        
        # Insert into database
        with DatabaseConnection() as conn:
            df_to_insert.to_sql('interest_rates', 
                              conn, 
                              if_exists='append', 
                              index=False,
                              method='multi')
    else:
        print("No valid rates data to insert")

if __name__ == "__main__":
    # Fetch treasury rates for the past year
    from datetime import datetime, timedelta
    end_date = datetime.now()
    start_date = end_date - timedelta(days=365)
    
    rates = fetch_treasury_rates(start_date, end_date)
    write_treasury_rates_to_db(rates)
    print("\nSample Treasury Rates:")
    print(rates.tail())
