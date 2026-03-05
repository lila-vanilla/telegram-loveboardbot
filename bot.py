import os
import sqlite3
from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

# --------- Настройки ---------
TOKEN = os.environ.get("TOKEN")
if not TOKEN:
    raise Exception("Environment variable TOKEN is not set!")

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
app = FastAPI()

DB_FILE = "loveboard.db"

# --------- Startup (ВАЖНО ДЛЯ RENDER) ---------
@app.on_event("startup")
async def on_startup():
    init_db()

# --------- FSM ---------
class Registration(StatesGroup):
    waiting_for_name = State()

class AddingSticker(StatesGroup):
    waiting_for_text = State()

# --------- SQLite ---------
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

def get_connection():
    return sqlite3.connect(DB_FILE)

def add_couple(login, password):
    conn = get_connection()
    c = conn.cursor()
    c.execute("INSERT INTO couples(login, password) VALUES(?, ?)", (login, password))
    conn.commit()
    conn.close()

def get_couple(login):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT login, password FROM couples WHERE login=?", (login,))
    res = c.fetchone()
    conn.close()
    return res

def add_member(user_login, couple_login, name, role, chat_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        INSERT OR REPLACE INTO members(user_login, couple_login, name, role, chat_id)
        VALUES (?, ?, ?, ?, ?)
    """, (user_login, couple_login, name, role, chat_id))
    conn.commit()
    conn.close()

def get_member(user_login):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM members WHERE user_login=?", (user_login,))
    res = c.fetchone()
    conn.close()
    return res

def add_sticker(couple_login, owner, text):
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "INSERT INTO stickers(couple_login, owner, text) VALUES (?, ?, ?)",
        (couple_login, owner, text)
    )
    conn.commit()
    conn.close()

def get_stickers(couple_login):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT owner, text FROM stickers WHERE couple_login=?", (couple_login,))
    res = c.fetchall()
    conn.close()
    return res

# --------- Клавиатура ---------
def get_filter_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="Все", callback_data="filter_all")
    kb.button(text="Мои", callback_data="filter_mine")
    kb.button(text="Партнёра", callback_data="filter_partner")
    kb.adjust(3)
    return kb.as_markup()

def stickers_to_text(stickers):
    if not stickers:
        return "(пусто)"
    return "\n".join([s[1] for s in stickers])

async def update_board(couple_login, chat_id=None):
    stickers = get_stickers(couple_login)
    text_board = "Доска:\n" + stickers_to_text(stickers)
    kb = get_filter_kb()

    if chat_id:
        await bot.send_message(chat_id, text_board, reply_markup=kb)
    else:
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT chat_id FROM members WHERE couple_login=?", (couple_login,))
        members = c.fetchall()
        conn.close()

        for m in members:
            await bot.send_message(m[0], text_board, reply_markup=kb)

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

    if couple[1] != password:
        await message.answer("Неверный пароль!")
        return

    user_login = f"{role}_{couple_login}"
    m = get_member(user_login)

    if not m:
        await message.answer("Введите своё имя:")
        await state.set_state(Registration.waiting_for_name)
        await state.update_data(
            user_login=user_login,
            couple_login=couple_login,
            role=role
        )
    else:
        add_member(user_login, couple_login, m[2], role, message.from_user.id)
        await message.answer(f"Вы вошли как {m[2]} ({role})")
        await update_board(couple_login, message.from_user.id)


@dp.message(Command("add"))
async def cmd_add(message: types.Message, state: FSMContext):
    user_id = message.from_user.id

    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT couple_login, user_login FROM members WHERE chat_id=?", (user_id,))
    res = c.fetchone()
    conn.close()

    if not res:
        await message.answer("Сначала войдите через /login")
        return

    couple_login, user_login = res

    await state.set_state(AddingSticker.waiting_for_text)
    await state.update_data(
        couple_login=couple_login,
        user_login=user_login
    )

    await message.answer("Введите текст стикера:")
    

# --------- Обработка текста ---------
@dp.message()
@dp.message()
async def process_text(message: types.Message, state: FSMContext):
    data = await state.get_data()
    current_state = await state.get_state()

    # -------- Регистрация имени --------
    if current_state == Registration.waiting_for_name.state:
        name = message.text.strip()

        add_member(
            data['user_login'],
            data['couple_login'],
            name,
            data['role'],
            message.from_user.id
        )

        await message.answer(
            f"Приятно познакомиться, {name}! ❤️\n"
            "Теперь можно добавить стикер через /add"
        )

        await update_board(data['couple_login'], message.from_user.id)
        await state.clear()
        return

    # -------- Добавление стикера --------
    if current_state == AddingSticker.waiting_for_text.state:
        member = get_member(data['user_login'])

        if not member:
            await message.answer("Ошибка. Попробуйте войти заново через /login")
            await state.clear()
            return

        name = member[2]
        role = member[3]

        color = "🔵" if role == "M" else "🌸"
        sticker_text = f"{color} {name}: {message.text.strip()}"

        add_sticker(
            data['couple_login'],
            data['user_login'],
            sticker_text
        )

        await message.answer("Стикер добавлен! 💌")
        await update_board(data['couple_login'], message.from_user.id)

        await state.clear()
        return

# --------- Callback ---------
@dp.callback_query()
async def filter_board(callback: types.CallbackQuery):
    action = callback.data.replace("filter_", "")
    user_id = callback.from_user.id

    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT couple_login, user_login FROM members WHERE chat_id=?", (user_id,))
    res = c.fetchone()
    conn.close()

    if not res:
        await callback.answer("Сначала войдите через /login")
        return

    couple_login, user_login = res
    stickers = get_stickers(couple_login)

    if action == "mine":
        stickers = [s for s in stickers if s[0] == user_login]
    elif action == "partner":
        stickers = [s for s in stickers if s[0] != user_login]

    text_board = "Доска:\n" + stickers_to_text(stickers)

    await bot.edit_message_text(
        chat_id=user_id,
        message_id=callback.message.message_id,
        text=text_board,
        reply_markup=get_filter_kb()
    )

    await callback.answer()

# --------- Webhook ---------
@app.post(f"/{TOKEN}")
async def telegram_webhook(request: Request):
    data = await request.json()
    update = types.Update.model_validate(data)
    await dp.feed_update(bot, update)
    return {"ok": True}
