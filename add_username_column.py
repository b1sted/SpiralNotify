import aiosqlite
from loguru import logger
import os


# Добавляет столбец username в таблицы subscribers и tickets
async def add_username_columns():
    try:
        async with aiosqlite.connect("subscribers.db") as db:
            # Добавление столбца username в subscribers
            cursor = await db.execute("PRAGMA table_info(subscribers)")
            columns = await cursor.fetchall()  # Исправлено!
            if not any(column[1] == 'username' for column in columns):
                await db.execute(
                    """
                    CREATE TABLE subscribers_temp (
                        chat_id INTEGER PRIMARY KEY,
                        username TEXT,
                        subscription_type TEXT
                    );
                    """
                )
                await db.execute(
                    "INSERT INTO subscribers_temp (chat_id, subscription_type) SELECT chat_id, subscription_type FROM subscribers"
                )
                await db.execute("DROP TABLE subscribers")
                await db.execute("ALTER TABLE subscribers_temp RENAME TO subscribers")
                await db.commit()
                logger.info("Добавлен столбец username в таблицу subscribers")
            else:
                logger.info("Столбец username уже существует в таблице subscribers")

        async with aiosqlite.connect("tickets.db") as db:
            # Добавление столбца username в tickets
            cursor = await db.execute("PRAGMA table_info(tickets)")
            columns = await cursor.fetchall()  # Исправлено!
            if not any(column[1] == 'username' for column in columns):
                await db.execute(
                    """
                    CREATE TABLE tickets_temp (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER,
                        username TEXT,
                        problem TEXT,
                        description TEXT,
                        status TEXT,
                        response TEXT
                    );
                    """
                )
                await db.execute(
                    "INSERT INTO tickets_temp (id, user_id, problem, description, status, response) SELECT id, user_id, problem, description, status, response FROM tickets"
                )
                await db.execute("DROP TABLE tickets")
                await db.execute("ALTER TABLE tickets_temp RENAME TO tickets")
                await db.commit()
                logger.info("Добавлен столбец username в таблицу tickets")
            else:
                logger.info("Столбец username уже существует в таблице tickets")
    except Exception as e:
        logger.error(f"Ошибка при добавлении столбца username: {e}")


if __name__ == "__main__":
    import asyncio
    asyncio.run(add_username_columns())
