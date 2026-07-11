"""
Веб-интерфейс для управления SLA ботом
"""

from flask import Flask, render_template, request, jsonify
from datetime import datetime
import os
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
                'username': emp.get('username', emp['email'].split('@')[0]),
                'status': 'active'
            })
        print("✅ Сотрудники перенесены из employees.py")
except ImportError:
    pass

# ============ СТРАНИЦЫ ============

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login')
def login():
    return render_template('index.html')

# ============ API: СОТРУДНИКИ ============

@app.route('/api/employees')
def api_get_employees():
    employees = db_manager.get_employees(active_only=True)
    return jsonify(employees)

@app.route('/api/employees/<int:employee_id>')
def api_get_employee(employee_id):
    employee = db_manager.get_employee_by_id(employee_id)
    if employee:
        return jsonify(employee)
    return jsonify({'error': 'Сотрудник не найден'}), 404

@app.route('/api/employees', methods=['POST'])
def api_add_employee():
    data = request.json
    
    if 'username' not in data or not data['username']:
        data['username'] = data['email'].split('@')[0] if data.get('email') else ''
    
    if 'search_names' not in data or not data['search_names']:
        name_parts = data['full_name'].split()
        data['search_names'] = [name_parts[0], name_parts[1]] if len(name_parts) >= 2 else [name_parts[0]]
    
    if 'status' not in data:
        data['status'] = 'active'
    
    db_manager.add_employee(data)
    return jsonify({'status': 'ok', 'message': 'Сотрудник добавлен'})

@app.route('/api/employees/<int:employee_id>', methods=['PUT'])
def api_update_employee(employee_id):
    data = request.json
    
    if 'search_names' not in data or not data['search_names']:
        name_parts = data['full_name'].split()
        data['search_names'] = [name_parts[0], name_parts[1]] if len(name_parts) >= 2 else [name_parts[0]]
    
    if 'status' not in data:
        data['status'] = 'active'
    
    db_manager.update_employee(employee_id, data)
    return jsonify({'status': 'ok', 'message': 'Сотрудник обновлён'})

@app.route('/api/employees/<int:employee_id>', methods=['DELETE'])
def api_delete_employee(employee_id):
    db_manager.delete_employee(employee_id, soft=True)
    return jsonify({'status': 'ok', 'message': 'Сотрудник удалён'})

# ============ API: НАСТРОЙКИ ============

@app.route('/api/settings')
def api_get_settings():
    settings = db_manager.get_settings()
    return jsonify(settings)

@app.route('/api/settings', methods=['POST'])
def api_update_settings():
    data = request.json
    db_manager.update_settings(data)
    return jsonify({'status': 'ok', 'message': 'Настройки сохранены'})

# ============ API: СТАТУСЫ ============

@app.route('/api/statuses')
def api_get_statuses():
    statuses = db_manager.get_task_statuses(active_only=True)
    return jsonify(statuses)

@app.route('/api/statuses', methods=['POST'])
def api_add_status():
    data = request.json
    db_manager.add_task_status(data['name'], data.get('notify_enabled', 1))
    return jsonify({'status': 'ok', 'message': 'Статус добавлен'})

@app.route('/api/statuses/<name>', methods=['PUT'])
def api_update_status(name):
    data = request.json
    db_manager.update_task_status(name, data.get('notify_enabled', 1))
    return jsonify({'status': 'ok', 'message': 'Статус обновлён'})

@app.route('/api/statuses/<name>', methods=['DELETE'])
def api_delete_status(name):
    db_manager.delete_task_status(name, soft=True)
    return jsonify({'status': 'ok', 'message': 'Статус удалён'})

# ============ API: ШАБЛОНЫ ============

@app.route('/api/templates')
def api_get_templates():
    templates = db_manager.get_all_templates_dict()
    return jsonify(templates)

@app.route('/api/templates', methods=['POST'])
def api_save_templates():
    data = request.json
    db_manager.save_templates(data)
    return jsonify({'status': 'ok', 'message': 'Шаблоны сохранены'})

# ============ API: ЛОГИ (упрощённо) ============

@app.route('/api/logs')
def api_get_logs():
    """Возвращает логи (упрощённо)"""
    return '📄 Логи временно отключены для снижения нагрузки'

@app.route('/api/logs', methods=['DELETE'])
def api_clear_logs():
    log_file = 'sla_bot.log'
    if os.path.exists(log_file):
        with open(log_file, 'w', encoding='utf-8') as f:
            f.write('')
    return jsonify({'status': 'ok', 'message': 'Логи очищены'})

# ============ API: ОШИБКИ (упрощённо) ============

@app.route('/api/error-logs')
def api_error_logs():
    """Возвращает логи ошибок (упрощённо)"""
    return jsonify([])

# ============ API: СТАТИСТИКА (упрощённо) ============

@app.route('/api/stats')
def api_get_stats():
    stats = db_manager.get_stats()
    
    employees = db_manager.get_employees(active_only=True)
    stats['employees_count'] = len(employees)
    
    try:
        result = os.popen('pgrep -f "sla_bot.py"').read().strip()
        stats['bot_running'] = bool(result)
        stats['bot_pid'] = result if result else None
    except:
        stats['bot_running'] = False
        stats['bot_pid'] = None
    
    # НЕ ходим в Jira при каждом запросе (кешируем)
    stats['total_tasks'] = 0
    stats['urgent_tasks'] = 0
    
    return jsonify(stats)

# ============ API: УПРАВЛЕНИЕ БОТОМ ============

@app.route('/api/restart', methods=['POST'])
def api_restart_bot():
    try:
        logger.info("🔄 Перезапуск бота...")
        
        os.system('pkill -f "sla_bot.py"')
        time.sleep(2)
        
        command = 'cd /root/sla-monitor-bot && source venv/bin/activate && nohup python3 sla_bot.py >> bot.log 2>&1 &'
        os.system(f'bash -c "{command}"')
        
        time.sleep(2)
        
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
    try:
        os.system('pkill -f "sla_bot.py"')
        logger.info("⏹ Бот остановлен")
        return jsonify({'status': 'ok', 'message': '⏹ Бот остановлен'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# ============ API: ПИНГ (упрощённо) ============

@app.route('/api/bot-ping')
def api_bot_ping():
    """Проверяет, работает ли бот (только процесс)"""
    import os
    result = os.popen('pgrep -f "sla_bot.py"').read().strip()
    if result:
        return jsonify({
            'status': 'ok',
            'message': '✅ OK',
            'pid': result,
            'timestamp': datetime.now().isoformat()
        })
    else:
        return jsonify({
            'status': 'error',
            'message': '❌ Бот не запущен'
        }), 503

# ============ API: УВЕДОМЛЕНИЯ ============

@app.route('/api/task/<task_key>')
def api_get_task(task_key):
    """Получить информацию о задаче по ключу"""
    try:
        import asyncio
        from api_client import TaskAPIClient
        
        async def get_task():
            client = TaskAPIClient()
            return await client.get_task_by_key(task_key)
        
        task = asyncio.run(get_task())
        
        if task:
            return jsonify(task)
        else:
            return jsonify({'error': 'Задача не найдена'}), 404
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/send-notification', methods=['POST'])
def api_send_notification():
    """Отправить уведомление по задаче"""
    try:
        import asyncio
        from telegram import Bot
        import config
        from api_client import TaskAPIClient
        import db_manager
        
        data = request.json
        task_key = data.get('task_key')
        priority = data.get('priority', 'Обычное')
        
        if not task_key:
            return jsonify({'error': 'Не указан номер задачи'}), 400
        
        async def get_task():
            client = TaskAPIClient()
            return await client.get_task_by_key(task_key)
        
        task = asyncio.run(get_task())
        
        if not task:
            return jsonify({'error': 'Задача не найдена'}), 404
        
        employee = db_manager.get_employee_by_name(task['assignee'])
        mention = employee['telegram_username'] if employee else f"@{task['assignee'].replace(' ', '_')}"
        
        priority_emoji = {
            'Обычное': '📨',
            'Важное': '⚠️',
            'Срочное': '🚨',
            'Критичное': '🔥'
        }
        
        priority_header = {
            'Обычное': 'Уведомление по задаче',
            'Важное': 'ВАЖНОЕ УВЕДОМЛЕНИЕ!',
            'Срочное': 'СРОЧНОЕ УВЕДОМЛЕНИЕ! 🚨',
            'Критичное': 'КРИТИЧНОЕ УВЕДОМЛЕНИЕ! 🔥'
        }
        
        emoji = priority_emoji.get(priority, '📨')
        header = priority_header.get(priority, 'Уведомление по задаче')
        
        due_date_str = task['due_date'].strftime('%d.%m.%Y %H:%M') if task.get('due_date') else 'не указан'
        
        message = f"{emoji} {header}\n\n"
        message += f"📌 Задача: {task['id']}\n"
        message += f"🔗 Ссылка: {task['url']}\n"
        message += f"📋 Название: {task['title']}\n"
        message += f"👤 Исполнитель: {task['assignee']} {mention}\n"
        message += f"📈 Статус: {task['status']}\n"
        message += f"⏰ Дедлайн: {due_date_str}\n"
        message += f"🎯 Приоритет: {task['priority'] or 'Не указан'}\n\n"
        
        if priority == 'Важное':
            message += "❗ Просьба обратить внимание на задачу!"
        elif priority == 'Срочное':
            message += "❗ Требуется срочное внимание к задаче!"
        elif priority == 'Критичное':
            message += "⛔ Задача требует немедленного решения!"
        else:
            message += "Просьба обратить внимание на задачу."
        
        bot = Bot(token=config.BOT_TOKEN)
        chat_id = config.CHAT_ID
        
        bot.send_message(chat_id=chat_id, text=message)
        
        return jsonify({'status': 'ok', 'message': '✅ Уведомление отправлено'})
        
    except Exception as e:
        logger.error(f"❌ Ошибка отправки уведомления: {e}")
        return jsonify({'error': str(e)}), 500


# ============ ЗАПУСК ============

if __name__ == '__main__':
    print("=" * 60)
    print("🌐 Веб-интерфейс для управления SLA ботом")
    print("📍 http://vladuha20011.fvds.ru:5000")
    print("=" * 60)
    
    app.run(host='0.0.0.0', port=5000, debug=False)
