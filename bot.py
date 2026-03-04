import os
import sqlite3
from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.dispatcher.fsm.storage.memory import MemoryStorage
from aiogram.dispatcher.fsm.context import FSMContext
from aiogram.dispatcher.fsm.state import StatesGroup, State
import asyncio
import requests

# --------- Настройки ---------
TOKEN = os.environ.get("TOKEN")
if not TOKEN:
    raise Exception("Environment variable TOKEN is not set!")

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
app = FastAPI()

DB_FILE = "loveboard.db"

# --------- FSM ---------
class Registration(StatesGroup):
    waiting_for_name = State()

class AddingSticker(StatesGroup):
    waiting_for_text = State()

# --------- SQLite ---------
def get_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS couples (
            login TEXT PRIMARY KEY,
            password TEXT NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS members (
            login TEXT PRIMARY KEY,
            couple_login TEXT NOT NULL,
            name TEXT NOT NULL,
            role TEXT NOT NULL,
            chat_id INTEGER NOT NULL,
            FOREIGN KEY(couple_login) REFERENCES couples(login)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS stickers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            couple_login TEXT NOT NULL,
            owner TEXT NOT NULL,
            text TEXT NOT NULL,
            FOREIGN KEY(couple_login) REFERENCES couples(login),
            FOREIGN KEY(owner) REFERENCES members(login)
        )
    """)
    conn.commit()
    conn.close()

init_db()

# --------- Работа с базой ---------
def add_couple(login, password):
    conn = get_connection()
    c = conn.cursor()
    c.execute("INSERT INTO couples (login, password) VALUES (?, ?)", (login, password))
    conn.commit()
    conn.close()

def get_couple(login):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM couples WHERE login = ?", (login,))
    couple = c.fetchone()
    conn.close()
    return couple

def add_member(login, couple_login, name, role, chat_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "INSERT INTO members (login, couple_login, name, role, chat_id) VALUES (?, ?, ?, ?, ?)",
        (login, couple_login, name, role, chat_id)
    )
    conn.commit()
    conn.close()

def get_member(login):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM members WHERE login = ?", (login,))
    member = c.fetchone()
    conn.close()
    return member

def add_sticker(couple_login, owner, text):
    conn = get_connection()
    c = conn.cursor()
    c.execute("INSERT INTO stickers (couple_login, owner, text) VALUES (?, ?, ?)",
              (couple_login, owner, text))
    conn.commit()
    conn.close()

def get_stickers(couple_login):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM stickers WHERE couple_login = ?", (couple_login,))
    stickers = c.fetchall()
    conn.close()
    return stickers

# --------- Клавиатура ---------
def get_filter_kb():
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("Все", callback_data="filter_all"))
    kb.add(InlineKeyboardButton("Мои", callback_data="filter_mine"))
    kb.add(InlineKeyboardButton("Партнёра", callback_data="filter_partner"))
    return kb

def stickers_to_grid(stickers, columns=3):
    grid = ""
    for i, s in enumerate(stickers):
        grid += s["text"] + "  "
        if (i+1) % columns == 0:
            grid += "\n"
    return grid.strip() if grid else "(пусто)"

async def update_board(couple_login):
    stickers = get_stickers(couple_login)
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM members WHERE couple_login = ?", (couple_login,))
    members = c.fetchall()
    conn.close()
    for member in members:
        chat_id = member["chat_id"]
        msg_text = stickers_to_grid(stickers)
        try:
            await bot.send_message(chat_id, f"Доска:\n{msg_text}", reply_markup=get_filter_kb())
        except:
            pass

# --------- FastAPI Webhook ---------
@app.post(f"/{TOKEN}")
async def telegram_webhook(req: Request):
    data = await req.json()
    update = types.Update(**data)
    await dp.update.dispatch(update)
    return {"ok": True}

# --------- Команды ---------
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "Привет! LoveBoardBot ❤️\n"
        "Создать пару: /register <логин_пары> <пароль>\n"
        "Войти: /login <логин_пары> <M/F> <пароль>"
    )

@dp.message(Command("register"))
async def cmd_register(message: types.Message):
    args = message.text.split()[1:]
    if len(args) != 2:
        await message.answer("Используй: /register <логин_пары> <пароль>")
        return
    couple_login, password = args
    if get_couple(couple_login):
        await message.answer("Пара уже существует!")
        return
    add_couple(couple_login, password)
    await message.answer(f"Пара '{couple_login}' создана!")

@dp.message(Command("login"))
async def cmd_login(message: types.Message, state: FSMContext):
    args = message.text.split()[1:]
    if len(args) != 3:
        await message.answer("Используй: /login <логин_пары> <M/F> <пароль>")
        return
    couple_login, role, password = args
    role = role.upper()
    couple = get_couple(couple_login)
    if not couple:
        await message.answer("Такой пары нет!")
        return
    if couple["password"] != password:
        await message.answer("Неверный пароль!")
        return
    user_login = f"{role}_{couple_login}"
    member = get_member(user_login)
    async with state.proxy() as data:
        data['user_login'] = user_login
        data['couple_login'] = couple_login
    if not member:
        await message.answer("Введите своё имя:")
        await Registration.waiting_for_name.set()
    else:
        await message.answer(f"Вы вошли как {member['name']} ({role})")

@dp.message(state=Registration.waiting_for_name)
async def process_name(message: types.Message, state: FSMContext):
    name = message.text.strip()
    async with state.proxy() as data:
        user_login = data['user_login']
        couple_login = data['couple_login']
    role = user_login[0]
    add_member(user_login, couple_login, name, role, message.from_user.id)
    await message.answer(f"Приятно познакомиться, {name}! /add чтобы добавить стикер")
    await state.clear()

@dp.message(Command("add"))
async def cmd_add(message: types.Message, state: FSMContext):
    async with state.proxy() as data:
        if 'user_login' not in data:
            await message.answer("Сначала войдите через /login")
            return
    await message.answer("Введите текст стикера:")
    await AddingSticker.waiting_for_text.set()

@dp.message(state=AddingSticker.waiting_for_text)
async def process_sticker(message: types.Message, state: FSMContext):
    text = message.text.strip()
    async with state.proxy() as data:
        user_login = data['user_login']
        couple_login = data['couple_login']
    member = get_member(user_login)
    color_emoji = "🔵" if member["role"]=="M" else "🌸"
    sticker_text = f"{color_emoji} {member['name']}: {text}"
    add_sticker(couple_login, user_login, sticker_text)
    await update_board(couple_login)
    await message.answer("Стикер добавлен и доска обновлена!")
    await state.clear()

# --------- Inline фильтры ---------
@dp.callback_query()
async def filter_board(callback_query: types.CallbackQuery):
    filter_type = callback_query.data.replace('filter_', '')
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM members WHERE chat_id = ?", (callback_query.from_user.id,))
    member = c.fetchone()
    if not member:
        await callback_query.answer("Сначала войдите через /login")
        return
    couple_login = member["couple_login"]
    user_login = member["login"]
    stickers = get_stickers(couple_login)
    if filter_type=="mine":
        stickers = [s for s in stickers if s["owner"]==user_login]
    elif filter_type=="partner":
        stickers = [s for s in stickers if s["owner"]!=user_login]
    msg_text = stickers_to_grid(stickers)
    await bot.send_message(callback_query.from_user.id, f"Доска:\n{msg_text}", reply_markup=get_filter_kb())
    await callback_query.answer()

# --------- Webhook setup ---------
async def on_startup():
    RENDER_URL = f"https://loveboardbot.onrender.com/{TOKEN}"
    r = requests.get(f"https://api.telegram.org/bot{TOKEN}/setWebhook?url={RENDER_URL}")
    print("Webhook setup response:", r.json())

if __name__ == "__main__":
    import uvicorn
    asyncio.run(on_startup())
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
