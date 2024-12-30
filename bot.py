import asyncio
import logging
import os
import sqlite3
from datetime import datetime

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

# Определение версии бота
BOT_VERSION = "2.00"

# Настройка логирования
logging.basicConfig(level=logging.INFO, filename='bot.log', filemode='a',
                    format='%(asctime)s - %(levelname)s - %(message)s')

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
bot_start_time = datetime.now()  # Время запуска бота для отслеживания времени работы


# Инициализация отдельных баз данных для тикетов и подписчиков
def init_ticket_db():
    conn = sqlite3.connect("tickets.db")
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS tickets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        problem TEXT,
        description TEXT,
        status TEXT,
        response TEXT
    );
    """)
    conn.commit()
    conn.close()


def init_subscriber_db():
    conn = sqlite3.connect("subscribers.db")
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS subscribers (
        chat_id INTEGER PRIMARY KEY,
        subscription_type TEXT
    );
    """)
    conn.commit()
    conn.close()


init_ticket_db()
init_subscriber_db()


# Состояния для отправки рассылки
class BroadcastFSM(StatesGroup):
    select_type = State()
    enter_content = State()  # Для текста и фото


# Состояния для подачи заявки
class TicketFSM(StatesGroup):
    problem = State()
    description = State()
    response = State()


# Состояния для управления ответами на заявки
class TicketStatusFSM(StatesGroup):
    response = State()


# Главное меню администратора
async def get_main_menu(user_id):
    keyboard = [
        [KeyboardButton(text="Подписка на уведомления")],
        [KeyboardButton(text="Поддержка")],
        [KeyboardButton(text="О боте")]
    ]
    if user_id == ADMIN_ID:
        keyboard.append([KeyboardButton(text="Администрирование")])
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


# Инлайн-клавиатуры для меню подписки, поддержки и администрирования
subscribe_menu = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="Подписка на все уведомления", callback_data="subscribe_all")],
        [InlineKeyboardButton(text="Подписка на обновления контента", callback_data="subscribe_updates")],
        [InlineKeyboardButton(text="Отписаться", callback_data="unsubscribe")],
        [InlineKeyboardButton(text="Назад", callback_data="back_main")]
    ]
)

support_menu = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="Отправить заявку", callback_data="send_ticket")],
        [InlineKeyboardButton(text="Просмотр заявок", callback_data="view_tickets")],
        [InlineKeyboardButton(text="Назад", callback_data="back_main")]
    ]
)

admin_menu = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="Отправить сообщение", callback_data="send_broadcast")],
        [InlineKeyboardButton(text="Просмотр нерешенных заявок", callback_data="view_unresolved_tickets")],
        [InlineKeyboardButton(text="Просмотр решенных заявок", callback_data="view_resolved_tickets")],
        [InlineKeyboardButton(text="Сброс базы данных", callback_data="reset_database")],
        [InlineKeyboardButton(text="Статистика", callback_data="view_statistics")],
        [InlineKeyboardButton(text="Просмотр логов", callback_data="view_logs")],
        [InlineKeyboardButton(text="Назад", callback_data="back_main")]
    ]
)

# Подменю выбора типа рассылки
broadcast_type_menu = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="Обновление (всем)", callback_data="broadcast_updates")],
        [InlineKeyboardButton(text="Исправления", callback_data="broadcast_fixes")],
        [InlineKeyboardButton(text="Назад", callback_data="back_main")]
    ]
)


# Форматирование времени работы в виде "X дней - ЧЧ:ММ:СС"
def get_uptime():
    uptime = datetime.now() - bot_start_time
    days, seconds = uptime.days, uptime.seconds
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    seconds = seconds % 60
    return f"{days} дней - {hours:02}:{minutes:02}:{seconds:02}"


# Команда start
@dp.message(Command("start"))
async def start(message: types.Message):
    main_menu = await get_main_menu(message.from_user.id)
    await message.answer("Добро пожаловать! Выберите интересующую вас опцию ниже:", reply_markup=main_menu)


# Меню подписки
@dp.message(F.text == "Подписка на уведомления")
async def subscribe(message: types.Message):
    # Подключение к базе данных для получения текущей подписки пользователя
    conn = sqlite3.connect("subscribers.db")
    cursor = conn.cursor()
    cursor.execute("SELECT subscription_type FROM subscribers WHERE chat_id = ?", (message.from_user.id,))
    result = cursor.fetchone()
    conn.close()

    # Определение текущего статуса подписки на русском
    if result:
        subscription_type = result[0]
        if subscription_type == "all":
            current_subscription = "Все уведомления"
        elif subscription_type == "updates":
            current_subscription = "Обновления"
        else:
            current_subscription = "Неизвестная подписка"
    else:
        current_subscription = "Нет подписки"

    # Отправка меню с текущим статусом подписки
    await message.answer(
        f"Настройте свою подписку:\n\nТекущая подписка: {current_subscription}",
        reply_markup=subscribe_menu
    )


# Обработчик выбора подписки "Все уведомления"
@dp.callback_query(lambda c: c.data == "subscribe_all")
async def subscribe_all(callback_query: types.CallbackQuery):
    conn = sqlite3.connect("subscribers.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO subscribers (chat_id, subscription_type) VALUES (?, ?)",
                   (callback_query.from_user.id, "all"))
    conn.commit()
    conn.close()
    await callback_query.answer("Вы подписаны на все уведомления.")
    await callback_query.message.delete()


# Обработчик выбора подписки "Обновления"
@dp.callback_query(lambda c: c.data == "subscribe_updates")
async def subscribe_updates(callback_query: types.CallbackQuery):
    conn = sqlite3.connect("subscribers.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO subscribers (chat_id, subscription_type) VALUES (?, ?)",
                   (callback_query.from_user.id, "updates"))
    conn.commit()
    conn.close()
    await callback_query.answer("Вы подписаны на обновления.")
    await callback_query.message.delete()


# Отписка
@dp.callback_query(lambda c: c.data == "unsubscribe")
async def unsubscribe(callback_query: types.CallbackQuery):
    conn = sqlite3.connect("subscribers.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM subscribers WHERE chat_id = ?", (callback_query.from_user.id,))
    conn.commit()
    conn.close()
    await callback_query.answer("Вы отписались от всех уведомлений.")
    await callback_query.message.delete()


# Меню поддержки
@dp.message(F.text == "Поддержка")
async def support(message: types.Message):
    await message.answer("Чем мы можем вам помочь?", reply_markup=support_menu)


# Отправить заявку: начало подачи заявки
@dp.callback_query(lambda c: c.data == "send_ticket")
async def send_ticket(callback_query: types.CallbackQuery, state: FSMContext):
    await callback_query.message.answer("Опишите кратко вашу проблему:")
    await state.set_state(TicketFSM.problem)


@dp.message(TicketFSM.problem)
async def enter_problem(message: types.Message, state: FSMContext):
    await state.update_data(problem=message.text)
    await message.answer("Дайте более подробное описание проблемы:")
    await state.set_state(TicketFSM.description)


@dp.message(TicketFSM.description)
async def enter_description(message: types.Message, state: FSMContext):
    data = await state.get_data()
    problem = data.get("problem")
    description = message.text

    conn = sqlite3.connect("tickets.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO tickets (user_id, problem, description, status) VALUES (?, ?, ?, ?)",
                   (message.from_user.id, problem, description, "Unresolved"))
    ticket_id = cursor.lastrowid
    conn.commit()
    conn.close()

    await message.answer("Ваша заявка отправлена.")
    await state.clear()

    # Уведомление админа о новой заявке
    await bot.send_message(ADMIN_ID,
                           f"Новая заявка:\nПроблема: {problem}\nОписание: {description}\nID заявки: {ticket_id}")


# Просмотр отправленных заявок
@dp.callback_query(lambda c: c.data == "view_tickets")
async def view_tickets(callback_query: types.CallbackQuery):
    conn = sqlite3.connect("tickets.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tickets WHERE user_id = ?", (callback_query.from_user.id,))
    user_tickets = cursor.fetchall()
    conn.close()

    if user_tickets:
        tickets_text = ""
        for row in user_tickets:
            ticket_info = f"Проблема: {row[2]}\nОписание: {row[3]}\nСтатус: {row[4]}"
            if row[4] == "Решено" and row[5]:
                ticket_info += f"\nОтвет: {row[5]}"
            tickets_text += f"{ticket_info}\n\n"

        await callback_query.message.answer(f"Ваши заявки:\n{tickets_text}", reply_markup=support_menu)
    else:
        await callback_query.answer("У вас нет отправленных заявок.", reply_markup=support_menu)


# О боте
@dp.message(F.text == "О боте")
async def about_bot(message: types.Message):
    await message.answer(
        f"Бот по отправке уведомлений о новом контенте и/или его исправлении на https://downwardspiral.gitbook.io/main.\n\n"
        f"Версия бота: {BOT_VERSION}"
    )


# Административное меню (только для админа)
@dp.message(F.text == "Администрирование")
async def admin(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        await message.answer("Панель администратора:", reply_markup=admin_menu)
    else:
        await message.answer("У вас нет доступа к этому разделу.")


# Выбор типа рассылки
@dp.callback_query(lambda c: c.data == "send_broadcast")
async def select_broadcast_type(callback_query: types.CallbackQuery, state: FSMContext):
    await callback_query.message.answer("Выберите, кому будет отправлено сообщение:", reply_markup=broadcast_type_menu)
    await state.set_state(BroadcastFSM.select_type)


# Обработчик выбора типа и переход к вводу сообщения
@dp.callback_query(lambda c: c.data.startswith("broadcast_"))
async def enter_broadcast_content(callback_query: types.CallbackQuery, state: FSMContext):
    broadcast_type = callback_query.data.split("_")[1]
    await state.update_data(broadcast_type=broadcast_type)
    await callback_query.message.answer("Отправьте текст сообщения и/или фотографию:")
    await state.set_state(BroadcastFSM.enter_content)


# Обработчик отправки сообщения (текст или фото)
@dp.message(BroadcastFSM.enter_content, F.text | F.photo)
async def send_broadcast(message: types.Message, state: FSMContext):
    data = await state.get_data()
    broadcast_type = data["broadcast_type"]

    # Получение текста и фото из сообщения
    text = message.caption if message.photo else message.text
    photo = message.photo[-1].file_id if message.photo else None

    # Выбор подписчиков по типу рассылки
    conn = sqlite3.connect("subscribers.db")
    cursor = conn.cursor()
    if broadcast_type == "updates":
        cursor.execute("SELECT chat_id FROM subscribers WHERE subscription_type IN ('all', 'updates')")
    elif broadcast_type == "fixes":
        cursor.execute("SELECT chat_id FROM subscribers WHERE subscription_type = 'all'")

    subscribers = cursor.fetchall()
    conn.close()

    # Отправка текста и/или фото подписчикам
    for (chat_id,) in subscribers:
        if photo:
            await bot.send_photo(chat_id, photo=photo, caption=text)
        else:
            await bot.send_message(chat_id, text)

    await message.answer("Сообщение успешно отправлено.")
    await state.clear()


# Обработчик для просмотра нерешенных обращений, включая те, что "В процессе"
@dp.callback_query(lambda c: c.data == "view_unresolved_tickets")
async def view_unresolved_tickets(callback_query: types.CallbackQuery):
    conn = sqlite3.connect("tickets.db")
    cursor = conn.cursor()
    # Выборка заявок со статусом "Unresolved" и "In Progress"
    cursor.execute("SELECT id, problem, description, status FROM tickets WHERE status IN ('Unresolved', 'In Progress')")
    unresolved_tickets = cursor.fetchall()
    conn.close()

    if unresolved_tickets:
        for ticket in unresolved_tickets:
            ticket_id, problem, description, status = ticket
            await callback_query.message.answer(
                f"Заявка ID: {ticket_id}\nСтатус: {status}\nПроблема: {problem}\nОписание: {description}",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(text="Решено", callback_data=f"change_status_resolved_{ticket_id}"),
                        InlineKeyboardButton(text="В процессе", callback_data=f"change_status_inprogress_{ticket_id}"),
                    ],
                    [InlineKeyboardButton(text="Назад", callback_data="back_main")]
                ])
            )
    else:
        await callback_query.answer("Нерешенных заявок не найдено.")


# Обработчик для установки статуса «В процессе»
@dp.callback_query(lambda c: c.data.startswith("change_status_inprogress_"))
async def set_status_in_progress(callback_query: types.CallbackQuery):
    ticket_id = int(callback_query.data.split("_")[-1])
    conn = sqlite3.connect("tickets.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE tickets SET status = 'In Progress' WHERE id = ?", (ticket_id,))
    conn.commit()
    conn.close()

    await callback_query.answer("Статус изменён на 'В процессе'.")
    await notify_user_about_status_change(ticket_id, "В процессе")


# Обработчик для установки статуса «Решено» и запроса ответа от администратора
@dp.callback_query(lambda c: c.data.startswith("change_status_resolved_"))
async def set_status_resolved(callback_query: types.CallbackQuery, state: FSMContext):
    ticket_id = int(callback_query.data.split("_")[-1])
    await state.update_data(ticket_id=ticket_id)  # Сохранение идентификатора заявки в контексте FSM
    await callback_query.message.answer("Пожалуйста, напишите ответ для этой закрытой заявки:")
    await state.set_state(TicketStatusFSM.response)


# Обработчик для сохранения ответа при закрытии заявки
@dp.message(TicketStatusFSM.response)
async def save_resolved_response(message: types.Message, state: FSMContext):
    data = await state.get_data()
    ticket_id = data["ticket_id"]
    response = message.text

    conn = sqlite3.connect("tickets.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE tickets SET status = 'Resolved', response = ? WHERE id = ?", (response, ticket_id))
    conn.commit()
    conn.close()

    await message.answer("Заявка отмечена как решенная с вашим ответом.")
    await state.clear()
    await notify_user_about_status_change(ticket_id, "Решено", response)


# Функция для уведомления пользователя об изменении статуса его заявки
async def notify_user_about_status_change(ticket_id, new_status, response=None):
    conn = sqlite3.connect("tickets.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, problem FROM tickets WHERE id = ?", (ticket_id,))
    user_id, problem = cursor.fetchone()
    conn.close()

    # Формирование уведомления для пользователя
    notification_message = f"Статус вашей заявки (ID: {ticket_id}, Проблема: {problem}) изменен на '{new_status}'."
    if new_status == "Решено" and response:
        notification_message += f"\nОтвет администратора: {response}"

    # Отправка уведомления пользователю
    await bot.send_message(user_id, notification_message)


# Обработчик для кнопки "Просмотр решенных заявок", отображает все решенные заявки
@dp.callback_query(lambda c: c.data == "view_resolved_tickets")
async def view_resolved_tickets(callback_query: types.CallbackQuery):
    conn = sqlite3.connect("tickets.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, problem, description, status, response FROM tickets WHERE status = 'Resolved'")
    resolved_tickets = cursor.fetchall()
    conn.close()

    if resolved_tickets:
        tickets_text = ""
        for ticket in resolved_tickets:
            ticket_info = (
                f"ID: {ticket[0]}\n"
                f"Проблема: {ticket[1]}\n"
                f"Описание: {ticket[2]}\n"
                f"Статус: {ticket[3]}\n"
                f"Ответ: {ticket[4]}\n\n"
            )
            tickets_text += ticket_info

        await callback_query.message.answer(f"Решенные заявки:\n{tickets_text}", reply_markup=admin_menu)
    else:
        await callback_query.answer("Решенные заявки отсутствуют.", reply_markup=admin_menu)


# Уведомление подписчиков в зависимости от типа подписки
async def notify_subscribers(subscription_type, text):
    conn = sqlite3.connect("subscribers.db")
    cursor = conn.cursor()
    cursor.execute("SELECT chat_id FROM subscribers WHERE subscription_type=?", (subscription_type,))
    subscribers = cursor.fetchall()
    conn.close()

    # Отправка сообщения каждому подписчику указанного типа
    for (chat_id,) in subscribers:
        await bot.send_message(chat_id, text)


# Сброс базы данных (только для администратора)
@dp.callback_query(lambda c: c.data == "reset_database")
async def reset_database(callback_query: types.CallbackQuery):
    if callback_query.from_user.id == ADMIN_ID:
        conn = sqlite3.connect("tickets.db")
        cursor = conn.cursor()
        cursor.execute("DELETE FROM tickets")
        conn.commit()
        conn.close()
        await callback_query.answer("База данных была сброшена.")
    else:
        await callback_query.answer("У вас нет прав для выполнения этого действия.")


# Статистика (только для администратора)
@dp.callback_query(lambda c: c.data == "view_statistics")
async def view_statistics(callback_query: types.CallbackQuery):
    if callback_query.from_user.id == ADMIN_ID:
        conn = sqlite3.connect("subscribers.db")
        cursor = conn.cursor()

        # Получение общего числа подписчиков
        cursor.execute("SELECT COUNT(*) FROM subscribers")
        total_subscribers = cursor.fetchone()[0]

        # Получение числа подписчиков по типам
        cursor.execute("SELECT subscription_type, COUNT(*) FROM subscribers GROUP BY subscription_type")
        subscription_counts = cursor.fetchall()

        # Форматирование времени работы бота
        uptime = get_uptime()
        conn.close()

        # Форматирование данных о подписках
        subscription_details = "\n".join([f"{stype}: {count}" for stype, count in subscription_counts])

        # Текст статистики с версией бота
        stats_text = (
            f"Всего подписчиков: {total_subscribers}\n"
            f"Подписчики по типам:\n{subscription_details}\n"
            f"Время работы бота: {uptime}\n"
            f"Версия бота: {BOT_VERSION}"
        )
        await callback_query.message.answer(stats_text, reply_markup=admin_menu)
    else:
        await callback_query.answer("У вас нет прав для выполнения этого действия.")


# Обработчик для кнопки "Просмотр логов" (только для администратора)
@dp.callback_query(lambda c: c.data == "view_logs")
async def view_logs(callback_query: types.CallbackQuery):
    if callback_query.from_user.id == ADMIN_ID:
        try:
            with open("bot.log", "r") as log_file:
                # Фильтруем логи: выбираем только строки с уровнем WARNING и выше
                warning_logs = [line for line in log_file.readlines() if
                                "WARNING" in line or "ERROR" in line or "CRITICAL" in line]
            logs_text = ''.join(warning_logs[-20:]) or "Логи уровня WARNING и выше пусты."
            await callback_query.message.answer(f"<b>Последние логи уровня WARNING и выше:</b>\n<pre>{logs_text}</pre>",
                                                parse_mode="HTML")
        except Exception as e:
            await callback_query.message.answer(f"Не удалось прочитать файл логов: {e}")
    else:
        await callback_query.answer("У вас нет доступа к этой функции.")


# Обработчик для кнопки "Назад"
@dp.callback_query(lambda c: c.data == "back_main")
async def back_to_main(callback_query: types.CallbackQuery):
    await callback_query.message.delete()


# Запустить бота
async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
