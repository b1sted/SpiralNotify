import asyncio
import os
from datetime import datetime, timedelta
import io

import aiosqlite
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from dotenv import load_dotenv
from loguru import logger

# Загрузка переменных окружения
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

# Определение версии бота
BOT_VERSION = "3.00"

# Создание папки log, если она не существует
log_dir = os.path.join(os.path.dirname(__file__), "log")
os.makedirs(log_dir, exist_ok=True)

# Настройка логгера loguru с добавлением цветов
logger.add(
    os.path.join(log_dir, "debug.log"),
    rotation="10 MB",
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level}</level> | <cyan>{module}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | <level>{message}</level>",
    level="DEBUG",
)
logger.add(
    os.path.join(log_dir, "error.log"),
    rotation="1 week",
    format="<red>{time:YYYY-MM-DD HH:mm:ss}</red> | <level>{level}</level> | <cyan>{module}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | <level>{message}</level>",
    level="WARNING",
    backtrace=True,
    diagnose=True,
)
logger.add(
    os.path.join(log_dir, "startup_shutdown.log"),
    rotation="100 MB",
    format="<blue>{time:YYYY-MM-DD HH:mm:ss}</blue> | <level>{level}</level> | <cyan>{module}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | <level>{message}</level>",
    level="INFO",
    filter=lambda record: "tags" in record["extra"]
    and "startup_shutdown" in record["extra"]["tags"],
)
logger.add(
    os.path.join(log_dir, "backup_operations.log"),
    rotation="1 week",
    format="<yellow>{time:YYYY-MM-DD HH:mm:ss}</yellow> | <level>{level}</level> | <cyan>{module}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | <level>{message}</level>",
    level="INFO",
    filter=lambda record: "tags" in record["extra"]
    and "backup_operations" in record["extra"]["tags"],
)

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
bot_start_time = datetime.now()  # Время запуска бота для отслеживания времени работы


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


# Состояния для выбора БД для сброса
class ResetDBFSM(StatesGroup):
    select_db = State()


# Состояния для создания бэкапа
class CreateBackupFSM(StatesGroup):
    confirmation = State()


db_connections = {}  # Словарь для хранения соединений


# Возвращает соединение с базой данных
async def get_db_connection(db_name: str) -> aiosqlite.Connection:
    """
    Если соединение уже существует, возвращает его.
    Если нет, создает новое соединение.
    """
    if db_name not in db_connections:
        try:
            db_connections[db_name] = await aiosqlite.connect(db_name)
        except aiosqlite.OperationalError as e:
            logger.error(f"Не удалось подключиться к базе данных {db_name}: {e}")
            return None
    return db_connections[db_name]


# Закрывает соединение с базой данных
async def close_db_connection(db_name: str):
    if db_name in db_connections:
        await db_connections[db_name].close()
        del db_connections[db_name]


# Перезагружает соединение с базой данных
async def reload_db_connection(db_name: str):
    await close_db_connection(db_name)
    await get_db_connection(db_name)


# Инициализирует базу данных для заявок (tickets.db)
async def init_ticket_db():
    db = await get_db_connection("tickets.db")
    if db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS tickets (
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
        await db.commit()


# Инициализирует базу данных для подписчиков (subscribers.db)
async def init_subscriber_db():
    db = await get_db_connection("subscribers.db")
    if db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS subscribers (
                chat_id INTEGER PRIMARY KEY,
                username TEXT,
                subscription_type TEXT
            );
            """
        )
        await db.commit()


# Создает резервные копии баз данных вручную
async def create_backup():
    now = datetime.now()
    backup_folder_name = now.strftime("%Y%m%d_%H%M%S")
    backup_dir = os.path.join(os.path.dirname(__file__), "backups", backup_folder_name)
    os.makedirs(backup_dir, exist_ok=True)  # Создаем подпапку с датой и временем

    # Создание резервной копии tickets.db
    backup_tickets_path = os.path.join(backup_dir, "tickets.db")
    async with aiosqlite.connect("tickets.db") as source, aiosqlite.connect(
        backup_tickets_path
    ) as destination:
        await source.backup(destination)

    # Создание резервной копии subscribers.db
    backup_subscribers_path = os.path.join(backup_dir, "subscribers.db")
    async with aiosqlite.connect("subscribers.db") as source, aiosqlite.connect(
        backup_subscribers_path
    ) as destination:
        await source.backup(destination)

    logger.bind(tags="backup_operations").info(
        f"Созданы резервные копии баз данных вручную в {now.strftime('%Y-%m-%d %H:%M:%S')} (папка: {backup_folder_name})"
    )

    await cleanup_old_backups()

    return backup_dir


# Возвращает информацию о последних резервных копиях
async def get_backup_info():
    backup_dir = os.path.join(os.path.dirname(__file__), "backups")
    tickets_backup_info = "Не найдено"
    subscribers_backup_info = "Не найдено"

    # Получаем список папок в директории backups
    folders = [
        folder
        for folder in os.listdir(backup_dir)
        if os.path.isdir(os.path.join(backup_dir, folder))
    ]
    folders.sort(reverse=True)  # Сортируем папки по убыванию (сначала новые)

    if folders:
        # Берем самую новую папку
        latest_backup_folder = folders[0]
        try:
            # Извлекаем дату и время из имени папки
            backup_datetime = datetime.strptime(latest_backup_folder, "%Y%m%d_%H%M%S")
            backup_datetime_str = backup_datetime.strftime("%Y-%m-%d %H:%M:%S")

            # Проверяем наличие файлов tickets.db и subscribers.db
            if os.path.exists(os.path.join(backup_dir, latest_backup_folder, "tickets.db")):
                tickets_backup_info = backup_datetime_str
            if os.path.exists(
                os.path.join(backup_dir, latest_backup_folder, "subscribers.db")
            ):
                subscribers_backup_info = backup_datetime_str

        except ValueError:
            logger.warning(
                f"Не удалось разобрать имя папки резервной копии: {latest_backup_folder}"
            )

    return tickets_backup_info, subscribers_backup_info


# Создает резервные копии баз данных tickets.db и subscribers.db еженедельно и при старте бота
async def backup_databases():
    logger.bind(tags="backup_operations").info(
        "Создание резервной копии при запуске бота..."
    )
    await create_backup()

    while True:
        now = datetime.now()
        next_backup = now + timedelta(weeks=1)
        next_backup = next_backup.replace(
            hour=0, minute=0, second=0, microsecond=0
        )  # Сброс времени на полночь
        wait_seconds = (next_backup - now).total_seconds()
        await asyncio.sleep(wait_seconds)

        await create_backup()


# Удаляет старые резервные копии баз данных, оставляя только последние 5 версий и удаляя копии старше 5 недель
async def cleanup_old_backups():
    backup_dir = os.path.join(os.path.dirname(__file__), "backups")
    now = datetime.now()
    max_versions = 5
    backup_files = {}

    for folder in os.listdir(backup_dir):
        folder_path = os.path.join(backup_dir, folder)
        if os.path.isdir(folder_path):
            try:
                # Извлекаем дату и время из имени папки
                folder_date = datetime.strptime(folder, "%Y%m%d_%H%M%S")
                backup_files[folder_date] = folder
            except ValueError:
                logger.warning(f"Не удалось разобрать имя папки резервной копии: {folder}")

    # Сортировка по дате, от старых к новым
    sorted_dates = sorted(backup_files.keys())

    # Удаление старых версий, если их больше чем max_versions
    while len(sorted_dates) > max_versions:
        oldest_date = sorted_dates.pop(0)
        try:
            for file in os.listdir(os.path.join(backup_dir, backup_files[oldest_date])):
                os.remove(os.path.join(backup_dir, backup_files[oldest_date], file))
            os.rmdir(os.path.join(backup_dir, backup_files[oldest_date]))
            logger.bind(tags="backup_operations").info(
                f"Удалена старая папка резервной копии: {backup_files[oldest_date]}"
            )
        except OSError as e:
            logger.error(
                f"Ошибка при удалении папки резервной копии: {backup_files[oldest_date]}, ошибка: {e}"
            )

    # Удаление бэкапов старше 5 недель
    for file_date, folder in backup_files.items():
        if now - file_date > timedelta(weeks=5):
            try:
                for file in os.listdir(os.path.join(backup_dir, folder)):
                    os.remove(os.path.join(backup_dir, folder, file))
                os.rmdir(os.path.join(backup_dir, folder))
                logger.bind(tags="backup_operations").info(
                    f"Удалена устаревшая папка резервной копии: {folder}"
                )
            except OSError as e:
                logger.error(f"Ошибка при удалении папки резервной копии: {folder}, ошибка: {e}")


# Возвращает время работы бота в формате 'X дней - ЧЧ:ММ:СС'
def get_uptime():
    uptime = datetime.now() - bot_start_time
    days, seconds = uptime.days, uptime.seconds
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    seconds = seconds % 60
    return f"{days} дней - {hours:02}:{minutes:02}:{seconds:02}"


# Возвращает главное меню бота
async def get_main_menu(user_id):
    keyboard = [
        [KeyboardButton(text="Подписка на уведомления")],
        [KeyboardButton(text="Поддержка")],
        [KeyboardButton(text="О боте")],
    ]
    if user_id == ADMIN_ID:
        keyboard.append([KeyboardButton(text="Администрирование")])
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


# Обработчик команды /start
@dp.message(Command("start"))
async def start(message: types.Message):
    main_menu = await get_main_menu(message.from_user.id)
    await message.answer(
        "Добро пожаловать! Выберите интересующую вас опцию ниже:",
        reply_markup=main_menu,
    )
    logger.info(
        f"Пользователь {message.from_user.id} ({message.from_user.username}) запустил бота."
    )


# Обработчик нажатия на кнопку 'Подписка на уведомления'
@dp.message(F.text == "Подписка на уведомления")
async def subscribe(message: types.Message):
    db = await get_db_connection("subscribers.db")
    if db:
        async with db.execute(
            "SELECT subscription_type FROM subscribers WHERE chat_id = ?",
            (message.from_user.id,),
        ) as cursor:
            result = await cursor.fetchone()

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

        await message.answer(
            f"Настройте свою подписку:\n\nТекущая подписка: {current_subscription}",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Подписка на все уведомления",
                            callback_data="subscribe_all",
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="Подписка на обновления контента",
                            callback_data="subscribe_updates",
                        )
                    ],
                    [InlineKeyboardButton(text="Отписаться", callback_data="unsubscribe")],
                    [InlineKeyboardButton(text="Назад", callback_data="back_main")],
                ]
            ),
        )
        logger.info(
            f"Пользователь {message.from_user.id} ({message.from_user.username}) запросил меню подписки."
        )


# Обработчик нажатия на кнопку 'Подписка на все уведомления'
@dp.callback_query(F.data == "subscribe_all")
async def subscribe_all(callback_query: types.CallbackQuery):
    db = await get_db_connection("subscribers.db")
    if db:
        await db.execute(
            "INSERT OR REPLACE INTO subscribers (chat_id, username, subscription_type) VALUES (?, ?, ?)",
            (callback_query.from_user.id, callback_query.from_user.username, "all"),
        )
        await db.commit()
        await callback_query.answer("Вы подписаны на все уведомления.")
        await callback_query.message.edit_text(
            "Настройте свою подписку:\n\nТекущая подписка: Все уведомления",
            reply_markup=callback_query.message.reply_markup,
        )
        logger.info(
            f"Пользователь {callback_query.from_user.id} ({callback_query.from_user.username}) подписался на все уведомления."
        )


# Обработчик нажатия на кнопку 'Подписка на обновления контента'
@dp.callback_query(F.data == "subscribe_updates")
async def subscribe_updates(callback_query: types.CallbackQuery):
    db = await get_db_connection("subscribers.db")
    if db:
        await db.execute(
            "INSERT OR REPLACE INTO subscribers (chat_id, username, subscription_type) VALUES (?, ?, ?)",
            (callback_query.from_user.id, callback_query.from_user.username, "updates"),
        )
        await db.commit()
        await callback_query.answer("Вы подписаны на обновления.")
        await callback_query.message.edit_text(
            "Настройте свою подписку:\n\nТекущая подписка: Обновления",
            reply_markup=callback_query.message.reply_markup,
        )
        logger.info(
            f"Пользователь {callback_query.from_user.id} ({callback_query.from_user.username}) подписался на обновления."
        )


# Обработчик нажатия на кнопку 'Отписаться'
@dp.callback_query(F.data == "unsubscribe")
async def unsubscribe(callback_query: types.CallbackQuery):
    db = await get_db_connection("subscribers.db")
    if db:
        # Получаем ник пользователя перед удалением записи
        async with db.execute(
            "SELECT username FROM subscribers WHERE chat_id = ?",
            (callback_query.from_user.id,),
        ) as cursor:
            result = await cursor.fetchone()
            username = result[0] if result else None

        await db.execute(
            "DELETE FROM subscribers WHERE chat_id = ?", (callback_query.from_user.id,)
        )
        await db.commit()
        await callback_query.answer("Вы отписались от всех уведомлений.")
        # Редактируем сообщение, обновляя статус подписки
        await callback_query.message.edit_text(
            "Настройте свою подписку:\n\nТекущая подписка: Нет подписки",
            reply_markup=callback_query.message.reply_markup,
        )
        logger.info(
            f"Пользователь {callback_query.from_user.id} ({username if username else 'Неизвестный'}) отписался от уведомлений."
        )


# Обработчик нажатия на кнопку 'Поддержка'
@dp.message(F.text == "Поддержка")
async def support(message: types.Message):
    await message.answer(
        "Чем мы можем вам помочь?",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Отправить заявку", callback_data="send_ticket"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="Просмотр заявок", callback_data="view_tickets"
                    )
                ],
                [InlineKeyboardButton(text="Назад", callback_data="back_main")],
            ]
        ),
    )
    logger.info(
        f"Пользователь {message.from_user.id} ({message.from_user.username}) запросил меню поддержки."
    )


# Обработчик нажатия на кнопку 'Отправить заявку'
@dp.callback_query(F.data == "send_ticket")
async def send_ticket(callback_query: types.CallbackQuery, state: FSMContext):
    await callback_query.message.edit_text(
        "Опишите кратко вашу проблему:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Назад", callback_data="support_menu")]
            ]
        ),
    )
    await state.set_state(TicketFSM.problem)
    logger.info(
        f"Пользователь {callback_query.from_user.id} ({callback_query.from_user.username}) начал подачу заявки."
    )


# Обработчик ввода краткого описания проблемы
@dp.message(TicketFSM.problem)
async def enter_problem(message: types.Message, state: FSMContext):
    await state.update_data(problem=message.text)
    await message.answer("Дайте более подробное описание проблемы:")
    await state.set_state(TicketFSM.description)
    logger.info(
        f"Пользователь {message.from_user.id} ({message.from_user.username}) ввел краткое описание проблемы: {message.text}"
    )


# Обработчик ввода подробного описания проблемы
@dp.message(TicketFSM.description)
async def enter_description(message: types.Message, state: FSMContext):
    data = await state.get_data()
    problem = data.get("problem")
    description = message.text

    db = await get_db_connection("tickets.db")
    if db:
        await db.execute(
            "INSERT INTO tickets (user_id, username, problem, description, status) VALUES (?, ?, ?, ?, ?)",
            (message.from_user.id, message.from_user.username, problem, description, "Unresolved"),
        )
        await db.commit()
        async with db.execute("SELECT last_insert_rowid()") as cursor:
            ticket_id = (await cursor.fetchone())[0]

        await message.answer("Ваша заявка отправлена.")
        await state.clear()
        logger.info(
            f"Пользователь {message.from_user.id} ({message.from_user.username}) отправил заявку. ID заявки: {ticket_id}"
        )

        await bot.send_message(
            ADMIN_ID,
            f"Новая заявка:\nПроблема: {problem}\nОписание: {description}\nID заявки: {ticket_id}",
        )
        logger.info(f"Отправлено уведомление администратору о новой заявке (ID: {ticket_id}).")


# Обработчик нажатия на кнопку 'Просмотр заявок'
@dp.callback_query(F.data == "view_tickets")
async def view_tickets(callback_query: types.CallbackQuery):
    db = await get_db_connection("tickets.db")
    if db:
        async with db.execute(
            "SELECT * FROM tickets WHERE user_id = ?", (callback_query.from_user.id,)
        ) as cursor:
            user_tickets = await cursor.fetchall()

        if user_tickets:
            tickets_text = ""
            for row in user_tickets:
                ticket_info = (
                    f"Проблема: {row[3]}\nОписание: {row[4]}\nСтатус: {row[5]}"  # Изменены индексы
                )
                if row[5] == "Решено" and row[6]:  # Изменены индексы
                    ticket_info += f"\nОтвет: {row[6]}"  # Изменены индексы
                tickets_text += f"{ticket_info}\n\n"

            await callback_query.message.edit_text(
                f"Ваши заявки:\n\n{tickets_text}",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="Назад", callback_data="support_menu")]
                    ]
                ),
            )
            logger.info(
                f"Пользователь {callback_query.from_user.id} ({callback_query.from_user.username}) просмотрел свои заявки."
            )
        else:
            await callback_query.message.edit_text(
                "У вас нет отправленных заявок.",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="Назад", callback_data="support_menu")]
                    ]
                ),
            )
            logger.info(
                f"Пользователь {callback_query.from_user.id} ({callback_query.from_user.username}) не имеет отправленных заявок."
            )


# Обработчик нажатия на кнопку 'О боте'
@dp.message(F.text == "О боте")
async def about_bot(message: types.Message):
    await message.answer(
        f"Бот по отправке уведомлений о новом контенте и/или его исправлении на https://docs.basted.ru/.\n\n"
        f"Версия бота: {BOT_VERSION}"
    )
    logger.info(
        f"Пользователь {message.from_user.id} ({message.from_user.username}) запросил информацию о боте."
    )


# Обработчик нажатия на кнопку 'Администрирование'
@dp.message(F.text == "Администрирование")
async def admin(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        await message.answer(
            "Панель администратора:",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Отправить сообщение", callback_data="admin_broadcast"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="Управление заявками", callback_data="admin_tickets"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="Дополнительно", callback_data="admin_additional"
                        )
                    ],
                    [InlineKeyboardButton(text="Назад", callback_data="back_main")],
                ]
            ),
        )
        logger.info(
            f"Администратор {message.from_user.id} ({message.from_user.username}) вошел в панель администратора."
        )
    else:
        await message.answer("У вас нет доступа к этому разделу.")
        logger.warning(
            f"Пользователь {message.from_user.id} ({message.from_user.username}) пытался получить доступ к панели администратора."
        )


# Обработчик нажатия на кнопку 'Отправить сообщение'
@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_menu(callback_query: types.CallbackQuery, state: FSMContext):
    await callback_query.message.edit_text(
        "Выберите, кому будет отправлено сообщение:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Обновление (всем)", callback_data="broadcast_updates"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="Исправления", callback_data="broadcast_fixes"
                    )
                ],
                [InlineKeyboardButton(text="Назад", callback_data="admin_menu")],
            ]
        ),
    )
    await state.set_state(BroadcastFSM.select_type)
    logger.info(
        f"Администратор {callback_query.from_user.id} ({callback_query.from_user.username}) вошел в меню отправки сообщений."
    )


# Обработчик выбора типа рассылки
@dp.callback_query(F.data.startswith("broadcast_"))
async def enter_broadcast_content(callback_query: types.CallbackQuery, state: FSMContext):
    broadcast_type = callback_query.data.split("_")[1]
    await state.update_data(broadcast_type=broadcast_type)
    await callback_query.message.edit_text(
        "Отправьте текст сообщения и/или фотографию:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Назад", callback_data="admin_broadcast")]
            ]
        ),
    )
    await state.set_state(BroadcastFSM.enter_content)
    logger.info(
        f"Администратор {callback_query.from_user.id} ({callback_query.from_user.username}) выбрал тип рассылки: {broadcast_type}"
    )


# Обработчик отправки сообщения
@dp.message(BroadcastFSM.enter_content, F.text | F.photo)
async def send_broadcast(message: types.Message, state: FSMContext):
    data = await state.get_data()
    broadcast_type = data["broadcast_type"]

    text = message.caption if message.photo else message.text
    photo = message.photo[-1].file_id if message.photo else None

    db = await get_db_connection("subscribers.db")
    if db:
        if broadcast_type == "updates":
            async with db.execute(
                "SELECT chat_id FROM subscribers WHERE subscription_type IN ('all', 'updates')"
            ) as cursor:
                subscribers = await cursor.fetchall()
        elif broadcast_type == "fixes":
            async with db.execute(
                "SELECT chat_id FROM subscribers WHERE subscription_type = 'all'"
            ) as cursor:
                subscribers = await cursor.fetchall()

        success_count = 0
        error_count = 0
        for (chat_id,) in subscribers:
            try:
                if photo:
                    msg = await bot.send_photo(chat_id, photo=photo, caption=text)
                else:
                    msg = await bot.send_message(chat_id, text)
                success_count += 1
                await state.update_data({f"read_{msg.message_id}": []})  # Добавляем список для хранения прочитавших
            except Exception as e:
                logger.error(f"Ошибка при отправке сообщения пользователю {chat_id}: {e}")
                error_count += 1

        await message.answer(
            f"Сообщение успешно отправлено {success_count} пользователям. Ошибок при отправке: {error_count}."
        )
        await state.clear()
        logger.info(
            f"Администратор {message.from_user.id} ({message.from_user.username}) отправил сообщение типа '{broadcast_type}'. Успешно: {success_count}, ошибок: {error_count}."
        )

        await message.answer(
            "Панель администратора:",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Отправить сообщение", callback_data="admin_broadcast"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="Управление заявками", callback_data="admin_tickets"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="Дополнительно", callback_data="admin_additional"
                        )
                    ],
                    [InlineKeyboardButton(text="Назад", callback_data="back_main")],
                ]
            ),
        )


# Обработчик нажатия на кнопку 'Управление заявками'
@dp.callback_query(F.data == "admin_tickets")
async def admin_tickets_menu(callback_query: types.CallbackQuery):
    await callback_query.message.edit_text(
        "Управление заявками:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Просмотр нерешенных заявок",
                        callback_data="view_unresolved_tickets",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="Просмотр решенных заявок",
                        callback_data="view_resolved_tickets",
                    )
                ],
                [InlineKeyboardButton(text="Назад", callback_data="admin_menu")],
            ]
        ),
    )
    logger.info(
        f"Администратор {callback_query.from_user.id} ({callback_query.from_user.username}) вошел в меню управления заявками."
    )


# Обработчик нажатия на кнопку 'Дополнительно'
@dp.callback_query(F.data == "admin_additional")
async def admin_additional_menu(callback_query: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback_query.message.edit_text(
        "Дополнительные функции:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Статистика", callback_data="view_statistics"
                    )
                ],
                [InlineKeyboardButton(text="Просмотр логов", callback_data="view_logs")],
                [
                    InlineKeyboardButton(
                        text="Управление БД", callback_data="db_actions"
                    )
                ],
                [InlineKeyboardButton(text="Назад", callback_data="admin_menu")],
            ]
        ),
    )
    logger.info(
        f"Администратор {callback_query.from_user.id} ({callback_query.from_user.username}) вошел в меню 'Дополнительно'."
    )


# Обработчик нажатия на кнопку 'Просмотр нерешенных заявок'
@dp.callback_query(F.data == "view_unresolved_tickets")
async def view_unresolved_tickets(callback_query: types.CallbackQuery):
    db = await get_db_connection("tickets.db")
    if db:
        async with db.execute(
            "SELECT id, problem, description, status, username FROM tickets WHERE status IN ('Unresolved', 'In Progress')"
        ) as cursor:
            unresolved_tickets = await cursor.fetchall()

        if unresolved_tickets:
            tickets_text = ""
            for ticket in unresolved_tickets:
                ticket_id, problem, description, status, username = ticket
                tickets_text += (
                    f"Заявка №{ticket_id} от пользователя {username if username else 'Не указан'}\n"
                    f"Статус: {status}\n"
                    f"Проблема: {problem}\n"
                    f"Описание: {description}\n----\n"
                )

            await callback_query.message.edit_text(
                f"Нерешенные заявки:\n\n{tickets_text}",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="Решено (выбрать заявку)",
                                callback_data="select_resolved_ticket",
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                text="В процессе (выбрать заявку)",
                                callback_data="select_in_progress_ticket",
                            )
                        ],
                        [InlineKeyboardButton(text="Назад", callback_data="admin_tickets")],
                    ]
                ),
            )
            logger.info(
                f"Администратор {callback_query.from_user.id} ({callback_query.from_user.username}) просмотрел нерешенные заявки."
            )
        else:
            await callback_query.message.edit_text(
                "Нерешенных заявок не найдено.",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="Назад", callback_data="admin_tickets")]
                    ]
                ),
            )
            logger.info(
                f"Администратор {callback_query.from_user.id} ({callback_query.from_user.username}) не нашел нерешенных заявок."
            )


# Обработчик нажатия на кнопку 'Решено (выбрать заявку)'
@dp.callback_query(F.data == "select_resolved_ticket")
async def select_resolved_ticket(callback_query: types.CallbackQuery):
    db = await get_db_connection("tickets.db")
    if db:
        async with db.execute(
            "SELECT id, problem FROM tickets WHERE status IN ('Unresolved', 'In Progress')"
        ) as cursor:
            tickets = await cursor.fetchall()

        if tickets:
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=f"Заявка {ticket[0]}: {ticket[1]}",
                            callback_data=f"mark_resolved_{ticket[0]}",
                        )
                    ]
                    for ticket in tickets
                ]
                + [[InlineKeyboardButton(text="Назад", callback_data="view_unresolved_tickets")]]
            )
            await callback_query.message.edit_text(
                "Выберите заявку для установки статуса 'Решено':", reply_markup=keyboard
            )
            logger.info(
                f"Администратор {callback_query.from_user.id} ({callback_query.from_user.username}) выбрал заявку для установки статуса 'Решено'."
            )
        else:
            await callback_query.message.edit_text(
                "Нет заявок для выбора.",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="Назад", callback_data="view_unresolved_tickets"
                            )
                        ]
                    ]
                ),
            )
            logger.info(
                f"Администратор {callback_query.from_user.id} ({callback_query.from_user.username}) не нашел заявок для выбора (установка статуса 'Решено')."
            )


# Обработчик нажатия на кнопку 'В процессе (выбрать заявку)'
@dp.callback_query(F.data == "select_in_progress_ticket")
async def select_in_progress_ticket(callback_query: types.CallbackQuery):
    db = await get_db_connection("tickets.db")
    if db:
        async with db.execute(
            "SELECT id, problem FROM tickets WHERE status IN ('Unresolved', 'In Progress')"
        ) as cursor:
            tickets = await cursor.fetchall()

        if tickets:
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=f"Заявка {ticket[0]}: {ticket[1]}",
                            callback_data=f"mark_in_progress_{ticket[0]}",
                        )
                    ]
                    for ticket in tickets
                ]
                + [[InlineKeyboardButton(text="Назад", callback_data="view_unresolved_tickets")]]
            )
            await callback_query.message.edit_text(
                "Выберите заявку для установки статуса 'В процессе':", reply_markup=keyboard
            )
            logger.info(
                f"Администратор {callback_query.from_user.id} ({callback_query.from_user.username}) выбрал заявку для установки статуса 'В процессе'."
            )
        else:
            await callback_query.message.edit_text(
                "Нет заявок для выбора.",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="Назад", callback_data="view_unresolved_tickets"
                            )
                        ]
                    ]
                ),
            )
            logger.info(
                f"Администратор {callback_query.from_user.id} ({callback_query.from_user.username}) не нашел заявок для выбора (установка статуса 'В процессе')."
            )


# Обработчик установки статуса 'В процессе'
@dp.callback_query(F.data.startswith("mark_in_progress_"))
async def set_status_in_progress(callback_query: types.CallbackQuery):
    ticket_id = int(callback_query.data.split("_")[-1])
    db = await get_db_connection("tickets.db")
    if db:
        await db.execute(
            "UPDATE tickets SET status = 'In Progress' WHERE id = ?", (ticket_id,)
        )
        await db.commit()

        await callback_query.answer("Статус изменён на 'В процессе'.")
        await notify_user_about_status_change(ticket_id, "В процессе")
        logger.info(
            f"Администратор {callback_query.from_user.id} ({callback_query.from_user.username}) установил статус 'В процессе' для заявки {ticket_id}."
        )

        # Возвращаемся в меню просмотра нерешенных заявок
        await view_unresolved_tickets(callback_query)


# Обработчик установки статуса 'Решено'
@dp.callback_query(F.data.startswith("mark_resolved_"))
async def set_status_resolved(callback_query: types.CallbackQuery, state: FSMContext):
    ticket_id = int(callback_query.data.split("_")[-1])
    await state.update_data(ticket_id=ticket_id)
    # Сохраняем message_id сообщения, которое будем редактировать
    await state.update_data(message_id_to_edit=callback_query.message.message_id)
    await callback_query.message.answer(
        "Пожалуйста, напишите ответ для этой закрытой заявки:"
    )
    await state.set_state(TicketStatusFSM.response)
    logger.info(
        f"Администратор {callback_query.from_user.id} ({callback_query.from_user.username}) начал ввод ответа для заявки {ticket_id}."
    )


# Обработчик сохранения ответа для заявки со статусом 'Решено'
@dp.message(TicketStatusFSM.response)
async def save_resolved_response(message: types.Message, state: FSMContext):
    data = await state.get_data()
    ticket_id = data["ticket_id"]
    response = message.text
    message_id_to_edit = data["message_id_to_edit"]

    db = await get_db_connection("tickets.db")
    if db:
        await db.execute(
            "UPDATE tickets SET status = 'Resolved', response = ? WHERE id = ?",
            (response, ticket_id),
        )
        await db.commit()

        await message.answer("Заявка отмечена как решенная с вашим ответом.")
        await state.clear()
        await notify_user_about_status_change(ticket_id, "Решено", response)
        logger.info(
            f"Администратор {message.from_user.id} ({message.from_user.username}) установил статус 'Решено' для заявки {ticket_id} и ввел ответ."
        )

        # Редактируем сохраненное сообщение бота
        await bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=message_id_to_edit,
            text="Выберите действие:",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Просмотр нерешенных заявок",
                            callback_data="view_unresolved_tickets",
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="Просмотр решенных заявок",
                            callback_data="view_resolved_tickets",
                        )
                    ],
                    [InlineKeyboardButton(text="Назад", callback_data="admin_menu")],
                ]
            ),
        )


# Обработчик нажатия на кнопку 'Просмотр решенных заявок'
@dp.callback_query(F.data == "view_resolved_tickets")
async def view_resolved_tickets(callback_query: types.CallbackQuery):
    db = await get_db_connection("tickets.db")
    if db:
        async with db.execute(
            "SELECT id, problem, description, status, response, username FROM tickets WHERE status = 'Resolved'"  # Добавил username в запрос
        ) as cursor:
            resolved_tickets = await cursor.fetchall()

        if resolved_tickets:
            tickets_text = ""
            for ticket in resolved_tickets:
                ticket_info = (
                    f"Заявка №{ticket[0]} от пользователя {ticket[5] if ticket[5] else 'Не указан'}\n"
                    f"Проблема: {ticket[1]}\n"
                    f"Описание: {ticket[2]}\n"
                    f"Статус: {ticket[3]}\n"
                    f"Ответ: {ticket[4]}\n----\n"
                )
                tickets_text += ticket_info

            await callback_query.message.edit_text(
                f"Решенные заявки:\n\n{tickets_text}",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="Назад", callback_data="admin_tickets")]
                    ]
                ),
            )
            logger.info(
                f"Администратор {callback_query.from_user.id} ({callback_query.from_user.username}) просмотрел решенные заявки."
            )
        else:
            await callback_query.message.edit_text(
                "Решенные заявки отсутствуют.",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="Назад", callback_data="admin_tickets")]
                    ]
                ),
            )
            logger.info(
                f"Администратор {callback_query.from_user.id} ({callback_query.from_user.username}) не нашел решенных заявок."
            )


# Обработчик нажатия на кнопку 'Назад' в меню 'Поддержка'
@dp.callback_query(F.data == "support_menu")
async def support_menu(callback_query: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback_query.message.edit_text(
        "Чем мы можем вам помочь?",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Отправить заявку", callback_data="send_ticket"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="Просмотр заявок", callback_data="view_tickets"
                    )
                ],
                [InlineKeyboardButton(text="Назад", callback_data="back_main")],
            ]
        ),
    )
    logger.info(
        f"Пользователь {callback_query.from_user.id} ({callback_query.from_user.username}) вернулся в меню поддержки."
    )


# Обработчик нажатия на кнопку 'Назад' в главном меню администратора
@dp.callback_query(F.data == "admin_menu")
async def admin_menu_back(callback_query: types.CallbackQuery):
    await callback_query.message.edit_text(
        "Панель администратора:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Отправить сообщение", callback_data="admin_broadcast"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="Управление заявками", callback_data="admin_tickets"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="Дополнительно", callback_data="admin_additional"
                    )
                ],
                [InlineKeyboardButton(text="Назад", callback_data="back_main")],
            ]
        ),
    )
    logger.info(
        f"Администратор {callback_query.from_user.id} ({callback_query.from_user.username}) вернулся в главное меню администратора."
    )


# Обработчик нажатия на кнопку 'Назад' в главном меню
@dp.callback_query(F.data == "back_main")
async def back_to_main(callback_query: types.CallbackQuery):
    await callback_query.message.delete()
    # main_menu = await get_main_menu(callback_query.from_user.id)  - убрано по требованию
    logger.info(
        f"Пользователь {callback_query.from_user.id} ({callback_query.from_user.username}) вернулся в главное меню."
    )


# Уведомляет подписчиков с указанным типом подписки
async def notify_subscribers(subscription_type, text):
    db = await get_db_connection("subscribers.db")
    if db:
        async with db.execute(
            "SELECT chat_id FROM subscribers WHERE subscription_type=?",
            (subscription_type,),
        ) as cursor:
            subscribers = await cursor.fetchall()

        for (chat_id,) in subscribers:
            await bot.send_message(chat_id, text)


# Обработчик нажатия на кнопку 'Управление БД'
@dp.callback_query(F.data == "db_actions")
async def db_actions(callback_query: types.CallbackQuery):
    await callback_query.message.edit_text(
        "Управление БД (сброс и бэкап):",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Сброс базы данных", callback_data="reset_database"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="Создать бэкап баз данных", callback_data="create_backup"
                    )
                ],
                [InlineKeyboardButton(text="Назад", callback_data="admin_additional")],
            ]
        ),
    )
    logger.info(
        f"Администратор {callback_query.from_user.id} ({callback_query.from_user.username}) вошел в меню 'Управление БД'."
    )


# Обработчик нажатия на кнопку 'Создать бэкап'
@dp.callback_query(F.data == "create_backup")
async def create_backup_handler(callback_query: types.CallbackQuery, state: FSMContext):
    await callback_query.message.edit_text(
        "Вы уверены, что хотите создать резервную копию?",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Да", callback_data="confirm_create_backup")],
                [InlineKeyboardButton(text="Нет", callback_data="admin_additional")],
            ]
        ),
    )
    await state.set_state(CreateBackupFSM.confirmation)


# Обработчик подтверждения создания бэкапа
@dp.callback_query(F.data == "confirm_create_backup")
async def confirm_create_backup_handler(callback_query: types.CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        backup_folder_path = await create_backup()
        backup_folder_name = os.path.basename(backup_folder_path)
        await callback_query.message.edit_text(
            f"Резервные копии успешно созданы в папке: {backup_folder_name}",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Назад", callback_data="admin_additional"
                        )
                    ]
                ]
            ),
        )
    except Exception as e:
        logger.error(f"Ошибка при создании резервной копии: {e}")
        await callback_query.message.edit_text(
            f"Произошла ошибка при создании резервной копии: {e}",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Назад", callback_data="admin_additional"
                        )
                    ]
                ]
            ),
        )


# Обработчик нажатия на кнопку 'Сброс базы данных'
@dp.callback_query(F.data == "reset_database")
async def reset_database_select(callback_query: types.CallbackQuery):
    if callback_query.from_user.id == ADMIN_ID:
        await callback_query.message.edit_text(
            "Выберите базу данных для сброса:",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="Заявки", callback_data="reset_tickets")],
                    [
                        InlineKeyboardButton(
                            text="Подписчики", callback_data="reset_subscribers"
                        )
                    ],
                    [InlineKeyboardButton(text="Назад", callback_data="admin_additional")],
                ]
            ),
        )
        logger.info(
            f"Администратор {callback_query.from_user.id} ({callback_query.from_user.username}) вошел в меню сброса базы данных."
        )
    else:
        await callback_query.answer("У вас нет прав для выполнения этого действия.")
        logger.warning(
            f"Пользователь {callback_query.from_user.id} ({callback_query.from_user.username}) пытался сбросить базу данных."
        )


# Обработчик сброса выбранной базы данных
@dp.callback_query(F.data.startswith("reset_"))
async def reset_database(callback_query: types.CallbackQuery):
    db_to_reset = callback_query.data.split("_")[1]
    if callback_query.from_user.id == ADMIN_ID:
        if db_to_reset == "tickets":
            db = await get_db_connection("tickets.db")
            if db:
                await db.execute("DELETE FROM tickets")
                await db.execute("UPDATE sqlite_sequence SET seq = 0 WHERE name = 'tickets'")
                await db.commit()
                await callback_query.message.edit_text(
                    "База данных заявок сброшена.",
                    reply_markup=InlineKeyboardMarkup(
                        inline_keyboard=[
                            [
                                InlineKeyboardButton(
                                    text="Назад", callback_data="admin_additional"
                                )
                            ]
                        ]
                    ),
                )
                logger.info(
                    f"Администратор {callback_query.from_user.id} ({callback_query.from_user.username}) сбросил базу данных заявок."
                )
        elif db_to_reset == "subscribers":
            db = await get_db_connection("subscribers.db")
            if db:
                await db.execute("DELETE FROM subscribers")
                await db.commit()
                await callback_query.message.edit_text(
                    "База данных подписчиков сброшена.",
                    reply_markup=InlineKeyboardMarkup(
                        inline_keyboard=[
                            [
                                InlineKeyboardButton(
                                    text="Назад", callback_data="admin_additional"
                                )
                            ]
                        ]
                    ),
                )
                logger.info(
                    f"Администратор {callback_query.from_user.id} ({callback_query.from_user.username}) сбросил базу данных подписчиков."
                )
        else:
            await callback_query.answer("Неизвестная база данных.")
            logger.warning(
                f"Администратор {callback_query.from_user.id} ({callback_query.from_user.username}) пытался сбросить неизвестную базу данных: {db_to_reset}"
            )
    else:
        await callback_query.answer("У вас нет прав для выполнения этого действия.")
        logger.warning(
            f"Пользователь {callback_query.from_user.id} ({callback_query.from_user.username}) пытался сбросить базу данных."
        )


# Обработчик нажатия на кнопку 'Статистика'
@dp.callback_query(F.data == "view_statistics")
async def view_statistics(callback_query: types.CallbackQuery):
    if callback_query.from_user.id == ADMIN_ID:
        db_sub = await get_db_connection("subscribers.db")
        db_tic = await get_db_connection("tickets.db")

        if db_sub and db_tic:
            # Получение общего числа подписчиков
            async with db_sub.execute("SELECT COUNT(*) FROM subscribers") as cursor:
                total_subscribers = (await cursor.fetchone())[0]

            # Получение числа подписчиков по типам
            async with db_sub.execute(
                "SELECT subscription_type, COUNT(*) FROM subscribers GROUP BY subscription_type"
            ) as cursor:
                subscription_counts = await cursor.fetchall()

            
            # Получение общего числа заявок
            async with db_tic.execute("SELECT COUNT(*) FROM tickets") as cursor:
                total_tickets = (await cursor.fetchone())[0]

            # Получение числа решенных заявок
            async with db_tic.execute(
                "SELECT COUNT(*) FROM tickets WHERE status = 'Resolved'"
            ) as cursor:
                resolved_tickets = (await cursor.fetchone())[0]

            # Получение числа нерешенных заявок
            async with db_tic.execute(
                "SELECT COUNT(*) FROM tickets WHERE status IN ('Unresolved', 'In Progress')"
            ) as cursor:
                unresolved_tickets = (await cursor.fetchone())[0]

            # Форматирование времени работы бота
            uptime = get_uptime()

            # Форматирование данных о подписках
            subscription_details = "\n".join(
                [f"{stype}: {count}" for stype, count in subscription_counts]
            )

            # Получение информации о бэкапах
            tickets_backup_info, subscribers_backup_info = await get_backup_info()

            # Текст статистики
            stats_text = (
                f"Время работы бота: {uptime}\n"
                f"Версия бота: {BOT_VERSION}\n\n"
                f"Всего подписчиков: {total_subscribers}\n"
                f"Подписчики по типам:\n{subscription_details}\n\n"
                f"Всего заявок: {total_tickets}\n"
                f"Решенных заявок: {resolved_tickets}\n"
                f"Нерешенных заявок: {unresolved_tickets}\n\n"
                f"Последний бэкап заявок: {tickets_backup_info}\n"
                f"Последний бэкап подписчиков: {subscribers_backup_info}"
            )

            await callback_query.message.edit_text(
                stats_text,
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="Назад", callback_data="admin_additional")]
                    ]
                ),
            )
            logger.info(
                f"Администратор {callback_query.from_user.id} ({callback_query.from_user.username}) просмотрел статистику."
            )
    else:
        await callback_query.answer("У вас нет прав для выполнения этого действия.")
        logger.warning(
            f"Пользователь {callback_query.from_user.id} ({callback_query.from_user.username}) пытался просмотреть статистику."
        )


# Обработчик нажатия на кнопку 'Просмотр логов'
@dp.callback_query(F.data == "view_logs")
async def view_logs(callback_query: types.CallbackQuery):
    if callback_query.from_user.id == ADMIN_ID:
        try:
            log_file_path = os.path.join(log_dir, "error.log")
            lines_to_show = 20
            logs_text = ""
            lines = []

            with open(log_file_path, "rb") as log_file:
                log_file.seek(0, io.SEEK_END)
                file_size = log_file.tell()
                if file_size > 0:
                    cursor_position = file_size

                    while len(lines) < lines_to_show and cursor_position > 0:
                        cursor_position -= 1
                        log_file.seek(cursor_position, io.SEEK_SET)
                        char = log_file.read(1)
                        if char == b"\n":
                            line = log_file.readline().decode(
                                "utf-8", errors="replace"
                            ).strip()
                            if line:
                                lines.append(line)
                        elif cursor_position == 0:
                            log_file.seek(0, io.SEEK_SET)
                            line = log_file.readline().decode(
                                "utf-8", errors="replace"
                            ).strip()
                            if line:
                                lines.append(line)

                    logs_text = "\n".join(reversed(lines))
                else:
                    logs_text = "Лог файл пуст."

            await callback_query.message.edit_text(
                f"<b>Последние {len(lines)} строк логов:</b>\n<pre>{logs_text}</pre>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="Назад", callback_data="admin_additional"
                            )
                        ]
                    ]
                ),
            )
            logger.info(
                f"Администратор {callback_query.from_user.id} ({callback_query.from_user.username}) просмотрел логи."
            )
        except Exception as e:
            logger.opt(exception=True).error(
                f"Ошибка при чтении логов администратором {callback_query.from_user.id} ({callback_query.from_user.username})"
            )
            await callback_query.message.edit_text(
                f"Не удалось прочитать файл логов: {e}",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="Назад", callback_data="admin_additional"
                            )
                        ]
                    ]
                ),
            )

    else:
        await callback_query.answer("У вас нет доступа к этой функции.")
        logger.warning(
            f"Пользователь {callback_query.from_user.id} ({callback_query.from_user.username}) пытался просмотреть логи."
        )


# Уведомляет пользователя об изменении статуса заявки
async def notify_user_about_status_change(ticket_id, new_status, response=None):
    db = await get_db_connection("tickets.db")
    if db:
        async with db.execute(
            "SELECT user_id, problem FROM tickets WHERE id = ?", (ticket_id,)
        ) as cursor:
            result = await cursor.fetchone()
            if result:
                user_id, problem = result

                notification_message = (
                    f"Статус вашей заявки (ID: {ticket_id}, Проблема: {problem}) изменен на '{new_status}'."
                )
                if new_status == "Решено" and response:
                    notification_message += f"\nОтвет администратора: {response}"

                await bot.send_message(user_id, notification_message)
                logger.info(
                    f"Пользователю {user_id} отправлено уведомление об изменении статуса заявки {ticket_id} на '{new_status}'."
                )
            else:
                logger.warning(f"Не удалось найти заявку с ID {ticket_id} для уведомления пользователя.")


# Запускает бота
async def main():
    await init_ticket_db()
    await init_subscriber_db()
    asyncio.create_task(backup_databases())
    logger.bind(tags="startup_shutdown").info(f"Бот начал работу. Версия: {BOT_VERSION}")
    try:
        await dp.start_polling(bot)
    except Exception:
        logger.opt(exception=True).error(f"Произошла ошибка при запуске бота.")
    finally:
        await close_db_connection("tickets.db")
        await close_db_connection("subscribers.db")
        logger.bind(tags="startup_shutdown").info("Бот завершил работу.")


if __name__ == "__main__":
    asyncio.run(main())
