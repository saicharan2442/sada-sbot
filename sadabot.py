import re
import random
import asyncio
import aiohttp
import requests
from io import BytesIO

from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

from telegram import Update, InputFile, InputMediaPhoto
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

BOT_TOKEN = 'ADD YOUR BOT TOKEN HERE'

COUNTRY_FLAGS = {
    "FRANCE": "🇫🇷", "UNITED STATES": "🇺🇸", "BRAZIL": "🇧🇷", "NAMIBIA": "🇳🇦",
    "INDIA": "🇮🇳", "GERMANY": "🇩🇪", "THAILAND": "🇹🇭", "MEXICO": "🇲🇽", "RUSSIA": "🇷🇺",
}

# ----- BIN Extraction and API calls -----

def extract_bin(bin_input):
    match = re.match(r'(\d{6,16})', bin_input)
    if not match:
        return None
    bin_number = match.group(1)
    return bin_number.ljust(16, 'x') if len(bin_number) == 6 else bin_number

async def generate_cc_async(bin_number):
    url = f"https://drlabapis.onrender.com/api/ccgenerator?bin={bin_number}&count=10"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=15) as response:
                if response.status == 200:
                    raw_text = await response.text()
                    return raw_text.strip().split("\n")
                else:
                    return {"error": f"API error: {response.status}"}
    except Exception as e:
        return {"error": str(e)}

async def lookup_bin(bin_number):
    url = f"https://drlabapis.onrender.com/api/bin?bin={bin_number[:6]}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=15) as response:
                if response.status == 200:
                    bin_data = await response.json()
                    country_name = bin_data.get('country', 'NOT FOUND').upper()
                    return {
                        "bank": bin_data.get('issuer', 'NOT FOUND').upper(),
                        "card_type": bin_data.get('type', 'NOT FOUND').upper(),
                        "network": bin_data.get('scheme', 'NOT FOUND').upper(),
                        "tier": bin_data.get('tier', 'NOT FOUND').upper(),
                        "country": country_name,
                        "flag": COUNTRY_FLAGS.get(country_name, "🏳️")
                    }
                else:
                    return {"error": f"API error: {response.status}"}
    except Exception as e:
        return {"error": str(e)}

def format_cc_response(data, bin_number, bin_info):
    if isinstance(data, dict) and "error" in data:
        return f"❌ ERROR: {data['error']}"
    if not data:
        return "❌ NO CARDS GENERATED."

    formatted_text = f"𝗕𝗜𝗡 ⇾ <code>{bin_number[:6]}</code>\n"
    formatted_text += f"𝗔𝗺𝗼𝘂𝗻𝘁 ⇾ <code>{len(data)}</code>\n\n"
    for card in data:
        formatted_text += f"<code>{card.upper()}</code>\n"
    formatted_text += f"\n𝗜𝗻𝗳𝗼: {bin_info.get('card_type', 'NOT FOUND')} - {bin_info.get('network', 'NOT FOUND')} ({bin_info.get('tier', 'NOT FOUND')})\n"
    formatted_text += f"𝐈𝐬𝐬𝐮𝐞𝐫: {bin_info.get('bank', 'NOT FOUND')}\n"
    formatted_text += f"𝗖𝗼𝘂𝗻𝘁𝗿𝘆: {bin_info.get('country', 'NOT FOUND')} {bin_info.get('flag', '🏳️')}"
    return formatted_text

# ----- Image Generation -----

def generate_image_url(prompt: str = ""):
    base_url = "https://image.pollinations.ai/prompt/"
    seed = random.randint(1000000000, 9999999999)
    full_url = f"{base_url}{prompt.replace(' ', '%20')}?width=1024&height=1024&seed={seed}&nologo=true&model=flux-pro"
    return full_url

def download_image(url, retries=3, timeout=30):
    for attempt in range(retries):
        try:
            response = requests.get(url, timeout=timeout)
            response.raise_for_status()
            return BytesIO(response.content)
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            if attempt < retries - 1:
                continue
            else:
                raise
    raise Exception("Failed to download image")

# ----- PDF from Website Screenshot -----

async def generate_pdf_from_url(url: str):
    screenshot_url = f"https://image.thum.io/get/fullpage/noanimate/{url}"
    try:
        # Use aiohttp here for async
        async with aiohttp.ClientSession() as session:
            async with session.get(screenshot_url, timeout=30) as response:
                if response.status != 200:
                    return None, f"Screenshot API returned status {response.status}"
                img_bytes = await response.read()
                img_stream = BytesIO(img_bytes)
                image = Image.open(img_stream).convert("RGB")
                img_width_px, img_height_px = image.size

                pdf_width_pt = img_width_px
                pdf_height_pt = img_height_px

                pdf_buffer = BytesIO()
                c = canvas.Canvas(pdf_buffer, pagesize=(pdf_width_pt, pdf_height_pt))

                img_buffer = BytesIO()
                image.save(img_buffer, format='PNG')
                img_buffer.seek(0)

                c.drawImage(ImageReader(img_buffer), 0, 0, width=pdf_width_pt, height=pdf_height_pt)
                c.showPage()
                c.save()
                pdf_buffer.seek(0)

                return pdf_buffer, None

    except Exception as e:
        return None, str(e)

# ----- Handlers -----

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 Hello! Welcome to the bot.\n\n"
        "Here are the commands you can use:\n"
        "➡️ /gen <bin> - Generate credit card data for a BIN.\n"
        "➡️ /img <prompt> - Generate images from a prompt.\n"
        "➡️ /site <url> - Get a full-page screenshot of a website as a PDF.\n\n"
        "Example:\n"
        "/gen 457173\n"
        "/img a girl with rolex watch\n"
        "/site https://example.com\n"
    )
    await update.message.reply_text(text)

async def gen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Please provide a BIN like /gen 457173")
        return
    bin_input = context.args[0]
    bin_number = extract_bin(bin_input)
    if not bin_number:
        await update.message.reply_text("❌ Invalid BIN format.")
        return
    await update.message.reply_chat_action(action="typing")
    cc_data = await generate_cc_async(bin_number)
    bin_info = await lookup_bin(bin_number)
    response_text = format_cc_response(cc_data, bin_number, bin_info)
    await update.message.reply_text(response_text, parse_mode="HTML")

async def img(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "⚠️ Use a prompt after /img command!\nExample: /img a girl with rolex watch"
        )
        return
    prompt = " ".join(context.args)
    await update.message.reply_chat_action(action="upload_photo")

    try:
        images = []
        # Generate 3 images by default
        for i in range(3):
            image_url = generate_image_url(prompt)
            image_data = download_image(image_url)
            images.append(image_data)

        media_group = [
            InputMediaPhoto(media=image, caption=f"🌟 Image {idx+1} for: {prompt}")
            for idx, image in enumerate(images)
        ]

        await update.message.reply_media_group(media=media_group)
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to generate image: {e}")

async def site(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Please provide a URL like /site https://example.com")
        return
    url = context.args[0]
    if not re.match(r"^https?://", url):
        await update.message.reply_text("⚠️ Invalid URL. Must start with http:// or https://")
        return

    await update.message.reply_chat_action(action="upload_document")

    pdf_buffer, error = await generate_pdf_from_url(url)
    if error:
        await update.message.reply_text(f"❌ Failed to generate PDF. Error: {error}")
        return

    await update.message.reply_document(
        document=InputFile(pdf_buffer, filename="fullpage_screenshot.pdf"),
        caption=f"📄 Full page screenshot PDF of: {url}"
    )


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("gen", gen))
    app.add_handler(CommandHandler("img", img))
    app.add_handler(CommandHandler("site", site))

    print("🚀 Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
