import os
import time
import re
import hashlib
from collections import defaultdict, deque

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# ---------- 设置 ----------

# 单人刷屏：10 秒 5 条
FLOOD_SECONDS = 10
FLOOD_COUNT = 5

# 群体复制广告：
# 60 秒内，同样内容由 3 个不同账号发送 -> 判定为群体垃圾信息
DUPLICATE_SECONDS = 60
DUPLICATE_USERS = 3

# 至少达到这个长度才进行重复内容判断
MIN_DUPLICATE_LENGTH = 8


# ---------- 内存记录 ----------

user_messages = defaultdict(lambda: deque())
duplicate_messages = defaultdict(lambda: deque())


async def is_admin(chat, user_id):
    """管理员和群主永远不会被自动处理。"""
    try:
        member = await chat.get_member(user_id)
        return member.status in ("administrator", "creator")
    except Exception:
        return False


def normalize_text(text):
    """
    标准化文本，降低攻击者通过空格、换行等方式
    绕过重复广告检测的可能。
    """
    if not text:
        return ""

    text = text.lower()
    text = re.sub(r"\s+", "", text)

    return text


def text_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def delete_message_safe(context, chat_id, message_id):
    try:
        await context.bot.delete_message(
            chat_id=chat_id,
            message_id=message_id
        )
    except Exception as e:
        print(f"DELETE ERROR: {e}")


async def ban_user_safe(context, chat, user):
    # 最后再检查一次管理员身份
    if await is_admin(chat, user.id):
        return

    try:
        await context.bot.ban_chat_member(
            chat_id=chat.id,
            user_id=user.id
        )

        print(
            f"BANNED: {user.full_name} "
            f"({user.id}) in {chat.title}"
        )

    except Exception as e:
        print(f"BAN ERROR: {e}")


async def status_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    """管理员可以用 /status 检查机器人是否在线。"""

    user = update.effective_user
    chat = update.effective_chat

    if not user or not chat:
        return

    if chat.type == "private":
        await update.message.reply_text(
            "Anti-spam bot is running."
        )
        return

    if await is_admin(chat, user.id):
        await update.message.reply_text(
            "Anti-spam bot is running."
        )


async def monitor(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat

    if not message or not user or not chat:
        return

    # 私聊不处理
    if chat.type == "private":
        return

    # Telegram Bot 自己不处理
    if user.is_bot:
        return

    # 管理员永远豁免
    if await is_admin(chat, user.id):
        return

    now = time.time()

    # ==================================================
    # 1. 单账号 Flood 检测
    # ==================================================

    user_key = (chat.id, user.id)
    history = user_messages[user_key]

    history.append((now, message.message_id))

    while history and now - history[0][0] > FLOOD_SECONDS:
        history.popleft()

    if len(history) >= FLOOD_COUNT:

        ids = [msg_id for _, msg_id in history]

        for msg_id in ids:
            await delete_message_safe(
                context,
                chat.id,
                msg_id
            )

        await ban_user_safe(
            context,
            chat,
            user
        )

        history.clear()
        return

    # ==================================================
    # 2. 多账号重复广告检测
    # ==================================================

    text = message.text or message.caption or ""

    normalized = normalize_text(text)

    if len(normalized) < MIN_DUPLICATE_LENGTH:
        return

    fingerprint = text_hash(normalized)

    duplicate_key = (chat.id, fingerprint)
    duplicate_history = duplicate_messages[duplicate_key]

    duplicate_history.append(
        (
            now,
            user.id,
            message.message_id,
            user
        )
    )

    # 清理 60 秒以前的数据
    while (
        duplicate_history
        and now - duplicate_history[0][0]
        > DUPLICATE_SECONDS
    ):
        duplicate_history.popleft()

    unique_users = {
        item[1]
        for item in duplicate_history
    }

    # 3 个不同账号发完全相同内容
    if len(unique_users) >= DUPLICATE_USERS:

        print(
            f"DUPLICATE SPAM detected in {chat.title}"
        )

        # 删除这一批重复消息
        for _, uid, msg_id, spam_user in list(
            duplicate_history
        ):

            await delete_message_safe(
                context,
                chat.id,
                msg_id
            )

            # 管理员永远不封
            if not await is_admin(chat, uid):
                await ban_user_safe(
                    context,
                    chat,
                    spam_user
                )

        duplicate_history.clear()


def main():

    if not TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN not found"
        )

    application = (
        Application
        .builder()
        .token(TOKEN)
        .build()
    )

    # /status
    application.add_handler(
        CommandHandler(
            "status",
            status_command
        )
    )

    # 所有普通消息
    application.add_handler(
        MessageHandler(
            filters.ALL & ~filters.StatusUpdate.ALL,
            monitor
        )
    )

    print("Anti-spam bot v2 is running...")

    application.run_polling()


if __name__ == "__main__":
    main()
