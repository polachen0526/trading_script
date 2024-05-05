import requests
import pandas as pd
import sys
import smtplib
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import json
import datetime

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


#################################################################### POST LINE AND EMAIL FUNC #############################################################################
def bot_send_msg_to_line(push_content):

    # set your Channel Access Token 和 Channel Secret
    CHANNEL_ACCESS_TOKEN = 'xxx'
    CHANNEL_SECRET = 'xxx'
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

    for interval, limit in zip(intervals, limits):
        #STEP 1. fetch history K line data
        df = get_contract_klines(symbol, interval, limit)

        if df is not None:
            # STEP 2. calc MA30 ,MA45 and MA60
            ema30 = calculate_ma(df['close'].astype(float), 30)
            ema45 = calculate_ma(df['close'].astype(float), 45)
            ema60 = calculate_ma(df['close'].astype(float), 60)
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
            
    return {"symbol": symbol,"time_slot_1d": time_slot_1d,"time_slot_8h": time_slot_8h,"time_slot_4h": time_slot_4h,"time_slot_1h": time_slot_1h}

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
            if((value10.iloc[-1-pre_candle] * 3) > float(df['volume'].iloc[-1-pre_candle]) and (value20.iloc[-1-pre_candle] * 3) > float(df['volume'].iloc[-1-pre_candle])):
                value_more_than_10_average = False
                value_more_than_20_average = False
            elif((value10.iloc[-1-pre_candle] * 3) < float(df['volume'].iloc[-1-pre_candle]) and (value20.iloc[-1-pre_candle] * 3) > float(df['volume'].iloc[-1-pre_candle])):
                value_more_than_10_average = True
                value_more_than_20_average = False
            elif((value10.iloc[-1-pre_candle] * 3) > float(df['volume'].iloc[-1-pre_candle]) and (value20.iloc[-1-pre_candle] * 3) < float(df['volume'].iloc[-1-pre_candle])):
                value_more_than_10_average = False
                value_more_than_20_average = True
            elif((value10.iloc[-1-pre_candle] * 3) < float(df['volume'].iloc[-1-pre_candle]) and (value20.iloc[-1-pre_candle] * 3) < float(df['volume'].iloc[-1-pre_candle])):
                value_more_than_10_average = True
                value_more_than_20_average = True
            
            #STEP 4. 確認是否下跌，收盤要小於開盤
            close_minus_open_positive = df['close'].iloc[-1-pre_candle] >= df['open'].iloc[-1-pre_candle]
        else:
            print("df is None , Fetch %s history data fail" % symbol)
            
        print(symbol + "----" + df['close'].iloc[-1-pre_candle] + "----" + df['open'].iloc[-1-pre_candle])
            
    return {"symbol": symbol,"value_more_than_10_average": value_more_than_10_average,"value_more_than_20_average": value_more_than_20_average,"volume":df['volume'].iloc[-1-pre_candle] , "close_minus_open_positive":close_minus_open_positive}

def print_target_message(target_prio_q_0,target_prio_q_1,target_prio_q_2,target_prio_q_3,target_prio_q_4_trend_reversal,target_prio_q_5_trend_reversal , print_message_to_json_sel , print_message_to_terminal):
    
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
        print("\n=========================== TARGET_PRIO_-1 ===========================")
        print(target_prio_q_minus_one)
    
    if(print_message_to_json_sel):
        
        data = {
            "target_prio_q_0":target_prio_q_0,
            "target_prio_q_1":target_prio_q_1,
            "target_prio_q_2":target_prio_q_2,
            "target_prio_q_3":target_prio_q_3,
            "target_prio_q_4_trend_reversal":target_prio_q_4_trend_reversal,
            "target_prio_q_5_trend_reversal":target_prio_q_5_trend_reversal
        }
        
        json_string = json.dumps(data , indent=4)
        
        with open("scan_target_data.json" , "w") as json_file:
            json_file.write(json_string)
            json_file.close()

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
    target_prio_q_4_trend_reversal = [] # 8hr,4hr,1hr
    target_prio_q_5_trend_reversal = [] # 4hr,1hr
    target_prio_q_minus_one = []
    
    # value increase group
    value_more_than_10_or_20_average  = []
    value_more_than_10_and_20_average = []
    
    #get current time
    current_time = datetime.datetime.now()
    
    # code testing
    pola_testing = 0
    
    if(current_time.minute %15 == 0 or pola_testing == 1):
        
        #Detect strong stock value at each 15 mins. 
        
        with open('scan_target_data.json','r') as json_file:
            data = json.load(json_file)
            json_file.close()
        
        symbols = []
        symbols = symbols + data["target_prio_q_0"] + data["target_prio_q_1"] + data["target_prio_q_2"] + data["target_prio_q_3"]
        
        with ThreadPoolExecutor(max_workers=2) as executor:
            # 提交任務並平行執行
            futures = [executor.submit(process_symbol_crypto_value, symbol, value_only_intervals, value_only_limits) for symbol in symbols]
            
            # 等待所有任務完成
            for future in as_completed(futures):
                result = future.result()
                
                # 如果收盤 > 開盤 ，那就代表現在這個爆量是上漲的，但是我希望是下跌，所以應該要False    
                if(result["value_more_than_10_average"] == True and result["value_more_than_20_average"] == True  and result["close_minus_open_positive"] == False):
                    value_more_than_10_and_20_average.append(result["symbol"])    
                elif(result["value_more_than_10_average"] == True or result["value_more_than_20_average"] == True  and result["close_minus_open_positive"] == False):
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

            bot_send_msg_to_line(push_content=crypto_push_message)
            
        else:
            crypto_push_message =   formatted_time   + "\n" + \
                                    "沒有強勢幣種下殺在15mins\n"

            bot_send_msg_to_line(push_content=crypto_push_message)
        
    
    #each 4hour detect ones
    if((current_time.hour % 4 == 0 and current_time.minute == 0) or pola_testing == 1):
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
                    elif(result["time_slot_1d"] == True and result["time_slot_8h"] == True  and result["time_slot_4h"] == False  ):
                        target_prio_q_2.append(result["symbol"])
                    elif(result["time_slot_1d"] == True and result["time_slot_8h"] == False ):
                        target_prio_q_3.append(result["symbol"])
                    else:
                        target_prio_q_minus_one.append(result["symbol"])

                    if(result["time_slot_1d"] == True and result["time_slot_8h"] == False and result["time_slot_4h"] == True and result["time_slot_1h"] == False):
                        target_prio_q_4_trend_reversal.append(result["symbol"])
                    if(result["time_slot_1d"] == True and result["time_slot_8h"] == False and result["time_slot_4h"] == True and result["time_slot_1h"] == True):
                        target_prio_q_5_trend_reversal.append(result["symbol"])

            # print your file to message and dump content to json file
            print_target_message(target_prio_q_0,target_prio_q_1,target_prio_q_2,target_prio_q_3,target_prio_q_4_trend_reversal,target_prio_q_5_trend_reversal,print_message_to_json_sel = 1 , print_message_to_terminal = 0)

            string_target_prio_q_0 = ' , '.join(target_prio_q_0)
            string_target_prio_q_1 = ' , '.join(target_prio_q_1)
            string_target_prio_q_2 = ' , '.join(target_prio_q_2)
            string_target_prio_q_3 = ' , '.join(target_prio_q_3)
            string_target_prio_q_4 = ' , '.join(target_prio_q_4_trend_reversal)
            string_target_prio_q_5 = ' , '.join(target_prio_q_5_trend_reversal)

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
                                "5. -----反轉且有機會 1d,4hr----- \n" + \
                                string_target_prio_q_4 +   "\n" + \
                                "6. -----反轉且強勢 1d,4hr,1hr----- \n" + \
                                string_target_prio_q_5

        bot_send_msg_to_line(push_content=crypto_push_message)
