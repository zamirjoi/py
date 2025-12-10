import random
import logging
import os
import json
import uuid
from typing import Set, Tuple, Optional

try:
    from telegram import (
        Update,
        InlineKeyboardMarkup,
        InlineKeyboardButton,
    )
    from telegram.ext import (
        ApplicationBuilder,
        CommandHandler,
        ContextTypes,
        CallbackQueryHandler,
    )
except ModuleNotFoundError as e:  # clearer error if dependency is missing
    raise ImportError(
        "The 'python-telegram-bot' package is required to run this bot. "
        "Install it with: pip install python-telegram-bot==21.4"
    ) from e


# ========== CONFIGURE THIS ==========
BOT_TOKEN = "8560372760:AAG9RBtfqRR0gtOuFruEPFk7Zt42RLUqxXM"
DOMAIN = "gmail.com"

# Telegram numeric IDs
VERIFIER_IDS = [7549804367]
OWNER_IDS = [8121258275]

OWNER_CONTACT = "@Zamir_XP"
CREDIT_PER_CONFIRMED = 0.07
WITHDRAW_THRESHOLD = 1.0
# ====================================

SUGGESTED_FILE = "suggested_emails.txt"
PENDING_FILE = "pending_gmails.txt"
CONFIRMED_FILE = "confirmed_gmails.txt"
FAILED_FILE = "failed_gmails.txt"
CREDITS_FILE = "user_credits.json"
PASSWORD_FILE = "default_password.txt"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ----------------- Translation helper (auto Google via deep-translator) -----------------
# Install with: pip install deep-translator

def translate_text_safe(text: str, target_lang: str) -> str:
    """Translate text to target_lang using deep-translator's Google translator.
    If deep-translator is not installed or translation fails, return the original text.
    """
    try:
        from deep_translator import GoogleTranslator  # type: ignore
    except Exception:
        return text

    if not target_lang or target_lang.lower().startswith("en"):
        return text

    try:
        return GoogleTranslator(source='auto', target=target_lang).translate(text)
    except Exception:
        return text


# ----------------- File helpers -----------------

def load_email_set(path: str) -> Set[str]:
    """Return set of email(lower) from first column of a tab-separated file."""
    emails: Set[str] = set()
    if not os.path.exists(path):
        return emails
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split("	")
                emails.add(parts[0].lower())
    except OSError as e:
        logger.error("Error reading %s: %s", path, e)
    return emails


def get_default_password() -> str:
    """Read default password from file; create with a safe default if missing."""
    if os.path.exists(PASSWORD_FILE):
        try:
            with open(PASSWORD_FILE, "r", encoding="utf-8") as f:
                pwd = f.readline().strip()
                if pwd:
                    return pwd
        except OSError as e:
            logger.error("Error reading %s: %s", PASSWORD_FILE, e)

    pwd = "12345gmail"
    try:
        with open(PASSWORD_FILE, "w", encoding="utf-8") as f:
            f.write(pwd + "")
    except OSError as e:
        logger.error("Error writing %s: %s", PASSWORD_FILE, e)
    return pwd


def generate_unique_username(existing: Set[str]) -> str:
    prefixes = [
        "thor", "kratos", "freya", "mimir", "atreus", "beserkerking",
        "odin", "mulla", "molana", "thrud", "baulder", "feye"
    ]

    while True:
        prefix = random.choice(prefixes)
        u = f"{prefix}{uuid.uuid4().hex[:6]}"
        if u.lower() not in existing:
            return u


def is_verifier(uid: int) -> bool:
    return uid in VERIFIER_IDS


def is_owner_or_verifier(uid: int) -> bool:
    return uid in VERIFIER_IDS or uid in OWNER_IDS


def move_email_between_files(
    email: str,
    src: str,
    dst: str,
    status: Optional[str] = None,
) -> Tuple[bool, Optional[list]]:
    """Move a line by email from src to dst, optionally updating status=..."""
    if not os.path.exists(src):
        return False, None

    email_l = email.lower()
    moved = None
    keep_lines = []

    with open(src, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip("")
            parts = line.split("	")
            if parts and parts[0].lower() == email_l:
                moved = parts
            else:
                keep_lines.append(raw)

    if moved is None:
        return False, None

    if status is not None:
        moved = [x for x in moved if not x.startswith("status=")]
        moved.append(f"status={status}")

    with open(src, "w", encoding="utf-8") as f:
        f.writelines(keep_lines)

    with open(dst, "a", encoding="utf-8") as f:
        f.write("	".join(moved) + "")

    return True, moved


# ----------------- Credits helpers -----------------

def load_credits() -> dict:
    if not os.path.exists(CREDITS_FILE):
        return {}
    try:
        with open(CREDITS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.error("Error reading %s: %s", CREDITS_FILE, e)
        return {}


def save_credits(data: dict) -> None:
    try:
        with open(CREDITS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except OSError as e:
        logger.error("Error writing %s: %s", CREDITS_FILE, e)


def add_credit(uid: int, amt: float) -> float:
    credits = load_credits()
    key = str(uid)
    credits[key] = round(credits.get(key, 0.0) + amt, 6)
    save_credits(credits)
    return credits[key]


def get_balance(uid: int) -> float:
    return float(load_credits().get(str(uid), 0.0))


# ----------------- Bot commands -----------------

async def _send(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    *,
    markdown: bool = False,
    reply_markup=None,
) -> None:
    """Send message to user, auto-translating if possible using Google via deep-translator.

    The function detects the user's Telegram `language_code` (e.g. 'hi', 'bn') and
    translates the English `text` into that language. If translation isn't available
    it falls back to the original English text.
    """
    # Determine user's language
    user_lang = None
    try:
        user = update.effective_user
        if user is not None and getattr(user, "language_code", None):
            user_lang = user.language_code.split("-")[0]
    except Exception:
        user_lang = None

    # Translate only if user's language is present and not English
    out_text = text
    if user_lang and user_lang != "en":
        out_text = translate_text_safe(text, user_lang)

    chat = update.effective_chat
    if chat is None:
        return

    if markdown:
        await context.bot.send_message(chat_id=chat.id, text=out_text, parse_mode="Markdown", reply_markup=reply_markup)
    else:
        await context.bot.send_message(chat_id=chat.id, text=out_text, reply_markup=reply_markup)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user

    buttons = [
        [InlineKeyboardButton("🆕 New Gmail", callback_data="newgmail")],
        [InlineKeyboardButton("💾 Save Created", callback_data="savecreated")],
        [InlineKeyboardButton("💰 Balance", callback_data="balance")],
    ]

    if is_owner_or_verifier(user.id):
        buttons.append([
            InlineKeyboardButton("⏳ Pending", callback_data="listpending"),
            InlineKeyboardButton("✅ Confirmed", callback_data="listconfirmed"),
        ])
        buttons.append([
            InlineKeyboardButton("✔️ Approve", callback_data="verifypass"),
            InlineKeyboardButton("❌ Reject", callback_data="verifyfail"),
        ])

    keyboard = InlineKeyboardMarkup(buttons)
    pwd = get_default_password()

    text = (
        "👋 *Welcome!*"
        "Use the buttons below to manage Gmail workflow."
        f"🔑 Current Password: `{pwd}`"
    )

    await _send(update, context, text, markdown=True, reply_markup=keyboard)


async def newgmail_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user

    used = load_email_set(SUGGESTED_FILE) | load_email_set(PENDING_FILE) | load_email_set(CONFIRMED_FILE)
    usernames = {e.split("@")[0].lower() for e in used if "@" in e}

    email: Optional[str] = None
    username: Optional[str] = None

    for _ in range(200):
        u = generate_unique_username(usernames)
        candidate_email = f"{u}@{DOMAIN}"
        if candidate_email.lower() not in used:
            username = u
            email = candidate_email
            usernames.add(u.lower())
            break

    if username is None or email is None:
        await _send(update, context, "⚠️ Could not generate unique Gmail.")
        return

    password = get_default_password()

    try:
        with open(SUGGESTED_FILE, "a", encoding="utf-8") as f:
            f.write(f"{email}	by_user_id={user.id}	by_username={user.username}")
    except OSError as e:
        logger.error("Error writing %s: %s", SUGGESTED_FILE, e)

    await _send(
        update,
        context,
        (
            "🆕 *New Gmail Generated*"
            f"📧 `{email}`"
            f"🔑 `{password}`"
        ),
        markdown=True,
    )


async def savecreated_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) < 2:
        await _send(update, context, "Send: /savecreated email password")
        return

    email: Optional[str] = None
    pwd_parts = []

    for a in context.args:
        if "@" in a and email is None:
            email = a
        else:
            pwd_parts.append(a)

    if not email or not pwd_parts:
        await _send(update, context, "Invalid format. Use: /savecreated email password")
        return

    password = " ".join(pwd_parts)
    user = update.effective_user

    try:
        with open(PENDING_FILE, "a", encoding="utf-8") as f:
            f.write(
                f"{email}	password={password}	creator_id={user.id}	"
                f"creator_username={user.username}	status=pending"
            )
    except OSError as e:
        logger.error("Error writing %s: %s", PENDING_FILE, e)

    # 🔔 Notify all verifiers that a new email has been submitted
    creator_name = f"@{user.username}" if user.username else f"ID:{user.id}"
    notify_text = (
        "📥 *New Gmail submitted for verification*"
        f"📧 `{email}`"
        f"👤 Creator: {creator_name}"
        "Use /verifypass or /verifyfail to process it."
    )
    for vid in VERIFIER_IDS:
        try:
            await context.bot.send_message(
                chat_id=vid,
                text=notify_text,
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error("Failed to notify verifier %s: %s", vid, e)

    await _send(update, context, "✅ Saved for verification.")


async def verifypass_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not is_verifier(user.id):
        await _send(update, context, "⛔ You are not allowed to verify.")
        return

    if not context.args:
        await _send(update, context, "Usage: /verifypass email")
        return

    email = context.args[0]
    ok, fields = move_email_between_files(email, PENDING_FILE, CONFIRMED_FILE, "confirmed")

    if not ok or fields is None:
        await _send(update, context, "Not found in pending.")
        return

    creator_id: Optional[int] = None
    for f in fields:
        if f.startswith("creator_id="):
            try:
                creator_id = int(f.split("=", 1)[1])
            except ValueError:
                creator_id = None

    if creator_id is not None:
        new_balance = add_credit(creator_id, CREDIT_PER_CONFIRMED)
        logger.info("Credited %s to %s; new balance=%s", CREDIT_PER_CONFIRMED, creator_id, new_balance)

        # ✅ Notify the creator about approval & credit
        try:
            msg = (
                "✅ *Your Gmail has been verified!*"


                f"📧 Email: `{email}`"
                f"💰 Credit added: `${CREDIT_PER_CONFIRMED:.3f}`"
                f"🧾 New Balance: `${new_balance:.3f}`"
                "Thanks for your contribution!"
            )
            # Auto translate creator message using language code
            user_lang = None
            try:
                # We don't have update for the creator here; use Telegram user settings if available
                # context.bot.get_chat may be used but could be rate-limited; we instead rely on creator's language_code stored earlier in future improvements.
                pass
            except Exception:
                pass

            await context.bot.send_message(
                chat_id=creator_id,
                text=msg,
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error("Failed to notify creator %s: %s", creator_id, e)

    await _send(update, context, "✅ Approved")


async def verifyfail_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not is_verifier(user.id):
        await _send(update, context, "⛔ You are not allowed to verify.")
        return
    if not context.args:
        await _send(update, context, "Usage: /verifyfail email [reason]")
        return

    email = context.args[0]
    reason = " ".join(context.args[1:]) or "no_reason"

    ok, fields = move_email_between_files(email, PENDING_FILE, FAILED_FILE, f"failed:{reason}")
    if ok:
        # Notify creator about rejection if possible
        creator_id: Optional[int] = None
        for p in fields:
            if p.startswith("creator_id="):
                try:
                    creator_id = int(p.split("=", 1)[1])
                except Exception:
                    creator_id = None
        if creator_id is not None:
            try:
                msg = (
                    "❌ *Your Gmail submission was rejected.*"
                    f"📧 Email: `{email}`"
                    f"❗ Reason: `{reason}`"
                    "If you think this is a mistake, contact the verifier or the owner."
                )
                await context.bot.send_message(chat_id=creator_id, text=msg, parse_mode="Markdown")
            except Exception as e:
                logger.error("Failed to notify creator %s about rejection: %s", creator_id, e)

        await _send(update, context, f"❌ {email} marked as FAILED and moved to failed list.")
    else:
        await _send(update, context, "⚠️ Email not found in PENDING list.")


async def listpending_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not is_owner_or_verifier(user.id):
        await _send(update, context, "⛔ You are not allowed to view pending.")
        return

    if not os.path.exists(PENDING_FILE):
        await _send(update, context, "No pending.")
        return

    msg_lines = ["⏳ *Pending List*"]
    with open(PENDING_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            msg_lines.append(f"• `{line.split('	')[0]}`")

    await _send(update, context, "".join(msg_lines), markdown=True)



async def listconfirmed_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not is_owner_or_verifier(user.id):
        await _send(update, context, "⛔ You are not allowed to view confirmed.")
        return

    if not os.path.exists(CONFIRMED_FILE):
        await _send(update, context, "No confirmed.")
        return

    msg_lines = ["✅ *Confirmed List*"]
    with open(CONFIRMED_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            msg_lines.append(f"• `{line.split('	')[0]}`")

    await _send(update, context, "".join(msg_lines), markdown=True)



async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bal = get_balance(update.effective_user.id)
    await _send(update, context, f"💰 Balance: ${bal:.3f}")


# ----------------- Withdraw / Payout helpers -----------------
WITHDRAWALS_FILE = "withdrawals.json"


def set_balance(uid: int, value: float) -> float:
    """Set user's balance exactly to `value` (used when owner pays out)."""
    credits = load_credits()
    credits[str(uid)] = round(float(value), 6)
    save_credits(credits)
    return credits[str(uid)]


async def withdraw_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """User requests withdrawal when they meet the threshold.

    Usage: /withdraw <amount> <method> <destination>
    Example: /withdraw 1.0 UPI sagar@okhdfc
    If amount is omitted or not a number, the full balance will be requested.
    """
    user = update.effective_user
    if user is None:
        return

    bal = get_balance(user.id)
    if bal < WITHDRAW_THRESHOLD:
        await _send(update, context, f"ℹ️ You need ${WITHDRAW_THRESHOLD:.2f} to withdraw. Your balance: ${bal:.3f}")
        return

    # Parse amount (first arg) optionally
    requested_amount = None
    args = list(context.args)
    if args:
        # try parse first arg as amount
        try:
            possible_amount = float(args[0])
            requested_amount = round(possible_amount, 6)
            args = args[1:]
        except Exception:
            requested_amount = None

    if requested_amount is None:
        # request full balance by default
        requested_amount = round(bal, 6)

    if requested_amount <= 0 or requested_amount > bal:
        await _send(update, context, f"Invalid amount. Your current balance: ${bal:.3f}")
        return

    if len(args) < 3:
        await _send(
        update,
        context,
        "Usage: /withdraw <amount> <method> <destination>\nExample: /withdraw 1.0 UPI sagar@okhdfc"
    )
    return

    method = args[0]
    dest = " ".join(args[1:])

    # Create withdrawal request
    req = {
        "id": uuid.uuid4().hex,
        "user_id": user.id,
        "user_name": user.username,
        "amount": requested_amount,
        "method": method,
        "destination": dest,
        "status": "pending",
    }

    # save to file
    try:
        arr = []
        if os.path.exists(WITHDRAWALS_FILE):
            with open(WITHDRAWALS_FILE, "r", encoding="utf-8") as f:
                arr = json.load(f)
        arr.append(req)
        with open(WITHDRAWALS_FILE, "w", encoding="utf-8") as f:
            json.dump(arr, f, indent=2)
    except Exception as e:
        logger.error("Failed to save withdrawal request: %s", e)
        await _send(update, context, "⚠️ Could not create withdrawal request. Try again later.")
        return

    # Notify owners/verifiers (whoever handles payouts)
    notify = (
    '''💸 *Withdrawal Request*\n
        f"ID: `{req['id']}`\n
        f"User: @{user.username if user.username else user.id} (ID:{user.id})\n
        f"Amount: `${requested_amount:.3f}`\n
        f"Method: {method}\n
        f"Destination: `{dest}`\n
        "Owner: use /pay <request_id> <txid_or_note> to mark paid.'''
    )

    for oid in OWNER_IDS:
        try:
            await context.bot.send_message(chat_id=oid, text=notify, parse_mode="Markdown")
        except Exception as e:
            logger.error("Failed to notify owner %s about withdraw: %s", oid, e)

    await _send(update, context, f"✅ Withdrawal request created for ${requested_amount:.3f}. Owner will process it soon.")


async def pay_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Owner marks a withdrawal request as paid.

    Usage: /pay <request_id> <txid_or_note>
    This will deduct the amount from user's balance and mark request as 'paid'.
    """
    user = update.effective_user
    if user is None or user.id not in OWNER_IDS:
        await _send(update, context, "⛔ You are not allowed to perform payouts.")
        return

    if len(context.args) < 2:
        await _send(update, context, "Usage: /pay <request_id> <txid_or_note>")
        return

    req_id = context.args[0]
    note = " ".join(context.args[1:])

    if not os.path.exists(WITHDRAWALS_FILE):
        await _send(update, context, "No withdrawal requests found.")
        return

    try:
        with open(WITHDRAWALS_FILE, "r", encoding="utf-8") as f:
            arr = json.load(f)
    except Exception as e:
        logger.error("Failed reading withdrawals: %s", e)
        await _send(update, context, "⚠️ Unable to read withdrawal file.")
        return

    found = None
    for r in arr:
        if r.get("id") == req_id:
            found = r
            break

    if not found:
        await _send(update, context, "Request ID not found.")
        return

    if found.get("status") == "paid":
        await _send(update, context, "Request is already marked as paid.")
        return

    # Subtract the paid amount from user's balance and mark paid
    uid = int(found["user_id"])
    amount = float(found["amount"])
    # subtract amount from user's balance (don't go negative)
    current_bal = get_balance(uid)
    remaining = round(max(0.0, current_bal - amount), 6)
    set_balance(uid, remaining)
    found["status"] = "paid"
    found["paid_by"] = user.id
    found["paid_note"] = note

    try:
        with open(WITHDRAWALS_FILE, "w", encoding="utf-8") as f:
            json.dump(arr, f, indent=2)
    except Exception as e:
        logger.error("Failed to update withdrawals: %s", e)
        await _send(update, context, "⚠️ Could not update withdrawal status file.")
        return

    # Notify the requester with remaining balance info
    try:
        msg = (
            '''✅ *Withdrawal Paid*\n
            f"Amount paid: `${amount:.3f}`\n
            f"Note/Tx: `{note}`\n
            f"Remaining balance: `${remaining:.3f}`\n
            "If you have issues, contact the owner.'''
        )
        await context.bot.send_message(chat_id=uid, text=msg, parse_mode="Markdown")
    except Exception as e:
        logger.error("Failed to notify requester %s: %s", uid, e)

    await _send(update, context, f"✅ Marked request {req_id} as paid.")


async def list_withdrawals_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Owner command to list all withdrawal requests."""
    user = update.effective_user
    if user is None or user.id not in OWNER_IDS:
        await _send(update, context, "⛔ You are not allowed to view withdrawals.")
        return

    if not os.path.exists(WITHDRAWALS_FILE):
        await _send(update, context, "No withdrawal requests.")
        return

    try:
        with open(WITHDRAWALS_FILE, "r", encoding="utf-8") as f:
            arr = json.load(f)
    except Exception as e:
        logger.error("Failed reading withdrawals: %s", e)
        await _send(update, context, "⚠️ Unable to read withdrawal file.")
        return

    lines = ["💸 *Withdrawal Requests*"]
    for r in arr:
        lines.append(
            f"• ID: `{r.get('id')}` — User: {r.get('user_name') or r.get('user_id')} — Amount: `${float(r.get('amount')):.3f}` — Status: {r.get('status')}"
        )
    await _send(update, context,"".join(lines), markdown=True)


# ----------------- Inline keyboard handler -----------------

async def inline_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    data = query.data

    if data == "newgmail":
        await newgmail_command(update, context)
    elif data == "savecreated":
        await _send(update, context, "Send: /savecreated email password")
    elif data == "balance":
        await balance_command(update, context)
    elif data == "listpending":
        await listpending_command(update, context)
    elif data == "listconfirmed":
        await listconfirmed_command(update, context)
    elif data == "verifypass":
        await _send(update, context, "Use: /verifypass email")
    elif data == "verifyfail":
        await _send(update, context, "Use: /verifyfail email [reason]")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception while handling an update", exc_info=context.error)


# ----------------- Simple tests for helpers -----------------

def _run_basic_tests() -> None:
    """Very small sanity tests for pure helper functions."""
    # generate_unique_username should not clash
    s: Set[str] = set()
    u1 = generate_unique_username(s)
    s.add(u1.lower())
    u2 = generate_unique_username(s)
    assert u1 != u2, "Usernames must be unique"

    # credits add up correctly
    if os.path.exists(CREDITS_FILE):
        os.remove(CREDITS_FILE)
    b0 = get_balance(1)
    assert b0 == 0.0
    b1 = add_credit(1, 0.5)
    b2 = add_credit(1, 0.25)
    assert abs(b2 - 0.75) < 1e-9

    # default password file is created
    if os.path.exists(PASSWORD_FILE):
        os.remove(PASSWORD_FILE)
    p = get_default_password()
    assert p == "12345gmail"


# ----------------- Entry point -----------------

def main() -> None:
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("newgmail", newgmail_command))
    app.add_handler(CommandHandler("savecreated", savecreated_command))
    app.add_handler(CommandHandler("verifypass", verifypass_command))
    app.add_handler(CommandHandler("verifyfail", verifyfail_command))
    app.add_handler(CommandHandler("listpending", listpending_command))
    app.add_handler(CommandHandler("listconfirmed", listconfirmed_command))
    app.add_handler(CommandHandler("balance", balance_command))

    # Withdraw / payout handlers
    app.add_handler(CommandHandler("withdraw", withdraw_command))
    app.add_handler(CommandHandler("pay", pay_command))
    app.add_handler(CommandHandler("withdrawals", list_withdrawals_command))

    app.add_handler(CallbackQueryHandler(inline_button_handler))
    app.add_error_handler(error_handler)

    logger.info("Bot is starting...")
    app.run_polling()


if __name__ == "__main__":
    # Optional: run basic tests by setting RUN_TESTS=1 in the environment
    if os.environ.get("RUN_TESTS") == "1":
        _run_basic_tests()
        print("Helper tests passed.")
    else:
        main()
