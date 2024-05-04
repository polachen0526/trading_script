import requests
import pandas as pd
from datetime import datetime, timedelta
import re

def taiwan_date_to_datetime(taiwan_date):
    # 將台灣日期字符串分割為年、月、日
    year, month, day = map(int, taiwan_date.split('/'))
    # 將民國年份轉換為西元年份
    year += 1911
    # 使用 datetime 函數將日期字符串轉換為 datetime 對象
    return datetime(year, month, day)

# 获取台股所有标的列表
def get_stock_symbols():
    url = 'https://www.twse.com.tw/exchangeReport/STOCK_DAY_ALL'
    response = requests.get(url)
    data = response.json()
    stock_symbols = [item[0] for item in data['data'] if re.match("^\d+$",item[0])]
    return stock_symbols

def get_stock_data(stock_code, start_date, end_date):
    url = f"https://www.twse.com.tw/exchangeReport/STOCK_DAY?response=json&date={start_date}&stockNo={stock_code}"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        if data['stat'] != "OK":
            return None
        df = pd.DataFrame(data['data'], columns=data['fields'])
        df = df[df['收盤價'] != "--"]
        df['收盤價'] = df['收盤價'].str.replace(',', '')
        df['日期'] = df['日期'].apply(taiwan_date_to_datetime)
        df['日期'] = pd.to_datetime(df['日期'])
        df.set_index('日期', inplace=True)
        return df
    else:
        print(f"Failed to fetch data for stock {stock_code}. Status code: {response.status_code}")
        return None
    
def calculate_ema(series, window):
    return series.ewm(span=window, adjust=False).mean()

def calculate_ma(series, window):
    return series.rolling(window=window).mean()

if __name__ == "__main__":
    
    stock_target_prio_q = []
    
    # 取得台股所有標的
    stock_symbols = get_stock_symbols()
    # 設定抓取歷史資料的時間範圍
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=365)).strftime("%Y%m%d")  # 抓取過去一年的資料

    # 抓取台股所有標的的歷史價格並計算 EMA
    for stock_code in stock_symbols:
        print(f"Fetching data for stock {stock_code}...")
        for i in range(6):
            df = get_stock_data(stock_code, (datetime.now() - timedelta(days=150 - i*30) ).strftime("%Y%m%d"), end_date)
            if df is not None:
                if i==0:
                    df_total = df
                else:
                    df_total = pd.concat([df_total,df],ignore_index=True)
        if df_total is not None:
            print(len(df_total))
            # 計算 EMA30、EMA45、EMA60
            ema30 = calculate_ma(df_total['收盤價'].astype(float), window=30)
            ema45 = calculate_ma(df_total['收盤價'].astype(float), window=45)
            ema60 = calculate_ma(df_total['收盤價'].astype(float), window=60)
            print(f"Symbol: {stock_code}, MA30: {ema30.iloc[-1]} , MA45: {ema45.iloc[-1]} , MA60: {ema60.iloc[-1]} , Close: {df_total['收盤價'].iloc[-1]}")
            if(ema30.iloc[-1] > ema45.iloc[-1] > ema60.iloc[-1] and ema60.iloc[-1] < float(df_total['收盤價'].iloc[-1])): #最後一個月的最後一根收盤價格
                stock_target_prio_q.append(stock_code)
        else:
            print(f"Failed to fetch data for stock {stock_code}.")
            
    # 輸出計算結果
    print(stock_target_prio_q)