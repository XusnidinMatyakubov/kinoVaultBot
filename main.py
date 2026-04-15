# Sozlamalar
#API_TOKEN = '7927133592:AAGlrKovkfot1Hu6ipt8Yrs2eYh7Zg5LuYE'
#ADMIN_ID = 8136481850

import asyncio
import logging
import sqlite3
import sys
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramRetryAfter, TelegramForbiddenError
from aiogram.client.default import DefaultBotProperties

# ====================== SOZLAMALAR ======================
API_TOKEN = '7927133592:AAGlrKovkfot1Hu6ipt8Yrs2eYh7Zg5LuYE'  # <-- Tokenni qo'ying
ADMIN_ID = 8136481850  # <-- O'zingizning ID'ingiz

CHANNELS = [
    "@kinovaulttime",
    "@Toshkentdan_Andijonga_Taksi",
    "@Namangandan_Tashkentga_taxi"
]

# ====================== BOT & DB ======================
bot = Bot(
    token=API_TOKEN,
    default=DefaultBotProperties(parse_mode="HTML")   # ← To'g'ri usul
)
dp = Dispatcher()

# Ma'lumotlar bazasi
conn = sqlite3.connect('kinovault.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS movies 
                  (code TEXT PRIMARY KEY, file_id TEXT)''')
conn.commit()


# ====================== OBUNA TEKSHIRISH (YAXSHILANGAN DEBUG VERSIYA) ======================
async def check_subscription(user_id: int) -> bool:
    """Har bir kanalni alohida tekshiradi va log qiladi"""
    logging.info(f"Obuna tekshirish boshlandi. User ID: {user_id}")

    all_subscribed = True

    for channel in CHANNELS:
        try:
            member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
            status = member.status
            logging.info(f"✅ {channel} → Status: {status}")

            if status in ["left", "kicked", "restricted"]:
                all_subscribed = False
                logging.warning(f"❌ {channel} ga obuna emas (status: {status})")

        except Exception as e:
            all_subscribed = False
            logging.error(f"❌ {channel} da XATOLIK | {type(e).__name__}: {e}")

    logging.info(f"Umumiy natija: {'✅ Obuna bor' if all_subscribed else '❌ Obuna yetarli emas'}")
    return all_subscribed


def get_sub_keyboard():
    builder = InlineKeyboardBuilder()
    for i, channel in enumerate(CHANNELS, 1):
        url = f"https://t.me/{channel.replace('@', '')}"
        builder.row(types.InlineKeyboardButton(
            text=f"🔗 {i}-kanalga a'zo bo'lish",
            url=url
        ))
    builder.row(types.InlineKeyboardButton(
        text="✅ Obunani tekshirish",
        callback_data="check_sub"
    ))
    return builder.as_markup()


# ====================== HANDLERLAR ======================

@dp.message(Command("start"))
async def start_handler(message: types.Message):
    try:
        if await check_subscription(message.from_user.id):
            await message.answer(
                "👋 Salom! Kino kodini yuboring, men sizga videoni topib beraman."
            )
        else:
            await message.answer(
                "Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling:",
                reply_markup=get_sub_keyboard()
            )
    except Exception as e:
        logging.error(f"Start handlerda xatolik: {e}")
        await message.answer("Xatolik yuz berdi. Keyinroq urinib ko'ring.")


@dp.callback_query(F.data == "check_sub")
async def callback_check(callback: types.CallbackQuery):
    try:
        if await check_subscription(callback.from_user.id):
            await callback.message.delete()
            await callback.message.answer(
                "✅ Rahmat! Endi kino kodini yuborishingiz mumkin."
            )
        else:
            await callback.answer(
                "❗ Hali hammaga obuna bo'lmadingiz!",
                show_alert=True
            )
    except Exception as e:
        logging.error(f"Callback tekshirishda xatolik: {e}")


@dp.message(F.video, F.from_user.id == ADMIN_ID)
async def save_video_handler(message: types.Message):
    try:
        if not message.caption:
            await message.answer("❗ Video ostiga kod yozing (caption).")
            return

        code = message.caption.strip()
        file_id = message.video.file_id

        cursor.execute(
            "INSERT OR REPLACE INTO movies (code, file_id) VALUES (?, ?)",
            (code, file_id)
        )
        conn.commit()

        await message.answer(f"✅ Video muvaffaqiyatli saqlandi!\nKod: <b>{code}</b>")
    except Exception as e:
        logging.error(f"Video saqlashda xatolik: {e}")
        await message.answer("❌ Videoni saqlashda xatolik yuz berdi.")


@dp.message(F.text)
async def get_video_handler(message: types.Message):
    try:
        # Obuna tekshirish
        if not await check_subscription(message.from_user.id):
            await message.answer(
                "Kino ko'rish uchun avval kanallarga obuna bo'ling:",
                reply_markup=get_sub_keyboard()
            )
            return

        code = message.text.strip()
        cursor.execute("SELECT file_id FROM movies WHERE code=?", (code,))
        result = cursor.fetchone()

        if result:
            await bot.send_video(
                chat_id=message.chat.id,
                video=result[0],
                caption=f"Kod: <b>{code}</b>\n@KinoVaultsBot"
            )
        else:
            await message.answer("⚠️ Bu kod bilan video topilmadi.")

    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after)
    except TelegramForbiddenError:
        pass  # Foydalanuvchi botni bloklagan
    except Exception as e:
        logging.error(f"Video yuborishda xatolik: {e}")
        await message.answer("Xatolik yuz berdi. Keyinroq urinib ko'ring.")


@dp.message(Command("status"))
async def status_handler(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return

    await message.answer("🔍 Obuna tekshirish boshlandi... Bot.log faylini oching.")

    is_sub = await check_subscription(message.from_user.id)
    if is_sub:
        await message.answer("✅ Siz barcha kanallarga obunasiz.")
    else:
        await message.answer("❌ Ba'zi kanallarga obuna emassiz. Bot.log ni tekshiring.")

# ====================== MAIN ======================

async def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler("bot.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout)
        ]
    )

    logging.info("🚀 Bot ishga tushdi...")

    try:
        await dp.start_polling(bot, skip_updates=True)
    except Exception as e:
        logging.critical(f"Bot to'xtab qoldi! Xatolik: {e}", exc_info=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Bot to'xtatildi (KeyboardInterrupt)")
    except Exception as e:
        logging.critical(f"Kutilmagan global xatolik: {e}", exc_info=True)