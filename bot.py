import os
import psycopg
from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.storage.memory import MemoryStorage
from passlib.context import CryptContext

# -----------------------
# ENV
# -----------------------

TOKEN = os.getenv("TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

if not TOKEN:
    raise Exception("TOKEN not set")

if not DATABASE_URL:
    raise Exception("DATABASE_URL not set")

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())
app = FastAPI()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# -----------------------
# DATABASE
# -----------------------

def get_conn():
    return psycopg.connect(DATABASE_URL)

def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:

            cur.execute("""
            CREATE TABLE IF NOT EXISTS couples (
                login TEXT PRIMARY KEY,
                password TEXT
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS members (
                user_login TEXT PRIMARY KEY,
                couple_login TEXT,
                name TEXT,
                role TEXT,
                chat_id BIGINT
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS stickers (
                id SERIAL PRIMARY KEY,
                couple_login TEXT,
                owner TEXT,
                text TEXT
            )
            """)

# -----------------------
# COUPLES
# -----------------------

def add_couple(login, password):

    hashed = pwd_context.hash(password)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO couples (login, password) VALUES (%s,%s)",
                (login, hashed)
            )

def get_couple(login):

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT login,password FROM couples WHERE login=%s",
                (login,)
            )
            return cur.fetchone()

def check_password(password, hashed):
    return pwd_context.verify(password, hashed)

# -----------------------
# MEMBERS
# -----------------------

def add_member(user_login, couple_login, name, role, chat_id):

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            INSERT INTO members
            (user_login,couple_login,name,role,chat_id)
            VALUES (%s,%s,%s,%s,%s)
            ON CONFLICT (user_login)
            DO UPDATE SET chat_id = EXCLUDED.chat_id
            """,
            (user_login,couple_login,name,role,chat_id)
            )

def get_member(user_login):

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM members WHERE user_login=%s",
                (user_login,)
            )
            return cur.fetchone()

# -----------------------
# STICKERS
# -----------------------

def add_sticker(couple_login, owner, text):

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO stickers (couple_login,owner,text) VALUES (%s,%s,%s)",
                (couple_login,owner,text)
            )

def get_stickers(couple_login):

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT owner,text FROM stickers WHERE couple_login=%s",
                (couple_login,)
            )
            return cur.fetchall()

# -----------------------
# UI
# -----------------------

def get_filter_kb():

    kb = InlineKeyboardBuilder()

    kb.button(text="Все", callback_data="filter_all")
    kb.button(text="Мои", callback_data="filter_mine")
    kb.button(text="Партнера", callback_data="filter_partner")

    kb.adjust(3)

    return kb.as_markup()

def board_text(stickers):

    if not stickers:
        return "Доска пустая"

    return "\n".join([s[1] for s in stickers])

async def update_board(couple_login, chat_id):

    stickers = get_stickers(couple_login)

    text = "❤️ LoveBoard\n\n" + board_text(stickers)

    await bot.send_message(
        chat_id,
        text,
        reply_markup=get_filter_kb()
    )

# -----------------------
# COMMANDS
# -----------------------

@dp.message(Command("start"))
async def start(message: types.Message):

    await message.answer(
        "LoveBoard ❤️\n\n"
        "/register login password\n"
        "/login login M/F password\n"
        "/add текст"
    )

# -----------------------

@dp.message(Command("register"))
async def register(message: types.Message):

    args = message.text.split()[1:]

    if len(args) != 2:
        await message.answer("/register login password")
        return

    login = args[0]
    password = args[1]

    if get_couple(login):
        await message.answer("Пара уже существует")
        return

    add_couple(login, password)

    await message.answer("Пара создана!")

# -----------------------

@dp.message(Command("login"))
async def login(message: types.Message):

    args = message.text.split()[1:]

    if len(args) != 3:
        await message.answer("/login login M/F password")
        return

    couple_login = args[0]
    role = args[1].upper()
    password = args[2]

    couple = get_couple(couple_login)

    if not couple:
        await message.answer("Пара не найдена")
        return

    if not check_password(password, couple[1]):
        await message.answer("Неверный пароль")
        return

    user_login = f"{role}_{couple_login}"

    add_member(
        user_login,
        couple_login,
        role,
        role,
        message.from_user.id
    )

    await message.answer("Вход выполнен")

    await update_board(couple_login, message.from_user.id)

# -----------------------

@dp.message(Command("add"))
async def add(message: types.Message):

    text = message.text.replace("/add","").strip()

    if not text:
        await message.answer("/add текст")
        return

    user_id = message.from_user.id

    with get_conn() as conn:
        with conn.cursor() as cur:

            cur.execute(
                "SELECT couple_login,user_login,name,role FROM members WHERE chat_id=%s",
                (user_id,)
            )

            res = cur.fetchone()

    if not res:
        await message.answer("Сначала /login")
        return

    couple_login,user_login,name,role = res

    color = "🔵" if role=="M" else "🌸"

    sticker = f"{color} {name}: {text}"

    add_sticker(couple_login,user_login,sticker)

    await update_board(couple_login,user_id)

# -----------------------
# CALLBACK
# -----------------------

@dp.callback_query()
async def filters(callback: types.CallbackQuery):

    action = callback.data

    user_id = callback.from_user.id

    with get_conn() as conn:
        with conn.cursor() as cur:

            cur.execute(
                "SELECT couple_login,user_login FROM members WHERE chat_id=%s",
                (user_id,)
            )

            res = cur.fetchone()

    if not res:
        await callback.answer()
        return

    couple_login,user_login = res

    stickers = get_stickers(couple_login)

    if action=="filter_mine":
        stickers = [s for s in stickers if s[0]==user_login]

    if action=="filter_partner":
        stickers = [s for s in stickers if s[0]!=user_login]

    text = "❤️ LoveBoard\n\n" + board_text(stickers)

    await callback.message.edit_text(
        text,
        reply_markup=get_filter_kb()
    )

    await callback.answer()

# -----------------------
# WEBHOOK
# -----------------------

@app.post(f"/{TOKEN}")
async def webhook(req: Request):

    data = await req.json()

    update = types.Update.model_validate(data)

    await dp.feed_update(bot, update)

    return {"ok": True}

# -----------------------
# START
# -----------------------

@app.on_event("startup")
async def startup():

    init_db()

    await bot.set_webhook(f"{WEBHOOK_URL}/{TOKEN}")
