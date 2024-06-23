import matplotlib
matplotlib.use('Agg')  # 使用非GUI的后端
from flask import Flask, request, abort, send_file
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, TemplateSendMessage, ButtonsTemplate, PostbackAction, PostbackEvent, ImageSendMessage
import json
import os
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator
from matplotlib.font_manager import FontProperties
import configparser
from queue import Queue
from threading import Thread

app = Flask(__name__)

# 加载配置文件
def load_config():
    config_path = os.path.join(os.path.dirname(__file__), 'config.ini')
    config = configparser.ConfigParser()
    config.read(config_path)
    return config['credentials']

credentials = load_config()
CHANNEL_ACCESS_TOKEN = credentials['line_CHANNEL_ACCESS_TOKEN']
CHANNEL_SECRET = credentials['line_CHANNEL_SECRET']

# Line bot settings
line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

# 指定中文字体路径
chinese_font_path = 'C:\\Users\\asd23\\OneDrive\\桌面\\python_trade_script\\yumindb.ttf'
chinese_font = FontProperties(fname=chinese_font_path, size=10)
if not chinese_font:
    raise ValueError("No suitable Chinese font found on your system. Please install a Chinese font.")

# 全局任务队列和用户状态
task_queue = Queue()
tasks_progress = {}
user_states = {}
RESP_ALL_USER_DATA_DIR = "RESP_ALL_USER_DATA_DIR"

if not os.path.exists(RESP_ALL_USER_DATA_DIR):
    os.makedirs(RESP_ALL_USER_DATA_DIR)

def get_user_folder(user_id):
    user_folder = os.path.join(RESP_ALL_USER_DATA_DIR, user_id)
    if not os.path.exists(user_folder):
        os.makedirs(user_folder)
    return user_folder

# 文件操作相关函数
def save_tasks_to_file(user_id):
    user_folder = get_user_folder(user_id)
    user_file = os.path.join(user_folder, "tasks.json")
    with open(user_file, 'w', encoding='utf-8') as file:
        json.dump(tasks_progress.get(user_id, {}), file, ensure_ascii=False, indent=4)

def load_tasks_from_file(user_id):
    user_folder = get_user_folder(user_id)
    user_file = os.path.join(user_folder, "tasks.json")
    if os.path.exists(user_file):
        with open(user_file, 'r', encoding='utf-8') as file:
            tasks_progress[user_id] = json.load(file)
    else:
        tasks_progress[user_id] = {}

# 任务操作相关函数
def reset_task(user_id):
    tasks_progress[user_id] = {}
    save_tasks_to_file(user_id)
    return f"所有任務已重置 for user '{user_id}'."

def create_task(user_id, task_name, subtask_name=None, progress=0):
    if user_id not in tasks_progress:
        tasks_progress[user_id] = {}

    if task_name not in tasks_progress[user_id]:
        tasks_progress[user_id][task_name] = {'progress': 0, 'subtasks': {}}

    if subtask_name:
        tasks_progress[user_id][task_name]['subtasks'][subtask_name] = progress
    else:
        tasks_progress[user_id][task_name]['progress'] = progress

    save_tasks_to_file(user_id)
    return f"任務 '{task_name}' 已成功創建/更新 for user '{user_id}'."

def update_task(user_id, task_name, subtask_name, progress=0):
    if user_id not in tasks_progress or task_name not in tasks_progress[user_id]:
        return f"任務 '{task_name}' 不存在 for user '{user_id}'."

    if subtask_name in tasks_progress[user_id][task_name]['subtasks']:
        tasks_progress[user_id][task_name]['subtasks'][subtask_name] = progress
    else:
        return f"子任務 '{subtask_name}' 不存在 under task '{task_name}'."

    save_tasks_to_file(user_id)
    return f"任務 '{task_name}' 的子任務 '{subtask_name}' 已成功更新 for user '{user_id}'."

def delete_task(user_id, task_name=None, subtask_name=None):
    if user_id not in tasks_progress:
        return f"沒有找到任務 for user '{user_id}'."

    if task_name:
        if task_name not in tasks_progress[user_id]:
            return f"任務 '{task_name}' 不存在 for user '{user_id}'."

        if subtask_name == '全刪':
            del tasks_progress[user_id][task_name]
            save_tasks_to_file(user_id)
            return f"任務 '{task_name}' 及其所有子任務已刪除 for user '{user_id}'."

        if subtask_name:
            if subtask_name in tasks_progress[user_id][task_name]['subtasks']:
                del tasks_progress[user_id][task_name]['subtasks'][subtask_name]
                save_tasks_to_file(user_id)
                return f"子任務 '{subtask_name}' 已刪除 under task '{task_name}' for user '{user_id}'."
            else:
                return f"子任務 '{subtask_name}' 不存在 under task '{task_name}'."
        else:
            del tasks_progress[user_id][task_name]
            save_tasks_to_file(user_id)
            return f"任務 '{task_name}' 已刪除 for user '{user_id}'."
    else:
        tasks_progress[user_id] = {}
        save_tasks_to_file(user_id)
        return f"所有任務已刪除 for user '{user_id}'."

def read_task(user_id, task_name=None, subtask_name=None):
    if user_id not in tasks_progress:
        return f"沒有找到任務 for user '{user_id}'."

    if task_name:
        if task_name not in tasks_progress[user_id]:
            return f"任務 '{task_name}' 不存在 for user '{user_id}'."

        task = tasks_progress[user_id][task_name]

        if not subtask_name:
            return json.dumps(task, ensure_ascii=False, indent=4)

        subtask_progress = task['subtasks'].get(subtask_name)
        if subtask_progress is None:
            return f"子任務 '{subtask_name}' 不存在 under task '{task_name}'."

        return json.dumps({subtask_name: subtask_progress}, ensure_ascii=False, indent=4)
    else:
        return json.dumps(tasks_progress[user_id], ensure_ascii=False, indent=4)

# 任務進度圖表繪製
def calculate_main_task_progress(task):
    subtasks = task['subtasks']
    if not subtasks:
        return task['progress']
    return sum(subtasks.values()) / len(subtasks)

def plot_tasks(user_id):
    if user_id not in tasks_progress or not tasks_progress[user_id]:
        return f"沒有找到任務 for user '{user_id}'."

    fig, ax = plt.subplots()
    task_names = []
    task_progress = []
    is_subtask = []

    for task_name, task in tasks_progress[user_id].items():
        main_task_progress = calculate_main_task_progress(task)
        task_names.append(task_name + "----")
        task_progress.append(main_task_progress)
        is_subtask.append(False)
        for subtask_name, subtask_progress in task['subtasks'].items():
            task_names.append("    " + f"  {subtask_name}")
            task_progress.append(subtask_progress)
            is_subtask.append(True)

    y_pos = range(len(task_names))
    colors = ['red' if p < 25 else 'orange' if p < 50 else 'yellow' if p < 75 else 'green' for p in task_progress]

    bars = ax.barh(y_pos, task_progress, align='center', color=colors)
    ax.set_yticks(y_pos)
    ax.set_yticklabels(task_names, fontproperties=chinese_font)
    ax.invert_yaxis()
    ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax.set_xlabel('進度', fontproperties=chinese_font)
    ax.set_title('任務進度', fontproperties=chinese_font)
    ax.set_xlim(0,100)

    for bar, progress, is_sub in zip(bars, task_progress, is_subtask):
        bar.set_hatch('//') if is_sub else bar.set_hatch('')
        ax.text(100, bar.get_y() + bar.get_height()/2, f'{progress}%', va='center', ha='right', color='black', fontproperties=chinese_font)
        

    user_folder = get_user_folder(user_id)
    image_path = os.path.join(user_folder, f"{user_id}_task_progress.png")
    plt.savefig(image_path, bbox_inches='tight')
    plt.close()

    return image_path

# 股票计算相关函数
def calculate_quantity(current_price, loss_percent, profit_percent, total_loss):
    loss_price = current_price * (1 - loss_percent / 100)
    profit_price = current_price * (1 + profit_percent / 100)
    loss_per_coin = current_price - loss_price
    profit_per_coin = profit_price - current_price
    quantity = total_loss / loss_per_coin

    result = (f"当前价格: {current_price}\n"
              f"预期损失价格: {loss_price}\n"
              f"预期盈利价格: {profit_price}\n"
              f"每'股'的损失: {loss_per_coin}\n"
              f"每'股'的盈利: {profit_per_coin}\n"
              f"可以购买的'股數': {quantity}")
    return result

def worker():
    while True:
        task = task_queue.get()
        if task is None:
            break
        func, args = task
        func(*args)
        task_queue.task_done()

def handle_task(user_id, action, params):
    load_tasks_from_file(user_id)
    if action == 'create_task':
        task_name = params.get('task_name')
        subtask_name = params.get('subtask_name')
        progress = params.get('progress', 0)
        message = create_task(user_id, task_name, subtask_name, progress)
    elif action == 'update_task':
        task_name = params.get('task_name')
        subtask_name = params.get('subtask_name')
        progress = params.get('progress', 0)
        message = update_task(user_id, task_name, subtask_name, progress)
    elif action == 'delete_task':
        task_name = params.get('task_name')
        subtask_name = params.get('subtask_name')
        message = delete_task(user_id, task_name, subtask_name)
    elif action == 'reset_task':
        message = reset_task(user_id)
    elif action == 'read_task':
        task_name = params.get('task_name')
        subtask_name = params.get('subtask_name')
        message = read_task(user_id, task_name, subtask_name)
    elif action == 'stock_calculator':
        current_price = params.get('current_price')
        loss_percent = params.get('loss_percent')
        profit_percent = params.get('profit_percent')
        total_loss = params.get('total_loss')
        message = calculate_quantity(current_price, loss_percent, profit_percent, total_loss)
    elif action == 'task_chart':
        message = plot_tasks(user_id)
    else:
        message = "未知操作"
    
    # 回應使用者
    reply_token = params.get('reply_token')
    if action == 'task_chart':
        if os.path.exists(message):
            image_url = f"https://10cb-114-44-40-10.ngrok-free.app/static/{user_id}/{os.path.basename(message)}"
            line_bot_api.reply_message(reply_token, [
                ImageSendMessage(original_content_url=image_url, preview_image_url=image_url),
                TextSendMessage(text="如果還有任意需求，請在對話框中輸入'表單'")
            ])
        else:
            line_bot_api.reply_message(reply_token, [
                TextSendMessage(text="無法生成圖表。"),
                TextSendMessage(text="如果還有任意需求，請在對話框中輸入'表單'")
            ])
    else:
        line_bot_api.reply_message(reply_token, [
            TextSendMessage(text=message),
            TextSendMessage(text="如果還有任意需求，請在對話框中輸入'表單'")
        ])

@app.route("/", methods=['POST'])
def linebot():
    body = request.get_data(as_text=True)
    try:
        json_data = json.loads(body)
        signature = request.headers['X-Line-Signature']
        handler.handle(body, signature)
        print(body)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    user_text = event.message.text

    if user_id in user_states:
        state = user_states[user_id]
        if state['action'] == 'create_task':
            if 'task_name' not in state:
                user_states[user_id]['task_name'] = user_text
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text='請輸入子任務名 (或無):'))
            elif 'subtask_name' not in state:
                user_states[user_id]['subtask_name'] = user_text
                if user_text.strip().lower() == '無':
                    user_states[user_id]['subtask_name'] = None
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text='請輸入進度 (0-100):'))
                else:
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text='請輸入進度 (0-100):'))
            else:
                try:
                    progress = int(user_text)
                    task_name = state['task_name']
                    subtask_name = state['subtask_name']
                    params = {
                        'task_name': task_name,
                        'subtask_name': subtask_name,
                        'progress': progress,
                        'reply_token': event.reply_token
                    }
                    task_queue.put((handle_task, (user_id, 'create_task', params)))
                    del user_states[user_id]
                except ValueError:
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text='請輸入有效的進度值 (0-100):'))
        elif state['action'] == 'update_task':
            if 'task_name' not in state:
                user_states[user_id]['task_name'] = user_text
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text='請輸入子任務名 (必填):'))
            elif 'subtask_name' not in state:
                user_states[user_id]['subtask_name'] = user_text
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text='請輸入新進度 (0-100):'))
            else:
                try:
                    progress = int(user_text)
                    task_name = state['task_name']
                    subtask_name = state['subtask_name']
                    params = {
                        'task_name': task_name,
                        'subtask_name': subtask_name,
                        'progress': progress,
                        'reply_token': event.reply_token
                    }
                    task_queue.put((handle_task, (user_id, 'update_task', params)))
                    del user_states[user_id]
                except ValueError:
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text='請輸入有效的進度值 (0-100):'))
        elif state['action'] == 'delete_task':
            if 'task_name' not in state:
                user_states[user_id]['task_name'] = user_text
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text='請輸入子任務名 (或全刪):'))
            else:
                task_name = state['task_name']
                subtask_name = user_text if user_text else None
                params = {
                    'task_name': task_name,
                    'subtask_name': subtask_name,
                    'reply_token': event.reply_token
                }
                task_queue.put((handle_task, (user_id, 'delete_task', params)))
                del user_states[user_id]
        elif state['action'] == 'stock_calculator':
            if 'current_price' not in state:
                try:
                    current_price = float(user_text)
                    user_states[user_id]['current_price'] = current_price
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text='請輸入預期損失百分比（如5表示5%）:'))
                except ValueError:
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text='請輸入有效的價格:'))
            elif 'loss_percent' not in state:
                try:
                    loss_percent = float(user_text)
                    user_states[user_id]['loss_percent'] = loss_percent
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text='請輸入預期盈利百分比（如30表示30%）:'))
                except ValueError:
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text='請輸入有效的百分比:'))
            elif 'profit_percent' not in state:
                try:
                    profit_percent = float(user_text)
                    user_states[user_id]['profit_percent'] = profit_percent
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text='請輸入預期損失總金額TWD（如2000 - 20000）:'))
                except ValueError:
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text='請輸入有效的百分比:'))
            else:
                try:
                    total_loss = float(user_text)
                    current_price = state['current_price']
                    loss_percent = state['loss_percent']
                    profit_percent = state['profit_percent']
                    params = {
                        'current_price': current_price,
                        'loss_percent': loss_percent,
                        'profit_percent': profit_percent,
                        'total_loss': total_loss,
                        'reply_token': event.reply_token
                    }
                    task_queue.put((handle_task, (user_id, 'stock_calculator', params)))
                    del user_states[user_id]
                except ValueError:
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text='請輸入有效的金額:'))
    else:
        if user_text == '表單':
            buttons_template = TemplateSendMessage(
                alt_text='Buttons template',
                template=ButtonsTemplate(
                    title='選擇一個操作',
                    text='請選擇以下一個操作',
                    actions=[
                        PostbackAction(label='任務操作表單', data='task_operations'),
                        PostbackAction(label='任務圖表顯示', data='task_chart'),
                        PostbackAction(label='股票計算機', data='stock_calculator')
                    ]
                )
            )
            line_bot_api.reply_message(event.reply_token, buttons_template)
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="請輸入 '表單' 來顯示菜單。"))

@handler.add(PostbackEvent)
def handle_postback(event):
    user_id = event.source.user_id
    data = event.postback.data

    load_tasks_from_file(user_id)

    if data == 'task_operations':
        buttons_template = TemplateSendMessage(
            alt_text='Buttons template',
            template=ButtonsTemplate(
                title='選擇一個操作',
                text='請選擇以下一個操作',
                actions=[
                    PostbackAction(label='創建任務', data='create_task'),
                    PostbackAction(label='讀取任務', data='read_task'),
                    PostbackAction(label='更新任務', data='update_task'),
                    PostbackAction(label='刪除任務', data='delete_task')
                ]
            )
        )
        line_bot_api.reply_message(event.reply_token, buttons_template)
    elif data == 'task_chart':
        params = {'reply_token': event.reply_token}
        task_queue.put((handle_task, (user_id, 'task_chart', params)))
    elif data in ['create_task', 'update_task', 'delete_task']:
        user_states[user_id] = {'action': data}
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text='請輸入任務名:'))
    elif data == 'read_task':
        params = {'reply_token': event.reply_token}
        task_queue.put((handle_task, (user_id, 'read_task', params)))
    elif data == 'reset_task':
        params = {'reply_token': event.reply_token}
        task_queue.put((handle_task, (user_id, 'reset_task', params)))
    elif data == 'stock_calculator':
        user_states[user_id] = {'action': 'stock_calculator'}
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text='請輸入當前價格:'))

@app.route('/static/<user_id>/<filename>')
def send_image(user_id, filename):
    return send_file(os.path.join(RESP_ALL_USER_DATA_DIR, user_id, filename), mimetype='image/png')

if __name__ == "__main__":
    worker_thread = Thread(target=worker)
    worker_thread.start()
    app.run(port=8080)

    # 等待队列任务完成
    task_queue.join()

    # 停止工作线程
    task_queue.put(None)
    worker_thread.join()
