import os
from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, types
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.filters import Command
import motor.motor_asyncio

# ===== ENV =====
TOKEN = os.environ.get("TOKEN")
MONGO_URI = os.environ.get("MONGO_URI")

if not TOKEN or not MONGO_URI:
    raise Exception("TOKEN или MONGO_URI не заданы!")

# ===== BOT INIT =====
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())
app = FastAPI()

# ===== MongoDB =====
client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
db = client.loveboard
couples = db.couples

# ===== FSM =====
class Registration(StatesGroup):
    waiting_for_name = State()

class AddingSticker(StatesGroup):
    waiting_for_text = State()

# ===== WEBHOOK =====
@app.post(f"/{TOKEN}")
async def telegram_webhook(req: Request):
    data = await req.json()
    update = types.Update.model_validate(data)
    await dp.feed_update(bot, update)
    return {"ok": True}

# ===== COMMANDS =====
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "LoveBoardBot ❤️\n\n"
        "Создать пару:\n/register <логин> <пароль>\n"
        "Войти:\n/login <логин> <M/F> <пароль>"
    )

# ===== REGISTER =====
@dp.message(Command("register"))
async def cmd_register(message: types.Message):
    parts = message.text.split()
    if len(parts) != 3:
        await message.answer("Используй: /register <логин> <пароль>")
        return

    _, login, password = parts

    existing = await couples.find_one({"login": login})
    if existing:
        await message.answer("Пара уже существует.")
        return

    await couples.insert_one({
        "login": login,
        "password": password,
        "members": {},
        "stickers": []
    })

    await message.answer("Пара создана!")

# ===== LOGIN =====
@dp.message(Command("login"))
async def cmd_login(message: types.Message, state: FSMContext):
    parts = message.text.split()
    if len(parts) != 4:
        await message.answer("Используй: /login <логин> <M/F> <пароль>")
        return

    _, login, role, password = parts
    role = role.upper()

    pair = await couples.find_one({"login": login, "password": password})
    if not pair:
        await message.answer("Неверный логин или пароль.")
        return

    user_login = f"{role}_{login}"
    await state.update_data(user_login=user_login, couple_login=login)

    if user_login not in pair["members"]:
        await message.answer("Введите своё имя:")
        await state.set_state(Registration.waiting_for_name)
    else:
        await couples.update_one(
            {"login": login},
            {"$set": {f"members.{user_login}.chat_id": message.from_user.id}}
        )
        name = pair["members"][user_login]["name"]
        await message.answer(f"Вы вошли как {name}")

# ===== SAVE NAME =====
@dp.message(Registration.waiting_for_name)
async def process_name(message: types.Message, state: FSMContext):
    name = message.text.strip()
    data = await state.get_data()
    user_login = data["user_login"]
    couple_login = data["couple_login"]
    role = user_login[0]

    await couples.update_one(
        {"login": couple_login},
        {"$set": {
            f"members.{user_login}": {
                "name": name,
                "role": role,
                "chat_id": message.from_user.id
            }
        }}
    )

    await message.answer(f"Добро пожаловать, {name}! Используй /add чтобы добавить стикер.")
    await state.clear()

# ===== ADD STICKER =====
@dp.message(Command("add"))
async def cmd_add(message: types.Message, state: FSMContext):
    await message.answer("Введите текст стикера:")
    await state.set_state(AddingSticker.waiting_for_text)

@dp.message(AddingSticker.waiting_for_text)
async def process_sticker(message: types.Message, state: FSMContext):
    text = message.text.strip()
    data = await state.get_data()

    if not data:
        await message.answer("Сначала войдите через /login")
        return

    user_login = data["user_login"]
    couple_login = data["couple_login"]

    pair = await couples.find_one({"login": couple_login})
    member = pair["members"].get(user_login)

    if not member:
        await message.answer("Ошибка пользователя.")
        return

    emoji = "🔵" if member["role"] == "M" else "🌸"
    full_text = f"{emoji} {member['name']}: {text}"

    await couples.update_one(
        {"login": couple_login},
        {"$push": {"stickers": full_text}}
    )

    updated = await couples.find_one({"login": couple_login})
    board = "\n".join(updated["stickers"]) if updated["stickers"] else "(пусто)"

    await message.answer("Доска:\n\n" + board)
    await state.clear()

# ===== RUN =====
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
