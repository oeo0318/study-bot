import os
import asyncio
import logging
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import calendar
import time
from pypdf import PdfReader
import discord
from discord import Option
from dotenv import load_dotenv
from openai import OpenAI 
from pydantic import BaseModel
from collections import defaultdict, deque
import random


# ====== Structured Output 模型 ======
class QuizQuestion(BaseModel):
    question: str
    option_a: str
    option_b: str
    option_c: str
    option_d: str
    correct_answer: str  # "A", "B", "C", or "D"
    explanation: str


# ====== 答題按鈕 View ======
class QuizView(discord.ui.View):
    def __init__(self, quiz: QuizQuestion, user_id: int):
        super().__init__(timeout=120)
        self.quiz = quiz
        self.user_id = user_id
        self.answered = False

    async def handle_answer(self, interaction: discord.Interaction, selected: str):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ 這不是你的題目！", ephemeral=True)
            return
        if self.answered:
            await interaction.response.send_message("⚠️ 你已經回答過了！", ephemeral=True)
            return
        
        self.answered = True
        for child in self.children:
            child.disabled = True
        
        correct = self.quiz.correct_answer.upper()
        if selected == correct:
            result = f"✅ **正確！** 答案是 **{correct}**\n\n📖 **解析：**\n{self.quiz.explanation}"
        else:
            result = f"❌ **錯誤！** 你選了 **{selected}**，正確答案是 **{correct}**\n\n📖 **解析：**\n{self.quiz.explanation}"
        
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(result)

    @discord.ui.button(label="A", style=discord.ButtonStyle.primary)
    async def button_a(self, button: discord.ui.Button, interaction: discord.Interaction):
        await self.handle_answer(interaction, "A")

    @discord.ui.button(label="B", style=discord.ButtonStyle.primary)
    async def button_b(self, button: discord.ui.Button, interaction: discord.Interaction):
        await self.handle_answer(interaction, "B")

    @discord.ui.button(label="C", style=discord.ButtonStyle.primary)
    async def button_c(self, button: discord.ui.Button, interaction: discord.Interaction):
        await self.handle_answer(interaction, "C")

    @discord.ui.button(label="D", style=discord.ButtonStyle.primary)
    async def button_d(self, button: discord.ui.Button, interaction: discord.Interaction):
        await self.handle_answer(interaction, "D")

# 設定日誌
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
SOUND_FILE_PATH = os.getenv("SOUND_FILE_PATH", "omg.mp3")

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
    max_retries=0,
)

SYSTEM_PROMPT = """你是一個專業的讀書計畫助手。
請用繁體中文回答,語氣友善且專業。
幫助使用者管理作業、複習和學習時間。
"""

# 談心專用的系統提示詞
CHAT_SYSTEM_PROMPT = """你是一位溫暖、善解人意的心靈導師和學習夥伴。

你的角色：
- 理解學生讀書時的壓力、疲憊和焦慮
- 提供溫暖的鼓勵和實際的建議
- 記住每個學生的個性和過往對話
- 根據學生的性格特質調整你的回應方式

回應原則：
1. **溫暖親切**：像朋友一樣關心他們，但保持適當界限
2. **個性化**：根據學生的個性（活潑/內向/焦慮/樂觀等）調整語氣
3. **實用建議**：不只是安慰，也提供具體的休息或調適方法
4. **正向鼓勵**：肯定他們的努力，給予希望
5. **簡潔有力**：回應不要太長，2-4段即可

語氣範例：
- 對於焦慮型學生：更多的安撫和肯定，告訴他們「已經做得很好了」
- 對於樂觀型學生：給予活力和幽默感，一起慶祝小成就
- 對於內向型學生：溫柔且不帶壓力的關心
- 對於疲憊型學生：建議休息，認可他們的付出

請用繁體中文回答，語氣溫暖自然。"""

# 設定通知頻道 ID
NOTIFICATION_CHANNEL_ID = 1468954162057187393

bot = discord.Bot(intents=discord.Intents.all())

# 資料儲存
DATA_FILE = "study_data.json"

def load_data() -> Dict:
    """載入資料"""
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_data(data: Dict):
    """儲存資料"""
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

async def generate_reply(prompt: str) -> str:
    """使用 AI 生成回覆"""
    try:
        response = await asyncio.to_thread(
            client.chat.completions.create,
            model="deepseek/deepseek-r1-0528:free",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
        return response.choices[0].message.content
    except Exception as e:
        logging.error(f"AI 生成錯誤: {e}")
        return "抱歉,AI 助手暫時無法回應,請稍後再試。"

async def generate_chat_reply(messages: List[Dict], personality: str = "") -> str:
    """使用 AI 生成談心回覆（帶對話歷史）"""
    try:
        # 準備系統提示詞
        system_prompt = CHAT_SYSTEM_PROMPT
        if personality:
            system_prompt += f"\n\n關於這位學生的個性分析：\n{personality}"
        
        # 構建完整的訊息列表
        full_messages = [{"role": "system", "content": system_prompt}] + messages
        
        response = await asyncio.to_thread(
            client.chat.completions.create,
            model="deepseek/deepseek-r1-0528:free",
            messages=full_messages,
            temperature=0.8,  # 增加一些創意和溫暖感
        )
        return response.choices[0].message.content
    except Exception as e:
        logging.error(f"談心 AI 生成錯誤: {e}")
        return "抱歉，我現在有點累了...但我隨時都在這裡陪你。要不要待會再聊？💙"

async def analyze_personality(chat_history: List[Dict]) -> str:
    """分析使用者個性"""
    if len(chat_history) < 6:  # 至少3次對話（6條訊息）才開始分析
        return ""
    
    try:
        # 取最近10次對話
        recent_messages = chat_history[-20:]
        
        analysis_prompt = """基於以下對話歷史，請分析這位學生的個性特質。

請以2-3句話描述：
1. 他們的情緒狀態傾向（焦慮/樂觀/平穩等）
2. 他們的表達風格（直接/含蓄/幽默等）
3. 他們最需要的支持類型（鼓勵/實際建議/陪伴等）

對話歷史：
""" + "\n".join([f"{msg['role']}: {msg['content']}" for msg in recent_messages])
        
        response = await asyncio.to_thread(
            client.chat.completions.create,
            model="deepseek/deepseek-r1-0528:free",
            messages=[
                {"role": "system", "content": "你是一位專業的心理分析師，擅長透過對話理解學生的個性。"},
                {"role": "user", "content": analysis_prompt}
            ],
        )
        return response.choices[0].message.content
    except Exception as e:
        logging.error(f"個性分析錯誤: {e}")
        return ""

def get_user_data(user_id: str) -> Dict:
    """獲取使用者資料"""
    data = load_data()
    if user_id not in data:
        data[user_id] = {
            "tasks": [],
            "timers": {},
            "chat_history": [],  # 談心對話歷史
            "personality_profile": ""  # 個性分析
        }
        save_data(data)
    return data[user_id]

def format_time_duration(seconds: int) -> str:
    """格式化時間長度"""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    
    if hours > 0:
        return f"{hours} 小時 {minutes} 分鐘"
    elif minutes > 0:
        return f"{minutes} 分鐘 {secs} 秒"
    else:
        return f"{secs} 秒"

# ==================== PDF 處理相關 ====================

SOURCE_ROOT = "upload"      # 主資料夾
OUTPUT_ROOT = "json_knowledge" # 輸出的 JSON 要放哪裡

def extract_text(pdf_path):
    text = ""
    try:
        reader = PdfReader(pdf_path)
        for page in reader.pages:
            t = page.extract_text()
            if t: text += t + "\n"
        return text
    except Exception as e:
        logging.error(f"❌ 讀取失敗 {pdf_path}: {e}")
        return ""

def process_category(category_name, folder_path):
    """處理單一分類資料夾"""
    json_filename = os.path.join(OUTPUT_ROOT, f"{category_name}.json")
    knowledge_base = []
    
    # 檢查是否已有舊檔 (斷點續傳)
    if os.path.exists(json_filename):
        try:
            with open(json_filename, 'r', encoding='utf-8') as f:
                knowledge_base = json.load(f)
        except: pass
    
    existing_files = {item['source'] for item in knowledge_base}
    
    files = [f for f in os.listdir(folder_path) if f.lower().endswith('.pdf')]
    logging.info(f"📂 分類 [{category_name}] 發現 {len(files)} 個 PDF")

    updated = False
    for filename in files:
        if filename in existing_files:
            continue
            
        logging.info(f"   🚀 正在處理: {filename}...")
        text = extract_text(os.path.join(folder_path, filename))
        
        if text.strip():
            # 切分文字 (Chunking)
            chunk_size = 1000
            for i in range(0, len(text), chunk_size):
                chunk = text[i:i+chunk_size]
                if len(chunk) > 50:
                    knowledge_base.append({
                        "category": category_name, # 標記分類
                        "source": filename,
                        "content": chunk
                    })
            updated = True
    
    # 如果有新資料才存檔
    if updated:
        with open(json_filename, 'w', encoding='utf-8') as f:
            json.dump(knowledge_base, f, ensure_ascii=False, indent=2)
        logging.info(f"   💾 [{category_name}] 已存檔！")
    else:
        logging.info(f"   ⏸️ [{category_name}] 無新增資料。")

def process_pdfs():
    """處理所有 PDF 檔案"""
    if not os.path.exists(OUTPUT_ROOT):
        os.makedirs(OUTPUT_ROOT)

    # 掃描 source_root 下的所有子資料夾
    if not os.path.exists(SOURCE_ROOT):
        logging.error(f"找不到 {SOURCE_ROOT} 資料夾")
        return

    subfolders = [f for f in os.listdir(SOURCE_ROOT) if os.path.isdir(os.path.join(SOURCE_ROOT, f))]
    
    logging.info(f"🔍 發現分類: {subfolders}")

    for folder in subfolders:
        folder_path = os.path.join(SOURCE_ROOT, folder)
        process_category(folder, folder_path)

# ==================== 題庫相關 ====================

# 設定 JSON 資料夾路徑
JSON_FOLDER = "json_knowledge"

# 快取所有題庫 { "歷史": [...資料...], "理化": [...資料...] }
knowledge_cache = {}

def load_all_knowledge():
    """載入所有分類的 JSON"""
    global knowledge_cache
    knowledge_cache = {} # 清空快取
    
    if not os.path.exists(JSON_FOLDER):
        os.makedirs(JSON_FOLDER)
        return

    files = [f for f in os.listdir(JSON_FOLDER) if f.endswith(".json")]
    
    for filename in files:
        category_name = filename.replace(".json", "") # 去掉副檔名當作分類名
        try:
            with open(os.path.join(JSON_FOLDER, filename), "r", encoding="utf-8") as f:
                data = json.load(f)
                knowledge_cache[category_name] = data
                logging.info(f"✅ 已載入分類：{category_name} ({len(data)} 筆片段)")
        except Exception as e:
            logging.error(f"❌ 載入失敗 {filename}: {e}")

# 動態取得分類列表 (給 Discord 自動補全用)
def get_categories(ctx: discord.AutocompleteContext):
    return list(knowledge_cache.keys())

# 出題 Prompt
def build_prompt(doc_data, category):
    return f"""
你是一位專業的國中老師。
科目：{category}
參考資料來源：{doc_data['source']}
資料內容：
{doc_data['content']}

任務：根據資料內容出一題「單選題」，並填寫以下欄位：
- question: 題目內容
- option_a: 選項 A 的內容（不需加 A. 前綴）
- option_b: 選項 B 的內容（不需加 B. 前綴）
- option_c: 選項 C 的內容（不需加 C. 前綴）
- option_d: 選項 D 的內容（不需加 D. 前綴）
- correct_answer: 正確答案，只能填 A、B、C 或 D 其中一個字母
- explanation: 詳細解析，說明為何正確答案是對的

規則：
1. 使用繁體中文。
2. 題目須具備教育意義，幫助學生理解概念，而非僅考察記憶。
3. 請確保題目與解析的內容都來自提供的資料內容，不要加入額外資訊。
4. 選項和題目務必合理，不能出現明顯錯誤或不合邏輯的內容。
5. 請勿使用詩歌體或過於文學化的語言，保持清晰直接，適合國中學生閱讀。
"""

# ==================== Slash Commands ====================

@bot.slash_command(name="出題", description="選擇科目並出題")
async def exam(
    ctx: discord.ApplicationContext,
    subject: Option(str, "請選擇科目", autocomplete=get_categories)
):
    # ✅ 先 defer，避免 timeout
    await ctx.defer()
    
    # 檢查該科目是否存在
    if subject not in knowledge_cache:
        await ctx.followup.send(f"❌ 找不到「{subject}」這個科目的題庫，請確認是否有該分類的 JSON 檔。")
        return
    
    # 取得該科目的所有資料
    category_data = knowledge_cache[subject]
    
    if not category_data:
        await ctx.followup.send(f"⚠️ 「{subject}」題庫是空的。")
        return

    await ctx.followup.send(f"📚 正在準備 **{subject}** 的試題...")

    try:
        # 隨機挑選一段
        selected_doc = random.choice(category_data)
        prompt = build_prompt(selected_doc, subject)

        # 使用 OpenRouter API (Structured Output)
        # 注意：DeepSeek R1 會輸出 <think> 標籤，不適合 structured output
        # 改用支援 structured output 的模型
        response = await asyncio.to_thread(
            client.beta.chat.completions.parse,
            model="meta-llama/llama-3.3-70b-instruct",
            messages=[
                {"role": "system", "content": "你是一位專業的國中老師，擅長出題。請按照指定格式回答。"},
                {"role": "user", "content": prompt}
            ],
            response_format=QuizQuestion,
        )

        quiz = response.choices[0].message.parsed
        
        # 格式化題目顯示
        question_text = (
            f"📝 **{subject} 題目**\n\n"
            f"{quiz.question}\n\n"
            f"**A.** {quiz.option_a}\n"
            f"**B.** {quiz.option_b}\n"
            f"**C.** {quiz.option_c}\n"
            f"**D.** {quiz.option_d}"
        )
        
        # 建立按鈕 View
        view = QuizView(quiz, ctx.author.id)
        await ctx.followup.send(question_text, view=view)

    except Exception as e:
        logging.error(f"出題錯誤: {e}")
        await ctx.followup.send(f"❌ 出題系統發生錯誤: {e}")

@bot.slash_command(name="重載題庫", description="重新讀取 JSON 檔案")
async def reload_db(ctx):
    await ctx.defer()
    # 使用 asyncio.to_thread 避免阻塞導致 interaction timeout
    await asyncio.to_thread(load_all_knowledge)
    await ctx.followup.send(f"✅ 題庫已更新，目前有 {len(knowledge_cache)} 個分類。")

@bot.slash_command(name="更新題庫", description="處理 PDF 並更新題庫")
async def update_knowledge_base(ctx):
    await ctx.defer()
    
    try:
        # 使用 asyncio.to_thread 避免阻塞導致 interaction timeout
        await asyncio.to_thread(process_pdfs)
        await asyncio.to_thread(load_all_knowledge)
        await ctx.followup.send(f"✅ 題庫已更新完成！目前有 {len(knowledge_cache)} 個分類。")
    except Exception as e:
        logging.error(f"更新題庫錯誤: {e}")
        await ctx.followup.send(f"❌ 更新題庫時發生錯誤: {e}")

@bot.slash_command(name="談心", description="跟機器人聊聊天，舒緩讀書壓力")
async def chat_with_bot(
    ctx: discord.ApplicationContext,
    心情: Option(str, "想說的話或現在的心情", required=True)
):
    """溫暖的談心功能"""
    await ctx.defer()  # 因為 AI 回應需要時間
    
    user_id = str(ctx.author.id)
    data = load_data()
    user_data = get_user_data(user_id)
    
    # 取得對話歷史（保留最近20條）
    chat_history = user_data.get("chat_history", [])[-20:]
    personality = user_data.get("personality_profile", "")
    
    # 加入使用者的新訊息
    chat_history.append({"role": "user", "content": 心情})
    
    # 生成回應
    response = await generate_chat_reply(chat_history, personality)
    
    # 儲存 AI 的回應
    chat_history.append({"role": "assistant", "content": response})
    
    # 每5次對話更新一次個性分析
    if len(chat_history) % 10 == 0:
        logging.info(f"更新使用者 {user_id} 的個性分析...")
        personality = await analyze_personality(chat_history)
        user_data["personality_profile"] = personality
    
    # 儲存更新的對話歷史
    user_data["chat_history"] = chat_history
    data[user_id] = user_data
    save_data(data)
    
    # 建立溫暖的 Embed 回應
    embed = discord.Embed(
        title="💙 談心時光",
        description=response,
        color=discord.Color.from_rgb(135, 206, 250)  # 淺藍色，溫暖平靜
    )
    
    # 根據對話次數顯示不同的提示
    chat_count = len(chat_history) // 2  # 除以2因為包含user和assistant
    
    if chat_count == 1:
        footer_text = "這是我們第一次談心 🌱 隨時都可以再來找我聊聊"
    elif chat_count <= 5:
        footer_text = f"我們已經聊了 {chat_count} 次了 🌿 我會越來越懂你"
    else:
        footer_text = f"我們已經是老朋友了！聊了 {chat_count} 次 🌳"
    
    embed.set_footer(text=footer_text)
    embed.timestamp = datetime.now()
    
    await ctx.followup.send(embed=embed)
    
    # 發送通知（可選）
    try:
        channel = bot.get_channel(NOTIFICATION_CHANNEL_ID)
        if channel:
            notif = discord.Embed(
                title="💬 談心記錄",
                description=f"{ctx.author.mention} 來談心了",
                color=discord.Color.blue()
            )
            notif.add_field(name="次數", value=f"第 {chat_count} 次", inline=True)
            notif.timestamp = datetime.now()
            await channel.send(embed=notif)
    except Exception as e:
        logging.error(f"通知失敗: {e}")

@bot.slash_command(name="查看談心記錄", description="查看你和機器人的對話歷史")
async def view_chat_history(ctx: discord.ApplicationContext):
    """查看談心歷史"""
    user_id = str(ctx.author.id)
    user_data = get_user_data(user_id)
    
    chat_history = user_data.get("chat_history", [])
    personality = user_data.get("personality_profile", "")
    
    if not chat_history:
        await ctx.respond("你還沒有跟我談過心呢！使用 `/談心` 來開始吧 💙")
        return
    
    embed = discord.Embed(
        title="💙 談心歷史記錄",
        description=f"總共聊了 {len(chat_history)//2} 次",
        color=discord.Color.from_rgb(135, 206, 250)
    )
    
    # 顯示最近3次對話
    recent_chats = []
    for i in range(len(chat_history)-1, max(len(chat_history)-7, -1), -2):
        if i >= 1:
            user_msg = chat_history[i-1]["content"]
            bot_msg = chat_history[i]["content"]
            
            # 限制長度
            user_preview = user_msg[:50] + "..." if len(user_msg) > 50 else user_msg
            bot_preview = bot_msg[:100] + "..." if len(bot_msg) > 100 else bot_msg
            
            recent_chats.append(f"**你說：** {user_preview}\n**回應：** {bot_preview}\n")
    
    if recent_chats:
        embed.add_field(
            name="📝 最近的對話",
            value="\n".join(recent_chats[:3]),
            inline=False
        )
    
    # 顯示個性分析（如果有）
    if personality:
        embed.add_field(
            name="🎭 你的個性分析",
            value=personality,
            inline=False
        )
    
    embed.set_footer(text="使用 /清除談心記錄 可以重新開始")
    
    await ctx.respond(embed=embed)

@bot.slash_command(name="清除談心記錄", description="清除所有談心對話歷史（重新開始）")
async def clear_chat_history(ctx: discord.ApplicationContext):
    """清除談心記錄"""
    user_id = str(ctx.author.id)
    data = load_data()
    user_data = get_user_data(user_id)
    
    chat_count = len(user_data.get("chat_history", [])) // 2
    
    user_data["chat_history"] = []
    user_data["personality_profile"] = ""
    data[user_id] = user_data
    save_data(data)
    
    embed = discord.Embed(
        title="🔄 記憶已重置",
        description=f"我們一起聊了 {chat_count} 次，這些回憶我會好好珍藏的。\n\n現在讓我們重新認識吧！期待與你的下一次談心 💙",
        color=discord.Color.from_rgb(135, 206, 250)
    )
    
    await ctx.respond(embed=embed)

@bot.slash_command(name="教學", description="查看機器人使用教學")
async def tutorial(ctx: discord.ApplicationContext):
    """顯示使用教學"""
    embed = discord.Embed(
        title="📚 讀書計畫機器人使用教學",
        description="以下是所有可用的指令:",
        color=discord.Color.blue()
    )
    
    embed.add_field(
        name="💙 /談心",
        value="跟機器人聊聊天，舒緩讀書壓力\n機器人會記住你的個性，給予個人化的溫暖回應",
        inline=False
    )
    
    embed.add_field(
        name="📝 /出題",
        value="從題庫中隨機出題測驗",
        inline=False
    )
    
    embed.add_field(
        name="1️⃣ /新增作業",
        value="新增作業任務\n參數: 日期(YYYY-MM-DD)、科目、頁數、預估時間(分鐘)",
        inline=False
    )
    
    embed.add_field(
        name="2️⃣ /新增複習",
        value="新增複習任務\n參數: 科目、範圍、把握度(1-10,1最不確定,10最有把握)",
        inline=False
    )
    
    embed.add_field(
        name="3️⃣ /刪除任務",
        value="刪除任務\n參數: 任務編號",
        inline=False
    )
    
    embed.add_field(
        name="4️⃣ /完成任務",
        value="標記任務完成(會顯示打勾✅)\n參數: 任務編號",
        inline=False
    )
    
    embed.add_field(
        name="5️⃣ /開始計時",
        value="開始計時某個任務\n參數: 任務編號",
        inline=False
    )
    
    embed.add_field(
        name="6️⃣ /結束計時",
        value="結束計時並顯示花費時間\n參數: 任務編號",
        inline=False
    )
    
    embed.add_field(
        name="7️⃣ /整月行事曆",
        value="查看整個月的行事曆\n有任務的日期會顯示 * 標誌\n參數: 年份、月份(可選,預設當月)",
        inline=False
    )
    
    embed.add_field(
        name="8️⃣ /查看日期",
        value="查看特定日期的所有行程\n參數: 日期(YYYY-MM-DD)",
        inline=False
    )
    
    embed.add_field(
        name="🍅 番茄鐘功能",
        value="/番茄鐘 - 開始25分鐘專注\n/停止番茄鐘 - 停止計時",
        inline=False
    )
    
    embed.add_field(
        name="💡 其他指令",
        value="/我的任務 - 查看所有任務列表\n/查看談心記錄 - 查看對話歷史\n/清除談心記錄 - 重置對話記憶\n/更新題庫 - 處理 PDF 並更新題庫",
        inline=False
    
    )
    
    embed.set_footer(text="任何問題都可以使用 /談心 跟我聊聊!")
    
    await ctx.respond(embed=embed)

@bot.slash_command(name="新增作業", description="新增一個作業任務")
async def add_homework(
    ctx: discord.ApplicationContext,
    日期: Option(str, "截止日期(格式:YYYY-MM-DD)", required=True),
    科目: Option(str, "科目名稱", required=True),
    頁數: Option(str, "頁數或範圍(例如:p.1-10)", required=True),
    預估時間: Option(int, "預估完成時間(分鐘)", required=True, min_value=1)
):
    """新增作業"""
    user_id = str(ctx.author.id)
    data = load_data()
    user_data = get_user_data(user_id)
    
    # 驗證日期格式
    try:
        deadline = datetime.strptime(日期, "%Y-%m-%d")
    except ValueError:
        await ctx.respond("❌ 日期格式錯誤!請使用 YYYY-MM-DD 格式(例如:2026-02-15)")
        return
    
    # 生成任務編號
    task_id = len(user_data["tasks"]) + 1
    
    task = {
        "id": task_id,
        "type": "作業",
        "subject": 科目,
        "pages": 頁數,
        "estimated_time": 預估時間,
        "actual_time": None,
        "deadline": deadline.isoformat(),
        "completed": False,
        "created_at": datetime.now().isoformat()
    }
    
    user_data["tasks"].append(task)
    data[user_id] = user_data
    save_data(data)
    
    # 計算剩餘天數
    days_left = (deadline - datetime.now()).days
    
    embed = discord.Embed(
        title="✅ 作業已新增!",
        description=f"**{科目}** 作業",
        color=discord.Color.green()
    )
    embed.add_field(name="📄 頁數", value=頁數, inline=True)
    embed.add_field(name="⏱️ 預估時間", value=f"{預估時間} 分鐘", inline=True)
    embed.add_field(name="📅 截止日期", value=日期, inline=True)
    embed.add_field(name="⏰ 剩餘時間", value=f"{days_left} 天", inline=True)
    embed.add_field(name="🔢 任務編號", value=f"#{task_id}", inline=True)
    
    embed.set_footer(text="使用 /開始計時 來開始做作業")
    
    await ctx.respond(embed=embed)
    
    # 發送通知
    try:
        channel = bot.get_channel(NOTIFICATION_CHANNEL_ID)
        if channel:
            notif = discord.Embed(
                title="📝 新增作業",
                description=f"{ctx.author.mention} 新增了作業",
                color=discord.Color.blue()
            )
            notif.add_field(name="科目", value=科目, inline=True)
            notif.add_field(name="截止", value=日期, inline=True)
            notif.timestamp = datetime.now()
            await channel.send(embed=notif)
    except Exception as e:
        logging.error(f"通知失敗: {e}")

@bot.slash_command(name="新增複習", description="新增一個複習任務")
async def add_review(
    ctx: discord.ApplicationContext,
    科目: Option(str, "科目名稱", required=True),
    範圍: Option(str, "複習範圍(例如:第1-3章)", required=True),
    把握度: Option(int, "把握程度(1-10,1最不確定,10最有把握)", required=True, min_value=1, max_value=10),
    預估時間: Option(int, "預估複習時間(分鐘)", required=True, min_value=1),
    使用遺忘曲線: Option(bool, "是否自動生成後續複習(1,3,7,14,30天後)", required=False, default=False)
):
    """新增複習"""
    user_id = str(ctx.author.id)
    data = load_data()
    user_data = get_user_data(user_id)
    
    current_time = datetime.now()
    created_tasks = []

    # 定義遺忘曲線的時間間隔 (天數)
    intervals = [0, 1, 3, 7, 14, 30] if 使用遺忘曲線 else [0]
    
    for i, days in enumerate(intervals):
        task_date = current_time + timedelta(days=days)
        task_id = len(user_data["tasks"]) + 1
        
        display_range = 範圍
        if 使用遺忘曲線:
            if days == 0:
                suffix = "(首次學習)"
            else:
                suffix = f"(複習 R{i} - {days}天後)"
            display_range = f"{範圍} {suffix}"

        deadline_str = task_date.strftime("%Y-%m-%d")

        task = {
            "id": task_id,
            "type": "複習",
            "subject": 科目,
            "range": display_range,
            "confidence": 把握度,
            "estimated_time": 預估時間,
            "actual_time": None,
            "deadline": f"{deadline_str}T23:59:59",
            "completed": False,
            "created_at": current_time.isoformat()
        }
        
        user_data["tasks"].append(task)
        created_tasks.append(task)

    data[user_id] = user_data
    save_data(data)
    
    confidence_emoji = "🔴" if 把握度 <= 3 else "🟡" if 把握度 <= 6 else "🟢"
    confidence_text = "不確定" if 把握度 <= 3 else "普通" if 把握度 <= 6 else "有把握"
    
    if 使用遺忘曲線:
        embed = discord.Embed(
            title="🧠 已套用遺忘曲線!",
            description=f"成功為 **{科目}** 建立了 **{len(created_tasks)}** 個複習排程",
            color=discord.Color.purple()
        )
        schedule_text = ""
        for task in created_tasks:
            date_str = datetime.fromisoformat(task['deadline']).strftime('%Y-%m-%d')
            schedule_text += f"📅 {date_str}: #{task['id']} {task['range']}\n"
            
        embed.add_field(name="📅 複習計畫表", value=schedule_text, inline=False)
        embed.add_field(name="💡 提示", value="這些任務已自動加入您的行事曆", inline=False)
        
    else:
        task = created_tasks[0]
        embed = discord.Embed(
            title="✅ 複習已新增!",
            description=f"**{科目}** 複習",
            color=discord.Color.green()
        )
        embed.add_field(name="📖 範圍", value=範圍, inline=True)
        embed.add_field(name="⏱️ 預估時間", value=f"{預估時間} 分鐘", inline=True)
        embed.add_field(name="💪 把握度", value=f"{confidence_emoji} {把握度}/10 ({confidence_text})", inline=True)
        embed.add_field(name="🔢 任務編號", value=f"#{task['id']}", inline=True)

    if 把握度 <= 3:
        embed.add_field(
            name="💡 建議",
            value="把握度較低，建議優先複習這個部分！",
            inline=False
        )
    
    embed.set_footer(text="使用 /開始計時 來開始複習")
    
    await ctx.respond(embed=embed)

@bot.slash_command(name="刪除任務", description="刪除一個任務")
async def delete_task(
    ctx: discord.ApplicationContext,
    任務編號: Option(int, "要刪除的任務編號", required=True)
):
    """刪除任務"""
    user_id = str(ctx.author.id)
    data = load_data()
    user_data = get_user_data(user_id)
    
    task_to_delete = None
    for i, task in enumerate(user_data["tasks"]):
        if task["id"] == 任務編號:
            task_to_delete = user_data["tasks"].pop(i)
            break
    
    if not task_to_delete:
        await ctx.respond(f"❌ 找不到編號 #{任務編號} 的任務!")
        return
    
    data[user_id] = user_data
    save_data(data)
    
    embed = discord.Embed(
        title="🗑️ 任務已刪除",
        description=f"已刪除 **{task_to_delete['subject']}** 的{task_to_delete['type']}",
        color=discord.Color.red()
    )
    embed.add_field(name="編號", value=f"#{任務編號}", inline=True)
    
    await ctx.respond(embed=embed)

@bot.slash_command(name="完成任務", description="標記任務為完成(會顯示✅)")
async def complete_task(
    ctx: discord.ApplicationContext,
    任務編號: Option(int, "要完成的任務編號", required=True)
):
    """完成任務"""
    user_id = str(ctx.author.id)
    data = load_data()
    user_data = get_user_data(user_id)
    
    task = None
    for t in user_data["tasks"]:
        if t["id"] == 任務編號:
            task = t
            break
    
    if not task:
        await ctx.respond(f"❌ 找不到編號 #{任務編號} 的任務!")
        return
    
    if task["completed"]:
        await ctx.respond(f"✅ 這個任務已經完成過了!")
        return
    
    task["completed"] = True
    task["completed_at"] = datetime.now().isoformat()
    
    data[user_id] = user_data
    save_data(data)
    
    embed = discord.Embed(
        title="🎉 任務完成!",
        description=f"**{task['subject']}** {task['type']}",
        color=discord.Color.gold()
    )
    
    if task["type"] == "作業":
        embed.add_field(name="📄 頁數", value=task['pages'], inline=True)
    else:
        embed.add_field(name="📖 範圍", value=task['range'], inline=True)
    
    embed.add_field(name="⏱️ 預估時間", value=f"{task['estimated_time']} 分鐘", inline=True)
    
    if task["actual_time"]:
        embed.add_field(name="⏰ 實際時間", value=f"{task['actual_time']} 分鐘", inline=True)
        
        efficiency = (task['estimated_time'] / task['actual_time']) * 100
        if efficiency > 100:
            embed.add_field(name="📈 效率", value=f"👍 比預期快 {efficiency-100:.0f}%", inline=False)
        elif efficiency < 100:
            embed.add_field(name="📈 效率", value=f"⏱️ 比預期慢 {100-efficiency:.0f}%", inline=False)
        else:
            embed.add_field(name="📈 效率", value="🎯 完美達成預估!", inline=False)
    
    embed.set_footer(text="太棒了!繼續保持!")
    
    await ctx.respond(embed=embed)

@bot.slash_command(name="開始計時", description="開始計時某個任務")
async def start_timer(
    ctx: discord.ApplicationContext,
    任務編號: Option(int, "要計時的任務編號", required=True)
):
    """開始計時"""
    user_id = str(ctx.author.id)
    data = load_data()
    user_data = get_user_data(user_id)
    
    task = None
    for t in user_data["tasks"]:
        if t["id"] == 任務編號:
            task = t
            break
    
    if not task:
        await ctx.respond(f"❌ 找不到編號 #{任務編號} 的任務!")
        return
    
    if task["completed"]:
        await ctx.respond(f"✅ 這個任務已經完成了,無需計時!")
        return
    
    if str(任務編號) in user_data["timers"]:
        await ctx.respond(f"⏱️ 任務 #{任務編號} 已經在計時中了!")
        return
    
    start_time = time.time()
    user_data["timers"][str(任務編號)] = start_time
    
    data[user_id] = user_data
    save_data(data)
    
    embed = discord.Embed(
        title="⏱️ 計時開始!",
        description=f"**{task['subject']}** {task['type']}",
        color=discord.Color.blue()
    )
    embed.add_field(name="⏰ 開始時間", value=datetime.now().strftime("%H:%M:%S"), inline=True)
    embed.add_field(name="🎯 預估時間", value=f"{task['estimated_time']} 分鐘", inline=True)
    embed.add_field(name="🔢 任務編號", value=f"#{任務編號}", inline=True)
    
    embed.set_footer(text="使用 /結束計時 來停止計時")
    
    await ctx.respond(embed=embed)

@bot.slash_command(name="結束計時", description="結束計時並顯示花費時間")
async def stop_timer(
    ctx: discord.ApplicationContext,
    任務編號: Option(int, "要結束計時的任務編號", required=True)
):
    """結束計時"""
    user_id = str(ctx.author.id)
    data = load_data()
    user_data = get_user_data(user_id)
    
    task = None
    for t in user_data["tasks"]:
        if t["id"] == 任務編號:
            task = t
            break
    
    if not task:
        await ctx.respond(f"❌ 找不到編號 #{任務編號} 的任務!")
        return
    
    if str(任務編號) not in user_data["timers"]:
        await ctx.respond(f"❌ 任務 #{任務編號} 沒有在計時中!")
        return
    
    start_time = user_data["timers"][str(任務編號)]
    end_time = time.time()
    elapsed_seconds = int(end_time - start_time)
    elapsed_minutes = elapsed_seconds / 60
    
    task["actual_time"] = round(elapsed_minutes, 1)
    del user_data["timers"][str(任務編號)]
    
    data[user_id] = user_data
    save_data(data)
    
    embed = discord.Embed(
        title="⏹️ 計時結束!",
        description=f"**{task['subject']}** {task['type']}",
        color=discord.Color.green()
    )
    
    embed.add_field(name="⏰ 花費時間", value=format_time_duration(elapsed_seconds), inline=True)
    embed.add_field(name="🎯 預估時間", value=f"{task['estimated_time']} 分鐘", inline=True)
    
    diff = elapsed_minutes - task['estimated_time']
    if diff > 0:
        embed.add_field(name="📊 差距", value=f"⏱️ 超過預估 {diff:.1f} 分鐘", inline=True)
    elif diff < 0:
        embed.add_field(name="📊 差距", value=f"👍 比預估快 {abs(diff):.1f} 分鐘", inline=True)
    else:
        embed.add_field(name="📊 差距", value="🎯 完美!", inline=True)
    
    embed.add_field(
        name="💡 提示",
        value="使用 /完成任務 來標記此任務為完成",
        inline=False
    )
    
    await ctx.respond(embed=embed)

@bot.slash_command(name="整月行事曆", description="查看整個月的行事曆")
async def monthly_calendar(
    ctx: discord.ApplicationContext,
    年份: Option(int, "年份(可選,預設今年)", required=False, default=None),
    月份: Option(int, "月份(1-12,可選,預設當月)", required=False, default=None, min_value=1, max_value=12)
):
    """顯示月行事曆"""
    # ✅ 先 defer
    await ctx.defer()
    
    user_id = str(ctx.author.id)
    user_data = get_user_data(user_id)
    
    now = datetime.now()
    target_year = 年份 if 年份 else now.year
    target_month = 月份 if 月份 else now.month
    
    cal = calendar.monthcalendar(target_year, target_month)
    month_name = f"{target_year} 年 {target_month} 月"
    
    daily_tasks = {}
    for task in user_data["tasks"]:
        if task.get("deadline"):
            try:
                deadline = datetime.fromisoformat(task["deadline"])
                if deadline.year == target_year and deadline.month == target_month:
                    day = deadline.day
                    if day not in daily_tasks:
                        daily_tasks[day] = []
                    daily_tasks[day].append(task)
            except:
                pass
    
    embed = discord.Embed(
        title=f"📅 {month_name} 行事曆",
        description="有任務的日期會顯示 * 標誌",
        color=discord.Color.blue()
    )
    
    weekdays = "一  二  三  四  五  六  日"
    calendar_text = f"```\n    {weekdays}\n"
    
    for week in cal:
        week_text = ""
        for day in week:
            if day == 0:
                week_text += "    "
            else:
                marker = "*" if day in daily_tasks else " "
                week_text += f"{day:2d}{marker} "
        calendar_text += week_text + "\n"
    
    calendar_text += "```"
    
    embed.add_field(name="月曆", value=calendar_text, inline=False)
    
    total_tasks = sum(len(tasks) for tasks in daily_tasks.values())
    days_with_tasks = len(daily_tasks)
    
    embed.add_field(name="📊 統計", value=f"{total_tasks} 個任務 | {days_with_tasks} 天有安排", inline=False)
    
    if daily_tasks:
        task_summary = []
        sorted_days = sorted(daily_tasks.keys())
        
        for day in sorted_days[:10]:
            tasks = daily_tasks[day]
            task_count = len(tasks)
            completed = sum(1 for t in tasks if t.get("completed", False))
            
            status = "✅" if completed == task_count else "⏳"
            task_summary.append(f"{status} {target_month}/{day} - {task_count} 個任務 ({completed} 已完成)")
        
        if len(sorted_days) > 10:
            task_summary.append(f"... 及其他 {len(sorted_days) - 10} 天")
        
        embed.add_field(
            name="📋 任務日期",
            value="\n".join(task_summary),
            inline=False
        )
    
    embed.set_footer(text="使用 /查看日期 來查看特定日期的詳細行程")
    
    # ✅ 用 followup 而不是 respond
    await ctx.followup.send(embed=embed)

@bot.slash_command(name="查看日期", description="查看特定日期的所有行程")
async def view_date(
    ctx: discord.ApplicationContext,
    日期: Option(str, "日期(格式:YYYY-MM-DD)", required=True)
):
    """查看特定日期的行程"""
    user_id = str(ctx.author.id)
    user_data = get_user_data(user_id)
    
    try:
        target_date = datetime.strptime(日期, "%Y-%m-%d")
    except ValueError:
        await ctx.respond("❌ 日期格式錯誤!請使用 YYYY-MM-DD 格式(例如:2026-02-15)")
        return
    
    tasks_on_date = []
    for task in user_data["tasks"]:
        if task.get("deadline"):
            try:
                deadline = datetime.fromisoformat(task["deadline"])
                if deadline.date() == target_date.date():
                    tasks_on_date.append(task)
            except:
                pass
    
    weekday = ['一', '二', '三', '四', '五', '六', '日'][target_date.weekday()]
    
    embed = discord.Embed(
        title=f"📅 {日期} (週{weekday}) 的行程",
        description=f"共 {len(tasks_on_date)} 個任務",
        color=discord.Color.blue()
    )
    
    if not tasks_on_date:
        embed.description = "🎉 這天沒有任何任務!"
        embed.set_footer(text="使用 /新增作業 或 /新增複習 來新增任務")
    else:
        homework = [t for t in tasks_on_date if t["type"] == "作業"]
        review = [t for t in tasks_on_date if t["type"] == "複習"]
        
        total_time = sum(t["estimated_time"] for t in tasks_on_date)
        completed_count = sum(1 for t in tasks_on_date if t.get("completed", False))
        
        if homework:
            hw_text = []
            for task in homework:
                status = "✅" if task.get("completed") else "⏳"
                hw_text.append(
                    f"{status} #{task['id']} {task['subject']} ({task['pages']}) - {task['estimated_time']}分鐘"
                )
            embed.add_field(
                name=f"📝 作業 ({len(homework)}個)",
                value="\n".join(hw_text),
                inline=False
            )
        
        if review:
            rv_text = []
            for task in review:
                status = "✅" if task.get("completed") else "⏳"
                confidence_emoji = "🔴" if task['confidence'] <= 3 else "🟡" if task['confidence'] <= 6 else "🟢"
                rv_text.append(
                    f"{status} #{task['id']} {task['subject']} ({task['range']}) {confidence_emoji}{task['confidence']} - {task['estimated_time']}分鐘"
                )
            embed.add_field(
                name=f"📚 複習 ({len(review)}個)",
                value="\n".join(rv_text),
                inline=False
            )
        
        embed.add_field(
            name="📊 統計",
            value=f"預估總時間: {total_time} 分鐘 ({total_time/60:.1f} 小時)\n完成進度: {completed_count}/{len(tasks_on_date)}",
            inline=False
        )
    
    await ctx.respond(embed=embed)

@bot.slash_command(name="我的任務", description="查看所有任務列表")
async def my_tasks(ctx: discord.ApplicationContext):
    """顯示所有任務"""
    user_id = str(ctx.author.id)
    user_data = get_user_data(user_id)
    
    if not user_data["tasks"]:
        await ctx.respond("你還沒有新增任何任務!使用 `/新增作業` 或 `/新增複習` 來開始吧 📚")
        return
    
    embed = discord.Embed(
        title=f"📚 所有任務",
        color=discord.Color.blue()
    )
    
    incomplete = [t for t in user_data["tasks"] if not t.get("completed", False)]
    completed = [t for t in user_data["tasks"] if t.get("completed", False)]
    
    if incomplete:
        hw_list = []
        rv_list = []
        
        for task in incomplete:
            if task["type"] == "作業":
                deadline = datetime.fromisoformat(task["deadline"]).strftime("%m/%d")
                hw_list.append(f"⏳ #{task['id']} {task['subject']} ({task['pages']}) - 截止:{deadline}")
            else:
                confidence_emoji = "🔴" if task['confidence'] <= 3 else "🟡" if task['confidence'] <= 6 else "🟢"
                rv_list.append(f"⏳ #{task['id']} {task['subject']} ({task['range']}) {confidence_emoji}{task['confidence']}")
        
        if hw_list:
            embed.add_field(
                name=f"📝 作業 ({len(hw_list)}個)",
                value="\n".join(hw_list[:10]),
                inline=False
            )
        
        if rv_list:
            embed.add_field(
                name=f"📚 複習 ({len(rv_list)}個)",
                value="\n".join(rv_list[:10]),
                inline=False
            )
    
    if completed:
        completed_text = "\n".join([
            f"✅ #{t['id']} {t['subject']} ({t['type']})"
            for t in completed[-5:]
        ])
        embed.add_field(
            name=f"✅ 已完成 (最近5個)",
            value=completed_text,
            inline=False
        )
    
    total_estimated = sum(t['estimated_time'] for t in user_data["tasks"])
    embed.add_field(
        name="📊 統計",
        value=f"總任務: {len(user_data['tasks'])} | 待完成: {len(incomplete)} | 已完成: {len(completed)}\n預估總時間: {total_estimated} 分鐘 ({total_estimated/60:.1f} 小時)",
        inline=False
    )
    
    await ctx.respond(embed=embed)

# ==================== 番茄鐘與語音指令 ====================

active_pomodoros = {} 
background_music_tasks = {}

async def play_bell_sound(ctx, duration_seconds=10):
    """連接語音頻道並循環播放音檔一段時間"""
    if not ctx.author.voice:
        await ctx.channel.send("❌ 你必須在語音頻道中才能播放音樂！")
        return

    voice_channel = ctx.author.voice.channel
    sound_file = SOUND_FILE_PATH

    # 檢查檔案是否存在
    if not os.path.exists(sound_file):
        await ctx.channel.send(f"❌ 找不到音效檔案: {sound_file}")
        logging.error(f"音效檔案不存在: {sound_file}")
        return

    try:
        vc = ctx.voice_client
        if not vc:
            vc = await voice_channel.connect()
        elif vc.channel != voice_channel:
            await vc.move_to(voice_channel)

        end_time = asyncio.get_event_loop().time() + duration_seconds
        
        while asyncio.get_event_loop().time() < end_time and vc.is_connected():
            if not vc.is_playing():
                vc.play(discord.FFmpegPCMAudio(sound_file))
            await asyncio.sleep(0.5)
        
        if vc.is_playing():
            vc.stop()
            
    except Exception as e:
        logging.error(f"語音播放出錯: {e}")
        await ctx.channel.send(f"⚠️ 語音播放失敗: {e}")

async def play_infinite_bell(ctx, user_id):
    """使用 FFmpeg 內建循環功能實現無縫無限播放"""
    if not ctx.author.voice:
        await ctx.channel.send("❌ 你必須在語音頻道中才能播放音樂！")
        return

    voice_channel = ctx.author.voice.channel
    sound_file = SOUND_FILE_PATH

    # 檢查檔案是否存在
    if not os.path.exists(sound_file):
        await ctx.channel.send(f"❌ 找不到音效檔案: {sound_file}")
        logging.error(f"音效檔案不存在: {sound_file}")
        return

    try:
        vc = ctx.voice_client
        if not vc:
            vc = await voice_channel.connect()
        elif vc.channel != voice_channel:
            await vc.move_to(voice_channel)

        logging.info(f"🔁 開始無限循環播放音效 (使用者: {user_id})")
        
        ffmpeg_options = {
            'before_options': '-stream_loop -1',
            'options': '-vn'
        }
        
        source = discord.FFmpegPCMAudio(sound_file, **ffmpeg_options)
        vc.play(source)
        
        while vc.is_connected() and user_id in background_music_tasks:
            await asyncio.sleep(1)
        
        if vc.is_playing():
            vc.stop()
        
        logging.info(f"⏹️ 停止無限循環播放 (使用者: {user_id})")
            
    except asyncio.CancelledError:
        logging.info(f"🛑 無限播放被取消 (使用者: {user_id})")
        if vc and vc.is_playing():
            vc.stop()
    except Exception as e:
        logging.error(f"❌ 無限播放出錯: {e}")
        await ctx.channel.send(f"⚠️ 音樂播放失敗: {e}")

async def pomodoro_task_logic(ctx, user_id):
    """番茄鐘核心流程"""
    try:
        await ctx.channel.send(
            f"🍅 {ctx.author.mention} **專注模式開始！** 倒數 25 分鐘。\n"
            f"🎵 背景音樂已啟動，使用 `/停止番茄鐘` 來停止。\n"
            f"讓我們再創高峰，這會很偉大！"
        )
        
        music_task = asyncio.create_task(play_infinite_bell(ctx, user_id))
        background_music_tasks[user_id] = music_task
        
        await asyncio.sleep(25 * 60) 
        
        await ctx.channel.send(
            f"{ctx.author.mention} ⏰ **專注時間到！** 休息時間開始。\n"
            f"🎵 音樂持續播放中..."
        )

        await ctx.channel.send(f"☕ {ctx.author.mention} 現在自動進入 **5 分鐘休息模式**。喝杯咖啡，放鬆一下。")
        await asyncio.sleep(5 * 60) 

        await ctx.channel.send(
            f"{ctx.author.mention} ⚡ **休息結束！** 能量充滿，準備好開始下一場勝利了嗎？\n"
            f"💡 使用 `/停止番茄鐘` 來停止音樂和計時器。"
        )

        if user_id in active_pomodoros:
            del active_pomodoros[user_id]
            
    except asyncio.CancelledError:
        logging.info(f"使用者 {user_id} 的番茄鐘已取消")
        if user_id in background_music_tasks:
            background_music_tasks[user_id].cancel()
            del background_music_tasks[user_id]
    except Exception as e:
        logging.error(f"番茄鐘流程出錯: {e}")
        await ctx.channel.send(f"⚠️ 番茄鐘發生錯誤: {e}")

@bot.slash_command(name="番茄鐘", description="開始番茄鐘 (25分專注+5分休息)")
async def pomodoro(ctx: discord.ApplicationContext):
    """開始番茄鐘"""
    user_id = ctx.author.id
    
    # ✅ 先回應，避免 timeout
    if user_id in active_pomodoros:
        active_pomodoros[user_id].cancel()
        await ctx.respond("🔄 偵測到舊的計時器，已為你重新啟動！")
    else:
        await ctx.respond("🚀 番茄鐘啟動！大家一起加油！")

    if ctx.author.voice:
        try:
            if not ctx.voice_client:
                await ctx.author.voice.channel.connect()
            elif ctx.voice_client.channel != ctx.author.voice.channel:
                await ctx.voice_client.move_to(ctx.author.voice.channel)
        except Exception as e:
            logging.error(f"加入語音失敗: {e}")
            await ctx.channel.send(f"⚠️ 無法加入語音頻道: {e}")

    task = asyncio.create_task(pomodoro_task_logic(ctx, user_id))
    active_pomodoros[user_id] = task

@bot.slash_command(name="停止番茄鐘", description="停止目前的番茄鐘計時")
async def stop_pomodoro(ctx: discord.ApplicationContext):
    """停止番茄鐘"""
    user_id = ctx.author.id
    
    if user_id in active_pomodoros:
        active_pomodoros[user_id].cancel()
        del active_pomodoros[user_id]
        
        if user_id in background_music_tasks:
            background_music_tasks[user_id].cancel()
            del background_music_tasks[user_id]
        
        if ctx.voice_client:
            await ctx.voice_client.disconnect()
            
        await ctx.respond("🛑 番茄鐘已停止。我們不需要休息，我們只需要勝利！")
    else:
        await ctx.respond("❌ 你目前沒有正在執行的番茄鐘。")

@bot.slash_command(name="停止音樂", description="停止背景提醒音樂")
async def stop_music(ctx: discord.ApplicationContext):
    """停止無限循環的提醒音樂"""
    user_id = ctx.author.id
    
    if user_id in background_music_tasks:
        background_music_tasks[user_id].cancel()
        del background_music_tasks[user_id]
        
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.stop()
        
        await ctx.respond("🔇 已停止提醒音樂！")
    else:
        await ctx.respond("❌ 目前沒有正在播放的提醒音樂。")

@bot.slash_command(name="加入語音", description="讓機器人進入你的語音頻道")
async def join_voice(ctx: discord.ApplicationContext):
    """手動加入語音頻道"""
    if not ctx.author.voice:
        await ctx.respond("❌ 你必須先進入一個語音頻道，我才能加入！")
        return
    
    channel = ctx.author.voice.channel
    
    try:
        if ctx.voice_client:
            await ctx.voice_client.move_to(channel)
        else:
            await channel.connect()
        await ctx.respond(f"🔊 已加入語音頻道：**{channel.name}**")
    except Exception as e:
        logging.error(f"加入語音失敗: {e}")
        await ctx.respond(f"❌ 無法加入語音頻道: {e}")

@bot.slash_command(name="測試音效", description="測試播放提示音")
async def test_sound(
    ctx: discord.ApplicationContext,
    播放秒數: Option(int, "播放秒數", required=False, default=5, min_value=1, max_value=30)
):
    """測試音效播放"""
    await ctx.defer()
    
    if not ctx.author.voice:
        await ctx.followup.send("❌ 你必須先進入一個語音頻道！")
        return
    
    await ctx.followup.send(f"🔊 開始播放測試音效 ({播放秒數} 秒)...")
    await play_bell_sound(ctx, duration_seconds=播放秒數)
    await ctx.channel.send(f"✅ 測試完成！")

@bot.slash_command(name="測試無限音樂", description="測試無限循環播放音樂")
async def test_infinite_music(ctx: discord.ApplicationContext):
    """測試無限循環播放"""
    await ctx.defer()
    
    if not ctx.author.voice:
        await ctx.followup.send("❌ 你必須先進入一個語音頻道！")
        return
    
    user_id = ctx.author.id
    
    if user_id in background_music_tasks:
        background_music_tasks[user_id].cancel()
        del background_music_tasks[user_id]
    
    await ctx.followup.send("🔁 開始無限循環播放音樂！使用 `/停止音樂` 來停止。")
    
    music_task = asyncio.create_task(play_infinite_bell(ctx, user_id))
    background_music_tasks[user_id] = music_task

# ==================== Events ====================

@bot.event
async def on_ready():
    load_all_knowledge()
    logging.info(f'{bot.user} 已上線!讀書計畫機器人準備就緒 📚')
    print(f'{bot.user} 已登入')
    print(f"✅ 題庫已載入，共 {len(knowledge_cache)} 個分類")
    print("\n可用指令:")
    print("  💙 /談心 - 跟機器人聊聊天，舒緩讀書壓力")
    print("  📝 /出題 - 從題庫中隨機出題")
    print("  /教學 - 查看使用教學")
    print("  /新增作業 - 新增作業任務")
    print("  /新增複習 - 新增複習任務")
    print("  /番茄鐘 - 開始專注模式\n")

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    
    if bot.user.mentioned_in(message):
        prompt = message.content.replace(f'<@{bot.user.id}>', '').strip()
        
        if not prompt:
            await message.reply("有什麼我可以幫助你的嗎? 📖\n使用 `/談心` 來跟我聊聊，或使用 `/教學` 查看所有指令!")
            return
        
        thinking_msg = await message.reply("思考中... 🤔")
        
        try:
            answer = await asyncio.wait_for(generate_reply(prompt), timeout=60.0)
        except asyncio.TimeoutError:
            answer = "抱歉,思考時間過長,請稍後再試。"
        except Exception as e:
            answer = "抱歉,發生了一些錯誤,請稍後再試。"
            logging.error(f"AI錯誤: {e}")
        
        await thinking_msg.edit(content=answer)

# ==================== 啟動機器人 ====================

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)