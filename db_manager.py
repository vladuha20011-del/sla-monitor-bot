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
    
    # Таблица сотрудников
    c.execute('''
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT,
            search_names TEXT,
            telegram_username TEXT,
            email TEXT,
            username TEXT,
            is_active INTEGER DEFAULT 1
        )
    ''')
    
    # Таблица настроек
    c.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT,
            description TEXT
        )
    ''')
    
    # Таблица статусов задач
    c.execute('''
        CREATE TABLE IF NOT EXISTS task_statuses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            is_active INTEGER DEFAULT 1
        )
    ''')
    
    # Таблица шаблонов сообщений
    c.execute('''
        CREATE TABLE IF NOT EXISTS message_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            template TEXT,
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
    
    # Добавляем статусы по умолчанию
    default_statuses = [
        'Ожидание поддержки',
        'Ожидание клиента',
        'Передано партнеру',
        'В процессе',
        'Эскалация (не разработка)',
        'Фин блок',
        'Согласование',
        'ЗАПРОС НА ПАУЗУ',
        'ETL',
        'РЕГ БЛОК',
        'Претензионный',
        'ЮР БЛОК',
        'ВНЕДРЕНИЕ',
        'РЕКА',
        'В разработку',
        'Пауза'
    ]
    
    for status in default_statuses:
        c.execute('INSERT OR IGNORE INTO task_statuses (name) VALUES (?)', (status,))
    
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
            'is_active': row['is_active']
        })
    return employees

def add_employee(data: Dict) -> int:
    """Добавить сотрудника"""
    conn = get_db_connection()
    c = conn.cursor()
    
    c.execute('''
        INSERT INTO employees (full_name, search_names, telegram_username, email, username)
        VALUES (?, ?, ?, ?, ?)
    ''', (
        data['full_name'],
        ','.join(data['search_names']),
        data['telegram_username'],
        data['email'],
        data['username']
    ))
    
    conn.commit()
    employee_id = c.lastrowid
    conn.close()
    return employee_id

def update_employee(employee_id: int, data: Dict):
    """Обновить сотрудника"""
    conn = get_db_connection()
    c = conn.cursor()
    
    c.execute('''
        UPDATE employees 
        SET full_name = ?, search_names = ?, telegram_username = ?, email = ?, username = ?
        WHERE id = ?
    ''', (
        data['full_name'],
        ','.join(data['search_names']),
        data['telegram_username'],
        data['email'],
        data['username'],
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
    """Найти сотрудника по имени"""
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

def get_all_telegram_mentions() -> str:
    """Получить все Telegram упоминания"""
    employees = get_employees(active_only=True)
    return " ".join([emp['telegram_username'] for emp in employees])

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

def get_task_statuses(active_only: bool = True) -> List[str]:
    """Получить статусы задач"""
    conn = get_db_connection()
    c = conn.cursor()
    
    query = 'SELECT name FROM task_statuses'
    if active_only:
        query += ' WHERE is_active = 1'
    
    c.execute(query)
    rows = c.fetchall()
    conn.close()
    
    return [row['name'] for row in rows]

def add_task_status(name: str):
    """Добавить статус задачи"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO task_statuses (name) VALUES (?)', (name,))
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

def get_all_templates() -> Dict[str, str]:
    """Получить все шаблоны"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT name, template FROM message_templates WHERE is_active = 1')
    rows = c.fetchall()
    conn.close()
    
    return {row['name']: row['template'] for row in rows}

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