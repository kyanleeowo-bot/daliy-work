"""
排程機器人 - 核心邏輯
- 接收 Telegram 訊息,存進 SQLite 當作「待辦事項池」
- 每天固定時間呼叫 Gemini API,依據目前所有未完成事項排出當日順序
- 把排好的結果推播回 Telegram

環境變數(部署時在 Railway/Render 的 Variables 分頁設定,不要寫死在程式裡):
  TELEGRAM_BOT_TOKEN   -> 從 BotFather 拿到的 token
  GEMINI_API_KEY       -> 從 Google AI Studio 拿到的 key
  CHAT_ID              -> 你自己的 Telegram chat id(第一次跟 bot 說話後,程式會印出來,填進去)
  PUSH_HOUR            -> 每天推播的時間(24小時制,預設 21,代表晚上9點)
"""

import os
import sqlite3
import logging
from datetime import datetime, timedelta

from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, ContextTypes, filters
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import google.generativeai as genai

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("schedule-bot")

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
CHAT_ID = os.environ.get("CHAT_ID")  # 一開始可能還沒有,先允許空值
PUSH_HOUR = int(os.environ.get("PUSH_HOUR", "21"))

DB_PATH = os.environ.get("DB_PATH", "tasks.db")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.0-flash")


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            done INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()


def add_task(content: str):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO tasks (content, created_at, done) VALUES (?, ?, 0)",
        (content, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def get_open_tasks():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, content, created_at FROM tasks WHERE done = 0 ORDER BY id"
    ).fetchall()
    conn.close()
    return rows


def mark_done(task_id: int):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE tasks SET done = 1 WHERE id = ?", (task_id,))
    conn.commit()
    conn.close()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        f"哈囉!你的 chat id 是 {chat_id}\n"
        "把這組數字設定成環境變數 CHAT_ID,我才能主動推播給你。\n\n"
        "設定好之後,直接傳訊息給我就可以加入待辦事項,"
        "例如:「這禮拜要交報告、看牙醫、健身兩次」。\n"
        "輸入 /list 可以看目前所有還沒完成的事。\n"
        "輸入 /done 3 代表把編號3標記完成。\n"
        "輸入 /plan 可以立刻要我重新排一次今天的行程(不用等到晚上9點)。"
    )


async def list_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tasks = get_open_tasks()
    if not tasks:
        await update.message.reply_text("目前沒有待辦事項,清爽得很。")
        return
    lines = [f"{t[0]}. {t[1]}" for t in tasks]
    await update.message.reply_text("目前待辦:\n" + "\n".join(lines))


async def done_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("用法:/done <編號>,例如 /done 3")
        return
    try:
        task_id = int(context.args[0])
        mark_done(task_id)
        await update.message.reply_text(f"已把 #{task_id} 標記完成 ✅")
    except ValueError:
        await update.message.reply_text("編號要是數字喔")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """任何非指令的一般文字,都當作新的待辦事項存進去。"""
    text = update.message.text
    add_task(text)
    await update.message.reply_text(
        "已收進待辦清單。輸入 /plan 可以立刻幫你重新排程,"
        "或是等晚上固定時間我會自動推播。"
    )


def build_prompt(tasks):
    task_lines = "\n".join([f"- {t[1]}(記錄於 {t[2]}）" for t in tasks])
    today = datetime.now().strftime("%Y-%m-%d")
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    return f"""你是一個幫用戶安排每日行程的助理。今天是 {today},請幫忙規劃 {tomorrow}(明天）該做的事。

以下是用戶目前所有還沒完成的事項(沒有標注明確時間的,由你依常理判斷輕重緩急）:
{task_lines}

請用繁體中文,輸出精簡的訊息,格式參考:
📅 明天行程
・(項目)

✅ 待辦事項(暫不用處理，但列出提醒)
・(項目)

規則:
- 有明確截止日期或時間的事項優先排入
- 沒寫時間的事項,依常理判斷是否該提前處理
- 不要輸出多餘的說明文字,直接給排程結果
"""


async def generate_and_send(app: Application, chat_id: str):
    tasks = get_open_tasks()
    if not tasks:
        await app.bot.send_message(chat_id=chat_id, text="目前沒有待辦事項,今天休息 🎉")
        return
    prompt = build_prompt(tasks)
    response = model.generate_content(prompt)
    await app.bot.send_message(chat_id=chat_id, text=response.text)


async def plan_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("排程中,稍等...")
    await generate_and_send(context.application, update.effective_chat.id)


async def scheduled_push(app: Application):
    if not CHAT_ID:
        log.warning("尚未設定 CHAT_ID,略過自動推播。請先跟 bot 說話一次拿到 chat id。")
        return
    await generate_and_send(app, CHAT_ID)


def main():
    init_db()
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("list", list_tasks))
    app.add_handler(CommandHandler("done", done_task))
    app.add_handler(CommandHandler("plan", plan_now))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        lambda: app.create_task(scheduled_push(app)),
        "cron",
        hour=PUSH_HOUR,
        minute=0,
    )
    scheduler.start()

    log.info(f"Bot 啟動,每天 {PUSH_HOUR}:00 自動推播。")
    app.run_polling()


if __name__ == "__main__":
    main()
