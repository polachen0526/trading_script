from datetime import datetime
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from downloader import CryptoDownloader

##################### CONFIGURATIONS #####################
CURRENT_TIMEZONE = "America/Los_Angeles"
##########################################################

def calc_total_bars(time_interval_array, days):
    bars_dict_array = []
    bars_dict = {
        "5m" : 12 * 24 * days,
        "15m": 4  * 24 * days,
        "30m": 2  * 24 * days,
        "1h" : 24 * days,
        "2h" : 12 * days,
        "4h" : 6  * days,
        "8h" : 3  * days,
        "1d" : 1  * days,
    }
    for time_slot in time_interval_array:
        bars_dict_array.append(bars_dict.get(time_slot))

    return bars_dict_array

def strategy_strong_stock(symbol, time_interval_array,total_days):
    try:
        '''
        find strong stock strategy by pola
        except arrange price of 1hour > 4hour
        except arrange price of 4hour > 8hour
        except arrange price of 8hour > 1day
        '''
        cryptodownloader_server = CryptoDownloader()
        crypto_name, status_1h, crypto_data_1h = cryptodownloader_server.get_crypto(symbol, time_interval=time_interval_array[0], timezone=CURRENT_TIMEZONE)
        crypto_name, status_4h, crypto_data_4h = cryptodownloader_server.get_crypto(symbol, time_interval=time_interval_array[1], timezone=CURRENT_TIMEZONE)
        crypto_name, status_8h, crypto_data_8h = cryptodownloader_server.get_crypto(symbol, time_interval=time_interval_array[2], timezone=CURRENT_TIMEZONE)
        crypto_name, status_1d, crypto_data_1d = cryptodownloader_server.get_crypto(symbol, time_interval=time_interval_array[3], timezone=CURRENT_TIMEZONE)

        status_array      = [status_1h , status_4h , status_8h , status_1d]
        crypto_data_array = [crypto_data_1h , crypto_data_4h , crypto_data_8h , crypto_data_1d]
        
        for time_slot in time_interval_array:
            if status_array[time_slot] == 0:
                if crypto_data_array[time_slot]:
                    print(f"{symbol} fails to get data -> {crypto_data_array[time_slot]}")
                return {"crypto": symbol, "PRIO_Q": -1}
            if crypto_data_array[time_slot].empty:
                return {"crypto": symbol, "PRIO_Q": -1}
            
    except Exception as e:
        print(f"Error in getting {symbol} info: {e}")
        return {"crypto": symbol, "PRIO_Q": -1}
    
    bars_array = calc_total_bars(time_interval_array, total_days)
    for bars in bars_array:
        if bars > 1500 - 60: #因為SMA_60根資料一定要大於60根才可以算，否則就會是NaN，但是最多只能從BINANCE FETCH 1500筆資料，所以最多可以算出1440平均值
            raise ValueError(f"Requesting too many bars. Limitation: 1440 bars. Your are requesting {bars} bars. Please decrease total days.")
    for crypto_data in crypto_data_array:
        if len(crypto_data) < bars + 60:
            return {"crypto": symbol, "PRIO_Q": -1}
    
    print("\n=========================== STEP 1 ===========================")
    # STEP 1. moving average check
    # check time_slot from day -> 8h -> 4h -> 1h
    # check time_slot_cnt 0 == day -> 1 == 8h -> 2 == 4h -> 3 == 1h
    reversd_crypto_data_array = crypto_data_array[::-1]
    reverse_time_slot_cnt = 0
    for reversed_crypto_data in reversd_crypto_data_array:
        moving_average_value_30 = reversed_crypto_data['SMA_30'].values[-1]
        moving_average_value_45 = reversed_crypto_data['SMA_45'].values[-1]
        moving_average_value_60 = reversed_crypto_data['SMA_60'].values[-1]
        print("\n",moving_average_value_30,moving_average_value_45,moving_average_value_60,"\n")
        if(reverse_time_slot_cnt == 0):
            if(moving_average_value_30 > moving_average_value_45 > moving_average_value_60):
                time_slot_1d = True
            else:
                time_slot_1d = False
        elif(reverse_time_slot_cnt == 1):
            if(moving_average_value_30 > moving_average_value_45 > moving_average_value_60):
                time_slot_8h = True
            else:
                time_slot_8h = False
        elif(reverse_time_slot_cnt == 2):
            if(moving_average_value_30 > moving_average_value_45 > moving_average_value_60):
                time_slot_4h = True
            else:
                time_slot_4h = False
        elif(reverse_time_slot_cnt == 3):
            if(moving_average_value_30 > moving_average_value_45 > moving_average_value_60):
                time_slot_1h = True
            else:
                time_slot_1h = False
        # for search another time slot 
        reverse_time_slot_cnt = reverse_time_slot_cnt + 1

    print("\n=========================== STEP 2 ===========================")
    # STEP 2. CONDITION CHECK AND INSERT TO PRIO_Q
    #PRIO_Q LEVEL 0 = highest  , 3 = lowest , PRIO_0 > PRIO_1 > PRIO_2 > PRIO_3
    if(  time_slot_1d == True and time_slot_8h == True  and time_slot_4h == True  and time_slot_1h == True):
        PRIO_Q_SEL = 0
    elif(time_slot_1d == True and time_slot_8h == True  and time_slot_4h == True  and time_slot_1h == False):
        PRIO_Q_SEL = 1
    elif(time_slot_1d == True and time_slot_8h == True  and time_slot_4h == False and time_slot_1h == False):
        PRIO_Q_SEL = 2
    elif(time_slot_1d == True and time_slot_8h == False and time_slot_4h == False and time_slot_1h == False):
        PRIO_Q_SEL = 3
    else:
        PRIO_Q_SEL = -1

    # STEP 3. RETURN CRYPTO_NAME , PRIO_Q_SEL
    return {"crypto": symbol, "PRIO_Q": PRIO_Q_SEL}

if __name__ == '__main__':
    
    # config setting
    crypto_downloader = CryptoDownloader()
    all_cryptos = crypto_downloader.get_all_symbols()
    time_array = ["1h","4h","8h","1d"]
    total_days = 7

    # target priority_queueu
    target_prio_q_0 = []
    target_prio_q_1 = []
    target_prio_q_2 = []
    target_prio_q_3 = []
    target_prio_q_minus_one = []

    print(all_cryptos) #get_all_symbols can get all

    with ThreadPoolExecutor(max_workers=10) as executor:
        future_tasks = [executor.submit(strategy_strong_stock, crypto, time_array, total_days) for crypto in all_cryptos]
        results = [future.result() for future in as_completed(future_tasks)]

    for result in results:
        if(result["PRIO_Q"]==0):
            target_prio_q_0.append(result["crypto"])
        elif(result["PRIO_Q"]==1):
            target_prio_q_1.append(result["crypto"])
        elif(result["PRIO_Q"]==2):
            target_prio_q_2.append(result["crypto"])
        elif(result["PRIO_Q"]==3):
            target_prio_q_3.append(result["crypto"])
        elif(result["PRIO_Q"]==-1):
            target_prio_q_minus_one.append(result["crypto"])
    
    print("\n=========================== COMPARE AND SELECT COMPLETE ===========================")
    print("\n=========================== COMPARE AND SELECT COMPLETE ===========================")
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
