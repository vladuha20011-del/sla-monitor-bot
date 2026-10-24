import os
from dotenv import load_dotenv

load_dotenv()

# Токен Telegram бота
BOT_TOKEN = os.getenv("BOT_TOKEN", "удален")

# ID чата
CHAT_ID = os.getenv("CHAT_ID", -удален)

# Настройки API сервиса
API_URL = os.getenv("API_URL", "удалено")
API_TOKEN = os.getenv("API_TOKEN", "удален")
API_TIMEOUT = 30

# Принудительное использование IPv6
FORCE_IPV6 = True

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
TAG_WORKDAYS_ONLY = True    # Тегать только по будням
