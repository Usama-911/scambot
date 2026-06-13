import asyncio
import logging
import sqlite3
import os
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import re

# ======== НАСТРОЙКИ — ЗАМЕНИ ТОКЕН ========
TOKEN = "8736546011:AAFEbdtyZDciLdnYK9WTWpjtGEhfJXxlVEs"
# ==========================================

logging.basicConfig(level=logging.INFO)

def init_db():
    conn = sqlite3.connect("scam.db")
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        query TEXT NOT NULL, query_type TEXT NOT NULL,
        comment TEXT NOT NULL, reporter_id INTEGER NOT NULL,
        reporter_name TEXT, created_at TEXT NOT NULL,
        status TEXT DEFAULT 'pending')""")
    c.execute("CREATE TABLE IF NOT EXISTS spam_guard (user_id INTEGER, last_report TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS moderators (user_id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()

def normalize(text):
    return text.strip().lower().replace(" ", "")

def detect_type(query):
    phone = re.sub(r"[\s\-\(\)\+]", "", query)
    if re.match(r"^\d{10,15}$", phone): return "phone"
    if re.match(r"^@?[a-zA-Z0-9_]{5,32}$", query): return "nickname"
    return "fio"

def get_reports(query):
    conn = sqlite3.connect("scam.db")
    c = conn.cursor()
    c.execute("SELECT comment, reporter_name, created_at FROM reports WHERE LOWER(REPLACE(query,' ',''))=? AND status='approved' ORDER BY created_at DESC LIMIT 10", (normalize(query),))
    rows = c.fetchall(); conn.close(); return rows

def count_reports(query):
    conn = sqlite3.connect("scam.db")
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM reports WHERE LOWER(REPLACE(query,' ',''))=? AND status='approved'", (normalize(query),))
    count = c.fetchone()[0]; conn.close(); return count

def add_report(query, query_type, comment, reporter_id, reporter_name):
    conn = sqlite3.connect("scam.db")
    c = conn.cursor()
    c.execute("INSERT INTO reports (query,query_type,comment,reporter_id,reporter_name,created_at,status) VALUES (?,?,?,?,?,?,'pending')",
              (query.strip(), query_type, comment, reporter_id, reporter_name, datetime.now().isoformat()))
    rid = c.lastrowid; conn.commit(); conn.close(); return rid

def is_spam(user_id):
    conn = sqlite3.connect("scam.db")
    c = conn.cursor()
    c.execute("SELECT last_report FROM spam_guard WHERE user_id=?", (user_id,))
    row = c.fetchone(); conn.close()
    if row and datetime.now() - datetime.fromisoformat(row[0]) < timedelta(minutes=5): return True
    return False

def update_spam_guard(user_id):
    conn = sqlite3.connect("scam.db")
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO spam_guard (user_id,last_report) VALUES (?,?)", (user_id, datetime.now().isoformat()))
    conn.commit(); conn.close()

def is_moderator(user_id):
    conn = sqlite3.connect("scam.db")
    c = conn.cursor()
    c.execute("SELECT 1 FROM moderators WHERE user_id=?", (user_id,))
    row = c.fetchone(); conn.close(); return bool(row)

def add_moderator(user_id):
    conn = sqlite3.connect("scam.db")
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO moderators (user_id) VALUES (?)", (user_id,))
    conn.commit(); conn.close()

def get_pending_reports():
    conn = sqlite3.connect("scam.db")
    c = conn.cursor()
    c.execute("SELECT id,query,query_type,comment,reporter_name,created_at FROM reports WHERE status='pending' ORDER BY created_at ASC LIMIT 5")
    rows = c.fetchall(); conn.close(); return rows

def update_report_status(report_id, status):
    conn = sqlite3.connect("scam.db")
    c = conn.cursor()
    c.execute("UPDATE reports SET status=? WHERE id=?", (status, report_id))
    conn.commit(); conn.close()

def get_risk_level(count):
    if count == 0: return "🟢 Не найден в базе"
    elif count == 1: return "🟡 Низкий риск (1 жалоба)"
    elif count <= 3: return "🟠 Средний риск"
    else: return "🔴 ВЫСОКИЙ РИСК"

class ReportState(StatesGroup):
    waiting_query = State()
    waiting_comment = State()

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("👋 <b>Антискам-бот</b>\n\nПроверяю номера телефонов, никнеймы и ФИО.\n\n🔍 /check — проверить\n⚠️ /report — добавить жалобу\nℹ️ /help — помощь", parse_mode="HTML")

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer("📖 <b>Примеры:</b>\n\n/check +79991234567\n/check @username\n/check Иванов Иван\n\n/report — добавить жалобу\n\nВсе жалобы проходят модерацию.", parse_mode="HTML")

@dp.message(Command("check"))
async def cmd_check(message: types.Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("❗ Пример: /check +79991234567"); return
    query = args[1].strip()
    reports = get_reports(query)
    count = count_reports(query)
    qtype = detect_type(query)
    type_emoji = {"phone":"📞","nickname":"👤","fio":"🪪"}.get(qtype,"🔍")
    type_name = {"phone":"Телефон","nickname":"Никнейм","fio":"ФИО"}.get(qtype,"")
    text = f"{type_emoji} <b>{type_name}:</b> <code>{query}</code>\n📊 <b>Статус:</b> {get_risk_level(count)}\n"
    if reports:
        text += f"\n💬 <b>Жалобы ({count}):</b>\n"
        for comment, reporter, date in reports:
            text += f"\n• {comment}\n  <i>{reporter or 'аноним'} · {date[:10]}</i>\n"
    else:
        text += "\n✅ Жалоб не найдено."
    await message.answer(text, parse_mode="HTML")

@dp.message(Command("report"))
async def cmd_report(message: types.Message, state: FSMContext):
    if is_spam(message.from_user.id):
        await message.answer("⏳ Подождите 5 минут между жалобами."); return
    await message.answer("📝 Введите номер телефона, никнейм или ФИО скамера:")
    await state.set_state(ReportState.waiting_query)

@dp.message(ReportState.waiting_query)
async def process_query(message: types.Message, state: FSMContext):
    query = message.text.strip()
    if len(query) < 3:
        await message.answer("❗ Слишком коротко."); return
    await state.update_data(query=query)
    await message.answer(f"✅ <code>{query}</code>\n\n✍️ Опишите что произошло:", parse_mode="HTML")
    await state.set_state(ReportState.waiting_comment)

@dp.message(ReportState.waiting_comment)
async def process_comment(message: types.Message, state: FSMContext):
    comment = message.text.strip()
    if len(comment) < 10:
        await message.answer("❗ Слишком коротко, опишите подробнее."); return
    data = await state.get_data()
    query = data["query"]
    reporter_name = message.from_user.full_name or "аноним"
    rid = add_report(query, detect_type(query), comment, message.from_user.id, reporter_name)
    update_spam_guard(message.from_user.id)
    await state.clear()
    await message.answer(f"✅ <b>Жалоба #{rid} отправлена на модерацию!</b>\nСпасибо! 🙏", parse_mode="HTML")
    conn = sqlite3.connect("scam.db")
    c = conn.cursor(); c.execute("SELECT user_id FROM moderators"); mods = c.fetchall(); conn.close()
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve_{rid}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{rid}")]])
    for (mod_id,) in mods:
        try: await bot.send_message(mod_id, f"🔔 <b>Жалоба #{rid}</b>\nОбъект: <code>{query}</code>\nКомментарий: {comment}\nОт: {reporter_name}", parse_mode="HTML", reply_markup=kb)
        except: pass

@dp.callback_query(F.data.startswith("approve_"))
async def approve_report(callback: types.CallbackQuery):
    if not is_moderator(callback.from_user.id):
        await callback.answer("Нет прав."); return
    update_report_status(int(callback.data.split("_")[1]), "approved")
    await callback.message.edit_text(callback.message.text + "\n\n✅ ОДОБРЕНО", parse_mode="HTML")
    await callback.answer("Одобрено!")

@dp.callback_query(F.data.startswith("reject_"))
async def reject_report(callback: types.CallbackQuery):
    if not is_moderator(callback.from_user.id):
        await callback.answer("Нет прав."); return
    update_report_status(int(callback.data.split("_")[1]), "rejected")
    await callback.message.edit_text(callback.message.text + "\n\n❌ ОТКЛОНЕНО", parse_mode="HTML")
    await callback.answer("Отклонено.")

@dp.message(Command("addmod"))
async def add_mod(message: types.Message):
    conn = sqlite3.connect("scam.db"); c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM moderators"); count = c.fetchone()[0]; conn.close()
    if count == 0:
        add_moderator(message.from_user.id)
        await message.answer("✅ Вы первый модератор!")
    elif is_moderator(message.from_user.id):
        args = message.text.split()
        if len(args) > 1:
            try: add_moderator(int(args[1])); await message.answer(f"✅ Модератор {args[1]} добавлен.")
            except: await message.answer("❗ /addmod 123456789")
        else: await message.answer("❗ Укажи ID: /addmod 123456789")
    else: await message.answer("❌ Нет прав.")

@dp.message(Command("pending"))
async def cmd_pending(message: types.Message):
    if not is_moderator(message.from_user.id):
        await message.answer("❌ Нет прав."); return
    reports = get_pending_reports()
    if not reports:
        await message.answer("✅ Нет жалоб на модерации."); return
    for rid, query, qtype, comment, reporter, date in reports:
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve_{rid}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{rid}")]])
        await message.answer(f"📋 <b>Жалоба #{rid}</b>\nОбъект: <code>{query}</code>\nКомментарий: {comment}", parse_mode="HTML", reply_markup=kb)

async def main():
    init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())