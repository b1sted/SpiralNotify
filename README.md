<p align="center">
  <img src="https://github.com/b1sted/SpiralNotify/blob/dev/.github/assets/logo.png" width="160" alt="SpiralNotify">
  <br>
    SpiralNotify
  <br>
</p>

<p align="center">
  <strong>
    An asynchronous Telegram notification bot built with
    <a href="https://github.com/aiogram/aiogram">aiogram</a> and
    <a href="https://github.com/omnilib/aiosqlite">aiosqlite</a>
  </strong>
</p>

<h2></h2>

<p align="center">
  <a href="#features"><img
    src="https://img.shields.io/badge/python-3.x-blue.svg"
    alt="Python Version"
  /></a>
  <a href="#installation"><img
    src="https://img.shields.io/badge/aiogram-3.x-green.svg"
    alt="aiogram"
  /></a>
  <a href="#dependencies"><img
    src="https://img.shields.io/badge/aiosqlite-✓-lightgrey.svg"
    alt="aiosqlite"
  /></a>
  <a href="#logging-"><img
    src="https://img.shields.io/badge/loguru-✓-brightgreen.svg"
    alt="loguru"
  /></a>
</p>

<p align="center">
  <img src="https://github.com/b1sted/SpiralNotify/blob/dev/.github/assets/screenshot.png" width="700" />
</p>

<p align="center">
  <a href="#overview">Overview</a> •
  <a href="#features">Features</a> •
  <a href="#prerequisites">Prerequisites</a> •
  <a href="#installation">Installation</a> •
  <a href="#configuration-">Configuration</a> •
  <a href="#running-the-bot-">Running</a> •
  <a href="#usage">Usage</a> •
  <a href="#logging-">Logging</a> •
  <a href="#backups-">Backups</a> •
  <a href="#dependencies">Dependencies</a>
</p>

<h2></h2>

## Overview

SpiralNotify is an asynchronous Telegram bot built with `aiogram`. Its primary purpose is to send notifications about new content or updates/fixes on a specific website (like `docs.basted.ru`) and provide a user support ticket system. It features distinct functionalities for regular users and an administrator.

## Features

### User Features
* **Subscription Management:**
    * Subscribe to receive *all* notifications (updates and fixes)
    * Subscribe to receive *only* content update notifications
    * Unsubscribe from notifications
    * View current subscription status
* **Support Tickets:**
    * Submit new support tickets with a problem title and detailed description
    * View the status and history of submitted tickets, including admin responses for resolved tickets
* **Bot Information:**
    * View basic information about the bot and its version

### Administrator Features
* **Broadcasting:**
    * Send broadcast messages to subscribers
    * Target broadcasts: Send to *all* subscribers or only those subscribed to *updates*
    * Send text messages or photos with captions
* **Ticket Management:**
    * View lists of unresolved and resolved tickets
    * Change ticket status (e.g., to "In Progress", "Resolved")
    * Provide written responses when resolving tickets (users are notified)
* **Bot Statistics:**
    * View bot uptime, version, total subscriber count, subscribers by type, total ticket count, resolved/unresolved ticket counts, and last backup timestamps
* **Logging:**
    * Access recent error logs directly through the bot interface
    * Detailed logging to separate files (`debug.log`, `error.log`, `startup_shutdown.log`, `backup_operations.log`)
* **Database Management:**
    * Manually trigger database backups
    * Reset (`DELETE FROM`) the tickets or subscribers database
* **Automated Backups:**
    * Automatic weekly backups of both `tickets.db` and `subscribers.db`
    * Automatic backup on bot startup
    * Automated cleanup of old backups (keeps the latest 5 versions, removes backups older than 5 weeks)

## Prerequisites

* Python 3.8+
* `pip` (Python package installer)

## Installation

Setting up SpiralNotify is straightforward:

1. **Clone the repository:**
   ```bash
   git clone https://github.com/b1sted/SpiralNotify.git
   cd SpiralNotify
   ```

2. **Create and activate a virtual environment (recommended):**
   ```bash
   python -m venv venv
   # On Windows:
   .\venv\Scripts\activate
   # On macOS/Linux:
   source venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

## Configuration ⚙️

The bot requires environment variables for configuration. Create a file named `.env` in the root project directory (`SpiralNotify/`) and add the following variables:

```dotenv
# .env file
BOT_TOKEN=YOUR_TELEGRAM_BOT_TOKEN
ADMIN_ID=YOUR_TELEGRAM_USER_ID
```

* `BOT_TOKEN`: Get this token from BotFather on Telegram.
* `ADMIN_ID`: Your unique Telegram User ID. You can find this by messaging bots like `@userinfobot`.

## Database Setup / Migration

1. **Initialization:** 
   
   The bot automatically creates and initializes the necessary SQLite databases (`tickets.db` and `subscribers.db`) in the project root directory if they don't exist when it starts.

2. **Schema Update (Username Column):** 
   
   The project includes a script `add_username_column.py` to ensure the `subscribers` and `tickets` tables have a `username` column. While the current `bot.py` initializes tables with this column, run this script if you are upgrading from an older version or want to be certain the schema is correct:
   ```bash
   python add_username_column.py
   ```
   This script safely adds the column if it's missing, preserving existing data.

## Running the Bot ▶️

Make sure your virtual environment is activated and the `.env` file is configured.

```bash
python bot.py
```

The bot will start, log its initialization, and begin polling for updates.

## Usage

### Users
* Start interacting with the bot by sending the `/start` command in Telegram.
* Use the main keyboard buttons ("Subscribe", "Support", "About Bot") to navigate features.
* Follow the inline keyboard prompts for specific actions like choosing subscription types or submitting tickets.

### Administrator
* If your Telegram User ID matches the `ADMIN_ID` in the `.env` file, you will see an "Administration" button on the main keyboard.
* Tap "Administration" to access the admin panel via inline keyboard buttons.
* **Broadcasting:** Navigate to "Send Message", choose the target audience ("Update (all)" or "Fixes"), and send the text or photo+caption you want to broadcast.
* **Ticket Management:** Navigate to "Manage Tickets" to view unresolved/resolved tickets. Select tickets to change their status or provide responses.
* **Other Functions:** Explore "Additional" for statistics, log viewing, and database management options.

## Logging 🪵

Logs are stored in the `log/` directory within the project folder.
* `debug.log`: Detailed debug information (rotates at 10MB).
* `error.log`: Warnings, errors, and exceptions (rotates weekly). Includes tracebacks.
* `startup_shutdown.log`: Bot start and stop events (rotates at 100MB).
* `backup_operations.log`: Information about manual and automatic backup creation/deletion (rotates weekly).

## Backups 💾

* **Location:** Backups are stored in the `backups/` directory, with each backup in a timestamped subfolder (e.g., `backups/20250415_014000/`).
* **Automation:** Backups run automatically on bot startup and then weekly.
* **Manual:** Admins can trigger backups via the "Administration" → "Additional" → "Manage DB" → "Create Backup" menu.
* **Cleanup:** The system automatically keeps the latest 5 backup folders and deletes any backup folders older than 5 weeks.

## Dependencies

* [aiogram](https://github.com/aiogram/aiogram): Asynchronous Telegram Bot API framework.
* [aiosqlite](https://github.com/omnilib/aiosqlite): Asynchronous interface for SQLite databases.
* [loguru](https://github.com/Delgan/loguru): Library for pleasant and powerful logging.
* [python-dotenv](https://github.com/theskumar/python-dotenv): Reads key-value pairs from a `.env` file and sets them as environment variables.

## Contributing

Contributions are welcome! Please feel free to submit pull requests or open issues for bugs, feature requests, or improvements.

## License

This project is licensed under the [GNU General Public License v3.0 (GPLv3)](https://www.gnu.org/licenses/gpl-3.0.en.html).  
Please refer to the full license text in the [LICENSE](LICENSE) file for details.
