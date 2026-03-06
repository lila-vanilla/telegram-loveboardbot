import os
import psycopg2
import bcrypt
from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.storage.memory import MemoryStorage

TOKEN = os.environ.get("TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL")

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())
app = FastAPI()


# ---------------- DB ----------------

def get_conn():
    return psycopg2.connect(DATABASE_URL)


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS couples(
        id SERIAL PRIMARY KEY,
        login TEXT UNIQUE,
        password_hash TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS members(
        id SERIAL PRIMARY KEY,
        user_login TEXT,
        couple_login TEXT,
        name TEXT,
        role TEXT,
        chat_id BIGINT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS stickers(
        id SERIAL PRIMARY KEY,
        couple_login TEXT,
        owner TEXT,
        text TEXT
    )
    """)

    conn.commit()
    conn.close()


# ---------------- PASSWORD ----------------

def hash_password(password: str):
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def check_password(password: str, hashed: str):
    return bcrypt.checkpw(password.encode(), hashed.encode())


# ---------------- COUPLES ----------------

def add_couple(login, password):

    conn = get_conn()
    cur = conn.cursor()

    password_hash = hash_password(password)

    cur.execute(
        "INSERT INTO couples(login,password_hash) VALUES(%s,%s)",
        (login, password_hash)
    )

    conn.commit()
    conn.close()


def get_couple(login):

    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        "SELECT login,password_hash FROM couples WHERE login=%s",
        (login,)
    )

    res = cur.fetchone()

    conn.close()

    return res


# ---------------- MEMBERS ----------------

def add_member(user_login, couple_login, name, role, chat_id):

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    INSERT INTO members(user_login,couple_login,name,role,chat_id)
    VALUES(%s,%s,%s,%s,%s)
    """, (user_login, couple_login, name, role, chat_id))

    conn.commit()
    conn.close()


def get_member(user_login):

    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        "SELECT * FROM members WHERE user_login=%s",
        (user_login,)
    )

    res = cur.fetchone()

    conn.close()

    return res


# ---------------- STICKERS ----------------

def add_sticker(couple_login, owner, text):

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    INSERT INTO stickers(couple_login,owner,text)
    VALUES(%s,%s,%s)
    """, (couple_login, owner, text))

    conn.commit()
    conn.close()


def get_stickers(couple_login):

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    SELECT owner,text FROM stickers
    WHERE couple_login=%s
    """, (couple_login,))

    res = cur.fetchall()

    conn.close()

    return res


# ---------------- UI ----------------

def keyboard():

    kb = InlineKeyboardBuilder()

    kb.button(text="Все", callback_data="all")
    kb.button(text="Мои", callback_data="mine")

    kb.adjust(2)

    return kb.as_markup()


async def update_board(couple_login, chat_id):

    stickers = get_stickers(couple_login)

    if not stickers:
        text = "Доска пуста"
    else:
        text = "\n".join([s[1] for s in stickers])

    await bot.send_message(
        chat_id,
        "❤️ LoveBoard\n\n" + text,
        reply_markup=keyboard()
    )


# ---------------- COMMANDS ----------------

@dp.message(Command("start"))
async def start(message: types.Message):

    await message.answer(
        "LoveBoardBot\n\n"
        "/register login password\n"
        "/login login M/F password\n"
        "/add текст"
    )


@dp.message(Command("register"))
async def register(message: types.Message):

    args = message.text.split()[1:]

    if len(args) != 2:
        await message.answer("Используй: /register login password")
        return

    login, password = args

    if get_couple(login):
        await message.answer("Пара уже существует")
        return

    add_couple(login, password)

    await message.answer("Пара создана ❤️")


@dp.message(Command("login"))
async def login(message: types.Message):

    args = message.text.split()[1:]

    if len(args) != 3:
        await message.answer("Используй: /login login M/F password")
        return

    login, role, password = args

    couple = get_couple(login)

    if not couple:
        await message.answer("Пары нет")
        return

    if not check_password(password, couple[1]):
        await message.answer("Пароль неверный")
        return

    user_login = f"{role}_{login}"

    add_member(
        user_login,
        login,
        role,
        role,
        message.from_user.id
    )

    await message.answer("Вы вошли ❤️")

    await update_board(login, message.from_user.id)


@dp.message(Command("add"))
async def add(message: types.Message):

    text = message.text.replace("/add", "").strip()

    if not text:
        await message.answer("Напиши: /add текст")
        return

    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        "SELECT couple_login,user_login FROM members WHERE chat_id=%s",
        (message.from_user.id,)
    )

    res = cur.fetchone()

    conn.close()

    if not res:
        await message.answer("Сначала /login")
        return

    couple_login, user_login = res

    sticker = f"📝 {text}"

    add_sticker(couple_login, user_login, sticker)

    await update_board(couple_login, message.from_user.id)


# ---------------- WEBHOOK ----------------

@app.post(f"/{TOKEN}")
async def webhook(req: Request):

    data = await req.json()

    update = types.Update.model_validate(data)

    await dp.feed_update(bot, update)

    return {"ok": True}


# ---------------- START ----------------

init_db()
