"""
Веб-интерфейс для управления SLA ботом
"""

from flask import Flask, render_template, request, jsonify
import sqlite3
import os
import subprocess
import json
import time
import logging

import db_manager

app = Flask(__name__)

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============ ИНИЦИАЛИЗАЦИЯ ============

db_manager.init_db()

# Переносим сотрудников из employees.py если они есть
try:
    from employees import EMPLOYEES
    existing = db_manager.get_employees(active_only=False)
    if len(existing) == 0:
        for emp in EMPLOYEES:
            db_manager.add_employee({
                'full_name': emp['full_name'],
                'search_names': emp['search_names'],
                'telegram_username': emp['telegram_username'],
                'email': emp['email'],
                'username': emp.get('username', emp['email'].split('@')[0])
            })
        print("✅ Сотрудники перенесены из employees.py")
except ImportError:
    pass

# ============ СТРАНИЦЫ ============

@app.route('/')
def index():
    """Главная страница"""
    return render_template('index.html')

@app.route('/login')
def login():
    """Страница входа (пока без пароля)"""
    return render_template('index.html')

# ============ API: СОТРУДНИКИ ============

@app.route('/api/employees')
def api_get_employees():
    """Получить всех сотрудников"""
    employees = db_manager.get_employees(active_only=True)
    return jsonify(employees)

@app.route('/api/employees', methods=['POST'])
def api_add_employee():
    """Добавить сотрудника"""
    data = request.json
    
    # Автоматически формируем username из email
    if 'username' not in data or not data['username']:
        data['username'] = data['email'].split('@')[0] if data.get('email') else ''
    
    # Формируем search_names если не указаны
    if 'search_names' not in data or not data['search_names']:
        name_parts = data['full_name'].split()
        data['search_names'] = [name_parts[0], name_parts[1]] if len(name_parts) >= 2 else [name_parts[0]]
    
    db_manager.add_employee(data)
    return jsonify({'status': 'ok', 'message': 'Сотрудник добавлен'})

@app.route('/api/employees/<int:employee_id>', methods=['PUT'])
def api_update_employee(employee_id):
    """Обновить сотрудника"""
    data = request.json
    db_manager.update_employee(employee_id, data)
    return jsonify({'status': 'ok', 'message': 'Сотрудник обновлён'})

@app.route('/api/employees/<int:employee_id>', methods=['DELETE'])
def api_delete_employee(employee_id):
    """Удалить сотрудника"""
    db_manager.delete_employee(employee_id, soft=True)
    return jsonify({'status': 'ok', 'message': 'Сотрудник удалён'})

# ============ API: НАСТРОЙКИ ============

@app.route('/api/settings')
def api_get_settings():
    """Получить настройки"""
    settings = db_manager.get_settings()
    return jsonify(settings)

@app.route('/api/settings', methods=['POST'])
def api_update_settings():
    """Обновить настройки"""
    data = request.json
    db_manager.update_settings(data)
    return jsonify({'status': 'ok', 'message': 'Настройки сохранены'})

# ============ API: СТАТУСЫ ============

@app.route('/api/statuses')
def api_get_statuses():
    """Получить статусы"""
    statuses = db_manager.get_task_statuses(active_only=True)
    return jsonify([{'name': s} for s in statuses])

@app.route('/api/statuses', methods=['POST'])
def api_add_status():
    """Добавить статус"""
    data = request.json
    db_manager.add_task_status(data['name'])
    return jsonify({'status': 'ok', 'message': 'Статус добавлен'})

@app.route('/api/statuses/<name>', methods=['DELETE'])
def api_delete_status(name):
    """Удалить статус"""
    db_manager.delete_task_status(name, soft=True)
    return jsonify({'status': 'ok', 'message': 'Статус удалён'})

# ============ API: ШАБЛОНЫ ============

@app.route('/api/templates')
def api_get_templates():
    """Получить шаблоны"""
    templates = db_manager.get_all_templates()
    return jsonify(templates)

@app.route('/api/templates', methods=['POST'])
def api_save_templates():
    """Сохранить шаблоны"""
    data = request.json
    for name, template in data.items():
        db_manager.save_template(name, template)
    return jsonify({'status': 'ok', 'message': 'Шаблоны сохранены'})

# ============ API: ЛОГИ ============

@app.route('/api/logs')
def api_get_logs():
    """Получить логи"""
    log_file = 'sla_bot.log'
    if not os.path.exists(log_file):
        return 'Лог-файл не найден'
    
    try:
        # Читаем последние 1000 строк
        with open(log_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            last_lines = lines[-1000:] if len(lines) > 1000 else lines
            return ''.join(last_lines)
    except Exception as e:
        return f'Ошибка чтения логов: {e}'

@app.route('/api/logs', methods=['DELETE'])
def api_clear_logs():
    """Очистить логи"""
    log_file = 'sla_bot.log'
    if os.path.exists(log_file):
        with open(log_file, 'w', encoding='utf-8') as f:
            f.write('')
    return jsonify({'status': 'ok', 'message': 'Логи очищены'})

# ============ API: СТАТИСТИКА ============

@app.route('/api/stats')
def api_get_stats():
    """Получить статистику"""
    stats = db_manager.get_stats()
    
    # Добавляем дополнительные данные
    employees = db_manager.get_employees(active_only=True)
    stats['employees_count'] = len(employees)
    
    # Проверяем, запущен ли бот
    try:
        result = os.popen('pgrep -f "sla_bot.py"').read().strip()
        stats['bot_running'] = bool(result)
        stats['bot_pid'] = result if result else None
    except:
        stats['bot_running'] = False
        stats['bot_pid'] = None
    
    # Пробуем получить данные из Jira
    try:
        import asyncio
        from api_client import TaskAPIClient
        
        async def get_jira_stats():
            client = TaskAPIClient()
            tasks = await client.get_tasks()
            return {
                'total_tasks': len(tasks),
                'urgent_tasks': len([t for t in tasks if t.get('should_notify', False)])
            }
        
        jira_stats = asyncio.run(get_jira_stats())
        stats.update(jira_stats)
    except Exception as e:
        stats['total_tasks'] = 0
        stats['urgent_tasks'] = 0
    
    return jsonify(stats)

# ============ API: УПРАВЛЕНИЕ БОТОМ ============

@app.route('/api/restart', methods=['POST'])
def api_restart_bot():
    """Перезапустить бота"""
    try:
        logger.info("🔄 Перезапуск бота...")
        
        # Убиваем старый процесс
        os.system('pkill -f "sla_bot.py"')
        time.sleep(2)
        
        # Запускаем нового бота в venv
        command = 'cd /root/sla-monitor-bot && source venv/bin/activate && nohup python3 sla_bot.py >> bot.log 2>&1 &'
        os.system(f'bash -c "{command}"')
        
        time.sleep(2)
        
        # Проверяем, запустился ли бот
        result = os.popen('pgrep -f "sla_bot.py"').read().strip()
        if result:
            logger.info(f"✅ Бот перезапущен (PID: {result})")
            return jsonify({'status': 'ok', 'message': f'🔄 Бот перезапущен (PID: {result})'})
        else:
            logger.error("❌ Бот не запустился")
            return jsonify({'status': 'error', 'message': '❌ Бот не запустился'}), 500
            
    except Exception as e:
        logger.error(f"❌ Ошибка перезапуска: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/stop', methods=['POST'])
def api_stop_bot():
    """Остановить бота"""
    try:
        os.system('pkill -f "sla_bot.py"')
        logger.info("⏹ Бот остановлен")
        return jsonify({'status': 'ok', 'message': '⏹ Бот остановлен'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# ============ ЗАПУСК ============

if __name__ == '__main__':
    print("=" * 60)
    print("🌐 Веб-интерфейс для управления SLA ботом")
    print("📍 http://vladuha20011.fvds.ru:5000")
    print("=" * 60)
    
    app.run(host='0.0.0.0', port=5000, debug=False)