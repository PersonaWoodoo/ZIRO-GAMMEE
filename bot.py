import asyncio
import html
import json
import random
import sqlite3
import string
import time
from datetime import datetime
from typing import Any, Dict, Optional

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart, StateFilter, BaseFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    ChatMember,
)

# ==================== КОНФИГ ====================

BOT_TOKEN = "8657372135:AAEyX7RD-_WlP2fjIL2S9TCeeYRn9A1StV8"
ADMIN_IDS = {8293927811, 8478884644}

# ==================== КОНСТАНТЫ ====================

DB_PATH = "data.db"
START_BALANCE = 100.0
MIN_BET = 10.0
CURRENCY_NAME = "VIRTEX"
DONAT_CURRENCY_NAME = "VIX"
BONUS_COOLDOWN_SECONDS = 12 * 60 * 60
BONUS_REWARD_MIN = 150
BONUS_REWARD_MAX = 350

CHANNEL_ID = "@VIRTEXCHANEL"
CHAT_ID = "@VIRTEXCHATW"

BANK_TERMS = {
    7: 0.03,
    14: 0.07,
    30: 0.18,
}

RED_NUMBERS = {
    1, 3, 5, 7, 9, 12, 14, 16, 18, 19,
    21, 23, 25, 27, 30, 32, 34, 36,
}

TOWER_MULTIPLIERS = [1.20, 1.48, 1.86, 2.35, 2.95, 3.75, 4.85, 6.15]
GOLD_MULTIPLIERS = [1.15, 1.35, 1.62, 2.0, 2.55, 3.25, 4.2]
DIAMOND_MULTIPLIERS = [1.12, 1.28, 1.48, 1.72, 2.02, 2.4, 2.92, 3.6]

LEGACY_GOLD_MULTIPLIERS = [2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096]
FOOTBALL_MULTIPLIERS = {"gol": 1.6, "mimo": 2.2}

# ==================== СОСТОЯНИЯ ====================

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

# ==================== ХРАНИЛИЩА ИГР ====================

TOWER_GAMES: Dict[int, Dict[str, Any]] = {}
GOLD_GAMES: Dict[int, Dict[str, Any]] = {}
DIAMOND_GAMES: Dict[int, Dict[str, Any]] = {}
MINES_GAMES: Dict[int, Dict[str, Any]] = {}
OCHKO_GAMES: Dict[int, Dict[str, Any]] = {}

NGOLD_GAMES: Dict[str, Dict[str, Any]] = {}
NTOWER_GAMES: Dict[str, Dict[str, Any]] = {}
NMINES_GAMES: Dict[str, Dict[str, Any]] = {}
NDIAMOND_GAMES: Dict[str, Dict[str, Any]] = {}
NOCHKO_GAMES: Dict[str, Dict[str, Any]] = {}
NFOOTBALL_GAMES: Dict[int, Dict[str, Any]] = {}

user_game_locks: Dict[str, asyncio.Lock] = {}# ==================== DB HELPERS ====================

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            coins REAL DEFAULT 100.0,
            vix REAL DEFAULT 0.0,
            GGs INTEGER DEFAULT 0,
            lost_coins REAL DEFAULT 0.0,
            won_coins REAL DEFAULT 0.0,
            status INTEGER DEFAULT 0,
            checks TEXT DEFAULT '[]',
            registered_at INTEGER DEFAULT 0
        )
    """)

    try:
        cursor.execute("ALTER TABLE users ADD COLUMN vix REAL DEFAULT 0.0")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN registered_at INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN lost_coins REAL DEFAULT 0.0")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN won_coins REAL DEFAULT 0.0")
    except sqlite3.OperationalError:
        pass

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            bet_amount REAL,
            choice TEXT,
            outcome TEXT,
            win INTEGER,
            payout REAL,
            ts INTEGER
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS checks (
            code TEXT PRIMARY KEY,
            creator_id TEXT,
            per_user REAL,
            remaining INTEGER,
            claimed TEXT,
            password TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS promos (
            name TEXT PRIMARY KEY,
            reward REAL,
            claimed TEXT,
            remaining_activations INTEGER
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bank_deposits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            principal REAL,
            rate REAL,
            term_days INTEGER,
            opened_at INTEGER,
            status TEXT,
            closed_at INTEGER
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS json_data (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    conn.commit()
    conn.close()

def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def now_ts() -> int:
    return int(time.time())

def fmt_money(value: float, currency: str = CURRENCY_NAME) -> str:
    value = round(float(value), 2)
    abs_value = abs(value)
    if abs_value >= 1000:
        compact = value / 1000
        text = f"{compact:.2f}".rstrip("0").rstrip(".")
        amount = f"{text}к"
    elif abs(value - int(value)) < 1e-9:
        amount = str(int(value))
    else:
        amount = f"{value:.2f}".rstrip("0").rstrip(".")
    return f"{amount} {currency}"

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

def parse_amount(text: str) -> float:
    raw = str(text or "").strip().lower().replace(" ", "").replace(",", ".")
    multiplier = 1.0
    if raw.endswith(("к", "k")):
        raw = raw[:-1]
        multiplier = 1000.0
    value = float(raw) * multiplier
    if value <= 0:
        raise ValueError("amount must be positive")
    return round(value, 2)

def parse_int(text: str) -> int:
    return int(str(text or "").strip())

def parse_bet_legacy(raw: str, balance: float) -> int:
    arg = str(raw or "").strip().lower().replace(" ", "")
    if arg in {"все", "всё"}:
        return int(balance)
    return int(parse_amount(arg))

def normalize_text(text: Optional[str]) -> str:
    s = str(text or "").lower().strip()
    for symbol in ["💰", "👤", "🎁", "🎮", "🧾", "🏦", "🎟", "❓", "✨", "•", "|"]:
        s = s.replace(symbol, " ")
    return " ".join(s.split())

def escape_html(text: Optional[str]) -> str:
    return html.escape(str(text or ""), quote=False)

def mention_user(user_id: int, name: Optional[str] = None) -> str:
    label = escape_html(name or f"Игрок {user_id}")
    return f'<a href="tg://user?id={int(user_id)}">{label}</a>'

def headline_user(emoji: str, user_id: int, name: Optional[str], text: str) -> str:
    return f"{emoji} {mention_user(user_id, name)}, {escape_html(text)}"

def normalize_promo_code(text: str) -> str:
    code = str(text or "").strip().upper()
    allowed = set(string.ascii_uppercase + string.digits + "_-")
    if not (3 <= len(code) <= 24):
        raise ValueError("length")
    if any(ch not in allowed for ch in code):
        raise ValueError("symbols")
    return code

def is_admin_user(user_id: int) -> bool:
    return int(user_id) in ADMIN_IDS

def ensure_user_in_conn(conn: sqlite3.Connection, user_id: int) -> None:
    now = now_ts()
    row = conn.execute("SELECT id, registered_at FROM users WHERE id = ?", (str(user_id),)).fetchone()
    if not row:
        conn.execute(
            """
            INSERT INTO users (id, coins, vix, GGs, lost_coins, won_coins, status, checks, registered_at)
            VALUES (?, ?, 0, 0, 0, 0, 0, '[]', ?)
            """,
            (str(user_id), START_BALANCE, now),
        )
    elif not row["registered_at"]:
        conn.execute("UPDATE users SET registered_at = ? WHERE id = ?", (now, str(user_id)))

def ensure_user(user_id: int) -> None:
    conn = get_db()
    try:
        ensure_user_in_conn(conn, user_id)
        conn.commit()
    finally:
        conn.close()

def get_user(user_id: int) -> sqlite3.Row:
    conn = get_db()
    try:
        ensure_user_in_conn(conn, user_id)
        row = conn.execute("SELECT * FROM users WHERE id = ?", (str(user_id),)).fetchone()
        conn.commit()
        return row
    finally:
        conn.close()

def set_json_value(key: str, value: Any) -> None:
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO json_data (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value, ensure_ascii=False)),
        )
        conn.commit()
    finally:
        conn.close()

def get_json_value(key: str, default: Any = None) -> Any:
    conn = get_db()
    try:
        row = conn.execute("SELECT value FROM json_data WHERE key = ?", (key,)).fetchone()
        if not row:
            return default
        try:
            return json.loads(row["value"])
        except Exception:
            return default
    finally:
        conn.close()

def reserve_bet(user_id: int, bet: float) -> tuple[bool, float]:
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        ensure_user_in_conn(conn, user_id)
        row = conn.execute("SELECT coins FROM users WHERE id = ?", (str(user_id),)).fetchone()
        coins = float(row["coins"] or 0)
        if coins < bet:
            conn.rollback()
            return False, coins
        new_balance = round(coins - bet, 2)
        conn.execute("UPDATE users SET coins = ? WHERE id = ?", (new_balance, str(user_id)))
        conn.commit()
        return True, new_balance
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def finalize_reserved_bet(
    user_id: int, bet: float, payout: float, choice: str, outcome: str,
) -> float:
    payout = round(max(0.0, payout), 2)
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        ensure_user_in_conn(conn, user_id)
        if payout > 0:
            conn.execute("UPDATE users SET coins = coins + ? WHERE id = ?", (payout, str(user_id)))
        conn.execute(
            """
            INSERT INTO bets (user_id, bet_amount, choice, outcome, win, payout, ts)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (str(user_id), round(bet, 2), choice, outcome, 1 if payout > 0 else 0, payout, now_ts()),
        )
        # Обновляем статистику
        if payout <= 0:
            conn.execute("UPDATE users SET lost_coins = lost_coins + ? WHERE id = ?", (bet, str(user_id)))
        else:
            conn.execute("UPDATE users SET won_coins = won_coins + ? WHERE id = ?", (payout - bet, str(user_id)))
        row = conn.execute("SELECT coins FROM users WHERE id = ?", (str(user_id),)).fetchone()
        conn.commit()
        return float(row["coins"] or 0)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def settle_instant_bet(
    user_id: int, bet: float, payout: float, choice: str, outcome: str,
) -> tuple[bool, float]:
    payout = round(max(0.0, payout), 2)
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        ensure_user_in_conn(conn, user_id)
        row = conn.execute("SELECT coins FROM users WHERE id = ?", (str(user_id),)).fetchone()
        coins = float(row["coins"] or 0)
        if coins < bet:
            conn.rollback()
            return False, coins
        new_balance = round(coins - bet + payout, 2)
        conn.execute("UPDATE users SET coins = ? WHERE id = ?", (new_balance, str(user_id)))
        conn.execute(
            """
            INSERT INTO bets (user_id, bet_amount, choice, outcome, win, payout, ts)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (str(user_id), round(bet, 2), choice, outcome, 1 if payout > 0 else 0, payout, now_ts()),
        )
        if payout <= 0:
            conn.execute("UPDATE users SET lost_coins = lost_coins + ? WHERE id = ?", (bet, str(user_id)))
        else:
            conn.execute("UPDATE users SET won_coins = won_coins + ? WHERE id = ?", (payout - bet, str(user_id)))
        conn.commit()
        return True, new_balance
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def add_balance(user_id: int, delta: float) -> float:
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        ensure_user_in_conn(conn, user_id)
        conn.execute("UPDATE users SET coins = coins + ? WHERE id = ?", (round(delta, 2), str(user_id)))
        row = conn.execute("SELECT coins FROM users WHERE id = ?", (str(user_id),)).fetchone()
        conn.commit()
        return float(row["coins"] or 0)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def get_profile_stats(user_id: int) -> Dict[str, Any]:
    conn = get_db()
    try:
        ensure_user_in_conn(conn, user_id)
        user = conn.execute("SELECT * FROM users WHERE id = ?", (str(user_id),)).fetchone()
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                COALESCE(SUM(CASE WHEN win = 1 THEN 1 ELSE 0 END), 0) AS wins,
                COALESCE(SUM(payout - bet_amount), 0) AS net,
                COALESCE(SUM(bet_amount), 0) AS total_bet
            FROM bets
            WHERE user_id = ?
            """,
            (str(user_id),),
        ).fetchone()
        dep = conn.execute(
            """
            SELECT
                COUNT(*) AS active_count,
                COALESCE(SUM(principal), 0) AS active_sum
            FROM bank_deposits
            WHERE user_id = ? AND status = 'active'
            """,
            (str(user_id),),
        ).fetchone()
        conn.commit()
        return {
            "coins": float(user["coins"] or 0),
            "vix": float(user["vix"] or 0),
            "status": int(user["status"] or 0),
            "total": int(row["total"] or 0),
            "wins": int(row["wins"] or 0),
            "net": float(row["net"] or 0),
            "total_bet": float(row["total_bet"] or 0),
            "active_deposits": int(dep["active_count"] or 0),
            "active_deposit_sum": float(dep["active_sum"] or 0),
        }
    finally:
        conn.close()

def get_top_balances(limit: int = 10) -> list[sqlite3.Row]:
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, coins FROM users ORDER BY coins DESC, id ASC LIMIT ?",
            (int(limit),),
        ).fetchall()
        conn.commit()
        return list(rows)
    finally:
        conn.close()

def generate_check_code(conn: sqlite3.Connection) -> str:
    while True:
        code = "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
        row = conn.execute("SELECT 1 FROM checks WHERE code = ?", (code,)).fetchone()
        if not row:
            return code

def create_check_atomic(user_id: int, per_user: float, count: int) -> tuple[bool, str]:
    total = round(per_user * count, 2)
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        ensure_user_in_conn(conn, user_id)
        row = conn.execute("SELECT coins FROM users WHERE id = ?", (str(user_id),)).fetchone()
        coins = float(row["coins"] or 0)
        if coins < total:
            conn.rollback()
            return (False, "Недостаточно средств для создания чека.")
        code = generate_check_code(conn)
        conn.execute("UPDATE users SET coins = coins - ? WHERE id = ?", (total, str(user_id)))
        conn.execute(
            """
            INSERT INTO checks (code, creator_id, per_user, remaining, claimed, password)
            VALUES (?, ?, ?, ?, ?, NULL)
            """,
            (code, str(user_id), round(per_user, 2), int(count), "[]"),
        )
        conn.commit()
        return True, code
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def claim_check_atomic(user_id: int, code: str) -> tuple[bool, str, float]:
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        ensure_user_in_conn(conn, user_id)
        row = conn.execute("SELECT * FROM checks WHERE code = ?", (code.upper(),)).fetchone()
        if not row:
            conn.rollback()
            return False, "Чек не найден.", 0.0
        if int(row["remaining"] or 0) <= 0:
            conn.rollback()
            return False, "Этот чек уже закончился.", 0.0
        claimed_raw = row["claimed"] or "[]"
        try:
            claimed = json.loads(claimed_raw)
        except Exception:
            claimed = []
        if str(user_id) in {str(x) for x in claimed}:
            conn.rollback()
            return False, "Ты уже активировал этот чек.", 0.0
        claimed.append(str(user_id))
        reward = round(float(row["per_user"] or 0), 2)
        conn.execute("UPDATE users SET coins = coins + ? WHERE id = ?", (reward, str(user_id)))
        conn.execute(
            "UPDATE checks SET remaining = remaining - 1, claimed = ? WHERE code = ?",
            (json.dumps(claimed, ensure_ascii=False), code.upper()),
        )
        conn.commit()
        return True, "Чек успешно активирован.", reward
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def list_my_checks(user_id: int) -> list[sqlite3.Row]:
    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT code, per_user, remaining
            FROM checks
            WHERE creator_id = ?
            ORDER BY rowid DESC
            LIMIT 10
            """,
            (str(user_id),),
        ).fetchall()
        return list(rows)
    finally:
        conn.close()

def redeem_promo_atomic(user_id: int, code: str) -> tuple[bool, str, float]:
    promo_name = code.upper().strip()
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        ensure_user_in_conn(conn, user_id)
        row = conn.execute("SELECT * FROM promos WHERE name = ?", (promo_name,)).fetchone()
        if not row:
            conn.rollback()
            return False, "Промокод не найден.", 0.0
        remaining = int(row["remaining_activations"] or 0)
        if remaining <= 0:
            conn.rollback()
            return False, "Промокод уже закончился.", 0.0
        try:
            claimed = json.loads(row["claimed"] or "[]")
        except Exception:
            claimed = []
        if str(user_id) in {str(x) for x in claimed}:
            conn.rollback()
            return (False, "Ты уже активировал этот промокод.", 0.0)
        reward = round(float(row["reward"] or 0), 2)
        claimed.append(str(user_id))
        conn.execute("UPDATE users SET coins = coins + ? WHERE id = ?", (reward, str(user_id)))
        conn.execute(
            "UPDATE promos SET claimed = ?, remaining_activations = remaining_activations - 1 WHERE name = ?",
            (json.dumps(claimed, ensure_ascii=False), promo_name),
        )
        conn.commit()
        return True, "Промокод активирован.", reward
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def create_promo(code: str, reward: float, activations: int) -> None:
    conn = get_db()
    try:
        conn.execute(
            """
            INSERT INTO promos (name, reward, claimed, remaining_activations)
            VALUES (?, ?, '[]', ?)
            ON CONFLICT(name) DO UPDATE
            SET reward = excluded.reward,
                remaining_activations = excluded.remaining_activations,
                claimed = '[]'
            """,
            (code.upper().strip(), round(reward, 2), int(activations)),
        )
        conn.commit()
    finally:
        conn.close()

def add_deposit(user_id: int, amount: float, term_days: int) -> tuple[bool, str]:
    rate = BANK_TERMS.get(term_days)
    if rate is None:
        return False, "Неверный срок депозита."
    ok, _ = reserve_bet(user_id, amount)
    if not ok:
        return (False, "Недостаточно средств для открытия депозита.")
    conn = get_db()
    try:
        conn.execute(
            """
            INSERT INTO bank_deposits (user_id, principal, rate, term_days, opened_at, status, closed_at)
            VALUES (?, ?, ?, ?, ?, 'active', NULL)
            """,
            (str(user_id), round(amount, 2), float(rate), int(term_days), now_ts()),
        )
        conn.commit()
        return True, "Депозит открыт."
    finally:
        conn.close()

def list_user_deposits(user_id: int, active_only: bool = False) -> list[sqlite3.Row]:
    conn = get_db()
    try:
        if active_only:
            rows = conn.execute(
                """
                SELECT * FROM bank_deposits
                WHERE user_id = ? AND status = 'active'
                ORDER BY id DESC
                """,
                (str(user_id),),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM bank_deposits
                WHERE user_id = ?
                ORDER BY id DESC
                LIMIT 15
                """,
                (str(user_id),),
            ).fetchall()
        return list(rows)
    finally:
        conn.close()

def withdraw_matured_deposits(user_id: int) -> tuple[int, float]:
    now = now_ts()
    conn = get_db()
    total_payout = 0.0
    closed_count = 0
    try:
        conn.execute("BEGIN IMMEDIATE")
        ensure_user_in_conn(conn, user_id)
        rows = conn.execute(
            """
            SELECT * FROM bank_deposits
            WHERE user_id = ? AND status = 'active'
            """,
            (str(user_id),),
        ).fetchall()
        for row in rows:
            unlock_ts = int(row["opened_at"] or 0) + int(row["term_days"] or 0) * 86400
            if now < unlock_ts:
                continue
            principal = float(row["principal"] or 0)
            rate = float(row["rate"] or 0)
            payout = round(principal * (1.0 + rate), 2)
            total_payout += payout
            closed_count += 1
            conn.execute(
                "UPDATE bank_deposits SET status = 'closed', closed_at = ? WHERE id = ?",
                (now, int(row["id"])),
            )
        if total_payout > 0:
            conn.execute("UPDATE users SET coins = coins + ? WHERE id = ?", (round(total_payout, 2), str(user_id)))
        conn.commit()
        return closed_count, round(total_payout, 2)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def get_bank_summary(user_id: int) -> Dict[str, Any]:
    conn = get_db()
    try:
        ensure_user_in_conn(conn, user_id)
        user = conn.execute("SELECT coins FROM users WHERE id = ?", (str(user_id),)).fetchone()
        deps = conn.execute(
            """
            SELECT
                COUNT(*) AS count_active,
                COALESCE(SUM(principal), 0) AS active_sum
            FROM bank_deposits
            WHERE user_id = ? AND status = 'active'
            """,
            (str(user_id),),
        ).fetchone()
        conn.commit()
        return {
            "coins": float(user["coins"] or 0),
            "count_active": int(deps["count_active"] or 0),
            "active_sum": float(deps["active_sum"] or 0),
        }
    finally:
        conn.close()# ==================== UI КЛАВИАТУРЫ ====================

def games_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🗼 Башня", callback_data="games:pick:tower"),
                InlineKeyboardButton(text="🥇 Золото", callback_data="games:pick:gold"),
            ],
            [
                InlineKeyboardButton(text="💎 Алмазы", callback_data="games:pick:diamonds"),
                InlineKeyboardButton(text="💣 Мины", callback_data="games:pick:mines"),
            ],
            [
                InlineKeyboardButton(text="🎴 Очко", callback_data="games:pick:ochko"),
                InlineKeyboardButton(text="🎡 Рулетка", callback_data="games:pick:roulette"),
            ],
            [
                InlineKeyboardButton(text="📈 Краш", callback_data="games:pick:crash"),
                InlineKeyboardButton(text="🎲 Кубик", callback_data="games:pick:cube"),
            ],
            [
                InlineKeyboardButton(text="🎯 Кости", callback_data="games:pick:dice"),
                InlineKeyboardButton(text="⚽ Футбол", callback_data="games:pick:football"),
            ],
            [InlineKeyboardButton(text="🏀 Баскет", callback_data="games:pick:basket")],
        ]
    )

def checks_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Создать чек", callback_data="checks:create")],
            [InlineKeyboardButton(text="💸 Активировать чек", callback_data="checks:claim")],
            [InlineKeyboardButton(text="📄 Мои чеки", callback_data="checks:my")],
        ]
    )

def bank_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Открыть депозит", callback_data="bank:open")],
            [InlineKeyboardButton(text="📜 Мои депозиты", callback_data="bank:list")],
            [InlineKeyboardButton(text="💰 Снять зрелые", callback_data="bank:withdraw")],
        ]
    )

def bank_terms_kb() -> InlineKeyboardMarkup:
    rows = []
    for days, rate in BANK_TERMS.items():
        rows.append(
            [InlineKeyboardButton(text=f"{days} дн. (+{int(rate * 100)}%)", callback_data=f"bank:term:{days}")]
        )
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="bank:term:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def roulette_choice_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔴 Красное", callback_data="roulette:choice:red"),
                InlineKeyboardButton(text="⚫ Черное", callback_data="roulette:choice:black"),
            ],
            [
                InlineKeyboardButton(text="2️⃣ Чет", callback_data="roulette:choice:even"),
                InlineKeyboardButton(text="1️⃣ Нечет", callback_data="roulette:choice:odd"),
            ],
            [InlineKeyboardButton(text="0️⃣ Зеро (x36)", callback_data="roulette:choice:zero")],
        ]
    )

def tower_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="1", callback_data="tower:pick:1"),
                InlineKeyboardButton(text="2", callback_data="tower:pick:2"),
                InlineKeyboardButton(text="3", callback_data="tower:pick:3"),
            ],
            [
                InlineKeyboardButton(text="💰 Забрать выигрыш", callback_data="tower:cash"),
                InlineKeyboardButton(text="❌ Сдаться", callback_data="tower:cancel"),
            ],
        ]
    )

def gold_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🧱 1", callback_data="gold:pick:1"),
                InlineKeyboardButton(text="🧱 2", callback_data="gold:pick:2"),
                InlineKeyboardButton(text="🧱 3", callback_data="gold:pick:3"),
                InlineKeyboardButton(text="🧱 4", callback_data="gold:pick:4"),
            ],
            [
                InlineKeyboardButton(text="💰 Забрать выигрыш", callback_data="gold:cash"),
                InlineKeyboardButton(text="❌ Сдаться", callback_data="gold:cancel"),
            ],
        ]
    )

def diamond_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔹 1", callback_data="diamond:pick:1"),
                InlineKeyboardButton(text="🔹 2", callback_data="diamond:pick:2"),
                InlineKeyboardButton(text="🔹 3", callback_data="diamond:pick:3"),
                InlineKeyboardButton(text="🔹 4", callback_data="diamond:pick:4"),
                InlineKeyboardButton(text="🔹 5", callback_data="diamond:pick:5"),
            ],
            [
                InlineKeyboardButton(text="💰 Забрать выигрыш", callback_data="diamond:cash"),
                InlineKeyboardButton(text="❌ Сдаться", callback_data="diamond:cancel"),
            ],
        ]
    )

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
    rows.append(
        [
            InlineKeyboardButton(text="💰 Забрать выигрыш", callback_data="mines:cash"),
            InlineKeyboardButton(text="❌ Сдаться", callback_data="mines:cancel"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)

def ochko_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="➕ Взять", callback_data="ochko:hit"),
                InlineKeyboardButton(text="✋ Стоп", callback_data="ochko:stand"),
            ],
        ]
    )

def ochko_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Начать", callback_data="ochko:start"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="ochko:cancel"),
            ]
        ]
    )

# ==================== ИГРОВЫЕ ХЕЛПЕРЫ ====================

def clear_active_sessions(user_id: int) -> None:
    TOWER_GAMES.pop(user_id, None)
    GOLD_GAMES.pop(user_id, None)
    DIAMOND_GAMES.pop(user_id, None)
    MINES_GAMES.pop(user_id, None)
    OCHKO_GAMES.pop(user_id, None)

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

def crash_roll() -> float:
    u = random.random()
    raw = 0.99 / (1.0 - u)
    return round(max(1.0, min(50.0, raw)), 2)

def football_value_text(value: int) -> str:
    return "Гол" if value >= 3 else "Мимо"

def basketball_value_text(value: int) -> str:
    return "Точный бросок" if value in {4, 5} else "Промах"

def mines_multiplier(opened_count: int, mines_count: int) -> float:
    if opened_count <= 0:
        return 1.0
    safe_cells = 9 - mines_count
    base = 9.0 / max(1.0, safe_cells)
    mult = (base ** opened_count) * 0.95
    return round(mult, 2)

def make_deck() -> list[tuple[str, str]]:
    ranks = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
    suits = ["♠", "♥", "♦", "♣"]
    deck = [(rank, suit) for rank in ranks for suit in suits]
    random.shuffle(deck)
    return deck

def card_points(rank: str) -> int:
    if rank in {"J", "Q", "K"}:
        return 10
    if rank == "A":
        return 11
    return int(rank)

def hand_value(cards: list[tuple[str, str]]) -> int:
    total = sum(card_points(rank) for rank, _ in cards)
    aces = sum(1 for rank, _ in cards if rank == "A")
    while total > 21 and aces > 0:
        total -= 10
        aces -= 1
    return total

def format_hand(cards: list[tuple[str, str]]) -> str:
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
    return (
        "🎴 <b>Очко</b>\n"
        f"Ставка: <b>{fmt_money(game['bet'])}</b>\n\n"
        f"Дилер: {dealer_line}\n"
        f"Ты: {format_hand(player_cards)} ({player_value})"
    )

def _game_lock(user_id: int | str) -> asyncio.Lock:
    key = str(user_id)
    lock = user_game_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        user_game_locks[key] = lock
    return lock

def _new_gid(prefix: str) -> str:
    return prefix + "".join(random.choices(string.ascii_lowercase + string.digits, k=10))# ==================== ФИЛЬТР ПОДПИСКИ ====================

class SubscriptionFilter(BaseFilter):
    async def __call__(self, message: Message, bot: Bot) -> bool:
        subscribed, sub_msg = await check_subscription(bot, message.from_user.id)
        if not subscribed:
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="📢 Подписаться на канал", url="https://t.me/VIRTEXCHANEL")],
                    [InlineKeyboardButton(text="💬 Войти в чат", url="https://t.me/VIRTEXCHATW")],
                    [InlineKeyboardButton(text="✅ Проверить подписку", callback_data="check_sub")],
                ]
            )
            await message.answer(sub_msg, reply_markup=keyboard)
            return False
        return True

async def check_subscription(bot: Bot, user_id: int) -> tuple[bool, str]:
    """Проверяет подписку на канал и чат. Возвращает (подписан, сообщение)."""
    not_subscribed = []
    try:
        chat_member = await bot.get_chat_member(CHANNEL_ID, user_id)
        if chat_member.status in ("left", "kicked", "restricted"):
            not_subscribed.append(f"📢 Канал: {CHANNEL_ID}")
    except Exception:
        not_subscribed.append(f"📢 Канал: {CHANNEL_ID}")
    try:
        chat_member = await bot.get_chat_member(CHAT_ID, user_id)
        if chat_member.status in ("left", "kicked", "restricted"):
            not_subscribed.append(f"💬 Чат: {CHAT_ID}")
    except Exception:
        not_subscribed.append(f"💬 Чат: {CHAT_ID}")
    if not_subscribed:
        lines = ["❌ <b>Для игры нужна подписка:</b>", ""]
        lines.extend(not_subscribed)
        lines.append("")
        lines.append("<i>Подпишись и попробуй снова.</i>")
        return False, "\n".join(lines)
    return True, ""

# ==================== BOT ====================

dp = Dispatcher(storage=MemoryStorage())

def get_bot_token() -> str:
    if not BOT_TOKEN or BOT_TOKEN == "PUT_YOUR_BOT_TOKEN_HERE":
        raise RuntimeError("Заполни BOT_TOKEN")
    return BOT_TOKEN# ==================== COMMON COMMANDS ====================

@dp.message(CommandStart())
async def start_command(message: Message, state: FSMContext):
    ensure_user(message.from_user.id)
    await state.clear()
    clear_active_sessions(message.from_user.id)
    bot = message.bot
    subscribed, sub_msg = await check_subscription(bot, message.from_user.id)
    if not subscribed:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📢 Подписаться на канал", url="https://t.me/VIRTEXCHANEL")],
                [InlineKeyboardButton(text="💬 Войти в чат", url="https://t.me/VIRTEXCHATW")],
                [InlineKeyboardButton(text="✅ Проверить подписку", callback_data="check_sub")],
            ]
        )
        await message.answer(sub_msg, reply_markup=keyboard)
        return
    await message.answer(
        "🎮 <b>Игровой бот VIRTEX</b>\n"
        "<blockquote>Основные команды:\n"
        "• <code>б</code> или <code>баланс</code>\n"
        "• <code>бонус</code>\n"
        "• <code>игры</code>\n"
        "• <code>топ</code>\n"
        "• <code>банк</code>\n"
        "• <code>чеки</code>\n"
        "• <code>промо CODE</code>\n"
        "• <code>помощь</code></blockquote>"
    )

@dp.callback_query(F.data == "check_sub")
async def check_sub_cb(query: CallbackQuery):
    bot = query.bot
    subscribed, sub_msg = await check_subscription(bot, query.from_user.id)
    if not subscribed:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📢 Подписаться на канал", url="https://t.me/VIRTEXCHANEL")],
                [InlineKeyboardButton(text="💬 Войти в чат", url="https://t.me/VIRTEXCHATW")],
                [InlineKeyboardButton(text="✅ Проверить подписку", callback_data="check_sub")],
            ]
        )
        await query.message.edit_text(sub_msg, reply_markup=keyboard)
        await query.answer("Подпишись на канал и чат!", show_alert=True)
        return
    await query.message.edit_text(
        "✅ <b>Подписка подтверждена!</b>\n\n"
        "🎮 <b>Игровой бот VIRTEX</b>\n"
        "<blockquote>Основные команды:\n"
        "• <code>б</code> или <code>баланс</code>\n"
        "• <code>бонус</code>\n"
        "• <code>игры</code>\n"
        "• <code>топ</code>\n"
        "• <code>банк</code>\n"
        "• <code>чеки</code>\n"
        "• <code>промо CODE</code>\n"
        "• <code>помощь</code></blockquote>"
    )
    await query.answer("Добро пожаловать!")

@dp.message(Command("menu"))
async def menu_command(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "📍 <b>Меню</b>\n"
        "<blockquote>💰 б | 🎁 бонус | 🎮 игры\n"
        "🏆 топ | 🧾 чеки | 🏦 банк | 🎟 промо | ❓ помощь</blockquote>"
    )

@dp.message(lambda m: normalize_text(m.text) in {"отмена", "/cancel", "cancel"})
async def cancel_any(message: Message, state: FSMContext):
    await state.clear()
    clear_active_sessions(message.from_user.id)
    await message.answer("🛑 Отменено. Можешь запускать новое действие 💫")

@dp.message(
    StateFilter(None),
    lambda m: normalize_text(m.text) in {"б", "баланс", "/balance", "balance", "b"},
)
async def balance_command(message: Message):
    user = get_user(message.from_user.id)
    vix = float(user["vix"] or 0)
    await message.answer(
        f"{headline_user('💰', message.from_user.id, message.from_user.first_name, 'твой баланс')}\n"
        f"<blockquote>Доступно: <b>{fmt_money(float(user['coins'] or 0), CURRENCY_NAME)}</b>\n"
        f"Донат: <b>{fmt_money(vix, DONAT_CURRENCY_NAME)}</b></blockquote>"
    )

@dp.message(
    StateFilter(None),
    lambda m: normalize_text(m.text) in {"профиль", "/profile", "profile"},
)
async def profile_command(message: Message):
    user_id = message.from_user.id
    stats = get_profile_stats(user_id)
    user = get_user(user_id)

    # Дата регистрации
    reg_ts = int(user["registered_at"] or 0)
    reg_date = fmt_dt(reg_ts) if reg_ts > 0 else "Неизвестно"

    # Место в топе
    top_rows = get_top_balances(1000)
    place = "—"
    for idx, row in enumerate(top_rows, start=1):
        if int(row["id"]) == user_id:
            place = str(idx)
            break

    # Статус
    status_code = int(user["status"] or 0)
    status_map = {0: "👤 Игрок", 1: "✨ VIP", 2: "💎 Премиум", 3: "👑 Админ"}
    status_text = status_map.get(status_code, "👤 Игрок")
    if is_admin_user(user_id):
        status_text = "👑 Админ"

    # Оборот
    total_bet = float(stats.get("total_bet", 0) or 0)

    # Проиграно
    lost_coins = float(user["lost_coins"] or 0)

    # Игры
    total_games = stats["total"]

    vix_balance = float(user["vix"] or 0)

    lines = [
        "🆔 <b>Профиль</b>",
        "·····················",
        f"├ 👤 <b>{escape_html(message.from_user.full_name)}</b>",
        f"├ ⚡️ Статус: <b>{status_text}</b>",
        f"├ 🎮 Сыграно игр: <b>{total_games}</b>",
        f"├ 🏆 Место в топе: <b>#{place}</b>",
        f"├ 🔄 Оборот: <b>{fmt_money(total_bet)}</b>",
        f"├ 📉 Проиграно: <b>{fmt_money(lost_coins)}</b>",
        f"├ 📅 Дата регистрации: <b>{reg_date}</b>",
        "·····················",
        f"💰 Баланс: <b>{fmt_money(stats['coins'], CURRENCY_NAME)}</b>",
        f"💎 Баланс: <b>{fmt_money(vix_balance, DONAT_CURRENCY_NAME)}</b>",
        "·····················",
        f"🆔 ID: <code>{user_id}</code>",
    ]
    await message.answer("\n".join(lines))

@dp.message(
    StateFilter(None),
    lambda m: normalize_text(m.text) in {"бонус", "/bonus", "bonus"},
)
async def bonus_command(message: Message):
    user_id = message.from_user.id
    ensure_user(user_id)
    key = f"bonus_ts:{user_id}"
    last = int(get_json_value(key, 0) or 0)
    now = now_ts()
    if now - last < BONUS_COOLDOWN_SECONDS:
        left = BONUS_COOLDOWN_SECONDS - (now - last)
        await message.answer(
            f"{headline_user('🎁', user_id, message.from_user.first_name, 'ты уже забрал бонус')}\n"
            f"<blockquote><i>Приходи позже.</i>\nОсталось: <b>{fmt_left(left)}</b></blockquote>"
        )
        return
    reward = round(float(random.randint(BONUS_REWARD_MIN, BONUS_REWARD_MAX)), 2)
    ok, balance = settle_instant_bet(
        user_id=user_id, bet=0.0, payout=reward, choice="bonus", outcome="bonus_claim",
    )
    if not ok:
        await message.answer("Не удалось выдать бонус, попробуй позже.")
        return
    set_json_value(key, now)
    await message.answer(
        f"{headline_user('🎁', user_id, message.from_user.first_name, 'ты получил бонус')}\n"
        f"<blockquote>Начислено: <b>{fmt_money(reward)}</b>\n"
        f"Новый баланс: <b>{fmt_money(balance)}</b></blockquote>"
    )

@dp.message(
    StateFilter(None),
    lambda m: normalize_text(m.text) in {"помощь", "/help", "help"},
)
async def help_command(message: Message):
    admin_hint = ""
    if is_admin_user(message.from_user.id):
        admin_hint = (
            "\n\n🛠️ Админ-команды:\n"
            "• <code>/new_promo</code> 🎟\n"
            "• <code>/addpromo CODE REWARD ACTIVATIONS</code> ⚙️\n"
            "• <code>выдать 1000</code> или reply + <code>выдать 1000</code> 💸"
        )
    await message.answer(
        "❓ <b>Помощь</b>\n"
        "<blockquote>Команды:\n"
        "• <code>б</code> или <code>баланс</code>\n"
        "• <code>бонус</code>\n"
        "• <code>игры</code>\n"
        "• <code>топ</code>\n"
        "• <code>помощь</code>\n"
        "• <code>банк</code>\n"
        "• <code>чеки</code>\n"
        "• <code>промо CODE</code></blockquote>\n\n"
        "Игры:\n"
        "<blockquote>🗼 башня, 🥇 золото, 💎 алмазы, 🎡 рулетка, 📈 краш,\n"
        "💣 мины, 🎲 кубик, 🎯 кости, 🎴 очко, ⚽️ футбол, 🏀 баскет</blockquote>\n\n"
        "Отмена действия: <code>отмена</code>" + admin_hint
    )

@dp.message(
    StateFilter(None),
    lambda m: normalize_text(m.text) in {"топ", "/top", "top"},
)
async def top_command(message: Message):
    rows = get_top_balances(10)
    if not rows:
        await message.answer("🏆 <b>Топ игроков</b>\n<blockquote><i>Пока список пуст.</i></blockquote>")
        return
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    lines = ["🏆 <b>Топ игроков по балансу</b>", "<blockquote>"]
    for idx, row in enumerate(rows, start=1):
        icon = medals.get(idx, f"{idx}.")
        lines.append(f"{icon} {mention_user(int(row['id']))} — <b>{fmt_money(float(row['coins'] or 0))}</b>")
    lines.append("</blockquote>")
    await message.answer("\n".join(lines))

@dp.message(
    StateFilter(None),
    lambda m: normalize_text(m.text).startswith("выдать "),
)
async def admin_give_command(message: Message):
    if not is_admin_user(message.from_user.id):
        await message.answer("⛔ Команда только для админов.")
        return
    parts = str(message.text or "").split(maxsplit=1)
    if len(parts) != 2:
        await message.answer("Формат: <code>выдать 1000</code>")
        return
    try:
        amount = parse_amount(parts[1])
    except Exception:
        await message.answer("Введи корректную сумму. Пример: <code>выдать 1000</code>")
        return
    target = (
        message.reply_to_message.from_user
        if message.reply_to_message and message.reply_to_message.from_user
        else message.from_user
    )
    balance = add_balance(target.id, amount)
    who = mention_user(target.id, target.full_name)
    await message.answer(
        f"{headline_user('✅', target.id, target.full_name, 'тебе выдана валюта')}\n"
        f"<blockquote>Кому: {who} (<code>{target.id}</code>)\n"
        f"Сумма: <b>{fmt_money(amount)}</b>\n"
        f"Новый баланс: <b>{fmt_money(balance)}</b></blockquote>"
  )# ==================== CHECKS ====================

@dp.message(
    StateFilter(None),
    lambda m: normalize_text(m.text) in {"чеки", "/check", "check"},
)
async def checks_command(message: Message):
    await message.answer("🧾 <b>Чеки</b>\n<i>Выбери действие ниже.</i>", reply_markup=checks_kb())

@dp.callback_query(F.data == "checks:create")
async def checks_create_cb(query: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(CheckCreateStates.waiting_amount)
    await query.message.answer("Введите сумму на 1 активацию чека:")
    await query.answer()

@dp.message(CheckCreateStates.waiting_amount)
async def checks_create_amount(message: Message, state: FSMContext):
    try:
        amount = parse_amount(message.text)
    except Exception:
        await message.answer("Нужно положительное число. Например: 100")
        return
    if amount < 10:
        await message.answer("Минимум для одной активации: 10")
        return
    await state.update_data(amount=amount)
    await state.set_state(CheckCreateStates.waiting_count)
    await message.answer("Сколько активаций (1-100)?")

@dp.message(CheckCreateStates.waiting_count)
async def checks_create_count(message: Message, state: FSMContext):
    try:
        count = parse_int(message.text)
    except Exception:
        await message.answer("Введи целое число 1-100.")
        return
    if not 1 <= count <= 100:
        await message.answer("Количество должно быть от 1 до 100.")
        return
    data = await state.get_data()
    amount = float(data.get("amount", 0))
    total = round(amount * count, 2)
    ok, result = create_check_atomic(message.from_user.id, amount, count)
    await state.clear()
    if not ok:
        await message.answer(f"❌ {result}")
        return
    await message.answer(
        "✅ <b>Чек создан</b>\n"
        f"<blockquote>Код: <code>{result}</code>\n"
        f"На 1 пользователя: <b>{fmt_money(amount)}</b>\n"
        f"Активаций: <b>{count}</b>\n"
        f"Заморожено: <b>{fmt_money(total)}</b></blockquote>"
    )

@dp.callback_query(F.data == "checks:claim")
async def checks_claim_cb(query: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(CheckClaimStates.waiting_code)
    await query.message.answer("Введи код чека:")
    await query.answer()

@dp.message(CheckClaimStates.waiting_code)
async def checks_claim_code(message: Message, state: FSMContext):
    code = str(message.text or "").strip().upper()
    if len(code) < 4:
        await message.answer("Код слишком короткий.")
        return
    ok, msg, reward = claim_check_atomic(message.from_user.id, code)
    await state.clear()
    if not ok:
        await message.answer(f"❌ {msg}")
        return
    await message.answer(f"✅ <b>Чек активирован</b>\n<blockquote>Начислено: <b>{fmt_money(reward)}</b></blockquote>")

@dp.callback_query(F.data == "checks:my")
async def checks_my_cb(query: CallbackQuery):
    rows = list_my_checks(query.from_user.id)
    if not rows:
        await query.message.answer("У тебя пока нет созданных чеков.")
        await query.answer()
        return
    lines = ["🧾 <b>Последние чеки</b>"]
    for row in rows:
        lines.append(f"<code>{row['code']}</code> | {fmt_money(float(row['per_user']))} | осталось: {int(row['remaining'])}")
    await query.message.answer("\n".join(lines))
    await query.answer()

# ==================== PROMO ====================

@dp.message(Command("addpromo"))
async def addpromo_command(message: Message):
    if not is_admin_user(message.from_user.id):
        await message.answer("⛔ Команда только для админов.")
        return
    parts = str(message.text or "").split()
    if len(parts) != 4:
        await message.answer("🧩 Формат: /addpromo CODE REWARD ACTIVATIONS")
        return
    try:
        code = normalize_promo_code(parts[1])
    except Exception:
        await message.answer("⚠️ Код: 3-24 символа, только A-Z, 0-9, _ или -")
        return
    try:
        reward = parse_amount(parts[2])
        activations = int(parts[3])
    except Exception:
        await message.answer("⚠️ Неверные данные. Пример: /addpromo START200 200 100")
        return
    if activations <= 0:
        await message.answer("⚠️ ACTIVATIONS должно быть больше 0.")
        return
    create_promo(code, reward, activations)
    await message.answer(
        "✅🎟 <b>Промокод сохранен</b>\n"
        f"🔤 Код: <code>{code}</code>\n"
        f"💎 Награда: <b>{fmt_money(reward)}</b>\n"
        f"♾️ Активаций: <b>{activations}</b>"
    )

@dp.message(Command("new_promo"))
async def new_promo_start(message: Message, state: FSMContext):
    if not is_admin_user(message.from_user.id):
        await message.answer("⛔ Команда только для админов.")
        return
    await state.clear()
    await state.set_state(NewPromoStates.waiting_code)
    await message.answer(
        "🛠️🎟 <b>Создание промо</b>\n"
        "Шаг 1/3: введи код промо\n"
        "Формат: A-Z, 0-9, _ или - (3..24)"
    )

@dp.message(
    StateFilter(NewPromoStates.waiting_code, NewPromoStates.waiting_reward, NewPromoStates.waiting_activations),
    lambda m: normalize_text(m.text) in {"отмена", "/cancel", "cancel"},
)
async def new_promo_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("🛑 Создание промо отменено.")

@dp.message(NewPromoStates.waiting_code)
async def new_promo_code_input(message: Message, state: FSMContext):
    try:
        code = normalize_promo_code(message.text or "")
    except Exception:
        await message.answer("⚠️ Некорректный код. Попробуй еще раз.")
        return
    await state.update_data(code=code)
    await state.set_state(NewPromoStates.waiting_reward)
    await message.answer("💰 Шаг 2/3: введи награду (число, например 250)")

@dp.message(NewPromoStates.waiting_reward)
async def new_promo_reward_input(message: Message, state: FSMContext):
    try:
        reward = parse_amount(message.text or "")
    except Exception:
        await message.answer("⚠️ Нужно положительное число. Например: 250")
        return
    await state.update_data(reward=reward)
    await state.set_state(NewPromoStates.waiting_activations)
    await message.answer("🔢 Шаг 3/3: введи количество активаций (целое число)")

@dp.message(NewPromoStates.waiting_activations)
async def new_promo_activations_input(message: Message, state: FSMContext):
    try:
        activations = parse_int(message.text or "")
    except Exception:
        await message.answer("⚠️ Введи целое число активаций.")
        return
    if activations <= 0:
        await message.answer("⚠️ Количество активаций должно быть > 0.")
        return
    data = await state.get_data()
    code = str(data.get("code", "")).strip()
    reward = float(data.get("reward", 0) or 0)
    if not code or reward <= 0:
        await state.clear()
        await message.answer("❌ Данные сессии потеряны. Запусти /new_promo еще раз.")
        return
    create_promo(code, reward, activations)
    await state.clear()
    await message.answer(
        "✅🎉 <b>Промо создано</b>\n"
        f"🔤 Код: <code>{code}</code>\n"
        f"💰 Награда: <b>{fmt_money(reward)}</b>\n"
        f"🎯 Активаций: <b>{activations}</b>\n"
        "🚀 Готово к использованию!"
    )

async def redeem_promo_flow(message: Message, code: str) -> None:
    ok, msg, reward = redeem_promo_atomic(message.from_user.id, code)
    if not ok:
        await message.answer(f"❌ {msg}")
        return
    await message.answer(f"✅🎊 <b>Промо активирован</b>\n💰 Награда: <b>{fmt_money(reward)}</b>")

@dp.message(
    StateFilter(None),
    lambda m: (normalize_text(m.text).startswith("промо") or normalize_text(m.text).startswith("/promo")),
)
async def promo_command(message: Message, state: FSMContext):
    text = str(message.text or "").strip()
    parts = text.split(maxsplit=1)
    if len(parts) == 2 and parts[1].strip():
        await redeem_promo_flow(message, parts[1].strip())
        return
    await state.clear()
    await state.set_state(PromoStates.waiting_code)
    await message.answer("🎟✨ Введи код промо:")

@dp.message(PromoStates.waiting_code)
async def promo_code_input(message: Message, state: FSMContext):
    code = str(message.text or "").strip()
    if not code:
        await message.answer("⚠️ Введи непустой код.")
        return
    await redeem_promo_flow(message, code)
    await state.clear()

# ==================== BANK ====================

def render_bank_panel_text(user_id: int) -> str:
    summary = get_bank_summary(user_id)
    return (
        "🏦 <b>Банк: депозиты</b>\n"
        f"<blockquote>Баланс: <b>{fmt_money(summary['coins'])}</b>\n"
        f"Активных депозитов: <b>{summary['count_active']}</b>\n"
        f"Сумма в работе: <b>{fmt_money(summary['active_sum'])}</b></blockquote>\n\n"
        "<i>Ставки:</i>\n"
        "• 7 дней: +3%\n"
        "• 14 дней: +7%\n"
        "• 30 дней: +18%"
    )

@dp.message(StateFilter(None), lambda m: normalize_text(m.text) in {"банк", "/bank", "bank"})
async def bank_command(message: Message):
    await message.answer(render_bank_panel_text(message.from_user.id), reply_markup=bank_kb())

@dp.callback_query(F.data == "bank:open")
async def bank_open_cb(query: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(BankStates.waiting_amount)
    await query.message.answer("Введи сумму депозита:")
    await query.answer()

@dp.message(BankStates.waiting_amount)
async def bank_open_amount(message: Message, state: FSMContext):
    try:
        amount = parse_amount(message.text)
    except Exception:
        await message.answer("Нужно положительное число.")
        return
    if amount < 100:
        await message.answer("Минимальный депозит: 100")
        return
    await state.update_data(amount=amount)
    await message.answer("Выбери срок депозита:", reply_markup=bank_terms_kb())

@dp.callback_query(F.data.startswith("bank:term:"))
async def bank_term_cb(query: CallbackQuery, state: FSMContext):
    raw = query.data.split(":")[-1]
    if raw == "cancel":
        await state.clear()
        await query.message.answer("Открытие депозита отменено.")
        await query.answer()
        return
    data = await state.get_data()
    amount = float(data.get("amount", 0) or 0)
    if amount <= 0:
        await query.message.answer("Сначала укажи сумму депозита.")
        await query.answer()
        return
    try:
        term_days = int(raw)
    except Exception:
        await query.answer("Ошибка срока", show_alert=True)
        return
    ok, msg = add_deposit(query.from_user.id, amount, term_days)
    await state.clear()
    if not ok:
        await query.message.answer(f"❌ {msg}")
    else:
        rate = BANK_TERMS[term_days]
        await query.message.answer(
            "✅ <b>Депозит открыт</b>\n"
            f"<blockquote>Сумма: <b>{fmt_money(amount)}</b>\n"
            f"Срок: <b>{term_days} дн.</b>\n"
            f"Доходность: <b>+{int(rate * 100)}%</b></blockquote>"
        )
        await query.message.answer(render_bank_panel_text(query.from_user.id), reply_markup=bank_kb())
    await query.answer()

@dp.callback_query(F.data == "bank:list")
async def bank_list_cb(query: CallbackQuery):
    rows = list_user_deposits(query.from_user.id)
    if not rows:
        await query.message.answer("У тебя пока нет депозитов.")
        await query.answer()
        return
    now = now_ts()
    lines = ["📜 <b>Последние депозиты</b>"]
    for row in rows[:10]:
        opened_at = int(row["opened_at"] or 0)
        term_days = int(row["term_days"] or 0)
        unlock_ts = opened_at + term_days * 86400
        left = unlock_ts - now
        status = str(row["status"])
        if status == "active":
            status_text = "⏳ активен" if left > 0 else "✅ можно снять"
        else:
            status_text = f"✅ закрыт {fmt_dt(int(row['closed_at'] or opened_at))}"
        lines.append(
            f"#{int(row['id'])} | {fmt_money(float(row['principal']))} | {term_days}д | +{int(float(row['rate']) * 100)}% | {status_text}"
        )
    await query.message.answer("\n".join(lines))
    await query.answer()

@dp.callback_query(F.data == "bank:withdraw")
async def bank_withdraw_cb(query: CallbackQuery):
    closed, payout = withdraw_matured_deposits(query.from_user.id)
    if closed == 0:
        await query.message.answer("Пока нет зрелых депозитов для вывода.")
    else:
        await query.message.answer(
            "✅ <b>Вывод депозитов</b>\n"
            f"Закрыто: <b>{closed}</b>\n"
            f"Начислено: <b>{fmt_money(payout)}</b>"
        )
        await query.message.answer(render_bank_panel_text(query.from_user.id), reply_markup=bank_kb())
    await query.answer()# ==================== GAMES MENU ====================

@dp.message(
    StateFilter(None),
    lambda m: normalize_text(m.text) in {"игры", "/games", "games"},
)
async def games_command(message: Message):
    await message.answer(
        "🎮 <b>Игры</b>\nВыбери игру кнопкой ниже.\n"
        "Дальше вводи ставку прямо командой, например: <code>башня 300 2</code>.",
        reply_markup=games_kb(),
    )

@dp.callback_query(F.data.startswith("games:pick:"))
async def games_pick_cb(query: CallbackQuery, state: FSMContext):
    await state.clear()
    game = query.data.split(":")[-1]
    usage_map = {
        "tower": "башня 300 2",
        "gold": "золото 300",
        "diamonds": "алмазы 300 2",
        "roulette": "рул 300 чет",
        "crash": "краш 300 2.5",
        "mines": "мины 300 3",
        "cube": "кубик 300 5",
        "dice": "кости 300 м",
        "ochko": "очко 300",
        "football": "футбол 300 гол",
        "basket": "баскет 300",
    }
    example = usage_map.get(game)
    if example:
        await query.message.answer(
            f"<i>Введи команду в чат:</i>\n<blockquote><code>{example}</code></blockquote>",
            parse_mode="HTML",
        )
    await query.answer()

@dp.message(
    StateFilter(None),
    lambda m: (
        normalize_text(m.text)
        in {
            "башня", "золото", "алмазы", "рулетка", "краш", "мины",
            "кубик", "кости", "очко", "футбол", "баскет",
        }
    ),
)
async def direct_game_text(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "<b>Для игр используй команды в таком формате:</b>\n"
        "<blockquote>"
        "<code>башня 300 2</code>\n"
        "<code>золото 300</code>\n"
        "<code>алмазы 300 2</code>\n"
        "<code>мины 300 3</code>\n"
        "<code>рул 300 чет</code>\n"
        "<code>краш 300 2.5</code>\n"
        "<code>кубик 300 5</code>\n"
        "<code>кости 300 м</code>\n"
        "<code>очко 300</code>\n"
        "<code>футбол 300 гол</code>\n"
        "<code>баскет 300</code></blockquote>",
        parse_mode="HTML",
    )

# ==================== ROULETTE ====================

@dp.message(StateFilter(None), lambda m: (m.text or "").lower().startswith("рул"))
async def roulette_start(message: Message, state: FSMContext):
    parts = (message.text or "").strip().lower().split()
    if len(parts) < 3:
        await state.clear()
        await state.set_state(RouletteStates.waiting_amount)
        await message.answer("🎡 <b>Рулетка</b>\nВведи сумму ставки:")
        return

    user_id = message.from_user.id
    balance = float(get_user(user_id)["coins"] or 0)
    try:
        bet = parse_bet_legacy(parts[1], balance)
    except Exception:
        await state.clear()
        await state.set_state(RouletteStates.waiting_amount)
        await message.answer("Неверная ставка. Введи сумму:")
        return

    if bet < MIN_BET:
        await message.answer(f"Минимальная ставка: {fmt_money(MIN_BET)}")
        return

    choice_raw = parts[2]
    mapping = {
        "красное": "red", "кра": "red", "red": "red",
        "черное": "black", "чёрное": "black", "чер": "black", "black": "black",
        "чет": "even", "четное": "even", "чёт": "even", "чётное": "even", "even": "even",
        "нечет": "odd", "нечетное": "odd", "нечёт": "odd", "нечётное": "odd", "odd": "odd",
        "зеро": "zero", "zero": "zero", "зел": "zero", "0": "zero",
    }
    choice = mapping.get(choice_raw)
    if not choice:
        await state.update_data(bet=float(bet))
        await state.set_state(RouletteStates.waiting_choice)
        await message.answer("Выбери сектор:", reply_markup=roulette_choice_kb())
        return

    # Быстрый запуск
    win, multiplier, outcome = roulette_roll(choice)
    payout = round(bet * multiplier, 2) if win else 0.0
    ok, new_balance = settle_instant_bet(
        user_id=user_id, bet=float(bet), payout=payout, choice=f"roulette:{choice}", outcome=outcome,
    )
    if not ok:
        await message.answer("Недостаточно средств на балансе.")
        return
    await message.answer(
        f"{headline_user('🎡', user_id, message.from_user.first_name, 'рулетка сыграна')}\n"
        f"<blockquote>{outcome}\n"
        f"Ставка: <b>{fmt_money(bet)}</b>\n"
        f"Результат: <b>{'Победа' if win else 'Поражение'}</b>\n"
        f"Выплата: <b>{fmt_money(payout)}</b>\n"
        f"Баланс: <b>{fmt_money(new_balance)}</b></blockquote>"
    )

@dp.message(RouletteStates.waiting_amount)
async def roulette_amount(message: Message, state: FSMContext):
    try:
        bet = parse_amount(message.text)
    except Exception:
        await message.answer("Введи корректную сумму ставки.")
        return
    if bet < MIN_BET:
        await message.answer(f"Минимальная ставка: {fmt_money(MIN_BET)}")
        return
    await state.update_data(bet=bet)
    await state.set_state(RouletteStates.waiting_choice)
    await message.answer(
        "Выбери сектор или введи текстом: красное / черное / чет / нечет / зеро",
        reply_markup=roulette_choice_kb(),
    )

async def finish_roulette(message: Message, state: FSMContext, choice: str) -> None:
    data = await state.get_data()
    bet = float(data.get("bet", 0) or 0)
    if bet <= 0:
        await message.answer("Ставка не найдена. Начни заново.")
        await state.clear()
        return
    win, multiplier, outcome = roulette_roll(choice)
    payout = round(bet * multiplier, 2) if win else 0.0
    ok, balance = settle_instant_bet(
        user_id=message.from_user.id, bet=bet, payout=payout, choice=f"roulette:{choice}", outcome=outcome,
    )
    await state.clear()
    if not ok:
        await message.answer("Недостаточно средств на балансе.")
        return
    await message.answer(
        f"{headline_user('🎡', message.from_user.id, message.from_user.first_name, 'рулетка сыграна')}\n"
        f"<blockquote>{outcome}\n"
        f"Ставка: <b>{fmt_money(bet)}</b>\n"
        f"Результат: <b>{'Победа' if win else 'Поражение'}</b>\n"
        f"Выплата: <b>{fmt_money(payout)}</b>\n"
        f"Баланс: <b>{fmt_money(balance)}</b></blockquote>"
    )

@dp.message(RouletteStates.waiting_choice)
async def roulette_choice_text(message: Message, state: FSMContext):
    raw = normalize_text(message.text)
    mapping = {
        "красное": "red", "red": "red",
        "черное": "black", "чёрное": "black", "black": "black",
        "чет": "even", "четное": "even", "чёт": "even", "чётное": "even", "even": "even",
        "нечет": "odd", "нечетное": "odd", "нечёт": "odd", "нечётное": "odd", "odd": "odd",
        "зеро": "zero", "zero": "zero", "0": "zero",
    }
    choice = mapping.get(raw)
    if not choice:
        await message.answer("Неверный выбор. Введи: красное/черное/чет/нечет/зеро")
        return
    await finish_roulette(message, state, choice)

@dp.callback_query(RouletteStates.waiting_choice, F.data.startswith("roulette:choice:"))
async def roulette_choice_cb(query: CallbackQuery, state: FSMContext):
    choice = query.data.split(":")[-1]
    fake_message = query.message
    await finish_roulette(fake_message, state, choice)
    await query.answer()

# ==================== CRASH ====================

@dp.message(StateFilter(None), lambda m: (m.text or "").lower().startswith("краш"))
async def crash_start(message: Message, state: FSMContext):
    parts = (message.text or "").strip().split()
    if len(parts) < 3:
        await state.clear()
        await state.set_state(CrashStates.waiting_amount)
        await message.answer("📈 <b>Краш</b>\nВведи сумму ставки:")
        return

    user_id = message.from_user.id
    balance = float(get_user(user_id)["coins"] or 0)
    try:
        bet = parse_bet_legacy(parts[1], balance)
        target = float(parts[2].replace(",", "."))
    except Exception:
        await state.clear()
        await state.set_state(CrashStates.waiting_amount)
        await message.answer("Неверный формат. Введи сумму ставки:")
        return

    if bet < MIN_BET:
        await message.answer(f"Минимальная ставка: {fmt_money(MIN_BET)}")
        return
    if target < 1.01 or target > 10:
        await message.answer("Множитель должен быть от 1.01 до 10.")
        return

    r = random.random()
    if r < 0.06:
        crash_multiplier = 1.00
    elif r < 0.55:
        crash_multiplier = round(random.uniform(1.01, 1.80), 2)
    elif r < 0.80:
        crash_multiplier = round(random.uniform(1.81, 2.80), 2)
    elif r < 0.93:
        crash_multiplier = round(random.uniform(2.81, 4.50), 2)
    elif r < 0.985:
        crash_multiplier = round(random.uniform(4.51, 9.50), 2)
    else:
        crash_multiplier = round(random.uniform(9.51, 10.0), 2)

    win = crash_multiplier >= target
    payout = round(bet * target, 2) if win else 0.0
    ok, new_balance = settle_instant_bet(
        user_id=user_id, bet=float(bet), payout=payout, choice=f"crash:{target}", outcome=f"crash={crash_multiplier}",
    )
    if not ok:
        await message.answer("Недостаточно средств.")
        return
    await message.answer(
        f"📈 <b>Краш</b>: <b>{crash_multiplier}x</b>\n"
        f"Твоя цель: <b>{target}x</b>\n"
        f"Результат: <b>{'Победа' if win else 'Поражение'}</b>\n"
        f"Выплата: <b>{fmt_money(payout)}</b>\n"
        f"Баланс: <b>{fmt_money(new_balance)}</b>"
    )

@dp.message(CrashStates.waiting_amount)
async def crash_amount(message: Message, state: FSMContext):
    try:
        bet = parse_amount(message.text)
    except Exception:
        await message.answer("Введи корректную ставку.")
        return
    if bet < MIN_BET:
        await message.answer(f"Минимальная ставка: {fmt_money(MIN_BET)}")
        return
    await state.update_data(bet=bet)
    await state.set_state(CrashStates.waiting_target)
    await message.answer("Введи множитель выигрыша (например 1.8). Диапазон: 1.1 - 10.0")

@dp.message(CrashStates.waiting_target)
async def crash_target(message: Message, state: FSMContext):
    data = await state.get_data()
    bet = float(data.get("bet", 0) or 0)
    try:
        target = parse_amount(message.text)
    except Exception:
        await message.answer("Введи число, например 1.8")
        return
    if target < 1.1 or target > 10.0:
        await message.answer("Множитель должен быть от 1.1 до 10.0")
        return
    rolled = crash_roll()
    win = target <= rolled
    payout = round(bet * target, 2) if win else 0.0
    ok, balance = settle_instant_bet(
        message.from_user.id, bet, payout, choice=f"crash:{target}", outcome=f"crash={rolled}",
    )
    await state.clear()
    if not ok:
        await message.answer("Недостаточно средств.")
        return
    await message.answer(
        f"{headline_user('📈', message.from_user.id, message.from_user.first_name, 'краш сыгран')}\n"
        f"<blockquote>Твой множитель: <b>x{target:.2f}</b>\n"
        f"Множитель игры: <b>x{rolled:.2f}</b>\n"
        f"Результат: <b>{'Победа' if win else 'Поражение'}</b>\n"
        f"Выплата: <b>{fmt_money(payout)}</b>\n"
        f"Баланс: <b>{fmt_money(balance)}</b></blockquote>"
    )

# ==================== CUBE ====================

@dp.message(StateFilter(None), lambda m: (m.text or "").lower().startswith("кубик"))
async def cube_start(message: Message, state: FSMContext):
    parts = (message.text or "").strip().lower().split()
    if len(parts) < 3:
        await state.clear()
        await state.set_state(CubeStates.waiting_amount)
        await message.answer("🎲 <b>Кубик</b>\nВведи сумму ставки:")
        return

    user_id = message.from_user.id
    balance = float(get_user(user_id)["coins"] or 0)
    try:
        bet = parse_bet_legacy(parts[1], balance)
    except Exception:
        await state.clear()
        await state.set_state(CubeStates.waiting_amount)
        await message.answer("Неверная ставка. Введи сумму:")
        return

    if bet < MIN_BET:
        await message.answer(f"Минимальная ставка: {fmt_money(MIN_BET)}")
        return

    bet_type = parts[2]
    valid_types = {"1", "2", "3", "4", "5", "6", "чет", "нечет", "б", "м"}
    if bet_type not in valid_types:
        await state.update_data(bet=float(bet))
        await state.set_state(CubeStates.waiting_guess)
        await message.answer("Угадай число от 1 до 6 (или чет/нечет/б/м):")
        return

    dice_msg = await message.answer_dice(emoji="🎲")
    number = int(dice_msg.dice.value)
    win = False
    mult = 0.0
    if bet_type == str(number):
        win, mult = True, 3.5
    elif bet_type == "чет" and number % 2 == 0:
        win, mult = True, 1.9
    elif bet_type == "нечет" and number % 2 == 1:
        win, mult = True, 1.9
    elif bet_type == "б" and number >= 4:
        win, mult = True, 1.9
    elif bet_type == "м" and number <= 3:
        win, mult = True, 1.9

    payout = round(bet * mult, 2) if win else 0.0
    ok, new_balance = settle_instant_bet(
        user_id=user_id, bet=float(bet), payout=payout, choice=f"cube:{bet_type}", outcome=f"num={number}",
    )
    if not ok:
        await message.answer("Недостаточно средств.")
        return

    more_less = "меньше" if number <= 3 else "больше"
    parity = "чет" if number % 2 == 0 else "нечет"
    await message.answer(
        f"🎲 <b>Кубик</b>\n"
        f"Выпало число: <b>{number}</b> ({more_less}, {parity})\n"
        f"Результат: <b>{'Победа' if win else 'Поражение'}</b>\n"
        f"Выплата: <b>{fmt_money(payout)}</b>\n"
        f"Баланс: <b>{fmt_money(new_balance)}</b>"
    )

@dp.message(CubeStates.waiting_amount)
async def cube_amount(message: Message, state: FSMContext):
    try:
        bet = parse_amount(message.text)
    except Exception:
        await message.answer("Введи корректную ставку.")
        return
    if bet < MIN_BET:
        await message.answer(f"Минимальная ставка: {fmt_money(MIN_BET)}")
        return
    await state.update_data(bet=bet)
    await state.set_state(CubeStates.waiting_guess)
    await message.answer("Угадай число от 1 до 6 (или чет/нечет/б/м):")

@dp.message(CubeStates.waiting_guess)
async def cube_guess(message: Message, state: FSMContext):
    data = await state.get_data()
    bet = float(data.get("bet", 0) or 0)
    guess_raw = normalize_text(message.text)
    
    # Пробуем число
    try:
        guess = int(guess_raw)
        if 1 <= guess <= 6:
            dice_msg = await message.answer_dice(emoji="🎲")
            rolled = int(dice_msg.dice.value)
            win = guess == rolled
            payout = round(bet * 5.8, 2) if win else 0.0
            ok, balance = settle_instant_bet(
                message.from_user.id, bet, payout, choice=f"cube:{guess}", outcome=f"rolled={rolled}",
            )
            await state.clear()
            if not ok:
                await message.answer("Недостаточно средств.")
                return
            await message.answer(
                f"{headline_user('🎲', message.from_user.id, message.from_user.first_name, 'кубик брошен')}\n"
                f"<blockquote>Твой выбор: <b>{guess}</b>\n"
                f"Выпало: <b>{rolled}</b>\n"
                f"Результат: <b>{'Победа' if win else 'Поражение'}</b>\n"
                f"Выплата: <b>{fmt_money(payout)}</b>\n"
                f"Баланс: <b>{fmt_money(balance)}</b></blockquote>"
            )
            return
    except Exception:
        pass

    # Пробуем текст
    bet_type = guess_raw
    valid_types = {"чет", "нечет", "б", "м", "even", "odd", "больше", "меньше"}
    mapping = {"even": "чет", "odd": "нечет", "больше": "б", "меньше": "м"}
    bet_type = mapping.get(bet_type, bet_type)
    if bet_type not in {"чет", "нечет", "б", "м"}:
        await message.answer("Введи число 1-6, чет/нечет или б/м")
        return

    dice_msg = await message.answer_dice(emoji="🎲")
    rolled = int(dice_msg.dice.value)
    win = False
    mult = 0.0
    if bet_type == "чет" and rolled % 2 == 0:
        win, mult = True, 1.9
    elif bet_type == "нечет" and rolled % 2 == 1:
        win, mult = True, 1.9
    elif bet_type == "б" and rolled >= 4:
        win, mult = True, 1.9
    elif bet_type == "м" and rolled <= 3:
        win, mult = True, 1.9

    payout = round(bet * mult, 2) if win else 0.0
    ok, balance = settle_instant_bet(
        message.from_user.id, bet, payout, choice=f"cube:{bet_type}", outcome=f"rolled={rolled}",
    )
    await state.clear()
    if not ok:
        await message.answer("Недостаточно средств.")
        return
    await message.answer(
        f"{headline_user('🎲', message.from_user.id, message.from_user.first_name, 'кубик брошен')}\n"
        f"<blockquote>Твой выбор: <b>{bet_type}</b>\n"
        f"Выпало: <b>{rolled}</b>\n"
        f"Результат: <b>{'Победа' if win else 'Поражение'}</b>\n"
        f"Выплата: <b>{fmt_money(payout)}</b>\n"
        f"Баланс: <b>{fmt_money(balance)}</b></blockquote>"
    )

# ==================== DICE ====================

@dp.message(StateFilter(None), lambda m: (m.text or "").lower().startswith("кости"))
async def dice_start(message: Message, state: FSMContext):
    parts = (message.text or "").strip().lower().split()
    if len(parts) < 3:
        await state.clear()
        await state.set_state(DiceStates.waiting_amount)
        await message.answer("🎯 <b>Кости</b>\nВведи сумму ставки:")
        return

    user_id = message.from_user.id
    balance = float(get_user(user_id)["coins"] or 0)
    try:
        bet = parse_bet_legacy(parts[1], balance)
    except Exception:
        await state.clear()
        await state.set_state(DiceStates.waiting_amount)
        await message.answer("Неверная ставка. Введи сумму:")
        return

    if bet < MIN_BET:
        await message.answer(f"Минимальная ставка: {fmt_money(MIN_BET)}")
        return

    choice = parts[2]
    mapping = {"м": "меньше", "б": "больше", "7": "семь", "семь": "семь", "равно": "семь"}
    choice = mapping.get(choice, choice)
    if choice not in {"больше", "меньше", "семь"}:
        await state.update_data(bet=float(bet))
        await state.set_state(DiceStates.waiting_guess)
        await message.answer("Выбери исход: больше / меньше / семь")
        return

    d1_msg = await message.answer_dice(emoji="🎲")
    d2_msg = await message.answer_dice(emoji="🎲")
    d1 = int(d1_msg.dice.value)
    d2 = int(d2_msg.dice.value)
    total = d1 + d2

    win = False
    mult = 0.0
    if choice == "больше" and total > 7:
        win, mult = True, 2.25
    elif choice == "меньше" and total < 7:
        win, mult = True, 2.25
    elif choice == "семь" and total == 7:
        win, mult = True, 5.0

    payout = round(bet * mult, 2) if win else 0.0
    ok, new_balance = settle_instant_bet(
        user_id=user_id, bet=float(bet), payout=payout, choice=f"dice:{choice}", outcome=f"{d1}+{d2}={total}",
    )
    if not ok:
        await message.answer("Недостаточно средств.")
        return

    relation = "меньше 7" if total < 7 else ("больше 7" if total > 7 else "равно 7")
    await message.answer(
        f"🎯 <b>Кости</b>\n"
        f"Выпало: <b>{d1}</b> + <b>{d2}</b> = <b>{total}</b> ({relation})\n"
        f"Результат: <b>{'Победа' if win else 'Поражение'}</b>\n"
        f"Выплата: <b>{fmt_money(payout)}</b>\n"
        f"Баланс: <b>{fmt_money(new_balance)}</b>"
    )

@dp.message(DiceStates.waiting_amount)
async def dice_amount(message: Message, state: FSMContext):
    try:
        bet = parse_amount(message.text)
    except Exception:
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
    mapping = {"м": "меньше", "б": "больше", "7": "семь", "семь": "семь", "равно": "семь"}
    guess = mapping.get(guess, guess)
    if guess not in {"больше", "меньше", "семь"}:
        await message.answer("Напиши: больше, меньше или семь")
        return

    d1_msg = await message.answer_dice(emoji="🎲")
    d2_msg = await message.answer_dice(emoji="🎲")
    d1 = int(d1_msg.dice.value)
    d2 = int(d2_msg.dice.value)
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
    ok, balance = settle_instant_bet(
        message.from_user.id, bet, payout, choice=f"dice:{guess}", outcome=f"{d1}+{d2}={total}",
    )
    await state.clear()
    if not ok:
        await message.answer("Недостаточно средств.")
        return
    await message.answer(
        f"{headline_user('🎯', message.from_user.id, message.from_user.first_name, 'кости брошены')}\n"
        f"<blockquote>Кубики: <b>{d1}</b> и <b>{d2}</b> (сумма {total})\n"
        f"Твой выбор: <b>{guess}</b>\n"
        f"Результат: <b>{'Победа' if win else 'Поражение'}</b>\n"
        f"Выплата: <b>{fmt_money(payout)}</b>\n"
        f"Баланс: <b>{fmt_money(balance)}</b></blockquote>"
    )

# ==================== FOOTBALL ====================

@dp.message(StateFilter(None), lambda m: (m.text or "").lower().startswith("футбол"))
async def football_start(message: Message, state: FSMContext):
    parts = (message.text or "").strip().lower().split()
    if len(parts) < 2:
        await state.clear()
        await state.set_state(FootballStates.waiting_amount)
        await message.answer("⚽ <b>Футбол</b>\nВведи сумму ставки:")
        return

    user_id = message.from_user.id
    balance = float(get_user(user_id)["coins"] or 0)
    try:
        bet = parse_bet_legacy(parts[1], balance)
    except Exception:
        await state.clear()
        await state.set_state(FootballStates.waiting_amount)
        await message.answer("Неверная ставка. Введи сумму:")
        return

    if bet < MIN_BET:
        await message.answer(f"Минимальная ставка: {fmt_money(MIN_BET)}")
        return

    choice = None
    if len(parts) >= 3:
        c = parts[2]
        if c in {"гол", "gol", "goal"}:
            choice = "gol"
        elif c in {"мимо", "mimo", "miss"}:
            choice = "mimo"

    if choice:
        dice_msg = await message.answer_dice(emoji="⚽")
        await asyncio.sleep(3)
        outcome = "mimo" if int(dice_msg.dice.value) <= 2 else "gol"
        value = int(dice_msg.dice.value)
        win = outcome == choice
        payout = round(bet * FOOTBALL_MULTIPLIERS[choice], 2) if win else 0.0
        ok, new_balance = settle_instant_bet(
            user_id=user_id, bet=float(bet), payout=payout, choice=f"football:{choice}", outcome=f"result={outcome}",
        )
        if not ok:
            await message.answer("Недостаточно средств.")
            return
        await message.answer(
            f"Итог: <b>{'Гол' if outcome == 'gol' else 'Мимо'}</b>\n"
            f"Твой выбор: <b>{'Гол' if choice == 'gol' else 'Мимо'}</b>\n"
            f"Результат: <b>{'Победа' if win else 'Поражение'}</b>\n"
            f"Выплата: <b>{fmt_money(payout)}</b>\n"
            f"Баланс: <b>{fmt_money(new_balance)}</b>"
        )
        return

    ok, _ = reserve_bet(user_id, float(bet))
    if not ok:
        await message.answer("Недостаточно средств.")
        return
    NFOOTBALL_GAMES[user_id] = {"bet": int(bet), "started_at": now_ts()}

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"Гол x{FOOTBALL_MULTIPLIERS['gol']}", callback_data="nfoot:play:gol")],
            [InlineKeyboardButton(text=f"Мимо x{FOOTBALL_MULTIPLIERS['mimo']}", callback_data="nfoot:play:mimo")],
            [InlineKeyboardButton(text="Отмена", callback_data="nfoot:cancel")],
        ]
    )
    await message.answer(
        f"Футбол: выбери результат\nСтавка: <b>{fmt_money(bet)}</b>",
        reply_markup=kb,
    )

@dp.message(FootballStates.waiting_amount)
async def football_amount(message: Message, state: FSMContext):
    try:
        bet = parse_amount(message.text)
    except Exception:
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
    dice_msg = await message.answer_dice(emoji="⚽")
    value = int(dice_msg.dice.value)
    win = value >= 4
    result_title = football_value_text(value)
    payout = round(bet * 1.85, 2) if win else 0.0
    balance = finalize_reserved_bet(
        message.from_user.id, bet, payout, choice="football", outcome=f"value={value}",
    )
    await message.answer(
        f"{headline_user('⚽', message.from_user.id, message.from_user.first_name, 'матч сыгран')}\n"
        f"<blockquote>Итог удара: <b>{result_title}</b>\n"
        f"Результат: <b>{'Победа' if win else 'Поражение'}</b>\n"
        f"Выплата: <b>{fmt_money(payout)}</b>\n"
        f"Баланс: <b>{fmt_money(balance)}</b></blockquote>"
    )

@dp.callback_query(F.data == "nfoot:cancel")
async def football_cancel(query: CallbackQuery):
    user_id = query.from_user.id
    session = NFOOTBALL_GAMES.pop(user_id, None)
    if not session:
        return await query.answer("Активной игры нет", show_alert=True)
    bet = int(session["bet"])
    balance = add_balance(user_id, bet)
    await query.message.edit_text(
        f"Игра отменена. Возвращено: <b>{fmt_money(bet)}</b>\nБаланс: <b>{fmt_money(balance)}</b>"
    )
    await query.answer()

@dp.callback_query(F.data.startswith("nfoot:play:"))
async def football_play(query: CallbackQuery):
    user_id = query.from_user.id
    session = NFOOTBALL_GAMES.get(user_id)
    if not session:
        return await query.answer("Активной игры нет", show_alert=True)
    choice = query.data.split(":")[-1]
    if choice not in {"gol", "mimo"}:
        return await query.answer("Ошибка выбора", show_alert=True)
    bet = int(session["bet"])
    try:
        await query.message.edit_reply_markup(None)
    except Exception:
        pass
    dice_msg = await query.message.answer_dice(emoji="⚽")
    await asyncio.sleep(3)
    outcome = "mimo" if int(dice_msg.dice.value) <= 2 else "gol"
    value = int(dice_msg.dice.value)
    win = outcome == choice
    payout = round(bet * FOOTBALL_MULTIPLIERS[choice], 2) if win else 0.0
    new_balance = finalize_reserved_bet(
        user_id=user_id, bet=float(bet), payout=payout, choice=f"football:{choice}", outcome=f"result={outcome}",
    )
    NFOOTBALL_GAMES.pop(user_id, None)
    await query.message.answer(
        f"Итог: <b>{'Гол' if outcome == 'gol' else 'Мимо'}</b>\n"
        f"Твой выбор: <b>{'Гол' if choice == 'gol' else 'Мимо'}</b>\n"
        f"Результат: <b>{'Победа' if win else 'Поражение'}</b>\n"
        f"Выплата: <b>{fmt_money(payout)}</b>\n"
        f"Баланс: <b>{fmt_money(new_balance)}</b>"
    )
    await query.answer()

# ==================== BASKET ====================

@dp.message(StateFilter(None), lambda m: (m.text or "").lower().startswith(("баскет", "баскетбол")))
async def basket_start(message: Message, state: FSMContext):
    parts = (message.text or "").strip().split()
    if len(parts) < 2:
        await state.clear()
        await state.set_state(BasketStates.waiting_amount)
        await message.answer("🏀 <b>Баскетбол</b>\nВведи сумму ставки:")
        return

    user_id = message.from_user.id
    balance = float(get_user(user_id)["coins"] or 0)
    try:
        bet = parse_bet_legacy(parts[1], balance)
    except Exception:
        await state.clear()
        await state.set_state(BasketStates.waiting_amount)
        await message.answer("Неверная ставка. Введи сумму:")
        return

    if bet < MIN_BET:
        await message.answer(f"Минимальная ставка: {fmt_money(MIN_BET)}")
        return

    roll = await message.answer_dice(emoji="🏀")
    value = int(roll.dice.value)
    win = value in {4, 5}
    result_title = basketball_value_text(value)
    payout = round(bet * 2.2, 2) if win else 0.0
    ok, new_balance = settle_instant_bet(
        user_id=user_id, bet=float(bet), payout=payout, choice="basketball", outcome=f"value={value}",
    )
    if not ok:
        await message.answer("Недостаточно средств.")
        return
    await message.answer(
        f"Итог броска: <b>{result_title}</b>\n"
        f"Результат: <b>{'Победа' if win else 'Поражение'}</b>\n"
        f"Выплата: <b>{fmt_money(payout)}</b>\n"
        f"Баланс: <b>{fmt_money(new_balance)}</b>"
    )

@dp.message(BasketStates.waiting_amount)
async def basket_amount(message: Message, state: FSMContext):
    try:
        bet = parse_amount(message.text)
    except Exception:
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
    dice_msg = await message.answer_dice(emoji="🏀")
    value = int(dice_msg.dice.value)
    win = value >= 4
    result_title = basketball_value_text(value)
    payout = round(bet * 1.85, 2) if win else 0.0
    balance = finalize_reserved_bet(
        message.from_user.id, bet, payout, choice="basket", outcome=f"value={value}",
    )
    await message.answer(
        f"{headline_user('🏀', message.from_user.id, message.from_user.first_name, 'бросок выполнен')}\n"
        f"<blockquote>Итог броска: <b>{result_title}</b>\n"
        f"Результат: <b>{'Победа' if win else 'Поражение'}</b>\n"
        f"Выплата: <b>{fmt_money(payout)}</b>\n"
        f"Баланс: <b>{fmt_money(balance)}</b></blockquote>"
  )# ==================== TOWER ====================

def tower_text(game: Dict[str, Any]) -> str:
    level = int(game["level"])
    bet = float(game["bet"])
    current_mult = TOWER_MULTIPLIERS[level - 1] if level > 0 else 0
    current_win = bet * current_mult if level > 0 else 0
    next_mult = (
        TOWER_MULTIPLIERS[level]
        if level < len(TOWER_MULTIPLIERS)
        else TOWER_MULTIPLIERS[-1]
    )
    return (
        "🗼 <b>Башня</b>\n"
        f"Ставка: <b>{fmt_money(bet)}</b>\n"
        f"Этаж: <b>{level}</b>\n"
        f"Текущий множитель: <b>x{current_mult:.2f}</b>\n"
        f"Потенциально сейчас: <b>{fmt_money(current_win)}</b>\n"
        f"Следующий этаж: <b>x{next_mult:.2f}</b>\n\n"
        "Выбери одну из 3 секций."
    )

@dp.message(StateFilter(None), lambda m: (m.text or "").lower().startswith("башня"))
async def tower_start(message: Message, state: FSMContext):
    parts = (message.text or "").strip().lower().split()
    if len(parts) < 2:
        await state.clear()
        await state.set_state(TowerStates.waiting_amount)
        await message.answer("🗼 <b>Башня</b>\nВведи сумму ставки:")
        return

    user_id = message.from_user.id
    lock = _game_lock(user_id)
    async with lock:
        if any(g.get("uid") == user_id and g.get("state") == "playing" for g in NTOWER_GAMES.values()):
            return await message.answer("У тебя уже есть активная башня.")
        if user_id in TOWER_GAMES:
            return await message.answer("У тебя уже есть активная башня.")

        balance = float(get_user(user_id)["coins"] or 0)
        try:
            bet = parse_bet_legacy(parts[1], balance)
        except Exception:
            return await message.answer("Неверная ставка.")

        mines = 1
        if len(parts) >= 3:
            try:
                mines = int(parts[2])
            except Exception:
                mines = 1
        if mines < 1 or mines > 4:
            return await message.answer("Количество мин: 1..4")
        if bet < MIN_BET:
            return await message.answer(f"Минимальная ставка: {fmt_money(MIN_BET)}")
        if bet > balance:
            return await message.answer("Недостаточно средств.")

        ok, _ = reserve_bet(user_id, float(bet))
        if not ok:
            return await message.answer("Недостаточно средств.")

        # Старая башня (3 секции)
        TOWER_GAMES[user_id] = {"bet": bet, "level": 0}
        await message.answer(tower_text(TOWER_GAMES[user_id]), reply_markup=tower_kb())

@dp.message(TowerStates.waiting_amount)
async def tower_start_amount(message: Message, state: FSMContext):
    try:
        bet = parse_amount(message.text)
    except Exception:
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

    chosen = int(query.data.split(":")[-1])
    safe = random.randint(1, 3)

    if chosen != safe:
        bet = float(game["bet"])
        balance = finalize_reserved_bet(user_id, bet, 0.0, "tower", "lose")
        TOWER_GAMES.pop(user_id, None)
        await query.message.edit_text(
            "💥 <b>Башня</b>\n"
            f"Ловушка в секции <b>{safe}</b>. Ты выбрал <b>{chosen}</b>.\n"
            f"Ставка сгорела: <b>{fmt_money(bet)}</b>\n"
            f"Баланс: <b>{fmt_money(balance)}</b>"
        )
        await query.answer()
        return

    game["level"] += 1
    level = int(game["level"])

    if level >= len(TOWER_MULTIPLIERS):
        bet = float(game["bet"])
        payout = round(bet * TOWER_MULTIPLIERS[-1], 2)
        balance = finalize_reserved_bet(user_id, bet, payout, "tower", "max_floor")
        TOWER_GAMES.pop(user_id, None)
        await query.message.edit_text(
            "🏁 <b>Башня</b>\n"
            "Максимальный этаж пройден.\n"
            f"Выплата: <b>{fmt_money(payout)}</b>\n"
            f"Баланс: <b>{fmt_money(balance)}</b>"
        )
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

    bet = float(game["bet"])
    level = int(game["level"])
    if level <= 0:
        await query.answer("Сначала сделай минимум 1 ход", show_alert=True)
        return

    mult = TOWER_MULTIPLIERS[level - 1]
    payout = round(bet * mult, 2)
    balance = finalize_reserved_bet(user_id, bet, payout, "tower", f"cashout_level={level}")
    TOWER_GAMES.pop(user_id, None)

    await query.message.edit_text(
        "✅ <b>Башня: выигрыш</b>\n"
        f"Этаж: <b>{level}</b>\n"
        f"Множитель: <b>x{mult:.2f}</b>\n"
        f"Выплата: <b>{fmt_money(payout)}</b>\n"
        f"Баланс: <b>{fmt_money(balance)}</b>"
    )
    await query.answer()

@dp.callback_query(F.data == "tower:cancel")
async def tower_cancel(query: CallbackQuery):
    user_id = query.from_user.id
    game = TOWER_GAMES.get(user_id)
    if not game:
        await query.answer("Нет активной игры", show_alert=True)
        return

    bet = float(game["bet"])
    level = int(game["level"])
    payout = 0.0
    outcome = "cancel_lose"
    if level == 0:
        payout = bet
        outcome = "cancel_refund"

    balance = finalize_reserved_bet(user_id, bet, payout, "tower", outcome)
    TOWER_GAMES.pop(user_id, None)
    await query.message.edit_text(
        "❌ <b>Башня завершена</b>\n"
        f"Возврат: <b>{fmt_money(payout)}</b>\n"
        f"Баланс: <b>{fmt_money(balance)}</b>"
    )
    await query.answer()

# ==================== GOLD ====================

def gold_text(game: Dict[str, Any]) -> str:
    step = int(game["step"])
    bet = float(game["bet"])
    cur_mult = GOLD_MULTIPLIERS[step - 1] if step > 0 else 0
    cur_win = bet * cur_mult if step > 0 else 0
    next_mult = (
        GOLD_MULTIPLIERS[step] if step < len(GOLD_MULTIPLIERS) else GOLD_MULTIPLIERS[-1]
    )
    return (
        "🥇 <b>Золото</b>\n"
        f"Ставка: <b>{fmt_money(bet)}</b>\n"
        f"Раунд: <b>{step}</b>\n"
        f"Текущий множитель: <b>x{cur_mult:.2f}</b>\n"
        f"Потенциально сейчас: <b>{fmt_money(cur_win)}</b>\n"
        f"Следующий раунд: <b>x{next_mult:.2f}</b>\n\n"
        "Выбери плитку (одна из них с ловушкой)."
    )

@dp.message(StateFilter(None), lambda m: (m.text or "").lower().startswith("золото"))
async def gold_start(message: Message, state: FSMContext):
    parts = (message.text or "").strip().lower().split()
    if len(parts) < 2:
        await state.clear()
        await state.set_state(GoldStates.waiting_amount)
        await message.answer("🥇 <b>Золото</b>\nВведи сумму ставки:")
        return

    user_id = message.from_user.id
    lock = _game_lock(user_id)
    async with lock:
        if any(g.get("uid") == user_id and g.get("state") == "playing" for g in NGOLD_GAMES.values()):
            return await message.answer("У тебя уже есть активная игра в золото.")
        if user_id in GOLD_GAMES:
            return await message.answer("У тебя уже есть активная игра в золото.")

        balance = float(get_user(user_id)["coins"] or 0)
        try:
            bet = parse_bet_legacy(parts[1], balance)
        except Exception:
            return await message.answer("Неверная ставка.")
        if bet < MIN_BET:
            return await message.answer(f"Минимальная ставка: {fmt_money(MIN_BET)}")
        if bet > balance:
            return await message.answer("Недостаточно средств.")

        ok, _ = reserve_bet(user_id, float(bet))
        if not ok:
            return await message.answer("Недостаточно средств.")

        # Запускаем legacy gold (12 уровней)
        levels = len(LEGACY_GOLD_MULTIPLIERS)
        bad_cells = [random.randint(0, 1) for _ in range(levels)]
        gid = _new_gid("g")
        game = {
            "gid": gid,
            "uid": user_id,
            "stake": int(bet),
            "bad_cells": bad_cells,
            "current_level": 0,
            "path": [],
            "state": "playing",
        }
        NGOLD_GAMES[gid] = game

        # Рендер legacy gold
        stake = int(bet)
        rows = []
        for i in reversed(range(levels)):
            left = "❔"
            right = "❔"
            value = f"{fmt_money(int(round(stake * LEGACY_GOLD_MULTIPLIERS[i])))}"
            rows.append(f"|{left}|{right}| {value} ({LEGACY_GOLD_MULTIPLIERS[i]}x)")

        await message.answer(
            "Золото: выбери клетку\n"
            f"Текущий приз: x0 / {fmt_money(0)}\n"
            f"Следующий шаг: x{LEGACY_GOLD_MULTIPLIERS[0]} / {fmt_money(int(round(stake * LEGACY_GOLD_MULTIPLIERS[0])))}\n\n"
            + "\n".join(rows),
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(text="❔", callback_data=f"ngold:{gid}:pick:0"),
                        InlineKeyboardButton(text="❔", callback_data=f"ngold:{gid}:pick:1"),
                    ],
                    [InlineKeyboardButton(text="Отмена", callback_data=f"ngold:{gid}:cancel")],
                ]
            ),
        )

@dp.message(GoldStates.waiting_amount)
async def gold_start_amount(message: Message, state: FSMContext):
    try:
        bet = parse_amount(message.text)
    except Exception:
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

    chosen = int(query.data.split(":")[-1])
    trap = random.randint(1, 4)

    if chosen == trap:
        bet = float(game["bet"])
        balance = finalize_reserved_bet(user_id, bet, 0.0, "gold", "lose")
        GOLD_GAMES.pop(user_id, None)
        await query.message.edit_text(
            "💥 <b>Золото</b>\n"
            f"Ловушка в плитке <b>{trap}</b>.\n"
            f"Потеряно: <b>{fmt_money(bet)}</b>\n"
            f"Баланс: <b>{fmt_money(balance)}</b>"
        )
        await query.answer()
        return

    game["step"] += 1
    step = int(game["step"])
    if step >= len(GOLD_MULTIPLIERS):
        bet = float(game["bet"])
        payout = round(bet * GOLD_MULTIPLIERS[-1], 2)
        balance = finalize_reserved_bet(user_id, bet, payout, "gold", "max_step")
        GOLD_GAMES.pop(user_id, None)
        await query.message.edit_text(
            "🏁 <b>Золото</b>\n"
            "Ты прошел все раунды.\n"
            f"Выплата: <b>{fmt_money(payout)}</b>\n"
            f"Баланс: <b>{fmt_money(balance)}</b>"
        )
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

    step = int(game["step"])
    bet = float(game["bet"])
    if step <= 0:
        await query.answer("Сначала сделай минимум 1 ход", show_alert=True)
        return

    mult = GOLD_MULTIPLIERS[step - 1]
    payout = round(bet * mult, 2)
    balance = finalize_reserved_bet(user_id, bet, payout, "gold", f"cashout_step={step}")
    GOLD_GAMES.pop(user_id, None)

    await query.message.edit_text(
        "✅ <b>Золото: выигрыш</b>\n"
        f"Раунд: <b>{step}</b>\n"
        f"Множитель: <b>x{mult:.2f}</b>\n"
        f"Выплата: <b>{fmt_money(payout)}</b>\n"
        f"Баланс: <b>{fmt_money(balance)}</b>"
    )
    await query.answer()

@dp.callback_query(F.data == "gold:cancel")
async def gold_cancel(query: CallbackQuery):
    user_id = query.from_user.id
    game = GOLD_GAMES.get(user_id)
    if not game:
        await query.answer("Нет активной игры", show_alert=True)
        return

    step = int(game["step"])
    bet = float(game["bet"])
    payout = bet if step == 0 else 0.0
    outcome = "cancel_refund" if step == 0 else "cancel_lose"
    balance = finalize_reserved_bet(user_id, bet, payout, "gold", outcome)
    GOLD_GAMES.pop(user_id, None)

    await query.message.edit_text(
        "❌ <b>Золото завершено</b>\n"
        f"Возврат: <b>{fmt_money(payout)}</b>\n"
        f"Баланс: <b>{fmt_money(balance)}</b>"
    )
    await query.answer()

# ==================== GOLD LEGACY CALLBACKS ====================

@dp.callback_query(F.data.startswith("ngold:"))
async def legacy_gold_cb(query: CallbackQuery):
    parts = (query.data or "").split(":")
    if len(parts) < 3:
        return await query.answer()
    _, gid, action = parts[:3]
    choice = int(parts[3]) if len(parts) == 4 and parts[3].isdigit() else None

    game = NGOLD_GAMES.get(gid)
    if not game:
        return await query.answer("Игра завершена", show_alert=True)
    if game["uid"] != query.from_user.id:
        return await query.answer("Это не твоя игра", show_alert=True)

    lock = _game_lock(query.from_user.id)
    async with lock:
        game = NGOLD_GAMES.get(gid)
        if not game or game.get("state") != "playing":
            return await query.answer("Игра завершена", show_alert=True)

        if action == "cancel":
            if int(game["current_level"]) != 0:
                return await query.answer("Нельзя отменить после хода", show_alert=True)
            stake = int(game["stake"])
            balance = add_balance(query.from_user.id, stake)
            NGOLD_GAMES.pop(gid, None)
            await query.message.edit_text(
                f"Игра отменена. Возвращено: <b>{fmt_money(stake)}</b>\nБаланс: <b>{fmt_money(balance)}</b>"
            )
            return await query.answer()

        if action == "collect":
            level = int(game["current_level"])
            if level <= 0:
                return await query.answer("Сделай хотя бы 1 ход", show_alert=True)
            mult = LEGACY_GOLD_MULTIPLIERS[level - 1]
            payout = int(round(int(game["stake"]) * mult))
            balance = finalize_reserved_bet(
                query.from_user.id, float(game["stake"]), float(payout), "gold", f"collect_lvl={level}",
            )
            NGOLD_GAMES.pop(gid, None)
            await query.message.edit_text(
                f"Ты забрал приз: <b>{fmt_money(payout)}</b> (x{mult})\nБаланс: <b>{fmt_money(balance)}</b>"
            )
            return await query.answer()

        if action == "pick":
            if choice not in {0, 1}:
                return await query.answer("Неверный выбор", show_alert=True)
            level = int(game["current_level"])
            if level >= len(LEGACY_GOLD_MULTIPLIERS):
                return await query.answer("Игра завершена", show_alert=True)

            bad = int(game["bad_cells"][level])
            game["path"].append(choice)

            if bad == choice:
                balance = finalize_reserved_bet(
                    query.from_user.id, float(game["stake"]), 0.0, "gold", "lose",
                )
                NGOLD_GAMES.pop(gid, None)
                await query.message.edit_text(
                    f"Поражение.\nБаланс: <b>{fmt_money(balance)}</b>"
                )
                return await query.answer()

            game["current_level"] = level + 1
            if game["current_level"] >= len(LEGACY_GOLD_MULTIPLIERS):
                payout = int(round(int(game["stake"]) * LEGACY_GOLD_MULTIPLIERS[-1]))
                balance = finalize_reserved_bet(
                    query.from_user.id, float(game["stake"]), float(payout), "gold", "won_full",
                )
                NGOLD_GAMES.pop(gid, None)
                await query.message.edit_text(
                    f"Все уровни пройдены!\nВыплата: <b>{fmt_money(payout)}</b>\nБаланс: <b>{fmt_money(balance)}</b>"
                )
                return await query.answer()

            NGOLD_GAMES[gid] = game
            stake = int(game["stake"])
            cur_level = int(game["current_level"])
            rows = []
            for i in reversed(range(len(LEGACY_GOLD_MULTIPLIERS))):
                if i < len(game["path"]):
                    left = "✅" if game["path"][i] == 0 else "◻️"
                    right = "✅" if game["path"][i] == 1 else "◻️"
                else:
                    left = right = "❔"
                value = f"{fmt_money(int(round(stake * LEGACY_GOLD_MULTIPLIERS[i])))}"
                rows.append(f"|{left}|{right}| {value} ({LEGACY_GOLD_MULTIPLIERS[i]}x)")

            cur_mult = LEGACY_GOLD_MULTIPLIERS[cur_level - 1] if cur_level > 0 else 0
            next_mult = LEGACY_GOLD_MULTIPLIERS[cur_level] if cur_level < len(LEGACY_GOLD_MULTIPLIERS) else LEGACY_GOLD_MULTIPLIERS[-1]
            cur_amt = int(round(stake * cur_mult))
            next_amt = int(round(stake * next_mult))

            await query.message.edit_text(
                "Золото: выбери клетку\n"
                f"Текущий приз: x{cur_mult} / {fmt_money(cur_amt)}\n"
                f"Следующий шаг: x{next_mult} / {fmt_money(next_amt)}\n\n"
                + "\n".join(rows),
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(text="❔", callback_data=f"ngold:{gid}:pick:0"),
                            InlineKeyboardButton(text="❔", callback_data=f"ngold:{gid}:pick:1"),
                        ],
                        [InlineKeyboardButton(text="Забрать", callback_data=f"ngold:{gid}:collect")],
                    ]
                ),
            )
            return await query.answer()

    await query.answer()

# ==================== DIAMONDS ====================

def diamond_text(game: Dict[str, Any]) -> str:
    step = int(game["step"])
    bet = float(game["bet"])
    cur_mult = DIAMOND_MULTIPLIERS[step - 1] if step > 0 else 0
    cur_win = bet * cur_mult if step > 0 else 0
    next_mult = (
        DIAMOND_MULTIPLIERS[step]
        if step < len(DIAMOND_MULTIPLIERS)
        else DIAMOND_MULTIPLIERS[-1]
    )
    return (
        "💎 <b>Алмазы</b>\n"
        f"Ставка: <b>{fmt_money(bet)}</b>\n"
        f"Шаг: <b>{step}</b>\n"
        f"Текущий множитель: <b>x{cur_mult:.2f}</b>\n"
        f"Потенциально сейчас: <b>{fmt_money(cur_win)}</b>\n"
        f"Следующий шаг: <b>x{next_mult:.2f}</b>\n\n"
        "Выбери кристалл (один из них бракованный)."
    )

@dp.message(StateFilter(None), lambda m: (m.text or "").lower().startswith("алмазы"))
async def diamonds_start(message: Message, state: FSMContext):
    parts = (message.text or "").strip().lower().split()
    if len(parts) < 2:
        await state.clear()
        await state.set_state(DiamondStates.waiting_amount)
        await message.answer("💎 <b>Алмазы</b>\nВведи сумму ставки:")
        return

    user_id = message.from_user.id
    lock = _game_lock(user_id)
    async with lock:
        if any(g.get("uid") == user_id and g.get("state") == "playing" for g in NDIAMOND_GAMES.values()):
            return await message.answer("У тебя уже есть активная игра в алмазы.")
        if user_id in DIAMOND_GAMES:
            return await message.answer("У тебя уже есть активная игра в алмазы.")

        balance = float(get_user(user_id)["coins"] or 0)
        try:
            bet = parse_bet_legacy(parts[1], balance)
        except Exception:
            return await message.answer("Неверная ставка.")

        mines_amount = 1
        if len(parts) >= 3:
            try:
                mines_amount = int(parts[2])
            except Exception:
                return await message.answer("Количество мин в ряду: 1 или 2.")
        if mines_amount < 1 or mines_amount > 2:
            return await message.answer("Количество мин в ряду: 1 или 2.")
        if bet < MIN_BET:
            return await message.answer(f"Минимальная ставка: {fmt_money(MIN_BET)}")
        if bet > balance:
            return await message.answer("Недостаточно средств.")

        ok, _ = reserve_bet(user_id, float(bet))
        if not ok:
            return await message.answer("Недостаточно средств.")

        ND_TOTAL_ROWS = 16
        ND_COLUMNS = 3
        bombs = []
        for _ in range(ND_TOTAL_ROWS):
            row = [0] * ND_COLUMNS
            for p in random.sample(range(ND_COLUMNS), mines_amount):
                row[p] = 1
            bombs.append(row)

        gid = _new_gid("d")
        state_data = {
            "gid": gid,
            "uid": user_id,
            "bet": int(bet),
            "mines_amount": int(mines_amount),
            "level": 0,
            "bombs": bombs,
            "selected": [],
            "lost": False,
            "state": "playing",
            "multipliers_history": [],
        }
        NDIAMOND_GAMES[gid] = state_data

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="❔", callback_data=f"ndiam:{gid}:pick:0"),
                    InlineKeyboardButton(text="❔", callback_data=f"ndiam:{gid}:pick:1"),
                    InlineKeyboardButton(text="❔", callback_data=f"ndiam:{gid}:pick:2"),
                ],
                [InlineKeyboardButton(text="Отмена", callback_data=f"ndiam:{gid}:cancel")],
            ]
        )
        await message.answer(
            f"Алмазы: выбери ячейку\nСтавка: <b>{fmt_money(bet)}</b>\nМин в ряду: <b>{mines_amount}</b>",
            reply_markup=kb,
        )

@dp.message(DiamondStates.waiting_amount)
async def diamond_start_amount(message: Message, state: FSMContext):
    try:
        bet = parse_amount(message.text)
    except Exception:
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

    chosen = int(query.data.split(":")[-1])
    trap = random.randint(1, 5)

    if chosen == trap:
        bet = float(game["bet"])
        balance = finalize_reserved_bet(user_id, bet, 0.0, "diamonds", "lose")
        DIAMOND_GAMES.pop(user_id, None)
        await query.message.edit_text(
            "💥 <b>Алмазы</b>\n"
            f"Бракованный кристалл: <b>{trap}</b>.\n"
            f"Потеряно: <b>{fmt_money(bet)}</b>\n"
            f"Баланс: <b>{fmt_money(balance)}</b>"
        )
        await query.answer()
        return

    game["step"] += 1
    step = int(game["step"])
    if step >= len(DIAMOND_MULTIPLIERS):
        bet = float(game["bet"])
        payout = round(bet * DIAMOND_MULTIPLIERS[-1], 2)
        balance = finalize_reserved_bet(user_id, bet, payout, "diamonds", "max_step")
        DIAMOND_GAMES.pop(user_id, None)
        await query.message.edit_text(
            "🏁 <b>Алмазы</b>\n"
            "Максимум шагов пройден.\n"
            f"Выплата: <b>{fmt_money(payout)}</b>\n"
            f"Баланс: <b>{fmt_money(balance)}</b>"
        )
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

    step = int(game["step"])
    bet = float(game["bet"])
    if step <= 0:
        await query.answer("Сначала сделай минимум 1 шаг", show_alert=True)
        return

    mult = DIAMOND_MULTIPLIERS[step - 1]
    payout = round(bet * mult, 2)
    balance = finalize_reserved_bet(user_id, bet, payout, "diamonds", f"cashout_step={step}")
    DIAMOND_GAMES.pop(user_id, None)

    await query.message.edit_text(
        "✅ <b>Алмазы: выигрыш</b>\n"
        f"Шаг: <b>{step}</b>\n"
        f"Множитель: <b>x{mult:.2f}</b>\n"
        f"Выплата: <b>{fmt_money(payout)}</b>\n"
        f"Баланс: <b>{fmt_money(balance)}</b>"
    )
    await query.answer()

@dp.callback_query(F.data == "diamond:cancel")
async def diamond_cancel(query: CallbackQuery):
    user_id = query.from_user.id
    game = DIAMOND_GAMES.get(user_id)
    if not game:
        await query.answer("Нет активной игры", show_alert=True)
        return

    step = int(game["step"])
    bet = float(game["bet"])
    payout = bet if step == 0 else 0.0
    outcome = "cancel_refund" if step == 0 else "cancel_lose"
    balance = finalize_reserved_bet(user_id, bet, payout, "diamonds", outcome)
    DIAMOND_GAMES.pop(user_id, None)

    await query.message.edit_text(
        "❌ <b>Алмазы завершены</b>\n"
        f"Возврат: <b>{fmt_money(payout)}</b>\n"
        f"Баланс: <b>{fmt_money(balance)}</b>"
    )
    await query.answer()

# ==================== DIAMONDS LEGACY CALLBACKS ====================

@dp.callback_query(F.data.startswith("ndiam:"))
async def legacy_diamonds_cb(query: CallbackQuery):
    parts = (query.data or "").split(":")
    if len(parts) < 3:
        return await query.answer()
    _, gid, action = parts[:3]
    idx = int(parts[3]) if len(parts) == 4 and parts[3].isdigit() else None

    state_data = NDIAMOND_GAMES.get(gid)
    if not state_data:
        return await query.answer("Игра завершена", show_alert=True)
    if int(state_data["uid"]) != query.from_user.id:
        return await query.answer("Это не твоя игра", show_alert=True)

    lock = _game_lock(query.from_user.id)
    async with lock:
        state_data = NDIAMOND_GAMES.get(gid)
        if not state_data or state_data.get("state") != "playing":
            return await query.answer("Игра завершена", show_alert=True)

        bet = int(state_data["bet"])
        ND_TOTAL_ROWS = 16
        ND_COLUMNS = 3
        ND_HOUSE_EDGE = 0.985

        if action == "cancel":
            if int(state_data["level"]) != 0 or state_data["selected"]:
                return await query.answer("После первого хода отмена недоступна", show_alert=True)
            balance = add_balance(query.from_user.id, bet)
            NDIAMOND_GAMES.pop(gid, None)
            await query.message.edit_text(
                f"Игра отменена. Возвращено: <b>{fmt_money(bet)}</b>\nБаланс: <b>{fmt_money(balance)}</b>"
            )
            return await query.answer()

        if action == "collect":
            if int(state_data["level"]) == 0:
                return await query.answer("Сделай хотя бы 1 ход", show_alert=True)
            # calc total mult
            prod = 1.0
            for m in state_data.get("multipliers_history", []):
                prod *= m
            total_mult = round(prod, 6)
            payout = int(round(bet * total_mult))
            state_data["state"] = "collected"
            balance = finalize_reserved_bet(
                query.from_user.id, float(bet), float(payout), "diamonds", "collect",
            )
            NDIAMOND_GAMES.pop(gid, None)
            await query.message.edit_text(
                f"Приз забран: <b>{fmt_money(payout)}</b> (x{round(total_mult, 2)})\nБаланс: <b>{fmt_money(balance)}</b>"
            )
            return await query.answer()

        if action == "pick":
            if idx is None or idx < 0 or idx >= ND_COLUMNS:
                return await query.answer("Неверный выбор", show_alert=True)
            level = int(state_data["level"])
            if level < 0 or level >= ND_TOTAL_ROWS:
                return await query.answer("Неверный уровень", show_alert=True)

            # calc step mult
            row_bombs = state_data["bombs"][level]
            mines_in_row = sum(1 for x in row_bombs if int(x) == 1)
            safe = ND_COLUMNS - mines_in_row
            p_safe = safe / ND_COLUMNS if safe > 0 else 0
            step_mult = round((1.0 / p_safe) * ND_HOUSE_EDGE, 6) if p_safe > 0 else 0
            if step_mult <= 0:
                step_mult = 1.0

            state_data["selected"].append(idx)

            if state_data["bombs"][level][idx] == 1:
                state_data["lost"] = True
                state_data["state"] = "lost"
                balance = finalize_reserved_bet(
                    query.from_user.id, float(bet), 0.0, "diamonds", "explode",
                )
                NDIAMOND_GAMES.pop(gid, None)
                await query.message.edit_text(
                    f"Ты попал на мину.\nРяд: <b>{level + 1}</b>\nБаланс: <b>{fmt_money(balance)}</b>"
                )
                return await query.answer()

            state_data["multipliers_history"].append(step_mult)
            state_data["level"] = level + 1

            if int(state_data["level"]) >= ND_TOTAL_ROWS:
                prod = 1.0
                for m in state_data.get("multipliers_history", []):
                    prod *= m
                total_mult = round(prod, 6)
                payout = int(round(bet * total_mult))
                state_data["state"] = "won"
                balance = finalize_reserved_bet(
                    query.from_user.id, float(bet), float(payout), "diamonds", "won_full",
                )
                NDIAMOND_GAMES.pop(gid, None)
                await query.message.edit_text(
                    f"Все ряды пройдены.\nВыплата: <b>{fmt_money(payout)}</b> (x{round(total_mult, 2)})\n"
                    f"Баланс: <b>{fmt_money(balance)}</b>"
                )
                return await query.answer()

            prod = 1.0
            for m in state_data.get("multipliers_history", []):
                prod *= m
            total_mult = round(prod, 6)
            potential = int(round(bet * total_mult))

            # build keyboard
            cur_level = int(state_data["level"])
            ND_SHOW_PREV_ROWS = 8
            start_prev = max(0, cur_level - ND_SHOW_PREV_ROWS)
            kb_rows = []
            for i in range(start_prev, cur_level):
                picked = state_data["selected"][i] if i < len(state_data["selected"]) else None
                r = []
                for j in range(ND_COLUMNS):
                    r.append(InlineKeyboardButton(text=("✅" if picked == j else "◻️"), callback_data="nnoop"))
                kb_rows.append(r)

            kb_rows.append([
                InlineKeyboardButton(text="❔", callback_data=f"ndiam:{gid}:pick:{j}")
                for j in range(ND_COLUMNS)
            ])
            kb_rows.append([InlineKeyboardButton(text="Забрать", callback_data=f"ndiam:{gid}:collect")])

            await query.message.edit_text(
                f"Алмазы: игра продолжается\n"
                f"Ряд: <b>{cur_level}/{ND_TOTAL_ROWS}</b>\n"
                f"Мин в ряду: <b>{state_data['mines_amount']}</b>\n"
                f"Текущий множитель: <b>x{round(total_mult, 2)}</b>\n"
                f"Возможный приз: <b>{fmt_money(potential)}</b>",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows),
            )
            return await query.answer()

    await query.answer()


@dp.callback_query(F.data == "nnoop")
async def n_noop(query: CallbackQuery):
    await query.answer()# ==================== MINES ====================

def mines_text(game: Dict[str, Any]) -> str:
    bet = float(game["bet"])
    opened_count = len(game["opened"])
    mines_count = int(game["mines_count"])
    mult = mines_multiplier(opened_count, mines_count)
    potential = round(bet * mult, 2)
    return (
        "💣 <b>Мины</b>\n"
        f"<blockquote>Ставка: <b>{fmt_money(bet)}</b>\n"
        f"Мин: <b>{mines_count}</b>\n"
        f"Открыто безопасных: <b>{opened_count}</b>\n"
        f"Текущий множитель: <b>x{mult:.2f}</b>\n"
        f"Потенциально сейчас: <b>{fmt_money(potential)}</b></blockquote>\n\n"
        "<i>Открывай клетки или забирай выигрыш.</i>"
    )

@dp.message(StateFilter(None), lambda m: (m.text or "").lower().startswith("мины"))
async def mines_start(message: Message, state: FSMContext):
    parts = (message.text or "").strip().lower().split()
    if len(parts) < 2:
        await state.clear()
        await state.set_state(MinesStates.waiting_amount)
        await message.answer("💣 <b>Мины</b>\nВведи сумму ставки:")
        return

    user_id = message.from_user.id
    lock = _game_lock(user_id)
    async with lock:
        if any(g.get("uid") == user_id and g.get("state") == "playing" for g in NMINES_GAMES.values()):
            return await message.answer("У тебя уже есть активная игра в мины.")
        if user_id in MINES_GAMES:
            return await message.answer("У тебя уже есть активная игра в мины.")

        balance = float(get_user(user_id)["coins"] or 0)
        try:
            bet = parse_bet_legacy(parts[1], balance)
        except Exception:
            return await message.answer("Неверная ставка.")

        mines_count = 1
        if len(parts) >= 3:
            try:
                mines_count = int(parts[2])
            except Exception:
                return await message.answer("Количество мин: число 1..5.")

        if not (1 <= mines_count <= 5):
            return await message.answer("Количество мин: 1..5.")
        if bet < MIN_BET:
            return await message.answer(f"Минимальная ставка: {fmt_money(MIN_BET)}")
        if bet > balance:
            return await message.answer("Недостаточно средств.")

        ok, _ = reserve_bet(user_id, float(bet))
        if not ok:
            return await message.answer("Недостаточно средств.")

        # Поле 3x3
        cells = list(range(1, 10))
        mines_positions = set(random.sample(cells, mines_count))
        MINES_GAMES[user_id] = {
            "bet": bet,
            "mines_count": mines_count,
            "mines": mines_positions,
            "opened": set(),
        }

        game = MINES_GAMES[user_id]
        await message.answer(mines_text(game), reply_markup=mines_kb(game))

@dp.message(MinesStates.waiting_amount)
async def mines_amount(message: Message, state: FSMContext):
    try:
        bet = parse_amount(message.text)
    except Exception:
        await message.answer("Введи корректную ставку.")
        return
    if bet < MIN_BET:
        await message.answer(f"Минимальная ставка: {fmt_money(MIN_BET)}")
        return
    await state.update_data(bet=bet)
    await state.set_state(MinesStates.waiting_mines)
    await message.answer("Сколько мин на поле 3x3? (1-5)")

@dp.message(MinesStates.waiting_mines)
async def mines_count(message: Message, state: FSMContext):
    data = await state.get_data()
    bet = float(data.get("bet", 0) or 0)
    try:
        mines_count = parse_int(message.text)
    except Exception:
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
    mines_positions = set(random.sample(cells, mines_count))
    MINES_GAMES[message.from_user.id] = {
        "bet": bet,
        "mines_count": mines_count,
        "mines": mines_positions,
        "opened": set(),
    }

    game = MINES_GAMES[message.from_user.id]
    await message.answer(mines_text(game), reply_markup=mines_kb(game))

@dp.callback_query(F.data == "mines:noop")
async def mines_noop(query: CallbackQuery):
    await query.answer()

@dp.callback_query(F.data.startswith("mines:cell:"))
async def mines_cell(query: CallbackQuery):
    user_id = query.from_user.id
    game = MINES_GAMES.get(user_id)
    if not game:
        await query.answer("Нет активной игры", show_alert=True)
        return

    idx = int(query.data.split(":")[-1])
    if idx in game["opened"]:
        await query.answer("Клетка уже открыта", show_alert=True)
        return

    if idx in game["mines"]:
        bet = float(game["bet"])
        balance = finalize_reserved_bet(user_id, bet, 0.0, "mines", "explode")
        text = (
            "💥 <b>Мины</b>\n"
            f"<blockquote>Ты попал на мину в клетке <b>{idx}</b>.\n"
            f"Потеряно: <b>{fmt_money(bet)}</b>\n"
            f"Баланс: <b>{fmt_money(balance)}</b></blockquote>"
        )
        await query.message.edit_text(text, reply_markup=mines_kb(game, reveal_all=True))
        MINES_GAMES.pop(user_id, None)
        await query.answer()
        return

    game["opened"].add(idx)
    safe_opened = len(game["opened"])
    safe_total = 9 - int(game["mines_count"])

    if safe_opened >= safe_total:
        bet = float(game["bet"])
        mult = mines_multiplier(safe_opened, int(game["mines_count"]))
        payout = round(bet * mult, 2)
        balance = finalize_reserved_bet(user_id, bet, payout, "mines", "cleared_all")
        await query.message.edit_text(
            "🏁 <b>Мины</b>\n"
            f"<blockquote>Все безопасные клетки открыты.\n"
            f"Множитель: <b>x{mult:.2f}</b>\n"
            f"Выплата: <b>{fmt_money(payout)}</b>\n"
            f"Баланс: <b>{fmt_money(balance)}</b></blockquote>",
            reply_markup=mines_kb(game, reveal_all=True),
        )
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

    bet = float(game["bet"])
    safe_opened = len(game["opened"])
    mines_count = int(game["mines_count"])

    if safe_opened <= 0:
        await query.answer("Сначала открой хотя бы 1 клетку", show_alert=True)
        return

    mult = mines_multiplier(safe_opened, mines_count)
    payout = round(bet * mult, 2)
    balance = finalize_reserved_bet(user_id, bet, payout, "mines", f"cashout_{safe_opened}")
    await query.message.edit_text(
        "✅ <b>Мины: выигрыш</b>\n"
        f"<blockquote>Открыто безопасных: <b>{safe_opened}</b>\n"
        f"Множитель: <b>x{mult:.2f}</b>\n"
        f"Выплата: <b>{fmt_money(payout)}</b>\n"
        f"Баланс: <b>{fmt_money(balance)}</b></blockquote>",
        reply_markup=mines_kb(game, reveal_all=True),
    )
    MINES_GAMES.pop(user_id, None)
    await query.answer()

@dp.callback_query(F.data == "mines:cancel")
async def mines_cancel(query: CallbackQuery):
    user_id = query.from_user.id
    game = MINES_GAMES.get(user_id)
    if not game:
        await query.answer("Нет активной игры", show_alert=True)
        return

    bet = float(game["bet"])
    safe_opened = len(game["opened"])
    mines_count = int(game["mines_count"])

    if safe_opened <= 0:
        payout = bet
        outcome = "cancel_refund"
    else:
        payout = round(bet * mines_multiplier(safe_opened, mines_count), 2)
        outcome = f"cancel_cashout_{safe_opened}"

    balance = finalize_reserved_bet(user_id, bet, payout, "mines", outcome)
    await query.message.edit_text(
        "❌ <b>Мины завершены</b>\n"
        f"Выплата: <b>{fmt_money(payout)}</b>\n"
        f"Баланс: <b>{fmt_money(balance)}</b>",
        reply_markup=mines_kb(game, reveal_all=True),
    )
    MINES_GAMES.pop(user_id, None)
    await query.answer()

# ==================== OCHKO (BLACKJACK) ====================

@dp.message(StateFilter(None), lambda m: (m.text or "").lower().startswith("очко"))
async def ochko_start(message: Message, state: FSMContext):
    parts = (message.text or "").strip().lower().split()
    if len(parts) < 2:
        await state.clear()
        await state.set_state(OchkoStates.waiting_amount)
        await message.answer("🎴 <b>Очко</b>\nВведи сумму ставки:")
        return

    user_id = message.from_user.id
    lock = _game_lock(user_id)
    async with lock:
        if any(g.get("uid") == user_id and g.get("state") == "playing" for g in NOCHKO_GAMES.values()):
            return await message.answer("У тебя уже есть активная игра в очко.")
        if user_id in OCHKO_GAMES:
            return await message.answer("У тебя уже есть активная игра в очко.")

        balance = float(get_user(user_id)["coins"] or 0)
        try:
            bet = parse_bet_legacy(parts[1], balance)
        except Exception:
            return await message.answer("Неверная ставка.")
        if bet < MIN_BET:
            return await message.answer(f"Минимальная ставка: {fmt_money(MIN_BET)}")
        if bet > balance:
            return await message.answer("Недостаточно средств.")

        await state.clear()
        await state.update_data(bet=float(bet))
        await state.set_state(OchkoStates.waiting_confirm)
        await message.answer(
            f"{headline_user('🎴', message.from_user.id, message.from_user.first_name, 'желаешь начать игру?')}\n"
            f"<blockquote>Ставка: <b>{fmt_money(float(bet))}</b>\n"
            "<i>После начала игры отменить ее уже нельзя.</i></blockquote>",
            reply_markup=ochko_confirm_kb(),
        )

@dp.message(OchkoStates.waiting_amount)
async def ochko_amount(message: Message, state: FSMContext):
    try:
        bet = parse_amount(message.text)
    except Exception:
        await message.answer("Введи корректную ставку.")
        return
    if bet < MIN_BET:
        await message.answer(f"Минимальная ставка: {fmt_money(MIN_BET)}")
        return
    await state.update_data(bet=bet)
    await state.set_state(OchkoStates.waiting_confirm)
    await message.answer(
        f"{headline_user('🎴', message.from_user.id, message.from_user.first_name, 'желаешь начать игру?')}\n"
        f"<blockquote>Ставка: <b>{fmt_money(bet)}</b>\n"
        "<i>После начала игры отменить ее уже нельзя.</i></blockquote>",
        reply_markup=ochko_confirm_kb(),
    )

@dp.callback_query(OchkoStates.waiting_confirm, F.data == "ochko:cancel")
async def ochko_cancel_before_start(query: CallbackQuery, state: FSMContext):
    await state.clear()
    await query.message.edit_text(
        f"{headline_user('❌', query.from_user.id, query.from_user.first_name, 'игра в очко отменена')}\n"
        "<blockquote><i>Ставка не списана.</i></blockquote>"
    )
    await query.answer()

@dp.callback_query(OchkoStates.waiting_confirm, F.data == "ochko:start")
async def ochko_start_confirm(query: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    bet = float(data.get("bet", 0) or 0)
    if bet < MIN_BET:
        await state.clear()
        await query.answer("Ставка не найдена", show_alert=True)
        return

    ok, _ = reserve_bet(query.from_user.id, bet)
    await state.clear()
    if not ok:
        await query.message.edit_text(
            f"{headline_user('❌', query.from_user.id, query.from_user.first_name, 'недостаточно средств для игры')}"
        )
        await query.answer()
        return

    deck = make_deck()
    player = [deck.pop(), deck.pop()]
    dealer = [deck.pop(), deck.pop()]
    OCHKO_GAMES[query.from_user.id] = {
        "bet": bet,
        "deck": deck,
        "player": player,
        "dealer": dealer,
    }
    game = OCHKO_GAMES[query.from_user.id]

    player_value = hand_value(player)
    dealer_value = hand_value(dealer)

    if player_value == 21:
        if dealer_value == 21:
            payout = bet
            outcome = "blackjack_push"
            text = (
                "🎴 <b>Очко</b>\n"
                f"{render_ochko_table(game, reveal_dealer=True)}\n\n"
                "Ничья по blackjack."
            )
        else:
            payout = round(bet * 2.5, 2)
            outcome = "blackjack_win"
            text = (
                "🎴 <b>Очко</b>\n"
                f"{render_ochko_table(game, reveal_dealer=True)}\n\n"
                "Blackjack!"
            )

        balance = finalize_reserved_bet(query.from_user.id, bet, payout, "ochko", outcome)
        OCHKO_GAMES.pop(query.from_user.id, None)
        await query.message.edit_text(
            f"{headline_user('🎴', query.from_user.id, query.from_user.first_name, 'игра окончена')}\n"
            f"{text}\n"
            f"Выплата: <b>{fmt_money(payout)}</b>\n"
            f"Баланс: <b>{fmt_money(balance)}</b>"
        )
        await query.answer()
        return

    await query.message.edit_text(
        render_ochko_table(game, reveal_dealer=False), reply_markup=ochko_kb()
    )
    await query.answer()

@dp.callback_query(F.data == "ochko:hit")
async def ochko_hit(query: CallbackQuery):
    user_id = query.from_user.id
    game = OCHKO_GAMES.get(user_id)
    if not game:
        await query.answer("Нет активной игры", show_alert=True)
        return

    deck = game["deck"]
    game["player"].append(deck.pop())
    value = hand_value(game["player"])

    if value > 21:
        bet = float(game["bet"])
        balance = finalize_reserved_bet(user_id, bet, 0.0, "ochko", "bust")
        await query.message.edit_text(
            f"{render_ochko_table(game, reveal_dealer=True)}\n\n"
            "Перебор. Ты проиграл.\n"
            f"Баланс: <b>{fmt_money(balance)}</b>"
        )
        OCHKO_GAMES.pop(user_id, None)
        await query.answer()
        return

    await query.message.edit_text(
        render_ochko_table(game, reveal_dealer=False), reply_markup=ochko_kb()
    )
    await query.answer()

@dp.callback_query(F.data == "ochko:stand")
async def ochko_stand(query: CallbackQuery):
    user_id = query.from_user.id
    game = OCHKO_GAMES.get(user_id)
    if not game:
        await query.answer("Нет активной игры", show_alert=True)
        return

    deck = game["deck"]
    player_value = hand_value(game["player"])
    while hand_value(game["dealer"]) < 17:
        game["dealer"].append(deck.pop())

    dealer_value = hand_value(game["dealer"])
    bet = float(game["bet"])

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
    await query.message.edit_text(
        f"{render_ochko_table(game, reveal_dealer=True)}\n\n"
        f"Результат: <b>{result_text}</b>\n"
        f"Выплата: <b>{fmt_money(payout)}</b>\n"
        f"Баланс: <b>{fmt_money(balance)}</b>"
    )
    OCHKO_GAMES.pop(user_id, None)
    await query.answer()


# ==================== NTOWER (LEGACY TOWER) CALLBACKS ====================

@dp.callback_query(F.data.startswith("ntower:"))
async def legacy_tower_cb(query: CallbackQuery):
    parts = (query.data or "").split(":")
    if len(parts) < 3:
        return await query.answer()
    _, gid, action = parts[:3]
    choice = int(parts[3]) if len(parts) == 4 and parts[3].isdigit() else None

    game = NTOWER_GAMES.get(gid)
    if not game:
        return await query.answer("Игра завершена", show_alert=True)
    if int(game["uid"]) != query.from_user.id:
        return await query.answer("Это не твоя игра", show_alert=True)

    lock = _game_lock(query.from_user.id)
    async with lock:
        game = NTOWER_GAMES.get(gid)
        if not game or game.get("state") != "playing":
            return await query.answer("Игра завершена", show_alert=True)

        if action == "cancel":
            if int(game["level"]) != 0 or game["selected"]:
                return await query.answer("После первого хода отмена недоступна", show_alert=True)
            bet = int(game["bet"])
            balance = add_balance(query.from_user.id, bet)
            NTOWER_GAMES.pop(gid, None)
            await query.message.edit_text(
                f"Игра отменена. Возвращено: <b>{fmt_money(bet)}</b>\nБаланс: <b>{fmt_money(balance)}</b>"
            )
            return await query.answer()

        if action == "collect":
            level = int(game["level"])
            if level <= 0:
                return await query.answer("Сделай хотя бы 1 ход", show_alert=True)
            mult = ntower_multiplier(level, int(game["mines"]))
            payout = int(round(int(game["bet"]) * mult))
            game["state"] = "collected"
            balance = finalize_reserved_bet(
                query.from_user.id, float(game["bet"]), float(payout), "tower", f"collect_lvl={level}",
            )
            NTOWER_GAMES.pop(gid, None)
            await query.message.edit_text(
                f"Приз забран: <b>{fmt_money(payout)}</b> (x{mult})\nБаланс: <b>{fmt_money(balance)}</b>"
            )
            return await query.answer()

        if action == "pick":
            if choice is None or choice < 0 or choice > 4:
                return await query.answer("Неверный выбор", show_alert=True)
            level = int(game["level"])
            if level < 0 or level > 8:
                return await query.answer("Неверный уровень", show_alert=True)

            game["selected"].append(choice)
            if game["bombs"][level][choice] == 1:
                game["state"] = "lost"
                balance = finalize_reserved_bet(
                    query.from_user.id, float(game["bet"]), 0.0, "tower", "lose",
                )
                NTOWER_GAMES.pop(gid, None)
                await query.message.edit_text(
                    f"Поражение.\nУровень: <b>{level}/9</b>\nБаланс: <b>{fmt_money(balance)}</b>"
                )
                return await query.answer()

            game["level"] = level + 1
            if int(game["level"]) >= 9:
                mult = ntower_multiplier(9, int(game["mines"]))
                payout = int(round(int(game["bet"]) * mult))
                game["state"] = "won"
                balance = finalize_reserved_bet(
                    query.from_user.id, float(game["bet"]), float(payout), "tower", "won_top",
                )
                NTOWER_GAMES.pop(gid, None)
                await query.message.edit_text(
                    f"Вершина пройдена!\nВыплата: <b>{fmt_money(payout)}</b> (x{mult})\n"
                    f"Баланс: <b>{fmt_money(balance)}</b>"
                )
                return await query.answer()

            NTOWER_GAMES[gid] = game

            # Рендер клавиатуры
            cur_level = int(game["level"])
            selected = game["selected"]
            kb_rows = []
            kb_rows.append([
                InlineKeyboardButton(text="❔", callback_data=f"ntower:{gid}:pick:{j}")
                for j in range(5)
            ])
            for i in range(cur_level - 1, -1, -1):
                chosen = selected[i] if i < len(selected) else None
                r = []
                for j in range(5):
                    r.append(InlineKeyboardButton(text=("✅" if chosen == j else "◻️"), callback_data="nnoop"))
                kb_rows.append(r)
            kb_rows.append([InlineKeyboardButton(text="Забрать", callback_data=f"ntower:{gid}:collect")])

            next_mult = ntower_multiplier(min(cur_level + 1, 9), int(game["mines"]))
            now_mult = ntower_multiplier(cur_level, int(game["mines"]))

            await query.message.edit_text(
                f"Башня\n"
                f"Ряд: <b>{min(cur_level + 1, 9)}/9</b>\n"
                f"Ставка: <b>{fmt_money(int(game['bet']))}</b>\n"
                f"Мин в ряду: <b>{game['mines']}</b>\n"
                f"Текущий множитель: <b>x{now_mult}</b>\n"
                f"Следующий множитель: <b>x{next_mult}</b>\n"
                f"Потенциальный приз: <b>{fmt_money(int(int(game['bet']) * next_mult))}</b>",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows),
            )
            return await query.answer()

    await query.answer()


def ntower_multiplier(level: int, mines: int, house_edge: float = 0.97, max_mult: float = 10000.0) -> float:
    mines = max(1, min(4, int(mines)))
    level = max(1, int(level))
    p_single = (5 - mines) / 5.0
    if p_single <= 0:
        fair = float("inf")
    else:
        fair = 1.0 / (p_single ** level)
    mult = fair * house_edge
    if not (mult < float("inf")):
        mult = max_mult
    return round(min(mult, max_mult), 2)


# ==================== LAUNCH ====================

async def main() -> None:
    init_db()
    bot = Bot(
        token=get_bot_token(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
