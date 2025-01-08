from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage, 
    FollowEvent, PostbackEvent, TemplateSendMessage,
    ButtonsTemplate, PostbackTemplateAction, MessageTemplateAction,
    ConfirmTemplate, MessageAction, URIAction, ImageSendMessage,
    CarouselColumn, CarouselTemplate, ImageMessage, FlexSendMessage
)
from datetime import datetime, date
import os
import base64
import openai
from io import BytesIO
from PIL import Image
from dotenv import load_dotenv

# 載入環境變數
load_dotenv()

# Line Bot 初始化
app = Flask(__name__)
line_bot_api = LineBotApi(os.getenv('LINE_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_SECRET'))

# 使用者資料儲存 (實際應用中建議使用資料庫)
user_profiles = {}

# 儲存用戶的飲食建議流程選擇
user_diet_suggestion_flow = {}

# 跳過系統產生的提示訊息
skip_text_message = set()

# 初始化函數
def initialize_daily_tracker(daily_calories):
    return {
        'total_calories': daily_calories,
        'consumed_calories': 0,
        'food_log': [],
        'date': date.today()
    }

# 新增食物記錄
def add_food_log(user_id, food_name, calories):
    today = date.today()
    daily_tracker = user_profiles[user_id]['daily_tracker']
    
    # 如果是新的一天，重新初始化
    if daily_tracker['date'] != today:
        daily_tracker = initialize_daily_tracker(user_profiles[user_id]['daily_calories'])
    
    # 檢查是否超過每日熱量
    if daily_tracker['consumed_calories'] + calories > daily_tracker['total_calories']:
        return False
    
    daily_tracker['consumed_calories'] += calories
    daily_tracker['food_log'].append({
        'name': food_name,
        'calories': calories,
        'time': datetime.now().strftime("%H:%M")
    })
    
    return True

def remove_food_log(user_id, food_name):
    daily_tracker = user_profiles[user_id]['daily_tracker']
    
    # 移除食物記錄
    for food in daily_tracker['food_log']:
        if food['name'] == food_name:
            daily_tracker['consumed_calories'] -= food['calories']
            daily_tracker['food_log'].remove(food)
            return True
    
    return False

def generate_diet_plan(selection_prompt):
    openai.api_key = os.getenv('OPENAI_API_KEY')

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages = [
                {"role": "system", 
                  "content": """你是一位營養師，為客戶設計繁體中文飲食菜單，
                    菜單的總熱量需滿足客戶所述的需求熱量，熱量範圍可以在需求熱量正負10%以內。
                    根據客戶的需求嚴格按照以下格式提供飲食建議：
                    <早餐/午餐/晚餐/點心/宵夜>:
                    -<食物名稱><數量/單位>:<食物熱量>大卡
                    -<食物名稱><數量/單位>:<食物熱量>大卡
                    ... 
                    總熱量:<總熱量>大卡
                    ...
                    菜單總熱量:<總熱量>大卡
                    針對菜單的營養價值做簡短描述。"""},
                {"role": "user", "content": selection_prompt}
                ], 
            temperature = 0.7,
            top_p = 0.2,
            stream = False,
        )

    except Exception as e:
        print(f"OpenAI API Error: {e}")
        return f"目前無法生成飲食建議，請稍後再試。"

    return response.choices[0].message.content

def start_diet_suggestion_flow(user_id):
    '''
    初始化飲食建議流程
    '''
    user_diet_suggestion_flow[user_id] = {
        'stage': 'meal_type',
        'selections': {}
    }

    # 用餐方式
    meal_type_template = CarouselTemplate(
        columns = [
            CarouselColumn(
                title='用餐方式',
                text='選擇用餐方式',
                actions=[
                    PostbackTemplateAction(label='外食', text='外食', data='meal_type_外食'),
                    PostbackTemplateAction(label='自行烹調', text='自行烹調', data='meal_type_自行烹調')
                ]
            )
        ]
    )

    template_message = TemplateSendMessage(
        alt_text='選擇用餐方式',
        template=meal_type_template
    )
    
    return template_message


def handle_diet_suggestion_flow(event, user_id, postback_data):
    """
    處理飲食建議流程的各個階段
    """
    if user_id not in user_diet_suggestion_flow:
        user_diet_suggestion_flow[user_id] = {
            'stage': 'meal_type',
            'selections': {}
        }

    flow_state = user_diet_suggestion_flow.get(user_id, {})
    
    if flow_state.get('stage') == 'meal_type':
        # 用餐方式選擇
        flow_state['selections']['meal_type'] = postback_data.split('_')[-1]
        flow_state['stage'] = 'cuisine_style'
        
        # 餐點風格選擇
        cuisine_template = CarouselTemplate(columns=[
            CarouselColumn(
                thumbnail_image_url='https://i.pinimg.com/736x/d3/42/1f/d3421fedf1f7648ca7c7f1879c397c4b.jpg',
                title='美式料理',
                text='如:漢堡、薯條、炸雞等',
                actions=[PostbackTemplateAction(label='選擇', text='美式', data='cuisine_美式')]
            ),
            CarouselColumn(
                thumbnail_image_url='https://i.pinimg.com/736x/ac/a8/f8/aca8f8463de190748b4505cdacce48eb.jpg',
                title='日式料理',
                text='如:壽司、拉麵、刺身等',
                actions=[PostbackTemplateAction(label='選擇', text='日式', data='cuisine_日式')]
            ),
            CarouselColumn(
                thumbnail_image_url='https://i.pinimg.com/736x/b4/62/b2/b462b28ecef0582be9f82ccb73371eaa.jpg',
                title='中式料理',
                text='如:炒飯、麵食、蛤蠣絲瓜等',
                actions=[PostbackTemplateAction(label='選擇', text='中式', data='cuisine_中式')]
            ),
            CarouselColumn(
                thumbnail_image_url='https://i.pinimg.com/736x/6b/8a/6e/6b8a6e33f4d5923047a04a09e29b8289.jpg',
                title='義式料理',
                text='如:義大利麵、披薩、焗烤等',
                actions=[PostbackTemplateAction(label='選擇', text='義式', data='cuisine_義式')]
            ),
            CarouselColumn(
                thumbnail_image_url='https://i.pinimg.com/736x/fd/ed/ea/fdedea6e3c56c7ec485b09b30fa8f816.jpg',
                title='韓式料理',
                text='如:泡菜、烤肉、石鍋拌飯等',
                actions=[PostbackTemplateAction(label='選擇', text='韓式', data='cuisine_韓式')]
            ),
            CarouselColumn(
                thumbnail_image_url='https://i.pinimg.com/736x/67/28/2f/67282ff1cecfd27c047e090813f221b4.jpg',
                title='泰式料理',
                text='如:打拋豬、綠咖哩、椒麻雞等',
                actions=[PostbackTemplateAction(label='選擇', text='泰式', data='cuisine_泰式')]
            )
        ])
        
        template_message = TemplateSendMessage(
            alt_text='選擇餐點風格',
            template=cuisine_template
        )
        
        return template_message
    
    elif flow_state.get('stage') == 'cuisine_style':
        # 餐點風格選擇
        flow_state['selections']['cuisine_style'] = postback_data.split('_')[-1]
        flow_state['stage'] = 'diet_requirement'
        
        # 飲食需求選擇
        requirement_template = CarouselTemplate(columns=[
            CarouselColumn(
                thumbnail_image_url='https://i.pinimg.com/736x/d4/0f/a4/d40fa452569e889d0b80502560212bfd.jpg',
                title='減重飲食',
                text='例如少油少鹽的清淡飲食',
                actions=[PostbackTemplateAction(label='選擇', text='減重', data='requirement_減重')]
            ),
            CarouselColumn(
                thumbnail_image_url='https://i.pinimg.com/736x/86/52/5c/86525c07fd58a8cc170ef4079a3a9bc9.jpg',
                title='高蛋白飲食',
                text='富含豐富蛋白質，適合增肌時期或運動後的人',
                actions=[PostbackTemplateAction(label='選擇', text='高蛋白', data='requirement_高蛋白')]
            ),
            CarouselColumn(
                thumbnail_image_url='https://i.pinimg.com/736x/c0/56/b7/c056b77c2c472ca12aee47211ea10ab4.jpg',
                title='均衡飲食',
                text='各類食物均衡攝取',
                actions=[PostbackTemplateAction(label='選擇', text='均衡', data='requirement_均衡')]
            ),
            CarouselColumn(
                thumbnail_image_url='https://i.pinimg.com/736x/1c/3c/1b/1c3c1b4b3604b307a99474e52d8a201e.jpg',
                title='素食飲食',
                text='適合素食者，不含葷食',
                actions=[PostbackTemplateAction(label='選擇', text='素食', data='requirement_素食')]
            ),
            CarouselColumn(
                thumbnail_image_url='https://img.shoplineapp.com/media/image_clips/668b7145948b3100167dac7a/original.jpg?1720414532',
                title='無麩質飲食',
                text='適合麩質過敏者，不含小麥、大麥、麥麩等',
                actions=[PostbackTemplateAction(label='選擇', text='無麩質', data='requirement_無麩質')]
            )
        ])
        
        template_message = TemplateSendMessage(
            alt_text='選擇飲食需求',
            template=requirement_template
        )
        
        return template_message
    
    elif flow_state.get('stage') == 'diet_requirement':
        # 飲食需求選擇
        flow_state['selections']['diet_requirement'] = postback_data.split('_')[-1]
        flow_state['stage'] = 'meal_time'
        
        # 用餐時間選擇
        meal_time_template = CarouselTemplate(columns=[
            CarouselColumn(
                thumbnail_image_url='https://i.pinimg.com/736x/c3/8c/4c/c38c4c218cbf7dacf09d6aacd9a6c3ef.jpg',
                title='早餐',
                text='選擇早餐菜單',
                actions=[PostbackTemplateAction(label='選擇', text='早餐', data='meal_time_早餐')]
            ),
            CarouselColumn(
                thumbnail_image_url='https://i.pinimg.com/736x/57/58/6f/57586f877369922c24ccf770e5a1e665.jpg',
                title='午餐',
                text='選擇午餐菜單',
                actions=[PostbackTemplateAction(label='選擇', text='午餐', data='meal_time_午餐')]
            ),
            CarouselColumn(
                thumbnail_image_url='https://i.pinimg.com/736x/f3/4a/2c/f34a2c2aef5c82f1549bb6ae52579aaf.jpg',
                title='晚餐',
                text='選擇晚餐菜單',
                actions=[PostbackTemplateAction(label='選擇', text='晚餐', data='meal_time_晚餐')]
            ),
            CarouselColumn(
                thumbnail_image_url='https://i.pinimg.com/736x/3e/70/1a/3e701a24d91eeee687e4a7798a6dc702.jpg',
                title='點心',
                text='選擇點心菜單',
                actions=[PostbackTemplateAction(label='選擇', text='點心', data='meal_time_點心')]
            ),
            CarouselColumn(
                thumbnail_image_url='https://i.pinimg.com/736x/66/5f/c5/665fc5e4e0f24744369a445215e3fb7c.jpg',
                title='宵夜',
                text='選擇宵夜菜單',
                actions=[PostbackTemplateAction(label='選擇', text='宵夜', data='meal_time_宵夜')]
            ),
            CarouselColumn(
                thumbnail_image_url='https://i.pinimg.com/736x/50/48/7f/50487fadf6c16916442f8e3846c22e0f.jpg',
                title='一日菜單',
                text='選擇一日菜單',
                actions=[PostbackTemplateAction(label='選擇', text='一日菜單', data='meal_time_一日菜單')]
            )
        ])
        
        template_message = TemplateSendMessage(
            alt_text='選擇用餐時間',
            template=meal_time_template
        )
        
        return template_message
    
    elif flow_state.get('stage') == 'meal_time':
        # 用餐時間選擇
        flow_state['selections']['meal_time'] = postback_data.split('_')[-1]
        
        # 如果不是一日菜單，要求輸入熱量
        if flow_state['selections']['meal_time'] != '一日菜單':
            flow_state['stage'] = 'calories'
            return TextSendMessage(text="請輸入您預計攝取的熱量(大卡)")
        else:
            flow_state['stage'] = 'additional_requirements'
            return TextSendMessage(text="請輸入其他特殊飲食需求(無特殊需求請輸入「無」)")
    
    elif flow_state.get('stage') == 'calories':
        # 熱量輸入
        try:
            calories = float(event.message.text)
            flow_state['selections']['calories'] = calories
            flow_state['stage'] = 'additional_requirements'
            return TextSendMessage(text="請輸入其他特殊飲食需求(無特殊需求請輸入「無」)")
        except ValueError:
            return TextSendMessage(text="請輸入有效的數字！")
    
    elif flow_state.get('stage') == 'additional_requirements':
        # 其他特殊需求
        flow_state['selections']['additional_requirements'] = event.message.text
        flow_state['stage'] = 'complete'
        
        # 準備OpenAI API調用的提示詞
        selections = flow_state['selections']
        prompt = (
            f"請為一位想要{selections['diet_requirement']}的客戶"
            f"提供一份{selections['meal_time']}的{selections['cuisine_style']}風格菜單。"
            f"飲食方式為{selections['meal_type']}，"
        )
        
        if selections['meal_time'] != '一日菜單':
            prompt += f"客戶需求攝取熱量為{selections['calories']}大卡"
        else:
            prompt += f"客戶需求攝取熱量為{user_profiles[user_id]['daily_tracker']['total_calories']}大卡"
        
        prompt += f"其他特殊需求：{selections['additional_requirements']}。"
        prompt += f"需要付上每一項餐點的熱量，並於最後告知這份菜單的總熱量。"

        
        
        # 呼叫OpenAI API生成飲食建議
        try:
            line_bot_api.push_message(
                user_id,
                TextSendMessage(text="🔄正在生成飲食建議，請稍後...")
            )
            diet_plan = generate_diet_plan(prompt)
            return TextSendMessage(text=diet_plan)
        except Exception as e:
            return TextSendMessage(text="❌無法生成飲食建議，請稍後再試。")


# 驗證編輯的輸入是否合法
def validate_edit_input(user_id, item, new_value):
    """
    驗證編輯的輸入是否合法
    """    
    try:
        if item == '目標':
            goal_map = {'1': '增肌', '2': '減重', '3': '維持體重'}
            if new_value in goal_map:
                return goal_map[new_value]
            return None
        
        elif item == '性別':
            if new_value in ['男', '女']:
                return new_value
            return None
        
        elif item == '年齡':
            age = int(new_value)
            if 10 <= age <= 100:
                return age
            return None
        
        elif item == '身高':
            height = float(new_value)
            if 100 <= height <= 250:
                return height
            return None
        
        elif item == '體重':
            weight = float(new_value)
            if 30 <= weight <= 120:
                return weight
            return None
        
        elif item == '活動量':
            activity_map = {
                '1': '久坐', 
                '2': '輕度活動', 
                '3': '中度活動', 
                '4': '高度活動', 
                '5': '非常活躍'
            }
            if new_value in activity_map:
                return activity_map[new_value]
            return None
        
    except ValueError:
        return None

# 計算基礎代謝率 (BMR) 的函數
def calculate_bmr(gender, age, height, weight):
    """
    使用 Harris-Benedict 公式計算基礎代謝率
    """
    if gender == '男':
        bmr = (9.99 * weight) + (6.25 * height) - (4.92 * age) + 5
    else:  # 女
        bmr = (9.99 * weight) + (6.25 * height) - (4.92 * age) - 161
    
    return round(bmr, 2)

# 計算每日推薦熱量攝取
def calculate_daily_calories(bmr, activity_level, goal):
    """
    根據活動量級別和目標計算每日推薦熱量
    """
    activity_multipliers = {
        '久坐': 1.2,
        '輕度活動': 1.375,
        '中度活動': 1.55,
        '高度活動': 1.725,
        '非常活躍': 1.9
    }
    
    daily_calories = bmr * activity_multipliers.get(activity_level, 1.2)
    
    # 根據目標調整熱量
    if goal == '增肌':
        daily_calories += 250  # 增加250卡路里
    elif goal == '減重':
        daily_calories *= 0.85  # 減少15%熱量
    
    return round(daily_calories, 2)

def compress_image(image_data, max_size_mb=10):
    """
    壓縮圖片至指定大小以下
    :param image_data: 原始圖片的二進制數據
    :param max_size_mb: 最大目標大小（MB）
    :return: 壓縮後的圖片數據（bytes）
    """
    # 將二進制數據轉換為 PIL Image
    img = Image.open(BytesIO(image_data))
    
    # 初始品質參數
    quality = 95
    output = BytesIO()
    
    # 如果是 PNG，轉換為 JPEG
    if img.format == 'PNG':
        # 如果有透明通道，先將背景轉為白色
        if img.mode in ('RGBA', 'LA'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[-1])
            img = background
        elif img.mode != 'RGB':
            img = img.convert('RGB')
    
    # 壓縮圖片直到大小小於目標大小
    while True:
        output = BytesIO()
        img.save(output, format='JPEG', quality=quality)
        size_mb = len(output.getvalue()) / (1024 * 1024)
        
        if size_mb <= max_size_mb or quality <= 5:
            break
        
        quality -= 5
    
    return output.getvalue()

@app.post("/")
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        print("電子簽章錯誤, 請檢查密鑰是否正確？")
        abort(400)

    return 'OK'

@handler.add(FollowEvent)
def handle_follow(event):
    """
    使用者第一次加入機器人時的歡迎訊息和目標選擇
    """
    user_id = event.source.user_id
    
    # 初始化使用者資料
    user_profiles[user_id] = {
        'setup_stage': 'goal'
    }
    
    
    button_template = ButtonsTemplate(
        title = "歡迎使用Meal Mate！",
        text = '請選擇您的目標',
        actions = [
            PostbackTemplateAction(label='增肌', text = '增肌', data='goal_增肌'),
            PostbackTemplateAction(label='減重', text = '減重', data='goal_減重'),
            PostbackTemplateAction(label='維持體重', text = '維持體重', data='goal_維持體重')
        ]
    )

    template_message = TemplateSendMessage(alt_text= '請選擇目標', template=button_template)

    line_bot_api.reply_message(event.reply_token, template_message)

@handler.add(MessageEvent, message = ImageMessage)
def handle_image(event):
    user_id = event.source.user_id
    try:
        line_bot_api.push_message(user_id, TextSendMessage(text="🔄正在分析圖片，請稍後..."))
        message_content = line_bot_api.get_message_content(event.message.id)

        image_data = message_content.content

        compressed_image = compress_image(image_data, max_size_mb=10)

        image_base64 = base64.b64encode(compressed_image).decode('utf-8')

        # 使用 OpenAI API 進行圖像分類
        openai.api_key = os.getenv('OPENAI_API_KEY')
        response = openai.ChatCompletion.create(
            model = "gpt-4o",
            messages = [
                {"role": "system", "content": """你是一位專業的營養師，專門分析食物照片並估算熱量。
                請依照以下格式回覆：
                1. 食物名稱：[辨識出的食物名稱]
                2. 份量估計：[估計的份量，例如：一碗、100克等]
                3. 熱量估計：[照片中每種食物估計熱量] 大卡 (ex: -白飯: 約320大卡\n -炒青菜: 約50大卡... -總熱量: 約370大卡)
                4. 營養建議：[簡短的營養建議]

                請盡可能準確估計，如果照片無法清楚判斷，請說明原因。"""},
                {"role": "user", "content": [
                    {"type": "text", "text": "請幫我估計這張圖片食物的熱量。"},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}}
                ]}
            ],
            temperature = 0.3,
            top_p = 0.2,
        )
        reply_text = response.choices[0].message.content
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
    except Exception as e:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"❌分析圖片時發生錯誤，請稍後再試。(Error: {str(e)})"))
    

@handler.add(PostbackEvent)
def handle_postback(event):
    """處理按鈕回調"""
    user_id = event.source.user_id
    data = event.postback.data
    
    if data.startswith('goal_'):
        goal = data.split('_')[1]

        # 跳過系統產生的提示訊息
        skip_text_message.add(goal)

        user_profiles[user_id]['goal'] = goal
        user_profiles[user_id]['setup_stage'] = 'gender'
        
        # 使用確認模板詢問性別
        confirm_template = ConfirmTemplate(
            text='請選擇您的性別:',
            actions=[
                PostbackTemplateAction(
                    label='男性',
                    text = '男性',
                    data='gender_男'
                ),
                PostbackTemplateAction(
                    label='女性',
                    text = '女性',
                    data='gender_女'
                )
            ]
        )
        
        template_message = TemplateSendMessage(
            alt_text='請選擇性別',
            template=confirm_template
        )
        
        line_bot_api.reply_message(event.reply_token, template_message)
    
    elif data.startswith('gender_'):
        gender = data.split('_')[1]

        skip_text_message.add(f"{gender}性")

        user_profiles[user_id]['gender'] = gender
        user_profiles[user_id]['setup_stage'] = 'age'
        
        line_bot_api.reply_message(
            event.reply_token, 
            TextSendMessage(text="請輸入您的年齡(數字)")
        )
    
    elif data.startswith('activity_'):
        activity_map = {
            '1': '久坐',
            '2': '輕度活動',
            '3': '中度活動',
            '4': '高度活動',
            '5': '非常活躍'
        }
        activity_level = activity_map[data.split('_')[1]]
        user_profiles[user_id]['activity_level'] = activity_level
        
        # 跳過系統產生的提示訊息
        skip_text_message.add(activity_level)

        # 計算基礎代謢率和每日推薦熱量
        profile = user_profiles[user_id]
        bmr = calculate_bmr(
            profile['gender'],
            profile['age'],
            profile['height'],
            profile['weight']
        )
        daily_calories = calculate_daily_calories(
            bmr,
            profile['activity_level'],
            profile['goal']
        )
        
        # 建立結果訊息
        result_message = (
            f"您的基本資料:\n"
            f"目標: {profile['goal']}\n"
            f"性別: {profile['gender']}\n"
            f"年齡: {profile['age']} 歲\n"
            f"身高: {profile['height']} 公分\n"
            f"體重: {profile['weight']} 公斤\n"
            f"活動量: {profile['activity_level']}\n\n"
            f"您的基礎代謝率(BMR): {round(bmr, 2)} 大卡\n"
            f"建議每日熱量攝取: {round(daily_calories, 2)} 大卡\n\n"
            "現在您可以開始記錄每日飲食了！ (輸入「Help」可查看指令)"
        )
        
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=result_message)
        )
        
        # 重置設置階段並初始化追蹤器
        user_profiles[user_id]['setup_stage'] = 'ready'
        user_profiles[user_id]['daily_tracker'] = initialize_daily_tracker(daily_calories)

    elif data == '開始飲食建議':
        template_message = start_diet_suggestion_flow(user_id)
        line_bot_api.reply_message(event.reply_token, template_message)
    elif data == '取消飲食建議':
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="已取消飲食建議流程"))
    elif data.startswith('meal_type_') or data.startswith('cuisine_') or \
         data.startswith('requirement_') or data.startswith('meal_time_'):
        skip_text_message.add(data.split('_')[-1])
        template_message = handle_diet_suggestion_flow(event, user_id, data)
        line_bot_api.reply_message(event.reply_token, template_message)
    elif data.startswith('edit_'):
        item = data.split('_')[1]
        value = data.split('_')[2]
        if(item == "goal"):
            try:
                user_profiles[user_id]['goal'] = value  
                skip_text_message.add(value)
                # 更新每日推薦熱量
                profile = user_profiles[user_id]
                bmr = calculate_bmr(
                    profile["gender"], profile["age"], profile["height"], profile["weight"]
                )
                daily_calories = calculate_daily_calories(
                    bmr, profile["activity_level"], profile["goal"]
                )
                user_profiles[user_id]["daily_tracker"]["total_calories"] = daily_calories
                result_message = f"目標已更新為: { value }"
            except:
                result_message = "無法更新目標"
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=result_message))
        elif(item == "activity"):
            try:
                activity_map = {
                    '1': '久坐',
                    '2': '輕度活動',
                    '3': '中度活動',
                    '4': '高度活動',
                    '5': '非常活躍'
                }
                user_profiles[user_id]['activity_level'] = activity_map[value]
                skip_text_message.add(activity_map[value])
                # 更新每日推薦熱量
                profile = user_profiles[user_id]
                bmr = calculate_bmr(
                    profile["gender"], profile["age"], profile["height"], profile["weight"]
                )
                daily_calories = calculate_daily_calories(
                    bmr, profile["activity_level"], profile["goal"]
                )
                user_profiles[user_id]["daily_tracker"]["total_calories"] = daily_calories
                result_message = f"活動量已更新為: {activity_map[value]}"
            except:
                result_message = "無法更新活動量"
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=result_message))



@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    message_text = event.message.text.strip()

    if message_text in skip_text_message:
        skip_text_message.remove(message_text)
        return
    
    # 檢查是否已存在用戶資料
    if user_id not in user_profiles:
        user_profiles[user_id] = {'setup_stage': 'goal'}
        buttons_template = ButtonsTemplate(
            title='歡迎使用Meal Mate！',
            text='請選擇您的目標:',
            actions=[
                PostbackTemplateAction(
                    label='增肌',
                    text = '增肌',
                    data='goal_增肌'
                ),
                PostbackTemplateAction(
                    label='減重',
                    text = '減重',
                    data='goal_減重'
                ),
                PostbackTemplateAction(
                    label='維持體重',
                    text = '維持體重',
                    data='goal_維持體重'
                )
            ]
        )
        template_message = TemplateSendMessage(
            alt_text='請選擇目標',
            template=buttons_template
        )
        line_bot_api.reply_message(event.reply_token, template_message)
        return
    
    # 根據設置階段處理不同的輸入
    current_stage = user_profiles[user_id].get('setup_stage', 'goal')
    
    if(current_stage != 'ready'):
        try:
            if current_stage == 'age':
                age = int(message_text)
                if 10 <= age <= 100:
                    user_profiles[user_id]['age'] = age
                    user_profiles[user_id]['setup_stage'] = 'height'
                    line_bot_api.reply_message(
                        event.reply_token, 
                        TextSendMessage(text="請輸入您的身高(公分)")
                    )
                else:
                    line_bot_api.reply_message(
                        event.reply_token, 
                        TextSendMessage(text="請輸入有效的年齡 (10-100)")
                    )
            
            elif current_stage == 'height':
                height = float(message_text)
                if 100 <= height <= 250:
                    user_profiles[user_id]['height'] = height
                    user_profiles[user_id]['setup_stage'] = 'weight'
                    line_bot_api.reply_message(
                        event.reply_token, 
                        TextSendMessage(text="請輸入您的體重(公斤)")
                    )
                else:
                    line_bot_api.reply_message(
                        event.reply_token, 
                        TextSendMessage(text="請輸入有效的身高 (100-250 公分)")
                    )
            
            elif current_stage == 'weight':
                weight = float(message_text)
                if 30 <= weight <= 120:
                    user_profiles[user_id]['weight'] = weight
                    user_profiles[user_id]['setup_stage'] = 'activity'
                    
                    # 活動量選擇
                    carousle_template = CarouselTemplate( columns = [
                            CarouselColumn(
                                thumbnail_image_url= 'https://img.freepik.com/free-vector/cabin-fever-concept-illustration_114360-2872.jpg?t=st=1733659160~exp=1733662760~hmac=89156d3dd8fa4077b4d68c375c752355c4c79c815309e9277f0088d754533abf&w=1380',
                                title = '久坐',
                                text = '幾乎沒有運動',
                                actions=[
                                    PostbackTemplateAction(label='選擇', text = '久坐',data='activity_1')
                                ]
                            ),
                            CarouselColumn(
                                thumbnail_image_url= 'https://img.freepik.com/free-vector/yoga-practice-concept-illustration_114360-5554.jpg?t=st=1733659207~exp=1733662807~hmac=692dea7fef6f60a4ec7b1deb65aa47afc650b16bf1b5e0f76d5cc849c03c8899&w=1380',
                                title = '輕度活動',
                                text = '運動 1-3 次/週',
                                actions=[
                                    PostbackTemplateAction(label='選擇', text = '輕度活動',data='activity_2')
                                ]
                            ),
                            CarouselColumn(
                                thumbnail_image_url= 'https://s38924.pcdn.co/wp-content/uploads/2021/03/New-Global-Adventures-and-Gravity-Forms-.png',
                                title = '中度活動',
                                text = '運動 3-5 次/週',
                                actions=[
                                    PostbackTemplateAction(label='選擇', text = '中度活動', data='activity_3')
                                ]
                            ),
                            CarouselColumn(
                                thumbnail_image_url= 'https://fitourney.com/images/5233015.jpg',
                                title = '高度活動',
                                text = '運動或運動 6-7 次/週',
                                actions=[
                                    PostbackTemplateAction(label='選擇', text = '高度活動', data='activity_4')
                                ]
                            ),
                            CarouselColumn(
                                thumbnail_image_url= 'https://img.freepik.com/free-vector/finish-line-concept-illustration_114360-2750.jpg?t=st=1733659371~exp=1733662971~hmac=852dda982c04280d83055dc470bcb3ba80e5407d96e144df6502e37c803d4876&w=1380',
                                title = '非常活躍',
                                text = '每天都有運動',
                                actions=[
                                    PostbackTemplateAction(label='選擇', text = '非常活躍', data='activity_5')
                                ]
                            )
                        ]
                    )

                    template_message = TemplateSendMessage(
                        alt_text='請選擇活動量級別',
                        template= carousle_template
                    )

                    line_bot_api.reply_message(
                        event.reply_token, 
                        template_message
                    )
                else:
                    line_bot_api.reply_message(
                        event.reply_token, 
                        TextSendMessage(text="請輸入有效的體重 (30-120 公斤)")
                    )
            
        except ValueError:
            line_bot_api.reply_message(
                event.reply_token, 
                TextSendMessage(text="請輸入有效的數字")
            )

    elif(current_stage == 'ready'):
            if(message_text.startswith('新增記錄')):
                # 記錄飲食
                # 解析訊息，例如 "記錄 雞胸肉 200"
                try:
                    _, food_name, calories = message_text.split()
                    calories = float(calories)
            
                    if add_food_log(user_id, food_name, calories):
                        remaining_calories = user_profiles[user_id]['daily_tracker']['total_calories'] - user_profiles[user_id]['daily_tracker']['consumed_calories']
                
                        line_bot_api.reply_message(
                            event.reply_token, 
                            TextSendMessage(text=f"已成功記錄 {food_name} ({calories} 大卡)。\n剩餘可攝取熱量：{round(remaining_calories, 2)} 大卡")
                        )
                    else:
                        line_bot_api.reply_message(
                        event.reply_token, 
                        TextSendMessage(text="超過每日建議熱量，無法記錄")
                        )
                except:
                    line_bot_api.reply_message(
                    event.reply_token, 
                    TextSendMessage(text="新增記錄格式錯誤。請使用「新增記錄 <食物名稱> <熱量>」")
                    )
            elif (message_text.startswith('刪除記錄')):
                # 刪除飲食記錄
                # 刪除記錄 食物名稱
                try:
                    _, food_name = message_text.split()
                    if remove_food_log(user_id, food_name):
                        line_bot_api.reply_message(
                            event.reply_token, 
                            TextSendMessage(text=f"已成功刪除 {food_name} 的飲食記錄")
                        )
                    else:
                        line_bot_api.reply_message(
                            event.reply_token, 
                            TextSendMessage(text=f"找不到 {food_name} 的飲食記錄")
                        )
                except:
                    line_bot_api.reply_message(
                    event.reply_token, 
                    TextSendMessage(text="刪除記錄格式錯誤。請使用「刪除記錄 <食物名稱>」")
                    )

            elif (message_text == '今日狀態'):
                # 顯示用戶狀態
                profile = user_profiles[user_id]
                daily_tracker = profile['daily_tracker']
                
                status_message = (
                    f"👤 個人資料:\n"
                    f"目標: {profile['goal']}\n"
                    f"性別: {profile['gender']}\n"
                    f"年齡: {profile['age']} 歲\n"
                    f"身高: {profile['height']} 公分\n"
                    f"體重: {profile['weight']} 公斤\n"
                    f"活動量: {profile['activity_level']}\n\n"
                    f"📊 今日熱量狀態:\n"
                    f"總建議熱量: {round(daily_tracker['total_calories'], 2)} 大卡\n"
                    f"已消耗熱量: {round(daily_tracker['consumed_calories'], 2)} 大卡\n"
                    f"剩餘可攝取熱量: {round((daily_tracker['total_calories'] - daily_tracker['consumed_calories']), 2)} 大卡\n\n"
                    "🍽️ 今日食物記錄:\n"
                )
                
                for food in daily_tracker['food_log']:
                    status_message += f"{food['time']} - {food['name']} ({round(food['calories'], 2)} 大卡)\n"
                
                line_bot_api.reply_message(
                    event.reply_token, 
                    TextSendMessage(text=status_message)
                )

            elif (message_text == '飲食建議'):
                confirm_template = ConfirmTemplate(
                text='確定要開始客製化飲食建議流程嗎？',
                actions=[
                    PostbackTemplateAction(
                        label='是',
                        data='開始飲食建議'
                    ),
                    PostbackTemplateAction(
                        label='否',
                        data='取消飲食建議'
                    )
                ]
                )
        
                template_message = TemplateSendMessage(
                    alt_text='飲食建議確認',
                    template=confirm_template
                )
        
                line_bot_api.reply_message(event.reply_token, template_message)
            
            elif user_diet_suggestion_flow.get(user_id, {}).get('stage') in ['calories', 'additional_requirements']:
                template_message = handle_diet_suggestion_flow(event, user_id, message_text)
                line_bot_api.reply_message(event.reply_token, template_message)

            elif message_text.startswith("編輯"):
                # 編輯個人資料
                try:
                    item = message_text.split()[1]
                    try:
                        new_value = message_text.split()[2]
                    except:
                        new_value = None
                    if(item == "身高" or item == "體重" or item == "年齡" or item == "性別"):
                        new_value = validate_edit_input(user_id, item, new_value)
                        itemMap = {"身高" : "height", "體重" : "weight", "年齡" : "age", "性別" : "gender"}
                        if new_value:
                            user_profiles[user_id][itemMap[item]] = new_value
                            profile = user_profiles[user_id]
                            bmr = calculate_bmr(
                                profile["gender"], profile["age"], profile["height"], profile["weight"]
                            )
                            daily_calories = calculate_daily_calories(
                                bmr, profile["activity_level"], profile["goal"]
                            )
                            user_profiles[user_id]["daily_tracker"]["total_calories"] = daily_calories
                            line_bot_api.reply_message(
                                event.reply_token, 
                                TextSendMessage(text=f"已更新 {item} 為 {new_value}")
                            )
                        else:
                            line_bot_api.reply_message(
                                event.reply_token, 
                                TextSendMessage(text=f"無法更新 {item}，請檢查輸入是否正確")
                            )
                    elif(item == "目標"):
                        buttons_template = ButtonsTemplate(
                            title = "重新設定目標",
                            text='請選擇您的目標:',
                            actions=[
                                PostbackTemplateAction(
                                    label='增肌',
                                    text = '增肌',
                                    data='edit_goal_增肌'
                                ),
                                PostbackTemplateAction(
                                    label='減重',
                                    text = '減重',
                                    data='edit_goal_減重'
                                ),
                                PostbackTemplateAction(
                                    label='維持體重',
                                    text = '維持體重',
                                    data='edit_goal_維持體重'
                                )
                            ]
                        )
                        template_message = TemplateSendMessage(
                            alt_text='請選擇目標',
                            template=buttons_template
                        )
                        line_bot_api.reply_message(event.reply_token, template_message)
                    elif(item == "活動量"):
                        carousle_template = CarouselTemplate( columns = [
                            CarouselColumn(
                                thumbnail_image_url= 'https://img.freepik.com/free-vector/cabin-fever-concept-illustration_114360-2872.jpg?t=st=1733659160~exp=1733662760~hmac=89156d3dd8fa4077b4d68c375c752355c4c79c815309e9277f0088d754533abf&w=1380',
                                title = '久坐',
                                text = '幾乎沒有運動',
                                actions=[
                                    PostbackTemplateAction(label='選擇', text = '久坐',data='edit_activity_1')
                                ]
                            ),
                            CarouselColumn(
                                thumbnail_image_url= 'https://img.freepik.com/free-vector/yoga-practice-concept-illustration_114360-5554.jpg?t=st=1733659207~exp=1733662807~hmac=692dea7fef6f60a4ec7b1deb65aa47afc650b16bf1b5e0f76d5cc849c03c8899&w=1380',
                                title = '輕度活動',
                                text = '運動 1-3 次/週',
                                actions=[
                                    PostbackTemplateAction(label='選擇', text = '輕度活動',data='edit_activity_2')
                                ]
                            ),
                            CarouselColumn(
                                thumbnail_image_url= 'https://s38924.pcdn.co/wp-content/uploads/2021/03/New-Global-Adventures-and-Gravity-Forms-.png',
                                title = '中度活動',
                                text = '運動 3-5 次/週',
                                actions=[
                                    PostbackTemplateAction(label='選擇', text = '中度活動', data='edit_activity_3')
                                ]
                            ),
                            CarouselColumn(
                                thumbnail_image_url= 'https://fitourney.com/images/5233015.jpg',
                                title = '高度活動',
                                text = '運動或運動 6-7 次/週',
                                actions=[
                                    PostbackTemplateAction(label='選擇', text = '高度活動', data='edit_activity_4')
                                ]
                            ),
                            CarouselColumn(
                                thumbnail_image_url= 'https://img.freepik.com/free-vector/finish-line-concept-illustration_114360-2750.jpg?t=st=1733659371~exp=1733662971~hmac=852dda982c04280d83055dc470bcb3ba80e5407d96e144df6502e37c803d4876&w=1380',
                                title = '非常活躍',
                                text = '每天都有運動',
                                actions=[
                                    PostbackTemplateAction(label='選擇', text = '非常活躍', data='edit_activity_5')
                                ]
                            )
                        ]
                        )

                        template_message = TemplateSendMessage(
                            alt_text='請選擇活動量級別',
                            template= carousle_template
                        )

                        line_bot_api.reply_message(
                            event.reply_token, 
                            template_message
                        )
                    else:
                        line_bot_api.reply_message(
                            event.reply_token, 
                            TextSendMessage(text="編輯項目錯誤。請使用「編輯 <項目> <修改內容>」"))

                                
                except:
                    line_bot_api.reply_message(
                        event.reply_token, 
                        TextSendMessage(text="編輯格式錯誤。請使用「編輯 <項目> <修改內容>」")
                    )            
            # 新增 Help 功能
            elif (message_text == "Help"):
                    help_message = (
                        "🥖 Meal Mate 使用說明 🍓\n\n"
                        "💻指令列表:\n"
                        "記錄食物: 新增記錄 <食物名稱> <熱量>\n"
                        "刪除食物記錄: 刪除記錄 <食物名稱>\n"
                        "顯示當日熱量狀態: 今日狀態\n"
                        "生成客製化飲食建議: 飲食建議 \n"
                        "修改個人資料: 編輯 <項目> <修改內容>\n"
                        "顯示指令說明: Help\n\n"
                        "✏️編輯範例:\n"
                        "「編輯 目標」\n"
                        "「編輯 體重 <重量>(kg)」\n"
                        "「編輯 身高 <身高>(cm)」\n"
                        "「編輯 年齡 <年齡>」\n"
                        "「編輯 性別 <男/女>」\n"
                        "「編輯 活動量」\n"
                    )
                    
                    line_bot_api.reply_message(
                        event.reply_token, 
                        TextSendMessage(text=help_message)
                    )
            else:
                # 後續功能可以在這裡擴充
                line_bot_api.reply_message(
                    event.reply_token, 
                    TextSendMessage(text="感謝您的使用。目前暫無此功能！ \n(輸入 Help 顯示指令列表)")
                )
    

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)