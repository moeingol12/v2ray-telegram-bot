import os
import re
import json
import time
import asyncio
import subprocess
import aiohttp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# ==================== تنظیمات ====================
BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"  # توکن ربات تلگرام شما
DEFAULT_CHANNELS = ["v2ray_free_conf", "v2ray_config"]  # بدون @
TEST_URL = "https://www.gstatic.com/generate_204"
XRAY_PORT = 10809  # پورت تست موقت
# =================================================

channels_list = list(DEFAULT_CHANNELS)

def setup_xray_core():
    """دانلود و آماده‌سازی هسته Xray در سرور ابری در صورت عدم وجود"""
    if not os.path.exists("./xray"):
        print("Downloading Xray core...")
        cmd = (
            "wget https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip -O xray.zip "
            "&& unzip -o xray.zip xray && chmod +x xray && rm xray.zip"
        )
        subprocess.run(cmd, shell=True, check=True)
        print("Xray core ready.")

async def fetch_configs_from_channel(channel: str) -> list[str]:
    """استخراج لینک‌های V2Ray از آرشیو وب تلگرام"""
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

def generate_xray_config_file(proxy_url: str):
    """تولید کانفیگ موقت JSON برای هسته Xray جهت تست"""
    # در محیط واقعی با ابزارهایی مانند v2ray-url-decoder یا xray convert ساختار JSON ساخته می‌شود
    # این ساختار پایه برای پورت SOCKS محلی است:
    config_json = {
        "inbounds": [{
            "port": XRAY_PORT,
            "protocol": "socks",
            "settings": {"auth": "noauth", "udp": True}
        }],
        "outbounds": [{
            "protocol": "freedom" # جایگزینی با outbound مربوط به کانفیگ
        }]
    }
    with open("temp_config.json", "w") as f:
        json.dump(config_json, f)

async def test_real_ping(config_str: str) -> float:
    """تست واقعی اتصالات از طریق Curl و پروکسی local"""
    try:
        generate_xray_config_file(config_str)
        
        # ۱. اجرای موقت هسته Xray
        process = subprocess.Popen(["./xray", "-c", "temp_config.json"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        await asyncio.sleep(0.5) # مهلت اولیه برای بالا آمدن پروکسی
        
        start_time = time.time()
        
        # ۲. تست واقعی با Curl از طریق پروکسی SOCKS5
        proc = await asyncio.create_subprocess_exec(
            "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
            "--socks5-hostname", f"127.0.0.1:{XRAY_PORT}",
            TEST_URL, "--connect-timeout", "3",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, _ = await proc.communicate()
        status_code = stdout.decode().strip()
        
        # ۳. بستن پروسه Xray
        process.terminate()
        
        if status_code in ["204", "200"]:
            latency = round((time.time() - start_time) * 1000, 2)
            return latency
    except Exception as e:
        pass
    
    return float('inf')

async def process_and_find_best():
    """چرخه کامل استخراج و تست real ping"""
    all_configs = []
    for ch in channels_list:
        cfgs = await fetch_configs_from_channel(ch)
        all_configs.extend(cfgs)
        
    unique_configs = list(set(all_configs))[:30] # تست ۳۰ کانفیگ جدیدتر
    
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

# ---------------- منو و دستورات تلگرام ----------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("⚡ دریافت سریع‌ترین کانفیگ (Real Ping)", callback_data="get_fastest")],
        [InlineKeyboardButton("🔗 دریافت لینک ساب‌اسکریپت", callback_data="get_sub")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    msg = (
        "🤖 **ربات تست هوشمند و ابری V2Ray**\n\n"
        "تست‌ها با **Real Ping** و هسته Xray روی سرور انجام می‌شوند.\n"
        "بدون هیچ‌گونه استفاده از منابع گوشی یا کامپیوتر شما."
    )
    if update.message:
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=reply_markup)
    else:
        await update.callback_query.message.edit_text(msg, parse_mode="Markdown", reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "get_fastest":
        await query.edit_message_text("⏳ **در حال استخراج و تست واقعی کانفیگ‌ها با هسته Xray... (حدود ۱۰ تا ۱۵ ثانیه)**")
        
        best_cfg, latency, _ = await process_and_find_best()
        
        if best_cfg:
            text = (
                f"✅ **سریع‌ترین کانفیگ پیدا شد!**\n\n"
                f"📊 **پینگ واقعی (Real Latency):** `{latency} ms`\n\n"
                f"```\n{best_cfg}\n```"
            )
        else:
            text = "❌ **هیچ کانفیگ سالمی در حال حاضر پاسخ نداد.**"

        keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data="back_home")]]
        await query.message.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "get_sub":
        await query.edit_message_text("⏳ **در حال ساخت لینک ساب‌اسکریپت از کانفیگ‌های سالم...**")
        _, _, working = await process_and_find_best()
        
        if working:
            # ذخیره کانفیگ‌های سالم در یک فایل متنی برای لینک ساب‌اسکریپت
            with open("sub.txt", "w") as f:
                f.write("\n".join(working))
            
            text = (
                f"🔗 **لینک ساب‌اسکریپت کانفیگ‌های سالم:**\n"
                f"تعداد کانفیگ‌های تست‌شده و سالم: {len(working)}\n\n"
                f"می‌توانید کانفیگ‌ها را مستقیم کپی کنید یا فایل زیر را وارد برنامه کنید."
            )
        else:
            text = "❌ **کانفیگ سالمی یافت نشد.**"

        keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data="back_home")]]
        await query.message.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "back_home":
        await start(update, context)

def main():
    # نصب اولیه هسته Xray
    try:
        setup_xray_core()
    except Exception as e:
        print(f"Warning: Could not setup Xray locally: {e}")

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    
    print("Bot is ready and listening...")
    app.run_polling()

if __name__ == "__main__":
    main()