import json
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from aiogram.dispatcher import FSMContext
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

TOKEN = "7906463689:AAGxKdDyTSozlc6JjLVcGkjFWpTN9byEdY4"

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

DB_FILE = "db.json"

class Registration(StatesGroup):
    waiting_for_name = State()

class AddingSticker(StatesGroup):
    waiting_for_text = State()

def load_db():
    try:
        with open(DB_FILE, "r") as f:
            return json.load(f)
    except:
        return {"couples": {}}

def save_db(db):
    with open(DB_FILE, "w") as f:
        json.dump(db, f, indent=2)

# -----------------------
# Создаём клавиатуру фильтров
# -----------------------
def get_filter_kb():
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("Все", callback_data="filter_all"))
    kb.add(InlineKeyboardButton("Мои", callback_data="filter_mine"))
    kb.add(InlineKeyboardButton("Партнёра", callback_data="filter_partner"))
    return kb

# -----------------------
# Преобразуем список стикеров в сетку
# -----------------------
def stickers_to_grid(stickers, columns=3):
    grid = ""
    for i, s in enumerate(stickers):
        grid += s["text"] + "  "
        if (i + 1) % columns == 0:
            grid += "\n"
    return grid.strip() if grid else "(пусто)"

# -----------------------
# Обновление доски для всех участников
# -----------------------
async def update_board(couple_login):
    db = load_db()
    couple = db["couples"][couple_login]
    for u_login, info in couple["members"].items():
        chat_id = info["chat_id"]
        msg_id = couple["board_message_ids"].get(u_login)
        stickers_display = stickers_to_grid(couple["stickers"], columns=3)
        kb = get_filter_kb()
        if msg_id:
            await bot.edit_message_text(chat_id=chat_id, message_id=msg_id,
                                        text=f"Доска:\n{stickers_display}", reply_markup=kb)
        else:
            msg = await bot.send_message(chat_id, f"Доска:\n{stickers_display}", reply_markup=kb)
            couple["board_message_ids"][u_login] = msg.message_id
            save_db(db)

# -----------------------
# Основной код регистрации, логина и добавления стикеров
# -----------------------
@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    await message.answer(
        "Привет! LoveBoardBot ❤️\n"
        "Создать пару: /register <логин_пары> <пароль>\n"
        "Войти: /login <логин_пары> <M/F> <пароль>"
    )

@dp.message_handler(commands=['register'])
async def register(message: types.Message):
    args = message.get_args().split()
    if len(args) != 2:
        await message.answer("Используй: /register <логин_пары> <пароль>")
        return
    couple_login, password = args
    db = load_db()
    if couple_login in db["couples"]:
        await message.answer("Пара уже существует!")
        return
    db["couples"][couple_login] = {"password": password, "members": {}, "stickers": [], "board_message_ids": {}}
    save_db(db)
    await message.answer(f"Пара '{couple_login}' создана!")

@dp.message_handler(commands=['login'])
async def login(message: types.Message, state: FSMContext):
    args = message.get_args().split()
    if len(args) != 3:
        await message.answer("Используй: /login <логин_пары> <M/F> <пароль>")
        return
    couple_login, role, password = args
    role = role.upper()
    db = load_db()
    if couple_login not in db["couples"]:
        await message.answer("Такой пары нет!")
        return
    couple = db["couples"][couple_login]
    if couple["password"] != password:
        await message.answer("Неверный пароль!")
        return
    user_login = f"{role}_{couple_login}"
    async with state.proxy() as data:
        data['user_login'] = user_login
        data['couple_login'] = couple_login
    if user_login not in couple["members"]:
        await message.answer("Введите своё имя:")
        await Registration.waiting_for_name.set()
    else:
        couple["members"][user_login]["chat_id"] = message.from_user.id
        save_db(db)
        await message.answer(f"Вы вошли как {couple['members'][user_login]['name']} ({role})")
        if user_login not in couple["board_message_ids"]:
            msg = await message.answer("Доска:\n(пусто)", reply_markup=get_filter_kb())
            couple["board_message_ids"][user_login] = msg.message_id
            save_db(db)

@dp.message_handler(state=Registration.waiting_for_name)
async def process_name(message: types.Message, state: FSMContext):
    name = message.text.strip()
    async with state.proxy() as data:
        user_login = data['user_login']
        couple_login = data['couple_login']
    db = load_db()
    db["couples"][couple_login]["members"][user_login] = {"name": name, "role": user_login[0], "chat_id": message.from_user.id}
    save_db(db)
    await message.answer(f"Приятно познакомиться, {name}! /add чтобы добавить стикер")
    msg = await message.answer("Доска:\n(пусто)", reply_markup=get_filter_kb())
    db["couples"][couple_login]["board_message_ids"][user_login] = msg.message_id
    save_db(db)
    await state.finish()

@dp.message_handler(commands=['add'])
async def add_sticker(message: types.Message, state: FSMContext):
    async with state.proxy() as data:
        if 'user_login' not in data:
            await message.answer("Сначала войдите через /login")
            return
    await message.answer("Введите текст стикера:")
    await AddingSticker.waiting_for_text.set()

@dp.message_handler(state=AddingSticker.waiting_for_text)
async def process_sticker(message: types.Message, state: FSMContext):
    text = message.text.strip()
    async with state.proxy() as data:
        user_login = data['user_login']
        couple_login = data['couple_login']
    db = load_db()
    member = db["couples"][couple_login]["members"][user_login]
    color_emoji = "🔵" if member["role"]=="M" else "🌸"
    sticker_text = f"{color_emoji} {member['name']}: {text}"
    db["couples"][couple_login]["stickers"].append({"owner": user_login, "text": sticker_text})
    save_db(db)
    await update_board(couple_login)
    await message.answer("Стикер добавлен и доска обновлена!")
    await state.finish()

@dp.callback_query_handler(lambda c: c.data.startswith('filter_'))
async def filter_board(callback_query: types.CallbackQuery):
    filter_type = callback_query.data.replace('filter_', '')
    db = load_db()
    user_id = callback_query.from_user.id
    couple_login = None
    user_login = None
    for c_login, couple in db["couples"].items():
        for u_login, info in couple["members"].items():
            if info.get("chat_id") == user_id:
                couple_login = c_login
                user_login = u_login
                break
    if not couple_login:
        await callback_query.answer("Сначала войдите через /login")
        return
    couple = db["couples"][couple_login]
    stickers = couple["stickers"]
    if filter_type=="all":
        filtered = stickers
    elif filter_type=="mine":
        filtered = [s for s in stickers if s["owner"]==user_login]
    else:
        filtered = [s for s in stickers if s["owner"]!=user_login]
    msg_id = couple["board_message_ids"].get(user_login)
    stickers_display = stickers_to_grid(filtered, columns=3)
    if msg_id:
        await bot.edit_message_text(chat_id=user_id, message_id=msg_id,
                                    text=f"Доска:\n{stickers_display}", reply_markup=get_filter_kb())
    await callback_query.answer()

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
