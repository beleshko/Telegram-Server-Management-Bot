#!/usr/bin/env python3
"""
Telegram Bot for Server Management with Power Monitoring
Designed for Termux on Android
"""

import asyncio
import json
import logging
import os
import sqlite3
import subprocess
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import paramiko
import schedule
from cryptography.fernet import Fernet
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('server_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class DatabaseManager:
    """Менеджер базы данных для хранения серверов и настроек"""
    
    def __init__(self, db_path: str = "servers.db"):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """Инициализация базы данных"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Таблица серверов
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS servers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                ip_address TEXT NOT NULL,
                port INTEGER DEFAULT 22,
                username TEXT NOT NULL,
                password_encrypted TEXT,
                key_path TEXT,
                shutdown_command TEXT DEFAULT 'sudo shutdown -h now',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Таблица настроек
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Таблица логов
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS event_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                message TEXT NOT NULL,
                server_name TEXT,
                status TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def add_server(self, name: str, ip: str, port: int, username: str, 
                   password: str = None, key_path: str = None, 
                   shutdown_command: str = 'sudo shutdown -h now') -> bool:
        """Добавление сервера"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            encrypted_password = None
            if password:
                encrypted_password = CryptoManager().encrypt(password)
            
            cursor.execute('''
                INSERT INTO servers (name, ip_address, port, username, password_encrypted, key_path, shutdown_command)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (name, ip, port, username, encrypted_password, key_path, shutdown_command))
            
            conn.commit()
            conn.close()
            return True
        except sqlite3.IntegrityError:
            return False
        except Exception as e:
            logger.error(f"Error adding server: {e}")
            return False
    
    def get_servers(self) -> List[Dict]:
        """Получение списка серверов"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM servers')
        rows = cursor.fetchall()
        conn.close()
        
        servers = []
        for row in rows:
            server = {
                'id': row[0],
                'name': row[1],
                'ip_address': row[2],
                'port': row[3],
                'username': row[4],
                'password_encrypted': row[5],
                'key_path': row[6],
                'shutdown_command': row[7],
                'created_at': row[8],
                'updated_at': row[9]
            }
            servers.append(server)
        
        return servers
    
    def remove_server(self, server_name: str) -> bool:
        """Удаление сервера"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('DELETE FROM servers WHERE name = ?', (server_name,))
            affected_rows = cursor.rowcount
            
            conn.commit()
            conn.close()
            
            return affected_rows > 0
        except Exception as e:
            logger.error(f"Error removing server: {e}")
            return False
    
    def log_event(self, event_type: str, message: str, server_name: str = None, status: str = None):
        """Логирование событий"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO event_logs (event_type, message, server_name, status)
                VALUES (?, ?, ?, ?)
            ''', (event_type, message, server_name, status))
            
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Error logging event: {e}")
    
    def get_recent_logs(self, limit: int = 20) -> List[Dict]:
        """Получение последних логов"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM event_logs 
            ORDER BY timestamp DESC 
            LIMIT ?
        ''', (limit,))
        
        rows = cursor.fetchall()
        conn.close()
        
        logs = []
        for row in rows:
            log = {
                'id': row[0],
                'event_type': row[1],
                'message': row[2],
                'server_name': row[3],
                'status': row[4],
                'timestamp': row[5]
            }
            logs.append(log)
        
        return logs

class CryptoManager:
    """Менеджер шифрования для защиты чувствительных данных"""
    
    def __init__(self):
        self.key_file = "encryption.key"
        self.key = self._load_or_generate_key()
        self.cipher = Fernet(self.key)
    
    def _load_or_generate_key(self) -> bytes:
        """Загрузка или генерация ключа шифрования"""
        if os.path.exists(self.key_file):
            with open(self.key_file, 'rb') as key_file:
                return key_file.read()
        else:
            key = Fernet.generate_key()
            with open(self.key_file, 'wb') as key_file:
                key_file.write(key)
            return key
    
    def encrypt(self, data: str) -> str:
        """Шифрование данных"""
        encrypted_data = self.cipher.encrypt(data.encode())
        return encrypted_data.decode()
    
    def decrypt(self, encrypted_data: str) -> str:
        """Расшифровка данных"""
        decrypted_data = self.cipher.decrypt(encrypted_data.encode())
        return decrypted_data.decode()

class PowerMonitor:
    """Монитор питания для Android/Termux"""
    
    def __init__(self, bot_instance):
        self.bot = bot_instance
        self.is_monitoring = False
        self.is_charging = self._get_charging_status()
        self.last_power_loss_time = None
        self.notification_thread = None
        self.monitor_thread = None
    
    def _get_charging_status(self) -> bool:
        """Получение статуса зарядки на Android"""
        try:
            # Использование Termux API для получения статуса батареи
            result = subprocess.run(['termux-battery-status'], 
                                  capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                battery_info = json.loads(result.stdout)
                return battery_info.get('plugged', 'UNPLUGGED') != 'UNPLUGGED'
            else:
                # Fallback метод через /sys/class/power_supply
                with open('/sys/class/power_supply/battery/status', 'r') as f:
                    status = f.read().strip()
                return status == 'Charging'
        except Exception as e:
            logger.error(f"Error getting charging status: {e}")
            return True  # Предполагаем подключение к питанию при ошибке
    
    def start_monitoring(self):
        """Запуск мониторинга питания"""
        if self.is_monitoring:
            return
        
        self.is_monitoring = True
        self.monitor_thread = threading.Thread(target=self._monitor_power, daemon=True)
        self.monitor_thread.start()
        logger.info("Power monitoring started")
    
    def stop_monitoring(self):
        """Остановка мониторинга питания"""
        self.is_monitoring = False
        if self.notification_thread and self.notification_thread.is_alive():
            self.notification_thread.join(timeout=1)
    
    def _monitor_power(self):
        """Основной цикл мониторинга питания"""
        while self.is_monitoring:
            try:
                current_charging = self._get_charging_status()
                
                if self.is_charging and not current_charging:
                    # Питание отключено
                    logger.warning("Power loss detected!")
                    self.last_power_loss_time = datetime.now()
                    asyncio.run_coroutine_threadsafe(
                        self.bot.handle_power_loss(), 
                        self.bot.application.loop
                    )
                    self._start_notification_cycle()
                
                elif not self.is_charging and current_charging:
                    # Питание восстановлено
                    logger.info("Power restored!")
                    asyncio.run_coroutine_threadsafe(
                        self.bot.handle_power_restore(), 
                        self.bot.application.loop
                    )
                    self._stop_notification_cycle()
                
                self.is_charging = current_charging
                time.sleep(2)  # Проверка каждые 2 секунды
                
            except Exception as e:
                logger.error(f"Error in power monitoring: {e}")
                time.sleep(5)
    
    def _start_notification_cycle(self):
        """Запуск цикла уведомлений каждые 5 минут"""
        if self.notification_thread and self.notification_thread.is_alive():
            return
        
        self.notification_thread = threading.Thread(
            target=self._notification_cycle, daemon=True
        )
        self.notification_thread.start()
    
    def _stop_notification_cycle(self):
        """Остановка цикла уведомлений"""
        # Поток завершится сам при восстановлении питания
        pass
    
    def _notification_cycle(self):
        """Цикл периодических уведомлений"""
        while not self.is_charging and self.is_monitoring:
            time.sleep(300)  # 5 минут
            if not self.is_charging:  # Проверяем еще раз
                elapsed = datetime.now() - self.last_power_loss_time
                asyncio.run_coroutine_threadsafe(
                    self.bot.send_power_reminder(elapsed), 
                    self.bot.application.loop
                )

class SSHManager:
    """Менеджер SSH-подключений для управления серверами"""
    
    def __init__(self):
        self.crypto = CryptoManager()
    
    def test_connection(self, server: Dict) -> Tuple[bool, str]:
        """Тестирование подключения к серверу"""
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            # Подготовка аутентификации
            auth_kwargs = {
                'hostname': server['ip_address'],
                'port': server['port'],
                'username': server['username'],
                'timeout': 10
            }
            
            if server['password_encrypted']:
                password = self.crypto.decrypt(server['password_encrypted'])
                auth_kwargs['password'] = password
            elif server['key_path'] and os.path.exists(server['key_path']):
                auth_kwargs['key_filename'] = server['key_path']
            else:
                return False, "No authentication method available"
            
            client.connect(**auth_kwargs)
            client.close()
            return True, "Connection successful"
            
        except Exception as e:
            return False, str(e)
    
    def shutdown_server(self, server: Dict) -> Tuple[bool, str]:
        """Безопасное отключение сервера"""
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                client = paramiko.SSHClient()
                client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                
                # Подготовка аутентификации
                auth_kwargs = {
                    'hostname': server['ip_address'],
                    'port': server['port'],
                    'username': server['username'],
                    'timeout': 10
                }
                
                if server['password_encrypted']:
                    password = self.crypto.decrypt(server['password_encrypted'])
                    auth_kwargs['password'] = password
                elif server['key_path'] and os.path.exists(server['key_path']):
                    auth_kwargs['key_filename'] = server['key_path']
                else:
                    return False, "No authentication method available"
                
                client.connect(**auth_kwargs)
                
                # Выполнение команды отключения
                stdin, stdout, stderr = client.exec_command(server['shutdown_command'])
                
                # Ожидание завершения команды (с таймаутом)
                exit_status = stdout.channel.recv_exit_status()
                
                client.close()
                
                if exit_status == 0:
                    return True, f"Shutdown successful (attempt {attempt + 1})"
                else:
                    error_output = stderr.read().decode().strip()
                    if attempt == max_retries - 1:
                        return False, f"Shutdown failed: {error_output}"
                
            except Exception as e:
                if attempt == max_retries - 1:
                    return False, f"Connection failed after {max_retries} attempts: {str(e)}"
                time.sleep(2)  # Пауза перед повтором
        
        return False, "Max retries exceeded"

class ServerBot:
    """Основной класс Telegram-бота"""
    
    def __init__(self, token: str, allowed_username: str):
        self.token = token
        self.allowed_username = allowed_username.replace('@', '')
        self.db = DatabaseManager()
        self.ssh = SSHManager()
        self.power_monitor = PowerMonitor(self)
        self.application = None
        
        # Состояния для диалогов
        self.user_states = {}
        self.temp_server_data = {}
    
    def is_authorized(self, update: Update) -> bool:
        """Проверка авторизации пользователя"""
        if not update.effective_user:
            return False
        return update.effective_user.username == self.allowed_username
    
    async def start_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /start"""
        if not self.is_authorized(update):
            await update.message.reply_text("Access denied. You are not authorized to use this bot.")
            return
        
        keyboard = [
            [KeyboardButton("📊 Status"), KeyboardButton("🖥️ Servers")],
            [KeyboardButton("⚙️ Settings"), KeyboardButton("📋 Logs")],
            [KeyboardButton("🧪 Test Shutdown")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        welcome_text = (
            "🤖 *Server Management Bot* активирован!\n\n"
            "Доступные функции:\n"
            "📊 Status - текущий статус системы\n"
            "🖥️ Servers - управление серверами\n"
            "⚙️ Settings - настройки бота\n"
            "📋 Logs - просмотр журнала событий\n"
            "🧪 Test Shutdown - тестовое отключение серверов\n\n"
            "Мониторинг питания запущен ✅"
        )
        
        await update.message.reply_text(welcome_text, parse_mode='Markdown', reply_markup=reply_markup)
        
        # Запуск мониторинга питания
        if not self.power_monitor.is_monitoring:
            self.power_monitor.start_monitoring()
    
    async def status_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик статуса системы"""
        if not self.is_authorized(update):
            return
        
        # Получение статуса питания
        charging_status = "🔌 Подключено" if self.power_monitor.is_charging else "🔋 От батареи"
        
        # Получение списка серверов
        servers = self.db.get_servers()
        server_count = len(servers)
        
        # Проверка подключения
        is_connected, message = self.ssh.test_connection(test_server)
        
        if not is_connected:
            await update.message.reply_text(
                f"❌ Ошибка подключения к серверу:\n{message}\n\n"
                "Проверьте данные и попробуйте еще раз. Начните с команды /start"
            )
            # Очистка состояния
            del self.user_states[user_id]
            del self.temp_server_data[user_id]
            return
        
        # Сохранение в базу данных
        success = self.db.add_server(
            name=server_data['name'],
            ip=server_data['ip'],
            port=server_data['port'],
            username=server_data['username'],
            password=server_data.get('password'),
            key_path=server_data.get('key_path'),
            shutdown_command=server_data['shutdown_command']
        )
        
        if success:
            await update.message.reply_text(
                f"✅ Сервер '{server_data['name']}' успешно добавлен!\n"
                f"📍 IP: {server_data['ip']}:{server_data['port']}\n"
                f"👤 Пользователь: {server_data['username']}\n"
                f"✅ Подключение протестировано успешно"
            )
            self.db.log_event("server_added", f"Server {server_data['name']} added successfully", server_data['name'])
        else:
            await update.message.reply_text(
                f"❌ Ошибка при сохранении сервера '{server_data['name']}'\n"
                "Возможно, сервер с таким именем уже существует"
            )
        
        # Очистка состояния
        del self.user_states[user_id]
        del self.temp_server_data[user_id]
    
    async def show_logs(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать логи событий"""
        if not self.is_authorized(update):
            return
        
        logs = self.db.get_recent_logs(10)
        
        if not logs:
            text = "📋 *Журнал событий*\n\nСобытий пока нет"
        else:
            text = "📋 *Журнал событий* (последние 10)\n\n"
            for log in logs:
                timestamp = datetime.fromisoformat(log['timestamp']).strftime("%d.%m %H:%M")
                icon = self._get_event_icon(log['event_type'])
                text += f"{icon} `{timestamp}` {log['message']}\n"
        
        await update.message.reply_text(text, parse_mode='Markdown')
    
    def _get_event_icon(self, event_type: str) -> str:
        """Получить иконку для типа события"""
        icons = {
            'power_loss': '⚡',
            'power_restore': '🔌',
            'server_shutdown': '🔴',
            'server_added': '➕',
            'server_removed': '🗑️',
            'test_shutdown': '🧪',
            'error': '❌'
        }
        return icons.get(event_type, '📝')
    
    async def test_shutdown(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Тестовое отключение серверов"""
        if not self.is_authorized(update):
            return
        
        servers = self.db.get_servers()
        
        if not servers:
            await update.message.reply_text("🧪 Нет серверов для тестирования")
            return
        
        await update.message.reply_text(
            "🧪 *Тестовое отключение серверов*\n\n"
            "⚠️ ВНИМАНИЕ: Это приведет к реальному отключению серверов!\n"
            "Для подтверждения отправьте: `CONFIRM TEST`",
            parse_mode='Markdown'
        )
        
        # Установка состояния ожидания подтверждения
        self.user_states[update.effective_user.id] = "confirming_test"
    
    async def show_settings(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать настройки бота"""
        if not self.is_authorized(update):
            return
        
        monitoring_status = "✅ Включен" if self.power_monitor.is_monitoring else "❌ Выключен"
        charging_status = "🔌 Подключено" if self.power_monitor.is_charging else "🔋 От батареи"
        
        text = f"⚙️ *Настройки бота*\n\n"
        text += f"🔍 Мониторинг питания: {monitoring_status}\n"
        text += f"⚡ Текущее состояние: {charging_status}\n"
        text += f"👤 Авторизованный пользователь: @{self.allowed_username}\n"
        text += f"📂 База данных: {'✅ Доступна' if os.path.exists(self.db.db_path) else '❌ Недоступна'}\n"
        text += f"🔐 Шифрование: {'✅ Активно' if os.path.exists('encryption.key') else '❌ Неактивно'}\n\n"
        text += f"📊 Серверов в базе: {len(self.db.get_servers())}\n"
        
        keyboard = [
            [InlineKeyboardButton("🔄 Перезапустить мониторинг", callback_data="restart_monitoring")],
            [InlineKeyboardButton("🧹 Очистить логи", callback_data="clear_logs")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(text, parse_mode='Markdown', reply_markup=reply_markup)
    
    async def handle_power_loss(self):
        """Обработка потери питания"""
        try:
            # Отправка немедленного уведомления
            message = (
                "🚨 *ОТКЛЮЧЕНИЕ ЭЛЕКТРОПИТАНИЯ!*\n\n"
                "⚡ Обнаружено отключение от сети\n"
                f"🕐 Время: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n\n"
                "🔄 Начинаю безопасное отключение серверов..."
            )
            
            await self.application.bot.send_message(
                chat_id=f"@{self.allowed_username}",
                text=message,
                parse_mode='Markdown'
            )
            
            # Логирование события
            self.db.log_event("power_loss", "Power loss detected, starting server shutdown sequence")
            
            # Получение списка серверов
            servers = self.db.get_servers()
            
            if not servers:
                await self.application.bot.send_message(
                    chat_id=f"@{self.allowed_username}",
                    text="ℹ️ Серверы для отключения не найдены"
                )
                return
            
            # Отключение каждого сервера
            shutdown_results = []
            for server in servers:
                success, message = self.ssh.shutdown_server(server)
                
                status_icon = "✅" if success else "❌"
                result_text = f"{status_icon} {server['name']}: {message}"
                shutdown_results.append(result_text)
                
                # Логирование результата
                self.db.log_event(
                    "server_shutdown",
                    f"Shutdown {server['name']}: {message}",
                    server['name'],
                    "success" if success else "failed"
                )
            
            # Отправка отчета
            report = "📋 *Отчет об отключении серверов:*\n\n" + "\n".join(shutdown_results)
            await self.application.bot.send_message(
                chat_id=f"@{self.allowed_username}",
                text=report,
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Error in handle_power_loss: {e}")
            self.db.log_event("error", f"Error in power loss handling: {str(e)}")
    
    async def handle_power_restore(self):
        """Обработка восстановления питания"""
        try:
            duration = ""
            if self.power_monitor.last_power_loss_time:
                elapsed = datetime.now() - self.power_monitor.last_power_loss_time
                hours, remainder = divmod(elapsed.total_seconds(), 3600)
                minutes, _ = divmod(remainder, 60)
                duration = f"Длительность отключения: {int(hours):02d}:{int(minutes):02d}"
            
            message = (
                "🔌 *ПИТАНИЕ ВОССТАНОВЛЕНО*\n\n"
                "✅ Подключение к электросети восстановлено\n"
                f"🕐 Время восстановления: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n"
                f"{duration}\n\n"
                "ℹ️ Серверы могут потребовать ручного запуска"
            )
            
            await self.application.bot.send_message(
                chat_id=f"@{self.allowed_username}",
                text=message,
                parse_mode='Markdown'
            )
            
            self.db.log_event("power_restore", "Power restored")
            
        except Exception as e:
            logger.error(f"Error in handle_power_restore: {e}")
    
    async def send_power_reminder(self, elapsed: timedelta):
        """Отправка напоминания о продолжающемся отключении"""
        try:
            hours, remainder = divmod(elapsed.total_seconds(), 3600)
            minutes, _ = divmod(remainder, 60)
            
            message = (
                "⚠️ *НАПОМИНАНИЕ: ПИТАНИЕ ВСЕ ЕЩЕ ОТКЛЮЧЕНО*\n\n"
                f"⏱️ Прошло времени: {int(hours):02d}:{int(minutes):02d}\n"
                f"🕐 Время: {datetime.now().strftime('%H:%M:%S')}\n\n"
                "🔋 Устройство работает от батареи"
            )
            
            await self.application.bot.send_message(
                chat_id=f"@{self.allowed_username}",
                text=message,
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Error sending power reminder: {e}")
    
    async def handle_test_confirmation(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка подтверждения тестового отключения"""
        if update.message.text == "CONFIRM TEST":
            servers = self.db.get_servers()
            
            await update.message.reply_text("🧪 Начинаю тестовое отключение серверов...")
            
            shutdown_results = []
            for server in servers:
                success, message = self.ssh.shutdown_server(server)
                
                status_icon = "✅" if success else "❌"
                result_text = f"{status_icon} {server['name']}: {message}"
                shutdown_results.append(result_text)
                
                self.db.log_event(
                    "test_shutdown",
                    f"Test shutdown {server['name']}: {message}",
                    server['name'],
                    "success" if success else "failed"
                )
            
            report = "📋 *Результаты тестового отключения:*\n\n" + "\n".join(shutdown_results)
            await update.message.reply_text(report, parse_mode='Markdown')
        else:
            await update.message.reply_text("❌ Тестовое отключение отменено")
        
        # Сброс состояния
        del self.user_states[update.effective_user.id]
    
    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик ошибок"""
        logger.error(f"Exception while handling an update: {context.error}")
    
    def run(self):
        """Запуск бота"""
        # Создание приложения
        self.application = Application.builder().token(self.token).build()
        
        # Добавление обработчиков
        self.application.add_handler(CommandHandler("start", self.start_handler))
        self.application.add_handler(CallbackQueryHandler(self.callback_query_handler))
        self.application.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND, 
            self._message_router
        ))
        
        # Обработчик ошибок
        self.application.add_error_handler(self.error_handler)
        
        logger.info("Starting Server Management Bot...")
        
        # Запуск бота
        self.application.run_polling(allowed_updates=Update.ALL_TYPES)
    
    async def _message_router(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Маршрутизатор сообщений"""
        user_id = update.effective_user.id
        
        # Проверка состояния подтверждения теста
        if user_id in self.user_states and self.user_states[user_id] == "confirming_test":
            await self.handle_test_confirmation(update, context)
        else:
            await self.message_handler(update, context)

def load_config() -> tuple:
    """Загрузка конфигурации из переменных окружения"""
    bot_token = os.getenv('BOT_TOKEN')
    allowed_user = os.getenv('ALLOWED_USER', '@mgmwm')
    
    if not bot_token:
        logger.error("BOT_TOKEN environment variable is required!")
        exit(1)
    
    return bot_token, allowed_user

def setup_termux_environment():
    """Настройка окружения Termux"""
    try:
        # Проверка доступности termux-battery-status
        result = subprocess.run(['which', 'termux-battery-status'], 
                              capture_output=True, text=True)
        if result.returncode != 0:
            logger.warning("termux-battery-status not found. Install termux-api package.")
            print("To install termux-api:")
            print("pkg install termux-api")
            print("Also install Termux:API from Google Play Store")
    
    except Exception as e:
        logger.error(f"Error setting up Termux environment: {e}")

def create_systemd_service():
    """Создание службы для автозапуска (для Termux)"""
    service_content = f"""#!/data/data/com.termux/files/usr/bin/bash
cd {os.getcwd()}
python server_bot.py
"""
    
    # Создание скрипта запуска
    with open("start_bot.sh", "w") as f:
        f.write(service_content)
    
    os.chmod("start_bot.sh", 0o755)
    
    print("Created start_bot.sh for manual startup")
    print("To run in background: nohup ./start_bot.sh &")

def main():
    """Главная функция"""
    print("🤖 Server Management Bot starting...")
    
    # Настройка окружения
    setup_termux_environment()
    
    # Загрузка конфигурации
    try:
        bot_token, allowed_user = load_config()
    except SystemExit:
        print("\n❌ Configuration error!")
        print("Please set the BOT_TOKEN environment variable:")
        print("export BOT_TOKEN='your_bot_token_here'")
        print("export ALLOWED_USER='@your_username'  # optional, defaults to @mgmwm")
        return
    
    # Создание и запуск бота
    try:
        bot = ServerBot(bot_token, allowed_user)
        
        # Создание службы автозапуска
        create_systemd_service()
        
        print(f"✅ Bot configured for user: {allowed_user}")
        print("🔍 Power monitoring will start after /start command")
        print("📱 Send /start to the bot to begin")
        
        bot.run()
        
    except KeyboardInterrupt:
        print("\n👋 Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        print(f"❌ Fatal error: {e}")

if __name__ == "__main__":
    main()верка доступности серверов
        online_servers = 0
        offline_servers = 0
        
        status_text = f"📊 *Статус системы*\n\n"
        status_text += f"⚡ Питание: {charging_status}\n"
        status_text += f"🖥️ Серверов: {server_count}\n"
        
        if servers:
            status_text += f"\n*Статус серверов:*\n"
            for server in servers[:5]:  # Показываем только первые 5
                is_online, message = self.ssh.test_connection(server)
                status_icon = "🟢" if is_online else "🔴"
                status_text += f"{status_icon} {server['name']} ({server['ip_address']})\n"
                if is_online:
                    online_servers += 1
                else:
                    offline_servers += 1
            
            if len(servers) > 5:
                status_text += f"... и еще {len(servers) - 5} серверов\n"
        
        status_text += f"\n🟢 Онлайн: {online_servers}\n"
        status_text += f"🔴 Офлайн: {offline_servers}\n"
        
        # Информация о мониторинге
        monitoring_status = "✅ Активен" if self.power_monitor.is_monitoring else "❌ Неактивен"
        status_text += f"\n🔍 Мониторинг: {monitoring_status}\n"
        
        await update.message.reply_text(status_text, parse_mode='Markdown')
    
    async def servers_menu_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик меню серверов"""
        if not self.is_authorized(update):
            return
        
        keyboard = [
            [InlineKeyboardButton("➕ Добавить сервер", callback_data="add_server")],
            [InlineKeyboardButton("📋 Список серверов", callback_data="list_servers")],
            [InlineKeyboardButton("✏️ Редактировать сервер", callback_data="edit_server")],
            [InlineKeyboardButton("🗑️ Удалить сервер", callback_data="remove_server")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "🖥️ *Управление серверами*\n\nВыберите действие:",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
    
    async def callback_query_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик callback запросов"""
        if not self.is_authorized(update):
            return
        
        query = update.callback_query
        await query.answer()
        
        if query.data == "add_server":
            await self.start_add_server(update, context)
        elif query.data == "list_servers":
            await self.list_servers(update, context)
        elif query.data == "remove_server":
            await self.start_remove_server(update, context)
        elif query.data.startswith("remove_"):
            server_name = query.data.replace("remove_", "")
            await self.confirm_remove_server(update, context, server_name)
    
    async def start_add_server(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Начало процесса добавления сервера"""
        user_id = update.effective_user.id
        self.user_states[user_id] = "adding_server_name"
        self.temp_server_data[user_id] = {}
        
        await update.callback_query.edit_message_text(
            "➕ *Добавление сервера*\n\n"
            "Введите название сервера (например: 'Main Server' или 'DB-1'):",
            parse_mode='Markdown'
        )
    
    async def list_servers(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Список серверов"""
        servers = self.db.get_servers()
        
        if not servers:
            text = "📋 *Список серверов*\n\nСерверы не добавлены"
        else:
            text = "📋 *Список серверов*\n\n"
            for server in servers:
                # Тестирование подключения
                is_online, _ = self.ssh.test_connection(server)
                status_icon = "🟢" if is_online else "🔴"
                
                text += f"{status_icon} *{server['name']}*\n"
                text += f"   📍 {server['ip_address']}:{server['port']}\n"
                text += f"   👤 {server['username']}\n"
                text += f"   📅 {server['created_at'][:10]}\n\n"
        
        await update.callback_query.edit_message_text(text, parse_mode='Markdown')
    
    async def start_remove_server(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Начало процесса удаления сервера"""
        servers = self.db.get_servers()
        
        if not servers:
            await update.callback_query.edit_message_text("🗑️ Нет серверов для удаления")
            return
        
        keyboard = []
        for server in servers:
            keyboard.append([InlineKeyboardButton(
                f"🗑️ {server['name']}", 
                callback_data=f"remove_{server['name']}"
            )])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.callback_query.edit_message_text(
            "🗑️ *Удаление сервера*\n\nВыберите сервер для удаления:",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
    
    async def confirm_remove_server(self, update: Update, context: ContextTypes.DEFAULT_TYPE, server_name: str):
        """Подтверждение удаления сервера"""
        success = self.db.remove_server(server_name)
        
        if success:
            text = f"✅ Сервер '{server_name}' успешно удален"
            self.db.log_event("server_removed", f"Server {server_name} removed", server_name)
        else:
            text = f"❌ Ошибка при удалении сервера '{server_name}'"
        
        await update.callback_query.edit_message_text(text)
    
    async def message_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик текстовых сообщений"""
        if not self.is_authorized(update):
            return
        
        user_id = update.effective_user.id
        text = update.message.text
        
        # Обработка кнопок главного меню
        if text == "📊 Status":
            await self.status_handler(update, context)
            return
        elif text == "🖥️ Servers":
            await self.servers_menu_handler(update, context)
            return
        elif text == "📋 Logs":
            await self.show_logs(update, context)
            return
        elif text == "🧪 Test Shutdown":
            await self.test_shutdown(update, context)
            return
        elif text == "⚙️ Settings":
            await self.show_settings(update, context)
            return
        
        # Обработка состояний диалогов
        if user_id in self.user_states:
            await self.handle_dialog_state(update, context, user_id, text)
    
    async def handle_dialog_state(self, update: Update, context: ContextTypes.DEFAULT_TYPE, 
                                 user_id: int, text: str):
        """Обработка состояний диалогов"""
        state = self.user_states[user_id]
        
        if state == "adding_server_name":
            self.temp_server_data[user_id]['name'] = text
            self.user_states[user_id] = "adding_server_ip"
            await update.message.reply_text(
                "📍 Введите IP-адрес сервера в локальной сети\n"
                "(например: 192.168.1.100):"
            )
        
        elif state == "adding_server_ip":
            self.temp_server_data[user_id]['ip'] = text
            self.user_states[user_id] = "adding_server_port"
            await update.message.reply_text(
                "🚪 Введите порт SSH (или нажмите Enter для порта 22 по умолчанию):"
            )
        
        elif state == "adding_server_port":
            try:
                port = int(text) if text.strip() else 22
                if 1 <= port <= 65535:
                    self.temp_server_data[user_id]['port'] = port
                    self.user_states[user_id] = "adding_server_username"
                    await update.message.reply_text("👤 Введите имя пользователя для SSH:")
                else:
                    await update.message.reply_text("❌ Порт должен быть от 1 до 65535")
            except ValueError:
                await update.message.reply_text("❌ Введите корректный номер порта")
        
        elif state == "adding_server_username":
            self.temp_server_data[user_id]['username'] = text
            self.user_states[user_id] = "adding_server_password"
            await update.message.reply_text(
                "🔐 Введите пароль для SSH\n"
                "(или отправьте 'key' если используете SSH-ключ):"
            )
        
        elif state == "adding_server_password":
            if text.lower() == 'key':
                self.user_states[user_id] = "adding_server_key"
                await update.message.reply_text(
                    "🔑 Введите полный путь к SSH-ключу\n"
                    "(например: /data/data/com.termux/files/home/.ssh/id_rsa):"
                )
            else:
                self.temp_server_data[user_id]['password'] = text
                self.user_states[user_id] = "adding_server_command"
                await update.message.reply_text(
                    "⚡ Введите команду для безопасного отключения\n"
                    "(или нажмите Enter для 'sudo shutdown -h now'):"
                )
        
        elif state == "adding_server_key":
            self.temp_server_data[user_id]['key_path'] = text
            self.user_states[user_id] = "adding_server_command"
            await update.message.reply_text(
                "⚡ Введите команду для безопасного отключения\n"
                "(или нажмите Enter для 'sudo shutdown -h now'):"
            )
        
        elif state == "adding_server_command":
            shutdown_command = text.strip() if text.strip() else 'sudo shutdown -h now'
            self.temp_server_data[user_id]['shutdown_command'] = shutdown_command
            
            # Завершение добавления сервера
            await self.finish_add_server(update, context, user_id)
    
    async def finish_add_server(self, update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
        """Завершение добавления сервера"""
        server_data = self.temp_server_data[user_id]
        
        # Тестирование подключения
        test_server = {
            'name': server_data['name'],
            'ip_address': server_data['ip'],
            'port': server_data['port'],
            'username': server_data['username'],
            'password_encrypted': None,
            'key_path': server_data.get('key_path'),
            'shutdown_command': server_data['shutdown_command']
        }
        
        if 'password' in server_data:
            test_server['password_encrypted'] = CryptoManager().encrypt(server_data['password'])
        
        # Про
