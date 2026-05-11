import asyncio
import html
import json
import random
import sqlite3
import string
import time
from datetime import datetime
from typing import Any, Dict, Optional

from aiogram import Bot, Dispatcher, F, BaseMiddleware
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    PreCheckoutQuery,
    SuccessfulPayment,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

# ==================== КОНФИГУРАЦИЯ ====================
BOT_TOKEN = "8657372135:AAEyX7RD-_WlP2fjIL2S9TCeeYRn9A1StV8"
BOT_USERNAME = "virrtexbot"
ADMIN_IDS = [8293927811, 8478884644]

REQUIRED_CHANNELS = [
    {"chat_id": "@VIRTEXCHANEL", "url": "https://t.me/VIRTEXCHANEL"},
    {"chat_id": "@VIRTEXCHATW", "url": "https://t.me/VIRTEXCHATW"},
]

CURRENCY_NAME = "VIRTEX"
START_BALANCE = 5000.0
MIN_BET = 10.0
BONUS_COOLDOWN_SECONDS = 12 * 60 * 60
BONUS_REWARD_MIN = 150
BONUS_REWARD_MAX = 350
TRANSFER_COMMISSION = 0.05
STARS_RATE = 3000
GAME_COOLDOWN = 2.5

REFERRER_BONUS = 5000.0
REFERRED_BONUS = 2500.0

BANK_TERMS = {7: 0.03, 14: 0.07, 30: 0.18}
RED_NUMBERS = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}
TOWER_MULTIPLIERS = [1.20, 1.48, 1.86, 2.35, 2.95, 3.75, 4.85, 6.15]
GOLD_MULTIPLIERS = [1.15, 1.35, 1.62, 2.0, 2.55, 3.25, 4.2]
DIAMOND_MULTIPLIERS = [1.12, 1.28, 1.48, 1.72, 2.02, 2.4, 2.92, 3.6]

DB_PATH = "data.db"

# ==================== СОЗДАНИЕ DISPATCHER ====================
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================
def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def now_ts() -> int:
    return int(time.time())

def fmt_money(value: float) -> str:
    value = round(float(value), 2)
    if value >= 1000:
        return f"{value/1000:.1f}k {CURRENCY_NAME}"
    return f"{value:.2f} {CURRENCY_NAME}"

def fmt_dt(ts: int) -> str:
    return datetime.fromtimestamp(ts).strftime("%d.%m.%Y %H:%M")

def fmt_left(seconds: int) -> str:
    seconds = max(0, int(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h}ч {m}м"
    if m > 0:
        return f"{m}м {s}с"
    return f"{s}с"

def escape_html(text: Optional[str]) -> str:
    return html.escape(str(text or ""), quote=False)

def mention_user(user_id: int, name: Optional[str] = None) -> str:
    label = escape_html(name or f"Игрок {user_id}")
    return f'<a href="tg://user?id={int(user_id)}">{label}</a>'

def is_admin(user_id: int) -> bool:
    return int(user_id) in ADMIN_IDS

def parse_amount(text: str) -> float:
    raw = str(text).strip().lower().replace(",", ".").replace(" ", "")
    mult = 1000 if raw.endswith(("k", "к")) else 1
    if mult > 1:
        raw = raw[:-1]
    value = float(raw) * mult
    if value <= 0:
        raise ValueError()
    return round(value, 2)

def parse_int(text: str) -> int:
    return int(str(text).strip())

def normalize_text(text: Optional[str]) -> str:
    s = (text or "").lower().strip()
    for symbol in ["💰", "👤", "🎁", "🎮", "🧾", "🏦", "🎟", "❓", "✨", "•", "|"]:
        s = s.replace(symbol, " ")
    return " ".join(s.split())

def ensure_user(user_id: int) -> None:
    conn = get_db()
    conn.execute("INSERT OR IGNORE INTO users (id, coins, GGs, lost_coins, won_coins, status, checks) VALUES (?, ?, 0, 0, 0, 0, '[]')", 
                 (str(user_id), START_BALANCE))
    conn.commit()
    conn.close()

def get_user(user_id: int):
    ensure_user(user_id)
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (str(user_id),)).fetchone()
    conn.close()
    return row

def add_balance(user_id: int, amount: float) -> float:
    conn = get_db()
    ensure_user(user_id)
    conn.execute("UPDATE users SET coins = coins + ? WHERE id = ?", (round(amount, 2), str(user_id)))
    row = conn.execute("SELECT coins FROM users WHERE id = ?", (str(user_id),)).fetchone()
    conn.commit()
    conn.close()
    return float(row["coins"])

def set_balance(user_id: int, amount: float) -> None:
    conn = get_db()
    ensure_user(user_id)
    conn.execute("UPDATE users SET coins = ? WHERE id = ?", (round(amount, 2), str(user_id)))
    conn.commit()
    conn.close()

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, coins REAL DEFAULT 5000, GGs INTEGER DEFAULT 0, lost_coins REAL DEFAULT 0, won_coins REAL DEFAULT 0, status INTEGER DEFAULT 0, checks TEXT DEFAULT '[]')''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS bets (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, bet_amount REAL, choice TEXT, outcome TEXT, win INTEGER, payout REAL, ts INTEGER)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS json_data (key TEXT PRIMARY KEY, value TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS checks (code TEXT PRIMARY KEY, creator_id TEXT, per_user REAL, remaining INTEGER, claimed TEXT, password TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS promos (name TEXT PRIMARY KEY, reward REAL, claimed TEXT, remaining_activations INTEGER)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS bank_deposits (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, principal REAL, rate REAL, term_days INTEGER, opened_at INTEGER, status TEXT, closed_at INTEGER)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS referrals (id INTEGER PRIMARY KEY AUTOINCREMENT, referrer_id TEXT NOT NULL, referred_id TEXT NOT NULL, reward_amount REAL NOT NULL, created_ts INTEGER NOT NULL, UNIQUE(referred_id))''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS banned_users (user_id TEXT PRIMARY KEY, banned_at INTEGER NOT NULL, reason TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS muted_users (user_id TEXT PRIMARY KEY, muted_until INTEGER NOT NULL, reason TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS system_balance (id INTEGER PRIMARY KEY CHECK (id = 1), coins REAL NOT NULL DEFAULT 0)''')
    cursor.execute("INSERT OR IGNORE INTO system_balance (id, coins) VALUES (1, 0)")
    
    conn.commit()
    conn.close()

# ==================== ПРОВЕРКА ПОДПИСКИ ====================
async def check_subscriptions(user_id: int, bot: Bot) -> tuple[bool, list]:
    not_subscribed = []
    for channel in REQUIRED_CHANNELS:
        try:
            member = await bot.get_chat_member(chat_id=channel["chat_id"], user_id=user_id)
            if member.status in ["left", "kicked"]:
                not_subscribed.append(channel)
        except:
            not_subscribed.append(channel)
    return len(not_subscribed) == 0, not_subscribed

def subscription_keyboard(not_subscribed: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for ch in not_subscribed:
        builder.button(text=f"📢 Подписаться", url=ch["url"])
    builder.button(text="✅ Проверить подписку", callback_data="check_subscription")
    builder.adjust(1)
    return builder.as_markup()

# ==================== ЗАЩИТА ОТ СПАМА ====================
user_cooldown = {}

def check_cooldown(user_id: int) -> bool:
    now = time.time()
    last = user_cooldown.get(user_id, 0)
    if now - last < GAME_COOLDOWN:
        return False
    user_cooldown[user_id] = now
    return True

# ==================== MIDDLEWARE ====================
class BanMuteSubscriptionMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: Message, data: dict):
        user_id = event.from_user.id
        
        conn = get_db()
        banned = conn.execute("SELECT 1 FROM banned_users WHERE user_id = ?", (str(user_id),)).fetchone()
        conn.close()
        if banned:
            await event.answer("🚫 Вы забанены")
            return
        
        if event.text and any(word in event.text.lower() for word in ["башня", "золото", "алмазы", "мины", "рул", "краш", "кубик", "кости", "очко", "футбол", "баскет", "игры", "пер"]):
            ok, not_subscribed = await check_subscriptions(user_id, data["bot"])
            if not ok:
                await event.answer("⚠️ Подпишитесь на каналы!", reply_markup=subscription_keyboard(not_subscribed))
                return
        
        conn = get_db()
        muted = conn.execute("SELECT muted_until FROM muted_users WHERE user_id = ?", (str(user_id),)).fetchone()
        conn.close()
        if muted and muted["muted_until"] > now_ts():
            await event.answer(f"⏳ Вы в муте до {fmt_dt(muted['muted_until'])}")
            return
        
        return await handler(event, data)

dp.message.middleware(BanMuteSubscriptionMiddleware())

# ==================== ФУНКЦИИ СТАВОК ====================
def settle_instant_bet(user_id: int, bet: float, payout: float, choice: str, outcome: str) -> tuple[bool, float]:
    payout = round(max(0.0, payout), 2)
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        ensure_user(user_id)
        row = conn.execute("SELECT coins FROM users WHERE id = ?", (str(user_id),)).fetchone()
        coins = float(row["coins"])
        if coins < bet:
            conn.rollback()
            return False, coins
        new_balance = round(coins - bet + payout, 2)
        conn.execute("UPDATE users SET coins = ? WHERE id = ?", (new_balance, str(user_id)))
        conn.execute("INSERT INTO bets (user_id, bet_amount, choice, outcome, win, payout, ts) VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (str(user_id), round(bet, 2), choice, outcome, 1 if payout > 0 else 0, payout, now_ts()))
        conn.commit()
        return True, new_balance
    except:
        conn.rollback()
        return False, 0
    finally:
        conn.close()

def reserve_bet(user_id: int, bet: float) -> tuple[bool, float]:
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        ensure_user(user_id)
        row = conn.execute("SELECT coins FROM users WHERE id = ?", (str(user_id),)).fetchone()
        coins = float(row["coins"])
        if coins < bet:
            conn.rollback()
            return False, coins
        new_balance = round(coins - bet, 2)
        conn.execute("UPDATE users SET coins = ? WHERE id = ?", (new_balance, str(user_id)))
        conn.commit()
        return True, new_balance
    except:
        conn.rollback()
        return False, 0
    finally:
        conn.close()

def finalize_reserved_bet(user_id: int, bet: float, payout: float, choice: str, outcome: str) -> float:
    payout = round(max(0.0, payout), 2)
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        if payout > 0:
            conn.execute("UPDATE users SET coins = coins + ? WHERE id = ?", (payout, str(user_id)))
        conn.execute("INSERT INTO bets (user_id, bet_amount, choice, outcome, win, payout, ts) VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (str(user_id), round(bet, 2), choice, outcome, 1 if payout > 0 else 0, payout, now_ts()))
        row = conn.execute("SELECT coins FROM users WHERE id = ?", (str(user_id),)).fetchone()
        conn.commit()
        return float(row["coins"])
    except:
        conn.rollback()
        return 0
    finally:
        conn.close()

# ==================== ФУНКЦИИ ПЕРЕВОДА ====================
def transfer_coins(from_id: int, to_id: int, amount: float) -> tuple[bool, str, float]:
    if amount <= 0:
        return False, "Сумма должна быть положительной", 0
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        ensure_user(from_id)
        ensure_user(to_id)
        from_row = conn.execute("SELECT coins FROM users WHERE id = ?", (str(from_id),)).fetchone()
        balance = float(from_row["coins"])
        if balance < amount:
            conn.rollback()
            return False, f"Недостаточно средств. У вас {fmt_money(balance)}", 0
        
        commission = round(amount * TRANSFER_COMMISSION, 2)
        net = round(amount - commission, 2)
        
        conn.execute("UPDATE users SET coins = coins - ? WHERE id = ?", (amount, str(from_id)))
        conn.execute("UPDATE users SET coins = coins + ? WHERE id = ?", (net, str(to_id)))
        conn.execute("UPDATE system_balance SET coins = coins + ? WHERE id = 1", (commission,))
        conn.commit()
        return True, f"✅ Переведено {fmt_money(net)} (комиссия {fmt_money(commission)})", net
    except:
        conn.rollback()
        return False, "Ошибка перевода", 0
    finally:
        conn.close()

# ==================== ФУНКЦИИ БАНА/МУТА ====================
def ban_user(user_id: int) -> bool:
    conn = get_db()
    try:
        conn.execute("INSERT OR REPLACE INTO banned_users (user_id, banned_at, reason) VALUES (?, ?, '')", (str(user_id), now_ts()))
        conn.commit()
        return True
    except:
        return False
    finally:
        conn.close()

def unban_user(user_id: int) -> bool:
    conn = get_db()
    try:
        conn.execute("DELETE FROM banned_users WHERE user_id = ?", (str(user_id),))
        conn.commit()
        return True
    except:
        return False
    finally:
        conn.close()

def mute_user(user_id: int, minutes: int) -> bool:
    conn = get_db()
    try:
        until = now_ts() + minutes * 60
        conn.execute("INSERT OR REPLACE INTO muted_users (user_id, muted_until, reason) VALUES (?, ?, '')", (str(user_id), until))
        conn.commit()
        return True
    except:
        return False
    finally:
        conn.close()

def unmute_user(user_id: int) -> bool:
    conn = get_db()
    try:
        conn.execute("DELETE FROM muted_users WHERE user_id = ?", (str(user_id),))
        conn.commit()
        return True
    except:
        return False
    finally:
        conn.close()

# ==================== ФУНКЦИИ ЧЕКОВ ====================
def generate_check_code(conn):
    while True:
        code = "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
        if not conn.execute("SELECT 1 FROM checks WHERE code=?", (code,)).fetchone():
            return code

def create_check_atomic(user_id: int, per_user: float, count: int):
    total = per_user * count
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        ensure_user(user_id)
        row = conn.execute("SELECT coins FROM users WHERE id=?", (str(user_id),)).fetchone()
        if float(row["coins"]) < total:
            conn.rollback()
            return False, "Недостаточно средств"
        code = generate_check_code(conn)
        conn.execute("UPDATE users SET coins = coins - ? WHERE id=?", (total, str(user_id)))
        conn.execute("INSERT INTO checks (code, creator_id, per_user, remaining, claimed) VALUES (?, ?, ?, ?, ?)",
                     (code, str(user_id), round(per_user, 2), count, "[]"))
        conn.commit()
        return True, code
    except:
        conn.rollback()
        return False, "Ошибка"
    finally:
        conn.close()

def claim_check_atomic(user_id: int, code: str):
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM checks WHERE code=?", (code.upper(),)).fetchone()
        if not row:
            conn.rollback()
            return False, "Чек не найден", 0
        if row["remaining"] <= 0:
            conn.rollback()
            return False, "Чек закончился", 0
        claimed = json.loads(row["claimed"] or "[]")
        if str(user_id) in claimed:
            conn.rollback()
            return False, "Вы уже активировали этот чек", 0
        claimed.append(str(user_id))
        reward = float(row["per_user"])
        conn.execute("UPDATE users SET coins = coins + ? WHERE id=?", (reward, str(user_id)))
        conn.execute("UPDATE checks SET remaining = remaining - 1, claimed = ? WHERE code=?", (json.dumps(claimed), code.upper()))
        conn.commit()
        return True, "Чек активирован", reward
    except:
        conn.rollback()
        return False, "Ошибка", 0
    finally:
        conn.close()

# ==================== ФУНКЦИИ ПРОМОКОДОВ ====================
def create_promo(code: str, reward: float, activations: int):
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO promos (name, reward, claimed, remaining_activations) VALUES (?, ?, '[]', ?)",
                 (code.upper(), round(reward, 2), activations))
    conn.commit()
    conn.close()

def redeem_promo_atomic(user_id: int, code: str):
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM promos WHERE name=?", (code.upper(),)).fetchone()
        if not row:
            conn.rollback()
            return False, "Промокод не найден", 0
        if row["remaining_activations"] <= 0:
            conn.rollback()
            return False, "Промокод закончился", 0
        claimed = json.loads(row["claimed"] or "[]")
        if str(user_id) in claimed:
            conn.rollback()
            return False, "Вы уже активировали этот промокод", 0
        claimed.append(str(user_id))
        reward = float(row["reward"])
        conn.execute("UPDATE users SET coins = coins + ? WHERE id=?", (reward, str(user_id)))
        conn.execute("UPDATE promos SET claimed = ?, remaining_activations = remaining_activations - 1 WHERE name=?", (json.dumps(claimed), code.upper()))
        conn.commit()
        return True, "Промокод активирован", reward
    except:
        conn.rollback()
        return False, "Ошибка", 0
    finally:
        conn.close()

# ==================== ФУНКЦИИ БАНКА ====================
def add_deposit(user_id: int, amount: float, term_days: int):
    rate = BANK_TERMS.get(term_days)
    if not rate:
        return False, "Неверный срок"
    ok, _ = reserve_bet(user_id, amount)
    if not ok:
        return False, f"Недостаточно средств"
    conn = get_db()
    conn.execute("INSERT INTO bank_deposits (user_id, principal, rate, term_days, opened_at, status) VALUES (?, ?, ?, ?, ?, 'active')",
                 (str(user_id), round(amount, 2), rate, term_days, now_ts()))
    conn.commit()
    conn.close()
    return True, f"Депозит открыт"

def withdraw_matured_deposits(user_id: int):
    now = now_ts()
    conn = get_db()
    total = 0
    count = 0
    try:
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute("SELECT * FROM bank_deposits WHERE user_id=? AND status='active'", (str(user_id),)).fetchall()
        for row in rows:
            unlock = row["opened_at"] + row["term_days"] * 86400
            if now < unlock:
                continue
            payout = row["principal"] * (1 + row["rate"])
            total += payout
            count += 1
            conn.execute("UPDATE bank_deposits SET status='closed', closed_at=? WHERE id=?", (now, row["id"]))
        if total > 0:
            conn.execute("UPDATE users SET coins = coins + ? WHERE id=?", (round(total, 2), str(user_id)))
        conn.commit()
        return count, round(total, 2)
    except:
        conn.rollback()
        return 0, 0
    finally:
        conn.close()

def get_bank_summary(user_id: int):
    conn = get_db()
    active = conn.execute("SELECT COUNT(*) as c, COALESCE(SUM(principal),0) as s FROM bank_deposits WHERE user_id=? AND status='active'", (str(user_id),)).fetchone()
    conn.close()
    return {"count": active["c"] if active else 0, "sum": active["s"] if active else 0}

# ==================== КЛАВИАТУРЫ ====================
def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Баланс", callback_data="menu:balance")],
        [InlineKeyboardButton(text="🎲 Игры", callback_data="menu:games")],
        [InlineKeyboardButton(text="⭐ Пополнить", callback_data="menu:donate")],
        [InlineKeyboardButton(text="🏦 Банк", callback_data="menu:bank")],
        [InlineKeyboardButton(text="🧾 Чеки", callback_data="menu:checks")],
        [InlineKeyboardButton(text="👥 Рефералы", callback_data="menu:ref")],
        [InlineKeyboardButton(text="➕ Добавить в чат", callback_data="menu:add_chat")],
        [InlineKeyboardButton(text="❓ Помощь", callback_data="menu:help")],
    ])

def games_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗼 Башня", callback_data="game:tower"), InlineKeyboardButton(text="🥇 Золото", callback_data="game:gold")],
        [InlineKeyboardButton(text="💎 Алмазы", callback_data="game:diamond"), InlineKeyboardButton(text="💣 Мины", callback_data="game:mines")],
        [InlineKeyboardButton(text="🎴 Очко", callback_data="game:ochko"), InlineKeyboardButton(text="🎡 Рулетка", callback_data="game:roulette")],
        [InlineKeyboardButton(text="📈 Краш", callback_data="game:crash"), InlineKeyboardButton(text="🎲 Кубик", callback_data="game:cube")],
        [InlineKeyboardButton(text="🎯 Кости", callback_data="game:dice"), InlineKeyboardButton(text="⚽ Футбол", callback_data="game:football")],
        [InlineKeyboardButton(text="🏀 Баскет", callback_data="game:basket"), InlineKeyboardButton(text="🔙 Назад", callback_data="menu:back")],
    ])

def checks_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать чек", callback_data="checks:create")],
        [InlineKeyboardButton(text="💸 Активировать чек", callback_data="checks:claim")],
        [InlineKeyboardButton(text="📄 Мои чеки", callback_data="checks:my")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="menu:back")],
    ])

def bank_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Открыть депозит", callback_data="bank:open")],
        [InlineKeyboardButton(text="📜 Мои депозиты", callback_data="bank:list")],
        [InlineKeyboardButton(text="💰 Снять зрелые", callback_data="bank:withdraw")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="menu:back")],
    ])

def bank_terms_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="7 дней (+3%)", callback_data="bank:term:7")],
        [InlineKeyboardButton(text="14 дней (+7%)", callback_data="bank:term:14")],
        [InlineKeyboardButton(text="30 дней (+18%)", callback_data="bank:term:30")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="bank:term:cancel")],
    ])

def roulette_choice_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔴 Красное", callback_data="roulette:choice:red"), InlineKeyboardButton(text="⚫ Черное", callback_data="roulette:choice:black")],
        [InlineKeyboardButton(text="2️⃣ Чет", callback_data="roulette:choice:even"), InlineKeyboardButton(text="1️⃣ Нечет", callback_data="roulette:choice:odd")],
        [InlineKeyboardButton(text="0️⃣ Зеро (x36)", callback_data="roulette:choice:zero")],
    ])

def tower_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1", callback_data="tower:pick:1"), InlineKeyboardButton(text="2", callback_data="tower:pick:2"), InlineKeyboardButton(text="3", callback_data="tower:pick:3")],
        [InlineKeyboardButton(text="💰 Забрать выигрыш", callback_data="tower:cash"), InlineKeyboardButton(text="❌ Сдаться", callback_data="tower:cancel")],
    ])

def gold_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧱 1", callback_data="gold:pick:1"), InlineKeyboardButton(text="🧱 2", callback_data="gold:pick:2"), InlineKeyboardButton(text="🧱 3", callback_data="gold:pick:3"), InlineKeyboardButton(text="🧱 4", callback_data="gold:pick:4")],
        [InlineKeyboardButton(text="💰 Забрать выигрыш", callback_data="gold:cash"), InlineKeyboardButton(text="❌ Сдаться", callback_data="gold:cancel")],
    ])

def diamond_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔹 1", callback_data="diamond:pick:1"), InlineKeyboardButton(text="🔹 2", callback_data="diamond:pick:2"), InlineKeyboardButton(text="🔹 3", callback_data="diamond:pick:3"), InlineKeyboardButton(text="🔹 4", callback_data="diamond:pick:4"), InlineKeyboardButton(text="🔹 5", callback_data="diamond:pick:5")],
        [InlineKeyboardButton(text="💰 Забрать выигрыш", callback_data="diamond:cash"), InlineKeyboardButton(text="❌ Сдаться", callback_data="diamond:cancel")],
    ])

def mines_kb(game: Dict[str, Any], reveal_all: bool = False) -> InlineKeyboardMarkup:
    opened = set(game["opened"])
    mines = set(game["mines"])
    rows = []
    for start in (1, 4, 7):
        row = []
        for idx in range(start, start + 3):
            if idx in opened:
                text = "✅"
                callback = "mines:noop"
            elif reveal_all and idx in mines:
                text = "💣"
                callback = "mines:noop"
            else:
                text = str(idx)
                callback = f"mines:cell:{idx}"
            row.append(InlineKeyboardButton(text=text, callback_data=callback))
        rows.append(row)

    rows.append([InlineKeyboardButton(text="💰 Забрать выигрыш", callback_data="mines:cash"), InlineKeyboardButton(text="❌ Сдаться", callback_data="mines:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def ochko_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Взять", callback_data="ochko:hit"), InlineKeyboardButton(text="✋ Стоп", callback_data="ochko:stand")],
    ])

def ochko_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Начать", callback_data="ochko:start"), InlineKeyboardButton(text="❌ Отмена", callback_data="ochko:cancel")],
    ])

# ==================== ГЛОБАЛЬНЫЕ СЛОВАРИ ДЛЯ ИГР ====================
TOWER_GAMES: Dict[int, Dict[str, Any]] = {}
GOLD_GAMES: Dict[int, Dict[str, Any]] = {}
DIAMOND_GAMES: Dict[int, Dict[str, Any]] = {}
MINES_GAMES: Dict[int, Dict[str, Any]] = {}
OCHKO_GAMES: Dict[int, Dict[str, Any]] = {}

# ==================== СОСТОЯНИЯ FSM ====================
class CheckCreateStates(StatesGroup):
    waiting_amount = State()
    waiting_count = State()

class CheckClaimStates(StatesGroup):
    waiting_code = State()

class PromoStates(StatesGroup):
    waiting_code = State()

class BankStates(StatesGroup):
    waiting_amount = State()

class RouletteStates(StatesGroup):
    waiting_amount = State()
    waiting_choice = State()

class CrashStates(StatesGroup):
    waiting_amount = State()
    waiting_target = State()

class CubeStates(StatesGroup):
    waiting_amount = State()
    waiting_guess = State()

class DiceStates(StatesGroup):
    waiting_amount = State()
    waiting_guess = State()

class FootballStates(StatesGroup):
    waiting_amount = State()

class BasketStates(StatesGroup):
    waiting_amount = State()

class TowerStates(StatesGroup):
    waiting_amount = State()

class GoldStates(StatesGroup):
    waiting_amount = State()

class DiamondStates(StatesGroup):
    waiting_amount = State()

class MinesStates(StatesGroup):
    waiting_amount = State()
    waiting_mines = State()

class OchkoStates(StatesGroup):
    waiting_amount = State()
    waiting_confirm = State()

class AdminBroadcastStates(StatesGroup):
    waiting_message = State()

# ==================== ТЕКСТ ПОМОЩИ ====================
def get_help_text() -> str:
    return """
<b>🎮 Игровой бот VIRTEX</b>

<b>💰 Баланс и бонусы</b>
• <code>б</code> или <code>баланс</code> - показать баланс
• <code>профиль</code> - статистика
• <code>бонус</code> - получить бонус

<b>🎲 Игры</b>
• <code>башня 300 2</code> - Башня
• <code>золото 300</code> - Золото
• <code>алмазы 300 2</code> - Алмазы
• <code>мины 300 3</code> - Мины
• <code>рул 300 чет</code> - Рулетка
• <code>краш 300 2.5</code> - Краш
• <code>кубик 300 5</code> - Кубик
• <code>кости 300 м</code> - Кости
• <code>очко 300</code> - Очко
• <code>футбол 300 гол</code> - Футбол
• <code>баскет 300</code> - Баскет

<b>💸 Переводы</b>
• <code>пер @username 100</code> - комиссия 5%

<b>⭐ Пополнение</b>
• <code>/donate</code> - купить VIRTEX за Stars (1 Star = 3000)

<b>🏦 Банк</b>
• <code>банк</code> - депозиты под 3-18%

<b>🧾 Чеки</b>
• <code>чеки</code> - создать/активировать чек

<b>🎟 Промокоды</b>
• <code>промо КОД</code> - активировать промокод

<b>👥 Рефералы</b>
• <code>/ref</code> - реферальная ссылка
• +5000 вам, +2500 другу

<b>❓ Помощь</b>
• <code>помощь</code> - это меню
"""

# ==================== КОМАНДЫ ====================
@dp.message(CommandStart())
async def start_cmd(message: Message, state: FSMContext, bot: Bot):
    user_id = message.from_user.id
    ensure_user(user_id)
    
    # Реферальная система
    args = message.text.split()
    if len(args) > 1 and args[1].startswith("ref_"):
        try:
            referrer_id = int(args[1][4:])
            if referrer_id != user_id:
                conn = get_db()
                existing = conn.execute("SELECT 1 FROM referrals WHERE referred_id = ?", (str(user_id),)).fetchone()
                if not existing:
                    add_balance(referrer_id, REFERRER_BONUS)
                    add_balance(user_id, REFERRED_BONUS)
                    conn.execute("INSERT INTO referrals (referrer_id, referred_id, reward_amount, created_ts) VALUES (?, ?, ?, ?)",
                                 (str(referrer_id), str(user_id), REFERRER_BONUS, now_ts()))
                    conn.commit()
                    await message.answer(f"🎉 По реферальной ссылке!\nВам +{fmt_money(REFERRED_BONUS)}\nРефереру +{fmt_money(REFERRER_BONUS)}")
                conn.close()
        except:
            pass
    
    await state.clear()
    await message.answer(
        f"🎮 Добро пожаловать в <b>{CURRENCY_NAME}</b>!\n\n"
        f"💰 Стартовый баланс: {fmt_money(START_BALANCE)}\n"
        f"👥 Реферальная ссылка: /ref\n\n"
        f"Используйте кнопки:",
        reply_markup=main_menu_kb()
    )

@dp.message(Command("help"))
@dp.message(lambda m: normalize_text(m.text) in {"помощь", "/help"})
async def help_cmd(message: Message):
    await message.answer(get_help_text())

@dp.message(Command("menu"))
async def menu_cmd(message: Message):
    await message.answer("📍 <b>Меню</b>", reply_markup=main_menu_kb())

@dp.message(Command("ref"))
async def ref_cmd(message: Message):
    link = f"https://t.me/{BOT_USERNAME}?start=ref_{message.from_user.id}"
    conn = get_db()
    count = conn.execute("SELECT COUNT(*) as c FROM referrals WHERE referrer_id = ?", (str(message.from_user.id),)).fetchone()["c"]
    conn.close()
    await message.answer(
        f"👥 <b>Реферальная программа</b>\n\n"
        f"🔗 Ваша ссылка:\n<code>{link}</code>\n\n"
        f"📊 Приглашено: {count}\n"
        f"🎁 За друга: +{fmt_money(REFERRER_BONUS)} вам, +{fmt_money(REFERRED_BONUS)} другу"
    )

@dp.message(Command("donate"))
async def donate_cmd(message: Message):
    await message.answer(
        f"⭐ <b>Пополнение {CURRENCY_NAME}</b>\n\n1 Star = {STARS_RATE} {CURRENCY_NAME}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⭐ 1 Star", callback_data="donate:1"), InlineKeyboardButton(text="⭐ 5 Stars", callback_data="donate:5")],
            [InlineKeyboardButton(text="⭐ 10 Stars", callback_data="donate:10"), InlineKeyboardButton(text="⭐ 50 Stars", callback_data="donate:50")],
            [InlineKeyboardButton(text="⭐ 100 Stars", callback_data="donate:100")],
        ])
    )

@dp.message(lambda m: normalize_text(m.text) in {"б", "баланс"})
async def balance_cmd(message: Message):
    user = get_user(message.from_user.id)
    await message.answer(f"💰 {mention_user(message.from_user.id, message.from_user.first_name)}, баланс: {fmt_money(float(user['coins']))}")

@dp.message(lambda m: normalize_text(m.text) in {"профиль"})
async def profile_cmd(message: Message):
    user = get_user(message.from_user.id)
    conn = get_db()
    bets = conn.execute("SELECT COUNT(*) as total, SUM(CASE WHEN win=1 THEN 1 ELSE 0 END) as wins FROM bets WHERE user_id=?", (str(message.from_user.id),)).fetchone()
    conn.close()
    total = bets["total"] or 1
    wr = (bets["wins"] / total * 100)
    await message.answer(
        f"👤 <b>Профиль</b>\n\n"
        f"💰 Баланс: {fmt_money(float(user['coins']))}\n"
        f"🎲 Ставок: {bets['total']}\n"
        f"🏆 Побед: {bets['wins']}\n"
        f"📊 Winrate: {wr:.1f}%"
    )

@dp.message(lambda m: normalize_text(m.text) in {"бонус"})
async def bonus_cmd(message: Message):
    user_id = message.from_user.id
    key = f"bonus_ts:{user_id}"
    conn = get_db()
    row = conn.execute("SELECT value FROM json_data WHERE key=?", (key,)).fetchone()
    last = int(json.loads(row["value"])) if row else 0
    now = now_ts()
    if now - last < BONUS_COOLDOWN_SECONDS:
        left = BONUS_COOLDOWN_SECONDS - (now - last)
        return await message.answer(f"🎁 Бонус через {fmt_left(left)}")
    reward = random.randint(BONUS_REWARD_MIN, BONUS_REWARD_MAX)
    ok, bal = settle_instant_bet(user_id, 0, reward, "bonus", "claim")
    if ok:
        conn.execute("INSERT OR REPLACE INTO json_data (key, value) VALUES (?, ?)", (key, json.dumps(now)))
        conn.commit()
        await message.answer(f"🎁 Бонус +{fmt_money(reward)}\n💰 Баланс: {fmt_money(bal)}")
    conn.close()

@dp.message(lambda m: normalize_text(m.text) in {"топ"})
async def top_cmd(message: Message):
    conn = get_db()
    rows = conn.execute("SELECT id, coins FROM users ORDER BY coins DESC LIMIT 10").fetchall()
    conn.close()
    if not rows:
        return await message.answer("🏆 Топ пуст")
    lines = ["🏆 <b>Топ игроков</b>", "<blockquote>"]
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    for i, row in enumerate(rows, 1):
        icon = medals.get(i, f"{i}.")
        lines.append(f"{icon} {mention_user(int(row['id']))} — {fmt_money(float(row['coins']))}")
    lines.append("</blockquote>")
    await message.answer("\n".join(lines))

@dp.message(lambda m: normalize_text(m.text) in {"игры"})
async def games_cmd(message: Message):
    await message.answer("🎮 <b>Игры</b>\nВыберите игру:", reply_markup=games_kb())

# ==================== ПЕРЕВОДЫ ====================
@dp.message(lambda m: normalize_text(m.text).startswith("пер"))
async def transfer_cmd(message: Message):
    text = message.text.strip()
    parts = text.split(maxsplit=2)
    
    if message.reply_to_message and message.reply_to_message.from_user:
        target = message.reply_to_message.from_user
        if len(parts) < 2:
            return await message.answer("❌ Формат: `пер 100` в ответ на сообщение")
        try:
            amount = parse_amount(parts[1])
        except:
            return await message.answer("❌ Неверная сумма")
        if amount < 1:
            return await message.answer(f"❌ Минимум: {fmt_money(1)}")
        ok, msg, _ = transfer_coins(message.from_user.id, target.id, amount)
        await message.answer(f"{msg}\n👤 Получатель: {mention_user(target.id, target.full_name)}")
        return
    
    if len(parts) < 3:
        return await message.answer("❌ Формат: `пер @username 100` или ответ на сообщение")
    
    target_str = parts[1]
    try:
        amount = parse_amount(parts[2])
    except:
        return await message.answer("❌ Неверная сумма")
    
    if amount < 1:
        return await message.answer(f"❌ Минимум: {fmt_money(1)}")
    
    if target_str.startswith("@"):
        try:
            chat = await message.bot.get_chat(target_str)
            target_id = chat.id
        except:
            return await message.answer("❌ Пользователь не найден")
    else:
        try:
            target_id = int(target_str)
        except:
            return await message.answer("❌ Неверный ID")
    
    if target_id == message.from_user.id:
        return await message.answer("❌ Нельзя перевести самому себе")
    
    ok, msg, _ = transfer_coins(message.from_user.id, target_id, amount)
    await message.answer(msg)

# ==================== ЧЕКИ ====================
@dp.message(lambda m: normalize_text(m.text) in {"чеки"})
async def checks_cmd(message: Message):
    await message.answer("🧾 <b>Чеки</b>", reply_markup=checks_kb())

@dp.callback_query(F.data == "checks:create")
async def checks_create_cb(query: CallbackQuery, state: FSMContext):
    await state.set_state(CheckCreateStates.waiting_amount)
    await query.message.answer("💰 Введите сумму на 1 активацию чека:")
    await query.answer()

@dp.message(CheckCreateStates.waiting_amount)
async def checks_create_amount(message: Message, state: FSMContext):
    try:
        amount = parse_amount(message.text)
    except:
        return await message.answer("❌ Введите сумму")
    if amount < 10:
        return await message.answer(f"❌ Минимум {fmt_money(10)}")
    await state.update_data(amount=amount)
    await state.set_state(CheckCreateStates.waiting_count)
    await message.answer("🔢 Количество активаций (1-100):")

@dp.message(CheckCreateStates.waiting_count)
async def checks_create_count(message: Message, state: FSMContext):
    try:
        count = int(message.text)
    except:
        return await message.answer("❌ Введите число")
    if count < 1 or count > 100:
        return await message.answer("❌ От 1 до 100")
    data = await state.get_data()
    amount = data["amount"]
    ok, code = create_check_atomic(message.from_user.id, amount, count)
    await state.clear()
    if not ok:
        return await message.answer(f"❌ {code}")
    await message.answer(f"✅ Чек создан!\n<code>{code}</code>\n💰 {fmt_money(amount)} x{count}")

@dp.callback_query(F.data == "checks:claim")
async def checks_claim_cb(query: CallbackQuery, state: FSMContext):
    await state.set_state(CheckClaimStates.waiting_code)
    await query.message.answer("🔑 Введите код чека:")
    await query.answer()

@dp.message(CheckClaimStates.waiting_code)
async def checks_claim_code(message: Message, state: FSMContext):
    code = message.text.strip().upper()
    ok, msg, reward = claim_check_atomic(message.from_user.id, code)
    await state.clear()
    if not ok:
        return await message.answer(f"❌ {msg}")
    await message.answer(f"✅ {msg}\n+{fmt_money(reward)}")

@dp.callback_query(F.data == "checks:my")
async def checks_my_cb(query: CallbackQuery):
    conn = get_db()
    rows = conn.execute("SELECT code, per_user, remaining FROM checks WHERE creator_id=? ORDER BY rowid DESC LIMIT 10", (str(query.from_user.id),)).fetchall()
    conn.close()
    if not rows:
        return await query.message.answer("📭 Нет чеков")
    lines = ["🧾 <b>Мои чеки</b>:"]
    for r in rows:
        lines.append(f"<code>{r['code']}</code> | {fmt_money(r['per_user'])} | ост. {r['remaining']}")
    await query.message.answer("\n".join(lines))
    await query.answer()

# ==================== ПРОМОКОДЫ ====================
@dp.message(lambda m: normalize_text(m.text).startswith("промо"))
async def promo_cmd(message: Message, state: FSMContext):
    parts = message.text.split(maxsplit=1)
    if len(parts) == 2:
        ok, msg, reward = redeem_promo_atomic(message.from_user.id, parts[1])
        if ok:
            return await message.answer(f"✅ {msg}\n+{fmt_money(reward)}")
        return await message.answer(f"❌ {msg}")
    await state.set_state(PromoStates.waiting_code)
    await message.answer("🎟 Введите код промокода:")

@dp.message(PromoStates.waiting_code)
async def promo_code_input(message: Message, state: FSMContext):
    ok, msg, reward = redeem_promo_atomic(message.from_user.id, message.text)
    await state.clear()
    if ok:
        await message.answer(f"✅ {msg}\n+{fmt_money(reward)}")
    else:
        await message.answer(f"❌ {msg}")

@dp.message(Command("addpromo"))
async def addpromo_cmd(message: Message):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) != 4:
        return await message.answer("📝 Формат: /addpromo КОД СУММА АКТИВАЦИИ")
    code = parts[1].upper()
    try:
        reward = parse_amount(parts[2])
        activations = int(parts[3])
    except:
        return await message.answer("❌ Неверные данные")
    create_promo(code, reward, activations)
    await message.answer(f"✅ Промокод {code} создан!\n💰 {fmt_money(reward)} x{activations}")

# ==================== БАНК ====================
@dp.message(lambda m: normalize_text(m.text) in {"банк"})
async def bank_cmd(message: Message):
    user = get_user(message.from_user.id)
    summary = get_bank_summary(message.from_user.id)
    await message.answer(
        f"🏦 <b>Банк</b>\n\n"
        f"💰 Баланс: {fmt_money(float(user['coins']))}\n"
        f"📊 Активных депозитов: {summary['count']}\n"
        f"💵 Сумма в депозитах: {fmt_money(summary['sum'])}\n\n"
        f"📈 Ставки: 7д(+3%), 14д(+7%), 30д(+18%)",
        reply_markup=bank_kb()
    )

@dp.callback_query(F.data == "bank:open")
async def bank_open_cb(query: CallbackQuery, state: FSMContext):
    await state.set_state(BankStates.waiting_amount)
    await query.message.answer("💰 Сумма депозита (мин 100):")
    await query.answer()

@dp.message(BankStates.waiting_amount)
async def bank_amount(message: Message, state: FSMContext):
    try:
        amount = parse_amount(message.text)
    except:
        return await message.answer("❌ Введите сумму")
    if amount < 100:
        return await message.answer(f"❌ Минимум {fmt_money(100)}")
    await state.update_data(amount=amount)
    await message.answer("📅 Выберите срок:", reply_markup=bank_terms_kb())

@dp.callback_query(F.data.startswith("bank:term:"))
async def bank_term_cb(query: CallbackQuery, state: FSMContext):
    term = query.data.split(":")[-1]
    if term == "cancel":
        await state.clear()
        await query.message.edit_text("❌ Отменено")
        return await query.answer()
    data = await state.get_data()
    amount = data.get("amount", 0)
    if amount <= 0:
        await state.clear()
        return await query.answer("❌ Ошибка", show_alert=True)
    ok, msg = add_deposit(query.from_user.id, amount, int(term))
    await state.clear()
    await query.message.edit_text(f"{'✅' if ok else '❌'} {msg}")
    await query.answer()

@dp.callback_query(F.data == "bank:list")
async def bank_list_cb(query: CallbackQuery):
    conn = get_db()
    rows = conn.execute("SELECT * FROM bank_deposits WHERE user_id=? ORDER BY id DESC LIMIT 10", (str(query.from_user.id),)).fetchall()
    conn.close()
    if not rows:
        return await query.message.answer("📭 Нет депозитов")
    now = now_ts()
    lines = ["📜 <b>Мои депозиты</b>:"]
    for r in rows:
        unlock = r["opened_at"] + r["term_days"] * 86400
        if r["status"] == "active":
            if unlock <= now:
                status = "✅ готов"
            else:
                status = f"⏳ {fmt_left(unlock-now)}"
        else:
            status = "🔒 закрыт"
        lines.append(f"#{r['id']} | {fmt_money(r['principal'])} | +{int(r['rate']*100)}% | {status}")
    await query.message.answer("\n".join(lines))
    await query.answer()

@dp.callback_query(F.data == "bank:withdraw")
async def bank_withdraw_cb(query: CallbackQuery):
    count, total = withdraw_matured_deposits(query.from_user.id)
    if count == 0:
        await query.message.answer("📭 Нет зрелых депозитов")
    else:
        await query.message.answer(f"✅ Выведено {count} депозитов на {fmt_money(total)}")
    await query.answer()

# ==================== ИГРЫ ====================

# ----------------------------- ROULETTE -----------------------------
def roulette_roll(choice: str) -> tuple[bool, float, str]:
    number = random.randint(0, 36)
    color = "green" if number == 0 else ("red" if number in RED_NUMBERS else "black")
    parity = "zero"
    if number != 0:
        parity = "even" if number % 2 == 0 else "odd"

    win = False
    multiplier = 0.0
    if choice == "red" and color == "red":
        win, multiplier = True, 2.0
    elif choice == "black" and color == "black":
        win, multiplier = True, 2.0
    elif choice == "even" and parity == "even":
        win, multiplier = True, 2.0
    elif choice == "odd" and parity == "odd":
        win, multiplier = True, 2.0
    elif choice == "zero" and number == 0:
        win, multiplier = True, 36.0

    pretty_color = {"red": "🔴 красное", "black": "⚫ черное", "green": "🟢 зеро"}[color]
    outcome = f"Выпало {number} ({pretty_color})"
    return win, multiplier, outcome

@dp.message(RouletteStates.waiting_amount)
async def roulette_amount(message: Message, state: FSMContext):
    try:
        bet = parse_amount(message.text)
    except:
        await message.answer("Введи корректную сумму ставки.")
        return
    if bet < MIN_BET:
        await message.answer(f"Минимальная ставка: {fmt_money(MIN_BET)}")
        return
    await state.update_data(bet=bet)
    await state.set_state(RouletteStates.waiting_choice)
    await message.answer("Выбери сектор:", reply_markup=roulette_choice_kb())

async def finish_roulette(message: Message, state: FSMContext, choice: str):
    data = await state.get_data()
    bet = float(data.get("bet", 0) or 0)
    if bet <= 0:
        await message.answer("Ставка не найдена. Начни заново.")
        await state.clear()
        return
    if not check_cooldown(message.from_user.id):
        await message.answer("⏳ Подождите 2.5 секунды")
        return
    win, multiplier, outcome = roulette_roll(choice)
    payout = round(bet * multiplier, 2) if win else 0.0
    ok, balance = settle_instant_bet(message.from_user.id, bet, payout, f"roulette:{choice}", outcome)
    await state.clear()
    if not ok:
        await message.answer("Недостаточно средств на балансе.")
        return
    await message.answer(f"🎡 {outcome}\nСтавка: {fmt_money(bet)}\nРезультат: {'Победа' if win else 'Поражение'}\nВыплата: {fmt_money(payout)}\nБаланс: {fmt_money(balance)}")

@dp.message(RouletteStates.waiting_choice)
async def roulette_choice_text(message: Message, state: FSMContext):
    raw = normalize_text(message.text)
    mapping = {"красное":"red","черное":"black","чет":"even","нечет":"odd","зеро":"zero"}
    choice = mapping.get(raw)
    if not choice:
        await message.answer("Неверный выбор. Введи: красное/черное/чет/нечет/зеро")
        return
    await finish_roulette(message, state, choice)

@dp.callback_query(RouletteStates.waiting_choice, F.data.startswith("roulette:choice:"))
async def roulette_choice_cb(query: CallbackQuery, state: FSMContext):
    choice = query.data.split(":")[-1]
    await finish_roulette(query.message, state, choice)
    await query.answer()

# ----------------------------- CRASH -----------------------------
def crash_roll() -> float:
    u = random.random()
    raw = 0.99 / (1.0 - u)
    return round(max(1.0, min(50.0, raw)), 2)

@dp.message(CrashStates.waiting_amount)
async def crash_amount(message: Message, state: FSMContext):
    try:
        bet = parse_amount(message.text)
    except:
        await message.answer("Введи корректную ставку.")
        return
    if bet < MIN_BET:
        await message.answer(f"Минимальная ставка: {fmt_money(MIN_BET)}")
        return
    await state.update_data(bet=bet)
    await state.set_state(CrashStates.waiting_target)
    await message.answer("Введи множитель выигрыша (1.1 - 10.0)")

@dp.message(CrashStates.waiting_target)
async def crash_target(message: Message, state: FSMContext):
    data = await state.get_data()
    bet = float(data.get("bet", 0) or 0)
    try:
        target = parse_amount(message.text)
    except:
        await message.answer("Введи число, например 1.8")
        return
    if target < 1.1 or target > 10.0:
        await message.answer("Множитель должен быть от 1.1 до 10.0")
        return
    if not check_cooldown(message.from_user.id):
        await message.answer("⏳ Подождите 2.5 секунды")
        return
    rolled = crash_roll()
    win = target <= rolled
    payout = round(bet * target, 2) if win else 0.0
    ok, balance = settle_instant_bet(message.from_user.id, bet, payout, f"crash:{target}", f"crash={rolled}")
    await state.clear()
    if not ok:
        await message.answer("Недостаточно средств.")
        return
    await message.answer(f"📈 <b>Краш</b>\nТвой множитель: x{target:.2f}\nМножитель игры: x{rolled:.2f}\nРезультат: {'Победа' if win else 'Поражение'}\nВыплата: {fmt_money(payout)}\nБаланс: {fmt_money(balance)}")

# ----------------------------- CUBE -----------------------------
@dp.message(CubeStates.waiting_amount)
async def cube_amount(message: Message, state: FSMContext):
    try:
        bet = parse_amount(message.text)
    except:
        await message.answer("Введи корректную ставку.")
        return
    if bet < MIN_BET:
        await message.answer(f"Минимальная ставка: {fmt_money(MIN_BET)}")
        return
    await state.update_data(bet=bet)
    await state.set_state(CubeStates.waiting_guess)
    await message.answer("Угадай число от 1 до 6:")

@dp.message(CubeStates.waiting_guess)
async def cube_guess(message: Message, state: FSMContext):
    data = await state.get_data()
    bet = float(data.get("bet", 0) or 0)
    try:
        guess = parse_int(message.text)
    except:
        await message.answer("Нужно целое число от 1 до 6.")
        return
    if guess < 1 or guess > 6:
        await message.answer("Число должно быть от 1 до 6.")
        return
    if not check_cooldown(message.from_user.id):
        await message.answer("⏳ Подождите 2.5 секунды")
        return
    dice_msg = await message.answer_dice(emoji="🎲")
    rolled = dice_msg.dice.value
    win = guess == rolled
    payout = round(bet * 5.8, 2) if win else 0.0
    ok, balance = settle_instant_bet(message.from_user.id, bet, payout, f"cube:{guess}", f"rolled={rolled}")
    await state.clear()
    if not ok:
        await message.answer("Недостаточно средств.")
        return
    await message.answer(f"🎲 <b>Кубик</b>\nТвой выбор: {guess}\nВыпало: {rolled}\nРезультат: {'Победа' if win else 'Поражение'}\nВыплата: {fmt_money(payout)}\nБаланс: {fmt_money(balance)}")

# ----------------------------- DICE -----------------------------
@dp.message(DiceStates.waiting_amount)
async def dice_amount(message: Message, state: FSMContext):
    try:
        bet = parse_amount(message.text)
    except:
        await message.answer("Введи корректную ставку.")
        return
    if bet < MIN_BET:
        await message.answer(f"Минимальная ставка: {fmt_money(MIN_BET)}")
        return
    await state.update_data(bet=bet)
    await state.set_state(DiceStates.waiting_guess)
    await message.answer("Выбери исход: больше / меньше / семь")

@dp.message(DiceStates.waiting_guess)
async def dice_guess(message: Message, state: FSMContext):
    data = await state.get_data()
    bet = float(data.get("bet", 0) or 0)
    guess = normalize_text(message.text)
    if guess not in {"больше", "меньше", "семь", "7"}:
        await message.answer("Напиши: больше, меньше или семь")
        return
    if not check_cooldown(message.from_user.id):
        await message.answer("⏳ Подождите 2.5 секунды")
        return
    d1_msg = await message.answer_dice(emoji="🎲")
    d2_msg = await message.answer_dice(emoji="🎲")
    d1 = d1_msg.dice.value
    d2 = d2_msg.dice.value
    total = d1 + d2
    win = False
    mult = 0.0
    if guess == "больше" and total > 7:
        win, mult = True, 1.9
    elif guess == "меньше" and total < 7:
        win, mult = True, 1.9
    elif guess in {"семь", "7"} and total == 7:
        win, mult = True, 5.0
    payout = round(bet * mult, 2) if win else 0.0
    ok, balance = settle_instant_bet(message.from_user.id, bet, payout, f"dice:{guess}", f"{d1}+{d2}={total}")
    await state.clear()
    if not ok:
        await message.answer("Недостаточно средств.")
        return
    await message.answer(f"🎯 <b>Кости</b>\nКубики: {d1} и {d2} (сумма {total})\nТвой выбор: {guess}\nРезультат: {'Победа' if win else 'Поражение'}\nВыплата: {fmt_money(payout)}\nБаланс: {fmt_money(balance)}")

# ----------------------------- FOOTBALL -----------------------------
def football_value_text(value: int) -> str:
    return "Гол" if value >= 3 else "Мимо"

@dp.message(FootballStates.waiting_amount)
async def football_amount(message: Message, state: FSMContext):
    try:
        bet = parse_amount(message.text)
    except:
        await message.answer("Введи корректную ставку.")
        return
    if bet < MIN_BET:
        await message.answer(f"Минимальная ставка: {fmt_money(MIN_BET)}")
        return
    if not check_cooldown(message.from_user.id):
        await message.answer("⏳ Подождите 2.5 секунды")
        return
    ok, _ = reserve_bet(message.from_user.id, bet)
    await state.clear()
    if not ok:
        await message.answer("Недостаточно средств.")
        return
    dice_msg = await message.answer_dice(emoji="⚽")
    value = dice_msg.dice.value
    win = value >= 4
    result_title = football_value_text(value)
    payout = round(bet * 1.85, 2) if win else 0.0
    balance = finalize_reserved_bet(message.from_user.id, bet, payout, "football", f"value={value}")
    await message.answer(f"⚽ <b>Футбол</b>\nИтог удара: {result_title}\nРезультат: {'Победа' if win else 'Поражение'}\nВыплата: {fmt_money(payout)}\nБаланс: {fmt_money(balance)}")

# ----------------------------- BASKET -----------------------------
def basketball_value_text(value: int) -> str:
    return "Точный бросок" if value in {4, 5} else "Промах"

@dp.message(BasketStates.waiting_amount)
async def basket_amount(message: Message, state: FSMContext):
    try:
        bet = parse_amount(message.text)
    except:
        await message.answer("Введи корректную ставку.")
        return
    if bet < MIN_BET:
        await message.answer(f"Минимальная ставка: {fmt_money(MIN_BET)}")
        return
    if not check_cooldown(message.from_user.id):
        await message.answer("⏳ Подождите 2.5 секунды")
        return
    ok, _ = reserve_bet(message.from_user.id, bet)
    await state.clear()
    if not ok:
        await message.answer("Недостаточно средств.")
        return
    dice_msg = await message.answer_dice(emoji="🏀")
    value = dice_msg.dice.value
    win = value >= 4
    result_title = basketball_value_text(value)
    payout = round(bet * 1.85, 2) if win else 0.0
    balance = finalize_reserved_bet(message.from_user.id, bet, payout, "basket", f"value={value}")
    await message.answer(f"🏀 <b>Баскетбол</b>\nИтог броска: {result_title}\nРезультат: {'Победа' if win else 'Поражение'}\nВыплата: {fmt_money(payout)}\nБаланс: {fmt_money(balance)}")

# ----------------------------- TOWER -----------------------------
def tower_text(game: Dict[str, Any]) -> str:
    level = game["level"]
    bet = game["bet"]
    current_mult = TOWER_MULTIPLIERS[level - 1] if level > 0 else 0
    current_win = bet * current_mult if level > 0 else 0
    next_mult = TOWER_MULTIPLIERS[level] if level < len(TOWER_MULTIPLIERS) else TOWER_MULTIPLIERS[-1]
    return (f"🗼 <b>Башня</b>\nСтавка: {fmt_money(bet)}\nЭтаж: {level}\nТекущий множитель: x{current_mult:.2f}\nПотенциально сейчас: {fmt_money(current_win)}\nСледующий этаж: x{next_mult:.2f}\n\nВыбери одну из 3 секций.")

@dp.message(TowerStates.waiting_amount)
async def tower_start_amount(message: Message, state: FSMContext):
    try:
        bet = parse_amount(message.text)
    except:
        await message.answer("Введи корректную ставку.")
        return
    if bet < MIN_BET:
        await message.answer(f"Минимальная ставка: {fmt_money(MIN_BET)}")
        return
    ok, _ = reserve_bet(message.from_user.id, bet)
    await state.clear()
    if not ok:
        await message.answer("Недостаточно средств.")
        return
    TOWER_GAMES[message.from_user.id] = {"bet": bet, "level": 0}
    await message.answer(tower_text(TOWER_GAMES[message.from_user.id]), reply_markup=tower_kb())

@dp.callback_query(F.data.startswith("tower:pick:"))
async def tower_pick(query: CallbackQuery):
    user_id = query.from_user.id
    game = TOWER_GAMES.get(user_id)
    if not game:
        await query.answer("Нет активной игры", show_alert=True)
        return
    if not check_cooldown(user_id):
        await query.answer("⏳ Подождите", show_alert=True)
        return
    chosen = int(query.data.split(":")[-1])
    safe = random.randint(1, 3)
    if chosen != safe:
        bet = game["bet"]
        balance = finalize_reserved_bet(user_id, bet, 0.0, "tower", "lose")
        TOWER_GAMES.pop(user_id, None)
        await query.message.edit_text(f"💥 <b>Башня</b>\nЛовушка в секции {safe}. Ты выбрал {chosen}.\nСтавка сгорела: {fmt_money(bet)}\nБаланс: {fmt_money(balance)}")
        await query.answer()
        return
    game["level"] += 1
    level = game["level"]
    if level >= len(TOWER_MULTIPLIERS):
        bet = game["bet"]
        payout = round(bet * TOWER_MULTIPLIERS[-1], 2)
        balance = finalize_reserved_bet(user_id, bet, payout, "tower", "max_floor")
        TOWER_GAMES.pop(user_id, None)
        await query.message.edit_text(f"🏁 <b>Башня</b>\nМаксимальный этаж пройден.\nВыплата: {fmt_money(payout)}\nБаланс: {fmt_money(balance)}")
        await query.answer()
        return
    await query.message.edit_text(tower_text(game), reply_markup=tower_kb())
    await query.answer("Успех")

@dp.callback_query(F.data == "tower:cash")
async def tower_cash(query: CallbackQuery):
    user_id = query.from_user.id
    game = TOWER_GAMES.get(user_id)
    if not game:
        await query.answer("Нет активной игры", show_alert=True)
        return
    bet = game["bet"]
    level = game["level"]
    if level <= 0:
        await query.answer("Сначала сделай минимум 1 ход", show_alert=True)
        return
    mult = TOWER_MULTIPLIERS[level - 1]
    payout = round(bet * mult, 2)
    balance = finalize_reserved_bet(user_id, bet, payout, "tower", f"cashout_level={level}")
    TOWER_GAMES.pop(user_id, None)
    await query.message.edit_text(f"✅ <b>Башня: выигрыш</b>\nЭтаж: {level}\nМножитель: x{mult:.2f}\nВыплата: {fmt_money(payout)}\nБаланс: {fmt_money(balance)}")
    await query.answer()

@dp.callback_query(F.data == "tower:cancel")
async def tower_cancel(query: CallbackQuery):
    user_id = query.from_user.id
    game = TOWER_GAMES.get(user_id)
    if not game:
        await query.answer("Нет активной игры", show_alert=True)
        return
    bet = game["bet"]
    level = game["level"]
    payout = 0.0
    outcome = "cancel_lose"
    if level == 0:
        payout = bet
        outcome = "cancel_refund"
    balance = finalize_reserved_bet(user_id, bet, payout, "tower", outcome)
    TOWER_GAMES.pop(user_id, None)
    await query.message.edit_text(f"❌ <b>Башня завершена</b>\nВозврат: {fmt_money(payout)}\nБаланс: {fmt_money(balance)}")
    await query.answer()

# ----------------------------- GOLD -----------------------------
def gold_text(game: Dict[str, Any]) -> str:
    step = game["step"]
    bet = game["bet"]
    cur_mult = GOLD_MULTIPLIERS[step - 1] if step > 0 else 0
    cur_win = bet * cur_mult if step > 0 else 0
    next_mult = GOLD_MULTIPLIERS[step] if step < len(GOLD_MULTIPLIERS) else GOLD_MULTIPLIERS[-1]
    return (f"🥇 <b>Золото</b>\nСтавка: {fmt_money(bet)}\nРаунд: {step}\nТекущий множитель: x{cur_mult:.2f}\nПотенциально сейчас: {fmt_money(cur_win)}\nСледующий раунд: x{next_mult:.2f}\n\nВыбери плитку (одна из них с ловушкой).")

@dp.message(GoldStates.waiting_amount)
async def gold_start_amount(message: Message, state: FSMContext):
    try:
        bet = parse_amount(message.text)
    except:
        await message.answer("Введи корректную ставку.")
        return
    if bet < MIN_BET:
        await message.answer(f"Минимальная ставка: {fmt_money(MIN_BET)}")
        return
    ok, _ = reserve_bet(message.from_user.id, bet)
    await state.clear()
    if not ok:
        await message.answer("Недостаточно средств.")
        return
    GOLD_GAMES[message.from_user.id] = {"bet": bet, "step": 0}
    await message.answer(gold_text(GOLD_GAMES[message.from_user.id]), reply_markup=gold_kb())

@dp.callback_query(F.data.startswith("gold:pick:"))
async def gold_pick(query: CallbackQuery):
    user_id = query.from_user.id
    game = GOLD_GAMES.get(user_id)
    if not game:
        await query.answer("Нет активной игры", show_alert=True)
        return
    if not check_cooldown(user_id):
        await query.answer("⏳ Подождите", show_alert=True)
        return
    chosen = int(query.data.split(":")[-1])
    trap = random.randint(1, 4)
    if chosen == trap:
        bet = game["bet"]
        balance = finalize_reserved_bet(user_id, bet, 0.0, "gold", "lose")
        GOLD_GAMES.pop(user_id, None)
        await query.message.edit_text(f"💥 <b>Золото</b>\nЛовушка в плитке {trap}.\nПотеряно: {fmt_money(bet)}\nБаланс: {fmt_money(balance)}")
        await query.answer()
        return
    game["step"] += 1
    step = game["step"]
    if step >= len(GOLD_MULTIPLIERS):
        bet = game["bet"]
        payout = round(bet * GOLD_MULTIPLIERS[-1], 2)
        balance = finalize_reserved_bet(user_id, bet, payout, "gold", "max_step")
        GOLD_GAMES.pop(user_id, None)
        await query.message.edit_text(f"🏁 <b>Золото</b>\nТы прошел все раунды.\nВыплата: {fmt_money(payout)}\nБаланс: {fmt_money(balance)}")
        await query.answer()
        return
    await query.message.edit_text(gold_text(game), reply_markup=gold_kb())
    await query.answer("Успех")

@dp.callback_query(F.data == "gold:cash")
async def gold_cash(query: CallbackQuery):
    user_id = query.from_user.id
    game = GOLD_GAMES.get(user_id)
    if not game:
        await query.answer("Нет активной игры", show_alert=True)
        return
    step = game["step"]
    bet = game["bet"]
    if step <= 0:
        await query.answer("Сначала сделай минимум 1 ход", show_alert=True)
        return
    mult = GOLD_MULTIPLIERS[step - 1]
    payout = round(bet * mult, 2)
    balance = finalize_reserved_bet(user_id, bet, payout, "gold", f"cashout_step={step}")
    GOLD_GAMES.pop(user_id, None)
    await query.message.edit_text(f"✅ <b>Золото: выигрыш</b>\nРаунд: {step}\nМножитель: x{mult:.2f}\nВыплата: {fmt_money(payout)}\nБаланс: {fmt_money(balance)}")
    await query.answer()

@dp.callback_query(F.data == "gold:cancel")
async def gold_cancel(query: CallbackQuery):
    user_id = query.from_user.id
    game = GOLD_GAMES.get(user_id)
    if not game:
        await query.answer("Нет активной игры", show_alert=True)
        return
    step = game["step"]
    bet = game["bet"]
    payout = bet if step == 0 else 0.0
    outcome = "cancel_refund" if step == 0 else "cancel_lose"
    balance = finalize_reserved_bet(user_id, bet, payout, "gold", outcome)
    GOLD_GAMES.pop(user_id, None)
    await query.message.edit_text(f"❌ <b>Золото завершено</b>\nВозврат: {fmt_money(payout)}\nБаланс: {fmt_money(balance)}")
    await query.answer()

# ----------------------------- DIAMONDS -----------------------------
def diamond_text(game: Dict[str, Any]) -> str:
    step = game["step"]
    bet = game["bet"]
    cur_mult = DIAMOND_MULTIPLIERS[step - 1] if step > 0 else 0
    cur_win = bet * cur_mult if step > 0 else 0
    next_mult = DIAMOND_MULTIPLIERS[step] if step < len(DIAMOND_MULTIPLIERS) else DIAMOND_MULTIPLIERS[-1]
    return (f"💎 <b>Алмазы</b>\nСтавка: {fmt_money(bet)}\nШаг: {step}\nТекущий множитель: x{cur_mult:.2f}\nПотенциально сейчас: {fmt_money(cur_win)}\nСледующий шаг: x{next_mult:.2f}\n\nВыбери кристалл (один из них бракованный).")

@dp.message(DiamondStates.waiting_amount)
async def diamond_start_amount(message: Message, state: FSMContext):
    try:
        bet = parse_amount(message.text)
    except:
        await message.answer("Введи корректную ставку.")
        return
    if bet < MIN_BET:
        await message.answer(f"Минимальная ставка: {fmt_money(MIN_BET)}")
        return
    ok, _ = reserve_bet(message.from_user.id, bet)
    await state.clear()
    if not ok:
        await message.answer("Недостаточно средств.")
        return
    DIAMOND_GAMES[message.from_user.id] = {"bet": bet, "step": 0}
    await message.answer(diamond_text(DIAMOND_GAMES[message.from_user.id]), reply_markup=diamond_kb())

@dp.callback_query(F.data.startswith("diamond:pick:"))
async def diamond_pick(query: CallbackQuery):
    user_id = query.from_user.id
    game = DIAMOND_GAMES.get(user_id)
    if not game:
        await query.answer("Нет активной игры", show_alert=True)
        return
    if not check_cooldown(user_id):
        await query.answer("⏳ Подождите", show_alert=True)
        return
    chosen = int(query.data.split(":")[-1])
    trap = random.randint(1, 5)
    if chosen == trap:
        bet = game["bet"]
        balance = finalize_reserved_bet(user_id, bet, 0.0, "diamonds", "lose")
        DIAMOND_GAMES.pop(user_id, None)
        await query.message.edit_text(f"💥 <b>Алмазы</b>\nБракованный кристалл: {trap}.\nПотеряно: {fmt_money(bet)}\nБаланс: {fmt_money(balance)}")
        await query.answer()
        return
    game["step"] += 1
    step = game["step"]
    if step >= len(DIAMOND_MULTIPLIERS):
        bet = game["bet"]
        payout = round(bet * DIAMOND_MULTIPLIERS[-1], 2)
        balance = finalize_reserved_bet(user_id, bet, payout, "diamonds", "max_step")
        DIAMOND_GAMES.pop(user_id, None)
        await query.message.edit_text(f"🏁 <b>Алмазы</b>\nМаксимум шагов пройден.\nВыплата: {fmt_money(payout)}\nБаланс: {fmt_money(balance)}")
        await query.answer()
        return
    await query.message.edit_text(diamond_text(game), reply_markup=diamond_kb())
    await query.answer("Успех")

@dp.callback_query(F.data == "diamond:cash")
async def diamond_cash(query: CallbackQuery):
    user_id = query.from_user.id
    game = DIAMOND_GAMES.get(user_id)
    if not game:
        await query.answer("Нет активной игры", show_alert=True)
        return
    step = game["step"]
    bet = game["bet"]
    if step <= 0:
        await query.answer("Сначала сделай минимум 1 шаг", show_alert=True)
        return
    mult = DIAMOND_MULTIPLIERS[step - 1]
    payout = round(bet * mult, 2)
    balance = finalize_reserved_bet(user_id, bet, payout, "diamonds", f"cashout_step={step}")
    DIAMOND_GAMES.pop(user_id, None)
    await query.message.edit_text(f"✅ <b>Алмазы: выигрыш</b>\nШаг: {step}\nМножитель: x{mult:.2f}\nВыплата: {fmt_money(payout)}\nБаланс: {fmt_money(balance)}")
    await query.answer()

@dp.callback_query(F.data == "diamond:cancel")
async def diamond_cancel(query: CallbackQuery):
    user_id = query.from_user.id
    game = DIAMOND_GAMES.get(user_id)
    if not game:
        await query.answer("Нет активной игры", show_alert=True)
        return
    step = game["step"]
    bet = game["bet"]
    payout = bet if step == 0 else 0.0
    outcome = "cancel_refund" if step == 0 else "cancel_lose"
    balance = finalize_reserved_bet(user_id, bet, payout, "diamonds", outcome)
    DIAMOND_GAMES.pop(user_id, None)
    await query.message.edit_text(f"❌ <b>Алмазы завершены</b>\nВозврат: {fmt_money(payout)}\nБаланс: {fmt_money(balance)}")
    await query.answer()

# ----------------------------- MINES -----------------------------
def mines_multiplier(opened_count: int, mines_count: int) -> float:
    if opened_count <= 0:
        return 1.0
    safe_cells = 9 - mines_count
    base = 9.0 / max(1.0, safe_cells)
    mult = (base ** opened_count) * 0.95
    return round(mult, 2)

def mines_text(game: Dict[str, Any]) -> str:
    bet = game["bet"]
    opened_count = len(game["opened"])
    mines_count = game["mines_count"]
    mult = mines_multiplier(opened_count, mines_count)
    potential = round(bet * mult, 2)
    return (f"💣 <b>Мины</b>\n<blockquote>Ставка: {fmt_money(bet)}\nМин: {mines_count}\nОткрыто безопасных: {opened_count}\nТекущий множитель: x{mult:.2f}\nПотенциально сейчас: {fmt_money(potential)}</blockquote>\n\n<i>Открывай клетки или забирай выигрыш.</i>")

@dp.callback_query(F.data == "mines:noop")
async def mines_noop(query: CallbackQuery):
    await query.answer()

@dp.message(MinesStates.waiting_amount)
async def mines_amount(message: Message, state: FSMContext):
    try:
        bet = parse_amount(message.text)
    except:
        await message.answer("Введи корректную ставку.")
        return
    if bet < MIN_BET:
        await message.answer(f"Минимальная ставка: {fmt_money(MIN_BET)}")
        return
    await state.update_data(bet=bet)
    await state.set_state(MinesStates.waiting_mines)
    await message.answer("Сколько мин на поле 3x3? (1-5)")

@dp.message(MinesStates.waiting_mines)
async def mines_count_msg(message: Message, state: FSMContext):
    data = await state.get_data()
    bet = float(data.get("bet", 0) or 0)
    try:
        mines_count = parse_int(message.text)
    except:
        await message.answer("Введи число от 1 до 5.")
        return
    if mines_count < 1 or mines_count > 5:
        await message.answer("Количество мин должно быть от 1 до 5.")
        return
    ok, _ = reserve_bet(message.from_user.id, bet)
    await state.clear()
    if not ok:
        await message.answer("Недостаточно средств.")
        return
    cells = list(range(1, 10))
    mines = set(random.sample(cells, mines_count))
    MINES_GAMES[message.from_user.id] = {"bet": bet, "mines_count": mines_count, "mines": mines, "opened": set()}
    game = MINES_GAMES[message.from_user.id]
    await message.answer(mines_text(game), reply_markup=mines_kb(game))

@dp.callback_query(F.data.startswith("mines:cell:"))
async def mines_cell(query: CallbackQuery):
    user_id = query.from_user.id
    game = MINES_GAMES.get(user_id)
    if not game:
        await query.answer("Нет активной игры", show_alert=True)
        return
    if not check_cooldown(user_id):
        await query.answer("⏳ Подождите", show_alert=True)
        return
    idx = int(query.data.split(":")[-1])
    if idx in game["opened"]:
        await query.answer("Клетка уже открыта", show_alert=True)
        return
    if idx in game["mines"]:
        bet = game["bet"]
        balance = finalize_reserved_bet(user_id, bet, 0.0, "mines", "explode")
        await query.message.edit_text(f"💥 <b>Мины</b>\n<blockquote>Ты попал на мину в клетке {idx}.\nПотеряно: {fmt_money(bet)}\nБаланс: {fmt_money(balance)}</blockquote>", reply_markup=mines_kb(game, reveal_all=True))
        MINES_GAMES.pop(user_id, None)
        await query.answer()
        return
    game["opened"].add(idx)
    safe_opened = len(game["opened"])
    safe_total = 9 - game["mines_count"]
    if safe_opened >= safe_total:
        bet = game["bet"]
        mult = mines_multiplier(safe_opened, game["mines_count"])
        payout = round(bet * mult, 2)
        balance = finalize_reserved_bet(user_id, bet, payout, "mines", "cleared_all")
        await query.message.edit_text(f"🏁 <b>Мины</b>\n<blockquote>Все безопасные клетки открыты.\nМножитель: x{mult:.2f}\nВыплата: {fmt_money(payout)}\nБаланс: {fmt_money(balance)}</blockquote>", reply_markup=mines_kb(game, reveal_all=True))
        MINES_GAMES.pop(user_id, None)
        await query.answer()
        return
    await query.message.edit_text(mines_text(game), reply_markup=mines_kb(game))
    await query.answer("Безопасно")

@dp.callback_query(F.data == "mines:cash")
async def mines_cash(query: CallbackQuery):
    user_id = query.from_user.id
    game = MINES_GAMES.get(user_id)
    if not game:
        await query.answer("Нет активной игры", show_alert=True)
        return
    bet = game["bet"]
    safe_opened = len(game["opened"])
    mines_count = game["mines_count"]
    if safe_opened <= 0:
        await query.answer("Сначала открой хотя бы 1 клетку", show_alert=True)
        return
    mult = mines_multiplier(safe_opened, mines_count)
    payout = round(bet * mult, 2)
    balance = finalize_reserved_bet(user_id, bet, payout, "mines", f"cashout_{safe_opened}")
    await query.message.edit_text(f"✅ <b>Мины: выигрыш</b>\n<blockquote>Открыто безопасных: {safe_opened}\nМножитель: x{mult:.2f}\nВыплата: {fmt_money(payout)}\nБаланс: {fmt_money(balance)}</blockquote>", reply_markup=mines_kb(game, reveal_all=True))
    MINES_GAMES.pop(user_id, None)
    await query.answer()

@dp.callback_query(F.data == "mines:cancel")
async def mines_cancel(query: CallbackQuery):
    user_id = query.from_user.id
    game = MINES_GAMES.get(user_id)
    if not game:
        await query.answer("Нет активной игры", show_alert=True)
        return
    bet = game["bet"]
    safe_opened = len(game["opened"])
    mines_count = game["mines_count"]
    if safe_opened <= 0:
        payout = bet
        outcome = "cancel_refund"
    else:
        payout = round(bet * mines_multiplier(safe_opened, mines_count), 2)
        outcome = f"cancel_cashout_{safe_opened}"
    balance = finalize_reserved_bet(user_id, bet, payout, "mines", outcome)
    await query.message.edit_text(f"❌ <b>Мины завершены</b>\nВыплата: {fmt_money(payout)}\nБаланс: {fmt_money(balance)}", reply_markup=mines_kb(game, reveal_all=True))
    MINES_GAMES.pop(user_id, None)
    await query.answer()

# ----------------------------- OCHKO (BLACKJACK) -----------------------------
def make_deck() -> list:
    ranks = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
    suits = ["♠", "♥", "♦", "♣"]
    deck = [(r, s) for r in ranks for s in suits]
    random.shuffle(deck)
    return deck

def card_points(rank: str) -> int:
    if rank in {"J", "Q", "K"}:
        return 10
    if rank == "A":
        return 11
    return int(rank)

def hand_value(cards: list) -> int:
    total = sum(card_points(r) for r, _ in cards)
    aces = sum(1 for r, _ in cards if r == "A")
    while total > 21 and aces > 0:
        total -= 10
        aces -= 1
    return total

def format_hand(cards: list) -> str:
    return " ".join(f"{r}{s}" for r, s in cards)

def render_ochko_table(game: Dict[str, Any], reveal_dealer: bool) -> str:
    player_cards = game["player"]
    dealer_cards = game["dealer"]
    player_value = hand_value(player_cards)
    if reveal_dealer:
        dealer_line = f"{format_hand(dealer_cards)} ({hand_value(dealer_cards)})"
    else:
        first = f"{dealer_cards[0][0]}{dealer_cards[0][1]}"
        dealer_line = f"{first} ??"
    return f"🎴 <b>Очко</b>\nСтавка: {fmt_money(game['bet'])}\n\nДилер: {dealer_line}\nТы: {format_hand(player_cards)} ({player_value})"

@dp.message(OchkoStates.waiting_amount)
async def ochko_amount_msg(message: Message, state: FSMContext):
    try:
        bet = parse_amount(message.text)
    except:
        await message.answer("Введи корректную ставку.")
        return
    if bet < MIN_BET:
        await message.answer(f"Минимальная ставка: {fmt_money(MIN_BET)}")
        return
    await state.update_data(bet=bet)
    await state.set_state(OchkoStates.waiting_confirm)
    await message.answer(f"Ставка: {fmt_money(bet)}\nНачать игру?", reply_markup=ochko_confirm_kb())

@dp.callback_query(OchkoStates.waiting_confirm, F.data == "ochko:cancel")
async def ochko_cancel_before_start(query: CallbackQuery, state: FSMContext):
    await state.clear()
    await query.message.edit_text("❌ Игра отменена")
    await query.answer()

@dp.callback_query(OchkoStates.waiting_confirm, F.data == "ochko:start")
async def ochko_start_confirm(query: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    bet = float(data.get("bet", 0) or 0)
    if bet < MIN_BET:
        await state.clear()
        await query.answer("Ставка не найдена", show_alert=True)
        return
    if not check_cooldown(query.from_user.id):
        await query.answer("⏳ Подождите 2.5 секунды", show_alert=True)
        return
    ok, _ = reserve_bet(query.from_user.id, bet)
    await state.clear()
    if not ok:
        await query.message.edit_text("❌ Недостаточно средств для игры")
        await query.answer()
        return
    deck = make_deck()
    player = [deck.pop(), deck.pop()]
    dealer = [deck.pop(), deck.pop()]
    OCHKO_GAMES[query.from_user.id] = {"bet": bet, "deck": deck, "player": player, "dealer": dealer}
    game = OCHKO_GAMES[query.from_user.id]
    player_value = hand_value(player)
    dealer_value = hand_value(dealer)
    if player_value == 21:
        if dealer_value == 21:
            payout = bet
            outcome = "blackjack_push"
            text = f"Ничья по blackjack."
        else:
            payout = round(bet * 2.5, 2)
            outcome = "blackjack_win"
            text = "Blackjack!"
        balance = finalize_reserved_bet(query.from_user.id, bet, payout, "ochko", outcome)
        OCHKO_GAMES.pop(query.from_user.id, None)
        await query.message.edit_text(f"{render_ochko_table(game, reveal_dealer=True)}\n\n{text}\nВыплата: {fmt_money(payout)}\nБаланс: {fmt_money(balance)}")
        await query.answer()
        return
    await query.message.edit_text(render_ochko_table(game, reveal_dealer=False), reply_markup=ochko_kb())
    await query.answer()

@dp.callback_query(F.data == "ochko:hit")
async def ochko_hit(query: CallbackQuery):
    user_id = query.from_user.id
    game = OCHKO_GAMES.get(user_id)
    if not game:
        await query.answer("Нет активной игры", show_alert=True)
        return
    if not check_cooldown(user_id):
        await query.answer("⏳ Подождите", show_alert=True)
        return
    game["player"].append(game["deck"].pop())
    value = hand_value(game["player"])
    if value > 21:
        bet = game["bet"]
        balance = finalize_reserved_bet(user_id, bet, 0.0, "ochko", "bust")
        await query.message.edit_text(f"{render_ochko_table(game, reveal_dealer=True)}\n\nПеребор. Ты проиграл.\nБаланс: {fmt_money(balance)}")
        OCHKO_GAMES.pop(user_id, None)
        await query.answer()
        return
    await query.message.edit_text(render_ochko_table(game, reveal_dealer=False), reply_markup=ochko_kb())
    await query.answer()

@dp.callback_query(F.data == "ochko:stand")
async def ochko_stand(query: CallbackQuery):
    user_id = query.from_user.id
    game = OCHKO_GAMES.get(user_id)
    if not game:
        await query.answer("Нет активной игры", show_alert=True)
        return
    while hand_value(game["dealer"]) < 17:
        game["dealer"].append(game["deck"].pop())
    player_value = hand_value(game["player"])
    dealer_value = hand_value(game["dealer"])
    bet = game["bet"]
    if dealer_value > 21 or player_value > dealer_value:
        payout = round(bet * 2.0, 2)
        result_text = "Победа"
        outcome = "win"
    elif dealer_value == player_value:
        payout = round(bet, 2)
        result_text = "Ничья"
        outcome = "push"
    else:
        payout = 0.0
        result_text = "Поражение"
        outcome = "lose"
    balance = finalize_reserved_bet(user_id, bet, payout, "ochko", outcome)
    await query.message.edit_text(f"{render_ochko_table(game, reveal_dealer=True)}\n\nРезультат: {result_text}\nВыплата: {fmt_money(payout)}\nБаланс: {fmt_money(balance)}")
    OCHKO_GAMES.pop(user_id, None)
    await query.answer()

# ==================== АДМИН КОМАНДЫ ====================
@dp.message(Command("ban"))
async def admin_ban(message: Message):
    if not is_admin(message.from_user.id):
        return
    target = message.reply_to_message.from_user if message.reply_to_message else None
    if not target:
        parts = message.text.split()
        if len(parts) < 2:
            return await message.answer("❌ /ban @username или /ban 123456789")
        try:
            uid = int(parts[1])
            ban_user(uid)
            await message.answer(f"🚫 Пользователь {uid} забанен")
        except:
            await message.answer("❌ Неверный ID")
    else:
        ban_user(target.id)
        await message.answer(f"🚫 {mention_user(target.id, target.full_name)} забанен")

@dp.message(Command("unban"))
async def admin_unban(message: Message):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 2:
        return await message.answer("❌ /unban 123456789")
    try:
        uid = int(parts[1])
        unban_user(uid)
        await message.answer(f"✅ Пользователь {uid} разбанен")
    except:
        await message.answer("❌ Неверный ID")

@dp.message(Command("mute"))
async def admin_mute(message: Message):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 3:
        return await message.answer("❌ /mute @user 5")
    target = message.reply_to_message.from_user if message.reply_to_message else None
    if not target:
        try:
            uid = int(parts[1])
            minutes = int(parts[2])
            mute_user(uid, minutes)
            await message.answer(f"🔇 Пользователь {uid} замьючен на {minutes} мин")
        except:
            await message.answer("❌ Неверный ID")
    else:
        minutes = int(parts[1])
        mute_user(target.id, minutes)
        await message.answer(f"🔇 {mention_user(target.id, target.full_name)} замьючен на {minutes} мин")

@dp.message(Command("unmute"))
async def admin_unmute(message: Message):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 2:
        return await message.answer("❌ /unmute 123456789")
    try:
        uid = int(parts[1])
        unmute_user(uid)
        await message.answer(f"✅ Пользователь {uid} размучен")
    except:
        await message.answer("❌ Неверный ID")

@dp.message(Command("выдать"))
async def admin_give(message: Message):
    if not is_admin(message.from_user.id):
        return
    target = message.reply_to_message.from_user if message.reply_to_message else None
    if not target:
        parts = message.text.split()
        if len(parts) < 3:
            return await message.answer("❌ /выдать @user 1000")
        try:
            amount = parse_amount(parts[2])
            if parts[1].startswith("@"):
                user = await message.bot.get_chat(parts[1])
                uid = user.id
            else:
                uid = int(parts[1])
        except:
            return await message.answer("❌ Неверные данные")
    else:
        try:
            amount = parse_amount(parts[1]) if len(parts) > 1 else 0
            uid = target.id
        except:
            return await message.answer("❌ Неверная сумма")
    if amount <= 0:
        return await message.answer("❌ Сумма должна быть положительной")
    bal = add_balance(uid, amount)
    await message.answer(f"✅ Выдано {fmt_money(amount)} пользователю {mention_user(uid)}\nНовый баланс: {fmt_money(bal)}")

@dp.message(Command("stats"))
async def admin_stats(message: Message):
    if not is_admin(message.from_user.id):
        return
    conn = get_db()
    users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    bets = conn.execute("SELECT COUNT(*) FROM bets").fetchone()[0]
    payout = conn.execute("SELECT SUM(payout) FROM bets").fetchone()[0] or 0
    sys = conn.execute("SELECT coins FROM system_balance WHERE id=1").fetchone()
    conn.close()
    await message.answer(f"📊 <b>Статистика</b>\n\n👥 Пользователей: {users}\n🎲 Ставок: {bets}\n💰 Выплачено: {fmt_money(payout)}\n🏦 Комиссий собрано: {fmt_money(sys[0] if sys else 0)}")

@dp.message(Command("massbonus"))
async def admin_mass_bonus(message: Message):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) != 2:
        return await message.answer("❌ /massbonus 100")
    try:
        amount = parse_amount(parts[1])
    except:
        return await message.answer("❌ Неверная сумма")
    conn = get_db()
    conn.execute("UPDATE users SET coins = coins + ?", (amount,))
    conn.commit()
    conn.close()
    await message.answer(f"✅ Всем пользователям начислено по {fmt_money(amount)}!")

@dp.message(Command("broadcast"))
async def admin_broadcast(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    text = message.text.replace("/broadcast", "", 1).strip()
    if not text:
        await state.set_state(AdminBroadcastStates.waiting_message)
        return await message.answer("📢 Введите текст рассылки:")
    await state.clear()
    conn = get_db()
    users = conn.execute("SELECT id FROM users").fetchall()
    conn.close()
    sent = 0
    for row in users:
        try:
            await message.bot.send_message(int(row[0]), text, parse_mode="HTML")
            sent += 1
            await asyncio.sleep(0.05)
        except:
            pass
    await message.answer(f"📢 Рассылка завершена! Отправлено: {sent}")

@dp.message(AdminBroadcastStates.waiting_message)
async def broadcast_text(message: Message, state: FSMContext):
    text = message.text
    await state.clear()
    conn = get_db()
    users = conn.execute("SELECT id FROM users").fetchall()
    conn.close()
    sent = 0
    for row in users:
        try:
            await message.bot.send_message(int(row[0]), text, parse_mode="HTML")
            sent += 1
            await asyncio.sleep(0.05)
        except:
            pass
    await message.answer(f"📢 Рассылка завершена! Отправлено: {sent}")

# ==================== КОЛБЭКИ МЕНЮ ====================
@dp.callback_query(F.data == "check_subscription")
async def check_subscription_cb(query: CallbackQuery, bot: Bot):
    ok, not_subscribed = await check_subscriptions(query.from_user.id, bot)
    if ok:
        await query.message.edit_text("✅ Спасибо за подписку!", reply_markup=main_menu_kb())
    else:
        await query.message.edit_text("⚠️ Подпишитесь на каналы!", reply_markup=subscription_keyboard(not_subscribed))
    await query.answer()

@dp.callback_query(F.data == "menu:balance")
async def menu_balance_cb(query: CallbackQuery):
    user = get_user(query.from_user.id)
    await query.message.edit_text(f"💰 <b>Баланс</b>\n\n{fmt_money(float(user['coins']))}", reply_markup=main_menu_kb())
    await query.answer()

@dp.callback_query(F.data == "menu:games")
async def menu_games_cb(query: CallbackQuery):
    await query.message.edit_text("🎮 <b>Выберите игру</b>", reply_markup=games_kb())
    await query.answer()

@dp.callback_query(F.data == "menu:donate")
async def menu_donate_cb(query: CallbackQuery):
    await query.message.edit_text(f"⭐ <b>Пополнение</b>\n\n1 Star = {STARS_RATE} {CURRENCY_NAME}", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ 1 Star", callback_data="donate:1"), InlineKeyboardButton(text="⭐ 5 Stars", callback_data="donate:5")],
        [InlineKeyboardButton(text="⭐ 10 Stars", callback_data="donate:10"), InlineKeyboardButton(text="⭐ 50 Stars", callback_data="donate:50")],
        [InlineKeyboardButton(text="⭐ 100 Stars", callback_data="donate:100")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="menu:back")],
    ]))
    await query.answer()

@dp.callback_query(F.data == "menu:bank")
async def menu_bank_cb(query: CallbackQuery):
    user = get_user(query.from_user.id)
    summary = get_bank_summary(query.from_user.id)
    await query.message.edit_text(f"🏦 <b>Банк</b>\n\n💰 Баланс: {fmt_money(float(user['coins']))}\n📊 Активных депозитов: {summary['count']}\n💵 Сумма в депозитах: {fmt_money(summary['sum'])}\n\n📈 Ставки: 7д(+3%), 14д(+7%), 30д(+18%)", reply_markup=bank_kb())
    await query.answer()

@dp.callback_query(F.data == "menu:checks")
async def menu_checks_cb(query: CallbackQuery):
    await query.message.edit_text("🧾 <b>Чеки</b>", reply_markup=checks_kb())
    await query.answer()

@dp.callback_query(F.data == "menu:ref")
async def menu_ref_cb(query: CallbackQuery):
    link = f"https://t.me/{BOT_USERNAME}?start=ref_{query.from_user.id}"
    conn = get_db()
    count = conn.execute("SELECT COUNT(*) as c FROM referrals WHERE referrer_id = ?", (str(query.from_user.id),)).fetchone()["c"]
    conn.close()
    await query.message.edit_text(f"👥 <b>Реферальная программа</b>\n\n🔗 Ваша ссылка:\n<code>{link}</code>\n\n📊 Приглашено: {count}\n🎁 За друга: +{fmt_money(REFERRER_BONUS)} вам, +{fmt_money(REFERRED_BONUS)} другу", reply_markup=main_menu_kb())
    await query.answer()

@dp.callback_query(F.data == "menu:add_chat")
async def menu_add_chat_cb(query: CallbackQuery):
    link = f"https://t.me/{BOT_USERNAME}?startgroup=true"
    await query.message.answer(f"🤖 <b>Добавить бота в чат</b>\n\nНажмите на кнопку ниже:\n\n<a href='{link}'>➕ Добавить {BOT_USERNAME} в чат</a>", disable_web_page_preview=True, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="menu:back")]]))
    await query.answer()

@dp.callback_query(F.data == "menu:help")
async def menu_help_cb(query: CallbackQuery):
    await query.message.edit_text(get_help_text(), reply_markup=main_menu_kb())
    await query.answer()

@dp.callback_query(F.data == "menu:back")
async def menu_back_cb(query: CallbackQuery):
    user = get_user(query.from_user.id)
    await query.message.edit_text(f"🎮 <b>{CURRENCY_NAME}</b>\nБаланс: {fmt_money(float(user['coins']))}", reply_markup=main_menu_kb())
    await query.answer()

@dp.callback_query(F.data.startswith("donate:"))
async def donate_pay_cb(query: CallbackQuery, bot: Bot):
    stars = int(query.data.split(":")[1])
    await bot.send_invoice(
        chat_id=query.from_user.id,
        title=f"Покупка {CURRENCY_NAME}",
        description=f"{stars} Stars → {stars * STARS_RATE} {CURRENCY_NAME}",
        payload=f"stars_{stars}_{query.from_user.id}",
        provider_token="",
        currency="XTR",
        prices=[{"label": f"{stars} Stars", "amount": stars}],
    )
    await query.answer()

@dp.pre_checkout_query()
async def pre_checkout(pre_checkout_query: PreCheckoutQuery, bot: Bot):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@dp.message(F.successful_payment)
async def successful_payment(message: Message):
    payload = message.successful_payment.invoice_payload
    parts = payload.split("_")
    stars = int(parts[1])
    user_id = int(parts[2])
    amount = stars * STARS_RATE
    add_balance(user_id, amount)
    await message.answer(f"✅ Пополнено! +{fmt_money(amount)}")

@dp.callback_query(F.data.startswith("game:"))
async def game_info_cb(query: CallbackQuery):
    game = query.data.split(":")[1]
    examples = {
        "tower": "башня 100", "gold": "золото 100", "diamond": "алмазы 100",
        "mines": "мины 100 3", "roulette": "рул 100 красное", "crash": "краш 100 2.5",
        "cube": "кубик 100 5", "dice": "кости 100 м", "ochko": "очко 100",
        "football": "футбол 100", "basket": "баскет 100"
    }
    await query.message.answer(f"📝 Пример: <code>{examples.get(game)}</code>")
    await query.answer()

# ==================== ОТМЕНА ====================
@dp.message(lambda m: normalize_text(m.text) in {"отмена", "/cancel"})
async def cancel_cmd(message: Message, state: FSMContext):
    await state.clear()
    TOWER_GAMES.pop(message.from_user.id, None)
    GOLD_GAMES.pop(message.from_user.id, None)
    DIAMOND_GAMES.pop(message.from_user.id, None)
    MINES_GAMES.pop(message.from_user.id, None)
    OCHKO_GAMES.pop(message.from_user.id, None)
    await message.answer("🛑 Действие отменено")

# ==================== ЗАПУСК ====================
async def main():
    init_db()
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await bot.delete_webhook(drop_pending_updates=True)
    print("✅ Бот VIRTEX успешно запущен!")
    print(f"👑 Админы: {ADMIN_IDS}")
    print(f"🎮 Доступно игр: 11")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
