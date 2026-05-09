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

def is_admin_user(user_id: int) -> bool:
    return int(user_id) in ADMIN_IDS

def parse_amount(text: str) -> float:
    raw = str(text).strip().lower().replace(",", ".").replace(" ", "")
    multiplier = 1000 if raw.endswith(("k", "к")) else 1
    if multiplier > 1:
        raw = raw[:-1]
    value = float(raw) * multiplier
    if value <= 0:
        raise ValueError()
    return round(value, 2)

def normalize_text(text: Optional[str]) -> str:
    return (text or "").lower().strip()

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
    conn.execute("UPDATE users SET coins = coins + ? WHERE id = ?", (round(amount, 2), str(user_id)))
    row = conn.execute("SELECT coins FROM users WHERE id = ?", (str(user_id),)).fetchone()
    conn.commit()
    conn.close()
    return float(row["coins"])

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
        
        return await handler(event, data)

# ==================== СОСТОЯНИЯ ====================
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

# ==================== ГЛОБАЛЬНЫЕ СЛОВАРИ ====================
TOWER_GAMES = {}
GOLD_GAMES = {}
DIAMOND_GAMES = {}
MINES_GAMES = {}
OCHKO_GAMES = {}

# ==================== БАЗОВЫЕ ФУНКЦИИ СТАВОК ====================
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
    except Exception as e:
        conn.rollback()
        print(f"Error: {e}")
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
    except Exception as e:
        conn.rollback()
        print(f"Error: {e}")
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
    except Exception as e:
        conn.rollback()
        print(f"Error: {e}")
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
    except Exception as e:
        conn.rollback()
        print(f"Transfer error: {e}")
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

# ==================== ТЕКСТ ПОМОЩИ ====================
def get_help_text() -> str:
    return """
<b>🎮 Игровой бот VIRTEX</b>

<b>💰 Баланс и бонусы</b>
• <code>б</code> или <code>баланс</code> - показать баланс
• <code>профиль</code> - статистика
• <code>бонус</code> - получить бонус

<b>🎲 Игры</b>
• <code>башня 100</code> - Башня
• <code>золото 100</code> - Золото
• <code>алмазы 100</code> - Алмазы
• <code>мины 100 3</code> - Мины (1-5 мин)
• <code>рул 100 красное</code> - Рулетка
• <code>краш 100 2.5</code> - Краш
• <code>кубик 100 5</code> - Кубик
• <code>кости 100 м</code> - Кости
• <code>очко 100</code> - Очко
• <code>футбол 100</code> - Футбол
• <code>баскет 100</code> - Баскетбол

<b>💸 Переводы</b>
• <code>пер @username 100</code> - комиссия 5%
• <code>пер 123456789 100</code>
• Или ответьте на сообщение: <code>пер 100</code>

<b>⭐ Пополнение</b>
• <code>/donate</code> - купить VIRTEX за Stars

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

def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Баланс", callback_data="menu:balance")],
        [InlineKeyboardButton(text="🎲 Игры", callback_data="menu:games")],
        [InlineKeyboardButton(text="⭐ Пополнить", callback_data="menu:donate")],
        [InlineKeyboardButton(text="🏦 Банк", callback_data="menu:bank")],
        [InlineKeyboardButton(text="👥 Рефералы", callback_data="menu:ref")],
        [InlineKeyboardButton(text="❓ Помощь", callback_data="menu:help")],
    ])

def games_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗼 Башня", callback_data="game:tower"), InlineKeyboardButton(text="🥇 Золото", callback_data="game:gold")],
        [InlineKeyboardButton(text="💎 Алмазы", callback_data="game:diamond"), InlineKeyboardButton(text="💣 Мины", callback_data="game:mines")],
        [InlineKeyboardButton(text="🎡 Рулетка", callback_data="game:roulette"), InlineKeyboardButton(text="📈 Краш", callback_data="game:crash")],
        [InlineKeyboardButton(text="🎲 Кубик", callback_data="game:cube"), InlineKeyboardButton(text="🎯 Кости", callback_data="game:dice")],
        [InlineKeyboardButton(text="🎴 Очко", callback_data="game:ochko"), InlineKeyboardButton(text="⚽ Футбол", callback_data="game:football")],
        [InlineKeyboardButton(text="🏀 Баскет", callback_data="game:basket"), InlineKeyboardButton(text="🔙 Назад", callback_data="menu:back")],
    ])

def checks_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать чек", callback_data="checks:create")],
        [InlineKeyboardButton(text="💸 Активировать чек", callback_data="checks:claim")],
        [InlineKeyboardButton(text="📄 Мои чеки", callback_data="checks:my")],
    ])

def bank_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Открыть депозит", callback_data="bank:open")],
        [InlineKeyboardButton(text="📜 Мои депозиты", callback_data="bank:list")],
        [InlineKeyboardButton(text="💰 Снять зрелые", callback_data="bank:withdraw")],
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
        [InlineKeyboardButton(text="🔴 Красное", callback_data="roulette:red"), InlineKeyboardButton(text="⚫ Черное", callback_data="roulette:black")],
        [InlineKeyboardButton(text="2️⃣ Чет", callback_data="roulette:even"), InlineKeyboardButton(text="1️⃣ Нечет", callback_data="roulette:odd")],
        [InlineKeyboardButton(text="0️⃣ Зеро (x36)", callback_data="roulette:zero")],
    ])

def tower_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1", callback_data="tower:1"), InlineKeyboardButton(text="2", callback_data="tower:2"), InlineKeyboardButton(text="3", callback_data="tower:3")],
        [InlineKeyboardButton(text="💰 Забрать", callback_data="tower:cash"), InlineKeyboardButton(text="❌ Сдаться", callback_data="tower:cancel")],
    ])

def gold_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1", callback_data="gold:1"), InlineKeyboardButton(text="2", callback_data="gold:2"), InlineKeyboardButton(text="3", callback_data="gold:3"), InlineKeyboardButton(text="4", callback_data="gold:4")],
        [InlineKeyboardButton(text="💰 Забрать", callback_data="gold:cash"), InlineKeyboardButton(text="❌ Сдаться", callback_data="gold:cancel")],
    ])

def diamond_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1", callback_data="diamond:1"), InlineKeyboardButton(text="2", callback_data="diamond:2"), InlineKeyboardButton(text="3", callback_data="diamond:3"), InlineKeyboardButton(text="4", callback_data="diamond:4"), InlineKeyboardButton(text="5", callback_data="diamond:5")],
        [InlineKeyboardButton(text="💰 Забрать", callback_data="diamond:cash"), InlineKeyboardButton(text="❌ Сдаться", callback_data="diamond:cancel")],
    ])

def mines_kb(game: Dict, reveal_all: bool = False) -> InlineKeyboardMarkup:
    opened = set(game["opened"])
    mines = set(game["mines"])
    rows = []
    for start in (1, 4, 7):
        row = []
        for idx in range(start, start + 3):
            if idx in opened:
                text = "✅"
                cb = "mines:noop"
            elif reveal_all and idx in mines:
                text = "💣"
                cb = "mines:noop"
            else:
                text = str(idx)
                cb = f"mines:{idx}"
            row.append(InlineKeyboardButton(text=text, callback_data=cb))
        rows.append(row)
    rows.append([InlineKeyboardButton(text="💰 Забрать", callback_data="mines:cash"), InlineKeyboardButton(text="❌ Сдаться", callback_data="mines:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def ochko_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Взять", callback_data="ochko:hit"), InlineKeyboardButton(text="✋ Стоп", callback_data="ochko:stand")],
    ])

def ochko_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Начать", callback_data="ochko:start"), InlineKeyboardButton(text="❌ Отмена", callback_data="ochko:cancel")],
    ])

# ==================== КОМАНДЫ ====================
@dp.message(CommandStart())
async def start_command(message: Message, state: FSMContext, bot: Bot):
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
                    conn.execute("UPDATE users SET coins = coins + ? WHERE id = ?", (REFERRER_BONUS, str(referrer_id)))
                    conn.execute("UPDATE users SET coins = coins + ? WHERE id = ?", (REFERRED_BONUS, str(user_id)))
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
async def help_command(message: Message):
    await message.answer(get_help_text())

@dp.message(Command("menu"))
async def menu_command(message: Message):
    await message.answer("📍 <b>Меню</b>", reply_markup=main_menu_kb())

@dp.callback_query(F.data == "menu:help")
async def menu_help_cb(query: CallbackQuery):
    await query.message.edit_text(get_help_text(), reply_markup=main_menu_kb())
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
            [InlineKeyboardButton(text="1 Star", callback_data="donate:1"), InlineKeyboardButton(text="5 Stars", callback_data="donate:5")],
            [InlineKeyboardButton(text="10 Stars", callback_data="donate:10"), InlineKeyboardButton(text="50 Stars", callback_data="donate:50")],
            [InlineKeyboardButton(text="100 Stars", callback_data="donate:100")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="menu:back")],
        ])
    )
    await query.answer()

@dp.callback_query(F.data == "menu:bank")
async def menu_bank_cb(query: CallbackQuery):
    await query.message.edit_text("🏦 <b>Банк</b>\n\n7д: +3%\n14д: +7%\n30д: +18%", reply_markup=main_menu_kb())
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

@dp.callback_query(F.data == "menu:back")
async def menu_back_cb(query: CallbackQuery):
    await query.message.edit_text(f"🎮 <b>{CURRENCY_NAME}</b>", reply_markup=main_menu_kb())
    await query.answer()

@dp.callback_query(F.data.startswith("donate:"))
async def donate_cb(query: CallbackQuery, bot: Bot):
    stars = int(query.data.split(":")[-1])
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
async def pre_checkout_handler(pre_checkout_query: PreCheckoutQuery, bot: Bot):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@dp.message(F.successful_payment)
async def successful_payment_handler(message: Message):
    payload = message.successful_payment.invoice_payload
    parts = payload.split("_")
    stars = int(parts[1])
    user_id = int(parts[2])
    virtex = stars * STARS_RATE
    add_balance(user_id, virtex)
    await message.answer(f"✅ Пополнено! +{fmt_money(virtex)}")

@dp.callback_query(F.data == "check_subscription")
async def check_subscription_cb(query: CallbackQuery, bot: Bot):
    ok, not_subscribed = await check_subscriptions(query.from_user.id, bot)
    if ok:
        await query.message.edit_text("✅ Спасибо за подписку!", reply_markup=main_menu_kb())
    else:
        await query.message.edit_text("⚠️ Подпишитесь на каналы!", reply_markup=subscription_keyboard(not_subscribed))
    await query.answer()

# ==================== ПЕРЕВОДЫ ====================
@dp.message(lambda m: normalize_text(m.text).startswith("пер"))
async def transfer_command(message: Message):
    text = message.text.strip()
    parts = text.split(maxsplit=2)
    
    # Ответ на сообщение
    if message.reply_to_message and message.reply_to_message.from_user:
        target = message.reply_to_message.from_user
        if len(parts) < 2:
            return await message.answer("❌ Формат: `пер 100` в ответ на сообщение", parse_mode="HTML")
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
        return await message.answer("❌ Формат:\n`пер @username 100`\n`пер 123456789 100`\nили ответьте на сообщение: `пер 100`", parse_mode="HTML")
    
    target_str = parts[1]
    try:
        amount = parse_amount(parts[2])
    except:
        return await message.answer("❌ Неверная сумма")
    
    if amount < 1:
        return await message.answer(f"❌ Минимум: {fmt_money(1)}")
    
    # Поиск по username
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

# ==================== БАЛАНС И БОНУС ====================
@dp.message(lambda m: normalize_text(m.text) in {"б", "баланс"})
async def balance_command(message: Message):
    user = get_user(message.from_user.id)
    await message.answer(f"💰 {mention_user(message.from_user.id, message.from_user.first_name)}, баланс: {fmt_money(float(user['coins']))}")

@dp.message(lambda m: normalize_text(m.text) in {"профиль"})
async def profile_command(message: Message):
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
async def bonus_command(message: Message):
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
async def top_command(message: Message):
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
async def games_command(message: Message):
    await message.answer("🎮 <b>Игры</b>", reply_markup=games_kb())

@dp.callback_query(F.data.startswith("game:"))
async def game_pick_cb(query: CallbackQuery):
    game = query.data.split(":")[-1]
    usage = {
        "tower": "башня 100", "gold": "золото 100", "diamond": "алмазы 100",
        "mines": "мины 100 3", "roulette": "рул 100 красное", "crash": "краш 100 2.5",
        "cube": "кубик 100 5", "dice": "кости 100 м", "ochko": "очко 100",
        "football": "футбол 100", "basket": "баскет 100"
    }
    await query.message.answer(f"📝 Пример: <code>{usage.get(game)}</code>")
    await query.answer()

# ==================== ИГРЫ ====================

# РУЛЕТКА
def roulette_roll(choice: str) -> tuple[bool, float, str]:
    num = random.randint(0, 36)
    if num == 0:
        color, parity = "green", "zero"
    else:
        color = "red" if num in RED_NUMBERS else "black"
        parity = "even" if num % 2 == 0 else "odd"
    win, mult = False, 0
    if choice == "red" and color == "red":
        win, mult = True, 2
    elif choice == "black" and color == "black":
        win, mult = True, 2
    elif choice == "even" and parity == "even":
        win, mult = True, 2
    elif choice == "odd" and parity == "odd":
        win, mult = True, 2
    elif choice == "zero" and num == 0:
        win, mult = True, 36
    return win, mult, f"Выпало {num}"

@dp.message(lambda m: normalize_text(m.text).startswith("рул"))
async def roulette_game(message: Message):
    if not check_cooldown(message.from_user.id):
        return await message.answer("⏳ Подождите")
    parts = message.text.split()
    if len(parts) != 3:
        return await message.answer("❌ Формат: `рул 100 красное`")
    try:
        bet = parse_amount(parts[1])
    except:
        return await message.answer("❌ Неверная ставка")
    if bet < MIN_BET:
        return await message.answer(f"❌ Минимум {fmt_money(MIN_BET)}")
    
    choice_map = {"красное":"red","черное":"black","чет":"even","нечет":"odd","зеро":"zero"}
    choice = choice_map.get(parts[2].lower())
    if not choice:
        return await message.answer("❌ Выберите: красное/черное/чет/нечет/зеро")
    
    win, mult, outcome = roulette_roll(choice)
    payout = bet * mult if win else 0
    ok, bal = settle_instant_bet(message.from_user.id, bet, payout, f"roulette", outcome)
    if not ok:
        return await message.answer("❌ Недостаточно средств")
    await message.answer(f"🎡 {outcome}\n{'✅ Победа!' if win else '❌ Поражение'}\n💰 Выплата: {fmt_money(payout)}\n💎 Баланс: {fmt_money(bal)}")

# КРАШ
def crash_roll() -> float:
    r = random.random()
    if r < 0.05: return round(random.uniform(1, 1.5), 2)
    elif r < 0.3: return round(random.uniform(1.51, 2.5), 2)
    elif r < 0.6: return round(random.uniform(2.51, 4), 2)
    elif r < 0.85: return round(random.uniform(4.01, 7), 2)
    else: return round(random.uniform(7.01, 50), 2)

@dp.message(lambda m: normalize_text(m.text).startswith("краш"))
async def crash_game(message: Message):
    if not check_cooldown(message.from_user.id):
        return await message.answer("⏳ Подождите")
    parts = message.text.split()
    if len(parts) != 3:
        return await message.answer("❌ Формат: `краш 100 2.5`")
    try:
        bet = parse_amount(parts[1])
        target = float(parts[2])
    except:
        return await message.answer("❌ Неверные данные")
    if bet < MIN_BET:
        return await message.answer(f"❌ Минимум {fmt_money(MIN_BET)}")
    if target < 1.1 or target > 10:
        return await message.answer("❌ Множитель от 1.1 до 10")
    
    rolled = crash_roll()
    win = target <= rolled
    payout = bet * target if win else 0
    ok, bal = settle_instant_bet(message.from_user.id, bet, payout, "crash", f"rolled={rolled}")
    if not ok:
        return await message.answer("❌ Недостаточно средств")
    await message.answer(f"📈 Краш: {rolled}x\n🎯 Ваш: {target}x\n{'✅ Победа!' if win else '❌ Поражение'}\n💰 Выплата: {fmt_money(payout)}\n💎 Баланс: {fmt_money(bal)}")

# КУБИК
@dp.message(lambda m: normalize_text(m.text).startswith("кубик"))
async def cube_game(message: Message):
    if not check_cooldown(message.from_user.id):
        return await message.answer("⏳ Подождите")
    parts = message.text.split()
    if len(parts) != 3:
        return await message.answer("❌ Формат: `кубик 100 5`")
    try:
        bet = parse_amount(parts[1])
        guess = int(parts[2])
    except:
        return await message.answer("❌ Неверные данные")
    if bet < MIN_BET:
        return await message.answer(f"❌ Минимум {fmt_money(MIN_BET)}")
    if guess < 1 or guess > 6:
        return await message.answer("❌ Число от 1 до 6")
    
    dice = await message.answer_dice(emoji="🎲")
    rolled = dice.dice.value
    win = guess == rolled
    payout = bet * 5.8 if win else 0
    ok, bal = settle_instant_bet(message.from_user.id, bet, payout, "cube", f"rolled={rolled}")
    if not ok:
        return await message.answer("❌ Недостаточно средств")
    await message.answer(f"🎲 Выпало: {rolled}\n{'✅ Победа!' if win else '❌ Поражение'}\n💰 Выплата: {fmt_money(payout)}\n💎 Баланс: {fmt_money(bal)}")

# КОСТИ
@dp.message(lambda m: normalize_text(m.text).startswith("кости"))
async def dice_game(message: Message):
    if not check_cooldown(message.from_user.id):
        return await message.answer("⏳ Подождите")
    parts = message.text.split()
    if len(parts) != 3:
        return await message.answer("❌ Формат: `кости 100 м` (м/б/равно)")
    try:
        bet = parse_amount(parts[1])
    except:
        return await message.answer("❌ Неверная ставка")
    if bet < MIN_BET:
        return await message.answer(f"❌ Минимум {fmt_money(MIN_BET)}")
    
    choice = parts[2].lower()
    if choice not in ["м", "б", "равно"]:
        return await message.answer("❌ Выберите: м, б или равно")
    
    d1 = await message.answer_dice(emoji="🎲")
    d2 = await message.answer_dice(emoji="🎲")
    total = d1.dice.value + d2.dice.value
    
    win, mult = False, 0
    if choice == "м" and total < 7:
        win, mult = True, 1.9
    elif choice == "б" and total > 7:
        win, mult = True, 1.9
    elif choice == "равно" and total == 7:
        win, mult = True, 5
    
    payout = bet * mult if win else 0
    ok, bal = settle_instant_bet(message.from_user.id, bet, payout, "dice", f"{d1.dice.value}+{d2.dice.value}={total}")
    if not ok:
        return await message.answer("❌ Недостаточно средств")
    await message.answer(f"🎯 Сумма: {total}\n{'✅ Победа!' if win else '❌ Поражение'}\n💰 Выплата: {fmt_money(payout)}\n💎 Баланс: {fmt_money(bal)}")

# ФУТБОЛ
@dp.message(lambda m: normalize_text(m.text).startswith("футбол"))
async def football_game(message: Message):
    if not check_cooldown(message.from_user.id):
        return await message.answer("⏳ Подождите")
    parts = message.text.split()
    if len(parts) != 2:
        return await message.answer("❌ Формат: `футбол 100`")
    try:
        bet = parse_amount(parts[1])
    except:
        return await message.answer("❌ Неверная ставка")
    if bet < MIN_BET:
        return await message.answer(f"❌ Минимум {fmt_money(MIN_BET)}")
    
    ok, _ = reserve_bet(message.from_user.id, bet)
    if not ok:
        return await message.answer("❌ Недостаточно средств")
    
    dice = await message.answer_dice(emoji="⚽")
    win = dice.dice.value >= 4
    payout = bet * 1.85 if win else 0
    bal = finalize_reserved_bet(message.from_user.id, bet, payout, "football", f"value={dice.dice.value}")
    await message.answer(f"⚽ {'Гол!' if win else 'Мимо'}\n{'✅ Победа!' if win else '❌ Поражение'}\n💰 Выплата: {fmt_money(payout)}\n💎 Баланс: {fmt_money(bal)}")

# БАСКЕТ
@dp.message(lambda m: normalize_text(m.text).startswith("баскет"))
async def basket_game(message: Message):
    if not check_cooldown(message.from_user.id):
        return await message.answer("⏳ Подождите")
    parts = message.text.split()
    if len(parts) != 2:
        return await message.answer("❌ Формат: `баскет 100`")
    try:
        bet = parse_amount(parts[1])
    except:
        return await message.answer("❌ Неверная ставка")
    if bet < MIN_BET:
        return await message.answer(f"❌ Минимум {fmt_money(MIN_BET)}")
    
    ok, _ = reserve_bet(message.from_user.id, bet)
    if not ok:
        return await message.answer("❌ Недостаточно средств")
    
    dice = await message.answer_dice(emoji="🏀")
    win = dice.dice.value >= 4
    payout = bet * 1.85 if win else 0
    bal = finalize_reserved_bet(message.from_user.id, bet, payout, "basket", f"value={dice.dice.value}")
    await message.answer(f"🏀 {'Попадание!' if win else 'Промах'}\n{'✅ Победа!' if win else '❌ Поражение'}\n💰 Выплата: {fmt_money(payout)}\n💎 Баланс: {fmt_money(bal)}")

# БАШНЯ
@dp.message(lambda m: normalize_text(m.text).startswith("башня"))
async def tower_start(message: Message):
    parts = message.text.split()
    if len(parts) != 2:
        return await message.answer("❌ Формат: `башня 100`")
    try:
        bet = parse_amount(parts[1])
    except:
        return await message.answer("❌ Неверная ставка")
    if bet < MIN_BET:
        return await message.answer(f"❌ Минимум {fmt_money(MIN_BET)}")
    
    ok, _ = reserve_bet(message.from_user.id, bet)
    if not ok:
        return await message.answer("❌ Недостаточно средств")
    
    TOWER_GAMES[message.from_user.id] = {"bet": bet, "level": 0}
    await message.answer(f"🗼 <b>Башня</b>\nСтавка: {fmt_money(bet)}\nЭтаж: 0/8\nВыберите секцию:", reply_markup=tower_kb())

@dp.callback_query(F.data.startswith("tower:"))
async def tower_callback(query: CallbackQuery):
    user_id = query.from_user.id
    game = TOWER_GAMES.get(user_id)
    if not game:
        return await query.answer("❌ Нет игры", show_alert=True)
    
    action = query.data.split(":")[-1]
    
    if action == "cancel":
        bal = finalize_reserved_bet(user_id, game["bet"], game["bet"], "tower", "cancel")
        TOWER_GAMES.pop(user_id)
        await query.message.edit_text(f"❌ Игра отменена\n💰 Возврат: {fmt_money(game['bet'])}\n💎 Баланс: {fmt_money(bal)}")
        return await query.answer()
    
    if action == "cash":
        if game["level"] == 0:
            return await query.answer("❌ Сначала сделайте ход", show_alert=True)
        mult = TOWER_MULTIPLIERS[game["level"]-1]
        payout = game["bet"] * mult
        bal = finalize_reserved_bet(user_id, game["bet"], payout, "tower", "cashout")
        TOWER_GAMES.pop(user_id)
        await query.message.edit_text(f"✅ Выигрыш!\n💰 Выплата: {fmt_money(payout)}\n💎 Баланс: {fmt_money(bal)}")
        return await query.answer()
    
    # pick
    chosen = int(action)
    safe = random.randint(1, 3)
    if chosen != safe:
        bal = finalize_reserved_bet(user_id, game["bet"], 0, "tower", "lose")
        TOWER_GAMES.pop(user_id)
        await query.message.edit_text(f"💥 Ловушка в {safe}!\n❌ Проигрыш\n💎 Баланс: {fmt_money(bal)}")
        return await query.answer()
    
    game["level"] += 1
    if game["level"] >= len(TOWER_MULTIPLIERS):
        payout = game["bet"] * TOWER_MULTIPLIERS[-1]
        bal = finalize_reserved_bet(user_id, game["bet"], payout, "tower", "win")
        TOWER_GAMES.pop(user_id)
        await query.message.edit_text(f"🏆 ПОБЕДА! Башня пройдена!\n💰 Выплата: {fmt_money(payout)}\n💎 Баланс: {fmt_money(bal)}")
        return await query.answer()
    
    TOWER_GAMES[user_id] = game
    await query.message.edit_text(
        f"🗼 <b>Башня</b>\nСтавка: {fmt_money(game['bet'])}\nЭтаж: {game['level']}/8\nМножитель: x{TOWER_MULTIPLIERS[game['level']-1]:.2f}\n💰 Потенциал: {fmt_money(game['bet'] * TOWER_MULTIPLIERS[game['level']-1])}",
        reply_markup=tower_kb()
    )
    await query.answer("✅ Успех!")

# ЗОЛОТО
@dp.message(lambda m: normalize_text(m.text).startswith("золото"))
async def gold_start(message: Message):
    parts = message.text.split()
    if len(parts) != 2:
        return await message.answer("❌ Формат: `золото 100`")
    try:
        bet = parse_amount(parts[1])
    except:
        return await message.answer("❌ Неверная ставка")
    if bet < MIN_BET:
        return await message.answer(f"❌ Минимум {fmt_money(MIN_BET)}")
    
    ok, _ = reserve_bet(message.from_user.id, bet)
    if not ok:
        return await message.answer("❌ Недостаточно средств")
    
    GOLD_GAMES[message.from_user.id] = {"bet": bet, "step": 0}
    await message.answer(f"🥇 <b>Золото</b>\nСтавка: {fmt_money(bet)}\nШаг: 0/7\nВыберите плитку:", reply_markup=gold_kb())

@dp.callback_query(F.data.startswith("gold:"))
async def gold_callback(query: CallbackQuery):
    user_id = query.from_user.id
    game = GOLD_GAMES.get(user_id)
    if not game:
        return await query.answer("❌ Нет игры", show_alert=True)
    
    action = query.data.split(":")[-1]
    
    if action == "cancel":
        bal = finalize_reserved_bet(user_id, game["bet"], game["bet"], "gold", "cancel")
        GOLD_GAMES.pop(user_id)
        await query.message.edit_text(f"❌ Игра отменена\n💰 Возврат: {fmt_money(game['bet'])}\n💎 Баланс: {fmt_money(bal)}")
        return await query.answer()
    
    if action == "cash":
        if game["step"] == 0:
            return await query.answer("❌ Сначала сделайте ход", show_alert=True)
        mult = GOLD_MULTIPLIERS[game["step"]-1]
        payout = game["bet"] * mult
        bal = finalize_reserved_bet(user_id, game["bet"], payout, "gold", "cashout")
        GOLD_GAMES.pop(user_id)
        await query.message.edit_text(f"✅ Выигрыш!\n💰 Выплата: {fmt_money(payout)}\n💎 Баланс: {fmt_money(bal)}")
        return await query.answer()
    
    chosen = int(action)
    trap = random.randint(1, 4)
    if chosen == trap:
        bal = finalize_reserved_bet(user_id, game["bet"], 0, "gold", "lose")
        GOLD_GAMES.pop(user_id)
        await query.message.edit_text(f"💥 Ловушка в {trap}!\n❌ Проигрыш\n💎 Баланс: {fmt_money(bal)}")
        return await query.answer()
    
    game["step"] += 1
    if game["step"] >= len(GOLD_MULTIPLIERS):
        payout = game["bet"] * GOLD_MULTIPLIERS[-1]
        bal = finalize_reserved_bet(user_id, game["bet"], payout, "gold", "win")
        GOLD_GAMES.pop(user_id)
        await query.message.edit_text(f"🏆 ПОБЕДА! Золото пройдено!\n💰 Выплата: {fmt_money(payout)}\n💎 Баланс: {fmt_money(bal)}")
        return await query.answer()
    
    GOLD_GAMES[user_id] = game
    await query.message.edit_text(
        f"🥇 <b>Золото</b>\nСтавка: {fmt_money(game['bet'])}\nШаг: {game['step']}/7\nМножитель: x{GOLD_MULTIPLIERS[game['step']-1]:.2f}\n💰 Потенциал: {fmt_money(game['bet'] * GOLD_MULTIPLIERS[game['step']-1])}",
        reply_markup=gold_kb()
    )
    await query.answer("✅ Успех!")

# АЛМАЗЫ
@dp.message(lambda m: normalize_text(m.text).startswith("алмазы"))
async def diamond_start(message: Message):
    parts = message.text.split()
    if len(parts) != 2:
        return await message.answer("❌ Формат: `алмазы 100`")
    try:
        bet = parse_amount(parts[1])
    except:
        return await message.answer("❌ Неверная ставка")
    if bet < MIN_BET:
        return await message.answer(f"❌ Минимум {fmt_money(MIN_BET)}")
    
    ok, _ = reserve_bet(message.from_user.id, bet)
    if not ok:
        return await message.answer("❌ Недостаточно средств")
    
    DIAMOND_GAMES[message.from_user.id] = {"bet": bet, "step": 0}
    await message.answer(f"💎 <b>Алмазы</b>\nСтавка: {fmt_money(bet)}\nШаг: 0/8\nВыберите кристалл:", reply_markup=diamond_kb())

@dp.callback_query(F.data.startswith("diamond:"))
async def diamond_callback(query: CallbackQuery):
    user_id = query.from_user.id
    game = DIAMOND_GAMES.get(user_id)
    if not game:
        return await query.answer("❌ Нет игры", show_alert=True)
    
    action = query.data.split(":")[-1]
    
    if action == "cancel":
        bal = finalize_reserved_bet(user_id, game["bet"], game["bet"], "diamond", "cancel")
        DIAMOND_GAMES.pop(user_id)
        await query.message.edit_text(f"❌ Игра отменена\n💰 Возврат: {fmt_money(game['bet'])}\n💎 Баланс: {fmt_money(bal)}")
        return await query.answer()
    
    if action == "cash":
        if game["step"] == 0:
            return await query.answer("❌ Сначала сделайте ход", show_alert=True)
        mult = DIAMOND_MULTIPLIERS[game["step"]-1]
        payout = game["bet"] * mult
        bal = finalize_reserved_bet(user_id, game["bet"], payout, "diamond", "cashout")
        DIAMOND_GAMES.pop(user_id)
        await query.message.edit_text(f"✅ Выигрыш!\n💰 Выплата: {fmt_money(payout)}\n💎 Баланс: {fmt_money(bal)}")
        return await query.answer()
    
    chosen = int(action)
    trap = random.randint(1, 5)
    if chosen == trap:
        bal = finalize_reserved_bet(user_id, game["bet"], 0, "diamond", "lose")
        DIAMOND_GAMES.pop(user_id)
        await query.message.edit_text(f"💥 Бракованный кристалл {trap}!\n❌ Проигрыш\n💎 Баланс: {fmt_money(bal)}")
        return await query.answer()
    
    game["step"] += 1
    if game["step"] >= len(DIAMOND_MULTIPLIERS):
        payout = game["bet"] * DIAMOND_MULTIPLIERS[-1]
        bal = finalize_reserved_bet(user_id, game["bet"], payout, "diamond", "win")
        DIAMOND_GAMES.pop(user_id)
        await query.message.edit_text(f"🏆 ПОБЕДА! Алмазы пройдены!\n💰 Выплата: {fmt_money(payout)}\n💎 Баланс: {fmt_money(bal)}")
        return await query.answer()
    
    DIAMOND_GAMES[user_id] = game
    await query.message.edit_text(
        f"💎 <b>Алмазы</b>\nСтавка: {fmt_money(game['bet'])}\nШаг: {game['step']}/8\nМножитель: x{DIAMOND_MULTIPLIERS[game['step']-1]:.2f}\n💰 Потенциал: {fmt_money(game['bet'] * DIAMOND_MULTIPLIERS[game['step']-1])}",
        reply_markup=diamond_kb()
    )
    await query.answer("✅ Успех!")

# МИНЫ
def mines_multiplier(opened: int, mines: int) -> float:
    safe = 9 - mines
    if opened <= 0:
        return 1.0
    return round((9 / safe) ** opened * 0.95, 2)

@dp.message(lambda m: normalize_text(m.text).startswith("мины"))
async def mines_start(message: Message, state: FSMContext):
    parts = message.text.split()
    if len(parts) < 2:
        return await message.answer("❌ Формат: `мины 100 3`")
    try:
        bet = parse_amount(parts[1])
    except:
        return await message.answer("❌ Неверная ставка")
    if bet < MIN_BET:
        return await message.answer(f"❌ Минимум {fmt_money(MIN_BET)}")
    
    mines = 3
    if len(parts) > 2:
        try:
            mines = int(parts[2])
        except:
            pass
    if mines < 1 or mines > 5:
        return await message.answer("❌ Количество мин от 1 до 5")
    
    ok, _ = reserve_bet(message.from_user.id, bet)
    if not ok:
        return await message.answer("❌ Недостаточно средств")
    
    cells = list(range(1, 10))
    mines_set = set(random.sample(cells, mines))
    MINES_GAMES[message.from_user.id] = {"bet": bet, "mines_count": mines, "mines": mines_set, "opened": set()}
    await message.answer(f"💣 <b>Мины</b>\nСтавка: {fmt_money(bet)}\nМин: {mines}\nОткрыто: 0/9\nВыберите клетку:", reply_markup=mines_kb(MINES_GAMES[message.from_user.id]))

@dp.callback_query(F.data == "mines:noop")
async def mines_noop(query: CallbackQuery):
    await query.answer()

@dp.callback_query(F.data.startswith("mines:"))
async def mines_callback(query: CallbackQuery):
    user_id = query.from_user.id
    game = MINES_GAMES.get(user_id)
    if not game:
        return await query.answer("❌ Нет игры", show_alert=True)
    
    action = query.data.split(":")[-1]
    
    if action == "cancel":
        if len(game["opened"]) == 0:
            payout = game["bet"]
        else:
            mult = mines_multiplier(len(game["opened"]), game["mines_count"])
            payout = game["bet"] * mult
        bal = finalize_reserved_bet(user_id, game["bet"], payout, "mines", "cancel")
        MINES_GAMES.pop(user_id)
        await query.message.edit_text(f"❌ Игра завершена\n💰 Выплата: {fmt_money(payout)}\n💎 Баланс: {fmt_money(bal)}")
        return await query.answer()
    
    if action == "cash":
        if len(game["opened"]) == 0:
            return await query.answer("❌ Сначала откройте клетку", show_alert=True)
        mult = mines_multiplier(len(game["opened"]), game["mines_count"])
        payout = game["bet"] * mult
        bal = finalize_reserved_bet(user_id, game["bet"], payout, "mines", "cashout")
        MINES_GAMES.pop(user_id)
        await query.message.edit_text(f"✅ Выигрыш!\n💰 Выплата: {fmt_money(payout)}\n💎 Баланс: {fmt_money(bal)}")
        return await query.answer()
    
    # открытие клетки
    try:
        idx = int(action)
    except:
        return await query.answer()
    
    if idx in game["opened"]:
        return await query.answer("❌ Уже открыто", show_alert=True)
    
    if idx in game["mines"]:
        bal = finalize_reserved_bet(user_id, game["bet"], 0, "mines", "explode")
        MINES_GAMES.pop(user_id)
        await query.message.edit_text(f"💥 МИНА в {idx}!\n❌ Проигрыш\n💎 Баланс: {fmt_money(bal)}")
        return await query.answer()
    
    game["opened"].add(idx)
    safe_total = 9 - game["mines_count"]
    
    if len(game["opened"]) >= safe_total:
        mult = mines_multiplier(len(game["opened"]), game["mines_count"])
        payout = game["bet"] * mult
        bal = finalize_reserved_bet(user_id, game["bet"], payout, "mines", "win")
        MINES_GAMES.pop(user_id)
        await query.message.edit_text(f"🏆 ПОБЕДА! Все безопасные клетки найдены!\n💰 Выплата: {fmt_money(payout)}\n💎 Баланс: {fmt_money(bal)}")
        return await query.answer()
    
    MINES_GAMES[user_id] = game
    mult = mines_multiplier(len(game["opened"]), game["mines_count"])
    await query.message.edit_text(
        f"💣 <b>Мины</b>\nСтавка: {fmt_money(game['bet'])}\nМин: {game['mines_count']}\nОткрыто: {len(game['opened'])}/9\nМножитель: x{mult:.2f}\n💰 Потенциал: {fmt_money(game['bet'] * mult)}",
        reply_markup=mines_kb(game)
    )
    await query.answer("✅ Безопасно!")

# ОЧКО
def make_deck():
    ranks = ["2","3","4","5","6","7","8","9","10","J","Q","K","A"]
    suits = ["♠","♥","♦","♣"]
    deck = [(r,s) for r in ranks for s in suits]
    random.shuffle(deck)
    return deck

def card_value(rank):
    if rank in ["J","Q","K"]:
        return 10
    if rank == "A":
        return 11
    return int(rank)

def hand_value(cards):
    total = sum(card_value(r) for r,_ in cards)
    aces = sum(1 for r,_ in cards if r == "A")
    while total > 21 and aces > 0:
        total -= 10
        aces -= 1
    return total

@dp.message(lambda m: normalize_text(m.text).startswith("очко"))
async def ochko_start(message: Message, state: FSMContext):
    parts = message.text.split()
    if len(parts) != 2:
        return await message.answer("❌ Формат: `очко 100`")
    try:
        bet = parse_amount(parts[1])
    except:
        return await message.answer("❌ Неверная ставка")
    if bet < MIN_BET:
        return await message.answer(f"❌ Минимум {fmt_money(MIN_BET)}")
    
    await state.update_data(bet=bet)
    await state.set_state(OchkoStates.waiting_confirm)
    await message.answer(f"🎴 Ставка: {fmt_money(bet)}\nНачать игру?", reply_markup=ochko_confirm_kb())

@dp.callback_query(OchkoStates.waiting_confirm, F.data == "ochko:cancel")
async def ochko_cancel(query: CallbackQuery, state: FSMContext):
    await state.clear()
    await query.message.edit_text("❌ Игра отменена")
    await query.answer()

@dp.callback_query(OchkoStates.waiting_confirm, F.data == "ochko:start")
async def ochko_start_game(query: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    bet = data.get("bet", 0)
    if bet <= 0:
        await state.clear()
        return await query.answer("❌ Ошибка", show_alert=True)
    
    ok, _ = reserve_bet(query.from_user.id, bet)
    await state.clear()
    if not ok:
        return await query.message.edit_text("❌ Недостаточно средств")
    
    deck = make_deck()
    player = [deck.pop(), deck.pop()]
    dealer = [deck.pop(), deck.pop()]
    OCHKO_GAMES[query.from_user.id] = {"bet": bet, "deck": deck, "player": player, "dealer": dealer}
    
    pv = hand_value(player)
    if pv == 21:
        dv = hand_value(dealer)
        if dv == 21:
            payout = bet
            msg = "🤝 Ничья!"
        else:
            payout = bet * 2.5
            msg = "🎉 BLACKJACK!"
        bal = finalize_reserved_bet(query.from_user.id, bet, payout, "ochko", "blackjack")
        OCHKO_GAMES.pop(query.from_user.id)
        await query.message.edit_text(f"🎴 BLACKJACK!\n💰 Выплата: {fmt_money(payout)}\n💎 Баланс: {fmt_money(bal)}")
        return await query.answer()
    
    await query.message.edit_text(
        f"🎴 <b>Очко</b>\nСтавка: {fmt_money(bet)}\n\nДилер: ??\nТы: {player[0][0]}{player[0][1]} {player[1][0]}{player[1][1]} ({pv})",
        reply_markup=ochko_kb()
    )
    await query.answer()

@dp.callback_query(F.data == "ochko:hit")
async def ochko_hit(query: CallbackQuery):
    user_id = query.from_user.id
    game = OCHKO_GAMES.get(user_id)
    if not game:
        return await query.answer("❌ Нет игры", show_alert=True)
    
    game["player"].append(game["deck"].pop())
    pv = hand_value(game["player"])
    
    if pv > 21:
        bal = finalize_reserved_bet(user_id, game["bet"], 0, "ochko", "bust")
        OCHKO_GAMES.pop(user_id)
        await query.message.edit_text(f"🎴 Перебор ({pv})!\n❌ Проигрыш\n💎 Баланс: {fmt_money(bal)}")
        return await query.answer()
    
    await query.message.edit_text(
        f"🎴 <b>Очко</b>\nСтавка: {fmt_money(game['bet'])}\n\nДилер: ??\nТы: {' '.join(f'{r}{s}' for r,s in game['player'])} ({pv})",
        reply_markup=ochko_kb()
    )
    await query.answer()

@dp.callback_query(F.data == "ochko:stand")
async def ochko_stand(query: CallbackQuery):
    user_id = query.from_user.id
    game = OCHKO_GAMES.get(user_id)
    if not game:
        return await query.answer("❌ Нет игры", show_alert=True)
    
    while hand_value(game["dealer"]) < 17:
        game["dealer"].append(game["deck"].pop())
    
    pv = hand_value(game["player"])
    dv = hand_value(game["dealer"])
    
    if dv > 21 or pv > dv:
        payout = game["bet"] * 2
        outcome = "win"
    elif pv == dv:
        payout = game["bet"]
        outcome = "push"
    else:
        payout = 0
        outcome = "lose"
    
    bal = finalize_reserved_bet(user_id, game["bet"], payout, "ochko", outcome)
    OCHKO_GAMES.pop(user_id)
    
    dealer_str = ' '.join(f'{r}{s}' for r,s in game["dealer"])
    player_str = ' '.join(f'{r}{s}' for r,s in game["player"])
    
    await query.message.edit_text(
        f"🎴 <b>Очко</b>\nСтавка: {fmt_money(game['bet'])}\n\n"
        f"Дилер: {dealer_str} ({dv})\n"
        f"Ты: {player_str} ({pv})\n\n"
        f"{'✅ Победа!' if payout > game['bet'] else ('🤝 Ничья' if payout == game['bet'] else '❌ Поражение')}\n"
        f"💰 Выплата: {fmt_money(payout)}\n💎 Баланс: {fmt_money(bal)}"
    )
    await query.answer()

# ==================== ЧЕКИ ====================
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
                     (code, str(user_id), round(per_user,2), count, "[]"))
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

@dp.message(lambda m: normalize_text(m.text) in {"чеки"})
async def checks_command(message: Message):
    await message.answer("🧾 <b>Чеки</b>", reply_markup=checks_kb())

@dp.callback_query(F.data == "checks:create")
async def checks_create_cb(query: CallbackQuery, state: FSMContext):
    await state.set_state(CheckCreateStates.waiting_amount)
    await query.message.answer("💰 Сумма на 1 активацию:")
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
def create_promo(code: str, reward: float, activations: int):
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO promos (name, reward, claimed, remaining_activations) VALUES (?, ?, '[]', ?)",
                 (code.upper(), round(reward,2), activations))
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

@dp.message(lambda m: normalize_text(m.text).startswith("промо"))
async def promo_command(message: Message, state: FSMContext):
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
def add_deposit(user_id: int, amount: float, term_days: int):
    rate = BANK_TERMS.get(term_days)
    if not rate:
        return False, "Неверный срок"
    ok, _ = reserve_bet(user_id, amount)
    if not ok:
        return False, "Недостаточно средств"
    conn = get_db()
    conn.execute("INSERT INTO bank_deposits (user_id, principal, rate, term_days, opened_at, status) VALUES (?, ?, ?, ?, ?, 'active')",
                 (str(user_id), round(amount,2), rate, term_days, now_ts()))
    conn.commit()
    conn.close()
    return True, f"Депозит открыт!"

def withdraw_matured_deposits(user_id: int):
    now = now_ts()
    conn = get_db()
    total, count = 0, 0
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
            conn.execute("UPDATE users SET coins = coins + ? WHERE id=?", (round(total,2), str(user_id)))
        conn.commit()
        return count, round(total,2)
    except:
        conn.rollback()
        return 0, 0
    finally:
        conn.close()

@dp.message(lambda m: normalize_text(m.text) in {"банк"})
async def bank_command(message: Message):
    user = get_user(message.from_user.id)
    conn = get_db()
    active = conn.execute("SELECT COUNT(*) as c, COALESCE(SUM(principal),0) as s FROM bank_deposits WHERE user_id=? AND status='active'", (str(message.from_user.id),)).fetchone()
    conn.close()
    await message.answer(
        f"🏦 <b>Банк</b>\n\n💰 Баланс: {fmt_money(float(user['coins']))}\n"
        f"📊 Активных: {active['c']}\n💵 Сумма: {fmt_money(active['s'])}\n\n📈 Ставки: 7д(+3%), 14д(+7%), 30д(+18%)",
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

# ==================== АДМИНКА ====================
@dp.message(Command("addpromo"))
async def addpromo_command(message: Message):
    if not is_admin_user(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) != 4:
        return await message.answer("📝 /addpromo КОД СУММА АКТИВАЦИИ")
    code = parts[1].upper()
    try:
        reward = parse_amount(parts[2])
        activations = int(parts[3])
    except:
        return await message.answer("❌ Неверные данные")
    create_promo(code, reward, activations)
    await message.answer(f"✅ Промокод {code} создан!\n💰 {fmt_money(reward)} x{activations}")

@dp.message(Command("ban"))
async def admin_ban(message: Message):
    if not is_admin_user(message.from_user.id):
        return
    target = message.reply_to_message.from_user if message.reply_to_message else None
    if not target:
        parts = message.text.split()
        if len(parts) < 2:
            return await message.answer("📝 Ответьте на сообщение или укажите ID")
        try:
            target_id = int(parts[1])
            target = await message.bot.get_chat(target_id)
        except:
            return await message.answer("❌ Пользователь не найден")
    ban_user(target.id)
    await message.answer(f"🚫 {mention_user(target.id)} забанен!")

@dp.message(Command("unban"))
async def admin_unban(message: Message):
    if not is_admin_user(message.from_user.id):
        return
    target = message.reply_to_message.from_user if message.reply_to_message else None
    if not target:
        parts = message.text.split()
        if len(parts) < 2:
            return
        try:
            target_id = int(parts[1])
        except:
            return
    else:
        target_id = target.id
    unban_user(target_id)
    await message.answer(f"✅ Пользователь разбанен")

@dp.message(Command("mute"))
async def admin_mute(message: Message):
    if not is_admin_user(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 3:
        return await message.answer("📝 /mute @user 5")
    target = message.reply_to_message.from_user if message.reply_to_message else None
    if not target:
        try:
            target_id = int(parts[1])
            target = await message.bot.get_chat(target_id)
        except:
            return await message.answer("❌ Пользователь не найден")
        minutes = int(parts[2])
    else:
        minutes = int(parts[1])
    mute_user(target.id, minutes)
    await message.answer(f"🔇 {mention_user(target.id)} замьючен на {minutes} мин")

@dp.message(Command("unmute"))
async def admin_unmute(message: Message):
    if not is_admin_user(message.from_user.id):
        return
    target = message.reply_to_message.from_user if message.reply_to_message else None
    if not target:
        parts = message.text.split()
        if len(parts) < 2:
            return
        try:
            target_id = int(parts[1])
        except:
            return
    else:
        target_id = target.id
    unmute_user(target_id)
    await message.answer(f"✅ {mention_user(target_id)} размучен")

@dp.message(Command("выдать"))
async def admin_give(message: Message):
    if not is_admin_user(message.from_user.id):
        return
    target = message.reply_to_message.from_user if message.reply_to_message else None
    if not target:
        parts = message.text.split()
        if len(parts) < 3:
            return await message.answer("📝 /выдать @user 1000")
        try:
            target_id = int(parts[1])
            target = await message.bot.get_chat(target_id)
        except:
            if parts[1].startswith("@"):
                try:
                    chat = await message.bot.get_chat(parts[1])
                    target = chat
                except:
                    return await message.answer("❌ Пользователь не найден")
            else:
                return await message.answer("❌ Неверный ID")
        amount = parse_amount(parts[2]) if len(parts) > 2 else 0
    else:
        amount = parse_amount(parts[1]) if len(parts) > 1 else 0
    if amount <= 0:
        return await message.answer("❌ Введите сумму")
    bal = add_balance(target.id, amount)
    await message.answer(f"✅ {mention_user(target.id)} выдано {fmt_money(amount)}\n💰 Новый баланс: {fmt_money(bal)}")

@dp.message(Command("broadcast"))
async def admin_broadcast(message: Message, state: FSMContext):
    if not is_admin_user(message.from_user.id):
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
            await message.bot.send_message(int(row["id"]), text)
            sent += 1
            await asyncio.sleep(0.05)
        except:
            pass
    await message.answer(f"📢 Рассылка завершена!\n✅ Отправлено: {sent}")

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
            await message.bot.send_message(int(row["id"]), text)
            sent += 1
            await asyncio.sleep(0.05)
        except:
            pass
    await message.answer(f"📢 Рассылка завершена!\n✅ Отправлено: {sent}")

@dp.message(Command("massbonus"))
async def admin_mass_bonus(message: Message):
    if not is_admin_user(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) != 2:
        return await message.answer("📝 /massbonus 100")
    try:
        amount = parse_amount(parts[1])
    except:
        return await message.answer("❌ Неверная сумма")
    conn = get_db()
    conn.execute("UPDATE users SET coins = coins + ?", (amount,))
    conn.commit()
    conn.close()
    await message.answer(f"✅ Всем начислено по {fmt_money(amount)}!")

@dp.message(Command("stats"))
async def admin_stats(message: Message):
    if not is_admin_user(message.from_user.id):
        return
    conn = get_db()
    users = conn.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]
    bets = conn.execute("SELECT COUNT(*) as c, SUM(payout) as p, SUM(bet_amount) as b FROM bets").fetchone()
    sys = conn.execute("SELECT coins FROM system_balance WHERE id=1").fetchone()
    conn.close()
    await message.answer(
        f"📊 <b>Статистика</b>\n\n"
        f"👥 Пользователей: {users}\n"
        f"🎲 Ставок: {bets['c'] or 0}\n"
        f"💰 Ставок на сумму: {fmt_money(bets['b'] or 0)}\n"
        f"💸 Выплачено: {fmt_money(bets['p'] or 0)}\n"
        f"🏦 Комиссий: {fmt_money(sys['coins'] if sys else 0)}"
    )

@dp.message(Command("ref"))
async def ref_command(message: Message):
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
async def donate_command(message: Message):
    await message.answer(
        f"⭐ <b>Пополнение {CURRENCY_NAME}</b>\n\n1 Star = {STARS_RATE} {CURRENCY_NAME}\n\nВыберите в меню /menu",
        reply_markup=main_menu_kb()
    )

# ==================== ОТМЕНА ====================
@dp.message(lambda m: normalize_text(m.text) in {"отмена"})
async def cancel_any(message: Message, state: FSMContext):
    await state.clear()
    TOWER_GAMES.pop(message.from_user.id, None)
    GOLD_GAMES.pop(message.from_user.id, None)
    DIAMOND_GAMES.pop(message.from_user.id, None)
    MINES_GAMES.pop(message.from_user.id, None)
    OCHKO_GAMES.pop(message.from_user.id, None)
    await message.answer("🛑 Отменено")

# ==================== ЗАПУСК ====================
async def main():
    init_db()
    dp.message.middleware(BanMuteSubscriptionMiddleware())
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await bot.delete_webhook(drop_pending_updates=True)
    print("✅ Бот VIRTEX запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
