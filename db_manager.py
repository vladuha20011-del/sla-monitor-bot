"""
Менеджер базы данных для бота и админки
"""

import sqlite3
import os
from typing import List, Dict, Any, Optional

DB_PATH = 'settings.db'

def get_db_connection():
    """Получить соединение с БД"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Инициализация базы данных"""
    conn = get_db_connection()
    c = conn.cursor()
    
    # Таблица сотрудников (с полем status)
    c.execute('''
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT,
            search_names TEXT,
            telegram_username TEXT,
            email TEXT,
            username TEXT,
            status TEXT DEFAULT 'active',
            is_active INTEGER DEFAULT 1
        )
    ''')
    
    # Добавляем колонку status, если её нет (для старых БД)
    try:
        c.execute('ALTER TABLE employees ADD COLUMN status TEXT DEFAULT "active"')
    except sqlite3.OperationalError:
        pass  # колонка уже существует
    
    # Таблица настроек
    c.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT,
            description TEXT
        )
    ''')
    
    # Таблица статусов задач (с флагом уведомления)
    c.execute('''
        CREATE TABLE IF NOT EXISTS task_statuses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            is_active INTEGER DEFAULT 1,
            notify_enabled INTEGER DEFAULT 1
        )
    ''')
    
    # Таблица шаблонов сообщений
    c.execute('''
        CREATE TABLE IF NOT EXISTS message_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            template TEXT,
            description TEXT,
            is_active INTEGER DEFAULT 1
        )
    ''')
    
    # Таблица статистики
    c.execute('''
        CREATE TABLE IF NOT EXISTS stats (
            key TEXT PRIMARY KEY,
            value INTEGER DEFAULT 0
        )
    ''')
    
    # Добавляем настройки по умолчанию
    default_settings = {
        'SLA_HOURS': ('24', 'За сколько часов до дедлайна уведомлять'),
        'CHECK_INTERVAL_MINUTES': ('180', 'Интервал проверки задач (минуты)'),
        'TAG_START_HOUR': ('9', 'С какого часа тегать'),
        'TAG_END_HOUR': ('18', 'До какого часа тегать'),
        'TAG_ENABLED': ('True', 'Теги включены'),
        'TAG_WORKDAYS_ONLY': ('True', 'Только по будням'),
        'IGNORE_REPLIES': ('True', 'Игнорировать ответы'),
        'IGNORE_EDITS': ('True', 'Игнорировать редактирования'),
        'IGNORE_FORWARDS': ('True', 'Игнорировать пересылки')
    }
    
    for key, (value, desc) in default_settings.items():
        c.execute('INSERT OR IGNORE INTO settings (key, value, description) VALUES (?, ?, ?)', 
                  (key, value, desc))
    
    # Добавляем статусы по умолчанию (с уведомлениями)
    default_statuses = [
        ('Ожидание поддержки', 1),
        ('В процессе', 1),
        ('Ожидание клиента', 0),
        ('Передано партнеру', 0),
        ('Эскалация (не разработка)', 0),
        ('Фин блок', 0),
        ('Согласование', 0),
        ('ЗАПРОС НА ПАУЗУ', 0),
        ('ETL', 0),
        ('РЕГ БЛОК', 0),
        ('Претензионный', 0),
        ('ЮР БЛОК', 0),
        ('ВНЕДРЕНИЕ', 0),
        ('РЕКА', 0),
        ('В разработку', 0),
        ('Пауза', 0)
    ]
    
    for status, notify in default_statuses:
        c.execute('INSERT OR IGNORE INTO task_statuses (name, notify_enabled) VALUES (?, ?)', 
                  (status, notify))
    
    # Добавляем шаблоны по умолчанию
    default_templates = [
        ('header', '⚠️ Внимание! Приближается SLA!', 'Заголовок уведомления'),
        ('footer', 'Коллеги, обратите внимание!', 'Финальная фраза'),
        ('task_format', '📌 Задача: {id}\n🔗 Ссылка: {url}\n📋 Название: {title}\n👤 Исполнитель: {assignee}\n📅 Создана: {created}\n⏰ Осталось на решение: {remaining}\n📈 Статус: {status}\n🎯 Приоритет: {priority}', 'Формат задачи в рассылке'),
        ('check_task_format', '📌 Задача: {id}\n📋 Название: {title}\n🔗 Ссылка: {url}\n\n👤 Исполнитель: {assignee}\n📅 Создана: {created}\n⏰ Осталось: {remaining}\n📈 Статус задачи: {status}\n🎯 Приоритет: {priority}', 'Формат задачи в /check'),
        ('reopen_format', '🔄 Переоткрыта: {reopen_date}', 'Текст для переоткрытой задачи'),
        ('alarm_header', '⚠️ Внимание! Приближается SLA!', 'Заголовок для /alarm'),
        ('alarm_footer', 'Коллеги, обратите внимание!', 'Финальная фраза для /alarm'),
        ('request_caption', '📊 ВСЕ задачи сотрудников: {employees}\n📈 Всего задач: {total}\n📋 {status_summary}', 'Подпись для /request'),
        ('checking_dep_caption', '📊 Отчёт по задачам отдела (всего: {total})', 'Подпись для /checking_dep')
    ]
    
    for name, template, desc in default_templates:
        c.execute('INSERT OR IGNORE INTO message_templates (name, template, description) VALUES (?, ?, ?)', 
                  (name, template, desc))
    
    conn.commit()
    conn.close()


# ============ РАБОТА С СОТРУДНИКАМИ ============

def get_employees(active_only: bool = True) -> List[Dict]:
    """Получить всех сотрудников"""
    conn = get_db_connection()
    c = conn.cursor()
    
    query = 'SELECT * FROM employees'
    if active_only:
        query += ' WHERE is_active = 1'
    
    query += ' ORDER BY id'
    
    c.execute(query)
    rows = c.fetchall()
    conn.close()
    
    employees = []
    for row in rows:
        employees.append({
            'id': row['id'],
            'full_name': row['full_name'],
            'search_names': row['search_names'].split(',') if row['search_names'] else [],
            'telegram_username': row['telegram_username'],
            'email': row['email'],
            'username': row['username'],
            'status': row['status'] if 'status' in row.keys() else 'active',
            'is_active': row['is_active']
        })
    return employees

def add_employee(data: Dict) -> int:
    """Добавить сотрудника"""
    conn = get_db_connection()
    c = conn.cursor()
    
    status = data.get('status', 'active')
    
    c.execute('''
        INSERT INTO employees (full_name, search_names, telegram_username, email, username, status)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (
        data['full_name'],
        ','.join(data['search_names']),
        data['telegram_username'],
        data['email'],
        data['username'],
        status
    ))
    
    conn.commit()
    employee_id = c.lastrowid
    conn.close()
    return employee_id

def update_employee(employee_id: int, data: Dict):
    """Обновить сотрудника"""
    conn = get_db_connection()
    c = conn.cursor()
    
    status = data.get('status', 'active')
    
    c.execute('''
        UPDATE employees 
        SET full_name = ?, search_names = ?, telegram_username = ?, email = ?, username = ?, status = ?
        WHERE id = ?
    ''', (
        data['full_name'],
        ','.join(data['search_names']),
        data['telegram_username'],
        data['email'],
        data['username'],
        status,
        employee_id
    ))
    
    conn.commit()
    conn.close()

def delete_employee(employee_id: int, soft: bool = True):
    """Удалить сотрудника (мягкое или жёсткое)"""
    conn = get_db_connection()
    c = conn.cursor()
    
    if soft:
        c.execute('UPDATE employees SET is_active = 0 WHERE id = ?', (employee_id,))
    else:
        c.execute('DELETE FROM employees WHERE id = ?', (employee_id,))
    
    conn.commit()
    conn.close()

def get_employee_by_name(name_text: str) -> Optional[Dict]:
    """Найти сотрудника по имени (только активных)"""
    employees = get_employees(active_only=True)
    if not name_text:
        return None
    
    name_text_lower = name_text.lower().strip()
    
    for employee in employees:
        # Полное совпадение
        if employee['full_name'].lower() == name_text_lower:
            return employee
        
        # По ключевым словам
        search_names = [s.lower() for s in employee['search_names']]
        if all(keyword in name_text_lower for keyword in search_names):
            return employee
        
        # Частичное совпадение
        name_words = employee['full_name'].lower().split()
        search_words = name_text_lower.split()
        if all(any(word in nw for nw in name_words) for word in search_words):
            return employee
    
    return None

def get_employee_by_id(employee_id: int) -> Optional[Dict]:
    """Получить сотрудника по ID"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT * FROM employees WHERE id = ? AND is_active = 1', (employee_id,))
    row = c.fetchone()
    conn.close()
    
    if row:
        return {
            'id': row['id'],
            'full_name': row['full_name'],
            'search_names': row['search_names'].split(',') if row['search_names'] else [],
            'telegram_username': row['telegram_username'],
            'email': row['email'],
            'username': row['username'],
            'status': row['status'] if 'status' in row.keys() else 'active',
            'is_active': row['is_active']
        }
    return None

def get_all_telegram_mentions() -> str:
    """Получить все Telegram упоминания (только активных)"""
    employees = get_employees(active_only=True)
    return " ".join([emp['telegram_username'] for emp in employees])

def get_active_employees_for_mention() -> List[Dict]:
    """Получить сотрудников, которых можно тегать (статус 'active')"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        SELECT * FROM employees 
        WHERE is_active = 1 AND status = 'active'
    ''')
    rows = c.fetchall()
    conn.close()
    
    employees = []
    for row in rows:
        employees.append({
            'id': row['id'],
            'full_name': row['full_name'],
            'telegram_username': row['telegram_username'],
            'status': row['status'] if 'status' in row.keys() else 'active'
        })
    return employees


# ============ РАБОТА С НАСТРОЙКАМИ ============

def get_settings() -> Dict[str, str]:
    """Получить все настройки"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT key, value FROM settings')
    rows = c.fetchall()
    conn.close()
    
    return {row['key']: row['value'] for row in rows}

def get_setting(key: str, default: str = None) -> str:
    """Получить настройку по ключу"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT value FROM settings WHERE key = ?', (key,))
    row = c.fetchone()
    conn.close()
    
    return row['value'] if row else default

def update_settings(data: Dict[str, str]):
    """Обновить настройки"""
    conn = get_db_connection()
    c = conn.cursor()
    
    for key, value in data.items():
        c.execute('UPDATE settings SET value = ? WHERE key = ?', (value, key))
    
    conn.commit()
    conn.close()


# ============ РАБОТА СО СТАТУСАМИ ============

def get_task_statuses(active_only: bool = True) -> List[Dict]:
    """Получить статусы задач с флагом уведомления"""
    conn = get_db_connection()
    c = conn.cursor()
    
    query = 'SELECT name, notify_enabled, is_active FROM task_statuses'
    if active_only:
        query += ' WHERE is_active = 1'
    
    c.execute(query)
    rows = c.fetchall()
    conn.close()
    
    return [{'name': row['name'], 'notify_enabled': bool(row['notify_enabled']), 'is_active': bool(row['is_active'])} for row in rows]

def get_notify_statuses() -> List[str]:
    """Получить статусы, для которых включены уведомления"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT name FROM task_statuses WHERE is_active = 1 AND notify_enabled = 1')
    rows = c.fetchall()
    conn.close()
    
    return [row['name'] for row in rows]

def add_task_status(name: str, notify_enabled: int = 1):
    """Добавить статус задачи"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO task_statuses (name, notify_enabled) VALUES (?, ?)', 
              (name, notify_enabled))
    conn.commit()
    conn.close()

def update_task_status(name: str, notify_enabled: int):
    """Обновить статус задачи (включить/выключить уведомления)"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('UPDATE task_statuses SET notify_enabled = ? WHERE name = ?', (notify_enabled, name))
    conn.commit()
    conn.close()

def delete_task_status(name: str, soft: bool = True):
    """Удалить статус задачи"""
    conn = get_db_connection()
    c = conn.cursor()
    
    if soft:
        c.execute('UPDATE task_statuses SET is_active = 0 WHERE name = ?', (name,))
    else:
        c.execute('DELETE FROM task_statuses WHERE name = ?', (name,))
    
    conn.commit()
    conn.close()


# ============ РАБОТА С ШАБЛОНАМИ ============

def get_template(name: str) -> Optional[str]:
    """Получить шаблон по имени"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT template FROM message_templates WHERE name = ? AND is_active = 1', (name,))
    row = c.fetchone()
    conn.close()
    
    return row['template'] if row else None

def save_template(name: str, template: str):
    """Сохранить шаблон"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        INSERT OR REPLACE INTO message_templates (name, template, is_active)
        VALUES (?, ?, 1)
    ''', (name, template))
    conn.commit()
    conn.close()

def get_all_templates() -> Dict[str, Dict]:
    """Получить все шаблоны с описаниями"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT name, template, description FROM message_templates WHERE is_active = 1')
    rows = c.fetchall()
    conn.close()
    
    return {row['name']: {'template': row['template'], 'description': row['description']} for row in rows}

def get_all_templates_dict() -> Dict[str, str]:
    """Получить все шаблоны как словарь {name: template}"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT name, template FROM message_templates WHERE is_active = 1')
    rows = c.fetchall()
    conn.close()
    
    return {row['name']: row['template'] for row in rows}

def save_templates(data: Dict[str, str]):
    """Сохранить несколько шаблонов"""
    conn = get_db_connection()
    c = conn.cursor()
    
    for name, template in data.items():
        c.execute('''
            INSERT OR REPLACE INTO message_templates (name, template, is_active)
            VALUES (?, ?, 1)
        ''', (name, template))
    
    conn.commit()
    conn.close()


# ============ СТАТИСТИКА ============

def increment_stats(key: str):
    """Увеличить статистику"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        INSERT INTO stats (key, value) VALUES (?, 1)
        ON CONFLICT(key) DO UPDATE SET value = value + 1
    ''', (key,))
    conn.commit()
    conn.close()

def get_stats() -> Dict[str, int]:
    """Получить статистику"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT key, value FROM stats')
    rows = c.fetchall()
    conn.close()
    
    return {row['key']: row['value'] for row in rows}
