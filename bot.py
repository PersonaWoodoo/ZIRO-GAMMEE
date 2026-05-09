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
from aiogram.utils.deep_linking import create_start_link

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
    abs_val = abs(value)
    if abs_val >= 1000:
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
        
        if event.text and any(word in event.text.lower() for word in ["краш", "рул", "баскет", "футбол", "дартс", "боулинг", "кубик", "слоты", "очко", "башня", "золото", "алмазы", "мины", "рыбалка", "скретч", "квак", "хило", "пирамида", "арена", "казино", "хоккей", "дуэль", "пер"]):
            ok, not_subscribed = await check_subscriptions(user_id, data["bot"])
            if not ok:
                await event.answer("⚠️ Подпишитесь на каналы!", reply_markup=subscription_keyboard(not_subscribed))
                return
        
        return await handler(event, data)

# ==================== СОСТОЯНИЯ FSM ====================
class CheckCreateStates(StatesGroup):
    waiting_amount = State()
    waiting_count = State()

class CheckClaimStates(StatesGroup):
    waiting_code = State()

class PromoStates(StatesGroup):
    waiting_code = State()

class NewPromoStates(StatesGroup):
    waiting_code = State()
    waiting_reward = State()
    waiting_activations = State()

class BankStates(StatesGroup):
    waiting_amount = State()

class RouletteStates(StatesGroup):
    waiting_bet = State()
    waiting_choice = State()

class CrashStates(StatesGroup):
    waiting_bet = State()
    waiting_mult = State()

class DiceStates(StatesGroup):
    waiting_bet = State()
    waiting_choice = State()

class FootballStates(StatesGroup):
    waiting_bet = State()
    waiting_choice = State()

class BasketballStates(StatesGroup):
    waiting_bet = State()

class DartsStates(StatesGroup):
    waiting_bet = State()

class BowlingStates(StatesGroup):
    waiting_bet = State()

class SlotsStates(StatesGroup):
    waiting_bet = State()

class OchkoStates(StatesGroup):
    waiting_bet = State()
    waiting_confirm = State()

class TowerStates(StatesGroup):
    waiting_bet = State()

class GoldStates(StatesGroup):
    waiting_bet = State()

class DiamondStates(StatesGroup):
    waiting_bet = State()

class MinesStates(StatesGroup):
    waiting_bet = State()
    waiting_mines = State()

class FishingStates(StatesGroup):
    waiting_bet = State()

class ScratchStates(StatesGroup):
    waiting_bet = State()

class KvakStates(StatesGroup):
    waiting_bet = State()

class HiLoStates(StatesGroup):
    waiting_bet = State()
    waiting_choice = State()

class PyramidStates(StatesGroup):
    waiting_bet = State()

class ArenaStates(StatesGroup):
    waiting_bet = State()

class CasinoStates(StatesGroup):
    waiting_bet = State()

class HockeyStates(StatesGroup):
    waiting_bet = State()

class DuelStates(StatesGroup):
    waiting_bet = State()

class AdminBroadcastStates(StatesGroup):
    waiting_message = State()

# ==================== ГЛОБАЛЬНЫЕ СЛОВАРИ ====================
TOWER_GAMES = {}
GOLD_GAMES = {}
DIAMOND_GAMES = {}
MINES_GAMES = {}
OCHKO_GAMES = {}
PYRAMID_GAMES = {}
ARENA_GAMES = {}
CASINO_GAMES = {}
HOCKEY_GAMES = {}
DUEL_GAMES = {}

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

# ==================== ТЕКСТ ПОМОЩИ И МЕНЮ ====================
def get_help_text() -> str:
    return """
<b>🎮 Игровой бот VIRTEX</b>

<b>💰 Баланс и бонусы</b>
• <code>б</code> или <code>баланс</code> - показать баланс
• <code>профиль</code> - статистика
• <code>бонус</code> - получить бонус

<b>🎲 Игры</b>
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
• <code>рыбалка 100</code> - Рыбалка
• <code>скретч 100</code> - Скретч
• <code>квак 100</code> - Квак
• <code>хило 100</code> - HiLo
• <code>пирамида 100</code> - Пирамида
• <code>арена 100</code> - Arena
• <code>казино 100</code> - Казино
• <code>хоккей 100</code> - Хоккей
• <code>дуэль 100</code> - Дуэль

<b>💸 Переводы</b>
• <code>пер @username 100</code> - комиссия 5%

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
        [InlineKeyboardButton(text="➕ Добавить в чат", callback_data="menu:add_chat")],
        [InlineKeyboardButton(text="❓ Помощь", callback_data="menu:help")],
    ])

def games_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📈 Краш", callback_data="game:crash"), InlineKeyboardButton(text="🎡 Рулетка", callback_data="game:roulette")],
        [InlineKeyboardButton(text="🏀 Баскет", callback_data="game:basket"), InlineKeyboardButton(text="⚽ Футбол", callback_data="game:football")],
        [InlineKeyboardButton(text="🎯 Дартс", callback_data="game:darts"), InlineKeyboardButton(text="🎳 Боулинг", callback_data="game:bowling")],
        [InlineKeyboardButton(text="🎲 Кубик", callback_data="game:dice"), InlineKeyboardButton(text="🎰 Слоты", callback_data="game:slots")],
        [InlineKeyboardButton(text="🎴 Очко", callback_data="game:ochko"), InlineKeyboardButton(text="🗼 Башня", callback_data="game:tower")],
        [InlineKeyboardButton(text="🥇 Золото", callback_data="game:gold"), InlineKeyboardButton(text="💎 Алмазы", callback_data="game:diamond")],
        [InlineKeyboardButton(text="💣 Мины", callback_data="game:mines"), InlineKeyboardButton(text="🐟 Рыбалка", callback_data="game:fishing")],
        [InlineKeyboardButton(text="🎫 Скретч", callback_data="game:scratch"), InlineKeyboardButton(text="🐸 Квак", callback_data="game:kvak")],
        [InlineKeyboardButton(text="🃏 HiLo", callback_data="game:hilo"), InlineKeyboardButton(text="🔺 Пирамида", callback_data="game:pyramid")],
        [InlineKeyboardButton(text="⚔️ Arena", callback_data="game:arena"), InlineKeyboardButton(text="🏆 Казино", callback_data="game:casino")],
        [InlineKeyboardButton(text="🏒 Хоккей", callback_data="game:hockey"), InlineKeyboardButton(text="🤺 Дуэль", callback_data="game:duel")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="menu:back")],
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
        [InlineKeyboardButton(text="📊 1-12", callback_data="roulette:1-12"), InlineKeyboardButton(text="📊 13-24", callback_data="roulette:13-24"), InlineKeyboardButton(text="📊 25-36", callback_data="roulette:25-36")],
        [InlineKeyboardButton(text="🔳 1-18", callback_data="roulette:low"), InlineKeyboardButton(text="🔳 19-36", callback_data="roulette:high")],
        [InlineKeyboardButton(text="0️⃣ Зеро (x36)", callback_data="roulette:zero")],
    ])

def ochko_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Взять", callback_data="ochko:hit"), InlineKeyboardButton(text="✋ Стоп", callback_data="ochko:stand")],
    ])

def ochko_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Начать", callback_data="ochko:start"), InlineKeyboardButton(text="❌ Отмена", callback_data="ochko:cancel")],
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

# ==================== КОМАНДЫ СТАРТ И ПОМОЩЬ ====================
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
    user = get_user(query.from_user.id)
    conn = get_db()
    active = conn.execute("SELECT COUNT(*) as c, COALESCE(SUM(principal),0) as s FROM bank_deposits WHERE user_id=? AND status='active'", (str(query.from_user.id),)).fetchone()
    conn.close()
    await query.message.edit_text(
        f"🏦 <b>Банк</b>\n\n💰 Баланс: {fmt_money(float(user['coins']))}\n📊 Активных: {active['c']}\n💵 Сумма: {fmt_money(active['s'])}\n\n📈 Ставки: 7д(+3%), 14д(+7%), 30д(+18%)",
        reply_markup=bank_kb()
    )
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
        f"Нажмите на кнопку ниже, чтобы добавить бота в ваш чат или группу:\n\n"
        f"🔗 <a href='{link}'>➕ Добавить {BOT_USERNAME} в чат</a>",
        disable_web_page_preview=True
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

@dp.callback_query(F.data.startswith("game:"))
async def game_pick_cb(query: CallbackQuery):
    game = query.data.split(":")[-1]
    usage = {
        "crash": "краш 100 2.5", "roulette": "рул 100 красное", "basket": "баскет 100",
        "football": "футбол 100 гол", "darts": "дартс 100", "bowling": "боулинг 100",
        "dice": "кубик 100 5", "slots": "слоты 100", "ochko": "очко 100",
        "tower": "башня 100", "gold": "золото 100", "diamond": "алмазы 100",
        "mines": "мины 100 3", "fishing": "рыбалка 100", "scratch": "скретч 100",
        "kvak": "квак 100", "hilo": "хило 100", "pyramid": "пирамида 100",
        "arena": "арена 100", "casino": "казино 100", "hockey": "хоккей 100",
        "duel": "дуэль 100"
    }
    await query.message.answer(f"📝 Пример: <code>{usage.get(game)}</code>")
    await query.answer()# ==================== ИГРА ОЧКО (BLACKJACK) ====================
def make_deck():
    ranks = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
    suits = ["♠", "♥", "♦", "♣"]
    deck = [(r, s) for r in ranks for s in suits]
    random.shuffle(deck)
    return deck

def card_value(rank: str) -> int:
    if rank in ["J", "Q", "K"]:
        return 10
    if rank == "A":
        return 11
    return int(rank)

def hand_value(cards: list) -> int:
    total = sum(card_value(r) for r, _ in cards)
    aces = sum(1 for r, _ in cards if r == "A")
    while total > 21 and aces > 0:
        total -= 10
        aces -= 1
    return total

def format_hand(cards: list) -> str:
    return " ".join(f"{r}{s}" for r, s in cards)

def ochko_text(game: Dict, reveal_dealer: bool) -> str:
    player_val = hand_value(game["player"])
    if reveal_dealer:
        dealer_line = f"{format_hand(game['dealer'])} ({hand_value(game['dealer'])})"
    else:
        first = f"{game['dealer'][0][0]}{game['dealer'][0][1]}"
        dealer_line = f"{first} ??"
    return f"🎴 <b>Очко (21)</b>\nСтавка: {fmt_money(game['bet'])}\n\nДилер: {dealer_line}\nТы: {format_hand(game['player'])} ({player_val})"

@dp.message(lambda m: normalize_text(m.text).startswith("очко"))
async def ochko_start(message: Message, state: FSMContext):
    parts = message.text.split()
    if len(parts) != 2:
        return await message.answer("❌ Формат: `очко 100`\nПример: `очко 500`")
    
    try:
        bet = parse_amount(parts[1])
    except:
        return await message.answer("❌ Неверная ставка")
    
    if bet < MIN_BET:
        return await message.answer(f"❌ Минимальная ставка: {fmt_money(MIN_BET)}")
    
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
        return await query.message.edit_text(f"❌ Недостаточно средств. Ваш баланс: {fmt_money(get_user(query.from_user.id)['coins'])}")
    
    deck = make_deck()
    player = [deck.pop(), deck.pop()]
    dealer = [deck.pop(), deck.pop()]
    OCHKO_GAMES[query.from_user.id] = {"bet": bet, "deck": deck, "player": player, "dealer": dealer}
    game = OCHKO_GAMES[query.from_user.id]
    
    pv = hand_value(player)
    if pv == 21:
        dv = hand_value(dealer)
        if dv == 21:
            payout = bet
            msg = "🤝 Ничья!"
        else:
            payout = bet * 2.5
            msg = "🎉 BLACKJACK! ПОБЕДА!"
        bal = finalize_reserved_bet(query.from_user.id, bet, payout, "ochko", "blackjack")
        OCHKO_GAMES.pop(query.from_user.id)
        await query.message.edit_text(
            f"{ochko_text(game, True)}\n\n{msg}\n"
            f"💰 Выплата: {fmt_money(payout)}\n"
            f"💎 Баланс: {fmt_money(bal)}"
        )
        return await query.answer()
    
    await query.message.edit_text(ochko_text(game, False), reply_markup=ochko_kb())
    await query.answer()

@dp.callback_query(F.data == "ochko:hit")
async def ochko_hit(query: CallbackQuery):
    user_id = query.from_user.id
    game = OCHKO_GAMES.get(user_id)
    if not game:
        return await query.answer("❌ Нет активной игры", show_alert=True)
    
    if not check_cooldown(user_id):
        return await query.answer("⏳ Подождите", show_alert=True)
    
    game["player"].append(game["deck"].pop())
    pv = hand_value(game["player"])
    
    if pv > 21:
        bal = finalize_reserved_bet(user_id, game["bet"], 0, "ochko", "bust")
        OCHKO_GAMES.pop(user_id)
        await query.message.edit_text(
            f"{ochko_text(game, True)}\n\n💥 ПЕРЕБОР! Вы проиграли.\n"
            f"💎 Баланс: {fmt_money(bal)}"
        )
        return await query.answer()
    
    await query.message.edit_text(ochko_text(game, False), reply_markup=ochko_kb())
    await query.answer()

@dp.callback_query(F.data == "ochko:stand")
async def ochko_stand(query: CallbackQuery):
    user_id = query.from_user.id
    game = OCHKO_GAMES.get(user_id)
    if not game:
        return await query.answer("❌ Нет активной игры", show_alert=True)
    
    # Дилер добирает карты до 17
    while hand_value(game["dealer"]) < 17:
        game["dealer"].append(game["deck"].pop())
    
    pv = hand_value(game["player"])
    dv = hand_value(game["dealer"])
    
    if dv > 21 or pv > dv:
        payout = game["bet"] * 2
        outcome = "win"
        msg = "🎉 ПОБЕДА!"
    elif pv == dv:
        payout = game["bet"]
        outcome = "push"
        msg = "🤝 НИЧЬЯ"
    else:
        payout = 0
        outcome = "lose"
        msg = "💔 ПОРАЖЕНИЕ"
    
    bal = finalize_reserved_bet(user_id, game["bet"], payout, "ochko", outcome)
    OCHKO_GAMES.pop(user_id)
    
    await query.message.edit_text(
        f"{ochko_text(game, True)}\n\n{msg}\n"
        f"💰 Выплата: {fmt_money(payout)}\n"
        f"💎 Баланс: {fmt_money(bal)}"
    )
    await query.answer()

# ==================== ИГРА БАШНЯ ====================
def tower_text(game: Dict) -> str:
    level = game["level"]
    bet = game["bet"]
    mult = TOWER_MULTIPLIERS[level - 1] if level > 0 else 0
    return f"🗼 <b>Башня</b>\nСтавка: {fmt_money(bet)}\nЭтаж: {level}/8\nМножитель: x{mult:.2f}\n💰 Потенциал: {fmt_money(bet * mult)}"

@dp.message(lambda m: normalize_text(m.text).startswith("башня"))
async def tower_start(message: Message):
    parts = message.text.split()
    if len(parts) != 2:
        return await message.answer("❌ Формат: `башня 100`\nПример: `башня 500`")
    
    try:
        bet = parse_amount(parts[1])
    except:
        return await message.answer("❌ Неверная ставка")
    
    if bet < MIN_BET:
        return await message.answer(f"❌ Минимальная ставка: {fmt_money(MIN_BET)}")
    
    ok, _ = reserve_bet(message.from_user.id, bet)
    if not ok:
        return await message.answer(f"❌ Недостаточно средств. Ваш баланс: {fmt_money(get_user(message.from_user.id)['coins'])}")
    
    TOWER_GAMES[message.from_user.id] = {"bet": bet, "level": 0}
    await message.answer(tower_text(TOWER_GAMES[message.from_user.id]), reply_markup=tower_kb())

@dp.callback_query(F.data.startswith("tower:"))
async def tower_callback(query: CallbackQuery):
    user_id = query.from_user.id
    game = TOWER_GAMES.get(user_id)
    if not game:
        return await query.answer("❌ Нет активной игры", show_alert=True)
    
    action = query.data.split(":")[-1]
    
    if action == "cancel":
        bal = finalize_reserved_bet(user_id, game["bet"], game["bet"], "tower", "cancel")
        TOWER_GAMES.pop(user_id)
        await query.message.edit_text(f"❌ Игра отменена\n💰 Возврат: {fmt_money(game['bet'])}\n💎 Баланс: {fmt_money(bal)}")
        return await query.answer()
    
    if action == "cash":
        if game["level"] == 0:
            return await query.answer("❌ Сначала сделайте ход", show_alert=True)
        mult = TOWER_MULTIPLIERS[game["level"] - 1]
        payout = game["bet"] * mult
        bal = finalize_reserved_bet(user_id, game["bet"], payout, "tower", "cashout")
        TOWER_GAMES.pop(user_id)
        await query.message.edit_text(f"✅ ВЫИГРЫШ!\n💰 Выплата: {fmt_money(payout)}\n💎 Баланс: {fmt_money(bal)}")
        return await query.answer()
    
    # Выбор секции
    chosen = int(action)
    safe = random.randint(1, 3)
    
    if chosen != safe:
        bal = finalize_reserved_bet(user_id, game["bet"], 0, "tower", "lose")
        TOWER_GAMES.pop(user_id)
        await query.message.edit_text(f"💥 ЛОВУШКА в секции {safe}!\n❌ ПРОИГРЫШ\n💎 Баланс: {fmt_money(bal)}")
        return await query.answer()
    
    game["level"] += 1
    
    if game["level"] >= len(TOWER_MULTIPLIERS):
        payout = game["bet"] * TOWER_MULTIPLIERS[-1]
        bal = finalize_reserved_bet(user_id, game["bet"], payout, "tower", "win")
        TOWER_GAMES.pop(user_id)
        await query.message.edit_text(f"🏆 ПОБЕДА! Башня пройдена!\n💰 Выплата: {fmt_money(payout)}\n💎 Баланс: {fmt_money(bal)}")
        return await query.answer()
    
    TOWER_GAMES[user_id] = game
    await query.message.edit_text(tower_text(game), reply_markup=tower_kb())
    await query.answer("✅ УСПЕХ!")

# ==================== ИГРА ЗОЛОТО ====================
def gold_text(game: Dict) -> str:
    step = game["step"]
    bet = game["bet"]
    mult = GOLD_MULTIPLIERS[step - 1] if step > 0 else 0
    return f"🥇 <b>Золото</b>\nСтавка: {fmt_money(bet)}\nШаг: {step}/7\nМножитель: x{mult:.2f}\n💰 Потенциал: {fmt_money(bet * mult)}"

@dp.message(lambda m: normalize_text(m.text).startswith("золото"))
async def gold_start(message: Message):
    parts = message.text.split()
    if len(parts) != 2:
        return await message.answer("❌ Формат: `золото 100`\nПример: `золото 500`")
    
    try:
        bet = parse_amount(parts[1])
    except:
        return await message.answer("❌ Неверная ставка")
    
    if bet < MIN_BET:
        return await message.answer(f"❌ Минимальная ставка: {fmt_money(MIN_BET)}")
    
    ok, _ = reserve_bet(message.from_user.id, bet)
    if not ok:
        return await message.answer(f"❌ Недостаточно средств. Ваш баланс: {fmt_money(get_user(message.from_user.id)['coins'])}")
    
    GOLD_GAMES[message.from_user.id] = {"bet": bet, "step": 0}
    await message.answer(gold_text(GOLD_GAMES[message.from_user.id]), reply_markup=gold_kb())

@dp.callback_query(F.data.startswith("gold:"))
async def gold_callback(query: CallbackQuery):
    user_id = query.from_user.id
    game = GOLD_GAMES.get(user_id)
    if not game:
        return await query.answer("❌ Нет активной игры", show_alert=True)
    
    action = query.data.split(":")[-1]
    
    if action == "cancel":
        bal = finalize_reserved_bet(user_id, game["bet"], game["bet"], "gold", "cancel")
        GOLD_GAMES.pop(user_id)
        await query.message.edit_text(f"❌ Игра отменена\n💰 Возврат: {fmt_money(game['bet'])}\n💎 Баланс: {fmt_money(bal)}")
        return await query.answer()
    
    if action == "cash":
        if game["step"] == 0:
            return await query.answer("❌ Сначала сделайте ход", show_alert=True)
        mult = GOLD_MULTIPLIERS[game["step"] - 1]
        payout = game["bet"] * mult
        bal = finalize_reserved_bet(user_id, game["bet"], payout, "gold", "cashout")
        GOLD_GAMES.pop(user_id)
        await query.message.edit_text(f"✅ ВЫИГРЫШ!\n💰 Выплата: {fmt_money(payout)}\n💎 Баланс: {fmt_money(bal)}")
        return await query.answer()
    
    # Выбор плитки
    chosen = int(action)
    trap = random.randint(1, 4)
    
    if chosen == trap:
        bal = finalize_reserved_bet(user_id, game["bet"], 0, "gold", "lose")
        GOLD_GAMES.pop(user_id)
        await query.message.edit_text(f"💥 ЛОВУШКА в плитке {trap}!\n❌ ПРОИГРЫШ\n💎 Баланс: {fmt_money(bal)}")
        return await query.answer()
    
    game["step"] += 1
    
    if game["step"] >= len(GOLD_MULTIPLIERS):
        payout = game["bet"] * GOLD_MULTIPLIERS[-1]
        bal = finalize_reserved_bet(user_id, game["bet"], payout, "gold", "win")
        GOLD_GAMES.pop(user_id)
        await query.message.edit_text(f"🏆 ПОБЕДА! Золото пройдено!\n💰 Выплата: {fmt_money(payout)}\n💎 Баланс: {fmt_money(bal)}")
        return await query.answer()
    
    GOLD_GAMES[user_id] = game
    await query.message.edit_text(gold_text(game), reply_markup=gold_kb())
    await query.answer("✅ УСПЕХ!")

# ==================== ИГРА АЛМАЗЫ ====================
def diamond_text(game: Dict) -> str:
    step = game["step"]
    bet = game["bet"]
    mult = DIAMOND_MULTIPLIERS[step - 1] if step > 0 else 0
    return f"💎 <b>Алмазы</b>\nСтавка: {fmt_money(bet)}\nШаг: {step}/8\nМножитель: x{mult:.2f}\n💰 Потенциал: {fmt_money(bet * mult)}"

@dp.message(lambda m: normalize_text(m.text).startswith("алмазы"))
async def diamond_start(message: Message):
    parts = message.text.split()
    if len(parts) != 2:
        return await message.answer("❌ Формат: `алмазы 100`\nПример: `алмазы 500`")
    
    try:
        bet = parse_amount(parts[1])
    except:
        return await message.answer("❌ Неверная ставка")
    
    if bet < MIN_BET:
        return await message.answer(f"❌ Минимальная ставка: {fmt_money(MIN_BET)}")
    
    ok, _ = reserve_bet(message.from_user.id, bet)
    if not ok:
        return await message.answer(f"❌ Недостаточно средств. Ваш баланс: {fmt_money(get_user(message.from_user.id)['coins'])}")
    
    DIAMOND_GAMES[message.from_user.id] = {"bet": bet, "step": 0}
    await message.answer(diamond_text(DIAMOND_GAMES[message.from_user.id]), reply_markup=diamond_kb())

@dp.callback_query(F.data.startswith("diamond:"))
async def diamond_callback(query: CallbackQuery):
    user_id = query.from_user.id
    game = DIAMOND_GAMES.get(user_id)
    if not game:
        return await query.answer("❌ Нет активной игры", show_alert=True)
    
    action = query.data.split(":")[-1]
    
    if action == "cancel":
        bal = finalize_reserved_bet(user_id, game["bet"], game["bet"], "diamond", "cancel")
        DIAMOND_GAMES.pop(user_id)
        await query.message.edit_text(f"❌ Игра отменена\n💰 Возврат: {fmt_money(game['bet'])}\n💎 Баланс: {fmt_money(bal)}")
        return await query.answer()
    
    if action == "cash":
        if game["step"] == 0:
            return await query.answer("❌ Сначала сделайте ход", show_alert=True)
        mult = DIAMOND_MULTIPLIERS[game["step"] - 1]
        payout = game["bet"] * mult
        bal = finalize_reserved_bet(user_id, game["bet"], payout, "diamond", "cashout")
        DIAMOND_GAMES.pop(user_id)
        await query.message.edit_text(f"✅ ВЫИГРЫШ!\n💰 Выплата: {fmt_money(payout)}\n💎 Баланс: {fmt_money(bal)}")
        return await query.answer()
    
    # Выбор кристалла
    chosen = int(action)
    trap = random.randint(1, 5)
    
    if chosen == trap:
        bal = finalize_reserved_bet(user_id, game["bet"], 0, "diamond", "lose")
        DIAMOND_GAMES.pop(user_id)
        await query.message.edit_text(f"💥 БРАКОВАННЫЙ КРИСТАЛЛ {trap}!\n❌ ПРОИГРЫШ\n💎 Баланс: {fmt_money(bal)}")
        return await query.answer()
    
    game["step"] += 1
    
    if game["step"] >= len(DIAMOND_MULTIPLIERS):
        payout = game["bet"] * DIAMOND_MULTIPLIERS[-1]
        bal = finalize_reserved_bet(user_id, game["bet"], payout, "diamond", "win")
        DIAMOND_GAMES.pop(user_id)
        await query.message.edit_text(f"🏆 ПОБЕДА! Алмазы пройдены!\n💰 Выплата: {fmt_money(payout)}\n💎 Баланс: {fmt_money(bal)}")
        return await query.answer()
    
    DIAMOND_GAMES[user_id] = game
    await query.message.edit_text(diamond_text(game), reply_markup=diamond_kb())
    await query.answer("✅ УСПЕХ!")

# ==================== ИГРА МИНЫ ====================
def mines_multiplier(opened: int, mines: int) -> float:
    safe = 9 - mines
    if opened <= 0:
        return 1.0
    return round((9 / safe) ** opened * 0.97, 2)

def mines_text(game: Dict) -> str:
    mult = mines_multiplier(len(game["opened"]), game["mines_count"])
    return f"💣 <b>Мины</b>\nСтавка: {fmt_money(game['bet'])}\nМин: {game['mines_count']}\nОткрыто: {len(game['opened'])}/9\nМножитель: x{mult:.2f}\n💰 Потенциал: {fmt_money(game['bet'] * mult)}"

@dp.message(lambda m: normalize_text(m.text).startswith("мины"))
async def mines_start(message: Message):
    parts = message.text.split()
    if len(parts) < 2:
        return await message.answer("❌ Формат: `мины 100 3`\nПример: `мины 500 3`")
    
    try:
        bet = parse_amount(parts[1])
    except:
        return await message.answer("❌ Неверная ставка")
    
    if bet < MIN_BET:
        return await message.answer(f"❌ Минимальная ставка: {fmt_money(MIN_BET)}")
    
    mines = 3
    if len(parts) > 2:
        try:
            mines = int(parts[2])
            if mines < 1 or mines > 5:
                mines = 3
        except:
            mines = 3
    
    ok, _ = reserve_bet(message.from_user.id, bet)
    if not ok:
        return await message.answer(f"❌ Недостаточно средств. Ваш баланс: {fmt_money(get_user(message.from_user.id)['coins'])}")
    
    cells = list(range(1, 10))
    mines_set = set(random.sample(cells, mines))
    MINES_GAMES[message.from_user.id] = {"bet": bet, "mines_count": mines, "mines": mines_set, "opened": set()}
    await message.answer(mines_text(MINES_GAMES[message.from_user.id]), reply_markup=mines_kb(MINES_GAMES[message.from_user.id]))

@dp.callback_query(F.data == "mines:noop")
async def mines_noop(query: CallbackQuery):
    await query.answer()

@dp.callback_query(F.data.startswith("mines:"))
async def mines_callback(query: CallbackQuery):
    user_id = query.from_user.id
    game = MINES_GAMES.get(user_id)
    if not game:
        return await query.answer("❌ Нет активной игры", show_alert=True)
    
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
        await query.message.edit_text(f"✅ ВЫИГРЫШ!\n💰 Выплата: {fmt_money(payout)}\n💎 Баланс: {fmt_money(bal)}")
        return await query.answer()
    
    # Открытие клетки
    try:
        idx = int(action)
    except:
        return await query.answer()
    
    if idx in game["opened"]:
        return await query.answer("❌ Уже открыто", show_alert=True)
    
    if idx in game["mines"]:
        bal = finalize_reserved_bet(user_id, game["bet"], 0, "mines", "explode")
        MINES_GAMES.pop(user_id)
        await query.message.edit_text(f"💥 МИНА в {idx}!\n❌ ПРОИГРЫШ\n💎 Баланс: {fmt_money(bal)}")
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
    await query.message.edit_text(mines_text(game), reply_markup=mines_kb(game))
    await query.answer("✅ БЕЗОПАСНО!")# ==================== ИГРА ОЧКО (BLACKJACK) ====================
def make_deck():
    ranks = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
    suits = ["♠", "♥", "♦", "♣"]
    deck = [(r, s) for r in ranks for s in suits]
    random.shuffle(deck)
    return deck

def card_value(rank: str) -> int:
    if rank in ["J", "Q", "K"]:
        return 10
    if rank == "A":
        return 11
    return int(rank)

def hand_value(cards: list) -> int:
    total = sum(card_value(r) for r, _ in cards)
    aces = sum(1 for r, _ in cards if r == "A")
    while total > 21 and aces > 0:
        total -= 10
        aces -= 1
    return total

def format_hand(cards: list) -> str:
    return " ".join(f"{r}{s}" for r, s in cards)

def ochko_text(game: Dict, reveal_dealer: bool) -> str:
    player_val = hand_value(game["player"])
    if reveal_dealer:
        dealer_line = f"{format_hand(game['dealer'])} ({hand_value(game['dealer'])})"
    else:
        first = f"{game['dealer'][0][0]}{game['dealer'][0][1]}"
        dealer_line = f"{first} ??"
    return f"🎴 <b>Очко (21)</b>\nСтавка: {fmt_money(game['bet'])}\n\nДилер: {dealer_line}\nТы: {format_hand(game['player'])} ({player_val})"

@dp.message(lambda m: normalize_text(m.text).startswith("очко"))
async def ochko_start(message: Message, state: FSMContext):
    parts = message.text.split()
    if len(parts) != 2:
        return await message.answer("❌ Формат: `очко 100`\nПример: `очко 500`")
    
    try:
        bet = parse_amount(parts[1])
    except:
        return await message.answer("❌ Неверная ставка")
    
    if bet < MIN_BET:
        return await message.answer(f"❌ Минимальная ставка: {fmt_money(MIN_BET)}")
    
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
        return await query.message.edit_text(f"❌ Недостаточно средств. Ваш баланс: {fmt_money(get_user(query.from_user.id)['coins'])}")
    
    deck = make_deck()
    player = [deck.pop(), deck.pop()]
    dealer = [deck.pop(), deck.pop()]
    OCHKO_GAMES[query.from_user.id] = {"bet": bet, "deck": deck, "player": player, "dealer": dealer}
    game = OCHKO_GAMES[query.from_user.id]
    
    pv = hand_value(player)
    if pv == 21:
        dv = hand_value(dealer)
        if dv == 21:
            payout = bet
            msg = "🤝 Ничья!"
        else:
            payout = bet * 2.5
            msg = "🎉 BLACKJACK! ПОБЕДА!"
        bal = finalize_reserved_bet(query.from_user.id, bet, payout, "ochko", "blackjack")
        OCHKO_GAMES.pop(query.from_user.id)
        await query.message.edit_text(
            f"{ochko_text(game, True)}\n\n{msg}\n"
            f"💰 Выплата: {fmt_money(payout)}\n"
            f"💎 Баланс: {fmt_money(bal)}"
        )
        return await query.answer()
    
    await query.message.edit_text(ochko_text(game, False), reply_markup=ochko_kb())
    await query.answer()

@dp.callback_query(F.data == "ochko:hit")
async def ochko_hit(query: CallbackQuery):
    user_id = query.from_user.id
    game = OCHKO_GAMES.get(user_id)
    if not game:
        return await query.answer("❌ Нет активной игры", show_alert=True)
    
    if not check_cooldown(user_id):
        return await query.answer("⏳ Подождите", show_alert=True)
    
    game["player"].append(game["deck"].pop())
    pv = hand_value(game["player"])
    
    if pv > 21:
        bal = finalize_reserved_bet(user_id, game["bet"], 0, "ochko", "bust")
        OCHKO_GAMES.pop(user_id)
        await query.message.edit_text(
            f"{ochko_text(game, True)}\n\n💥 ПЕРЕБОР! Вы проиграли.\n"
            f"💎 Баланс: {fmt_money(bal)}"
        )
        return await query.answer()
    
    await query.message.edit_text(ochko_text(game, False), reply_markup=ochko_kb())
    await query.answer()

@dp.callback_query(F.data == "ochko:stand")
async def ochko_stand(query: CallbackQuery):
    user_id = query.from_user.id
    game = OCHKO_GAMES.get(user_id)
    if not game:
        return await query.answer("❌ Нет активной игры", show_alert=True)
    
    # Дилер добирает карты до 17
    while hand_value(game["dealer"]) < 17:
        game["dealer"].append(game["deck"].pop())
    
    pv = hand_value(game["player"])
    dv = hand_value(game["dealer"])
    
    if dv > 21 or pv > dv:
        payout = game["bet"] * 2
        outcome = "win"
        msg = "🎉 ПОБЕДА!"
    elif pv == dv:
        payout = game["bet"]
        outcome = "push"
        msg = "🤝 НИЧЬЯ"
    else:
        payout = 0
        outcome = "lose"
        msg = "💔 ПОРАЖЕНИЕ"
    
    bal = finalize_reserved_bet(user_id, game["bet"], payout, "ochko", outcome)
    OCHKO_GAMES.pop(user_id)
    
    await query.message.edit_text(
        f"{ochko_text(game, True)}\n\n{msg}\n"
        f"💰 Выплата: {fmt_money(payout)}\n"
        f"💎 Баланс: {fmt_money(bal)}"
    )
    await query.answer()

# ==================== ИГРА БАШНЯ ====================
def tower_text(game: Dict) -> str:
    level = game["level"]
    bet = game["bet"]
    mult = TOWER_MULTIPLIERS[level - 1] if level > 0 else 0
    return f"🗼 <b>Башня</b>\nСтавка: {fmt_money(bet)}\nЭтаж: {level}/8\nМножитель: x{mult:.2f}\n💰 Потенциал: {fmt_money(bet * mult)}"

@dp.message(lambda m: normalize_text(m.text).startswith("башня"))
async def tower_start(message: Message):
    parts = message.text.split()
    if len(parts) != 2:
        return await message.answer("❌ Формат: `башня 100`\nПример: `башня 500`")
    
    try:
        bet = parse_amount(parts[1])
    except:
        return await message.answer("❌ Неверная ставка")
    
    if bet < MIN_BET:
        return await message.answer(f"❌ Минимальная ставка: {fmt_money(MIN_BET)}")
    
    ok, _ = reserve_bet(message.from_user.id, bet)
    if not ok:
        return await message.answer(f"❌ Недостаточно средств. Ваш баланс: {fmt_money(get_user(message.from_user.id)['coins'])}")
    
    TOWER_GAMES[message.from_user.id] = {"bet": bet, "level": 0}
    await message.answer(tower_text(TOWER_GAMES[message.from_user.id]), reply_markup=tower_kb())

@dp.callback_query(F.data.startswith("tower:"))
async def tower_callback(query: CallbackQuery):
    user_id = query.from_user.id
    game = TOWER_GAMES.get(user_id)
    if not game:
        return await query.answer("❌ Нет активной игры", show_alert=True)
    
    action = query.data.split(":")[-1]
    
    if action == "cancel":
        bal = finalize_reserved_bet(user_id, game["bet"], game["bet"], "tower", "cancel")
        TOWER_GAMES.pop(user_id)
        await query.message.edit_text(f"❌ Игра отменена\n💰 Возврат: {fmt_money(game['bet'])}\n💎 Баланс: {fmt_money(bal)}")
        return await query.answer()
    
    if action == "cash":
        if game["level"] == 0:
            return await query.answer("❌ Сначала сделайте ход", show_alert=True)
        mult = TOWER_MULTIPLIERS[game["level"] - 1]
        payout = game["bet"] * mult
        bal = finalize_reserved_bet(user_id, game["bet"], payout, "tower", "cashout")
        TOWER_GAMES.pop(user_id)
        await query.message.edit_text(f"✅ ВЫИГРЫШ!\n💰 Выплата: {fmt_money(payout)}\n💎 Баланс: {fmt_money(bal)}")
        return await query.answer()
    
    # Выбор секции
    chosen = int(action)
    safe = random.randint(1, 3)
    
    if chosen != safe:
        bal = finalize_reserved_bet(user_id, game["bet"], 0, "tower", "lose")
        TOWER_GAMES.pop(user_id)
        await query.message.edit_text(f"💥 ЛОВУШКА в секции {safe}!\n❌ ПРОИГРЫШ\n💎 Баланс: {fmt_money(bal)}")
        return await query.answer()
    
    game["level"] += 1
    
    if game["level"] >= len(TOWER_MULTIPLIERS):
        payout = game["bet"] * TOWER_MULTIPLIERS[-1]
        bal = finalize_reserved_bet(user_id, game["bet"], payout, "tower", "win")
        TOWER_GAMES.pop(user_id)
        await query.message.edit_text(f"🏆 ПОБЕДА! Башня пройдена!\n💰 Выплата: {fmt_money(payout)}\n💎 Баланс: {fmt_money(bal)}")
        return await query.answer()
    
    TOWER_GAMES[user_id] = game
    await query.message.edit_text(tower_text(game), reply_markup=tower_kb())
    await query.answer("✅ УСПЕХ!")

# ==================== ИГРА ЗОЛОТО ====================
def gold_text(game: Dict) -> str:
    step = game["step"]
    bet = game["bet"]
    mult = GOLD_MULTIPLIERS[step - 1] if step > 0 else 0
    return f"🥇 <b>Золото</b>\nСтавка: {fmt_money(bet)}\nШаг: {step}/7\nМножитель: x{mult:.2f}\n💰 Потенциал: {fmt_money(bet * mult)}"

@dp.message(lambda m: normalize_text(m.text).startswith("золото"))
async def gold_start(message: Message):
    parts = message.text.split()
    if len(parts) != 2:
        return await message.answer("❌ Формат: `золото 100`\nПример: `золото 500`")
    
    try:
        bet = parse_amount(parts[1])
    except:
        return await message.answer("❌ Неверная ставка")
    
    if bet < MIN_BET:
        return await message.answer(f"❌ Минимальная ставка: {fmt_money(MIN_BET)}")
    
    ok, _ = reserve_bet(message.from_user.id, bet)
    if not ok:
        return await message.answer(f"❌ Недостаточно средств. Ваш баланс: {fmt_money(get_user(message.from_user.id)['coins'])}")
    
    GOLD_GAMES[message.from_user.id] = {"bet": bet, "step": 0}
    await message.answer(gold_text(GOLD_GAMES[message.from_user.id]), reply_markup=gold_kb())

@dp.callback_query(F.data.startswith("gold:"))
async def gold_callback(query: CallbackQuery):
    user_id = query.from_user.id
    game = GOLD_GAMES.get(user_id)
    if not game:
        return await query.answer("❌ Нет активной игры", show_alert=True)
    
    action = query.data.split(":")[-1]
    
    if action == "cancel":
        bal = finalize_reserved_bet(user_id, game["bet"], game["bet"], "gold", "cancel")
        GOLD_GAMES.pop(user_id)
        await query.message.edit_text(f"❌ Игра отменена\n💰 Возврат: {fmt_money(game['bet'])}\n💎 Баланс: {fmt_money(bal)}")
        return await query.answer()
    
    if action == "cash":
        if game["step"] == 0:
            return await query.answer("❌ Сначала сделайте ход", show_alert=True)
        mult = GOLD_MULTIPLIERS[game["step"] - 1]
        payout = game["bet"] * mult
        bal = finalize_reserved_bet(user_id, game["bet"], payout, "gold", "cashout")
        GOLD_GAMES.pop(user_id)
        await query.message.edit_text(f"✅ ВЫИГРЫШ!\n💰 Выплата: {fmt_money(payout)}\n💎 Баланс: {fmt_money(bal)}")
        return await query.answer()
    
    # Выбор плитки
    chosen = int(action)
    trap = random.randint(1, 4)
    
    if chosen == trap:
        bal = finalize_reserved_bet(user_id, game["bet"], 0, "gold", "lose")
        GOLD_GAMES.pop(user_id)
        await query.message.edit_text(f"💥 ЛОВУШКА в плитке {trap}!\n❌ ПРОИГРЫШ\n💎 Баланс: {fmt_money(bal)}")
        return await query.answer()
    
    game["step"] += 1
    
    if game["step"] >= len(GOLD_MULTIPLIERS):
        payout = game["bet"] * GOLD_MULTIPLIERS[-1]
        bal = finalize_reserved_bet(user_id, game["bet"], payout, "gold", "win")
        GOLD_GAMES.pop(user_id)
        await query.message.edit_text(f"🏆 ПОБЕДА! Золото пройдено!\n💰 Выплата: {fmt_money(payout)}\n💎 Баланс: {fmt_money(bal)}")
        return await query.answer()
    
    GOLD_GAMES[user_id] = game
    await query.message.edit_text(gold_text(game), reply_markup=gold_kb())
    await query.answer("✅ УСПЕХ!")

# ==================== ИГРА АЛМАЗЫ ====================
def diamond_text(game: Dict) -> str:
    step = game["step"]
    bet = game["bet"]
    mult = DIAMOND_MULTIPLIERS[step - 1] if step > 0 else 0
    return f"💎 <b>Алмазы</b>\nСтавка: {fmt_money(bet)}\nШаг: {step}/8\nМножитель: x{mult:.2f}\n💰 Потенциал: {fmt_money(bet * mult)}"

@dp.message(lambda m: normalize_text(m.text).startswith("алмазы"))
async def diamond_start(message: Message):
    parts = message.text.split()
    if len(parts) != 2:
        return await message.answer("❌ Формат: `алмазы 100`\nПример: `алмазы 500`")
    
    try:
        bet = parse_amount(parts[1])
    except:
        return await message.answer("❌ Неверная ставка")
    
    if bet < MIN_BET:
        return await message.answer(f"❌ Минимальная ставка: {fmt_money(MIN_BET)}")
    
    ok, _ = reserve_bet(message.from_user.id, bet)
    if not ok:
        return await message.answer(f"❌ Недостаточно средств. Ваш баланс: {fmt_money(get_user(message.from_user.id)['coins'])}")
    
    DIAMOND_GAMES[message.from_user.id] = {"bet": bet, "step": 0}
    await message.answer(diamond_text(DIAMOND_GAMES[message.from_user.id]), reply_markup=diamond_kb())

@dp.callback_query(F.data.startswith("diamond:"))
async def diamond_callback(query: CallbackQuery):
    user_id = query.from_user.id
    game = DIAMOND_GAMES.get(user_id)
    if not game:
        return await query.answer("❌ Нет активной игры", show_alert=True)
    
    action = query.data.split(":")[-1]
    
    if action == "cancel":
        bal = finalize_reserved_bet(user_id, game["bet"], game["bet"], "diamond", "cancel")
        DIAMOND_GAMES.pop(user_id)
        await query.message.edit_text(f"❌ Игра отменена\n💰 Возврат: {fmt_money(game['bet'])}\n💎 Баланс: {fmt_money(bal)}")
        return await query.answer()
    
    if action == "cash":
        if game["step"] == 0:
            return await query.answer("❌ Сначала сделайте ход", show_alert=True)
        mult = DIAMOND_MULTIPLIERS[game["step"] - 1]
        payout = game["bet"] * mult
        bal = finalize_reserved_bet(user_id, game["bet"], payout, "diamond", "cashout")
        DIAMOND_GAMES.pop(user_id)
        await query.message.edit_text(f"✅ ВЫИГРЫШ!\n💰 Выплата: {fmt_money(payout)}\n💎 Баланс: {fmt_money(bal)}")
        return await query.answer()
    
    # Выбор кристалла
    chosen = int(action)
    trap = random.randint(1, 5)
    
    if chosen == trap:
        bal = finalize_reserved_bet(user_id, game["bet"], 0, "diamond", "lose")
        DIAMOND_GAMES.pop(user_id)
        await query.message.edit_text(f"💥 БРАКОВАННЫЙ КРИСТАЛЛ {trap}!\n❌ ПРОИГРЫШ\n💎 Баланс: {fmt_money(bal)}")
        return await query.answer()
    
    game["step"] += 1
    
    if game["step"] >= len(DIAMOND_MULTIPLIERS):
        payout = game["bet"] * DIAMOND_MULTIPLIERS[-1]
        bal = finalize_reserved_bet(user_id, game["bet"], payout, "diamond", "win")
        DIAMOND_GAMES.pop(user_id)
        await query.message.edit_text(f"🏆 ПОБЕДА! Алмазы пройдены!\n💰 Выплата: {fmt_money(payout)}\n💎 Баланс: {fmt_money(bal)}")
        return await query.answer()
    
    DIAMOND_GAMES[user_id] = game
    await query.message.edit_text(diamond_text(game), reply_markup=diamond_kb())
    await query.answer("✅ УСПЕХ!")

# ==================== ИГРА МИНЫ ====================
def mines_multiplier(opened: int, mines: int) -> float:
    safe = 9 - mines
    if opened <= 0:
        return 1.0
    return round((9 / safe) ** opened * 0.97, 2)

def mines_text(game: Dict) -> str:
    mult = mines_multiplier(len(game["opened"]), game["mines_count"])
    return f"💣 <b>Мины</b>\nСтавка: {fmt_money(game['bet'])}\nМин: {game['mines_count']}\nОткрыто: {len(game['opened'])}/9\nМножитель: x{mult:.2f}\n💰 Потенциал: {fmt_money(game['bet'] * mult)}"

@dp.message(lambda m: normalize_text(m.text).startswith("мины"))
async def mines_start(message: Message):
    parts = message.text.split()
    if len(parts) < 2:
        return await message.answer("❌ Формат: `мины 100 3`\nПример: `мины 500 3`")
    
    try:
        bet = parse_amount(parts[1])
    except:
        return await message.answer("❌ Неверная ставка")
    
    if bet < MIN_BET:
        return await message.answer(f"❌ Минимальная ставка: {fmt_money(MIN_BET)}")
    
    mines = 3
    if len(parts) > 2:
        try:
            mines = int(parts[2])
            if mines < 1 or mines > 5:
                mines = 3
        except:
            mines = 3
    
    ok, _ = reserve_bet(message.from_user.id, bet)
    if not ok:
        return await message.answer(f"❌ Недостаточно средств. Ваш баланс: {fmt_money(get_user(message.from_user.id)['coins'])}")
    
    cells = list(range(1, 10))
    mines_set = set(random.sample(cells, mines))
    MINES_GAMES[message.from_user.id] = {"bet": bet, "mines_count": mines, "mines": mines_set, "opened": set()}
    await message.answer(mines_text(MINES_GAMES[message.from_user.id]), reply_markup=mines_kb(MINES_GAMES[message.from_user.id]))

@dp.callback_query(F.data == "mines:noop")
async def mines_noop(query: CallbackQuery):
    await query.answer()

@dp.callback_query(F.data.startswith("mines:"))
async def mines_callback(query: CallbackQuery):
    user_id = query.from_user.id
    game = MINES_GAMES.get(user_id)
    if not game:
        return await query.answer("❌ Нет активной игры", show_alert=True)
    
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
        await query.message.edit_text(f"✅ ВЫИГРЫШ!\n💰 Выплата: {fmt_money(payout)}\n💎 Баланс: {fmt_money(bal)}")
        return await query.answer()
    
    # Открытие клетки
    try:
        idx = int(action)
    except:
        return await query.answer()
    
    if idx in game["opened"]:
        return await query.answer("❌ Уже открыто", show_alert=True)
    
    if idx in game["mines"]:
        bal = finalize_reserved_bet(user_id, game["bet"], 0, "mines", "explode")
        MINES_GAMES.pop(user_id)
        await query.message.edit_text(f"💥 МИНА в {idx}!\n❌ ПРОИГРЫШ\n💎 Баланс: {fmt_money(bal)}")
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
    await query.message.edit_text(mines_text(game), reply_markup=mines_kb(game))
    await query.answer("✅ БЕЗОПАСНО!")# ==================== ИГРА РЫБАЛКА ====================
@dp.message(lambda m: normalize_text(m.text).startswith("рыбалка"))
async def fishing_game(message: Message):
    if not check_cooldown(message.from_user.id):
        return await message.answer("⏳ Подождите 2.5 секунды перед следующей игрой")
    
    parts = message.text.split()
    if len(parts) != 2:
        return await message.answer("❌ Формат: `рыбалка 100`\nПример: `рыбалка 500`")
    
    try:
        bet = parse_amount(parts[1])
    except:
        return await message.answer("❌ Неверная ставка")
    
    if bet < MIN_BET:
        return await message.answer(f"❌ Минимальная ставка: {fmt_money(MIN_BET)}")
    
    # Рыбалка: случайный улов от 1 до 6
    dice_msg = await message.answer_dice(emoji="🎣")
    value = dice_msg.dice.value
    
    if value == 6:
        multiplier = 5.0
        result_text = "🐋 БОЛЬШАЯ РЫБА! ОГРОМНЫЙ УЛОВ!"
    elif value == 5:
        multiplier = 3.0
        result_text = "🐟 ОТЛИЧНАЯ РЫБА!"
    elif value == 4:
        multiplier = 2.0
        result_text = "🐠 ХОРОШАЯ РЫБА!"
    elif value == 3:
        multiplier = 1.5
        result_text = "🐡 МЕЛКАЯ РЫБА"
    elif value == 2:
        multiplier = 1.2
        result_text = "🦐 МЕЛКОТА"
    else:
        multiplier = 0
        result_text = "❌ ПУСТО! РЫБЫ НЕТ!"
    
    win = multiplier > 0
    payout = bet * multiplier if win else 0
    
    ok, bal = settle_instant_bet(message.from_user.id, bet, payout, "fishing", f"value={value}")
    if not ok:
        return await message.answer(f"❌ Недостаточно средств. Ваш баланс: {fmt_money(get_user(message.from_user.id)['coins'])}")
    
    await message.answer(
        f"🎣 <b>Рыбалка</b>\n"
        f"📊 Результат: <b>{value}/6</b>\n"
        f"{result_text}\n"
        f"{'✅ ПОБЕДА! x' + str(multiplier) if win else '❌ ПОРАЖЕНИЕ'}\n"
        f"💰 Выплата: {fmt_money(payout)}\n"
        f"💎 Баланс: {fmt_money(bal)}"
    )

# ==================== ИГРА СКРЕТЧ ====================
@dp.message(lambda m: normalize_text(m.text).startswith("скретч"))
async def scratch_game(message: Message):
    if not check_cooldown(message.from_user.id):
        return await message.answer("⏳ Подождите 2.5 секунды перед следующей игрой")
    
    parts = message.text.split()
    if len(parts) != 2:
        return await message.answer("❌ Формат: `скретч 100`\nПример: `скретч 500`")
    
    try:
        bet = parse_amount(parts[1])
    except:
        return await message.answer("❌ Неверная ставка")
    
    if bet < MIN_BET:
        return await message.answer(f"❌ Минимальная ставка: {fmt_money(MIN_BET)}")
    
    # Скретч-карта: 3 символа
    symbols = ["💰", "💎", "⭐", "7️⃣", "🍒", "🎰"]
    card = [random.choice(symbols) for _ in range(3)]
    
    # Определение выигрыша
    if card[0] == card[1] == card[2]:
        if card[0] == "💰":
            multiplier = 10.0
        elif card[0] == "💎":
            multiplier = 8.0
        elif card[0] == "⭐":
            multiplier = 6.0
        elif card[0] == "7️⃣":
            multiplier = 5.0
        else:
            multiplier = 3.0
    elif card[0] == card[1] or card[1] == card[2] or card[0] == card[2]:
        multiplier = 1.5
    else:
        multiplier = 0
    
    win = multiplier > 0
    payout = bet * multiplier if win else 0
    
    ok, bal = settle_instant_bet(message.from_user.id, bet, payout, "scratch", f"{card[0]}{card[1]}{card[2]}")
    if not ok:
        return await message.answer(f"❌ Недостаточно средств. Ваш баланс: {fmt_money(get_user(message.from_user.id)['coins'])}")
    
    await message.answer(
        f"🎫 <b>Скретч-карта</b>\n"
        f"┌─────┬─────┬─────┐\n"
        f"│  {card[0]}  │  {card[1]}  │  {card[2]}  │\n"
        f"└─────┴─────┴─────┘\n"
        f"{'✅ ПОБЕДА! x' + str(multiplier) if win else '❌ ПОРАЖЕНИЕ'}\n"
        f"💰 Выплата: {fmt_money(payout)}\n"
        f"💎 Баланс: {fmt_money(bal)}"
    )

# ==================== ИГРА КВАК ====================
@dp.message(lambda m: normalize_text(m.text).startswith("квак"))
async def kvak_game(message: Message):
    if not check_cooldown(message.from_user.id):
        return await message.answer("⏳ Подождите 2.5 секунды перед следующей игрой")
    
    parts = message.text.split()
    if len(parts) != 2:
        return await message.answer("❌ Формат: `квак 100`\nПример: `квак 500`")
    
    try:
        bet = parse_amount(parts[1])
    except:
        return await message.answer("❌ Неверная ставка")
    
    if bet < MIN_BET:
        return await message.answer(f"❌ Минимальная ставка: {fmt_money(MIN_BET)}")
    
    dice_msg = await message.answer_dice(emoji="🐸")
    value = dice_msg.dice.value
    
    # Квак - лягушка прыгает: 1-6
    if value == 6:
        multiplier = 5.8
        result_text = "🐸 ЛЯГУШКА НА ВЕРШИНЕ! РЕКОРД!"
    elif value == 5:
        multiplier = 3.5
        result_text = "🐸 ОТЛИЧНЫЙ ПРЫЖОК!"
    elif value == 4:
        multiplier = 2.0
        result_text = "🐸 ХОРОШИЙ ПРЫЖОК"
    elif value == 3:
        multiplier = 1.3
        result_text = "🐸 СРЕДНИЙ ПРЫЖОК"
    else:
        multiplier = 0
        result_text = "🐸 СЛАБЫЙ ПРЫЖОК!"
    
    win = multiplier > 0
    payout = bet * multiplier if win else 0
    
    ok, bal = settle_instant_bet(message.from_user.id, bet, payout, "kvak", f"value={value}")
    if not ok:
        return await message.answer(f"❌ Недостаточно средств. Ваш баланс: {fmt_money(get_user(message.from_user.id)['coins'])}")
    
    await message.answer(
        f"🐸 <b>Квак</b>\n"
        f"📊 Прыжок лягушки: <b>{value}/6</b>\n"
        f"{result_text}\n"
        f"{'✅ ПОБЕДА! x' + str(multiplier) if win else '❌ ПОРАЖЕНИЕ'}\n"
        f"💰 Выплата: {fmt_money(payout)}\n"
        f"💎 Баланс: {fmt_money(bal)}"
    )

# ==================== ИГРА HILO ====================
@dp.message(lambda m: normalize_text(m.text).startswith("хило"))
async def hilo_game(message: Message):
    if not check_cooldown(message.from_user.id):
        return await message.answer("⏳ Подождите 2.5 секунды перед следующей игрой")
    
    parts = message.text.split()
    if len(parts) < 3:
        return await message.answer("❌ Формат: `хило 100 выше`\nПримеры:\n`хило 100 выше`\n`хило 100 ниже`")
    
    try:
        bet = parse_amount(parts[1])
    except:
        return await message.answer("❌ Неверная ставка")
    
    if bet < MIN_BET:
        return await message.answer(f"❌ Минимальная ставка: {fmt_money(MIN_BET)}")
    
    choice = parts[2].lower()
    if choice not in ["выше", "ниже", "higher", "lower"]:
        return await message.answer("❌ Выберите: `выше` или `ниже`")
    
    first_card = random.randint(1, 13)
    second_card = random.randint(1, 13)
    
    # Преобразование для отображения
    card_names = {1: "A", 11:"J", 12:"Q", 13:"K"}
    first_display = card_names.get(first_card, str(first_card))
    second_display = card_names.get(second_card, str(second_card))
    
    if choice in ["выше", "higher"]:
        win = second_card > first_card
    else:
        win = second_card < first_card
    
    multiplier = 2.0 if win else 0
    payout = bet * multiplier if win else 0
    
    ok, bal = settle_instant_bet(message.from_user.id, bet, payout, "hilo", f"{first_card}>{second_card}")
    if not ok:
        return await message.answer(f"❌ Недостаточно средств. Ваш баланс: {fmt_money(get_user(message.from_user.id)['coins'])}")
    
    await message.answer_dice(emoji="🎲")
    await asyncio.sleep(1)
    
    await message.answer(
        f"🃏 <b>Hi-Lo</b>\n"
        f"📊 Первая карта: <b>{first_display}</b>\n"
        f"🎯 Ваш прогноз: <b>{choice.upper()}</b>\n"
        f"🎲 Вторая карта: <b>{second_display}</b>\n"
        f"{'✅ ПОБЕДА! x2' if win else '❌ ПОРАЖЕНИЕ'}\n"
        f"💰 Выплата: {fmt_money(payout)}\n"
        f"💎 Баланс: {fmt_money(bal)}"
    )

# ==================== ИГРА ПИРАМИДА ====================
@dp.message(lambda m: normalize_text(m.text).startswith("пирамида"))
async def pyramid_start(message: Message):
    parts = message.text.split()
    if len(parts) != 2:
        return await message.answer("❌ Формат: `пирамида 100`\nПример: `пирамида 500`")
    
    try:
        bet = parse_amount(parts[1])
    except:
        return await message.answer("❌ Неверная ставка")
    
    if bet < MIN_BET:
        return await message.answer(f"❌ Минимальная ставка: {fmt_money(MIN_BET)}")
    
    ok, _ = reserve_bet(message.from_user.id, bet)
    if not ok:
        return await message.answer(f"❌ Недостаточно средств. Ваш баланс: {fmt_money(get_user(message.from_user.id)['coins'])}")
    
    PYRAMID_GAMES[message.from_user.id] = {"bet": bet, "level": 1, "max_level": 5}
    await message.answer(
        f"🔺 <b>Пирамида</b>\n"
        f"💰 Ставка: {fmt_money(bet)}\n"
        f"🏆 Уровень: 1/{PYRAMID_GAMES[message.from_user.id]['max_level']}\n"
        f"🎯 Множитель: x1.0\n\n"
        f"Выберите камень:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ ЛЕВЫЙ КАМЕНЬ", callback_data=f"pyramid:left")],
            [InlineKeyboardButton(text="➡️ ПРАВЫЙ КАМЕНЬ", callback_data=f"pyramid:right")],
            [InlineKeyboardButton(text="💰 ЗАБРАТЬ", callback_data=f"pyramid:cash")],
        ])
    )

@dp.callback_query(F.data.startswith("pyramid:"))
async def pyramid_callback(query: CallbackQuery):
    user_id = query.from_user.id
    game = PYRAMID_GAMES.get(user_id)
    if not game:
        return await query.answer("❌ Нет активной игры", show_alert=True)
    
    action = query.data.split(":")[-1]
    
    if action == "cash":
        if game["level"] == 1:
            payout = game["bet"]
        else:
            payout = game["bet"] * (1 + (game["level"] - 1) * 0.3)
        bal = finalize_reserved_bet(user_id, game["bet"], payout, "pyramid", "cashout")
        PYRAMID_GAMES.pop(user_id)
        await query.message.edit_text(f"✅ ВЫИГРЫШ!\n💰 Выплата: {fmt_money(payout)}\n💎 Баланс: {fmt_money(bal)}")
        return await query.answer()
    
    safe = random.choice(["left", "right"])
    
    if action != safe:
        bal = finalize_reserved_bet(user_id, game["bet"], 0, "pyramid", "lose")
        PYRAMID_GAMES.pop(user_id)
        await query.message.edit_text(f"💥 ОБВАЛ! Вы выбрали не тот камень!\n❌ ПРОИГРЫШ\n💎 Баланс: {fmt_money(bal)}")
        return await query.answer()
    
    game["level"] += 1
    
    if game["level"] > game["max_level"]:
        payout = game["bet"] * (1 + (game["max_level"] - 1) * 0.3)
        bal = finalize_reserved_bet(user_id, game["bet"], payout, "pyramid", "win")
        PYRAMID_GAMES.pop(user_id)
        await query.message.edit_text(f"🏆 ПОБЕДА! Пирамида пройдена!\n💰 Выплата: {fmt_money(payout)}\n💎 Баланс: {fmt_money(bal)}")
        return await query.answer()
    
    PYRAMID_GAMES[user_id] = game
    current_mult = 1 + (game["level"] - 1) * 0.3
    await query.message.edit_text(
        f"🔺 <b>Пирамида</b>\n"
        f"💰 Ставка: {fmt_money(game['bet'])}\n"
        f"🏆 Уровень: {game['level']}/{game['max_level']}\n"
        f"🎯 Множитель: x{current_mult:.1f}\n"
        f"💰 Потенциал: {fmt_money(game['bet'] * current_mult)}\n\n"
        f"Выберите камень:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ ЛЕВЫЙ КАМЕНЬ", callback_data=f"pyramid:left")],
            [InlineKeyboardButton(text="➡️ ПРАВЫЙ КАМЕНЬ", callback_data=f"pyramid:right")],
            [InlineKeyboardButton(text="💰 ЗАБРАТЬ", callback_data=f"pyramid:cash")],
        ])
    )
    await query.answer("✅ УСПЕХ!")

# ==================== ИГРА ARENA ====================
@dp.message(lambda m: normalize_text(m.text).startswith("арена"))
async def arena_start(message: Message):
    parts = message.text.split()
    if len(parts) != 2:
        return await message.answer("❌ Формат: `арена 100`\nПример: `арена 500`")
    
    try:
        bet = parse_amount(parts[1])
    except:
        return await message.answer("❌ Неверная ставка")
    
    if bet < MIN_BET:
        return await message.answer(f"❌ Минимальная ставка: {fmt_money(MIN_BET)}")
    
    ok, _ = reserve_bet(message.from_user.id, bet)
    if not ok:
        return await message.answer(f"❌ Недостаточно средств. Ваш баланс: {fmt_money(get_user(message.from_user.id)['coins'])}")
    
    ARENA_GAMES[message.from_user.id] = {"bet": bet, "round": 1, "max_rounds": 3}
    await message.answer(
        f"⚔️ <b>Arena</b>\n"
        f"💰 Ставка: {fmt_money(bet)}\n"
        f"🏆 Раунд: 1/{ARENA_GAMES[message.from_user.id]['max_rounds']}\n"
        f"🎯 Множитель: x1.0\n\n"
        f"Выберите бойца:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚔️ ЛЕВЫЙ БОЕЦ", callback_data=f"arena:left")],
            [InlineKeyboardButton(text="⚔️ ПРАВЫЙ БОЕЦ", callback_data=f"arena:right")],
            [InlineKeyboardButton(text="💰 ЗАБРАТЬ", callback_data=f"arena:cash")],
        ])
    )

@dp.callback_query(F.data.startswith("arena:"))
async def arena_callback(query: CallbackQuery):
    user_id = query.from_user.id
    game = ARENA_GAMES.get(user_id)
    if not game:
        return await query.answer("❌ Нет активной игры", show_alert=True)
    
    action = query.data.split(":")[-1]
    
    if action == "cash":
        if game["round"] == 1:
            payout = game["bet"]
        else:
            payout = game["bet"] * (1 + (game["round"] - 1) * 0.5)
        bal = finalize_reserved_bet(user_id, game["bet"], payout, "arena", "cashout")
        ARENA_GAMES.pop(user_id)
        await query.message.edit_text(f"✅ ВЫИГРЫШ!\n💰 Выплата: {fmt_money(payout)}\n💎 Баланс: {fmt_money(bal)}")
        return await query.answer()
    
    winner = random.choice(["left", "right"])
    
    if action != winner:
        bal = finalize_reserved_bet(user_id, game["bet"], 0, "arena", "lose")
        ARENA_GAMES.pop(user_id)
        await query.message.edit_text(f"💥 ПОРАЖЕНИЕ! Ваш боец проиграл!\n❌ ПРОИГРЫШ\n💎 Баланс: {fmt_money(bal)}")
        return await query.answer()
    
    game["round"] += 1
    
    if game["round"] > game["max_rounds"]:
        payout = game["bet"] * (1 + (game["max_rounds"] - 1) * 0.5)
        bal = finalize_reserved_bet(user_id, game["bet"], payout, "arena", "win")
        ARENA_GAMES.pop(user_id)
        await query.message.edit_text(f"🏆 ПОБЕДА! Арена пройдена!\n💰 Выплата: {fmt_money(payout)}\n💎 Баланс: {fmt_money(bal)}")
        return await query.answer()
    
    ARENA_GAMES[user_id] = game
    current_mult = 1 + (game["round"] - 1) * 0.5
    await query.message.edit_text(
        f"⚔️ <b>Arena</b>\n"
        f"💰 Ставка: {fmt_money(game['bet'])}\n"
        f"🏆 Раунд: {game['round']}/{game['max_rounds']}\n"
        f"🎯 Множитель: x{current_mult:.1f}\n"
        f"💰 Потенциал: {fmt_money(game['bet'] * current_mult)}\n\n"
        f"Выберите бойца:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚔️ ЛЕВЫЙ БОЕЦ", callback_data=f"arena:left")],
            [InlineKeyboardButton(text="⚔️ ПРАВЫЙ БОЕЦ", callback_data=f"arena:right")],
            [InlineKeyboardButton(text="💰 ЗАБРАТЬ", callback_data=f"arena:cash")],
        ])
    )
    await query.answer("✅ ПОБЕДА!")

# ==================== ИГРА КАЗИНО ====================
@dp.message(lambda m: normalize_text(m.text).startswith("казино"))
async def casino_game(message: Message):
    if not check_cooldown(message.from_user.id):
        return await message.answer("⏳ Подождите 2.5 секунды перед следующей игрой")
    
    parts = message.text.split()
    if len(parts) != 2:
        return await message.answer("❌ Формат: `казино 100`\nПример: `казино 500`")
    
    try:
        bet = parse_amount(parts[1])
    except:
        return await message.answer("❌ Неверная ставка")
    
    if bet < MIN_BET:
        return await message.answer(f"❌ Минимальная ставка: {fmt_money(MIN_BET)}")
    
    # Казино - рулетка с 3 слотами
    slots = [random.randint(1, 9) for _ in range(3)]
    
    if slots[0] == slots[1] == slots[2]:
        multiplier = 10.0
        result_text = "🎰 ДЖЕКПОТ! ТРИ ОДИНАКОВЫХ!"
    elif slots[0] == slots[1] or slots[1] == slots[2] or slots[0] == slots[2]:
        multiplier = 2.0
        result_text = "🎰 ХОРОШО! ДВА ОДИНАКОВЫХ!"
    else:
        multiplier = 0
        result_text = "🎰 НЕ ПОВЕЗЛО..."
    
    win = multiplier > 0
    payout = bet * multiplier if win else 0
    
    ok, bal = settle_instant_bet(message.from_user.id, bet, payout, "casino", f"{slots}")
    if not ok:
        return await message.answer(f"❌ Недостаточно средств. Ваш баланс: {fmt_money(get_user(message.from_user.id)['coins'])}")
    
    await message.answer_dice(emoji="🎲")
    
    await message.answer(
        f"🎰 <b>Казино</b>\n"
        f"┌─────┬─────┬─────┐\n"
        f"│  {slots[0]}  │  {slots[1]}  │  {slots[2]}  │\n"
        f"└─────┴─────┴─────┘\n"
        f"{result_text}\n"
        f"{'✅ ПОБЕДА! x' + str(multiplier) if win else '❌ ПОРАЖЕНИЕ'}\n"
        f"💰 Выплата: {fmt_money(payout)}\n"
        f"💎 Баланс: {fmt_money(bal)}"
    )

# ==================== ИГРА ХОККЕЙ ====================
@dp.message(lambda m: normalize_text(m.text).startswith("хоккей"))
async def hockey_game(message: Message):
    if not check_cooldown(message.from_user.id):
        return await message.answer("⏳ Подождите 2.5 секунды перед следующей игрой")
    
    parts = message.text.split()
    if len(parts) != 2:
        return await message.answer("❌ Формат: `хоккей 100`\nПример: `хоккей 500`")
    
    try:
        bet = parse_amount(parts[1])
    except:
        return await message.answer("❌ Неверная ставка")
    
    if bet < MIN_BET:
        return await message.answer(f"❌ Минимальная ставка: {fmt_money(MIN_BET)}")
    
    dice_msg = await message.answer_dice(emoji="🏒")
    value = dice_msg.dice.value
    
    if value == 6:
        multiplier = 5.0
        result_text = "🏒 ГОЛ! ШАЙБА В ВОРОТАХ!"
    elif value >= 4:
        multiplier = 2.0
        result_text = "🏒 БЛИЗКО! ШТАНГА!"
    else:
        multiplier = 0
        result_text = "🏒 МИМО! БРОСОК НЕТОЧНЫЙ!"
    
    win = multiplier > 0
    payout = bet * multiplier if win else 0
    
    ok, bal = settle_instant_bet(message.from_user.id, bet, payout, "hockey", f"value={value}")
    if not ok:
        return await message.answer(f"❌ Недостаточно средств. Ваш баланс: {fmt_money(get_user(message.from_user.id)['coins'])}")
    
    await message.answer(
        f"🏒 <b>Хоккей</b>\n"
        f"📊 Сила броска: <b>{value}/6</b>\n"
        f"{result_text}\n"
        f"{'✅ ПОБЕДА! x' + str(multiplier) if win else '❌ ПОРАЖЕНИЕ'}\n"
        f"💰 Выплата: {fmt_money(payout)}\n"
        f"💎 Баланс: {fmt_money(bal)}"
    )

# ==================== ИГРА ДУЭЛЬ ====================
@dp.message(lambda m: normalize_text(m.text).startswith("дуэль"))
async def duel_start(message: Message):
    parts = message.text.split()
    if len(parts) != 2:
        return await message.answer("❌ Формат: `дуэль 100`\nПример: `дуэль 500`")
    
    try:
        bet = parse_amount(parts[1])
    except:
        return await message.answer("❌ Неверная ставка")
    
    if bet < MIN_BET:
        return await message.answer(f"❌ Минимальная ставка: {fmt_money(MIN_BET)}")
    
    ok, _ = reserve_bet(message.from_user.id, bet)
    if not ok:
        return await message.answer(f"❌ Недостаточно средств. Ваш баланс: {fmt_money(get_user(message.from_user.id)['coins'])}")
    
    DUEL_GAMES[message.from_user.id] = {"bet": bet, "round": 1, "max_rounds": 3}
    await message.answer(
        f"🤺 <b>Дуэль</b>\n"
        f"💰 Ставка: {fmt_money(bet)}\n"
        f"🏆 Дуэль: 1/{DUEL_GAMES[message.from_user.id]['max_rounds']}\n"
        f"🎯 Множитель: x1.0\n\n"
        f"Сделайте выбор:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚔️ ВЫСТРЕЛ", callback_data=f"duel:shoot")],
            [InlineKeyboardButton(text="🛡️ ЗАЩИТА", callback_data=f"duel:defend")],
            [InlineKeyboardButton(text="💰 ЗАБРАТЬ", callback_data=f"duel:cash")],
        ])
    )

@dp.callback_query(F.data.startswith("duel:"))
async def duel_callback(query: CallbackQuery):
    user_id = query.from_user.id
    game = DUEL_GAMES.get(user_id)
    if not game:
        return await query.answer("❌ Нет активной игры", show_alert=True)
    
    action = query.data.split(":")[-1]
    
    if action == "cash":
        if game["round"] == 1:
            payout = game["bet"]
        else:
            payout = game["bet"] * (1 + (game["round"] - 1) * 0.6)
        bal = finalize_reserved_bet(user_id, game["bet"], payout, "duel", "cashout")
        DUEL_GAMES.pop(user_id)
        await query.message.edit_text(f"✅ ВЫИГРЫШ!\n💰 Выплата: {fmt_money(payout)}\n💎 Баланс: {fmt_money(bal)}")
        return await query.answer()
    
    opponent = random.choice(["shoot", "defend"])
    
    if action == "shoot" and opponent == "defend":
        win = True
        result_text = "💥 ВАШ ВЫСТРЕЛ ПОПАЛ! Противник не защитился!"
    elif action == "defend" and opponent == "shoot":
        win = True
        result_text = "🛡️ ВЫ ЗАЩИТИЛИСЬ! Противник промахнулся!"
    else:
        win = False
        if action == "shoot" and opponent == "shoot":
            result_text = "💢 ОБА ВЫСТРЕЛИЛИ! ОБА РАНЕНЫ!"
        else:
            result_text = "🤝 ОБА ЗАЩИТИЛИСЬ! НИЧЬЯ!"
    
    if not win:
        bal = finalize_reserved_bet(user_id, game["bet"], 0, "duel", "lose")
        DUEL_GAMES.pop(user_id)
        await query.message.edit_text(f"💔 {result_text}\n❌ ПОРАЖЕНИЕ\n💎 Баланс: {fmt_money(bal)}")
        return await query.answer()
    
    game["round"] += 1
    
    if game["round"] > game["max_rounds"]:
        payout = game["bet"] * (1 + (game["max_rounds"] - 1) * 0.6)
        bal = finalize_reserved_bet(user_id, game["bet"], payout, "duel", "win")
        DUEL_GAMES.pop(user_id)
        await query.message.edit_text(f"🏆 ПОБЕДА! Вы выиграли дуэль!\n💰 Выплата: {fmt_money(payout)}\n💎 Баланс: {fmt_money(bal)}")
        return await query.answer()
    
    DUEL_GAMES[user_id] = game
    current_mult = 1 + (game["round"] - 1) * 0.6
    await query.message.edit_text(
        f"🤺 <b>Дуэль</b>\n"
        f"✅ {result_text}\n\n"
        f"💰 Ставка: {fmt_money(game['bet'])}\n"
        f"🏆 Дуэль: {game['round']}/{game['max_rounds']}\n"
        f"🎯 Множитель: x{current_mult:.1f}\n"
        f"💰 Потенциал: {fmt_money(game['bet'] * current_mult)}\n\n"
        f"Сделайте выбор:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚔️ ВЫСТРЕЛ", callback_data=f"duel:shoot")],
            [InlineKeyboardButton(text="🛡️ ЗАЩИТА", callback_data=f"duel:defend")],
            [InlineKeyboardButton(text="💰 ЗАБРАТЬ", callback_data=f"duel:cash")],
        ])
    )
    await query.answer("✅ ПОБЕДА!")# ==================== ЧЕКИ ====================
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
        return False, "Ошибка создания чека"
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
        return False, "Ошибка активации", 0
    finally:
        conn.close()

@dp.message(lambda m: normalize_text(m.text) in {"чеки", "/checks", "check"})
async def checks_command(message: Message):
    await message.answer("🧾 <b>Чеки</b>\nВыберите действие:", reply_markup=checks_kb())

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
        return await message.answer("❌ Введите корректную сумму")
    if amount < 10:
        return await message.answer(f"❌ Минимальная сумма: {fmt_money(10)}")
    await state.update_data(amount=amount)
    await state.set_state(CheckCreateStates.waiting_count)
    await message.answer("🔢 Введите количество активаций (1-100):")

@dp.message(CheckCreateStates.waiting_count)
async def checks_create_count(message: Message, state: FSMContext):
    try:
        count = int(message.text)
    except:
        return await message.answer("❌ Введите целое число")
    if count < 1 or count > 100:
        return await message.answer("❌ Количество должно быть от 1 до 100")
    data = await state.get_data()
    amount = data["amount"]
    ok, code = create_check_atomic(message.from_user.id, amount, count)
    await state.clear()
    if not ok:
        return await message.answer(f"❌ {code}")
    await message.answer(
        f"✅ <b>Чек создан!</b>\n\n"
        f"📝 Код: <code>{code}</code>\n"
        f"💰 Сумма: {fmt_money(amount)}\n"
        f"🎟 Активаций: {count}\n\n"
        f"Поделитесь кодом с друзьями!"
    )

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
        return await query.message.answer("📭 У вас пока нет созданных чеков")
    lines = ["🧾 <b>Мои чеки</b>:", "<blockquote>"]
    for r in rows:
        lines.append(f"<code>{r['code']}</code> | {fmt_money(r['per_user'])} | осталось {r['remaining']}")
    lines.append("</blockquote>")
    await query.message.answer("\n".join(lines))
    await query.answer()

# ==================== ПРОМОКОДЫ ====================
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

@dp.message(Command("addpromo"))
async def addpromo_command(message: Message):
    if not is_admin_user(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) != 4:
        return await message.answer("📝 Формат: /addpromo КОД СУММА АКТИВАЦИИ")
    code = parts[1].upper().strip()
    try:
        reward = parse_amount(parts[2])
        activations = int(parts[3])
    except:
        return await message.answer("❌ Неверные данные")
    create_promo(code, reward, activations)
    await message.answer(f"✅ Промокод <code>{code}</code> создан!\n💰 Награда: {fmt_money(reward)}\n🎟 Активаций: {activations}")

# ==================== БАНК ====================
def add_deposit(user_id: int, amount: float, term_days: int):
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

@dp.message(lambda m: normalize_text(m.text) in {"банк", "/bank", "bank"})
async def bank_command(message: Message):
    user = get_user(message.from_user.id)
    conn = get_db()
    active = conn.execute("SELECT COUNT(*) as c, COALESCE(SUM(principal),0) as s FROM bank_deposits WHERE user_id=? AND status='active'", (str(message.from_user.id),)).fetchone()
    conn.close()
    await message.answer(
        f"🏦 <b>Банк {CURRENCY_NAME}</b>\n\n"
        f"💰 Баланс: {fmt_money(float(user['coins']))}\n"
        f"📊 Активных депозитов: {active['c']}\n"
        f"💵 Сумма в депозитах: {fmt_money(active['s'])}\n\n"
        f"📈 Ставки:\n"
        f"• 7 дней: +3%\n"
        f"• 14 дней: +7%\n"
        f"• 30 дней: +18%",
        reply_markup=bank_kb()
    )

@dp.callback_query(F.data == "bank:open")
async def bank_open_cb(query: CallbackQuery, state: FSMContext):
    await state.set_state(BankStates.waiting_amount)
    await query.message.answer("💰 Введите сумму депозита (мин 100):")
    await query.answer()

@dp.message(BankStates.waiting_amount)
async def bank_amount(message: Message, state: FSMContext):
    try:
        amount = parse_amount(message.text)
    except:
        return await message.answer("❌ Введите корректную сумму")
    if amount < 100:
        return await message.answer(f"❌ Минимальный депозит: {fmt_money(100)}")
    await state.update_data(amount=amount)
    await message.answer("📅 Выберите срок депозита:", reply_markup=bank_terms_kb())

@dp.callback_query(F.data.startswith("bank:term:"))
async def bank_term_cb(query: CallbackQuery, state: FSMContext):
    term = query.data.split(":")[-1]
    if term == "cancel":
        await state.clear()
        await query.message.edit_text("❌ Открытие депозита отменено")
        return await query.answer()
    data = await state.get_data()
    amount = data.get("amount", 0)
    if amount <= 0:
        await state.clear()
        return await query.answer("❌ Ошибка, начните заново", show_alert=True)
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
        return await query.message.answer("📭 У вас пока нет депозитов")
    now = now_ts()
    lines = ["📜 <b>Мои депозиты</b>:", "<blockquote>"]
    for r in rows:
        unlock = r["opened_at"] + r["term_days"] * 86400
        if r["status"] == "active":
            if unlock <= now:
                status = "✅ готов к снятию"
            else:
                status = f"⏳ {fmt_left(unlock-now)}"
        else:
            status = "🔒 закрыт"
        lines.append(f"#{r['id']} | {fmt_money(r['principal'])} | +{int(r['rate']*100)}% | {status}")
    lines.append("</blockquote>")
    await query.message.answer("\n".join(lines))
    await query.answer()

@dp.callback_query(F.data == "bank:withdraw")
async def bank_withdraw_cb(query: CallbackQuery):
    count, total = withdraw_matured_deposits(query.from_user.id)
    if count == 0:
        await query.message.answer("📭 Нет зрелых депозитов для вывода")
    else:
        await query.message.answer(f"✅ Выведено {count} депозитов на сумму {fmt_money(total)}")
    await query.answer()

# ==================== АДМИНСКИЕ КОМАНДЫ ====================
@dp.message(Command("ban"))
async def admin_ban(message: Message):
    if not is_admin_user(message.from_user.id):
        return
    target = message.reply_to_message.from_user if message.reply_to_message else None
    if not target:
        parts = message.text.split()
        if len(parts) < 2:
            return await message.answer("📝 Ответьте на сообщение или укажите ID: /ban 123456789")
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
    await message.answer(f"✅ {mention_user(target_id)} разбанен")

@dp.message(Command("mute"))
async def admin_mute(message: Message):
    if not is_admin_user(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 3:
        return await message.answer("📝 Формат: /mute @user 5")
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
            return await message.answer("📝 Формат: /выдать @user 1000")
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
            await message.bot.send_message(int(row["id"]), text, parse_mode="HTML")
            sent += 1
            await asyncio.sleep(0.05)
        except:
            pass
    await message.answer(f"📢 Рассылка завершена!\n✅ Отправлено: {sent} пользователям")

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
            await message.bot.send_message(int(row["id"]), text, parse_mode="HTML")
            sent += 1
            await asyncio.sleep(0.05)
        except:
            pass
    await message.answer(f"📢 Рассылка завершена!\n✅ Отправлено: {sent} пользователям")

@dp.message(Command("massbonus"))
async def admin_mass_bonus(message: Message):
    if not is_admin_user(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) != 2:
        return await message.answer("📝 Формат: /massbonus 100")
    try:
        amount = parse_amount(parts[1])
    except:
        return await message.answer("❌ Неверная сумма")
    conn = get_db()
    conn.execute("UPDATE users SET coins = coins + ?", (amount,))
    conn.commit()
    conn.close()
    await message.answer(f"✅ Всем пользователям начислено по {fmt_money(amount)}!")

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
        f"📊 <b>Статистика бота</b>\n\n"
        f"👥 Пользователей: {users}\n"
        f"🎲 Ставок сделано: {bets['c'] or 0}\n"
        f"💰 Общая сумма ставок: {fmt_money(bets['b'] or 0)}\n"
        f"💸 Выплачено: {fmt_money(bets['p'] or 0)}\n"
        f"🏦 Комиссий собрано: {fmt_money(sys['coins'] if sys else 0)}"
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
        f"📊 Приглашено друзей: {count}\n"
        f"🎁 Бонусы:\n"
        f"• Вы получаете: +{fmt_money(REFERRER_BONUS)}\n"
        f"• Друг получает: +{fmt_money(REFERRED_BONUS)}\n\n"
        f"💡 Другу нужно перейти по ссылке и начать играть!"
    )

@dp.message(Command("donate"))
async def donate_command(message: Message):
    await message.answer(
        f"⭐ <b>Пополнение {CURRENCY_NAME}</b>\n\n"
        f"1 Telegram Star = {STARS_RATE} {CURRENCY_NAME}\n\n"
        f"Выберите сумму в меню: /menu",
        reply_markup=main_menu_kb()
    )

# ==================== КОМАНДЫ ДЛЯ ТЕКСТОВОГО ВЫЗОВА ====================
@dp.message(lambda m: normalize_text(m.text) in {"б", "баланс", "/balance", "balance"})
async def balance_command(message: Message):
    user = get_user(message.from_user.id)
    await message.answer(f"💰 {mention_user(message.from_user.id, message.from_user.first_name)}, баланс: {fmt_money(float(user['coins']))}")

@dp.message(lambda m: normalize_text(m.text) in {"профиль", "/profile", "profile"})
async def profile_command(message: Message):
    user = get_user(message.from_user.id)
    conn = get_db()
    bets = conn.execute("SELECT COUNT(*) as total, SUM(CASE WHEN win=1 THEN 1 ELSE 0 END) as wins FROM bets WHERE user_id=?", (str(message.from_user.id),)).fetchone()
    conn.close()
    total = bets["total"] or 1
    wr = (bets["wins"] / total * 100)
    await message.answer(
        f"👤 <b>Профиль</b>\n\n"
        f"🆔 ID: {message.from_user.id}\n"
        f"💰 Баланс: {fmt_money(float(user['coins']))}\n"
        f"🎲 Ставок: {bets['total']}\n"
        f"🏆 Побед: {bets['wins']}\n"
        f"📊 Winrate: {wr:.1f}%"
    )

@dp.message(lambda m: normalize_text(m.text) in {"бонус", "/bonus", "bonus"})
async def bonus_command(message: Message):
    user_id = message.from_user.id
    key = f"bonus_ts:{user_id}"
    conn = get_db()
    row = conn.execute("SELECT value FROM json_data WHERE key=?", (key,)).fetchone()
    last = int(json.loads(row["value"])) if row else 0
    now = now_ts()
    if now - last < BONUS_COOLDOWN_SECONDS:
        left = BONUS_COOLDOWN_SECONDS - (now - last)
        return await message.answer(f"🎁 Бонус доступен через {fmt_left(left)}")
    reward = random.randint(BONUS_REWARD_MIN, BONUS_REWARD_MAX)
    ok, bal = settle_instant_bet(user_id, 0, reward, "bonus", "claim")
    if ok:
        conn.execute("INSERT OR REPLACE INTO json_data (key, value) VALUES (?, ?)", (key, json.dumps(now)))
        conn.commit()
        await message.answer(f"🎁 Бонус +{fmt_money(reward)}\n💰 Баланс: {fmt_money(bal)}")
    conn.close()

@dp.message(lambda m: normalize_text(m.text) in {"топ", "/top", "top"})
async def top_command(message: Message):
    conn = get_db()
    rows = conn.execute("SELECT id, coins FROM users ORDER BY coins DESC LIMIT 10").fetchall()
    conn.close()
    if not rows:
        return await message.answer("🏆 Топ игроков пуст")
    lines = ["🏆 <b>Топ игроков по балансу</b>", "<blockquote>"]
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    for i, row in enumerate(rows, 1):
        icon = medals.get(i, f"{i}.")
        lines.append(f"{icon} {mention_user(int(row['id']))} — {fmt_money(float(row['coins']))}")
    lines.append("</blockquote>")
    await message.answer("\n".join(lines))

@dp.message(lambda m: normalize_text(m.text) in {"игры", "/games", "games"})
async def games_command(message: Message):
    await message.answer("🎮 <b>Игры</b>\nВыберите игру:", reply_markup=games_kb())

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

# ==================== ПОПОЛНЕНИЕ (ДОНАТ) ====================
@dp.message(lambda m: normalize_text(m.text) in {"пополнить", "донат", "дон", "/donate"})
async def donate_text_command(message: Message):
    await message.answer(
        f"⭐ <b>Пополнение {CURRENCY_NAME}</b>\n\n"
        f"1 Telegram Star = {STARS_RATE} {CURRENCY_NAME}\n\n"
        f"Выберите сумму в меню: /menu",
        reply_markup=main_menu_kb()
    )

# ==================== ОТМЕНА ====================
@dp.message(lambda m: normalize_text(m.text) in {"отмена", "/cancel", "cancel"})
async def cancel_any(message: Message, state: FSMContext):
    await state.clear()
    TOWER_GAMES.pop(message.from_user.id, None)
    GOLD_GAMES.pop(message.from_user.id, None)
    DIAMOND_GAMES.pop(message.from_user.id, None)
    MINES_GAMES.pop(message.from_user.id, None)
    OCHKO_GAMES.pop(message.from_user.id, None)
    PYRAMID_GAMES.pop(message.from_user.id, None)
    ARENA_GAMES.pop(message.from_user.id, None)
    DUEL_GAMES.pop(message.from_user.id, None)
    await message.answer("🛑 Действие отменено")

# ==================== ЗАПУСК БОТА ====================
async def main():
    init_db()
    dp.message.middleware(BanMuteSubscriptionMiddleware())
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await bot.delete_webhook(drop_pending_updates=True)
    print("✅ Бот VIRTEX успешно запущен!")
    print(f"📊 Бот: @{BOT_USERNAME}")
    print(f"👑 Админы: {ADMIN_IDS}")
    print(f"🎮 Доступно игр: 22")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
