import os
import sqlite3
import asyncio
from fastapi import FastAPI, Request
from aiogram import Bot, types, Dispatcher, F, Router
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# ----------------- Настройки -----------------
TOKEN = os.environ.get("TOKEN")
if not TOKEN:
    raise Exception("TOKEN не задан!")

DB_FILE = "loveboard.db"

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
app = FastAPI()

# ----------------- FSM -----------------
class Registration(StatesGroup):
    waiting_for_name = State()

class AddingSticker(StatesGroup):
    waiting_for_text = State()

# ----------------- SQLite -----------------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS couples (
            login TEXT PRIMARY KEY,
            password TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS members (
            user_login TEXT PRIMARY KEY,
            couple_login TEXT,
            name TEXT,
            role TEXT,
            chat_id INTEGER
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS stickers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            couple_login TEXT,
            owner TEXT,
            text TEXT
        )
    """)
    conn.commit()
    conn.close()

def add_couple(login, password):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO couples(login,password) VALUES (?,?)", (login,password))
    conn.commit()
    conn.close()

def get_couple(login):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT login,password FROM couples WHERE login=?", (login,))
    res = c.fetchone()
    conn.close()
    return res

def add_member(user_login, couple_login, name, role, chat_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO members(user_login,couple_login,name,role,chat_id) VALUES (?,?,?,?,?)",
              (user_login, couple_login, name, role, chat_id))
    conn.commit()
    conn.close()

def get_member(user_login):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT user_login,couple_login,name,role,chat_id FROM members WHERE user_login=?", (user_login,))
    res = c.fetchone()
    conn.close()
    return res

def add_sticker(couple_login, owner, text):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO stickers(couple_login,owner,text) VALUES (?,?,?)", (couple_login, owner, text))
    conn.commit()
    conn.close()

def get_stickers(couple_login):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT owner,text FROM stickers WHERE couple_login=?", (couple_login,))
    res = c.fetchall()
    conn.close()
    return [{"owner": o, "text": t} for o,t in res]

# ----------------- UI -----------------
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

async def update_board(couple_login, user_id):
    stickers = get_stickers(couple_login)
    stickers_display = stickers_to_grid(stickers, columns=3)
    await bot.send_message(user_id, f"Доска:\n{stickers_display}", reply_markup=get_filter_kb())

# ----------------- Команды -----------------
@router.message(F.text == "/start")
async def cmd_start(message: types.Message):
    await message.answer(
        "Привет! LoveBoardBot ❤️\n"
        "Создать пару: /register <логин_пары> <пароль>\n"
        "Войти: /login <логин_пары> <M/F> <пароль>"
    )

@router.message(F.text.startswith("/register"))
async def cmd_register(message: types.Message, state: FSMContext):
    parts = message.text.split()
    if len(parts)!=3:
        await message.answer("Используй: /register <логин_пары> <пароль>")
        return
    _, couple_login, password = parts
    if get_couple(couple_login):
        await message.answer("Пара уже существует!")
        return
    add_couple(couple_login, password)
    await message.answer(f"Пара '{couple_login}' создана!")

@router.message(F.text.startswith("/login"))
async def cmd_login(message: types.Message, state: FSMContext):
    parts = message.text.split()
    if len(parts)!=4:
        await message.answer("Используй: /login <логин_пары> <M/F> <пароль>")
        return
    _, couple_login, role, password = parts
    role = role.upper()
    couple = get_couple(couple_login)
    if not couple:
        await message.answer("Такой пары нет!")
        return
    if couple[1]!=password:
        await message.answer("Неверный пароль!")
        return
    user_login = f"{role}_{couple_login}"
    member = get_member(user_login)
    await state.update_data(user_login=user_login, couple_login=couple_login)
    if member:
        await message.answer(f"Вы вошли как {member[2]} ({role})")
        await update_board(couple_login, message.from_user.id)
    else:
        await message.answer("Введите своё имя:")
        await state.set_state(Registration.waiting_for_name)

# ----------------- Ввод имени -----------------
@router.message(F.text, F.chat.type == "private")
async def process_name(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state == Registration.waiting_for_name.state:
        data = await state.get_data()
        user_login = data["user_login"]
        couple_login = data["couple_login"]
        add_member(user_login, couple_login, message.text.strip(), user_login[0], message.from_user.id)
        await message.answer(f"Приятно познакомиться, {message.text.strip()}! /add чтобы добавить стикер")
        await update_board(couple_login, message.from_user.id)
        await state.clear()

# ----------------- Добавление стикера -----------------
@router.message(F.text == "/add")
async def cmd_add(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if "user_login" not in data:
        await message.answer("Сначала войдите через /login")
        return
    await message.answer("Введите текст стикера:")
    await state.set_state(AddingSticker.waiting_for_text)

@router.message(F.text, F.chat.type == "private")
async def process_sticker(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state == AddingSticker.waiting_for_text.state:
        data = await state.get_data()
        user_login = data["user_login"]
        couple_login = data["couple_login"]
        member = get_member(user_login)
        color_emoji = "🔵" if member[3]=="M" else "🌸"
        sticker_text = f"{color_emoji} {member[2]}: {message.text.strip()}"
        add_sticker(couple_login, user_login, sticker_text)
        await message.answer("Стикер добавлен и доска обновлена!")
        await update_board(couple_login, message.from_user.id)
        await state.clear()

# ----------------- Inline-фильтры -----------------
@router.callback_query()
async def filter_board(callback_query: types.CallbackQuery):
    filter_type = callback_query.data.replace("filter_","")
    user_id = callback_query.from_user.id
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT couple_login,user_login FROM members WHERE chat_id=?", (user_id,))
    res = c.fetchone()
    conn.close()
    if not res:
        await callback_query.answer("Сначала войдите через /login")
        return
    couple_login,user_login = res
    stickers = get_stickers(couple_login)
    if filter_type=="mine":
        stickers = [s for s in stickers if s["owner"]==user_login]
    elif filter_type=="partner":
        stickers = [s for s in stickers if s["owner"]!=user_login]
    stickers_display = stickers_to_grid(stickers, columns=3)
    await bot.edit_message_text(user_id, callback_query.message.message_id,
                                f"Доска:\n{stickers_display}", reply_markup=get_filter_kb())
    await callback_query.answer()

# ----------------- FastAPI webhook -----------------
@app.post(f"/{TOKEN}")
async def telegram_webhook(req: Request):
    data = await req.json()
    update = types.Update(**data)
    await dp.update.dispatch(update)
    return {"ok": True}

# ----------------- Setup -----------------
dp.include_router(router)
init_db()

async def on_startup():
    RENDER_URL = f"https://loveboardbot.onrender.com/{TOKEN}"
    import requests
    r = requests.get(f"https://api.telegram.org/bot{TOKEN}/setWebhook?url={RENDER_URL}")
    print("Webhook setup response:", r.json())

if __name__=="__main__":
    import uvicorn
    asyncio.run(on_startup())
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
