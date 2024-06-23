import requests
import pandas as pd
from datetime import datetime, timedelta
import re
import configparser
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
import matplotlib.pyplot as plt
from mplfinance.original_flavor import candlestick_ohlc

def load_config():
    current_dir = os.path.dirname(__file__)
    config_path = os.path.join(current_dir, 'config.ini')
    config = configparser.ConfigParser()
    config.read(config_path)
    return config

def bot_send_pic_to_line_notify(image_path, token, title_en, stock_code, stock_name):
    url = 'https://notify-api.line.me/api/notify'
    if title_en:
        message = '\n台灣股票強勢標的搜尋圖'
    else:
        message = f'\n{stock_code} {stock_name}'
    files = {'imageFile': open(image_path, 'rb')}
    headers = {'Authorization': f'Bearer {token}'}
    response = requests.post(url, headers=headers, files=files, data={'message': message})
    if response.status_code == 200:
        print("推送圖片至 Line Notify 成功")
    else:
        print(f"推送圖片失敗: {response.status_code}")

def taiwan_date_to_datetime(taiwan_date):
    year, month, day = map(int, taiwan_date.split('/'))
    year += 1911
    return datetime(year, month, day)

def get_stock_symbols():
    url = 'https://www.twse.com.tw/exchangeReport/STOCK_DAY_ALL'
    response = requests.get(url)
    data = response.json()
    stock_symbols = [{"證券代號": item[0], "證券名稱": item[1]} for item in data['data'] if re.match("^\d+$", item[0])]
    return stock_symbols

def get_stock_data(stock_code, start_date, end_date):
    url = f"https://www.twse.com.tw/exchangeReport/STOCK_DAY?response=json&date={start_date}&stockNo={stock_code}"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        if data['stat'] != "OK":
            return None
        df = pd.DataFrame(data['data'], columns=data['fields'])
        df = df[df['最低價'] != "--"]
        df['最低價'] = df['最低價'].str.replace(',', '').astype(float)
        df['收盤價'] = df['收盤價'].str.replace(',', '').astype(float)
        df['開盤價'] = df['開盤價'].str.replace(',', '').astype(float)
        df['最高價'] = df['最高價'].str.replace(',', '').astype(float)
        df['成交股數'] = df['成交股數'].str.replace(',', '').astype(float)
        df['日期'] = df['日期'].apply(taiwan_date_to_datetime)
        df['日期'] = pd.to_datetime(df['日期'])
        df.set_index('日期', inplace=True)
        return df
    else:
        print(f"無法獲取股票 {stock_code} 的數據，狀態碼: {response.status_code}")
        return None

def calculate_ema(series, window):
    return series.ewm(span=window, adjust=False).mean()

def calculate_ma(series, window):
    return series.rolling(window=window).mean()

def calculate_growth_rate(df, days):
    if len(df) < days + 1:
        return None
    start_price = float(df['收盤價'].iloc[-(days+1)])
    end_price = float(df['收盤價'].iloc[-1])
    growth_rate = ((end_price - start_price) / start_price) * 100
    return growth_rate

def fetch_and_calculate(stock_code, stock_name, start_date, end_date, sel_condition):
    df_total = None
    print(f"正在獲取股票 {stock_code} ({stock_name}) 的數據...")
    for i in range(12):
        df = get_stock_data(stock_code, (datetime.now() - timedelta(days=330 - i * 30)).strftime("%Y%m%d"), end_date)
        if df is not None:
            if df_total is None:
                df_total = df
            else:
                df_total = pd.concat([df_total, df], ignore_index=True)
        else:
            print("數據獲取錯誤")
            
    if(sel_condition == 0):
        if df_total is not None and len(df_total) >= 2:
            if float(df_total['收盤價'].iloc[-1]) > float(df_total['開盤價'].iloc[-1]):  # 判断最后一根K线是否收涨
                ma30 = calculate_ma(df_total['收盤價'], window=30)
                ma45 = calculate_ma(df_total['收盤價'], window=45)
                ma60 = calculate_ma(df_total['收盤價'], window=60)
                growth_rate = calculate_growth_rate(df_total, 5)  # 计算过去5天的增长率
                if (ma30.iloc[-1] > ma45.iloc[-1] > ma60.iloc[-1]) and (ma60.iloc[-1] < float(df_total['收盤價'].iloc[-1])):
                    if( abs((float(df_total['收盤價'].iloc[-1]) - ma30.iloc[-1]) / ma30.iloc[-1]) <= 0.05 or 
                        abs((float(df_total['收盤價'].iloc[-1]) - ma45.iloc[-1]) / ma45.iloc[-1]) <= 0.05 or 
                        abs((float(df_total['收盤價'].iloc[-1]) - ma60.iloc[-1]) / ma60.iloc[-1]) <= 0.05):
                        return stock_code, stock_name, growth_rate
    elif(sel_condition == 1):
        if df_total is not None and len(df_total) >= 2:
            if float(df_total['收盤價'].iloc[-1]) > float(df_total['開盤價'].iloc[-1]):  # 判断最后一根K线是否收涨
                ma20 = calculate_ma(df_total['收盤價'], window=20)
                ma60 = calculate_ma(df_total['收盤價'], window=60)
                growth_rate = calculate_growth_rate(df_total, 5)  # 计算过去5天的增长率
                if (ma60.iloc[-1] * 1.05 > ma20.iloc[-1] > ma60.iloc[-1]): #多頭排列
                    if((ma20.iloc[-1] * 1.05) > float(df_total['收盤價'].iloc[-1]) > ma20.iloc[-1]): # (防止直接開高，追高)
                        if(float(df_total['成交股數'].iloc[-2]) < (float(df_total['成交股數'].iloc[-1]))): # N成交量要大於N-1 and N要漲 (N = 最新的一根)
                            return stock_code, stock_name, growth_rate
    return None

def plot_stock_data(stock_code, stock_name, df, sel_condition, save_dir):
    plt.figure(figsize=(12, 8))

    # 确保数据类型正确
    df['開盤價'] = df['開盤價'].astype(float)
    df['最高價'] = df['最高價'].astype(float)
    df['最低價'] = df['最低價'].astype(float)
    df['收盤價'] = df['收盤價'].astype(float)
    df['成交股數'] = df['成交股數'].astype(float)
    df['Color'] = df['Color'].astype(str)

    ax1 = plt.subplot2grid((6,1), (0,0), rowspan=4, colspan=1)
    ax1.set_title(f'{stock_code} {stock_name} Candlestick Chart')
    ax1.xaxis.set_visible(False)  # 隐藏时间轴

    # 绘制K线图
    candlestick_ohlc(ax1, zip(range(len(df)), df['開盤價'], df['最高價'], df['最低價'], df['收盤價']), width=0.6, colorup='red', colordown='green')
    
    if sel_condition == 0:
        ax1.plot(df.index, df['MA30'], label=f'MA30: {df["MA30"].iloc[-1]:.2f}', color='yellow')
        ax1.plot(df.index, df['MA45'], label=f'MA45: {df["MA45"].iloc[-1]:.2f}', color='orange')
        ax1.plot(df.index, df['MA60'], label=f'MA60: {df["MA60"].iloc[-1]:.2f}', color='red')
    elif sel_condition == 1:
        ax1.plot(df.index, df['MA20'], label=f'MA20: {df["MA20"].iloc[-1]:.2f}', color='orange')
        ax1.plot(df.index, df['MA60'], label=f'MA60: {df["MA60"].iloc[-1]:.2f}', color='red')

    # 显示最后一根K棒的价格
    last_close_price = df['收盤價'].iloc[-1]
    ax1.text(len(df)-1, df['最高價'].iloc[-1], f'{last_close_price:.2f}', ha='center', va='bottom', fontsize=10, color='black')

    # 计算止损价位（最后一个收盘价的95%）
    stop_loss_price = last_close_price * 0.95

    # 绘制止损价位线
    ax1.axhline(stop_loss_price, color='blue', linestyle='--', label=f'5% Stop Loss: {stop_loss_price:.2f}')
    ax1.text(len(df)+5, stop_loss_price, f'{stop_loss_price:.2f}', ha='center', va='bottom', fontsize=10, color='blue')

    ax1.legend(loc='upper left')
    ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, pos: f'{x:.2f}' if pos == 0 else ''))  # 只显示最后的价格

    # 绘制成交量
    ax2 = plt.subplot2grid((6,1), (4,0), rowspan=2, colspan=1, sharex=ax1)
    ax2.bar(df.index, df['成交股數'], color=df['Color'])
    ax2.set_title(f'{stock_code} {stock_name} Volume')
    ax2.grid(True)
    
    plt.tight_layout()
    image_path = os.path.join(save_dir, f"{stock_code}_{stock_name}_chart.png")
    plt.savefig(image_path)
    plt.close()
    return image_path

def visualize_growth_table(df_top_growth, save_dir):
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.axis('tight')
    ax.axis('off')
    table = ax.table(cellText=df_top_growth.values,
                    colLabels=df_top_growth.columns,
                    cellLoc='center',
                    loc='center',
                    colWidths=[0.3, 0.3])
    table.auto_set_font_size(False)
    table.set_fontsize(14)
    table.scale(1.2, 1.2)
    plt.title(f"Top 10 Stocks by Growth Rate\n{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", fontsize=16, fontweight='bold')
    plt.tight_layout()
    image_path = os.path.join(save_dir, 'stock_colored_table.png')
    plt.savefig(image_path, bbox_inches='tight')
    return image_path

def main():
    config = load_config()
    line_notify_token = config['credentials']['line_notify_token_stock']
    stock_symbols = get_stock_symbols()
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=365)).strftime("%Y%m%d")

    TW_STOCK_STRONG_PIC_EVERY_DAY_DATA = "TW_STOCK_STRONG_PIC_EVERY_DAY_DATA"
    if not os.path.exists(TW_STOCK_STRONG_PIC_EVERY_DAY_DATA):
        os.makedirs(TW_STOCK_STRONG_PIC_EVERY_DAY_DATA)

    today_date = datetime.now().strftime("%Y%m%d")
    today_dir = os.path.join(TW_STOCK_STRONG_PIC_EVERY_DAY_DATA, today_date)
    if not os.path.exists(today_dir):
        os.makedirs(today_dir)

    stock_target_prio_q = []
    growth_rates = {}
    
    # 0 = crypto , 1 = tw_stock , 2 = us_stock
    sel_condition = 1
    
    with ThreadPoolExecutor(max_workers=1) as executor:
        futures = [executor.submit(fetch_and_calculate, stock['證券代號'], stock['證券名稱'], start_date, end_date , sel_condition) for stock in stock_symbols]
        for future in as_completed(futures):
            result = future.result()
            if result:
                stock_code, stock_name, growth_rate = result
                stock_target_prio_q.append(stock_code)
                growth_rates[stock_code] = growth_rate

    sorted_growth_rates = sorted(growth_rates.items(), key=lambda x: x[1], reverse=True)[:10]
    df_top_growth = pd.DataFrame(sorted_growth_rates, columns=['Stock', 'Growth Rate'])
    print(df_top_growth)
    growth_table_image = visualize_growth_table(df_top_growth, today_dir)
    bot_send_pic_to_line_notify(growth_table_image, line_notify_token, title_en=1, stock_code=None, stock_name=None)

    for stock_code in df_top_growth['Stock']:
        stock_name = next((stock['證券名稱'] for stock in stock_symbols if stock['證券代號'] == stock_code), "Unknown")
        df_total = None
        for i in range(12):
            df = get_stock_data(stock_code, (datetime.now() - timedelta(days=330 - i * 30)).strftime("%Y%m%d"), end_date)
            if df is not None:
                if df_total is None:
                    df_total = df
                else:
                    df_total = pd.concat([df_total, df], ignore_index=True)
            else:
                print("數據獲取錯誤")
        if df_total is not None:
            if sel_condition == 0:
                df_total['MA30'] = calculate_ma(df_total['收盤價'], window=30)
                df_total['MA45'] = calculate_ma(df_total['收盤價'], window=45)
                df_total['MA60'] = calculate_ma(df_total['收盤價'], window=60)
                df_total['Color'] = ['red' if close_price > open_price else 'green' for close_price, open_price in zip(df_total['收盤價'], df_total['開盤價'])]
                image_path = plot_stock_data(stock_code, stock_name, df_total, sel_condition, today_dir)
                bot_send_pic_to_line_notify(image_path, line_notify_token, title_en=0, stock_code=stock_code, stock_name=stock_name)
            elif sel_condition == 1:
                df_total['MA20'] = calculate_ma(df_total['收盤價'], window=20)
                df_total['MA60'] = calculate_ma(df_total['收盤價'], window=60)
                df_total['Color'] = ['red' if close_price > open_price else 'green' for close_price, open_price in zip(df_total['收盤價'], df_total['開盤價'])]
                image_path = plot_stock_data(stock_code, stock_name, df_total, sel_condition, today_dir)
                bot_send_pic_to_line_notify(image_path, line_notify_token, title_en=0, stock_code=stock_code, stock_name=stock_name)

if __name__ == "__main__":
    main()
