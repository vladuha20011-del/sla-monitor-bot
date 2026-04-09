"""
Основной бот для мониторинга SLA с поддержкой команд
Использует простой polling без Application и без Markdown
"""

import asyncio
import logging
import sys
import os
import re
import io
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

from telegram import Bot, Update, ChatMember, InputFile
from telegram.constants import ParseMode
from telegram.error import TelegramError

# Для Excel отчётов
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side

import config
from api_client import TaskAPIClient
from employees import find_employee_by_name, get_all_telegram_mentions, EMPLOYEES, find_employees_by_lastname

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
    
    async def is_allowed_chat(self, chat_id: int) -> bool:
        """
        Проверяет, разрешено ли использовать бота в этом чате
        Запрещает личные сообщения, разрешает только групповой чат
        """
        try:
            chat = await self.bot.get_chat(chat_id)
            if chat.type in ['group', 'supergroup']:
                return True
            else:
                logger.warning(f"Запрещённый чат: {chat_id} (тип: {chat.type})")
                return False
        except Exception as e:
            logger.error(f"Ошибка при проверке типа чата: {e}")
            return False
    
    async def check_tasks(self):
        """Проверяет задачи и отправляет уведомления (текстом или Excel)"""
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
                if employee:
                    employee_tasks.append(task)
            
            logger.info(f"📊 Задач от сотрудников отдела: {len(employee_tasks)}")
            
            # Из них отбираем те, что требуют уведомления
            tasks_to_notify = [t for t in employee_tasks if t.get('should_notify', False)]
            
            logger.info(f"📊 Задач для уведомления: {len(tasks_to_notify)}")
            
            if not tasks_to_notify:
                logger.info("✅ Нет задач для уведомления")
                return
            
            # Фильтруем задачи, которые ещё не уведомляли
            new_tasks = [t for t in tasks_to_notify if t['id'] not in self.notified_tasks]
            
            if not new_tasks:
                logger.info("✅ Нет новых задач для уведомления")
                return
            
            # Сортируем по времени до дедлайна
            new_tasks.sort(key=lambda x: x['hours_until_due'])
            
            # ГИБКАЯ ДОСТАВКА: если задач много — отправляем Excel, если мало — текстом
            if len(new_tasks) >= 5:
                logger.info(f"📊 Отправляем Excel отчёт ({len(new_tasks)} задач)")
                await self._send_excel_notification(new_tasks)
            else:
                logger.info(f"📊 Отправляем текстовое уведомление ({len(new_tasks)} задач)")
                await self._send_bulk_notification(new_tasks, is_manual=False)
            
        except Exception as e:
            logger.error(f"❌ Ошибка при проверке задач: {e}", exc_info=True)
    
    async def _send_excel_notification(self, tasks: list):
        """
        Отправляет Excel файл с тегами исполнителей
        """
        if not tasks:
            return
        
        # Проверяем текущее время (МСК)
        now = datetime.now()
        current_hour = now.hour
        current_weekday = now.weekday()
        
        # Проверяем, можно ли тегать
        should_mention = config.TAG_ENABLED
        if should_mention:
            time_ok = current_hour >= config.TAG_START_HOUR and current_hour < config.TAG_END_HOUR
            day_ok = True
            if config.TAG_WORKDAYS_ONLY:
                day_ok = current_weekday < 5
            should_mention = time_ok and day_ok
        
        # Собираем теги исполнителей
        mentions = []
        for task in tasks:
            employee = find_employee_by_name(task['assignee'])
            if employee and should_mention:
                mentions.append(employee['telegram_username'])
        
        mentions_str = " ".join(set(mentions)) if mentions else ""
        
        # Генерируем Excel файл
        excel_file = await self._generate_excel_report(tasks)
        
        # Формируем сообщение
        if mentions_str:
            caption = (
                f"📊 Коллеги, в файле собраны задачи с истекающим SLA ({len(tasks)} шт.).\n"
                f"Просьба обратить внимание на свои задачи: {mentions_str}"
            )
        else:
            caption = (
                f"📊 Коллеги, в файле собраны задачи с истекающим SLA ({len(tasks)} шт.).\n"
                f"Просьба обратить внимание на свои задачи."
            )
        
        # Отправляем файл
        try:
            await self.bot.send_document(
                chat_id=self.chat_id,
                document=InputFile(excel_file, filename=excel_file.name),
                caption=caption
            )
            logger.info(f"✅ Отправлен Excel отчёт с {len(tasks)} задачами")
            
            # Добавляем задачи в список уведомлённых
            for task in tasks:
                self.notified_tasks.add(task['id'])
                
        except TelegramError as e:
            logger.error(f"❌ Ошибка отправки Excel отчёта: {e}")
    
    async def _send_bulk_notification(self, tasks: list, is_manual: bool = False):
        """
        Отправляет одно общее уведомление со всеми задачами (текстом)
        """
        if not tasks:
            return
        
        # Проверяем текущее время (МСК)
        now = datetime.now()
        current_hour = now.hour
        current_weekday = now.weekday()  # 0-6 (пн-вс)
        
        # Проверяем, можно ли тегать
        should_mention = config.TAG_ENABLED
        
        if should_mention:
            # Проверка по времени суток
            time_ok = current_hour >= config.TAG_START_HOUR and current_hour < config.TAG_END_HOUR
            
            # Проверка по дням недели (если включено)
            day_ok = True
            if config.TAG_WORKDAYS_ONLY:
                day_ok = current_weekday < 5  # пн-пт = 0-4
            
            should_mention = time_ok and day_ok
            
            if not time_ok:
                logger.info(f"⏰ Теги отключены по времени: {current_hour}ч (рабочие часы {config.TAG_START_HOUR}-{config.TAG_END_HOUR})")
            elif not day_ok:
                logger.info(f"📅 Теги отключены по дню недели: {current_weekday} (рабочие дни пн-пт)")
        
        # Формируем заголовок (всегда одинаковый)
        message = "⚠️ Внимание! Приближается SLA!\n\n"
        messages_sent = 0
        
        for i, task in enumerate(tasks):
            # Находим сотрудника по имени
            employee = find_employee_by_name(task['assignee'])
            
            # Формируем упоминание исполнителя
            if employee and should_mention:
                mention = f"{task['assignee']} {employee['telegram_username']}"
            else:
                mention = f"{task['assignee']}"
            
            # Формируем время и статус
            hours_left = task['hours_until_due']
            time_str = self._format_time(hours_left)
            sla_status = self._get_sla_status(hours_left)
            
            # Форматируем дату создания
            created_date = "неизвестно"
            if 'created' in task and task['created']:
                try:
                    # Парсим дату создания из Jira
                    created_str = task['created']
                    # Убираем часовой пояс и лишние символы
                    if 'T' in created_str:
                        created_str = created_str.split('+')[0].split('.')[0]
                        created_dt = datetime.strptime(created_str, '%Y-%m-%dT%H:%M:%S')
                        created_date = created_dt.strftime('%d.%m.%Y %H:%M')
                except Exception as e:
                    logger.debug(f"Ошибка парсинга даты создания {task['created']}: {e}")
                    created_date = str(task['created'])[:16]
            
            # Добавляем задачу в общее сообщение
            message += (
                f"📌 Задача: {task['id']}\n"
                f"🔗 Ссылка: {task['url']}\n"
                f"📋 Название: {task['title']}\n"
                f"👤 Исполнитель: {mention}\n"
                f"📅 Создана: {created_date}\n"
                f"⏰ Дедлайн: {task['due_date'].strftime('%d.%m.%Y %H:%M')}\n"
                f"⌛ Осталось: {time_str}\n"
                f"📊 {sla_status}\n"
                f"📈 Статус: {task['status']}\n"
                f"🎯 Приоритет: {task['priority'] or 'Не указан'}\n\n"
            )
            
            # Добавляем разделитель между задачами (кроме последней)
            if i < len(tasks) - 1:
                message += f"{'—' * 45}\n\n"
            
            # Если это не ручной вызов, добавляем задачу в список уведомлённых
            if not is_manual:
                self.notified_tasks.add(task['id'])
            
            # Telegram имеет лимит на длину сообщения (3500 символов)
            if len(message) > 3500:
                # Добавляем финальное обращение перед отправкой
                if not message.endswith("Коллеги, обратите внимание на задачи!"):
                    message += "Коллеги, обратите внимание на задачи!"
                
                await self.bot.send_message(
                    chat_id=self.chat_id,
                    text=message,
                    disable_web_page_preview=True
                )
                messages_sent += 1
                logger.info(f"📨 Отправлена часть {messages_sent} (примерно {i+1}/{len(tasks)} задач)")
                
                # ВАЖНО: задержка между отправками
                await asyncio.sleep(2)
                
                # Начинаем новое сообщение
                message = "⚠️ Внимание! Приближается SLA! (продолжение)\n\n"
        
        # Добавляем финальное обращение, если его ещё нет
        if message and not message.endswith("Коллеги, обратите внимание на задачи!"):
            message += "Коллеги, обратите внимание на задачи!"
        
        # Отправляем остаток сообщения
        if message and len(message) > 0:
            try:
                await self.bot.send_message(
                    chat_id=self.chat_id,
                    text=message,
                    disable_web_page_preview=True
                )
                messages_sent += 1
                logger.info(f"✅ Отправлено общее уведомление с {len(tasks)} задачами (всего {messages_sent} частей)")
            except TelegramError as e:
                logger.error(f"❌ Ошибка отправки общего уведомления: {e}")
    
    async def _generate_excel_report(self, tasks: list) -> io.BytesIO:
        """Генерирует Excel файл с отчётом по задачам"""
        logger.info(f"📊 Генерация Excel для {len(tasks)} задач")
        
        if not tasks:
            wb = Workbook()
            ws = wb.active
            ws.title = "SLA Отчёт"
            ws.cell(row=1, column=1, value="Нет задач для отображения")
            excel_bytes = io.BytesIO()
            wb.save(excel_bytes)
            excel_bytes.seek(0)
            excel_bytes.name = f"sla_report_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
            return excel_bytes
        
        try:
            wb = Workbook()
            ws = wb.active
            ws.title = "SLA Отчёт"
            
            # Заголовки
            headers = [
                'ID', 'Название', 'Исполнитель', 'Telegram', 'Создана',
                'Дедлайн', 'Ост.(ч)', 'Статус SLA', 'Статус', 'Приоритет', 'Ссылка'
            ]
            
            for col, header in enumerate(headers, 1):
                ws.cell(row=1, column=col, value=header)
            
            # Данные
            for row, task in enumerate(tasks, 2):
                employee = find_employee_by_name(task['assignee'])
                telegram = employee['telegram_username'] if employee else '—'
                hours = task['hours_until_due']
                
                # Дата создания
                created_date = "—"
                if 'created' in task and task['created']:
                    try:
                        created_str = task['created']
                        if 'T' in created_str:
                            created_str = created_str.split('+')[0].split('.')[0]
                            created_dt = datetime.strptime(created_str, '%Y-%m-%dT%H:%M:%S')
                            created_date = created_dt.strftime('%d.%m.%Y')
                    except:
                        created_date = "ошибка"
                
                # Статус SLA
                if hours < 0:
                    sla_status = "ПРОСРОЧЕНО"
                elif hours < 12:
                    sla_status = "Критично"
                elif hours < 24:
                    sla_status = "Скоро"
                else:
                    sla_status = "Норма"
                
                # Записываем данные
                ws.cell(row=row, column=1, value=task['id'])
                ws.cell(row=row, column=2, value=task['title'][:50])
                ws.cell(row=row, column=3, value=task['assignee'])
                ws.cell(row=row, column=4, value=telegram)
                ws.cell(row=row, column=5, value=created_date)
                ws.cell(row=row, column=6, value=task['due_date'].strftime('%d.%m.%Y'))
                ws.cell(row=row, column=7, value=round(hours, 1))
                ws.cell(row=row, column=8, value=sla_status)
                ws.cell(row=row, column=9, value=task['status'][:15])
                ws.cell(row=row, column=10, value=task['priority'] or '—')
                ws.cell(row=row, column=11, value=task['url'])
            
            # Автоширина
            for col in range(1, 6):
                ws.column_dimensions[chr(64 + col)].width = 15
            ws.column_dimensions[chr(64 + 11)].width = 30
            
            excel_bytes = io.BytesIO()
            wb.save(excel_bytes)
            excel_bytes.seek(0)
            excel_bytes.name = f"sla_report_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
            
            logger.info(f"✅ Excel отчёт сгенерирован")
            return excel_bytes
            
        except Exception as e:
            logger.error(f"❌ Ошибка при генерации Excel: {e}")
            wb = Workbook()
            ws = wb.active
            ws.cell(row=1, column=1, value=f"Ошибка генерации отчёта: {str(e)}")
            excel_bytes = io.BytesIO()
            wb.save(excel_bytes)
            excel_bytes.seek(0)
            excel_bytes.name = f"sla_report_error.xlsx"
            return excel_bytes
    
    async def _generate_request_excel_report(self, tasks: list, employee_name: str = None) -> io.BytesIO:
        """
        Генерирует Excel файл с отчётом по задачам для команды /request
        Столбцы: ID, Тип, Название, Статус, Создана, Дедлайн, Исполнитель, Ссылка
        """
        logger.info(f"📊 Генерация персонального Excel для {len(tasks)} задач")
        
        if not tasks:
            wb = Workbook()
            ws = wb.active
            ws.title = "Задачи"
            ws.cell(row=1, column=1, value="Нет задач для отображения")
            excel_bytes = io.BytesIO()
            wb.save(excel_bytes)
            excel_bytes.seek(0)
            excel_bytes.name = f"tasks_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
            return excel_bytes
        
        try:
            wb = Workbook()
            ws = wb.active
            ws.title = "Задачи"
            
            # Заголовки
            headers = [
                'ID задачи',
                'Тип задачи',
                'Название',
                'Статус',
                'Создана',
                'Дедлайн',
                'Исполнитель',
                'Ссылка'
            ]
            
            for col, header in enumerate(headers, 1):
                ws.cell(row=1, column=col, value=header)
            
            # Данные
            for row, task in enumerate(tasks, 2):
                # Получаем тип задачи из raw_data
                issue_type = "Неизвестно"
                if 'raw_data' in task:
                    fields = task['raw_data'].get('fields', {})
                    issue_type_data = fields.get('issuetype', {})
                    issue_type = issue_type_data.get('name', 'Неизвестно')
                
                # Форматируем дату создания
                created_date = "—"
                if 'created' in task and task['created']:
                    try:
                        created_str = task['created']
                        if 'T' in created_str:
                            created_str = created_str.split('+')[0].split('.')[0]
                            created_dt = datetime.strptime(created_str, '%Y-%m-%dT%H:%M:%S')
                            created_date = created_dt.strftime('%d.%m.%Y %H:%M')
                    except:
                        created_date = str(task['created'])[:16]
                
                # Записываем данные
                ws.cell(row=row, column=1, value=task['id'])
                ws.cell(row=row, column=2, value=issue_type)
                ws.cell(row=row, column=3, value=task['title'][:100])
                ws.cell(row=row, column=4, value=task['status'])
                ws.cell(row=row, column=5, value=created_date)
                ws.cell(row=row, column=6, value=task['due_date'].strftime('%d.%m.%Y %H:%M') if task['due_date'] else '—')
                ws.cell(row=row, column=7, value=task['assignee'])
                ws.cell(row=row, column=8, value=task['url'])
            
            # Автоширина
            ws.column_dimensions['A'].width = 12
            ws.column_dimensions['B'].width = 15
            ws.column_dimensions['C'].width = 50
            ws.column_dimensions['D'].width = 20
            ws.column_dimensions['E'].width = 16
            ws.column_dimensions['F'].width = 16
            ws.column_dimensions['G'].width = 25
            ws.column_dimensions['H'].width = 40
            
            excel_bytes = io.BytesIO()
            wb.save(excel_bytes)
            excel_bytes.seek(0)
            
            if employee_name:
                safe_name = employee_name.replace(' ', '_').replace('@', '')
                excel_bytes.name = f"tasks_{safe_name}_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
            else:
                excel_bytes.name = f"tasks_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
            
            logger.info(f"✅ Персональный Excel отчёт сгенерирован")
            return excel_bytes
            
        except Exception as e:
            logger.error(f"❌ Ошибка при генерации персонального Excel: {e}")
            wb = Workbook()
            ws = wb.active
            ws.cell(row=1, column=1, value=f"Ошибка генерации отчёта: {str(e)}")
            excel_bytes = io.BytesIO()
            wb.save(excel_bytes)
            excel_bytes.seek(0)
            excel_bytes.name = f"tasks_error.xlsx"
            return excel_bytes
    
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
            task_data = await self.api_client.get_task_by_key(task_key)
            if not task_data:
                return None
            
            fields = task_data.get('fields', {})
            assignee_data = fields.get('assignee')
            assignee_name = self.api_client._extract_assignee(assignee_data)
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
                    "assignee": assignee_name,
                    "assignee_raw": assignee_data,
                    "due_date": due_date,
                    "hours_until_due": hours_until_due,
                    "should_notify": hours_until_due <= config.SLA_HOURS,
                    "status": fields.get('status', {}).get('name') if fields.get('status') else 'Неизвестно',
                    "status_id": fields.get('status', {}).get('id') if fields.get('status') else None,
                    "priority": fields.get('priority', {}).get('name') if fields.get('priority') else None,
                    "url": f"{self.api_client.base_url}/browse/{task_data.get('key')}",
                    "due_date_source": sla_source,
                    "created": fields.get('created'),
                    "raw_data": task_data
                }
                return task
            return None
        except Exception as e:
            logger.error(f"Ошибка при получении задачи {task_key}: {e}")
            return None
    
    async def handle_updates(self):
        """Обрабатывает входящие команды"""
        try:
            try:
                updates = await self.bot.get_updates(offset=self.last_update_id + 1, timeout=10)
            except Exception as e:
                logger.debug(f"Ошибка получения обновлений: {e}")
                await asyncio.sleep(1)
                return
            
            for update in updates:
                self.last_update_id = update.update_id
                
                if update.message and update.message.text:
                    text = update.message.text.strip()
                    chat_id = update.message.chat_id
                    user_id = update.message.from_user.id
                    
                    logger.info(f"📨 Получено сообщение: '{text}' от {user_id}")
                    
                    # ПРОВЕРКА: запрещаем личные сообщения
                    try:
                        is_allowed = await self.is_allowed_chat(chat_id)
                    except Exception as e:
                        logger.debug(f"Ошибка проверки чата: {e}")
                        continue
                    
                    if not is_allowed:
                        await self.bot.send_message(
                            chat_id=chat_id,
                            text="❌ Бот работает только в групповых чатах. Личные сообщения запрещены."
                        )
                        continue
                    
                    # Разбираем команду и аргументы
                    parts = text.split()
                    full_command = parts[0].lower()
                    
                    # ИЗВЛЕКАЕМ БАЗОВУЮ КОМАНДУ (отрезаем @username если есть)
                    if '@' in full_command:
                        base_command = full_command.split('@')[0]
                    else:
                        base_command = full_command
                    
                    # Обрабатываем команды по base_command
                    if base_command == '/start':
                        await self.bot.send_message(
                            chat_id=chat_id,
                            text=(
                                "✅ Бот мониторинга SLA\n\n"
                                "📋 Доступные команды:\n"
                                "/alarm - показать новые задачи с истекающим SLA\n"
                                "/checking_dep - сформировать Excel отчёт по задачам отдела\n"
                                "/request - выгрузить задачи сотрудника по фамилии (например: /request Бухвиц)\n"
                                "/check - проверить конкретную задачу (Например: /check ZZ-123456)"
                            )
                        )
                    
                    elif base_command == '/help':
                        help_text = (
                            "🤖 Команды бота:\n\n"
                            "/alarm - показать новые задачи с истекающим SLA\n"
                            "/checking_dep - сформировать Excel отчёт по задачам отдела\n"
                            "/request - выгрузить задачи сотрудника по фамилии (например: /request Бухвиц)\n"
                            "/check - проверить конкретную задачу (Например: /check ZZ-12345)"
                        )
                        await self.bot.send_message(
                            chat_id=chat_id,
                            text=help_text
                        )
                    
                    elif base_command == '/alarm':
                        await self.bot.send_message(
                            chat_id=chat_id,
                            text="🔍 Формирую отчёт по новым задачам с истекающим SLA..."
                        )
                        
                        tasks = await self.api_client.get_tasks()
                        
                        employee_tasks = []
                        for task in tasks:
                            employee = find_employee_by_name(task['assignee'])
                            if employee:
                                employee_tasks.append(task)
                        
                        tasks_to_notify = [t for t in employee_tasks if t.get('should_notify', False)]
                        
                        if not tasks_to_notify:
                            await self.bot.send_message(
                                chat_id=chat_id,
                                text="✅ Нет задач с истекающим SLA"
                            )
                            continue
                        
                        new_tasks = [t for t in tasks_to_notify if t['id'] not in self.notified_tasks]
                        
                        if not new_tasks:
                            await self.bot.send_message(
                                chat_id=chat_id,
                                text="✅ Нет новых задач с истекающим SLA"
                            )
                            continue
                        
                        new_tasks.sort(key=lambda x: x['hours_until_due'])
                        
                        # ГИБКАЯ ДОСТАВКА
                        if len(new_tasks) >= 5:
                            await self._send_excel_notification(new_tasks)
                        else:
                            await self._send_bulk_notification(new_tasks, is_manual=False)
                    
                    elif base_command == '/checking_dep':
                        logger.info("🔍 Вход в /checking_dep")
                        await self.bot.send_message(
                            chat_id=chat_id,
                            text="📊 Формирую Excel отчёт по задачам отдела..."
                        )
                        
                        logger.info("🔍 Запрашиваем задачи из Jira")
                        tasks = await self.api_client.get_tasks()
                        logger.info(f"🔍 Получено задач из Jira: {len(tasks)}")
                        
                        dep_tasks = []
                        for task in tasks:
                            employee = find_employee_by_name(task['assignee'])
                            if employee:
                                dep_tasks.append(task)
                        logger.info(f"🔍 Отфильтровано задач отдела: {len(dep_tasks)}")
                        
                        if not dep_tasks:
                            await self.bot.send_message(
                                chat_id=chat_id,
                                text="✅ Нет задач у сотрудников отдела"
                            )
                            continue
                        
                        dep_tasks.sort(key=lambda x: x['hours_until_due'])
                        logger.info(f"🔍 Задачи отсортированы, генерируем Excel")
                        
                        excel_file = await self._generate_excel_report(dep_tasks)
                        logger.info(f"🔍 Excel сгенерирован, отправляем")
                        
                        await self.bot.send_document(
                            chat_id=chat_id,
                            document=InputFile(excel_file, filename=excel_file.name),
                            caption=f"📊 Отчёт по задачам отдела (всего: {len(dep_tasks)})"
                        )
                        
                        logger.info(f"✅ Отправлен Excel отчёт с {len(dep_tasks)} задачами")
                    
                    elif base_command == '/request':
                        # Проверяем аргументы
                        if len(parts) < 2:
                            await self.bot.send_message(
                                chat_id=chat_id,
                                text="❌ Укажите фамилию сотрудника\n\nПример: /request Бухвиц"
                            )
                            continue
                        
                        lastname = parts[1]
                        await self.bot.send_message(
                            chat_id=chat_id,
                            text=f"🔍 Ищу задачи сотрудников с фамилией '{lastname}'..."
                        )
                        
                        # Ищем сотрудников по фамилии
                        employees_found = find_employees_by_lastname(lastname)
                        
                        if not employees_found:
                            await self.bot.send_message(
                                chat_id=chat_id,
                                text=f"❌ Сотрудники с фамилией '{lastname}' не найдены в базе"
                            )
                            continue
                        
                        # Получаем задачи из Jira
                        tasks = await self.api_client.get_tasks()
                        
                        # Собираем задачи для найденных сотрудников
                        all_user_tasks = []
                        for emp in employees_found:
                            for task in tasks:
                                if find_employee_by_name(task['assignee']) == emp:
                                    task_copy = task.copy()
                                    task_copy['employee_name'] = emp['full_name']
                                    all_user_tasks.append(task_copy)
                        
                        if not all_user_tasks:
                            await self.bot.send_message(
                                chat_id=chat_id,
                                text=f"✅ У сотрудников с фамилией '{lastname}' нет активных задач"
                            )
                            continue
                        
                        # Сортируем по дедлайну
                        all_user_tasks.sort(key=lambda x: x['hours_until_due'])
                        
                        # Генерируем персональный Excel
                        excel_file = await self._generate_request_excel_report(all_user_tasks, lastname)
                        
                        # Формируем список найденных сотрудников
                        emp_names = ", ".join([e['full_name'] for e in employees_found])
                        
                        await self.bot.send_document(
                            chat_id=chat_id,
                            document=InputFile(excel_file, filename=excel_file.name),
                            caption=f"📊 Задачи сотрудников: {emp_names}\nВсего задач: {len(all_user_tasks)}"
                        )
                        
                        logger.info(f"✅ Отправлен персональный Excel отчёт для фамилии '{lastname}' с {len(all_user_tasks)} задачами")
                    
                    elif base_command == '/check':
                        if len(parts) < 2:
                            await self.bot.send_message(
                                chat_id=chat_id,
                                text="❌ Укажите номер задачи\n\nПример: /check ZZ-12345"
                            )
                            continue
                        
                        task_key = parts[1].upper()
                        
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
                        
                        task = await self.get_task_by_key(task_key)
                        
                        if not task:
                            await self.bot.send_message(
                                chat_id=chat_id,
                                text=f"❌ Задача {task_key} не найдена.\n\nВозможно, задача уже закрыта или не существует."
                            )
                            continue
                        
                        assignee_formatted = self._format_assignee(task['assignee'])
                        
                        # Получаем тип задачи
                        issue_type = "Неизвестно"
                        if 'raw_data' in task:
                            fields = task['raw_data'].get('fields', {})
                            issue_type_data = fields.get('issuetype', {})
                            issue_type = issue_type_data.get('name', 'Неизвестно')
                        
                        created_date = "неизвестно"
                        if 'created' in task and task['created']:
                            try:
                                created_str = task['created']
                                if 'T' in created_str:
                                    created_str = created_str.split('+')[0].split('.')[0]
                                    created_dt = datetime.strptime(created_str, '%Y-%m-%dT%H:%M:%S')
                                    created_date = created_dt.strftime('%d.%m.%Y %H:%M')
                            except:
                                created_date = str(task['created'])[:16]
                        
                        hours = task['hours_until_due']
                        sla_status = self._get_sla_status(hours)
                        
                        task_info = (
                            f"📌 Задача: {task['id']}\n"
                            f"📋 Тип: {issue_type}\n"
                            f"📋 Название: {task['title']}\n"
                            f"🔗 Ссылка: {task['url']}\n\n"
                            f"👤 Исполнитель: {assignee_formatted}\n"
                            f"📅 Создана: {created_date}\n"
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
        logger.info(f"🚀 Бот запущен. Интервал проверки: {config.CHECK_INTERVAL_MINUTES} минут")
        self.last_update_id = 0
        
        while self.is_running:
            try:
                current_minute = datetime.now().minute
                if current_minute % config.CHECK_INTERVAL_MINUTES == 0:
                    await self.check_tasks()
                    await asyncio.sleep(60)
                
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
        "url": "https://test.ru",
        "created": datetime.now().isoformat()
    }
    
    await bot._send_bulk_notification([test_task])
    print("✅ Тестовое уведомление отправлено!")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] == "--test":
            asyncio.run(test_bot())
        elif sys.argv[1] == "--send-test":
            asyncio.run(send_test_notification())
    else:
        bot = SLABot()
        try:
            asyncio.run(bot.run_forever())
        except KeyboardInterrupt:
            print("\n🛑 Бот остановлен")
