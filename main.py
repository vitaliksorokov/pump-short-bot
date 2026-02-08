import json
import os
from dataclasses import dataclass, asdict
from typing import Dict, Any, List

from dotenv import load_dotenv
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_IDS_RAW = os.getenv("CHAT_IDS", "")
SETTINGS_PATH = os.path.join(os.path.dirname(__file__), "settings.json")

# ---- Модель настроек ----
@dataclass
class UserSettings:
    notifications: bool = True

    # Фильтры
    profile: str = "normal"  # conservative / normal / aggressive
    timeframe: str = "5m"    # 1m / 5m / 15m
    pump_pct: int = 10       # 5 / 10 / 20
    volume_bucket: str = "50k-200k"  # <50k / 50k-200k / >200k
    marketcap: str = ">10M"  # >10M / >50M / all
    coins_scope: str = "top100"  # top10 / top100 / all
    mode: str = "short"      # short / long / both


DEFAULT_SETTINGS = UserSettings()


# ---- Хранилище настроек в JSON ----
def _load_all_settings() -> Dict[str, Any]:
    if not os.path.exists(SETTINGS_PATH):
        return {}
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _save_all_settings(data: Dict[str, Any]) -> None:
    tmp_path = SETTINGS_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, SETTINGS_PATH)


def get_user_settings(user_id: int) -> UserSettings:
    all_data = _load_all_settings()
    raw = all_data.get(str(user_id), {})
    # Мягкое слияние с дефолтами (если полей нет)
    merged = asdict(DEFAULT_SETTINGS)
    if isinstance(raw, dict):
        merged.update(raw)
    return UserSettings(**merged)


def set_user_settings(user_id: int, new_settings: UserSettings) -> None:
    all_data = _load_all_settings()
    all_data[str(user_id)] = asdict(new_settings)
    _save_all_settings(all_data)


# ---- Вспомогательное: доступ (опционально) ----
def parse_chat_ids(raw: str) -> List[int]:
    ids = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.append(int(part))
        except ValueError:
            pass
    return ids


ALLOWED_CHAT_IDS = set(parse_chat_ids(CHAT_IDS_RAW))


def is_allowed(update: Update) -> bool:
    # Если CHAT_IDS не задан — считаем, что доступ открыт всем (для теста)
    if not ALLOWED_CHAT_IDS:
        return True
    chat_id = update.effective_chat.id if update.effective_chat else None
    return chat_id in ALLOWED_CHAT_IDS


# ---- Клавиатуры ----
def build_main_menu(s: UserSettings) -> InlineKeyboardMarkup:
    notif = "✅ Уведомления: ВКЛ" if s.notifications else "⛔ Уведомления: ВЫКЛ"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(notif, callback_data="toggle_notifications")],
        [
            InlineKeyboardButton(f"Профиль: {s.profile}", callback_data="menu_profile"),
            InlineKeyboardButton(f"TF: {s.timeframe}", callback_data="menu_timeframe"),
        ],
        [
            InlineKeyboardButton(f"Рост: >{s.pump_pct}%", callback_data="menu_pump"),
            InlineKeyboardButton(f"Объём: {s.volume_bucket}", callback_data="menu_volume"),
        ],
        [
            InlineKeyboardButton(f"Капа: {s.marketcap}", callback_data="menu_marketcap"),
            InlineKeyboardButton(f"Монеты: {s.coins_scope}", callback_data="menu_coins"),
        ],
        [
            InlineKeyboardButton(f"Режим: {s.mode}", callback_data="menu_mode"),
        ],
        [
            InlineKeyboardButton("📣 Тестовый сигнал", callback_data="test_signal"),
        ],
        [
            InlineKeyboardButton("🔄 Обновить экран", callback_data="refresh"),
            InlineKeyboardButton("♻️ Сброс", callback_data="reset"),
        ],
    ])


def build_submenu(title: str, items: List[tuple], back_cb: str = "back") -> InlineKeyboardMarkup:
    # items: [(label, callback_data), ...]
    rows = [[InlineKeyboardButton(label, callback_data=cb)] for label, cb in items]
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data=back_cb)])
    return InlineKeyboardMarkup(rows)


def status_text(s: UserSettings) -> str:
    return (
        "⚙️ Текущие настройки:\n"
        f"• Уведомления: {'ВКЛ' if s.notifications else 'ВЫКЛ'}\n"
        f"• Профиль: {s.profile}\n"
        f"• Таймфрейм: {s.timeframe}\n"
        f"• Рост: >{s.pump_pct}%\n"
        f"• Объём: {s.volume_bucket}\n"
        f"• Капитализация: {s.marketcap}\n"
        f"• Монеты: {s.coins_scope}\n"
        f"• Режим сигналов: {s.mode}\n"
    )
def build_test_signal_text(s: UserSettings) -> str:
    # Сделаем “как настоящий” сигнал
    # Сигнал будет зависеть от выбранного режима (short/long/both)
    direction = "SHORT" if s.mode in ("short", "both") else "LONG"

    # Подставим условные цифры “пампа”
    tf = s.timeframe
    pump = s.pump_pct
    vol = s.volume_bucket
    mc = s.marketcap
    coins = s.coins_scope
    profile = s.profile

    confidence = "HIGH" if profile == "conservative" else ("MEDIUM" if profile == "normal" else "LOW")

    reasons = [
        f"рост {pump + 7}% за {tf}",
        f"объём {('~120k' if vol == '50k-200k' else ('~30k' if vol == '<50k' else '~450k'))}",
        "верхний фитиль на свече (пример)",
        "объём начал снижаться (пример)",
        "подтверждение 1 свечой (пример)",
    ]

    text = (
        "🚨 *TEST SIGNAL*\n"
        f"*COIN:* TESTCOIN/USDT\n"
        f"*Direction:* {direction}\n"
        f"*Timeframe:* {tf}\n"
        f"*Confidence:* {confidence}\n\n"
        f"*Filters:* profile={profile}, coins={coins}, mcap={mc}, vol={vol}, pump=>{pump}%\n\n"
        "*Reasons:*\n"
        + "\n".join([f"• {r}" for r in reasons])
        + "\n\n"
        "_Это тестовое сообщение. Реальные сигналы подключим после добавления сканера бирж._"
    )
    return text

# ---- Хендлеры ----
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return

    user_id = update.effective_user.id
    s = get_user_settings(user_id)
    text = "🤖 Панель управления ботом.\n\n" + status_text(s)
    await update.message.reply_text(text, reply_markup=build_main_menu(s))


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return

    user_id = update.effective_user.id
    s = get_user_settings(user_id)
    await update.message.reply_text("📌 " + status_text(s), reply_markup=build_main_menu(s))


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return

    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    s = get_user_settings(user_id)
    data = query.data

    # --- навигация ---
    if data == "refresh":
        await query.edit_message_text("🤖 Панель управления ботом.\n\n" + status_text(s), reply_markup=build_main_menu(s))
        return

    if data == "back":
        await query.edit_message_text("🤖 Панель управления ботом.\n\n" + status_text(s), reply_markup=build_main_menu(s))
        return

    if data == "reset":
        s = DEFAULT_SETTINGS
        set_user_settings(user_id, s)
        await query.edit_message_text("♻️ Сброшено к настройкам по умолчанию.\n\n" + status_text(s), reply_markup=build_main_menu(s))
        return

    if data == "toggle_notifications":
        s.notifications = not s.notifications
        set_user_settings(user_id, s)
        await query.edit_message_text("🤖 Панель управления ботом.\n\n" + status_text(s), reply_markup=build_main_menu(s))
        return

    if data == "test_signal":
        # Отправим отдельным сообщением тестовый сигнал
        text = build_test_signal_text(s)
        await query.message.reply_text(text, parse_mode="Markdown")
        # И вернём пользователя в меню (обновим экран)
        await query.edit_message_text("🤖 Панель управления ботом.\n\n" + status_text(s), reply_markup=build_main_menu(s))
        return

    # --- подменю ---
    if data == "menu_profile":
        kb = build_submenu("Профиль", [
            ("🟢 conservative", "set_profile:conservative"),
            ("🟡 normal", "set_profile:normal"),
            ("🔴 aggressive", "set_profile:aggressive"),
        ])
        await query.edit_message_text("Выбери профиль:", reply_markup=kb)
        return

    if data == "menu_timeframe":
        kb = build_submenu("TF", [
            ("1m", "set_tf:1m"),
            ("5m", "set_tf:5m"),
            ("15m", "set_tf:15m"),
        ])
        await query.edit_message_text("Выбери таймфрейм:", reply_markup=kb)
        return

    if data == "menu_pump":
        kb = build_submenu("Рост %", [
            (">5%", "set_pump:5"),
            (">10%", "set_pump:10"),
            (">20%", "set_pump:20"),
        ])
        await query.edit_message_text("Выбери порог роста:", reply_markup=kb)
        return

    if data == "menu_volume":
        kb = build_submenu("Объём", [
            ("<50k", "set_vol:<50k"),
            ("50k-200k", "set_vol:50k-200k"),
            (">200k", "set_vol:>200k"),
        ])
        await query.edit_message_text("Выбери фильтр объёма:", reply_markup=kb)
        return

    if data == "menu_marketcap":
        kb = build_submenu("Капитализация", [
            (">10M", "set_mc:>10M"),
            (">50M", "set_mc:>50M"),
            ("all", "set_mc:all"),
        ])
        await query.edit_message_text("Выбери фильтр капитализации:", reply_markup=kb)
        return

    if data == "menu_coins":
        kb = build_submenu("Список монет", [
            ("top10", "set_coins:top10"),
            ("top100", "set_coins:top100"),
            ("all", "set_coins:all"),
        ])
        await query.edit_message_text("Выбери список монет:", reply_markup=kb)
        return

    if data == "menu_mode":
        kb = build_submenu("Режим сигналов", [
            ("short", "set_mode:short"),
            ("long", "set_mode:long"),
            ("both", "set_mode:both"),
        ])
        await query.edit_message_text("Выбери режим сигналов:", reply_markup=kb)
        return

    # --- установка значений ---
    if data.startswith("set_profile:"):
        s.profile = data.split(":", 1)[1]
    elif data.startswith("set_tf:"):
        s.timeframe = data.split(":", 1)[1]
    elif data.startswith("set_pump:"):
        s.pump_pct = int(data.split(":", 1)[1])
    elif data.startswith("set_vol:"):
        s.volume_bucket = data.split(":", 1)[1]
    elif data.startswith("set_mc:"):
        s.marketcap = data.split(":", 1)[1]
    elif data.startswith("set_coins:"):
        s.coins_scope = data.split(":", 1)[1]
    elif data.startswith("set_mode:"):
        s.mode = data.split(":", 1)[1]
    else:
        # неизвестная кнопка — вернёмся в меню
        await query.edit_message_text("🤖 Панель управления ботом.\n\n" + status_text(s), reply_markup=build_main_menu(s))
        return

    set_user_settings(user_id, s)
    await query.edit_message_text("✅ Сохранено.\n\n" + status_text(s), reply_markup=build_main_menu(s))


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN не найден. Проверь файл .env")

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.run_polling()


if __name__ == "__main__":
    main()
