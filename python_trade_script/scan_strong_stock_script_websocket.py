import requests
import pandas as pd
import sys

def get_contract_assets():
    url = "https://fapi.binance.com/fapi/v1/exchangeInfo"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        return [asset['symbol'] for asset in data['symbols']]
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

def calculate_ema(series, window):
    return series.ewm(span=window, adjust=False).mean()

if __name__ == "__main__":
    
    # fetch all of trading object 
    symbols_all = get_contract_assets()                       
    symbols     = [s for s in symbols_all if "USDT" in s and s[-4:]=="USDT"]

    # time config
    intervals   = ["1d", "8h", "4h", "1h"]
    limits      = [30, 120, 120, 120]                       

    # target priority_queueu
    target_prio_q_0 = []
    target_prio_q_1 = []
    target_prio_q_2 = []
    target_prio_q_3 = []
    target_prio_q_minus_one = []

    if symbols is not None:
        for symbol in symbols:

            # time_slot checker , initial when calc another crypto
            time_slot_1d = False
            time_slot_8h = False
            time_slot_4h = False
            time_slot_1h = False

            for interval, limit in zip(intervals, limits):
                #STEP 1. fetch history K line data
                df = get_contract_klines(symbol, interval, limit)

                if df is not None:
                    # STEP 2. calc EMA30 ,EMA45 and EMA60
                    ema30 = calculate_ema(df['close'], 30)
                    ema45 = calculate_ema(df['close'], 45)
                    ema60 = calculate_ema(df['close'], 60)
                    #print(f"interval: {interval} , Symbol: {symbol}, EMA30: {ema30.iloc[-1]} , EMA45: {ema45.iloc[-1]} , EMA60: {ema60.iloc[-1]}")

                    #STEP 3. MOVING AVERAGE CHECK
                    if(ema30.iloc[-1] > ema45.iloc[-1] > ema60.iloc[-1]): 
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

            # STEP 4. CONDITION CHECK AND INSERT TO PRIO_Q
            #PRIO_Q LEVEL 0 = highest  , 3 = lowest , PRIO_0 > PRIO_1 > PRIO_2 > PRIO_3
            if(  time_slot_1d == True and time_slot_8h == True  and time_slot_4h == True  and time_slot_1h == True):
                target_prio_q_0.append(symbol)
            elif(time_slot_1d == True and time_slot_8h == True  and time_slot_4h == True  and time_slot_1h == False):
                target_prio_q_1.append(symbol)
            elif(time_slot_1d == True and time_slot_8h == True  and time_slot_4h == False and time_slot_1h == False):
                target_prio_q_2.append(symbol)
            elif(time_slot_1d == True and time_slot_8h == False and time_slot_4h == False and time_slot_1h == False):
                target_prio_q_3.append(symbol)
            else:
                target_prio_q_minus_one.append(symbol)
        
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
        print("\n=========================== TARGET_PRIO_-1 ===========================")
        print(target_prio_q_minus_one)
        

                    