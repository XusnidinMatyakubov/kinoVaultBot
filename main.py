import asyncio
import logging
import os
import sqlite3
import sys
from pathlib import Path

from aiogram import Bot, Dispatcher, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder


BASE_DIR = Path(__file__).resolve().parent
IS_RENDER = os.getenv("RENDER", "").lower() == "true"


def get_env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None or not str(value).strip():
        raise RuntimeError(f"{name} muhit o'zgaruvchisi topilmadi.")
    return str(value).strip()


def resolve_db_path() -> Path:
    configured_path = os.getenv("DB_PATH")
    if configured_path:
        return Path(configured_path).expanduser().resolve()

    render_disk_root = os.getenv("RENDER_DISK_ROOT")
    if render_disk_root:
        return (Path(render_disk_root) / "kinovault.db").resolve()

    if IS_RENDER:
        return Path("/tmp/kinovault.db")

    return (BASE_DIR / "data" / "kinovault.db").resolve()

# Sozlamalar
LOCAL_BOT_TOKEN = "7927133592:AAGlrKovkfot1Hu6ipt8Yrs2eYh7Zg5LuYE"
LOCAL_ADMIN_ID = "8136481850"

API_TOKEN = get_env("BOT_TOKEN", LOCAL_BOT_TOKEN)
ADMIN_ID = int(get_env("ADMIN_ID", LOCAL_ADMIN_ID))
CHANNELS = [
    channel.strip()
    for channel in os.getenv(
        "CHANNELS",
        "@kinovaulttime,@Toshkentdan_Andijonga_Taksi,@Namangandan_Tashkentga_taxi",
    ).split(",")
    if channel.strip()
]

DB_PATH = resolve_db_path()
LOG_PATH = Path(os.getenv("LOG_PATH", str(BASE_DIR / "bot.log"))).expanduser().resolve()
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

bot = Bot(
    token=API_TOKEN,
    default=DefaultBotProperties(parse_mode="HTML"),
)
dp = Dispatcher()

conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()
cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS movies (
        code TEXT PRIMARY KEY,
        file_id TEXT
    )
    """
)
conn.commit()


async def check_subscription(user_id: int) -> bool:
    logging.info("Obuna tekshirish boshlandi. User ID: %s", user_id)
    all_subscribed = True

    for channel in CHANNELS:
        try:
            member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
            status = member.status
            logging.info("%s -> Status: %s", channel, status)

            if status in ["left", "kicked", "restricted"]:
                all_subscribed = False
                logging.warning("%s ga obuna emas (status: %s)", channel, status)
        except Exception as error:
            all_subscribed = False
            logging.error("%s da xatolik | %s: %s", channel, type(error).__name__, error)

    logging.info("Umumiy natija: %s", "Obuna bor" if all_subscribed else "Obuna yetarli emas")
    return all_subscribed


def get_sub_keyboard():
    builder = InlineKeyboardBuilder()
    for index, channel in enumerate(CHANNELS, 1):
        url = f"https://t.me/{channel.replace('@', '')}"
        builder.row(
            types.InlineKeyboardButton(
                text=f"{index}-kanalga a'zo bo'lish",
                url=url,
            )
        )
    builder.row(
        types.InlineKeyboardButton(
            text="Obunani tekshirish",
            callback_data="check_sub",
        )
    )
    return builder.as_markup()


@dp.message(Command("start"))
async def start_handler(message: types.Message):
    try:
        if await check_subscription(message.from_user.id):
            await message.answer("Salom. Kino kodini yuboring, men sizga videoni topib beraman.")
        else:
            await message.answer(
                "Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling:",
                reply_markup=get_sub_keyboard(),
            )
    except Exception as error:
        logging.error("Start handlerda xatolik: %s", error)
        await message.answer("Xatolik yuz berdi. Keyinroq urinib ko'ring.")


@dp.callback_query(F.data == "check_sub")
async def callback_check(callback: types.CallbackQuery):
    try:
        if await check_subscription(callback.from_user.id):
            await callback.message.delete()
            await callback.message.answer("Rahmat. Endi kino kodini yuborishingiz mumkin.")
        else:
            await callback.answer("Hali hammaga obuna bo'lmadingiz.", show_alert=True)
    except Exception as error:
        logging.error("Callback tekshirishda xatolik: %s", error)


@dp.message(F.video, F.from_user.id == ADMIN_ID)
async def save_video_handler(message: types.Message):
    try:
        if not message.caption:
            await message.answer("Video ostiga kod yozing.")
            return

        code = message.caption.strip()
        file_id = message.video.file_id

        cursor.execute(
            "INSERT OR REPLACE INTO movies (code, file_id) VALUES (?, ?)",
            (code, file_id),
        )
        conn.commit()

        await message.answer(f"Video muvaffaqiyatli saqlandi.\nKod: <b>{code}</b>")
    except Exception as error:
        logging.error("Video saqlashda xatolik: %s", error)
        await message.answer("Videoni saqlashda xatolik yuz berdi.")


@dp.message(F.text)
async def get_video_handler(message: types.Message):
    try:
        if not await check_subscription(message.from_user.id):
            await message.answer(
                "Kino ko'rish uchun avval kanallarga obuna bo'ling:",
                reply_markup=get_sub_keyboard(),
            )
            return

        code = message.text.strip()
        cursor.execute("SELECT file_id FROM movies WHERE code = ?", (code,))
        result = cursor.fetchone()

        if result:
            await bot.send_video(
                chat_id=message.chat.id,
                video=result[0],
                caption=f"Kod: <b>{code}</b>\n@KinoVaultsBot",
            )
        else:
            await message.answer("Bu kod bilan video topilmadi.")
    except TelegramRetryAfter as error:
        await asyncio.sleep(error.retry_after)
    except TelegramForbiddenError:
        pass
    except Exception as error:
        logging.error("Video yuborishda xatolik: %s", error)
        await message.answer("Xatolik yuz berdi. Keyinroq urinib ko'ring.")


@dp.message(Command("status"))
async def status_handler(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return

    await message.answer("Obuna tekshirish boshlandi. Log faylini tekshiring.")

    is_sub = await check_subscription(message.from_user.id)
    if is_sub:
        await message.answer("Siz barcha kanallarga obunasiz.")
    else:
        await message.answer("Ba'zi kanallarga obuna emassiz. Log faylini tekshiring.")


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(LOG_PATH, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )

    logging.info("Bot ishga tushdi")
    logging.info("DB fayli: %s", DB_PATH)
    if IS_RENDER and not os.getenv("RENDER_DISK_ROOT") and not os.getenv("DB_PATH"):
        logging.warning("Render persistent disk topilmadi. SQLite baza /tmp da saqlanadi va restartdan keyin o'chadi.")

    try:
        await dp.start_polling(bot, skip_updates=True)
    except Exception as error:
        logging.critical("Bot to'xtab qoldi. Xatolik: %s", error, exc_info=True)
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Bot to'xtatildi (KeyboardInterrupt)")
    except Exception as error:
        logging.critical("Kutilmagan global xatolik: %s", error, exc_info=True)
