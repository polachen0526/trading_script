import requests
import pandas as pd
import sys
import smtplib
import time
import json
import datetime
import configparser
import os
import numpy as np
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors

#################################################################### CRYPTO FUNC #############################################################################
def get_contract_assets():
    url = "https://fapi.binance.com/fapi/v1/exchangeInfo"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        return [asset['symbol'] for asset in data['symbols'] if asset["contractType"]=="PERPETUAL" and asset['symbol'][-4:]=="USDT" and asset["status"]=="TRADING"]
    else:
        print(f"Failed to fetch contract assets. Status code: {response.status_code}")
        return []

def get_contract_klines(symbol, interval, limit):
    url = "https://fapi.binance.com/fapi/v1/klines"
    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit
    }
    response = requests.get(url, params=params)
    if response.status_code == 200:
        data = response.json()
        df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'quote_asset_volume', 'number_of_trades', 'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        return df
    else:
        print(f"Failed to fetch data for symbol {symbol}. Status code: {response.status_code}")
        return None

#################################################################### EMA FUNC #############################################################################
def calculate_ema(series, window):
    return series.ewm(span=window, adjust=False).mean()

def calculate_ma(series, window):
    return series.rolling(window=window).mean()

def calculate_volatility(prices):
    log_returns = np.log(prices[1:] / prices[:-1])
    volatility = np.sqrt(np.sum((log_returns - np.mean(log_returns))**2) / (len(log_returns) - 1))
    return volatility

# 函式：計算增長百分比
def calculate_growth_percent(df,interval):
    
    if(interval=="1d"):
        growth_percent = np.zeros((5, 3))
        time_count = 5
    elif(interval=="8h"):
        growth_percent = np.zeros((5 * 3, 3))
        time_count = 5 * 3
    elif(interval=="4h"):
        growth_percent = np.zeros((5 * 3 * 2, 3))
        time_count = 5 * 3 * 2
    elif(interval=="1h"):
        growth_percent = np.zeros((5 * 3 * 2 * 4, 3))
        time_count = 5 * 3 * 2 * 4

    for i in range(time_count):
        
        if(len(df) < time_count):
            growth_percent[i, :] = 0
            continue
            
        current = df.iloc[-i-1]
        prev_1 = df.iloc[-i-2]
        
        # 計算增長百分比
        growth_percent[i, 0] = ((current['ma_30'] - prev_1['ma_30']) / prev_1['ma_30']) * 100
        growth_percent[i, 1] = ((current['ma_45'] - prev_1['ma_45']) / prev_1['ma_45']) * 100
        growth_percent[i, 2] = ((current['ma_60'] - prev_1['ma_60']) / prev_1['ma_60']) * 100

    return growth_percent


#################################################################### POST LINE AND EMAIL FUNC #############################################################################
def bot_send_pic_to_line_notify(push_content):
    # 設定Line Notify的權杖
    token = config['credentials']['line_notify_token']

    # 要傳送的圖片檔案路徑
    #image_path = 'colored_table.png'
    image_path = push_content

    # Line Notify的API端點
    url = 'https://notify-api.line.me/api/notify'

    # 設定要傳送的訊息
    message = '\n虛擬貨幣強勢標的搜尋圖'

    # 設定要上傳的圖片檔案
    files = {'imageFile': open(image_path, 'rb')}

    # 設定Headers，包括權杖和Content-Type
    headers = {'Authorization': f'Bearer {token}'}

    # 發送POST請求
    response = requests.post(url, headers=headers, files=files, data={'message': message})
    
    print("push pic to line-bot-notify success")
    
def bot_send_msg_to_line_notify(push_content):
    url = 'https://notify-api.line.me/api/notify'
    token = config['credentials']['line_notify_token']
    headers = {
        'Authorization': 'Bearer ' + token    # 設定權杖
    }
    data = {
        'message':"\n" + push_content     # 設定要發送的訊息
    }
    data = requests.post(url, headers=headers, data=data)   # 使用 POST 方法
    
    print("push data to line-bot-notify success")
    
def bot_send_msg_to_line(push_content):

    # set your Channel Access Token 和 Channel Secret
    CHANNEL_ACCESS_TOKEN = config['credentials']['line_CHANNEL_ACCESS_TOKEN']
    CHANNEL_SECRET = config['credentials']['line_CHANNEL_SECRET']
    channel_access_token = CHANNEL_ACCESS_TOKEN
    
    # set robot user line id ,主動推送訊息使用
    user_id = 'Uca1834654755de850c8d290fcfa06c5e'

    # 初始化 LineBotApi
    line_bot_api = LineBotApi(channel_access_token)
        
    # message content
    message = TextSendMessage(text=push_content)

    # push message
    line_bot_api.push_message(user_id, messages=message)
    
    print("push data to line-bot success")
    
    
def bot_send_msg_to_email(push_content):
    # send gmail setting
    sender_email    = "pola_strong_stock_finder@gmail.com"
    receiver_email  = "asd23065@gmail.com"

    # create message object instance
    msg = MIMEMultipart()

    # setup the parameters of the message
    password = "your_password"
    msg['From'] = sender_email
    msg['To'] = receiver_email
    msg['Subject'] = "Subject of the Mail"

    # add in the message body
    msg.attach(MIMEText(push_content, 'plain'))

    # create server
    server = smtplib.SMTP('smtp.gmail.com: 587')

    server.starttls()

    # Login Credentials for sending the mail
    server.login(msg['From'], password)

    # send the message via the server.
    server.sendmail(msg['From'], msg['To'], msg.as_string())

    server.quit()
    
def process_symbol_crypto(symbol,intervals,limits):
    # 在這裡處理單個交易對的邏輯
    # time_slot checker , initial when calc another crypto
    time_slot_1d = False
    time_slot_8h = False
    time_slot_4h = False
    time_slot_1h = False
    strength_score_1d = 0
    strength_score_8h = 0
    strength_score_4h = 0
    strength_score_1h = 0

    for interval, limit in zip(intervals, limits):
        #STEP 1. fetch history K line data
        df = get_contract_klines(symbol, interval, limit)

        if df is not None:
            # STEP 2. calc MA30 ,MA45 and MA60
            df['ma_30'] = ema30 = calculate_ma(df['close'].astype(float), 30)
            df['ma_45'] = ema45 = calculate_ma(df['close'].astype(float), 45)
            df['ma_60'] = ema60 = calculate_ma(df['close'].astype(float), 60)
            growth_percent_symbol = calculate_growth_percent(df,interval)  # 計算增長百分比
            growth_average = (growth_percent_symbol[:, 0] + growth_percent_symbol[:, 1] + growth_percent_symbol[:, 2]) / 3  # 計算平均增長率
            if(interval=="1d"):
                strength_score_1d = growth_average.mean()  # 計算強勢評分
            elif(interval=="8h"):
                strength_score_8h = growth_average.mean()  # 計算強勢評分
            elif(interval=="4h"):
                strength_score_4h = growth_average.mean()  # 計算強勢評分
            elif(interval=="1h"):
                strength_score_1h = growth_average.mean()  # 計算強勢評分
            
            print(f"interval: {interval} , Symbol: {symbol}, MA30: {ema30.iloc[-1]} , MA45: {ema45.iloc[-1]} , MA60: {ema60.iloc[-1]} , Close: {df['close'].iloc[-1]}")

            #STEP 3. MOVING AVERAGE CHECK
            #check ema 30 > 45 > 60，多頭排列，並且確認當前價格不可以低於60均線，否則失去了多頭保護的意義，必須退到下一個時間軸作保護
            #example :: 八小時 ema 30>45>60，但是如果當前價格沒有大於60 MA，代表已經跌破了，必須拉到下一個TARGET_PRIO_Q 2->3
            if((ema30.iloc[-1] > ema45.iloc[-1] > ema60.iloc[-1]) and (ema60.iloc[-1] < float(df['close'].iloc[-1]))):
                if(interval=="1d"):
                    time_slot_1d = True
                elif(interval=="8h"):
                    time_slot_8h = True
                elif(interval=="4h"):
                    time_slot_4h = True
                elif(interval=="1h"):
                    time_slot_1h = True
                else:
                    print("ERROR interval please check your time slot")
                    print("ERROR INFO IS %s" % interval)
                    sys.exit(1)
        else:
            print("df is None , Fetch %s history data fail" % symbol)
            
    return {"symbol": symbol,
            "time_slot_1d": time_slot_1d,
            "time_slot_8h": time_slot_8h,
            "time_slot_4h": time_slot_4h,
            "time_slot_1h": time_slot_1h,
            "strength_score_1d":strength_score_1d,
            "strength_score_8h":strength_score_8h,
            "strength_score_4h":strength_score_4h,
            "strength_score_1h":strength_score_1h}

def process_symbol_crypto_value(symbol,intervals,limits):
    
    '''
    value_only_intervals   = ["15m"]
    value_only_limits      = [30]
    
    這邊只會抓取下殺的VALUE,需要每個15分鐘下去確認這些強勢標的是否有下殺
    '''
    value_more_than_10_average = False
    value_more_than_20_average = False
    
    #這個代表是上漲，因為收盤-開盤是正的
    close_minus_open_positive = True 
    pre_candle = 1

    for interval, limit in zip(intervals, limits):
        #STEP 1. fetch history K line data
        df = get_contract_klines(symbol, interval, limit)

        if df is not None:
            # STEP 2. calc value10 ,value20
            # 因為你是抓取%15==0，代表已經是這一個15分鐘的開頭了，可以去推算說是否前一根成交量，是前前一根10-20根的3-10倍
            value10 = calculate_ma(df['volume'].astype(float), 10)
            value20 = calculate_ma(df['volume'].astype(float), 20)
            print(f"interval: {interval} , Symbol: {symbol}, value10: {value10.iloc[-1-pre_candle]} , value20: {value20[-1-pre_candle]} , value: {df['volume'].iloc[-1-pre_candle]}")

            #STEP 3. MOVING AVERAGE CHECK
            #check ema 30 > 45 > 60，多頭排列，並且確認當前價格不可以低於60均線，否則失去了多頭保護的意義，必須退到下一個時間軸作保護
            #example :: 八小時 ema 30>45>60，但是如果當前價格沒有大於60 MA，代表已經跌破了，必須拉到下一個TARGET_PRIO_Q 2->3
            threshold_value = 3
            if((value10.iloc[-1-pre_candle] * threshold_value) > float(df['volume'].iloc[-1-pre_candle]) and (value20.iloc[-1-pre_candle] * threshold_value) > float(df['volume'].iloc[-1-pre_candle])):
                value_more_than_10_average = False
                value_more_than_20_average = False
            elif((value10.iloc[-1-pre_candle] * threshold_value) < float(df['volume'].iloc[-1-pre_candle]) and (value20.iloc[-1-pre_candle] * threshold_value) > float(df['volume'].iloc[-1-pre_candle])):
                value_more_than_10_average = True
                value_more_than_20_average = False
            elif((value10.iloc[-1-pre_candle] * threshold_value) > float(df['volume'].iloc[-1-pre_candle]) and (value20.iloc[-1-pre_candle] * threshold_value) < float(df['volume'].iloc[-1-pre_candle])):
                value_more_than_10_average = False
                value_more_than_20_average = True
            elif((value10.iloc[-1-pre_candle] * threshold_value) < float(df['volume'].iloc[-1-pre_candle]) and (value20.iloc[-1-pre_candle] * threshold_value) < float(df['volume'].iloc[-1-pre_candle])):
                value_more_than_10_average = True
                value_more_than_20_average = True
            
            #STEP 4. 確認是否下跌，收盤要小於開盤
            close_minus_open_positive = df['close'].iloc[-1-pre_candle] >= df['open'].iloc[-1-pre_candle]
        else:
            print("df is None , Fetch %s history data fail" % symbol)
            
        print(symbol + "----" + df['close'].iloc[-1-pre_candle] + "----" + df['open'].iloc[-1-pre_candle])
            
    return {"symbol": symbol,"value_more_than_10_average": value_more_than_10_average,"value_more_than_20_average": value_more_than_20_average,"volume":df['volume'].iloc[-1-pre_candle] , "close_minus_open_positive":close_minus_open_positive}

def print_target_message(target_prio_q_0,target_prio_q_1,target_prio_q_2,target_prio_q_3,target_prio_q_4_trend_reversal,target_prio_q_5_trend_reversal,target_prio_q_6_trend_reversal,target_prio_q_7_trend_reversal, print_message_to_json_sel , print_message_to_terminal):
    
    # print message and dump json file
    
    if(print_message_to_terminal):    
        print("\n=========================== COMPARE AND SELECT COMPLETE ===========================")
        print("\n")
        print("\n=========================== TARGET_PRIO_0 ===========================")
        print(target_prio_q_0)
        print("\n=========================== TARGET_PRIO_1 ===========================")
        print(target_prio_q_1)
        print("\n=========================== TARGET_PRIO_2 ===========================")
        print(target_prio_q_2)
        print("\n=========================== TARGET_PRIO_3 ===========================")
        print(target_prio_q_3)
        print("\n=========================== TARGET_PRIO_4 ===========================")
        print(target_prio_q_4_trend_reversal)
        print("\n=========================== TARGET_PRIO_5 ===========================")
        print(target_prio_q_5_trend_reversal)
        print("\n=========================== TARGET_PRIO_6 ===========================")
        print(target_prio_q_6_trend_reversal)
        print("\n=========================== TARGET_PRIO_7 ===========================")
        print(target_prio_q_7_trend_reversal)
        #print("\n=========================== TARGET_PRIO_8 ===========================")
        #print(target_prio_q_8_trend_reversal)
        #print("\n=========================== TARGET_PRIO_9 ===========================")
        #print(target_prio_q_9_trend_reversal)
        print("\n=========================== TARGET_PRIO_-1 ===========================")
        print(target_prio_q_minus_one)
    
    if(print_message_to_json_sel):
        
        data = {
            "target_prio_q_0":target_prio_q_0,
            "target_prio_q_1":target_prio_q_1,
            "target_prio_q_2":target_prio_q_2,
            "target_prio_q_3":target_prio_q_3,
            "target_prio_q_4_trend_reversal":target_prio_q_4_trend_reversal,
            "target_prio_q_5_trend_reversal":target_prio_q_5_trend_reversal,
            "target_prio_q_6_trend_reversal":target_prio_q_6_trend_reversal,
            "target_prio_q_7_trend_reversal":target_prio_q_7_trend_reversal
            #"target_prio_q_8_trend_reversal":target_prio_q_8_trend_reversal,
            #"target_prio_q_9_trend_reversal":target_prio_q_9_trend_reversal
        }
        
        json_string = json.dumps(data , indent=4)
        
        with open("scan_target_data.json" , "w") as json_file:
            json_file.write(json_string)
            json_file.close()
def pre_calc_visualize_colored_table(data_1d , data_8h , data_4h , data_1h):
    # 計算出現次數
    all_data = data_1d + data_8h + data_4h + data_1h
    counter = Counter(all_data)

    # 創建表格
    df = pd.DataFrame({
        '1D': data_1d,
        '8H': data_8h,
        '4H': data_4h,
        '1H': data_1h
    })

    # 定義柔和的顏色
    colors = {
        1: '#E0E0E0',   # 淺灰色
        2: '#ADD8E6',   # 淺藍色
        3: '#FFFACD',   # 淺黃色
        4: '#FFC1C1'    # 淺紅色
    }

    # 根據出現次數進行著色
    def get_color(name):
        count = counter[name]
        return colors[count]

    # 創建一個帶有顏色的數據框
    df_colored = df.applymap(lambda x: get_color(x))
    
    return df , df_colored

# 在表格上方添加目前時間和在表格左側添加序列
def visualize_colored_table(df, df_colored):
    fig, ax = plt.subplots(figsize=(12, 8))

    # 隱藏軸
    ax.axis('off')
    ax.axis('tight')
    
    row = [i for i in range(1,11)]
    # 創建表格
    table = ax.table(cellText=df.values, rowLabels=row, colLabels=df.columns, cellLoc='center', loc='center', colWidths=[0.15]*len(df.columns))
    
    # 在表格上方添加目前時間
    plt.text(0.5, 0.75, f"Scan Crypto Strong Target: {current_time}", horizontalalignment='center', verticalalignment='center', transform=ax.transAxes ,fontsize=16, fontweight='bold')
    # owner
    plt.text(0.5, 0.25, f"Po-Jung Chen (pola): asd23065@gmail.com", horizontalalignment='center', verticalalignment='center', transform=ax.transAxes ,fontsize=16, fontweight='bold')

    # 填充顏色
    for i in range(len(df)):
        for j in range(len(df.columns)):
            cell = table[(i+1, j)]
            cell.set_facecolor(df_colored.iloc[i, j])
    
    table.auto_set_font_size(False)
    table.set_fontsize(14)
    table.scale(1.2, 1.2)

    # 調整表格位置
    plt.tight_layout()

    #plt.show()
    plt.savefig('colored_table.png', bbox_inches='tight')
    
    pic_name = 'colored_table.png'
    return pic_name

if __name__ == "__main__":

    # time config
    intervals   = ["1d", "8h", "4h", "1h"]
    limits      = [60, 240, 480, 1440]              
    
    # take value only time config
    value_only_intervals   = ["15m"]
    value_only_limits      = [30]                                

    # target priority_queueu
    target_prio_q_0 = []
    target_prio_q_1 = []
    target_prio_q_2 = []
    target_prio_q_3 = []
    target_prio_q_4 = []
    target_prio_q_5 = []
    target_prio_q_6 = []
    target_prio_q_7 = []
    target_prio_q_4_trend_reversal = []
    target_prio_q_5_trend_reversal = []
    target_prio_q_6_trend_reversal = []
    target_prio_q_7_trend_reversal = []
    target_prio_q_8_trend_reversal = []
    target_prio_q_9_trend_reversal = []
    target_prio_q_minus_one = []
    
    # value increase group
    value_more_than_10_or_20_average  = []
    value_more_than_10_and_20_average = []
    
    #get current time
    current_time = datetime.datetime.now()
    
    #get secret number
    current_dir = os.path.dirname(__file__)
    config_path = os.path.join(current_dir, 'config.ini')
    config = configparser.ConfigParser()
    config.read(config_path)
    
    # code testing
    pola_testing = 0
    
    if(current_time.minute %15 == 0 or pola_testing == 2):
        
        #wait new data
        time.sleep(10) 
        
        #Detect strong stock value at each 15 mins. 
        
        with open('scan_target_data.json','r') as json_file:
            data = json.load(json_file)
            json_file.close()
        
        #預設大盤走勢，給USER自己設定
        symbols = ["BTCUSDT","ETHUSDT"]
        symbols =   symbols + \
                    data["target_prio_q_0"] + \
                    data["target_prio_q_1"] + \
                    data["target_prio_q_2"] + \
                    data["target_prio_q_3"] + \
                    data["target_prio_q_4_trend_reversal"] + \
                    data["target_prio_q_5_trend_reversal"] + \
                    data["target_prio_q_6_trend_reversal"] + \
                    data["target_prio_q_7_trend_reversal"]
                    #data["target_prio_q_8_trend_reversal"] + \
                    #data["target_prio_q_9_trend_reversal"]
        symbols = list(set(symbols))
        
        with ThreadPoolExecutor(max_workers=2) as executor:
            # 提交任務並平行執行
            futures = [executor.submit(process_symbol_crypto_value, symbol, value_only_intervals, value_only_limits) for symbol in symbols]
            
            # 等待所有任務完成
            for future in as_completed(futures):
                result = future.result()
                
                # 如果收盤 > 開盤 ，那就代表現在這個爆量是上漲的，但是我希望是下跌，所以應該要False    
                if((result["value_more_than_10_average"] == True and result["value_more_than_20_average"] == True)  and result["close_minus_open_positive"] == False):
                    value_more_than_10_and_20_average.append(result["symbol"])    
                elif((result["value_more_than_10_average"] == True or result["value_more_than_20_average"] == True)  and result["close_minus_open_positive"] == False):
                    value_more_than_10_or_20_average.append(result["symbol"])
                
                print(result["symbol"] + "-----" + result["volume"])
                
        string_value_more_than_10_or_20_average  = ' , '.join(value_more_than_10_or_20_average)
        string_value_more_than_10_and_20_average = ' , '.join(value_more_than_10_and_20_average)        
        
        send_time = datetime.datetime.now()
        formatted_time = send_time.strftime("%Y-%m-%d %H:%M:%S")
        
        if((len(value_more_than_10_and_20_average) > 0 or len(value_more_than_10_or_20_average) > 0)):
            
            crypto_push_message =   formatted_time   + "\n" + \
                                    "交易所 : 幣安\n" + \
                                    "交易對 : 合約\n" + \
                                    "時間序 : 1hr,4hr,8hr,1d\n" + \
                                    "1. -----15分下殺爆量大於10 and 20----- \n" + \
                                    string_value_more_than_10_and_20_average + "\n" + \
                                    "2. -----15分下殺爆量大於10 or 20----- \n" + \
                                    string_value_more_than_10_or_20_average

            bot_send_msg_to_line_notify(push_content=crypto_push_message)
            
        else:
            crypto_push_message =   formatted_time   + "\n" + \
                                    "沒有強勢幣種下殺在15mins\n"

            bot_send_msg_to_line_notify(push_content=crypto_push_message)
        
    
    #each 4hour detect ones
    if((current_time.hour % 4 == 0 and current_time.minute == 0) or pola_testing == 1):
        
        #wait new data
        time.sleep(10)
        
        # fetch all of trading object 
        symbols = get_contract_assets()
    
        if symbols is not None:
            with ThreadPoolExecutor(max_workers=2) as executor:
                # 提交任務並平行執行
                futures = [executor.submit(process_symbol_crypto, symbol, intervals, limits) for symbol in symbols]

                # 等待所有任務完成
                for future in as_completed(futures):
                    result = future.result()

                    # STEP 4. CONDITION CHECK AND INSERT TO PRIO_Q
                    #PRIO_Q LEVEL 0 = highest  , 3 = lowest , PRIO_0 > PRIO_1 > PRIO_2 > PRIO_3
                    if(  result["time_slot_1d"] == True and result["time_slot_8h"] == True  and result["time_slot_4h"] == True   and result["time_slot_1h"] == True):
                        target_prio_q_0.append(result["symbol"])
                    elif(result["time_slot_1d"] == True and result["time_slot_8h"] == True  and result["time_slot_4h"] == True   and result["time_slot_1h"] == False):
                        target_prio_q_1.append(result["symbol"])
                    elif(result["time_slot_1d"] == True and result["time_slot_8h"] == True  and result["time_slot_4h"] == False  and result["time_slot_1h"] == False):
                        target_prio_q_2.append(result["symbol"])
                    elif(result["time_slot_1d"] == True and result["time_slot_8h"] == False and result["time_slot_4h"] == False  and result["time_slot_1h"] == False):
                        target_prio_q_3.append(result["symbol"])
                        
                    if(  result["time_slot_1d"] == True):
                        target_prio_q_4.append([result["symbol"],result["strength_score_1d"]])
                    if(result["time_slot_8h"] == True):
                        target_prio_q_5.append([result["symbol"],result["strength_score_8h"]])
                    if(result["time_slot_4h"] == True):
                        target_prio_q_6.append([result["symbol"],result["strength_score_4h"]])
                    if(result["time_slot_1h"] == True):
                        target_prio_q_7.append([result["symbol"],result["strength_score_1h"]])
                    

                    #if(result["time_slot_1d"] == False and result["time_slot_8h"] == False and result["time_slot_4h"] == True and result["time_slot_1h"] == False):
                    #    target_prio_q_8_trend_reversal.append(result["symbol"])
                    #if(result["time_slot_1d"] == False and result["time_slot_8h"] == False and result["time_slot_4h"] == True and result["time_slot_1h"] == True):
                    #    target_prio_q_9_trend_reversal.append(result["symbol"])

            target_prio_q_4_trend_reversal = [item[0] for item in sorted(target_prio_q_4, key=lambda x: x[1], reverse=True)[:10]]
            target_prio_q_5_trend_reversal = [item[0] for item in sorted(target_prio_q_5, key=lambda x: x[1], reverse=True)[:10]]
            target_prio_q_6_trend_reversal = [item[0] for item in sorted(target_prio_q_6, key=lambda x: x[1], reverse=True)[:10]]
            target_prio_q_7_trend_reversal = [item[0] for item in sorted(target_prio_q_7, key=lambda x: x[1], reverse=True)[:10]]
            # print your file to message and dump content to json file
            print_target_message(
                                target_prio_q_0,
                                target_prio_q_1,
                                target_prio_q_2,
                                target_prio_q_3,
                                target_prio_q_4_trend_reversal,
                                target_prio_q_5_trend_reversal,
                                target_prio_q_6_trend_reversal,
                                target_prio_q_7_trend_reversal,
                                print_message_to_json_sel = 1 ,
                                print_message_to_terminal = 0)

            string_target_prio_q_0 = ' , '.join(target_prio_q_0)
            string_target_prio_q_1 = ' , '.join(target_prio_q_1)
            string_target_prio_q_2 = ' , '.join(target_prio_q_2)
            string_target_prio_q_3 = ' , '.join(target_prio_q_3)
            string_target_prio_q_4 = ' , '.join(target_prio_q_4_trend_reversal)
            string_target_prio_q_5 = ' , '.join(target_prio_q_5_trend_reversal)
            string_target_prio_q_6 = ' , '.join(target_prio_q_6_trend_reversal)
            string_target_prio_q_7 = ' , '.join(target_prio_q_7_trend_reversal)
            #string_target_prio_q_8 = ' , '.join(target_prio_q_8_trend_reversal)
            #string_target_prio_q_9 = ' , '.join(target_prio_q_9_trend_reversal)

        else:
            print("script get_contract_assets fail please check your internet")
            sys.exit(1)

        #STEP 5. SEND EMAIL AND LINE TO NOTICE MY SELF
        send_time = datetime.datetime.now()
        formatted_time = send_time.strftime("%Y-%m-%d %H:%M:%S")

        crypto_push_message =   formatted_time   + "\n" + \
                                "交易所 : 幣安\n" + \
                                "交易對 : 合約\n" + \
                                "時間序 : 1hr,4hr,8hr,1d\n" + \
                                "1. -----滿足 1hr,4hr,8hr,1d----- \n" + \
                                string_target_prio_q_0 +   "\n" + \
                                "2. -----滿足 4hr,8hr,1d----- \n" + \
                                string_target_prio_q_1 +   "\n" + \
                                "3. -----滿足 8hr,1d----- \n" + \
                                string_target_prio_q_2 +   "\n" + \
                                "4. -----滿足 1d----- \n" + \
                                string_target_prio_q_3 +   "\n" + \
                                "5. -----1D strong crypto----- \n" + \
                                string_target_prio_q_4 +   "\n" + \
                                "6. -----8h strong crypto----- \n" + \
                                string_target_prio_q_5 +   "\n" + \
                                "7. -----4h strong crypto----- \n" + \
                                string_target_prio_q_6 +   "\n" + \
                                "8. -----1h strong crypto---- \n" + \
                                string_target_prio_q_7

        bot_send_msg_to_line_notify(push_content=crypto_push_message)
        
        
        # draw pic and send to line notify
        df , df_colored = pre_calc_visualize_colored_table(
                                target_prio_q_4_trend_reversal,
                                target_prio_q_5_trend_reversal,
                                target_prio_q_6_trend_reversal,
                                target_prio_q_7_trend_reversal)
        pic_name = visualize_colored_table(df=df,df_colored=df_colored)
        bot_send_pic_to_line_notify(pic_name)
        
