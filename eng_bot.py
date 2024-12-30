import os
import logging
import sqlite3
import asyncio
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
GROUP_ID = int(os.getenv("GROUP_ID"))  # Group ID for specific group messages

# Set up logging
logging.basicConfig(level=logging.INFO)

# Initialize bot and dispatcher
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
bot_start_time = datetime.now()  # Bot start time for uptime tracking

# Initialize separate ticket and subscriber databases
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

# FSM for ticket submission
class TicketFSM(StatesGroup):
    problem = State()
    description = State()
    response = State()

# Define the FSM for managing ticket response input
class TicketStatusFSM(StatesGroup):
    response = State()
    
# Main menu keyboard
main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Subscribe")],
        [KeyboardButton(text="Support")],
        [KeyboardButton(text="About Bot")],
        [KeyboardButton(text="Administration")] if ADMIN_ID else []
    ],
    resize_keyboard=True
)

# Inline keyboard options for subscription, support, and administration
subscribe_menu = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="Subscribe to all notifications", callback_data="subscribe_all")],
        [InlineKeyboardButton(text="Subscribe to content updates only", callback_data="subscribe_updates")],
        [InlineKeyboardButton(text="Unsubscribe", callback_data="unsubscribe")],
        [InlineKeyboardButton(text="Back", callback_data="back_main")]
    ]
)

support_menu = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="Send Ticket", callback_data="send_ticket")],
        [InlineKeyboardButton(text="View Sent Tickets", callback_data="view_tickets")],
        [InlineKeyboardButton(text="Back", callback_data="back_main")]
    ]
)

admin_menu = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="View Unresolved Tickets", callback_data="view_unresolved_tickets")],
        [InlineKeyboardButton(text="View Resolved Tickets", callback_data="view_resolved_tickets")],
        [InlineKeyboardButton(text="Reset Database", callback_data="reset_database")],
        [InlineKeyboardButton(text="Statistics", callback_data="view_statistics")],
        [InlineKeyboardButton(text="Back", callback_data="back_main")]
    ]
)

# Format uptime in "X days - HH:MM:SS"
def get_uptime():
    uptime = datetime.now() - bot_start_time
    days, seconds = uptime.days, uptime.seconds
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    seconds = seconds % 60
    return f"{days} days - {hours:02}:{minutes:02}:{seconds:02}"

# Start command
@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer("Welcome to the bot! Choose an option:", reply_markup=main_menu)

# Subscribe menu
@dp.message(F.text == "Subscribe")
async def subscribe(message: types.Message):
    await message.answer("Manage your subscriptions:", reply_markup=subscribe_menu)

# Subscribe to all notifications
@dp.callback_query(lambda c: c.data == "subscribe_all")
async def subscribe_all(callback_query: types.CallbackQuery):
    conn = sqlite3.connect("subscribers.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO subscribers (chat_id, subscription_type) VALUES (?, ?)",
                   (callback_query.from_user.id, "all"))
    conn.commit()
    conn.close()
    await callback_query.answer("Subscribed to all notifications.")
    await callback_query.message.delete()  # Closes the menu

# Subscribe to content updates only
@dp.callback_query(lambda c: c.data == "subscribe_updates")
async def subscribe_updates(callback_query: types.CallbackQuery):
    conn = sqlite3.connect("subscribers.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO subscribers (chat_id, subscription_type) VALUES (?, ?)",
                   (callback_query.from_user.id, "updates"))
    conn.commit()
    conn.close()
    await callback_query.answer("Subscribed to content updates only.")
    await callback_query.message.delete()  # Closes the menu

# Unsubscribe
@dp.callback_query(lambda c: c.data == "unsubscribe")
async def unsubscribe(callback_query: types.CallbackQuery):
    conn = sqlite3.connect("subscribers.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM subscribers WHERE chat_id = ?", (callback_query.from_user.id,))
    conn.commit()
    conn.close()
    await callback_query.answer("Unsubscribed from all notifications.")
    await callback_query.message.delete()  # Closes the menu

# Support menu
@dp.message(F.text == "Support")
async def support(message: types.Message):
    await message.answer("How can we help you?", reply_markup=support_menu)

# Send Ticket: Start ticket submission
@dp.callback_query(lambda c: c.data == "send_ticket")
async def send_ticket(callback_query: types.CallbackQuery, state: FSMContext):
    await callback_query.message.answer("Please describe the problem (brief title):")
    await state.set_state(TicketFSM.problem)

@dp.message(TicketFSM.problem)
async def enter_problem(message: types.Message, state: FSMContext):
    await state.update_data(problem=message.text)
    await message.answer("Please provide a detailed description of the issue:")
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
    ticket_id = cursor.lastrowid  # Get the ticket ID for the new entry
    conn.commit()
    conn.close()

    await message.answer("Your ticket has been submitted.")
    await state.clear()

    # Notify admin of new ticket
    await bot.send_message(ADMIN_ID, f"New ticket submitted:\nProblem: {problem}\nDescription: {description}\nTicket ID: {ticket_id}")

# View Sent Tickets: Display user tickets
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
            ticket_info = f"Problem: {row[2]}\nDescription: {row[3]}\nStatus: {row[4]}"
            if row[4] == "Resolved" and row[5]:
                ticket_info += f"\nResponse: {row[5]}"
            tickets_text += f"{ticket_info}\n\n"

        await callback_query.message.answer(f"Your Tickets:\n{tickets_text}", reply_markup=support_menu)
    else:
        await callback_query.message.answer("You have no submitted tickets.", reply_markup=support_menu)

# About Bot command
@dp.message(F.text == "About Bot")
async def about_bot(message: types.Message):
    await message.answer("This bot provides notifications and support services. Customize this message as needed.")

# Administration menu (for admin only)
@dp.message(F.text == "Administration")
async def admin(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        await message.answer("Administration Panel:", reply_markup=admin_menu)
    else:
        await message.answer("Unauthorized access.")

# Handler to view unresolved tickets and provide status change options
@dp.callback_query(lambda c: c.data == "view_unresolved_tickets")
async def view_unresolved_tickets(callback_query: types.CallbackQuery):
    conn = sqlite3.connect("tickets.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, problem, description FROM tickets WHERE status = 'Unresolved'")
    unresolved_tickets = cursor.fetchall()
    conn.close()

    if unresolved_tickets:
        for ticket in unresolved_tickets:
            await callback_query.message.answer(
                f"Ticket ID: {ticket[0]}\nProblem: {ticket[1]}\nDescription: {ticket[2]}",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(text="Resolved", callback_data=f"change_status_resolved_{ticket[0]}"),
                        InlineKeyboardButton(text="In Progress", callback_data=f"change_status_inprogress_{ticket[0]}"),
                    ],
                    [InlineKeyboardButton(text="Back", callback_data="back_main")]
                ])
            )
    else:
        await callback_query.answer("No unresolved tickets found.")

# Handler for setting status to "In Progress"
@dp.callback_query(lambda c: c.data.startswith("change_status_inprogress_"))
async def set_status_in_progress(callback_query: types.CallbackQuery):
    ticket_id = int(callback_query.data.split("_")[-1])
    conn = sqlite3.connect("tickets.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE tickets SET status = 'In Progress' WHERE id = ?", (ticket_id,))
    conn.commit()
    conn.close()

    await callback_query.answer("Status updated to 'In Progress'.")
    await notify_user_about_status_change(ticket_id, "In Progress")

# Handler for setting status to "Resolved" and prompting admin to write a response
@dp.callback_query(lambda c: c.data.startswith("change_status_resolved_"))
async def set_status_resolved(callback_query: types.CallbackQuery, state: FSMContext):
    ticket_id = int(callback_query.data.split("_")[-1])
    await state.update_data(ticket_id=ticket_id)  # Save the ticket ID in the FSM context
    await callback_query.message.answer("Please write a response for this resolved ticket:")
    await state.set_state(TicketStatusFSM.response)

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

    await message.answer("The ticket has been marked as resolved with your response.")
    await state.clear()
    await notify_user_about_status_change(ticket_id, "Resolved", response)

# Function to notify user about the status change
async def notify_user_about_status_change(ticket_id, new_status, response=None):
    conn = sqlite3.connect("tickets.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, problem FROM tickets WHERE id = ?", (ticket_id,))
    user_id, problem = cursor.fetchone()
    conn.close()

    # Construct notification message for the user
    notification_message = f"Your ticket (ID: {ticket_id}, Problem: {problem}) has been updated to '{new_status}'."
    if new_status == "Resolved" and response:
        notification_message += f"\nResponse from admin: {response}"

    # Send notification to the user
    await bot.send_message(user_id, notification_message)

# Обработчик для кнопки "View Resolved Tickets", отображает все разрешенные заявки
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
                f"Problem: {ticket[1]}\n"
                f"Description: {ticket[2]}\n"
                f"Status: {ticket[3]}\n"
                f"Response: {ticket[4]}\n\n"
            )
            tickets_text += ticket_info

        await callback_query.message.answer(f"Resolved Tickets:\n{tickets_text}", reply_markup=admin_menu)
    else:
        await callback_query.message.answer("No resolved tickets found.", reply_markup=admin_menu)

# Handle messages from specific group and send notifications
@dp.message(lambda message: message.chat.id == GROUP_ID)
async def parse_group_message(message: types.Message):
    # Split the message text to separate the first paragraph from the rest
    paragraphs = message.text.split('\n', 1)
    if len(paragraphs) > 1:
        first_paragraph, remaining_text = paragraphs[0], paragraphs[1]
    else:
        first_paragraph, remaining_text = message.text, ""

    # Determine which group of subscribers to notify
    if first_paragraph.strip() == "Update":
        # Send to all subscribers
        await notify_subscribers("all", remaining_text)
        await notify_subscribers("updates", remaining_text)
    elif first_paragraph.strip() == "Fixes":
        # Send only to subscribers of "all"
        await notify_subscribers("all", remaining_text)

# Notify subscribers based on subscription type
async def notify_subscribers(subscription_type, text):
    conn = sqlite3.connect("subscribers.db")
    cursor = conn.cursor()
    cursor.execute("SELECT chat_id FROM subscribers WHERE subscription_type=?", (subscription_type,))
    subscribers = cursor.fetchall()
    conn.close()

    # Send the message to each subscriber in the specified subscription group
    for (chat_id,) in subscribers:
        await bot.send_message(chat_id, text)

# Reset Database (admin only)
@dp.callback_query(lambda c: c.data == "reset_database")
async def reset_database(callback_query: types.CallbackQuery):
    if callback_query.from_user.id == ADMIN_ID:
        conn = sqlite3.connect("tickets.db")
        cursor = conn.cursor()
        cursor.execute("DELETE FROM tickets")
        conn.commit()
        conn.close()
        await callback_query.answer("Database has been reset.")
    else:
        await callback_query.answer("Unauthorized action.")

# Statistics (admin only)
@dp.callback_query(lambda c: c.data == "view_statistics")
async def view_statistics(callback_query: types.CallbackQuery):
    if callback_query.from_user.id == ADMIN_ID:
        conn = sqlite3.connect("subscribers.db")
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM subscribers")
        total_subscribers = cursor.fetchone()[0]

        cursor.execute("SELECT subscription_type, COUNT(*) FROM subscribers GROUP BY subscription_type")
        subscription_counts = cursor.fetchall()

        uptime = get_uptime()
        conn.close()

        subscription_details = "\n".join([f"{stype}: {count}" for stype, count in subscription_counts])
        stats_text = (
            f"Total Subscribers: {total_subscribers}\n"
            f"Subscribers by Type:\n{subscription_details}\n"
            f"Bot Uptime: {uptime}\n"
            f"Bot Version: 21.6"
        )
        await callback_query.message.answer(stats_text, reply_markup=admin_menu)
    else:
        await callback_query.answer("Unauthorized action.")

# Back button handler
@dp.callback_query(lambda c: c.data == "back_main")
async def back_to_main(callback_query: types.CallbackQuery):
    await callback_query.message.delete()

# Run bot
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
