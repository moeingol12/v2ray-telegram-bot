import os
import re
import json
import time
import asyncio
import subprocess
import urllib.request
import zipfile
import stat
import aiohttp
from fastapi import FastAPI
import uvicorn
import threading
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# ==================== تنظیمات ====================
BOT_TOKEN = "TOKEN_HERE"  # توکن ربات تلگرام خود را اینجا بگذارید
DEFAULT_CHANNELS = ["v2ray_free_conf", "v2ray_config"]  # بدون @
TEST_URL = "https://www.gstatic.com/generate_204"
XRAY_PORT = 10809
# =================================================

channels_list = list(DEFAULT_CHANNELS)

# راه‌اندازی یک وب‌سایت کوچک برای اینکه رندر سرویس را فعال نگه دارد
app_web = FastAPI()

@app_web.get("/")
def home():
    return {"status": "Bot is running!"}

def run_web():
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app_web, host="0.0.0.0", port=port)

def setup_xray_core():
    if not os.path.exists("./xray"):
        print("Downloading Xray core...")
        url = "https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip"
        zip_path = "xray.zip"
        try:
            urllib.request.urlretrieve(url, zip_path)
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extract("xray", ".")
            os.chmod("xray", os.stat("xray").st_mode | stat.S_IEXEC)
            os.remove(zip_path)
            print("Xray core ready.")
        except Exception as e:
            print(f"Error downloading Xray: {e}")

async def fetch_configs_from_channel(channel: str) -> list[str]:
    url = f"https://t.me/s/{channel}"
    configs = []
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    pattern = r'(vless://[^\s<"]+|vmess://[^\s<"]+|trojan://[^\s<"]+|ss://[^\s<"]+)'
                    configs = re.findall(pattern, html)
    except Exception as e:
        print(f"Error fetching {channel}: {e}")
    return configs

def generate_xray_config_file():
    config_json = {
        "inbounds": [{
            "port": XRAY_PORT,
            "protocol": "socks",
            "settings": {"auth": "noauth", "udp": True}
        }],
        "outbounds": [{"protocol": "freedom"}]
    }
    with open("temp_config.json", "w") as f:
        json.dump(config_json, f)

async def test_real_ping(config_str: str) -> float:
    try:
        generate_xray_config_file()
        process = subprocess.Popen(["./xray", "-c", "temp_config.json"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        await asyncio.sleep(0.5)
        
        start_time = time.time()
        async with aiohttp.ClientSession() as session:
            async with session.get(TEST_URL, timeout=aiohttp.ClientTimeout(total=3)) as resp:
                if resp.status in [200, 204]:
                    latency = round((time.time() - start_time) * 1000, 2)
                    process.terminate()
                    return latency
        process.terminate()
    except Exception:
        pass
    return float('inf')

async def process_and_find_best():
    all_configs = []
    for ch in channels_list:
        cfgs = await fetch_configs_from_channel(ch)
        all_configs.extend(cfgs)
        
    unique_configs = list(set(all_configs))[:20]
    best_config = None
    best_latency = float('inf')
    working_configs = []

    for cfg in unique_configs:
        latency = await test_real_ping(cfg)
        if latency < float('inf'):
            working_configs.append(cfg)
            if latency < best_latency:
                best_latency = latency
                best_config = cfg

    return best_config, best_latency, working_configs

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("⚡ دریافت سریع‌ترین کانفیگ", callback_data="get_fastest")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    msg = "🤖 **ربات تست ابری V2Ray**\n\nبرای دریافت سریع‌ترین کانفیگ دکمه زیر را بزنید:"
    if update.message:
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=reply_markup)
    else:
        await update.callback_query.message.edit_text(msg, parse_mode="Markdown", reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "get_fastest":
        await query.edit_message_text("⏳ **در حال تست کانفیگ‌ها در فضای ابری...**")
        best_cfg, latency, _ = await process_and_find_best()
        
        if best_cfg:
            text = f"✅ **سریع‌ترین کانفیگ:**\n⚡ پینگ: `{latency} ms`\n\n```\n{best_cfg}\n```"
        else:
            text = "❌ **کانفیگ سالمی یافت نشد.**"

        keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data="back_home")]]
        await query.message.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "back_home":
        await start(update, context)

def main():
    setup_xray_core()
    
    # اجرای وب‌سایت در یک ترد جداگانه
    t = threading.Thread(target=run_web)
    t.daemon = True
    t.start()

    # اجرای ربات تلگرام
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    print("Bot is ready...")
    app.run_polling()

if __name__ == "__main__":
    main()
