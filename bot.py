import asyncio
import random
import sqlite3
import time
import json
import string
from datetime import datetime
from aiogram import Bot, Dispatcher, F, BaseMiddleware
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, PreCheckoutQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

# ==================== КОНФИГ ====================
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
RED_NUMBERS = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
TOWER_MULTIPLIERS = [1.20, 1.48, 1.86, 2.35, 2.95, 3.75, 4.85, 6.15]
GOLD_MULTIPLIERS = [1.15, 1.35, 1.62, 2.0, 2.55, 3.25, 4.2]
DIAMOND_MULTIPLIERS = [1.12, 1.28, 1.48, 1.72, 2.02, 2.4, 2.92, 3.6]

DB_PATH = "data.db"

# ==================== СОЗДАНИЕ БД ====================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, coins REAL DEFAULT 5000, GGs INTEGER DEFAULT 0, lost_coins REAL DEFAULT 0, won_coins REAL DEFAULT 0, status INTEGER DEFAULT 0, checks TEXT DEFAULT '[]');
        CREATE TABLE IF NOT EXISTS bets (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, bet_amount REAL, choice TEXT, outcome TEXT, win INTEGER, payout REAL, ts INTEGER);
        CREATE TABLE IF NOT EXISTS json_data (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS checks (code TEXT PRIMARY KEY, creator_id TEXT, per_user REAL, remaining INTEGER, claimed TEXT, password TEXT);
        CREATE TABLE IF NOT EXISTS promos (name TEXT PRIMARY KEY, reward REAL, claimed TEXT, remaining_activations INTEGER);
        CREATE TABLE IF NOT EXISTS bank_deposits (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, principal REAL, rate REAL, term_days INTEGER, opened_at INTEGER, status TEXT, closed_at INTEGER);
        CREATE TABLE IF NOT EXISTS referrals (id INTEGER PRIMARY KEY AUTOINCREMENT, referrer_id TEXT NOT NULL, referred_id TEXT NOT NULL, reward_amount REAL NOT NULL, created_ts INTEGER NOT NULL, UNIQUE(referred_id));
        CREATE TABLE IF NOT EXISTS banned_users (user_id TEXT PRIMARY KEY, banned_at INTEGER NOT NULL, reason TEXT);
        CREATE TABLE IF NOT EXISTS muted_users (user_id TEXT PRIMARY KEY, muted_until INTEGER NOT NULL, reason TEXT);
        CREATE TABLE IF NOT EXISTS system_balance (id INTEGER PRIMARY KEY CHECK (id = 1), coins REAL NOT NULL DEFAULT 0);
    ''')
    conn.execute("INSERT OR IGNORE INTO system_balance (id, coins) VALUES (1, 0)")
    conn.commit()
    conn.close()

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def now_ts():
    return int(time.time())

def fmt_money(value):
    value = round(float(value), 2)
    if value >= 1000:
        return f"{value/1000:.1f}k {CURRENCY_NAME}"
    return f"{value:.2f} {CURRENCY_NAME}"

def fmt_left(seconds):
    seconds = max(0, int(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h}ч {m}м"
    if m > 0:
        return f"{m}м {s}с"
    return f"{s}с"

def escape_html(text):
    return str(text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def mention_user(user_id, name=None):
    label = escape_html(name or f"Игрок {user_id}")
    return f'<a href="tg://user?id={int(user_id)}">{label}</a>'

def is_admin(user_id):
    return int(user_id) in ADMIN_IDS

def parse_amount(text):
    raw = str(text).strip().lower().replace(",", ".").replace(" ", "")
    mult = 1000 if raw.endswith(("k", "к")) else 1
    if mult > 1:
        raw = raw[:-1]
    value = float(raw) * mult
    if value <= 0:
        raise ValueError()
    return round(value, 2)

def normalize_text(text):
    return (text or "").lower().strip()

def ensure_user(user_id):
    conn = get_db()
    conn.execute("INSERT OR IGNORE INTO users (id, coins, GGs, lost_coins, won_coins, status, checks) VALUES (?, ?, 0, 0, 0, 0, '[]')", 
                 (str(user_id), START_BALANCE))
    conn.commit()
    conn.close()

def get_user(user_id):
    ensure_user(user_id)
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (str(user_id),)).fetchone()
    conn.close()
    return row

def add_balance(user_id, amount):
    conn = get_db()
    ensure_user(user_id)
    conn.execute("UPDATE users SET coins = coins + ? WHERE id = ?", (round(amount, 2), str(user_id)))
    row = conn.execute("SELECT coins FROM users WHERE id = ?", (str(user_id),)).fetchone()
    conn.commit()
    conn.close()
    return float(row["coins"])

def set_balance(user_id, amount):
    conn = get_db()
    ensure_user(user_id)
    conn.execute("UPDATE users SET coins = ? WHERE id = ?", (round(amount, 2), str(user_id)))
    conn.commit()
    conn.close()

# ==================== ПРОВЕРКА ПОДПИСКИ ====================
async def check_subscriptions(user_id, bot):
    not_subscribed = []
    for channel in REQUIRED_CHANNELS:
        try:
            member = await bot.get_chat_member(chat_id=channel["chat_id"], user_id=user_id)
            if member.status in ["left", "kicked"]:
                not_subscribed.append(channel)
        except:
            not_subscribed.append(channel)
    return len(not_subscribed) == 0, not_subscribed

def subscription_keyboard(not_subscribed):
    builder = InlineKeyboardBuilder()
    for ch in not_subscribed:
        builder.button(text=f"📢 Подписаться", url=ch["url"])
    builder.button(text="✅ Проверить подписку", callback_data="check_subscription")
    builder.adjust(1)
    return builder.as_markup()

# ==================== ЗАЩИТА ОТ СПАМА ====================
user_cooldown = {}

def check_cooldown(user_id):
    now = time.time()
    last = user_cooldown.get(user_id, 0)
    if now - last < GAME_COOLDOWN:
        return False
    user_cooldown[user_id] = now
    return True

# ==================== MIDDLEWARE ====================
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

class BanMuteSubscriptionMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: Message, data: dict):
        user_id = event.from_user.id
        
        conn = get_db()
        banned = conn.execute("SELECT 1 FROM banned_users WHERE user_id = ?", (str(user_id),)).fetchone()
        conn.close()
        if banned:
            await event.answer("🚫 Вы забанены")
            return
        
        if event.text and any(word in event.text.lower() for word in ["краш", "рул", "баскет", "футбол", "дартс", "боулинг", "кубик", "слоты", "очко", "башня", "золото", "алмазы", "мины", "игры", "пер"]):
            ok, not_subscribed = await check_subscriptions(user_id, data["bot"])
            if not ok:
                await event.answer("⚠️ Подпишитесь на каналы!", reply_markup=subscription_keyboard(not_subscribed))
                return
        
        conn = get_db()
        muted = conn.execute("SELECT muted_until FROM muted_users WHERE user_id = ?", (str(user_id),)).fetchone()
        conn.close()
        if muted and muted["muted_until"] > now_ts():
            await event.answer(f"⏳ Вы в муте до {fmt_left(muted['muted_until'] - now_ts())}")
            return
        
        return await handler(event, data)

dp.message.middleware(BanMuteSubscriptionMiddleware())

# ==================== БАЗОВЫЕ ФУНКЦИИ СТАВОК ====================
def settle_instant_bet(user_id, bet, payout, choice, outcome):
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

def reserve_bet(user_id, bet):
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

def finalize_reserved_bet(user_id, bet, payout, choice, outcome):
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
def transfer_coins(from_id, to_id, amount):
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
def ban_user(user_id):
    conn = get_db()
    try:
        conn.execute("INSERT OR REPLACE INTO banned_users (user_id, banned_at, reason) VALUES (?, ?, '')", (str(user_id), now_ts()))
        conn.commit()
        return True
    except:
        return False
    finally:
        conn.close()

def unban_user(user_id):
    conn = get_db()
    try:
        conn.execute("DELETE FROM banned_users WHERE user_id = ?", (str(user_id),))
        conn.commit()
        return True
    except:
        return False
    finally:
        conn.close()

def mute_user(user_id, minutes):
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

def unmute_user(user_id):
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

def create_check_atomic(user_id, per_user, count):
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

def claim_check_atomic(user_id, code):
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
def create_promo(code, reward, activations):
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO promos (name, reward, claimed, remaining_activations) VALUES (?, ?, '[]', ?)",
                 (code.upper(), round(reward, 2), activations))
    conn.commit()
    conn.close()

def redeem_promo_atomic(user_id, code):
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
def add_deposit(user_id, amount, term_days):
    rate = BANK_TERMS.get(term_days)
    if not rate:
        return False, "Неверный срок"
    ok, _ = reserve_bet(user_id, amount)
    if not ok:
        return False, f"Недостаточно средств. Ваш баланс: {fmt_money(get_user(user_id)['coins'])}"
    conn = get_db()
    conn.execute("INSERT INTO bank_deposits (user_id, principal, rate, term_days, opened_at, status) VALUES (?, ?, ?, ?, ?, 'active')",
                 (str(user_id), round(amount, 2), rate, term_days, now_ts()))
    conn.commit()
    conn.close()
    return True, f"Депозит открыт! Сумма: {fmt_money(amount)} на {term_days} дней"

def withdraw_matured_deposits(user_id):
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

def get_bank_summary(user_id):
    conn = get_db()
    active = conn.execute("SELECT COUNT(*) as c, COALESCE(SUM(principal),0) as s FROM bank_deposits WHERE user_id=? AND status='active'", (str(user_id),)).fetchone()
    conn.close()
    return {"count": active["c"], "sum": active["s"]}

# ==================== ТЕКСТ ПОМОЩИ И КЛАВИАТУРЫ ====================
def get_help_text():
    return """
<b>🎮 ИГРОВОЙ БОТ VIRTEX</b>

<b>💰 БАЛАНС И БОНУСЫ</b>
• <code>б</code> или <code>баланс</code> - показать баланс
• <code>профиль</code> - статистика
• <code>бонус</code> - получить бонус

<b>🎲 ВСЕ ИГРЫ</b>
• <code>краш 100 2.5</code> - Краш
• <code>рул 100 красное</code> - Рулетка
• <code>баскет 100</code> - Баскетбол
• <code>футбол 100 гол</code> - Футбол
• <code>дартс 100</code> - Дартс
• <code>боулинг 100</code> - Боулинг
• <code>кубик 100 5</code> - Кубик
• <code>слоты 100</code> - Слоты
• <code>очко 100</code> - Очко (21)
• <code>башня 100</code> - Башня
• <code>золото 100</code> - Золото
• <code>алмазы 100</code> - Алмазы
• <code>мины 100 3</code> - Мины

<b>💸 ПЕРЕВОДЫ</b>
• <code>пер @username 100</code> - комиссия 5%

<b>⭐ ПОПОЛНЕНИЕ</b>
• <code>/donate</code> - купить VIRTEX за Stars (1 Star = 3000)

<b>🏦 БАНК</b>
• <code>банк</code> - депозиты под 3-18%

<b>🧾 ЧЕКИ</b>
• <code>чеки</code> - создать/активировать чек

<b>🎟 ПРОМОКОДЫ</b>
• <code>промо КОД</code> - активировать промокод

<b>👥 РЕФЕРАЛЫ</b>
• <code>/ref</code> - реферальная ссылка
• За друга: +5000 вам, +2500 другу

<b>❓ ПОМОЩЬ</b>
• <code>помощь</code> - это меню
"""

def main_menu_kb():
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

def games_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📈 Краш", callback_data="game:crash"), InlineKeyboardButton(text="🎡 Рулетка", callback_data="game:roulette")],
        [InlineKeyboardButton(text="🏀 Баскет", callback_data="game:basket"), InlineKeyboardButton(text="⚽ Футбол", callback_data="game:football")],
        [InlineKeyboardButton(text="🎯 Дартс", callback_data="game:darts"), InlineKeyboardButton(text="🎳 Боулинг", callback_data="game:bowling")],
        [InlineKeyboardButton(text="🎲 Кубик", callback_data="game:dice"), InlineKeyboardButton(text="🎰 Слоты", callback_data="game:slots")],
        [InlineKeyboardButton(text="🗼 Башня", callback_data="game:tower"), InlineKeyboardButton(text="🥇 Золото", callback_data="game:gold")],
        [InlineKeyboardButton(text="💎 Алмазы", callback_data="game:diamond"), InlineKeyboardButton(text="💣 Мины", callback_data="game:mines")],
        [InlineKeyboardButton(text="🎴 Очко", callback_data="game:blackjack"), InlineKeyboardButton(text="🔙 Назад", callback_data="menu:back")],
    ])

def checks_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать чек", callback_data="checks:create")],
        [InlineKeyboardButton(text="💸 Активировать чек", callback_data="checks:claim")],
        [InlineKeyboardButton(text="📄 Мои чеки", callback_data="checks:my")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="menu:back")],
    ])

def bank_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Открыть депозит", callback_data="bank:open")],
        [InlineKeyboardButton(text="📜 Мои депозиты", callback_data="bank:list")],
        [InlineKeyboardButton(text="💰 Снять зрелые", callback_data="bank:withdraw")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="menu:back")],
    ])

def bank_terms_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="7 дней (+3%)", callback_data="bank:term:7")],
        [InlineKeyboardButton(text="14 дней (+7%)", callback_data="bank:term:14")],
        [InlineKeyboardButton(text="30 дней (+18%)", callback_data="bank:term:30")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="bank:term:cancel")],
    ])

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

class AdminBroadcastStates(StatesGroup):
    waiting_message = State()

# ==================== КОМАНДЫ СТАРТ И ПОМОЩЬ ====================
@dp.message(CommandStart())
async def start_cmd(message: Message, bot: Bot):
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

# ==================== КОМАНДЫ БАЛАНСА ====================
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
    await message.answer("🎮 <b>Игры</b>", reply_markup=games_kb())

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
@dp.message(lambda m: normalize_text(m.text) in {"чеки", "/checks"})
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

# ==================== БАНК ====================
@dp.message(lambda m: normalize_text(m.text) in {"банк", "/bank"})
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

# ==================== ВСЕ ИГРЫ ====================

# КРАШ
@dp.message(lambda m: m.text and m.text.lower().startswith("краш"))
async def game_crash(message: Message):
    if not check_cooldown(message.from_user.id):
        return await message.answer("⏳ Подождите 2.5 секунды")
    parts = message.text.split()
    if len(parts) != 3:
        return await message.answer("❌ Формат: `краш 100 2.5`")
    try:
        bet = parse_amount(parts[1])
        target = float(parts[2])
    except:
        return await message.answer("❌ Неверные данные")
    user_id = message.from_user.id
    balance = get_user(user_id)["coins"]
    if bet < MIN_BET:
        return await message.answer(f"❌ Минимальная ставка: {fmt_money(MIN_BET)}")
    if bet > balance:
        return await message.answer(f"❌ Недостаточно средств")
    rolled = round(random.uniform(1.0, 10.0), 2)
    win = target <= rolled
    payout = bet * target if win else 0
    ok, bal = settle_instant_bet(user_id, bet, payout, "crash", f"rolled={rolled}")
    if not ok:
        return await message.answer(f"❌ Ошибка")
    await message.answer(f"📈 <b>Краш</b>\n🎯 Ваш: x{target}\n💥 Игра: x{rolled}\n{'✅ ПОБЕДА! +' + fmt_money(payout) if win else '❌ ПОРАЖЕНИЕ'}\n💰 Баланс: {fmt_money(bal)}")

# РУЛЕТКА
@dp.message(lambda m: m.text and m.text.lower().startswith("рул"))
async def game_roulette(message: Message):
    if not check_cooldown(message.from_user.id):
        return await message.answer("⏳ Подождите 2.5 секунды")
    parts = message.text.split()
    if len(parts) != 3:
        return await message.answer("❌ Формат: `рул 100 красное`")
    try:
        bet = parse_amount(parts[1])
    except:
        return await message.answer("❌ Неверная ставка")
    choice = parts[2].lower()
    valid = ["красное", "черное", "чет", "нечет"]
    if choice not in valid:
        return await message.answer("❌ Выберите: красное, черное, чет, нечет")
    user_id = message.from_user.id
    balance = get_user(user_id)["coins"]
    if bet < MIN_BET:
        return await message.answer(f"❌ Минимальная ставка: {fmt_money(MIN_BET)}")
    if bet > balance:
        return await message.answer(f"❌ Недостаточно средств")
    num = random.randint(0, 36)
    if num == 0:
        color = "zero"
    else:
        color = "красное" if num in RED_NUMBERS else "черное"
    win = False
    if choice == "красное" and color == "красное":
        win = True
    elif choice == "черное" and color == "черное":
        win = True
    elif choice == "чет" and num != 0 and num % 2 == 0:
        win = True
    elif choice == "нечет" and num != 0 and num % 2 == 1:
        win = True
    payout = bet * 2 if win else 0
    ok, bal = settle_instant_bet(user_id, bet, payout, "roulette", f"num={num}")
    if not ok:
        return await message.answer(f"❌ Ошибка")
    await message.answer(f"🎡 <b>Рулетка</b>\n🎲 Выпало: {num} ({'зеленое' if num==0 else color})\n🎯 Ваша ставка: {choice}\n{'✅ ПОБЕДА! +' + fmt_money(payout) if win else '❌ ПОРАЖЕНИЕ'}\n💰 Баланс: {fmt_money(bal)}")

# БАСКЕТБОЛ
@dp.message(lambda m: m.text and m.text.lower().startswith("баскет"))
async def game_basket(message: Message):
    if not check_cooldown(message.from_user.id):
        return await message.answer("⏳ Подождите 2.5 секунды")
    parts = message.text.split()
    if len(parts) != 2:
        return await message.answer("❌ Формат: `баскет 100`")
    try:
        bet = parse_amount(parts[1])
    except:
        return await message.answer("❌ Неверная ставка")
    user_id = message.from_user.id
    balance = get_user(user_id)["coins"]
    if bet < MIN_BET:
        return await message.answer(f"❌ Минимальная ставка: {fmt_money(MIN_BET)}")
    if bet > balance:
        return await message.answer(f"❌ Недостаточно средств")
    dice = random.randint(1, 6)
    win = dice >= 4
    payout = bet * 2.4 if win else 0
    ok, bal = settle_instant_bet(user_id, bet, payout, "basketball", f"value={dice}")
    if not ok:
        return await message.answer(f"❌ Ошибка")
    await message.answer(f"🏀 <b>Баскетбол</b>\n🎲 Результат: {dice}\n{'✅ ПОПАДАНИЕ! +' + fmt_money(payout) if win else '❌ ПРОМАХ'}\n💰 Баланс: {fmt_money(bal)}")

# ФУТБОЛ
@dp.message(lambda m: m.text and m.text.lower().startswith("футбол"))
async def game_football(message: Message):
    if not check_cooldown(message.from_user.id):
        return await message.answer("⏳ Подождите 2.5 секунды")
    parts = message.text.split()
    if len(parts) < 2:
        return await message.answer("❌ Формат: `футбол 100 гол`")
    try:
        bet = parse_amount(parts[1])
    except:
        return await message.answer("❌ Неверная ставка")
    choice = parts[2].lower() if len(parts) > 2 else "гол"
    if choice not in ["гол", "мимо"]:
        choice = "гол"
    user_id = message.from_user.id
    balance = get_user(user_id)["coins"]
    if bet < MIN_BET:
        return await message.answer(f"❌ Минимальная ставка: {fmt_money(MIN_BET)}")
    if bet > balance:
        return await message.answer(f"❌ Недостаточно средств")
    dice = random.randint(1, 6)
    is_goal = dice >= 4
    result = "гол" if is_goal else "мимо"
    win = result == choice
    payout = bet * 2.4 if win else 0
    ok, bal = settle_instant_bet(user_id, bet, payout, "football", f"value={dice}")
    if not ok:
        return await message.answer(f"❌ Ошибка")
    await message.answer(f"⚽ <b>Футбол</b>\n🎲 Результат: {'ГОЛ!' if is_goal else 'МИМО!'}\n🎯 Ваш прогноз: {choice}\n{'✅ ПОБЕДА! +' + fmt_money(payout) if win else '❌ ПОРАЖЕНИЕ'}\n💰 Баланс: {fmt_money(bal)}")

# ДАРТС
@dp.message(lambda m: m.text and m.text.lower().startswith("дартс"))
async def game_darts(message: Message):
    if not check_cooldown(message.from_user.id):
        return await message.answer("⏳ Подождите 2.5 секунды")
    parts = message.text.split()
    if len(parts) != 2:
        return await message.answer("❌ Формат: `дартс 100`")
    try:
        bet = parse_amount(parts[1])
    except:
        return await message.answer("❌ Неверная ставка")
    user_id = message.from_user.id
    balance = get_user(user_id)["coins"]
    if bet < MIN_BET:
        return await message.answer(f"❌ Минимальная ставка: {fmt_money(MIN_BET)}")
    if bet > balance:
        return await message.answer(f"❌ Недостаточно средств")
    dice = random.randint(1, 6)
    if dice == 6:
        mult = 5.8
    elif dice >= 5:
        mult = 3.5
    elif dice >= 4:
        mult = 2.0
    else:
        mult = 0
    payout = bet * mult if mult > 0 else 0
    ok, bal = settle_instant_bet(user_id, bet, payout, "darts", f"value={dice}")
    if not ok:
        return await message.answer(f"❌ Ошибка")
    await message.answer(f"🎯 <b>Дартс</b>\n📊 Результат: {dice}/6\n{'✅ ПОБЕДА! x' + str(mult) if payout > 0 else '❌ ПОРАЖЕНИЕ'}\n💰 Баланс: {fmt_money(bal)}")

# БОУЛИНГ
@dp.message(lambda m: m.text and m.text.lower().startswith("боулинг"))
async def game_bowling(message: Message):
    if not check_cooldown(message.from_user.id):
        return await message.answer("⏳ Подождите 2.5 секунды")
    parts = message.text.split()
    if len(parts) != 2:
        return await message.answer("❌ Формат: `боулинг 100`")
    try:
        bet = parse_amount(parts[1])
    except:
        return await message.answer("❌ Неверная ставка")
    user_id = message.from_user.id
    balance = get_user(user_id)["coins"]
    if bet < MIN_BET:
        return await message.answer(f"❌ Минимальная ставка: {fmt_money(MIN_BET)}")
    if bet > balance:
        return await message.answer(f"❌ Недостаточно средств")
    dice = random.randint(1, 6)
    if dice == 6:
        mult = 5.8
    elif dice >= 5:
        mult = 3.5
    elif dice >= 4:
        mult = 2.0
    else:
        mult = 0
    payout = bet * mult if mult > 0 else 0
    ok, bal = settle_instant_bet(user_id, bet, payout, "bowling", f"value={dice}")
    if not ok:
        return await message.answer(f"❌ Ошибка")
    await message.answer(f"🎳 <b>Боулинг</b>\n📊 Результат: {dice}/6\n{'✅ ПОБЕДА! x' + str(mult) if payout > 0 else '❌ ПОРАЖЕНИЕ'}\n💰 Баланс: {fmt_money(bal)}")

# КУБИК
@dp.message(lambda m: m.text and m.text.lower().startswith("кубик"))
async def game_dice(message: Message):
    if not check_cooldown(message.from_user.id):
        return await message.answer("⏳ Подождите 2.5 секунды")
    parts = message.text.split()
    if len(parts) != 3:
        return await message.answer("❌ Формат: `кубик 100 5` (число 1-6, больше, меньше, чет, нечет)")
    try:
        bet = parse_amount(parts[1])
    except:
        return await message.answer("❌ Неверная ставка")
    choice = parts[2].lower()
    user_id = message.from_user.id
    balance = get_user(user_id)["coins"]
    if bet < MIN_BET:
        return await message.answer(f"❌ Минимальная ставка: {fmt_money(MIN_BET)}")
    if bet > balance:
        return await message.answer(f"❌ Недостаточно средств")
    rolled = random.randint(1, 6)
    win = False
    mult = 0
    if choice.isdigit() and 1 <= int(choice) <= 6:
        win = rolled == int(choice)
        mult = 5.8
    elif choice in ["больше", "б"]:
        win = rolled >= 4
        mult = 1.9
    elif choice in ["меньше", "м"]:
        win = rolled <= 3
        mult = 1.9
    elif choice in ["чет", "четное"]:
        win = rolled % 2 == 0
        mult = 1.9
    elif choice in ["нечет", "нечетное"]:
        win = rolled % 2 == 1
        mult = 1.9
    else:
        return await message.answer("❌ Неверная ставка")
    payout = bet * mult if win else 0
    ok, bal = settle_instant_bet(user_id, bet, payout, "dice", f"rolled={rolled}")
    if not ok:
        return await message.answer(f"❌ Ошибка")
    await message.answer(f"🎲 <b>Кубик</b>\n🎲 Выпало: {rolled}\n🎯 Ваша ставка: {choice}\n{'✅ ПОБЕДА! x' + str(mult) if win else '❌ ПОРАЖЕНИЕ'}\n💰 Баланс: {fmt_money(bal)}")

# СЛОТЫ
@dp.message(lambda m: m.text and m.text.lower().startswith("слоты"))
async def game_slots(message: Message):
    if not check_cooldown(message.from_user.id):
        return await message.answer("⏳ Подождите 2.5 секунды")
    parts = message.text.split()
    if len(parts) != 2:
        return await message.answer("❌ Формат: `слоты 100`")
    try:
        bet = parse_amount(parts[1])
    except:
        return await message.answer("❌ Неверная ставка")
    user_id = message.from_user.id
    balance = get_user(user_id)["coins"]
    if bet < MIN_BET:
        return await message.answer(f"❌ Минимальная ставка: {fmt_money(MIN_BET)}")
    if bet > balance:
        return await message.answer(f"❌ Недостаточно средств")
    symbols = ["🍒", "🍋", "🍊", "🍉", "🔔", "⭐", "7️⃣", "💎"]
    reel = [random.choice(symbols) for _ in range(3)]
    if reel[0] == reel[1] == reel[2]:
        if reel[0] == "7️⃣":
            mult = 15
        elif reel[0] == "💎":
            mult = 12
        else:
            mult = 5
        win = True
    elif reel[0] == reel[1] or reel[1] == reel[2]:
        mult = 2
        win = True
    else:
        mult = 0
        win = False
    payout = bet * mult if win else 0
    ok, bal = settle_instant_bet(user_id, bet, payout, "slots", f"{reel}")
    if not ok:
        return await message.answer(f"❌ Ошибка")
    await message.answer(f"🎰 <b>Слоты</b>\n┌─────┬─────┬─────┐\n│ {reel[0]} │ {reel[1]} │ {reel[2]} │\n└─────┴─────┴─────┘\n{'✅ ПОБЕДА! x' + str(mult) if win else '❌ ПОРАЖЕНИЕ'}\n💰 Баланс: {fmt_money(bal)}")

# БАШНЯ
tower_games = {}

@dp.message(lambda m: m.text and m.text.lower().startswith("башня"))
async def game_tower_start(message: Message):
    parts = message.text.split()
    if len(parts) != 2:
        return await message.answer("❌ Формат: `башня 100`")
    try:
        bet = parse_amount(parts[1])
    except:
        return await message.answer("❌ Неверная ставка")
    user_id = message.from_user.id
    balance = get_user(user_id)["coins"]
    if bet < MIN_BET:
        return await message.answer(f"❌ Минимальная ставка: {fmt_money(MIN_BET)}")
    if bet > balance:
        return await message.answer(f"❌ Недостаточно средств")
    ok, _ = reserve_bet(user_id, bet)
    if not ok:
        return await message.answer(f"❌ Ошибка")
    tower_games[user_id] = {"bet": bet, "level": 0}
    await message.answer(f"🗼 <b>Башня</b>\n💰 Ставка: {fmt_money(bet)}\n🏆 Уровень: 0/8\n\nВыберите секцию:",
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="1", callback_data="tower:1"), InlineKeyboardButton(text="2", callback_data="tower:2"), InlineKeyboardButton(text="3", callback_data="tower:3")],
                            [InlineKeyboardButton(text="💰 Забрать", callback_data="tower:cash")],
                        ]))

@dp.callback_query(F.data.startswith("tower:"))
async def game_tower_callback(query: CallbackQuery):
    user_id = query.from_user.id
    game = tower_games.get(user_id)
    if not game:
        await query.answer("❌ Нет игры")
        return
    action = query.data.split(":")[1]
    if action == "cash":
        if game["level"] == 0:
            await query.answer("❌ Сначала сделайте ход")
            return
        mult = TOWER_MULTIPLIERS[game["level"]-1]
        payout = game["bet"] * mult
        bal = finalize_reserved_bet(user_id, game["bet"], payout, "tower", "cashout")
        del tower_games[user_id]
        await query.message.edit_text(f"✅ Выигрыш! +{fmt_money(payout)}\n💰 Баланс: {fmt_money(bal)}")
        await query.answer()
        return
    safe = random.randint(1, 3)
    if int(action) != safe:
        bal = finalize_reserved_bet(user_id, game["bet"], 0, "tower", "lose")
        del tower_games[user_id]
        await query.message.edit_text(f"💥 Ловушка в {safe}!\n❌ ПРОИГРЫШ\n💰 Баланс: {fmt_money(bal)}")
        await query.answer()
        return
    game["level"] += 1
    if game["level"] >= 8:
        payout = game["bet"] * TOWER_MULTIPLIERS[-1]
        bal = finalize_reserved_bet(user_id, game["bet"], payout, "tower", "win")
        del tower_games[user_id]
        await query.message.edit_text(f"🏆 ПОБЕДА! +{fmt_money(payout)}\n💰 Баланс: {fmt_money(bal)}")
        await query.answer()
        return
    tower_games[user_id] = game
    mult = TOWER_MULTIPLIERS[game["level"]-1]
    await query.message.edit_text(f"🗼 <b>Башня</b>\n💰 Ставка: {fmt_money(game['bet'])}\n🏆 Уровень: {game['level']}/8\n🎯 Множитель: x{mult}\n💰 Потенциал: {fmt_money(game['bet'] * mult)}\n\nВыберите секцию:",
                                 reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                     [InlineKeyboardButton(text="1", callback_data="tower:1"), InlineKeyboardButton(text="2", callback_data="tower:2"), InlineKeyboardButton(text="3", callback_data="tower:3")],
                                     [InlineKeyboardButton(text="💰 Забрать", callback_data="tower:cash")],
                                 ]))
    await query.answer("✅ Успех!")

# ЗОЛОТО
gold_games = {}

@dp.message(lambda m: m.text and m.text.lower().startswith("золото"))
async def game_gold_start(message: Message):
    parts = message.text.split()
    if len(parts) != 2:
        return await message.answer("❌ Формат: `золото 100`")
    try:
        bet = parse_amount(parts[1])
    except:
        return await message.answer("❌ Неверная ставка")
    user_id = message.from_user.id
    balance = get_user(user_id)["coins"]
    if bet < MIN_BET:
        return await message.answer(f"❌ Минимальная ставка: {fmt_money(MIN_BET)}")
    if bet > balance:
        return await message.answer(f"❌ Недостаточно средств")
    ok, _ = reserve_bet(user_id, bet)
    if not ok:
        return await message.answer(f"❌ Ошибка")
    gold_games[user_id] = {"bet": bet, "step": 0}
    await message.answer(f"🥇 <b>Золото</b>\n💰 Ставка: {fmt_money(bet)}\n🏆 Шаг: 0/7\n\nВыберите плитку:",
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="1", callback_data="gold:1"), InlineKeyboardButton(text="2", callback_data="gold:2"), InlineKeyboardButton(text="3", callback_data="gold:3"), InlineKeyboardButton(text="4", callback_data="gold:4")],
                            [InlineKeyboardButton(text="💰 Забрать", callback_data="gold:cash")],
                        ]))

@dp.callback_query(F.data.startswith("gold:"))
async def game_gold_callback(query: CallbackQuery):
    user_id = query.from_user.id
    game = gold_games.get(user_id)
    if not game:
        await query.answer("❌ Нет игры")
        return
    action = query.data.split(":")[1]
    if action == "cash":
        if game["step"] == 0:
            await query.answer("❌ Сначала сделайте ход")
            return
        mult = GOLD_MULTIPLIERS[game["step"]-1]
        payout = game["bet"] * mult
        bal = finalize_reserved_bet(user_id, game["bet"], payout, "gold", "cashout")
        del gold_games[user_id]
        await query.message.edit_text(f"✅ Выигрыш! +{fmt_money(payout)}\n💰 Баланс: {fmt_money(bal)}")
        await query.answer()
        return
    trap = random.randint(1, 4)
    if int(action) == trap:
        bal = finalize_reserved_bet(user_id, game["bet"], 0, "gold", "lose")
        del gold_games[user_id]
        await query.message.edit_text(f"💥 Ловушка в {trap}!\n❌ ПРОИГРЫШ\n💰 Баланс: {fmt_money(bal)}")
        await query.answer()
        return
    game["step"] += 1
    if game["step"] >= 7:
        payout = game["bet"] * GOLD_MULTIPLIERS[-1]
        bal = finalize_reserved_bet(user_id, game["bet"], payout, "gold", "win")
        del gold_games[user_id]
        await query.message.edit_text(f"🏆 ПОБЕДА! +{fmt_money(payout)}\n💰 Баланс: {fmt_money(bal)}")
        await query.answer()
        return
    gold_games[user_id] = game
    mult = GOLD_MULTIPLIERS[game["step"]-1]
    await query.message.edit_text(f"🥇 <b>Золото</b>\n💰 Ставка: {fmt_money(game['bet'])}\n🏆 Шаг: {game['step']}/7\n🎯 Множитель: x{mult}\n💰 Потенциал: {fmt_money(game['bet'] * mult)}\n\nВыберите плитку:",
                                 reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                     [InlineKeyboardButton(text="1", callback_data="gold:1"), InlineKeyboardButton(text="2", callback_data="gold:2"), InlineKeyboardButton(text="3", callback_data="gold:3"), InlineKeyboardButton(text="4", callback_data="gold:4")],
                                     [InlineKeyboardButton(text="💰 Забрать", callback_data="gold:cash")],
                                 ]))
    await query.answer("✅ Успех!")

# АЛМАЗЫ
diamond_games = {}

@dp.message(lambda m: m.text and m.text.lower().startswith("алмазы"))
async def game_diamond_start(message: Message):
    parts = message.text.split()
    if len(parts) != 2:
        return await message.answer("❌ Формат: `алмазы 100`")
    try:
        bet = parse_amount(parts[1])
    except:
        return await message.answer("❌ Неверная ставка")
    user_id = message.from_user.id
    balance = get_user(user_id)["coins"]
    if bet < MIN_BET:
        return await message.answer(f"❌ Минимальная ставка: {fmt_money(MIN_BET)}")
    if bet > balance:
        return await message.answer(f"❌ Недостаточно средств")
    ok, _ = reserve_bet(user_id, bet)
    if not ok:
        return await message.answer(f"❌ Ошибка")
    diamond_games[user_id] = {"bet": bet, "step": 0}
    await message.answer(f"💎 <b>Алмазы</b>\n💰 Ставка: {fmt_money(bet)}\n🏆 Шаг: 0/8\n\nВыберите кристалл:",
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="1", callback_data="diamond:1"), InlineKeyboardButton(text="2", callback_data="diamond:2"), InlineKeyboardButton(text="3", callback_data="diamond:3"), InlineKeyboardButton(text="4", callback_data="diamond:4"), InlineKeyboardButton(text="5", callback_data="diamond:5")],
                            [InlineKeyboardButton(text="💰 Забрать", callback_data="diamond:cash")],
                        ]))

@dp.callback_query(F.data.startswith("diamond:"))
async def game_diamond_callback(query: CallbackQuery):
    user_id = query.from_user.id
    game = diamond_games.get(user_id)
    if not game:
        await query.answer("❌ Нет игры")
        return
    action = query.data.split(":")[1]
    if action == "cash":
        if game["step"] == 0:
            await query.answer("❌ Сначала сделайте ход")
            return
        mult = DIAMOND_MULTIPLIERS[game["step"]-1]
        payout = game["bet"] * mult
        bal = finalize_reserved_bet(user_id, game["bet"], payout, "diamond", "cashout")
        del diamond_games[user_id]
        await query.message.edit_text(f"✅ Выигрыш! +{fmt_money(payout)}\n💰 Баланс: {fmt_money(bal)}")
        await query.answer()
        return
    trap = random.randint(1, 5)
    if int(action) == trap:
        bal = finalize_reserved_bet(user_id, game["bet"], 0, "diamond", "lose")
        del diamond_games[user_id]
        await query.message.edit_text(f"💥 Бракованный кристалл {trap}!\n❌ ПРОИГРЫШ\n💰 Баланс: {fmt_money(bal)}")
        await query.answer()
        return
    game["step"] += 1
    if game["step"] >= 8:
        payout = game["bet"] * DIAMOND_MULTIPLIERS[-1]
        bal = finalize_reserved_bet(user_id, game["bet"], payout, "diamond", "win")
        del diamond_games[user_id]
        await query.message.edit_text(f"🏆 ПОБЕДА! +{fmt_money(payout)}\n💰 Баланс: {fmt_money(bal)}")
        await query.answer()
        return
    diamond_games[user_id] = game
    mult = DIAMOND_MULTIPLIERS[game["step"]-1]
    await query.message.edit_text(f"💎 <b>Алмазы</b>\n💰 Ставка: {fmt_money(game['bet'])}\n🏆 Шаг: {game['step']}/8\n🎯 Множитель: x{mult}\n💰 Потенциал: {fmt_money(game['bet'] * mult)}\n\nВыберите кристалл:",
                                 reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                     [InlineKeyboardButton(text="1", callback_data="diamond:1"), InlineKeyboardButton(text="2", callback_data="diamond:2"), InlineKeyboardButton(text="3", callback_data="diamond:3"), InlineKeyboardButton(text="4", callback_data="diamond:4"), InlineKeyboardButton(text="5", callback_data="diamond:5")],
                                     [InlineKeyboardButton(text="💰 Забрать", callback_data="diamond:cash")],
                                 ]))
    await query.answer("✅ Успех!")

# МИНЫ
mines_games = {}

@dp.message(lambda m: m.text and m.text.lower().startswith("мины"))
async def game_mines_start(message: Message):
    parts = message.text.split()
    if len(parts) < 2:
        return await message.answer("❌ Формат: `мины 100 3`")
    try:
        bet = parse_amount(parts[1])
    except:
        return await message.answer("❌ Неверная ставка")
    mines = 3
    if len(parts) > 2:
        try:
            mines = int(parts[2])
            if mines < 1 or mines > 5:
                mines = 3
        except:
            mines = 3
    user_id = message.from_user.id
    balance = get_user(user_id)["coins"]
    if bet < MIN_BET:
        return await message.answer(f"❌ Минимальная ставка: {fmt_money(MIN_BET)}")
    if bet > balance:
        return await message.answer(f"❌ Недостаточно средств")
    ok, _ = reserve_bet(user_id, bet)
    if not ok:
        return await message.answer(f"❌ Ошибка")
    cells = list(range(1, 10))
    bomb_cells = set(random.sample(cells, mines))
    mines_games[user_id] = {"bet": bet, "mines": mines, "bombs": bomb_cells, "opened": set()}
    kb = InlineKeyboardBuilder()
    for i in range(1, 10):
        kb.button(text="❔", callback_data=f"mines:{i}")
    kb.button(text="💰 Забрать", callback_data="mines:cash")
    kb.adjust(3)
    await message.answer(f"💣 <b>Мины</b>\n💰 Ставка: {fmt_money(bet)}\n💣 Мин: {mines}\n🎯 Открыто: 0/9", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("mines:"))
async def game_mines_callback(query: CallbackQuery):
    user_id = query.from_user.id
    game = mines_games.get(user_id)
    if not game:
        await query.answer("❌ Нет игры")
        return
    action = query.data.split(":")[1]
    if action == "cash":
        if len(game["opened"]) == 0:
            await query.answer("❌ Сначала откройте клетку")
            return
        safe_total = 9 - game["mines"]
        mult = (9 / safe_total) ** len(game["opened"]) * 0.95
        payout = game["bet"] * mult
        bal = finalize_reserved_bet(user_id, game["bet"], payout, "mines", "cashout")
        del mines_games[user_id]
        await query.message.edit_text(f"✅ Выигрыш! +{fmt_money(payout)}\n💰 Баланс: {fmt_money(bal)}")
        await query.answer()
        return
    try:
        cell = int(action)
    except:
        return
    if cell in game["opened"]:
        await query.answer("❌ Уже открыто")
        return
    if cell in game["bombs"]:
        bal = finalize_reserved_bet(user_id, game["bet"], 0, "mines", "explode")
        del mines_games[user_id]
        await query.message.edit_text(f"💥 МИНА в {cell}!\n❌ ПРОИГРЫШ\n💰 Баланс: {fmt_money(bal)}")
        await query.answer()
        return
    game["opened"].add(cell)
    safe_total = 9 - game["mines"]
    if len(game["opened"]) >= safe_total:
        mult = (9 / safe_total) ** len(game["opened"]) * 0.95
        payout = game["bet"] * mult
        bal = finalize_reserved_bet(user_id, game["bet"], payout, "mines", "win")
        del mines_games[user_id]
        await query.message.edit_text(f"🏆 ПОБЕДА! +{fmt_money(payout)}\n💰 Баланс: {fmt_money(bal)}")
        await query.answer()
        return
    mines_games[user_id] = game
    mult = (9 / safe_total) ** len(game["opened"]) * 0.95
    kb = InlineKeyboardBuilder()
    for i in range(1, 10):
        if i in game["opened"]:
            kb.button(text="✅", callback_data="mines:noop")
        else:
            kb.button(text="❔", callback_data=f"mines:{i}")
    kb.button(text="💰 Забрать", callback_data="mines:cash")
    kb.adjust(3)
    await query.message.edit_text(f"💣 <b>Мины</b>\n💰 Ставка: {fmt_money(game['bet'])}\n💣 Мин: {game['mines']}\n🎯 Открыто: {len(game['opened'])}/9\n🎯 Множитель: x{mult:.2f}\n💰 Потенциал: {fmt_money(game['bet'] * mult)}", reply_markup=kb.as_markup())
    await query.answer("✅ Безопасно!")

@dp.callback_query(F.data == "mines:noop")
async def mines_noop(query: CallbackQuery):
    await query.answer()

# ОЧКО (BLACKJACK)
ochko_games = {}

def card_value_ochko(card):
    val = card[0]
    if val in ["J","Q","K"]:
        return 10
    if val == "A":
        return 11
    return int(val)

def hand_value_ochko(hand):
    total = sum(card_value_ochko(c) for c in hand)
    aces = sum(1 for c in hand if c[0] == "A")
    while total > 21 and aces > 0:
        total -= 10
        aces -= 1
    return total

def make_deck():
    suits = ["♠","♥","♦","♣"]
    ranks = ["2","3","4","5","6","7","8","9","10","J","Q","K","A"]
    deck = [(r,s) for r in ranks for s in suits]
    random.shuffle(deck)
    return deck

@dp.message(lambda m: m.text and m.text.lower().startswith("очко"))
async def game_ochko_start(message: Message):
    parts = message.text.split()
    if len(parts) != 2:
        return await message.answer("❌ Формат: `очко 100`")
    try:
        bet = parse_amount(parts[1])
    except:
        return await message.answer("❌ Неверная ставка")
    user_id = message.from_user.id
    balance = get_user(user_id)["coins"]
    if bet < MIN_BET:
        return await message.answer(f"❌ Минимальная ставка: {fmt_money(MIN_BET)}")
    if bet > balance:
        return await message.answer(f"❌ Недостаточно средств")
    ok, _ = reserve_bet(user_id, bet)
    if not ok:
        return await message.answer(f"❌ Ошибка")
    deck = make_deck()
    player = [deck.pop(), deck.pop()]
    dealer = [deck.pop(), deck.pop()]
    ochko_games[user_id] = {"bet": bet, "deck": deck, "player": player, "dealer": dealer}
    pv = hand_value_ochko(player)
    if pv == 21:
        dv = hand_value_ochko(dealer)
        if dv == 21:
            payout = bet
            bal = finalize_reserved_bet(user_id, bet, payout, "ochko", "push")
            del ochko_games[user_id]
            await message.answer(f"🎴 <b>Очко</b>\n🤝 НИЧЬЯ! BLACKJACK\n💰 Возврат: {fmt_money(payout)}\n💰 Баланс: {fmt_money(bal)}")
        else:
            payout = bet * 2.5
            bal = finalize_reserved_bet(user_id, bet, payout, "ochko", "blackjack")
            del ochko_games[user_id]
            await message.answer(f"🎴 <b>Очко</b>\n🎉 BLACKJACK! ПОБЕДА!\n+{fmt_money(payout)}\n💰 Баланс: {fmt_money(bal)}")
        return
    await message.answer(f"🎴 <b>Очко</b>\n💰 Ставка: {fmt_money(bet)}\n\nДилер: {dealer[0][0]}{dealer[0][1]} ??\nТы: {player[0][0]}{player[0][1]} {player[1][0]}{player[1][1]} ({pv})\n\nВыберите действие:",
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="➕ Взять", callback_data="ochko:hit")],
                            [InlineKeyboardButton(text="✋ Стоп", callback_data="ochko:stand")],
                        ]))

@dp.callback_query(F.data.startswith("ochko:"))
async def game_ochko_callback(query: CallbackQuery):
    user_id = query.from_user.id
    game = ochko_games.get(user_id)
    if not game:
        await query.answer("❌ Нет игры")
        return
    action = query.data.split(":")[1]
    if action == "hit":
        game["player"].append(game["deck"].pop())
        pv = hand_value_ochko(game["player"])
        if pv > 21:
            bal = finalize_reserved_bet(user_id, game["bet"], 0, "ochko", "bust")
            del ochko_games[user_id]
            await query.message.edit_text(f"🎴 <b>Очко</b>\n💥 ПЕРЕБОР! {pv}\n❌ ПОРАЖЕНИЕ\n💰 Баланс: {fmt_money(bal)}")
            await query.answer()
            return
        await query.message.edit_text(f"🎴 <b>Очко</b>\n💰 Ставка: {fmt_money(game['bet'])}\n\nДилер: {game['dealer'][0][0]}{game['dealer'][0][1]} ??\nТы: {' '.join(f'{c[0]}{c[1]}' for c in game['player'])} ({pv})\n\nВыберите действие:",
                                      reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                          [InlineKeyboardButton(text="➕ Взять", callback_data="ochko:hit")],
                                          [InlineKeyboardButton(text="✋ Стоп", callback_data="ochko:stand")],
                                      ]))
        await query.answer()
        return
    if action == "stand":
        while hand_value_ochko(game["dealer"]) < 17:
            game["dealer"].append(game["deck"].pop())
        pv = hand_value_ochko(game["player"])
        dv = hand_value_ochko(game["dealer"])
        if dv > 21 or pv > dv:
            payout = game["bet"] * 2
            result = "✅ ПОБЕДА!"
        elif pv == dv:
            payout = game["bet"]
            result = "🤝 НИЧЬЯ"
        else:
            payout = 0
            result = "❌ ПОРАЖЕНИЕ"
        bal = finalize_reserved_bet(user_id, game["bet"], payout, "ochko", "stand")
        del ochko_games[user_id]
        await query.message.edit_text(f"🎴 <b>Очко</b>\n💰 Ставка: {fmt_money(game['bet'])}\n\nДилер: {' '.join(f'{c[0]}{c[1]}' for c in game['dealer'])} ({dv})\nТы: {' '.join(f'{c[0]}{c[1]}' for c in game['player'])} ({pv})\n\n{result}\n{'💰 Выплата: ' + fmt_money(payout) if payout > 0 else ''}\n💰 Баланс: {fmt_money(bal)}")
        await query.answer()

# ==================== АДМИН КОМАНДЫ ====================
@dp.message(Command("ban"))
async def admin_ban(message: Message):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 2:
        return await message.answer("❌ /ban @username или /ban 123456789")
    target = message.reply_to_message.from_user if message.reply_to_message else None
    if not target:
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
    add_balance(uid, amount)
    await message.answer(f"✅ Выдано {fmt_money(amount)} пользователю {mention_user(uid)}")

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
    await message.answer(f"📊 <b>Статистика</b>\n\n👥 Пользователей: {users}\n🎲 Ставок: {bets}\n💰 Выплачено: {fmt_money(payout)}\n🏦 Комиссий: {fmt_money(sys[0] if sys else 0)}")

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
    await message.answer(f"✅ Всем начислено по {fmt_money(amount)}")

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

@dp.message(Command("addpromo"))
async def admin_addpromo(message: Message):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) != 4:
        return await message.answer("❌ /addpromo КОД СУММА АКТИВАЦИИ")
    code = parts[1].upper()
    try:
        reward = parse_amount(parts[2])
        activations = int(parts[3])
    except:
        return await message.answer("❌ Неверные данные")
    create_promo(code, reward, activations)
    await message.answer(f"✅ Промокод {code} создан!\n💰 {fmt_money(reward)} x{activations}")

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
    await query.message.edit_text(
        f"⭐ <b>Пополнение</b>\n\n1 Star = {STARS_RATE} {CURRENCY_NAME}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⭐ 1 Star", callback_data="donate:1"), InlineKeyboardButton(text="⭐ 5 Stars", callback_data="donate:5")],
            [InlineKeyboardButton(text="⭐ 10 Stars", callback_data="donate:10"), InlineKeyboardButton(text="⭐ 50 Stars", callback_data="donate:50")],
            [InlineKeyboardButton(text="⭐ 100 Stars", callback_data="donate:100")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="menu:back")],
        ])
    )
    await query.answer()

@dp.callback_query(F.data == "menu:bank")
async def menu_bank_cb(query: CallbackQuery):
    user = get_user(query.from_user.id)
    summary = get_bank_summary(query.from_user.id)
    await query.message.edit_text(
        f"🏦 <b>Банк</b>\n\n"
        f"💰 Баланс: {fmt_money(float(user['coins']))}\n"
        f"📊 Активных депозитов: {summary['count']}\n"
        f"💵 Сумма в депозитах: {fmt_money(summary['sum'])}\n\n"
        f"📈 Ставки: 7д(+3%), 14д(+7%), 30д(+18%)",
        reply_markup=bank_kb()
    )
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
    await query.message.edit_text(
        f"👥 <b>Реферальная программа</b>\n\n"
        f"🔗 Ваша ссылка:\n<code>{link}</code>\n\n"
        f"📊 Приглашено: {count}\n"
        f"🎁 За друга: +{fmt_money(REFERRER_BONUS)} вам, +{fmt_money(REFERRED_BONUS)} другу",
        reply_markup=main_menu_kb()
    )
    await query.answer()

@dp.callback_query(F.data == "menu:add_chat")
async def menu_add_chat_cb(query: CallbackQuery):
    link = f"https://t.me/{BOT_USERNAME}?startgroup=true"
    await query.message.answer(
        f"🤖 <b>Добавить бота в чат</b>\n\n"
        f"Нажмите на кнопку ниже:\n\n"
        f"<a href='{link}'>➕ Добавить {BOT_USERNAME} в чат</a>",
        disable_web_page_preview=True,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="menu:back")]])
    )
    await query.answer()

@dp.callback_query(F.data == "menu:help")
async def menu_help_cb(query: CallbackQuery):
    await query.message.edit_text(get_help_text(), reply_markup=main_menu_kb())
    await query.answer()

@dp.callback_query(F.data == "menu:back")
async def menu_back_cb(query: CallbackQuery):
    await query.message.edit_text(f"🎮 <b>{CURRENCY_NAME}</b>\nБаланс: {fmt_money(get_user(query.from_user.id)['coins'])}", reply_markup=main_menu_kb())
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
        "crash": "краш 100 2.5", "roulette": "рул 100 красное", "basket": "баскет 100",
        "football": "футбол 100 гол", "darts": "дартс 100", "bowling": "боулинг 100",
        "dice": "кубик 100 5", "slots": "слоты 100", "tower": "башня 100",
        "gold": "золото 100", "diamond": "алмазы 100", "mines": "мины 100 3",
        "blackjack": "очко 100"
    }
    await query.message.answer(f"📝 Пример: <code>{examples.get(game)}</code>")
    await query.answer()

# ==================== ОТМЕНА ====================
@dp.message(lambda m: normalize_text(m.text) in {"отмена", "/cancel"})
async def cancel_cmd(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("🛑 Действие отменено")

# ==================== ЗАПУСК ====================
async def main():
    init_db()
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await bot.delete_webhook(drop_pending_updates=True)
    print("✅ Бот VIRTEX успешно запущен!")
    print(f"👑 Админы: {ADMIN_IDS}")
    print(f"🎮 Доступно игр: 13")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
