"""
Основной бот для мониторинга SLA с поддержкой команд
Использует простой polling без Application и без Markdown
"""

import asyncio
import logging
import sys
import os
import re
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

from telegram import Bot, Update, ChatMember
from telegram.constants import ParseMode
from telegram.error import TelegramError

import config
from api_client import TaskAPIClient
from employees import find_employee_by_name, get_all_telegram_mentions, EMPLOYEES

# Настройка логирования
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename=config.LOG_FILE
)
logger = logging.getLogger(__name__)

class SLABot:
    """Бот для мониторинга SLA задач"""
    
    def __init__(self):
        self.bot = Bot(token=config.BOT_TOKEN)
        self.api_client = TaskAPIClient()
        self.chat_id = config.CHAT_ID
        self.notified_tasks = set()  # Храним ID задач, о которых уже уведомили
        self.is_running = True
        self.last_update_id = 0
    
    async def is_user_admin(self, chat_id: int, user_id: int) -> bool:
        """
        Проверяет, является ли пользователь администратором в чате
        """
        try:
            # Получаем информацию о пользователе в чате
            chat_member = await self.bot.get_chat_member(chat_id, user_id)
            
            # Проверяем статус
            return chat_member.status in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]
        except Exception as e:
            logger.error(f"Ошибка при проверке прав администратора: {e}")
            return False
    
    async def check_tasks(self):
        """Проверяет задачи и отправляет уведомления ТОЛЬКО для сотрудников из базы"""
        if not self.is_running:
            return
        
        logger.info("🔄 Проверка задач...")
        
        try:
            # Получаем задачи из API
            tasks = await self.api_client.get_tasks()
            
            if not tasks:
                logger.info("✅ Нет задач")
                return
            
            # Фильтруем задачи: только те, где исполнитель есть в базе
            employee_tasks = []
            for task in tasks:
                employee = find_employee_by_name(task['assignee'])
                if employee:  # Если сотрудник найден в базе
                    employee_tasks.append(task)
            
            logger.info(f"📊 Задач от сотрудников из базы: {len(employee_tasks)}")
            
            # Из них отбираем те, что требуют уведомления
            tasks_to_notify = [t for t in employee_tasks if t.get('should_notify', False)]
            
            logger.info(f"📊 Задач для уведомления (только сотрудники из базы): {len(tasks_to_notify)}")
            
            for task in tasks_to_notify:
                if not self.is_running:
                    break
                await self.send_notification(task)
                
        except Exception as e:
            logger.error(f"❌ Ошибка при проверке задач: {e}", exc_info=True)
    
    async def send_notification(self, task: Dict[str, Any]):
        """Отправляет уведомление о задаче"""
        task_id = task['id']
        
        # Проверяем, не отправляли ли уже уведомление
        if task_id in self.notified_tasks:
            return
        
        # Находим сотрудника по имени
        employee = find_employee_by_name(task['assignee'])
        
        # Формируем упоминание исполнителя (employee всегда есть, потому что мы отфильтровали)
        if employee:
            mention = f"{task['assignee']} {employee['telegram_username']}"
        else:
            mention = f"{task['assignee']}"  # Сюда не должны попадать, но оставим на всякий случай
        
        # Формируем сообщение (без Markdown)
        hours_left = task['hours_until_due']
        time_str = self._format_time(hours_left)
        sla_status = self._get_sla_status(hours_left)
        
        message = (
            f"⚠️ Внимание! Приближается SLA!\n\n"
            f"📌 Задача: {task['id']}\n"
            f"🔗 Ссылка: {task['url']}\n"
            f"📋 Название: {task['title']}\n"
            f"👤 Исполнитель: {mention}\n"
            f"⏰ Дедлайн: {task['due_date'].strftime('%d.%m.%Y %H:%M')}\n"
            f"⌛ Осталось: {time_str}\n"
            f"📊 {sla_status}\n"
            f"📈 Статус: {task['status']}\n"
            f"🎯 Приоритет: {task['priority'] or 'Не указан'}\n\n"
            f"Обрати внимание на задачу!"
        )
        
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                disable_web_page_preview=True
            )
            
            if employee:
                logger.info(f"✅ Уведомление для {task_id} -> {employee['telegram_username']}")
            else:
                logger.info(f"✅ Уведомление для {task_id} -> {task['assignee']} (не в базе)")
            
            self.notified_tasks.add(task_id)
            
        except TelegramError as e:
            logger.error(f"❌ Ошибка отправки: {e}")
    
    def _format_time(self, hours: float) -> str:
        """Форматирует время до дедлайна"""
        if hours < 0:
            return f"⚠️ ПРОСРОЧЕНО на {abs(hours):.1f}ч"
        elif hours < 1:
            minutes = int(hours * 60)
            return f"⏰ {minutes} минут"
        elif hours < 24:
            return f"⏰ {hours:.1f} часов"
        else:
            days = int(hours / 24)
            remaining_hours = hours % 24
            return f"⏰ {days}д {remaining_hours:.0f}ч"
    
    def _get_sla_status(self, hours: float) -> str:
        """Возвращает статус SLA на основе оставшегося времени"""
        if hours < 0:
            return "⚠️ ПРОСРОЧЕНО"
        elif hours < 12:
            return "🔴 Критично (менее 12 часов)"
        elif hours < 24:
            return "🟡 Скоро истекает (менее 24 часов)"
        else:
            return "🟢 В норме"
    
    def _format_assignee(self, api_name: str) -> str:
        """Форматирует имя исполнителя: имя из API + (тег) если есть в базе"""
        employee = find_employee_by_name(api_name)
        if employee:
            return f"{api_name} {employee['telegram_username']}"
        else:
            return api_name
    
    async def get_task_by_key(self, task_key: str) -> Optional[Dict]:
        """Получает конкретную задачу по ключу через прямой запрос"""
        try:
            # Прямой запрос к API
            task_data = await self.api_client.get_task_by_key(task_key)
            
            if not task_data:
                return None
            
            # Преобразуем в нужный формат
            fields = task_data.get('fields', {})
            assignee_data = fields.get('assignee')
            
            # Получаем имя исполнителя из API
            assignee_name = self.api_client._extract_assignee(assignee_data)
            
            # Получаем дату SLA
            due_date, sla_source = self.api_client._extract_sla_date(fields)
            
            if due_date:
                now = datetime.now()
                if due_date.tzinfo is not None:
                    due_date = due_date.replace(tzinfo=None)
                hours_until_due = (due_date - now).total_seconds() / 3600
                
                task = {
                    "id": task_data.get('key'),
                    "key": task_data.get('key'),
                    "title": fields.get('summary', 'Без названия'),
                    "assignee": assignee_name,  # Имя из API
                    "assignee_raw": assignee_data,  # Оригинальные данные
                    "due_date": due_date,
                    "hours_until_due": hours_until_due,
                    "should_notify": 0 < hours_until_due <= config.SLA_HOURS,
                    "status": fields.get('status', {}).get('name') if fields.get('status') else 'Неизвестно',
                    "status_id": fields.get('status', {}).get('id') if fields.get('status') else None,
                    "priority": fields.get('priority', {}).get('name') if fields.get('priority') else None,
                    "url": f"{self.api_client.base_url}/browse/{task_data.get('key')}",
                    "due_date_source": sla_source
                }
                return task
            
            return None
            
        except Exception as e:
            logger.error(f"Ошибка при получении задачи {task_key}: {e}")
            return None
    
    async def handle_updates(self):
        """Обрабатывает входящие команды"""
        try:
            updates = await self.bot.get_updates(offset=self.last_update_id + 1, timeout=30)
            
            for update in updates:
                self.last_update_id = update.update_id
                
                if update.message and update.message.text:
                    text = update.message.text.strip()
                    chat_id = update.message.chat_id
                    user_id = update.message.from_user.id
                    
                    # Разбираем команду и аргументы
                    parts = text.split()
                    full_command = parts[0].lower()
                    
                    # ИЗВЛЕКАЕМ БАЗОВУЮ КОМАНДУ (отрезаем @username если есть)
                    if '@' in full_command:
                        base_command = full_command.split('@')[0]
                        logger.debug(f"Команда с @username: {full_command} -> базовая: {base_command}")
                    else:
                        base_command = full_command
                        logger.debug(f"Команда без @username: {base_command}")
                    
                    # Обрабатываем команды по base_command
                    if base_command == '/start':
                        await self.bot.send_message(
                            chat_id=chat_id,
                            text=(
                                "✅ Бот мониторинга SLA\n\n"
                                "📋 Доступные команды:\n"
                                "/alarm - показать все задачи с истекающим SLA\n"
                                "/checking_dep - показать задачи только сотрудников отдела\n"
                                "/check - проверить конкретную задачу (Например: /check ZZ-123456)"
                            )
                        )
                    
                    elif base_command == '/help':
                        help_text = (
                            "🤖 Команды бота:\n\n"
                            "/alarm - показать все задачи с истекающим SLA\n"
                            "/checking_dep - показать задачи только сотрудников отдела\n"
                            "/check - проверить конкретную задачу (Например: /check ZZ-12345)"
                        )
                        await self.bot.send_message(
                            chat_id=chat_id,
                            text=help_text
                        )
                    
                    elif base_command == '/alarm':
                        await self.bot.send_message(
                            chat_id=chat_id,
                            text="🔍 Проверяю все задачи с истекающим SLA..."
                        )
                        
                        # Получаем задачи
                        tasks = await self.api_client.get_tasks()
                        urgent_tasks = [t for t in tasks if t.get('should_notify', False)]
                        
                        if not urgent_tasks:
                            await self.bot.send_message(
                                chat_id=chat_id,
                                text="✅ Нет задач с истекающим SLA (в ближайшие 24 часа)"
                            )
                            continue
                        
                        # Формируем сообщение СО ВСЕМИ задачами
                        msg = f"⚠️ Найдено задач с истекающим SLA: {len(urgent_tasks)}\n\n"
                        
                        # Сортируем по времени до дедлайна (сначала самые срочные)
                        urgent_tasks.sort(key=lambda x: x['hours_until_due'])
                        
                        for task in urgent_tasks:
                            # Форматируем исполнителя: имя из API + (тег) если есть
                            assignee_formatted = self._format_assignee(task['assignee'])
                            
                            # Добавляем статус SLA
                            sla_status = self._get_sla_status(task['hours_until_due'])
                            
                            msg += (
                                f"📌 {task['id']}\n"
                                f"👤 {assignee_formatted}\n"
                                f"📋 {task['title'][:50]}...\n"
                                f"⏰ {task['due_date'].strftime('%d.%m.%Y %H:%M')}\n"
                                f"⌛ Осталось: {self._format_time(task['hours_until_due'])}\n"
                                f"📊 {sla_status}\n"
                                f"📈 Статус задачи: {task['status']}\n"
                                f"🔗 {task['url']}\n\n"
                            )
                            
                            # Telegram имеет лимит на длину сообщения (4096 символов)
                            if len(msg) > 3500:
                                await self.bot.send_message(
                                    chat_id=chat_id,
                                    text=msg,
                                    disable_web_page_preview=True
                                )
                                msg = ""
                        
                        if msg:
                            await self.bot.send_message(
                                chat_id=chat_id,
                                text=msg,
                                disable_web_page_preview=True
                            )
                    
                    elif base_command == '/checking_dep':
                        await self.bot.send_message(
                            chat_id=chat_id,
                            text="🔍 Проверяю задачи только сотрудников отдела..."
                        )
                        
                        # Получаем задачи
                        tasks = await self.api_client.get_tasks()
                        
                        # Фильтруем задачи только тех, чьи исполнители есть в EMPLOYEES
                        dep_tasks = []
                        for task in tasks:
                            employee = find_employee_by_name(task['assignee'])
                            if employee:  # Если сотрудник найден в базе
                                dep_tasks.append(task)
                        
                        if not dep_tasks:
                            await self.bot.send_message(
                                chat_id=chat_id,
                                text="✅ Нет задач у сотрудников из базы"
                            )
                            continue
                        
                        # Фильтруем задачи с истекающим SLA
                        urgent_dep_tasks = [t for t in dep_tasks if t.get('should_notify', False)]
                        
                        if not urgent_dep_tasks:
                            await self.bot.send_message(
                                chat_id=chat_id,
                                text="✅ У сотрудников из базы нет задач с истекающим SLA"
                            )
                            continue
                        
                        # Формируем сообщение
                        msg = f"⚠️ Найдено задач у сотрудников из базы: {len(urgent_dep_tasks)}\n\n"
                        
                        # Сортируем по времени до дедлайна
                        urgent_dep_tasks.sort(key=lambda x: x['hours_until_due'])
                        
                        for task in urgent_dep_tasks:
                            employee = find_employee_by_name(task['assignee'])
                            assignee_formatted = f"{task['assignee']} {employee['telegram_username']}"
                            sla_status = self._get_sla_status(task['hours_until_due'])
                            
                            msg += (
                                f"📌 {task['id']}\n"
                                f"👤 {assignee_formatted}\n"
                                f"📋 {task['title'][:50]}...\n"
                                f"⏰ {task['due_date'].strftime('%d.%m.%Y %H:%M')}\n"
                                f"⌛ Осталось: {self._format_time(task['hours_until_due'])}\n"
                                f"📊 {sla_status}\n"
                                f"📈 Статус задачи: {task['status']}\n"
                                f"🔗 {task['url']}\n\n"
                            )
                            
                            if len(msg) > 3500:
                                await self.bot.send_message(
                                    chat_id=chat_id,
                                    text=msg,
                                    disable_web_page_preview=True
                                )
                                msg = ""
                        
                        if msg:
                            await self.bot.send_message(
                                chat_id=chat_id,
                                text=msg,
                                disable_web_page_preview=True
                            )
                    
                    elif base_command == '/check':
                        # Проверяем, есть ли аргумент (номер задачи)
                        if len(parts) < 2:
                            await self.bot.send_message(
                                chat_id=chat_id,
                                text="❌ Укажите номер задачи\n\nПример: /check ZZ-12345"
                            )
                            continue
                        
                        task_key = parts[1].upper()
                        
                        # Проверяем формат задачи
                        if not re.match(r'^ZZ-\d+$', task_key, re.IGNORECASE):
                            await self.bot.send_message(
                                chat_id=chat_id,
                                text="❌ Неверный формат задачи\n\nИспользуйте формат: ZZ-12345"
                            )
                            continue
                        
                        await self.bot.send_message(
                            chat_id=chat_id,
                            text=f"🔍 Ищу задачу {task_key}..."
                        )
                        
                        # Получаем задачу через прямой запрос
                        task = await self.get_task_by_key(task_key)
                        
                        if not task:
                            await self.bot.send_message(
                                chat_id=chat_id,
                                text=f"❌ Задача {task_key} не найдена.\n\nВозможно, задача уже закрыта или не существует."
                            )
                            continue
                        
                        # Форматируем исполнителя: имя из API + (тег) если есть
                        assignee_formatted = self._format_assignee(task['assignee'])
                        
                        # Получаем статус SLA
                        hours = task['hours_until_due']
                        sla_status = self._get_sla_status(hours)
                        
                        # Формируем сообщение
                        task_info = (
                            f"📌 Задача: {task['id']}\n"
                            f"📋 Название: {task['title']}\n"
                            f"🔗 Ссылка: {task['url']}\n\n"
                            f"👤 Исполнитель: {assignee_formatted}\n"
                            f"⏰ Дедлайн: {task['due_date'].strftime('%d.%m.%Y %H:%M')}\n"
                            f"⌛ Осталось: {self._format_time(hours)}\n"
                            f"📊 {sla_status}\n"
                            f"📈 Статус задачи: {task['status']}\n"
                            f"🎯 Приоритет: {task['priority'] or 'Не указан'}"
                        )
                        
                        await self.bot.send_message(
                            chat_id=chat_id,
                            text=task_info,
                            disable_web_page_preview=True
                        )
                    
                    elif base_command == '/update':
                        # Проверяем права администратора
                        is_admin = await self.is_user_admin(chat_id, user_id)
                        
                        if not is_admin:
                            await self.bot.send_message(
                                chat_id=chat_id,
                                text="❌ У вас нет прав на выполнение этой команды."
                            )
                            logger.warning(f"Пользователь {user_id} попытался использовать /update без прав админа")
                            continue
                        
                        await self.bot.send_message(
                            chat_id=chat_id,
                            text="🛑 Бот уходит на обновление\n\n⏸ Проверка задач временно приостановлена.\n🔄 Скоро бот будет запущен снова."
                        )
                        logger.info(f"🛑 Останавливаем бота по команде от администратора {user_id}")
                        self.is_running = False
                        await asyncio.sleep(2)
                        sys.exit(0)
                    
                    elif base_command == '/restart':
                        # Проверяем права администратора
                        is_admin = await self.is_user_admin(chat_id, user_id)
                        
                        if not is_admin:
                            await self.bot.send_message(
                                chat_id=chat_id,
                                text="❌ У вас нет прав на выполнение этой команды."
                            )
                            logger.warning(f"Пользователь {user_id} попытался использовать /restart без прав админа")
                            continue
                        
                        await self.bot.send_message(
                            chat_id=chat_id,
                            text="🔄 Рестарт бота..."
                        )
                        logger.info(f"🔄 Рестартаем бота по команде от администратора {user_id}")
                        self.is_running = False
                        await asyncio.sleep(2)
                        python = sys.executable
                        os.execl(python, python, *sys.argv)
                    
                    else:
                        # Неизвестная команда
                        await self.bot.send_message(
                            chat_id=chat_id,
                            text="❌ Неизвестная команда\n\nНапишите /help для списка команд"
                        )
                        
        except Exception as e:
            logger.error(f"Ошибка при обработке команд: {e}")
            try:
                await self.bot.send_message(
                    chat_id=chat_id if 'chat_id' in locals() else self.chat_id,
                    text=f"❌ Ошибка при выполнении команды\n\n{str(e)[:200]}"
                )
            except:
                pass
    
    async def run_forever(self):
        """Запускает бесконечный цикл"""
        logger.info(f"🚀 Бот запущен. Интервал проверки: 60 минут")
        
        # Сначала получаем последний update_id
        try:
            updates = await self.bot.get_updates()
            if updates:
                self.last_update_id = updates[-1].update_id
                logger.info(f"📝 Последний update_id: {self.last_update_id}")
        except Exception as e:
            logger.error(f"Ошибка при получении последнего update_id: {e}")
        
        # Отправляем сообщение о запуске
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text="🚀 Бот мониторинга SLA запущен\n\nИспользуйте /help для списка команд"
            )
        except:
            pass
        
        while self.is_running:
            try:
                # Проверяем задачи раз в 60 минут
                current_minute = datetime.now().minute
                if current_minute == 0:  # Проверка в начале каждого часа
                    await self.check_tasks()
                    await asyncio.sleep(60)  # Ждем минуту, чтобы не проверять несколько раз
                
                # Обрабатываем команды (каждую секунду)
                await self.handle_updates()
                
                await asyncio.sleep(1)
                
            except KeyboardInterrupt:
                logger.info("🛑 Бот остановлен")
                break
            except Exception as e:
                logger.error(f"❌ Ошибка в основном цикле: {e}", exc_info=True)
                await asyncio.sleep(5)


async def test_bot():
    """Тестовая функция"""
    print("\n" + "=" * 60)
    print("🤖 ТЕСТИРОВАНИЕ SLA БОТА")
    print("=" * 60)
    
    print("\n📋 Проверка конфигурации:")
    print(f"   CHAT_ID: {config.CHAT_ID}")
    print(f"   BOT_TOKEN: {config.BOT_TOKEN[:10]}...")
    print(f"   SLA_HOURS: {config.SLA_HOURS}")
    
    bot = SLABot()
    
    print("\n🔍 Получаем задачи из Jira...")
    tasks = await bot.api_client.get_tasks()
    
    if tasks:
        print(f"\n✅ Получено задач: {len(tasks)}")
        to_notify = [t for t in tasks if t.get('should_notify')]
        print(f"⚠️ Требуют уведомления: {len(to_notify)}")
        
        if tasks:
            print(f"\n📋 Пример задачи:")
            task = tasks[0]
            print(f"   ID: {task['id']}")
            print(f"   Исполнитель: {task['assignee']}")
            print(f"   Дедлайн: {task['due_date'].strftime('%d.%m.%Y %H:%M')}")
            print(f"   Осталось: {task['hours_until_due']:.1f}ч")
    else:
        print("\n❌ Не удалось получить задачи")
    
    print("\n" + "=" * 60)


async def send_test_notification():
    """Отправляет тестовое уведомление"""
    print("\n📨 ОТПРАВКА ТЕСТОВОГО УВЕДОМЛЕНИЯ")
    
    bot = SLABot()
    
    employee = find_employee_by_name("Бухвиц Владислав")
    if not employee:
        print("❌ Сотрудник не найден")
        return
    
    test_task = {
        "id": "TEST-001",
        "title": "🔧 ТЕСТОВАЯ ЗАДАЧА",
        "assignee": "Бухвиц Владислав",
        "due_date": datetime.now() + timedelta(hours=2),
        "hours_until_due": 2.5,
        "status": "В работе",
        "priority": "High",
        "url": "https://test.ru"
    }
    
    await bot.send_notification(test_task)
    print("✅ Тестовое уведомление отправлено!")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] == "--test":
            asyncio.run(test_bot())
        elif sys.argv[1] == "--send-test":
            asyncio.run(send_test_notification())
    else:
        # Постоянная работа
        bot = SLABot()
        try:
            asyncio.run(bot.run_forever())
        except KeyboardInterrupt:
            print("\n🛑 Бот остановлен")
