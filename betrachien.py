import asyncio
import logging
import sqlite3
import requests
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters import Command, StateFilter
import random
import uuid
import shutil
import os
import json

# ------------------- SETTINGS -------------------
BOT_TOKEN = "8290771687:AAGr8B0ntWp40hZ4d_qIN8wENlndyqLN7TI"
TON_WALLET = "UQDo1VlU9TsqUNdp7TR82NtnZHGBBSvrlVFcVqX7RGCgl94b"
TON_API_KEY = "9060786ace747b6d2803f447ab760568b65bc3de5a2155e03e777f626a47e34f"
END_DATE = datetime(2026, 1, 1, 0, 0, 0)
TOTAL_SUPPLY = 100_000_000
BASE_TOKEN_PRICE = 0.5
X_LINK = "https://x.com/batrachiencoin"
ENERGY_REGEN_RATE = 1
MAX_ENERGY_BASE = 1000
DAILY_REWARD = 100
MULTI_LEVEL_REF_DEPTH = 5
REF_BONUS_PERCENTAGES = [0.10, 0.07, 0.05, 0.03, 0.01]
SPIN_REWARDS = ["points_100", "points_500", "energy_refill", "rare_item", "free_boost", "jackpot_1000", "token_bonus_100"]
SUPER_RARE_CHANCE = 3
GLOBAL_EVENT_ACTIVE = False
GLOBAL_EVENT_END = None
GLOBAL_EVENT_MULTI = 1.0
AIRDROP_THRESHOLD = 10000

# ------------------- DATABASE -------------------
DB_FILE = "batrachien.db"
DB_BACKUP = "batrachien_backup.db"

conn = sqlite3.connect(DB_FILE, check_same_thread=False)
cursor = conn.cursor()

def backup_db():
    if os.path.exists(DB_FILE):
        shutil.copy(DB_FILE, DB_BACKUP)
        logging.info("Database backed up to batrachien_backup.db")

def init_db():
    backup_db()
    cursor.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        ref_code TEXT,
        referred_by INTEGER
    )""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS sales (
        user_id INTEGER,
        amount INTEGER,
        tx_hash TEXT
    )""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS pending_payments (
        user_id INTEGER,
        amount INTEGER,
        tx_timestamp TEXT,
        tx_id TEXT
    )""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS points (
        user_id INTEGER PRIMARY KEY,
        batrapoints INTEGER DEFAULT 0,
        token_balance INTEGER DEFAULT 0,
        energy INTEGER DEFAULT 1000,
        max_energy INTEGER DEFAULT 1000,
        last_energy_update TEXT,
        last_daily_claim TEXT,
        last_spin TEXT,
        last_passive_update TEXT,
        tap_count INTEGER DEFAULT 0,
        star_battle_wins INTEGER DEFAULT 0,
        staked_tokens INTEGER DEFAULT 0,
        stake_start TEXT
    )""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS boosts (
        user_id INTEGER PRIMARY KEY,
        active_until TEXT
    )""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS rare_items (
        user_id INTEGER,
        item_name TEXT,
        PRIMARY KEY (user_id, item_name)
    )""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS levels (
        user_id INTEGER PRIMARY KEY,
        level INTEGER DEFAULT 1,
        title TEXT
    )""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS upgrades (
        user_id INTEGER PRIMARY KEY,
        multi_tap_level INTEGER DEFAULT 0,
        energy_regen_level INTEGER DEFAULT 0,
        max_energy_level INTEGER DEFAULT 0,
        auto_tap_level INTEGER DEFAULT 0,
        galaxy_conquer_level INTEGER DEFAULT 0
    )""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS achievements (
        user_id INTEGER,
        achievement_name TEXT,
        PRIMARY KEY (user_id, achievement_name)
    )""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS airdrops (
        user_id INTEGER PRIMARY KEY,
        last_airdrop TEXT
    )""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS missions (
        user_id INTEGER,
        mission_name TEXT,
        completed_at TEXT,
        PRIMARY KEY (user_id, mission_name)
    )""")
    
    for table, columns in {
        "users": ["username", "ref_code", "referred_by"],
        "pending_payments": ["amount", "tx_timestamp", "tx_id"],
        "points": ["token_balance", "tap_count", "star_battle_wins", "staked_tokens", "stake_start"],
        "upgrades": ["galaxy_conquer_level"],
        "levels": ["title"]
    }.items():
        cursor.execute(f"PRAGMA table_info({table})")
        existing = [col[1] for col in cursor.fetchall()]
        for col in columns:
            if col not in existing:
                col_type = 'TEXT' if col.endswith('timestamp') or col.endswith('start') or col == 'title' else 'INTEGER DEFAULT 0'
                try:
                    cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
                    logging.info(f"Added column {col} to {table}")
                except sqlite3.OperationalError as e:
                    logging.error(f"Failed to add column {col} to {table}: {e}")
    conn.commit()

init_db()

# ------------------- FSM -------------------
class PresaleStates(StatesGroup):
    amount = State()
    burn = State()
    stake = State()

# ------------------- BOT -------------------
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

FROG_ART = """
🌌🐸🚀🐸🚀🐸🌌
    🐸🐸🐸
🐸🐸🐸🐸🐸
    🐸🐸🐸
🌌🐸🚀🐸🚀🐸🌌
💥 **Batrachien: Rule the Cosmos!** 💥
"""

# ------------------- HELPER FUNCTIONS -------------------
def get_countdown():
    remaining = END_DATE - datetime.now()
    if remaining.total_seconds() > 0:
        days, seconds = remaining.days, remaining.seconds
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"⏳ **{days}d {hours}h {minutes}m** left to conquer! ⏳"
    return "🎉 **Presale ended!** Cosmic launch initiated! 🐸💫"

def get_sold_amount():
    cursor.execute("SELECT SUM(amount) FROM sales")
    sold = cursor.fetchone()[0] or 0
    return sold

def get_token_price():
    sold = get_sold_amount()
    price_multi = 1 + (sold / TOTAL_SUPPLY) * 0.5
    return BASE_TOKEN_PRICE * price_multi

def get_stats():
    sold = get_sold_amount()
    remaining = TOTAL_SUPPLY - sold
    progress = int((sold / TOTAL_SUPPLY) * 20)
    bar = '🟪' * progress + '⬛' * (20 - progress)
    return f"📊 **Token Conquest**: {sold}/{TOTAL_SUPPLY} (Remaining: {remaining})\n{bar}\n💰 **Price**: 1 Batrachien = {get_token_price():.2f} TON"

def generate_ref_code(user_id):
    return f"bat_{user_id}"

def get_title(level):
    if level >= 100: return "Star Emperor"
    if level >= 50: return "Nebula Lord"
    if level >= 25: return "Cosmic Commander"
    if level >= 10: return "Galactic Warrior"
    return "Frog Cadet"

def get_leaderboard(type="points"):
    if type == "points":
        cursor.execute("SELECT u.user_id, p.batrapoints, u.username, l.level, l.title FROM points p JOIN users u ON p.user_id = u.user_id JOIN levels l ON p.user_id = l.user_id ORDER BY p.batrapoints DESC LIMIT 10")
        rows = cursor.fetchall()
        text = "🏆 **Cosmic BatraPoints Leaderboard** 🏆\n"
        for idx, (uid, pts, uname, level, title) in enumerate(rows, start=1):
            display_name = uname or f"User {uid}"
            title = title or get_title(level)
            text += f"{idx}. {display_name} - {pts} pts ({title}, Lvl {level})\n"
    elif type == "tokens":
        cursor.execute("SELECT u.user_id, p.token_balance, u.username, l.level, l.title FROM points p JOIN users u ON p.user_id = u.user_id JOIN levels l ON p.user_id = l.user_id ORDER BY p.token_balance DESC LIMIT 10")
        rows = cursor.fetchall()
        text = "💎 **Batrachien Token Leaderboard** 💎\n"
        for idx, (uid, tokens, uname, level, title) in enumerate(rows, start=1):
            display_name = uname or f"User {uid}"
            title = title or get_title(level)
            text += f"{idx}. {display_name} - {tokens} tokens ({title}, Lvl {level})\n"
    return text if rows else f"No {type} yet! Start conquering! 🚀"

def get_ref_leaderboard():
    cursor.execute("SELECT u.user_id, u.username, COUNT(r.user_id) as refs FROM users u LEFT JOIN users r ON r.referred_by = u.user_id GROUP BY u.user_id ORDER BY refs DESC LIMIT 10")
    rows = cursor.fetchall()
    text = "👑 **Intergalactic Referral Lords** 👑\n"
    for idx, (uid, uname, refs) in enumerate(rows, start=1):
        display_name = uname or f"User {uid}"
        text += f"{idx}. {display_name} - {refs} cosmic allies\n"
    return text if rows else "No allies yet! Build your empire! 🌌"

def award_multi_level_referral(user_id, amount, level=1):
    if level > MULTI_LEVEL_REF_DEPTH:
        return
    cursor.execute("SELECT referred_by FROM users WHERE user_id = ?", (user_id,))
    ref = cursor.fetchone()
    if ref and ref[0]:
        bonus_perc = REF_BONUS_PERCENTAGES[level-1]
        bonus = int(amount * bonus_perc)
        cursor.execute(
            "INSERT INTO sales (user_id, amount, tx_hash) VALUES (?, ?, ?)",
            (ref[0], bonus, f"bonus_ref_level{level}_{user_id}_{uuid.uuid4().hex[:8]}")
        )
        cursor.execute("UPDATE points SET batrapoints = batrapoints + ?, token_balance = token_balance + ? WHERE user_id = ?",
                      (bonus, bonus // 2, ref[0]))
        conn.commit()
        award_multi_level_referral(ref[0], amount, level + 1)

def update_energy(user_id):
    cursor.execute("SELECT energy, max_energy, last_energy_update FROM points WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        return 0, MAX_ENERGY_BASE
    energy, max_energy, last_update_str = row
    if last_update_str:
        last_update = datetime.fromisoformat(last_update_str)
        minutes_passed = (datetime.now() - last_update).total_seconds() / 60
        cursor.execute("SELECT energy_regen_level FROM upgrades WHERE user_id = ?", (user_id,))
        regen_level = cursor.fetchone()[0] or 0
        regen_rate = ENERGY_REGEN_RATE + regen_level
        add_energy = int(minutes_passed * regen_rate)
        new_energy = min(energy + add_energy, max_energy)
    else:
        new_energy = max_energy
    cursor.execute("UPDATE points SET energy = ?, last_energy_update = ? WHERE user_id = ?",
                   (new_energy, datetime.now().isoformat(), user_id))
    conn.commit()
    return new_energy, max_energy

def get_bonuses(user_id):
    gain_multi = 1.0
    energy_bonus = 0
    rare_chance_multi = 1.0
    multi_tap_bonus = 0
    cursor.execute("SELECT item_name FROM rare_items WHERE user_id = ?", (user_id,))
    items = cursor.fetchall()
    for item in items:
        item_name = item[0]
        if "Golden Frog" in item_name:
            gain_multi += 0.15
        if "Leaping Token" in item_name:
            energy_bonus += 300
        if "Magic Lily" in item_name:
            rare_chance_multi *= 2.5
        if "Epic Sword" in item_name:
            multi_tap_bonus += 2
        if "Rocket Frog" in item_name:
            gain_multi += 0.75
        if "Space Helmet" in item_name:
            energy_bonus += 750
    if GLOBAL_EVENT_ACTIVE and datetime.now() < GLOBAL_EVENT_END:
        gain_multi *= GLOBAL_EVENT_MULTI
    cursor.execute("SELECT galaxy_conquer_level FROM upgrades WHERE user_id = ?", (user_id,))
    galaxy_level = cursor.fetchone()[0] or 0
    gain_multi += galaxy_level * 0.3
    return gain_multi, energy_bonus, rare_chance_multi, multi_tap_bonus

def check_achievements(user_id):
    cursor.execute("SELECT tap_count, batrapoints, token_balance, star_battle_wins FROM points WHERE user_id = ?", (user_id,))
    tap_count, points, tokens, wins = cursor.fetchone()
    cursor.execute("SELECT COUNT(*) FROM users WHERE referred_by = ?", (user_id,))
    ref_count = cursor.fetchone()[0]
    
    achievements = []
    if tap_count >= 1000 and not cursor.execute("SELECT 1 FROM achievements WHERE user_id = ? AND achievement_name = ?", (user_id, "Master Tapper")).fetchone():
        achievements.append(("Master Tapper", 500, 100))
    if points >= 10000 and not cursor.execute("SELECT 1 FROM achievements WHERE user_id = ? AND achievement_name = ?", (user_id, "Point Lord")).fetchone():
        achievements.append(("Point Lord", 1000, 200))
    if ref_count >= 10 and not cursor.execute("SELECT 1 FROM achievements WHERE user_id = ? AND achievement_name = ?", (user_id, "Referral King")).fetchone():
        achievements.append(("Referral King", 750, 150))
    if tokens >= 1000 and not cursor.execute("SELECT 1 FROM achievements WHERE user_id = ? AND achievement_name = ?", (user_id, "Token Emperor")).fetchone():
        achievements.append(("Token Emperor", 2000, 500))
    if wins >= 5 and not cursor.execute("SELECT 1 FROM achievements WHERE user_id = ? AND achievement_name = ?", (user_id, "Star Conqueror")).fetchone():
        achievements.append(("Star Conqueror", 1500, 300))
    
    for name, point_reward, token_reward in achievements:
        cursor.execute("INSERT INTO achievements (user_id, achievement_name) VALUES (?, ?)", (user_id, name))
        cursor.execute("UPDATE points SET batrapoints = batrapoints + ?, token_balance = token_balance + ? WHERE user_id = ?", (point_reward, token_reward, user_id))
        conn.commit()
        return f"🏆 **Achievement Unlocked: {name}!** +{point_reward} BatraPoints + {token_reward} Tokens! 🌟"
    return None

async def check_airdrop(user_id):
    cursor.execute("SELECT batrapoints, token_balance, last_airdrop FROM points p LEFT JOIN airdrops a ON p.user_id = a.user_id WHERE p.user_id = ?", (user_id,))
    points, tokens, last_airdrop = cursor.fetchone()
    if last_airdrop:
        last_airdrop = datetime.fromisoformat(last_airdrop)
        if (datetime.now() - last_airdrop).days < 7:
            return None
    if points >= AIRDROP_THRESHOLD or tokens >= AIRDROP_THRESHOLD // 10:
        reward = random.randint(50, 200)
        cursor.execute("UPDATE points SET token_balance = token_balance + ? WHERE user_id = ?", (reward, user_id))
        cursor.execute("INSERT OR REPLACE INTO airdrops (user_id, last_airdrop) VALUES (?, ?)", (user_id, datetime.now().isoformat()))
        conn.commit()
        return f"🌠 **Cosmic Airdrop Landed!** +{reward} Batrachien Tokens! 🚀"
    return None

async def update_stake(user_id):
    cursor.execute("SELECT staked_tokens, stake_start FROM points WHERE user_id = ?", (user_id,))
    staked, stake_start = cursor.fetchone()
    if not staked or not stake_start:
        return
    stake_time = datetime.fromisoformat(stake_start)
    hours_passed = (datetime.now() - stake_time).total_seconds() / 3600
    if hours_passed < 1:
        return
    reward = int(staked * 0.05 * hours_passed)
    token_reward = int(staked * 0.01 * hours_passed)
    cursor.execute("UPDATE points SET batrapoints = batrapoints + ?, token_balance = token_balance + ?, stake_start = ? WHERE user_id = ?",
                   (reward, token_reward, datetime.now().isoformat(), user_id))
    conn.commit()

async def update_passive(user_id):
    cursor.execute("SELECT batrapoints, token_balance, last_passive_update, auto_tap_level, galaxy_conquer_level FROM points p JOIN upgrades u ON p.user_id = u.user_id WHERE p.user_id = ?", (user_id,))
    row = cursor.fetchone()
    if not row or (row[3] == 0 and row[4] == 0):
        return
    batrapoints, token_balance, last_update_str, auto_level, galaxy_level = row
    if last_update_str:
        last_update = datetime.fromisoformat(last_update_str)
        minutes_passed = (datetime.now() - last_update).total_seconds() / 60
        multi = GLOBAL_EVENT_MULTI if GLOBAL_EVENT_ACTIVE and datetime.now() < GLOBAL_EVENT_END else 1.0
        point_gain = int(minutes_passed * auto_level * multi)
        token_gain = int(minutes_passed * galaxy_level * 0.1 * multi)
        cursor.execute("UPDATE points SET batrapoints = batrapoints + ?, token_balance = token_balance + ?, last_passive_update = ? WHERE user_id = ?",
                       (point_gain, token_gain, datetime.now().isoformat(), user_id))
        conn.commit()

# ------------------- START HANDLER -------------------
@dp.message(Command("start"))
async def start(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    referred_by = None
    if message.text and len(message.text.split()) > 1:
        ref_code = message.text.split()[1]
        if ref_code.startswith("bat_"):
            try:
                referred_by = int(ref_code.split("_")[1])
                cursor.execute("SELECT 1 FROM users WHERE user_id = ?", (referred_by,))
                if not cursor.fetchone() or referred_by == user_id:
                    referred_by = None
            except ValueError:
                pass

    cursor.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user_id, username))
    cursor.execute("UPDATE users SET ref_code = ? WHERE user_id = ?", (generate_ref_code(user_id), user_id))
    if referred_by:
        cursor.execute("UPDATE users SET referred_by = ? WHERE user_id = ?", (referred_by, user_id))
    conn.commit()

    cursor.execute("INSERT OR IGNORE INTO points (user_id, batrapoints, token_balance, energy, max_energy, last_energy_update, last_passive_update, tap_count, star_battle_wins, staked_tokens) VALUES (?,0,0,1000,1000,?,?,0,0,0)",
                   (user_id, datetime.now().isoformat(), datetime.now().isoformat()))
    cursor.execute("INSERT OR IGNORE INTO levels (user_id, level, title) VALUES (?,1,?)", (user_id, get_title(1)))
    cursor.execute("INSERT OR IGNORE INTO upgrades (user_id) VALUES (?)", (user_id,))
    conn.commit()

    welcome_text = (
        f"{FROG_ART}\n"
        f"**Batrachien Presale LIVE** 🔥\n"
        f"🐸💎 **Welcome to the Galactic Batrachien Cosmos!** 💎🐸\n"
        f"{get_countdown()}\n\n"
        f"✨ **Tap, Build, Conquer the Stars! Outshine the Universe!** ✨\n"
        f"Launch your cosmic journey:"
    )

    kb = InlineKeyboardBuilder()
    kb.button(text="🎮 Play & Farm", web_app=types.WebAppInfo(url='https://batrachien-game.vercel.app'))  # Vercel URL'sini buraya koy
    kb.button(text="🚀 Buy Tokens", callback_data="buy")
    kb.button(text="📈 Stats & Progress", callback_data="stats")
    kb.button(text="🔗 Referral Empire", callback_data="ref")
    kb.button(text="🪙 Coin Lore", callback_data="coin_info")
    kb.button(text="🟦 Join X Frog Armada", url=X_LINK)
    kb.adjust(2)
    await message.answer(welcome_text, reply_markup=kb.as_markup(), parse_mode="Markdown")
    airdrop_msg = await check_airdrop(user_id)
    if airdrop_msg:
        await message.answer(airdrop_msg, parse_mode="Markdown")

# ------------------- MINI APP ENTEGRASYONU -------------------
@dp.message(F.web_app_data)
async def handle_mini_app_data(message: types.Message):
    user_id = message.from_user.id
    try:
        data = json.loads(message.web_app_data.data)
        action = data.get('action')
        
        if action == 'hop':
            energy, max_energy = update_energy(user_id)
            await update_passive(user_id)
            await update_stake(user_id)
            gain_multi, energy_bonus, rare_chance_multi, multi_tap_bonus = get_bonuses(user_id)
            max_energy += energy_bonus
            energy = min(energy, max_energy)
            if energy < 1:
                await message.answer("⚠️ **Energy Core Depleted!** Regen or power up! 🚀", parse_mode="Markdown")
                return

            cursor.execute("SELECT active_until FROM boosts WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            now = datetime.now()
            temp_bonus = 2 if row and datetime.fromisoformat(row[0]) > now else 1

            cursor.execute("SELECT multi_tap_level FROM upgrades WHERE user_id = ?", (user_id,))
            multi_tap = 1 + cursor.fetchone()[0] + multi_tap_bonus

            total_gain = int(temp_bonus * multi_tap * gain_multi)
            cursor.execute("UPDATE points SET energy = energy - 1, batrapoints = batrapoints + ?, tap_count = tap_count + 1 WHERE user_id = ?",
                          (total_gain, user_id))
            
            if random.randint(1, 100) <= SUPER_RARE_CHANCE * rare_chance_multi:
                item = random.choice(["Golden Frog (+15% gain)", "Leaping Token (+300 energy)", "Magic Lily (x2.5 rare chance)", "Epic Sword (+2 multi-tap)", "Rocket Frog (+75% gain)", "Space Helmet (+750 energy)"])
                cursor.execute("INSERT OR IGNORE INTO rare_items (user_id, item_name) VALUES (?, ?)", (user_id, item))
                conn.commit()
                await message.answer(f"✨ **Super Rare Artifact Found!** {item}! 🌟", parse_mode="Markdown")
            
            cursor.execute("SELECT level FROM levels WHERE user_id = ?", (user_id,))
            level = cursor.fetchone()[0]
            batrapoints = cursor.execute("SELECT batrapoints FROM points WHERE user_id = ?", (user_id,)).fetchone()[0]
            if batrapoints >= level * 1000:
                level += 1
                cursor.execute("UPDATE levels SET level = ?, title = ? WHERE user_id = ?", (level, get_title(level), user_id))
                await message.answer(f"🌌 **Level Up!** You are now a {get_title(level)} (Level {level})! 🏆", parse_mode="Markdown")
            
            conn.commit()
            ach_msg = await check_achievements(user_id)
            airdrop_msg = await check_airdrop(user_id)
            text = f"🐸 **Galactic Leap!** +{total_gain} BatraPoints 🚀\nEnergy: {energy}/{max_energy}"
            if ach_msg:
                text += f"\n{ach_msg}"
            if airdrop_msg:
                text += f"\n{airdrop_msg}"
            await message.answer(text, parse_mode="Markdown")

        elif action == 'boost':
            cursor.execute("SELECT token_balance, active_until FROM points p LEFT JOIN boosts b ON p.user_id = b.user_id WHERE p.user_id = ?", (user_id,))
            row = cursor.fetchone()
            tokens, active_until = row
            if active_until and datetime.fromisoformat(active_until) > datetime.now():
                await message.answer("⚠️ **Boost Already Active!** Wait for cooldown! ⏳", parse_mode="Markdown")
                return
            if tokens < 50:
                await message.answer("⚠️ **Need 50 Tokens for Hyperdrive Boost!** 💎", parse_mode="Markdown")
                return
            cursor.execute("UPDATE points SET token_balance = token_balance - 50 WHERE user_id = ?", (user_id,))
            cursor.execute("INSERT OR REPLACE INTO boosts (user_id, active_until) VALUES (?, ?)",
                          (user_id, (datetime.now() + timedelta(minutes=15)).isoformat()))
            conn.commit()
            airdrop_msg = await check_airdrop(user_id)
            text = "⚡ **Hyperdrive Boost Activated!** +2 points/hop for 15 min! 🚀"
            if airdrop_msg:
                text += f"\n{airdrop_msg}"
            await message.answer(text, parse_mode="Markdown")

        elif action == 'daily':
            cursor.execute("SELECT last_daily_claim FROM points WHERE user_id = ?", (user_id,))
            last_claim = cursor.fetchone()[0]
            now = datetime.now()
            if last_claim and (now - datetime.fromisoformat(last_claim)).days < 1:
                await message.answer("⚠️ **Daily Reward Already Claimed!** Come back tomorrow! ⏳", parse_mode="Markdown")
                return
            cursor.execute("UPDATE points SET batrapoints = batrapoints + ?, last_daily_claim = ? WHERE user_id = ?",
                          (DAILY_REWARD, now.isoformat(), user_id))
            conn.commit()
            airdrop_msg = await check_airdrop(user_id)
            text = f"📅 **Daily Cosmic Cache!** +{DAILY_REWARD} BatraPoints! 🌟"
            if airdrop_msg:
                text += f"\n{airdrop_msg}"
            await message.answer(text, parse_mode="Markdown")

        elif action == 'spin':
            cursor.execute("SELECT last_spin FROM points WHERE user_id = ?", (user_id,))
            last_spin = cursor.fetchone()[0]
            now = datetime.now()
            if last_spin and (now - datetime.fromisoformat(last_spin)).total_seconds() < 3600:
                await message.answer("⚠️ **Galaxy Wheel on Cooldown!** Try again in 1 hour! ⏳", parse_mode="Markdown")
                return
            cursor.execute("SELECT token_balance FROM points WHERE user_id = ?", (user_id,))
            tokens = cursor.fetchone()[0] or 0
            if tokens < 10:
                await message.answer("⚠️ **Need 10 Tokens to Spin Galaxy Wheel!** 💎", parse_mode="Markdown")
                return
            cursor.execute("UPDATE points SET token_balance = token_balance - 10 WHERE user_id = ?", (user_id,))
            _, _, rare_chance_multi, _ = get_bonuses(user_id)
            reward = random.choice(SPIN_REWARDS)
            msg = ""
            if reward.startswith("points_"):
                bonus = int(reward.split("_")[1])
                cursor.execute("UPDATE points SET batrapoints = batrapoints + ? WHERE user_id = ?", (bonus, user_id))
                msg = f"💰 **Jackpot! +{bonus} BatraPoints!**"
            elif reward == "energy_refill":
                cursor.execute("UPDATE points SET energy = max_energy WHERE user_id = ?", (user_id,))
                msg = "⚡ **Full Energy Core Recharge!**"
            elif reward == "rare_item":
                item = random.choice(["Golden Frog (+15% gain)", "Leaping Token (+300 energy)", "Magic Lily (x2.5 rare chance)", "Epic Sword (+2 multi-tap)", "Rocket Frog (+75% gain)", "Space Helmet (+750 energy)"])
                cursor.execute("INSERT OR IGNORE INTO rare_items (user_id, item_name) VALUES (?, ?)", (user_id, item))
                msg = f"✨ **Rare Artifact: {item}!**"
            elif reward == "free_boost":
                cursor.execute("INSERT OR REPLACE INTO boosts (user_id, active_until) VALUES (?, ?)",
                              (user_id, (datetime.now() + timedelta(minutes=15)).isoformat()))
                msg = "⚡ **Free Hyperdrive Boost!**"
            elif reward == "jackpot_1000":
                bonus = 1000
                cursor.execute("UPDATE points SET batrapoints = batrapoints + ? WHERE user_id = ?", (bonus, user_id))
                msg = f"🌌 **Mega Jackpot! +{bonus} BatraPoints!**"
            elif reward == "token_bonus_100":
                bonus = 100
                cursor.execute("UPDATE points SET token_balance = token_balance + ? WHERE user_id = ?", (bonus, user_id))
                msg = f"💎 **Token Meteor! +{bonus} Tokens!**"
            cursor.execute("UPDATE points SET last_spin = ? WHERE user_id = ?", (now.isoformat(), user_id))
            conn.commit()
            airdrop_msg = await check_airdrop(user_id)
            text = f"🎡 **Galaxy Wheel Spun!** Reward: {msg}"
            if airdrop_msg:
                text += f"\n{airdrop_msg}"
            await message.answer(text, parse_mode="Markdown")

        elif action == 'shop':
            cursor.execute("SELECT multi_tap_level, energy_regen_level, max_energy_level, auto_tap_level, galaxy_conquer_level FROM upgrades WHERE user_id = ?", (user_id,))
            levels = cursor.fetchone() or (0, 0, 0, 0, 0)
            cursor.execute("SELECT token_balance FROM points WHERE user_id = ?", (user_id,))
            tokens = cursor.fetchone()[0] or 0
            text = (
                f"🛒 **Intergalactic Token Forge** 🛒\n"
                f"**Your Tokens:** {tokens:,}\n\n"
                f"1. **Multi-Tap** (Lvl {levels[0]}): +1 gain/hop. Cost: {50 + levels[0]*20} tokens\n"
                f"2. **Energy Regen** (Lvl {levels[1]}): +1 regen/min. Cost: {100 + levels[1]*50} tokens\n"
                f"3. **Max Energy** (Lvl {levels[2]}): +500 max. Cost: {200 + levels[2]*100} tokens\n"
                f"4. **Auto-Tap** (Lvl {levels[3]}): +1 pt/min passive. Cost: {300 + levels[3]*150} tokens\n"
                f"5. **Galaxy Conquer** (Lvl {levels[4]}): +30% gain & 0.1 token/min. Cost: {500 + levels[4]*250} tokens"
            )
            kb = InlineKeyboardBuilder()
            kb.button(text="1️⃣ Multi-Tap", web_app=types.WebAppInfo(url='https://batrachien-game.vercel.app?upgrade=multi'))
            kb.button(text="2️⃣ Energy Regen", web_app=types.WebAppInfo(url='https://batrachien-game.vercel.app?upgrade=regen'))
            kb.button(text="3️⃣ Max Energy", web_app=types.WebAppInfo(url='https://batrachien-game.vercel.app?upgrade=max'))
            kb.button(text="4️⃣ Auto-Tap", web_app=types.WebAppInfo(url='https://batrachien-game.vercel.app?upgrade=auto'))
            kb.button(text="5️⃣ Galaxy Conquer", web_app=types.WebAppInfo(url='https://batrachien-game.vercel.app?upgrade=galaxy'))
            kb.adjust(2)
            await message.answer(text, reply_markup=kb.as_markup(), parse_mode="Markdown")

        elif action.startswith('upgrade_'):
            upgrade_type = action.split('_')[1]
            cursor.execute("SELECT token_balance FROM points WHERE user_id = ?", (user_id,))
            tokens = cursor.fetchone()[0] or 0
            cursor.execute(f"SELECT {upgrade_type}_level FROM upgrades WHERE user_id = ?", (user_id,))
            level = cursor.fetchone()[0] or 0

            if upgrade_type == "multi":
                cost = 50 + level * 20
                field = "multi_tap_level"
            elif upgrade_type == "regen":
                cost = 100 + level * 50
                field = "energy_regen_level"
            elif upgrade_type == "max":
                cost = 200 + level * 100
                field = "max_energy_level"
                if tokens >= cost:
                    new_max = MAX_ENERGY_BASE + (level + 1) * 500
                    cursor.execute("UPDATE points SET max_energy = ? WHERE user_id = ?", (new_max, user_id))
            elif upgrade_type == "auto":
                cost = 300 + level * 150
                field = "auto_tap_level"
            elif upgrade_type == "galaxy":
                cost = 500 + level * 250
                field = "galaxy_conquer_level"

            if tokens >= cost:
                cursor.execute(f"UPDATE upgrades SET {field} = {field} + 1 WHERE user_id = ?", (user_id,))
                cursor.execute("UPDATE points SET token_balance = token_balance - ? WHERE user_id = ?", (cost, user_id))
                conn.commit()
                airdrop_msg = await check_airdrop(user_id)
                text = f"🚀 **Cosmic Upgrade Forged!** {upgrade_type.capitalize()} now Lvl {level + 1}! 🌟"
                if airdrop_msg:
                    text += f"\n{airdrop_msg}"
                await message.answer(text, parse_mode="Markdown")
            else:
                await message.answer(f"⚠️ **Insufficient Tokens!** Need {cost} tokens 💎", parse_mode="Markdown")

        elif action == 'star_battle':
            cursor.execute("SELECT token_balance, star_battle_wins FROM points WHERE user_id = ?", (user_id,))
            tokens, wins = cursor.fetchone()
            cost = 20
            if tokens < cost:
                await message.answer(f"⚠️ **Need {cost} Tokens to Enter Star Battle!** 💎", parse_mode="Markdown")
                return
            cursor.execute("UPDATE points SET token_balance = token_balance - ? WHERE user_id = ?", (cost, user_id))
            win_chance = min(50 + wins * 2, 80)
            if random.randint(1, 100) <= win_chance:
                reward = random.randint(100, 500)
                token_reward = reward // 5
                cursor.execute("UPDATE points SET batrapoints = batrapoints + ?, token_balance = token_balance + ?, star_battle_wins = star_battle_wins + 1 WHERE user_id = ?",
                              (reward, token_reward, user_id))
                msg = f"⚔️ **Star Battle Triumph!** +{reward} BatraPoints + {token_reward} Tokens! 🏆"
            else:
                msg = "⚔️ **Star Battle Defeat!** Sharpen your cosmic blades! 💪"
            conn.commit()
            ach_msg = await check_achievements(user_id)
            airdrop_msg = await check_airdrop(user_id)
            text = msg
            if ach_msg:
                text += f"\n{ach_msg}"
            if airdrop_msg:
                text += f"\n{airdrop_msg}"
            await message.answer(text, parse_mode="Markdown")

        elif action == 'burn_tokens':
            amount = data.get('amount')
            if not amount or amount < 100:
                await message.answer("⚠️ **Minimum Burn: 100 Tokens!**", parse_mode="Markdown")
                return
            cursor.execute("SELECT token_balance FROM points WHERE user_id = ?", (user_id,))
            tokens = cursor.fetchone()[0] or 0
            if amount > tokens:
                await message.answer(f"⚠️ **Insufficient Tokens!** You have {tokens:,} tokens.", parse_mode="Markdown")
                return
            points_gain = amount * 5
            cursor.execute("UPDATE points SET token_balance = token_balance - ?, batrapoints = batrapoints + ? WHERE user_id = ?",
                          (amount, points_gain, user_id))
            cursor.execute("INSERT OR REPLACE INTO boosts (user_id, active_until) VALUES (?, ?)",
                          (user_id, (datetime.now() + timedelta(hours=1)).isoformat()))
            conn.commit()
            airdrop_msg = await check_airdrop(user_id)
            text = f"🔥 **Tokens Vaporized!** {amount:,} tokens burned for +{points_gain:,} BatraPoints + 1h rare chance boost! 💥"
            if airdrop_msg:
                text += f"\n{airdrop_msg}"
            await message.answer(text, parse_mode="Markdown")

        elif action == 'stake_tokens':
            amount = data.get('amount')
            cursor.execute("SELECT token_balance, staked_tokens FROM points WHERE user_id = ?", (user_id,))
            tokens, staked = cursor.fetchone()
            if amount == 0:
                if staked == 0:
                    await message.answer("⚠️ **No Tokens Staked!**", parse_mode="Markdown")
                    return
                await update_stake(user_id)
                cursor.execute("UPDATE points SET token_balance = token_balance + ?, staked_tokens = 0, stake_start = NULL WHERE user_id = ?",
                              (staked, user_id))
                conn.commit()
                await message.answer(f"💰 **Unstaked {staked:,} Tokens!** Back to your vault! 🚀", parse_mode="Markdown")
                return
            if amount < 100:
                await message.answer("⚠️ **Minimum Stake: 100 Tokens!**", parse_mode="Markdown")
                return
            if amount > tokens:
                await message.answer(f"⚠️ **Insufficient Tokens!** You have {tokens:,} tokens.", parse_mode="Markdown")
                return
            cursor.execute("UPDATE points SET token_balance = token_balance - ?, staked_tokens = staked_tokens + ?, stake_start = ? WHERE user_id = ?",
                          (amount, amount, datetime.now().isoformat(), user_id))
            conn.commit()
            airdrop_msg = await check_airdrop(user_id)
            text = f"💰 **{amount:,} Tokens Staked!** Earning 5% points, 1% tokens/hour! 🌟"
            if airdrop_msg:
                text += f"\n{airdrop_msg}"
            await message.answer(text, parse_mode="Markdown")

        elif action.startswith('mission_'):
            mission_idx = int(action.split('_')[1]) - 1
            missions = [
                ("Nebula Hunt", 50, 0.7, "100-300 points"),
                ("Starforge Raid", 100, 0.5, "200-600 points + rare item"),
                ("Black Hole Dive", 200, 0.3, "500-1000 points + 50-100 tokens")
            ]
            name, cost, success_chance, reward_desc = missions[mission_idx]
            cursor.execute("SELECT token_balance FROM points WHERE user_id = ?", (user_id,))
            tokens = cursor.fetchone()[0] or 0
            cursor.execute("SELECT completed_at FROM missions WHERE user_id = ? AND mission_name = ?", (user_id, name))
            last_completed = cursor.fetchone()
            if last_completed and (datetime.now() - datetime.fromisoformat(last_completed[0])).total_seconds() < 3600:
                await message.answer(f"⚠️ **{name} on Cooldown!** Try again in 1 hour! ⏳", parse_mode="Markdown")
                return
            if tokens < cost:
                await message.answer(f"⚠️ **Need {cost} Tokens for {name}!** 💎", parse_mode="Markdown")
                return
            cursor.execute("UPDATE points SET token_balance = token_balance - ? WHERE user_id = ?", (cost, user_id))
            if random.random() <= success_chance:
                if mission_idx == 0:
                    reward = random.randint(100, 300)
                    cursor.execute("UPDATE points SET batrapoints = batrapoints + ? WHERE user_id = ?", (reward, user_id))
                    msg = f"🌌 **{name} Success!** +{reward} BatraPoints! 🏆"
                elif mission_idx == 1:
                    reward = random.randint(200, 600)
                    item = random.choice(["Golden Frog (+15% gain)", "Leaping Token (+300 energy)", "Magic Lily (x2.5 rare chance)", "Epic Sword (+2 multi-tap)", "Rocket Frog (+75% gain)", "Space Helmet (+750 energy)"])
                    cursor.execute("UPDATE points SET batrapoints = batrapoints + ? WHERE user_id = ?", (reward, user_id))
                    cursor.execute("INSERT OR IGNORE INTO rare_items (user_id, item_name) VALUES (?, ?)", (user_id, item))
                    msg = f"🌌 **{name} Success!** +{reward} BatraPoints + {item}! 🏆"
                elif mission_idx == 2:
                    reward = random.randint(500, 1000)
                    token_reward = random.randint(50, 100)
                    cursor.execute("UPDATE points SET batrapoints = batrapoints + ?, token_balance = token_balance + ? WHERE user_id = ?", (reward, token_reward, user_id))
                    msg = f"🌌 **{name} Success!** +{reward} BatraPoints + {token_reward} Tokens! 🏆"
            else:
                msg = f"🌌 **{name} Failed!** The cosmos was unforgiving! 💪"
            cursor.execute("INSERT OR REPLACE INTO missions (user_id, mission_name, completed_at) VALUES (?, ?, ?)",
                          (user_id, name, datetime.now().isoformat()))
            conn.commit()
            airdrop_msg = await check_airdrop(user_id)
            text = msg
            if airdrop_msg:
                text += f"\n{airdrop_msg}"
            await message.answer(text, parse_mode="Markdown")

        else:
            await message.answer("⚠️ **Invalid Action!**", parse_mode="Markdown")
    except json.JSONDecodeError:
        await message.answer("⚠️ **Data Error!**", parse_mode="Markdown")

# ------------------- CALLBACKS -------------------
@dp.callback_query(F.data == "buy")
async def buy_callback(callback: types.CallbackQuery, state: FSMContext):
    if datetime.now() > END_DATE:
        await callback.message.answer("⚠️ **Presale Terminated!** The cosmic fleet has launched! 🌌")
        await callback.answer()
        return
    sold = get_sold_amount()
    if sold >= TOTAL_SUPPLY:
        await callback.message.answer("⚠️ **All Tokens Conquered!** Frog armada at max capacity! 🚀")
        await callback.answer()
        return
    await state.set_state(PresaleStates.amount)
    price = get_token_price()
    await callback.message.answer(
        f"💸 **Enter Batrachien Token Amount to Seize!**\n**Current Price:** {price:.2f} TON/token\n**Available:** {TOTAL_SUPPLY - sold} tokens",
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.callback_query(F.data == "stats")
async def stats_callback(callback: types.CallbackQuery):
    event_text = f"\n🌌 **Cosmic Event: x{GLOBAL_EVENT_MULTI}x points & tokens until {GLOBAL_EVENT_END.strftime('%H:%M UTC')}**" if GLOBAL_EVENT_ACTIVE and datetime.now() < GLOBAL_EVENT_END else ""
    kb = InlineKeyboardBuilder()
    kb.button(text="📊 Points Leaderboard", callback_data="leaderboard_points")
    kb.button(text="💎 Tokens Leaderboard", callback_data="leaderboard_tokens")
    kb.adjust(2)
    await callback.message.answer(get_stats() + event_text, reply_markup=kb.as_markup(), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.startswith("leaderboard_"))
async def leaderboard_callback(callback: types.CallbackQuery):
    type = callback.data.split("_")[1]
    leaderboard = get_leaderboard(type)
    kb = InlineKeyboardBuilder()
    kb.button(text="🔙 Back to Stats", callback_data="stats")
    await callback.message.edit_text(leaderboard, reply_markup=kb.as_markup(), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "ref")
async def ref_callback(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    cursor.execute("SELECT ref_code FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    ref_code = result[0] if result else generate_ref_code(user_id)
    bot_username = (await bot.get_me()).username
    link = f"https://t.me/{bot_username}?start={ref_code}"
    cursor.execute("SELECT COUNT(*) FROM users WHERE referred_by = ?", (user_id,))
    ref_count = cursor.fetchone()[0]
    kb = InlineKeyboardBuilder()
    kb.button(text="👑 Referral Leaderboard", callback_data="ref_leaderboard")
    await callback.message.answer(
        f"🔗 **Forge Your Cosmic Empire:** {link}\n💎 **Multi-level Rewards:** 10%/7%/5%/3%/1%\n🛸 **Your Armada:** {ref_count} cosmic frogs",
        reply_markup=kb.as_markup(), parse_mode="Markdown"
    )
    await callback.answer()

@dp.callback_query(F.data == "ref_leaderboard")
async def ref_leaderboard_callback(callback: types.CallbackQuery):
    leaderboard = get_ref_leaderboard()
    kb = InlineKeyboardBuilder()
    kb.button(text="🔙 Back to Referral", callback_data="ref")
    await callback.message.edit_text(leaderboard, reply_markup=kb.as_markup(), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "coin_info")
async def coin_info_callback(callback: types.CallbackQuery):
    text = (
        f"🐸 **Batrachien Galactic Chronicle** 🐸\n\n"
        f"💎 **Total Supply:** {TOTAL_SUPPLY:,}\n"
        f"💰 **Price:** {get_token_price():.2f} TON (Dynamic!)\n"
        f"🚀 **Presale Ends:** {END_DATE.strftime('%d %b %Y')}\n"
        f"📈 **Multi-level Referrals:** 10%/7%/5%/3%/1%\n"
        f"✨ **Tap-farm, build, battle, stake, and conquer!**\n"
        f"🌟 **{AIRDROP_THRESHOLD:,}+ points/tokens for cosmic airdrops!**"
    )
    await callback.message.answer(text, parse_mode="Markdown")
    await callback.answer()

# ------------------- INVENTORY -------------------
@dp.message(Command("inventory"))
async def inventory_command(message: types.Message):
    user_id = message.from_user.id
    cursor.execute("SELECT item_name FROM rare_items WHERE user_id = ?", (user_id,))
    items = cursor.fetchall()
    text = "🎁 **Cosmic Vault** 🎁\n" + "\n".join([f"💎 {i[0]}" for i in items]) if items else "No artifacts yet! Conquer the stars! 🚀"
    await message.answer(text, parse_mode="Markdown")

# ------------------- BUY PROCESS -------------------
@dp.message(StateFilter(PresaleStates.amount))
async def process_amount(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    try:
        amount = int(message.text)
        if amount <= 0:
            await message.answer("⚠️ **Positive Thrust Required!** Enter a valid amount. 🚀")
            return
        sold = get_sold_amount()
        remaining = TOTAL_SUPPLY - sold
        if amount > remaining:
            await message.answer(f"⚠️ **Only {remaining:,} Tokens Left!** Adjust your trajectory. 🚀")
            return
        cost = amount * get_token_price()
        tx_id = uuid.uuid4().hex
        pay_link = f"ton://transfer/{TON_WALLET}?amount={int(cost*1e9)}&text=Batrachien_{amount}_{user_id}_{tx_id}"

        cursor.execute("INSERT INTO pending_payments (user_id, amount, tx_timestamp, tx_id) VALUES (?, ?, ?, ?)",
                       (user_id, amount, datetime.now().isoformat(), tx_id))
        conn.commit()

        kb = InlineKeyboardBuilder()
        kb.button(text="💰 Pay with TON Keeper", url=pay_link)
        kb.button(text="❌ Cancel", callback_data="cancel_buy")
        kb.adjust(1)

        text = (
            f"🚀 **Secure {amount:,} Batrachien Tokens!** 🚀\n"
            f"**Cost:** {cost:.2f} TON\n"
            f"**Wallet:** `{TON_WALLET}`\n"
            f"**Memo:** `Batrachien_{amount}_{user_id}_{tx_id}`\n"
            f"Pay via TON Keeper or copy memo for manual transfer."
        )
        await message.answer(text, reply_markup=kb.as_markup(), parse_mode="Markdown")
        asyncio.create_task(check_payment(user_id, amount, tx_id))
        await state.clear()
    except ValueError:
        await message.answer("⚠️ **Invalid Coordinates!** Enter a valid number. 🚀")

@dp.callback_query(F.data == "cancel_buy")
async def cancel_buy_callback(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("❌ **Mission Aborted!** Return to base! 🌌", parse_mode="Markdown")
    await callback.answer()

# ------------------- PAYMENT CHECK -------------------
async def check_payment(user_id, amount, tx_id):
    delay = 5
    max_retries = 3
    for _ in range(60):
        cursor.execute("SELECT tx_timestamp FROM pending_payments WHERE user_id = ? AND amount = ? AND tx_id = ?", (user_id, amount, tx_id))
        row = cursor.fetchone()
        if not row:
            return
        for attempt in range(max_retries):
            try:
                url = f"https://toncenter.com/api/v2/getTransactions?address={TON_WALLET}&limit=20&api_key={TON_API_KEY}"
                response = requests.get(url, timeout=10)
                response.raise_for_status()
                data = response.json()
                for tx in data.get('result', []):
                    if tx['in_msg'].get('message') == f"Batrachien_{amount}_{user_id}_{tx_id}":
                        tx_hash = tx['transaction_id']['hash']
                        tx_value = int(tx['in_msg']['value']) / 1e9
                        if abs(tx_value - amount * get_token_price()) < 0.01:
                            cursor.execute("INSERT INTO sales (user_id, amount, tx_hash) VALUES (?, ?, ?)",
                                           (user_id, amount, tx_hash))
                            cursor.execute("UPDATE points SET token_balance = token_balance + ?, batrapoints = batrapoints + ? WHERE user_id = ?",
                                           (amount, amount // 5, user_id))
                            cursor.execute("DELETE FROM pending_payments WHERE user_id = ? AND amount = ? AND tx_id = ?", (user_id, amount, tx_id))
                            award_multi_level_referral(user_id, amount)
                            conn.commit()
                            airdrop_msg = await check_airdrop(user_id)
                            text = (
                                f"{FROG_ART}\n"
                                f"✅ **Token Acquisition Confirmed!** {amount:,} tokens + {amount // 5:,} bonus BatraPoints added! 🎉\n"
                                f"{get_stats()}"
                            )
                            if airdrop_msg:
                                text += f"\n{airdrop_msg}"
                            await bot.send_message(user_id, text, parse_mode="Markdown")
                            return
                break
            except requests.exceptions.RequestException as e:
                logging.error(f"Payment check error (attempt {attempt+1}/{max_retries}): {e}")
                delay = min(delay * 2, 60)
                if attempt < max_retries - 1:
                    await asyncio.sleep(delay)
                continue
        await asyncio.sleep(delay)
    cursor.execute("DELETE FROM pending_payments WHERE user_id = ? AND amount = ? AND tx_id = ?", (user_id, amount, tx_id))
    conn.commit()
    await bot.send_message(user_id, "⚠️ **Payment Orbit Failed!** Retry your launch! 🚀", parse_mode="Markdown")

# ------------------- GLOBAL EVENT -------------------
async def manage_global_event():
    global GLOBAL_EVENT_ACTIVE, GLOBAL_EVENT_END, GLOBAL_EVENT_MULTI
    while True:
        if not GLOBAL_EVENT_ACTIVE and random.random() < 0.15:
            GLOBAL_EVENT_ACTIVE = True
            GLOBAL_EVENT_MULTI = random.choice([1.5, 2.0, 3.0, 5.0])
            GLOBAL_EVENT_END = datetime.now() + timedelta(hours=1)
            cursor.execute("SELECT user_id FROM users")
            for (user_id,) in cursor.fetchall():
                try:
                    await bot.send_message(user_id, f"🌌 **Cosmic Surge Alert!** x{GLOBAL_EVENT_MULTI}x points & tokens for 1 hour! 🚀", parse_mode="Markdown")
                except:
                    pass
        if GLOBAL_EVENT_ACTIVE and datetime.now() >= GLOBAL_EVENT_END:
            GLOBAL_EVENT_ACTIVE = False
            cursor.execute("SELECT user_id FROM users")
            for (user_id,) in cursor.fetchall():
                try:
                    await bot.send_message(user_id, f"🌌 **Cosmic Surge Ended!** Normal space resumed! 🪐", parse_mode="Markdown")
                except:
                    pass
        await asyncio.sleep(1800)

# ------------------- CLEANUP TASK -------------------
async def cleanup_expired():
    while True:
        now = datetime.now().isoformat()
        cursor.execute("DELETE FROM pending_payments WHERE tx_timestamp < ?", ((datetime.fromisoformat(now) - timedelta(minutes=5)).isoformat(),))
        cursor.execute("DELETE FROM boosts WHERE active_until < ?", (now,))
        cursor.execute("DELETE FROM missions WHERE completed_at < ?", ((datetime.fromisoformat(now) - timedelta(hours=24)).isoformat(),))
        conn.commit()
        await asyncio.sleep(300)

# ------------------- RUN -------------------
async def main():
    asyncio.create_task(cleanup_expired())
    asyncio.create_task(manage_global_event())
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())