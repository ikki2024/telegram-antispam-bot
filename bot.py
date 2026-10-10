import os
import time
from collections import defaultdict, deque

from telegram import Update
from telegram.ext import (
    Application,
    ContextTypes,
    MessageHandler,
    filters,
)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# 防刷屏设置：
# 同一个人 10 秒内发送 5 条消息 -> 删除这些消息并封禁
FLOOD_SECONDS = 10
FLOOD_COUNT = 5

user_messages = defaultdict(lambda: deque())


async def is_admin(update: Update, user_id: int) -> bool:
    """管理员不会被机器人处理"""
    member = await update.effective_chat.get_member(user_id)
    return member.status in ("administrator", "creator")


async def monitor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat

    if not message or not user or not chat:
        return

    # 不处理私聊
    if chat.type == "private":
        return

    # 不处理管理员
    try:
        if await is_admin(update, user.id):
            return
    except Exception:
        return

    key = (chat.id, user.id)
    now = time.time()

    history = user_messages[key]
    history.append((now, message.message_id))

    # 删除超过时间窗口的记录
    while history and now - history[0][0] > FLOOD_SECONDS:
        history.popleft()

    # 达到刷屏阈值
    if len(history) >= FLOOD_COUNT:
        message_ids = [msg_id for _, msg_id in history]

        # 先删除刷屏消息
        for msg_id in message_ids:
            try:
                await context.bot.delete_message(
                    chat_id=chat.id,
                    message_id=msg_id
                )
            except Exception:
                pass

        # 再封禁发送者
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

        history.clear()


def main():
    if not TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not found")

    application = Application.builder().token(TOKEN).build()

    application.add_handler(
        MessageHandler(
            filters.ALL & ~filters.StatusUpdate.ALL,
            monitor
        )
    )

    print("Anti-spam bot is running...")
    application.run_polling()


if __name__ == "__main__":
    main()
