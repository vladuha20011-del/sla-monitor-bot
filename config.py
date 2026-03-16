import os
from dotenv import load_dotenv

load_dotenv()

# Токен Telegram бота
BOT_TOKEN = os.getenv("BOT_TOKEN", "8518207763:AAGySQdpoYh1dvzcRqgKA-Bfx8PidbeHFmU")

# ID чата
CHAT_ID = os.getenv("CHAT_ID", -1003860414028)

# Настройки API сервиса
API_URL = os.getenv("API_URL", "https://support.sbertroika.ru")
API_TOKEN = os.getenv("API_TOKEN", "ODUxMTgzODUyODkyOm5XL0uISXn8vaT1VLN/FnQYss1K")
API_TIMEOUT = 30

# Настройки SLA
SLA_HOURS = 24
CHECK_INTERVAL_MINUTES = 180

# Формат даты
DATE_FORMAT = "%Y-%m-%d"

# Часовой пояс
TIMEZONE = "Europe/Moscow"

# Логирование
LOG_LEVEL = "INFO"
LOG_FILE = "sla_bot.log"
DEBUG_MODE = True

# Настройка тегов
TAG_START_HOUR = 9      # (МСК)
TAG_END_HOUR = 18       # (МСК)
TAG_ENABLED = True      # Включить/выключить теги
