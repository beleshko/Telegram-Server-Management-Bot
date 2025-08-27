#!/usr/bin/env python3
"""
Server Management Bot Utilities
Утилиты для обслуживания и диагностики бота
"""

import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import paramiko
from cryptography.fernet import Fernet


class BotDiagnostics:
    """Диагностика и обслуживание бота"""
    
    def __init__(self, db_path="servers.db"):
        self.db_path = db_path
        self.project_dir = Path(__file__).parent
    
    def check_system_requirements(self):
        """Проверка системных требований"""
        print("🔍 Checking system requirements...")
        print("=" * 40)
        
        # Проверка Termux
        is_termux = os.path.exists("/data/data/com.termux")
        print(f"📱 Termux environment: {'✅' if is_termux else '❌'}")
        
        # Проверка Python
        python_version = sys.version.split()[0]
        print(f"🐍 Python version: {python_version}")
        
        # Проверка пакетов
        required_packages = [
            "telegram", "paramiko", "cryptography", "schedule"
        ]
        
        for package in required_packages:
            try:
                __import__(package)
                print(f"📦 {package}: ✅")
            except ImportError:
                print(f"📦 {package}: ❌ (install with: pip install {package})")
        
        # Проверка Termux API
        try:
            result = subprocess.run(['which', 'termux-battery-status'], 
                                  capture_output=True, text=True)
            api_available = result.returncode == 0
            print(f"🔋 Termux API: {'✅' if api_available else '❌'}")
            
            if api_available:
                # Тест батареи
                try:
                    result = subprocess.run(['termux-battery-status'], 
                                          capture_output=True, text=True, timeout=5)
                    if result.returncode == 0:
                        battery_info = json.loads(result.stdout)
                        print(f"   Battery: {battery_info.get('percentage', 'N/A')}% "
                              f"({battery_info.get('status', 'Unknown')})")
                    else:
                        print("   ⚠️ Battery status not accessible")
                except Exception as e:
                    print(f"   ⚠️ Battery test failed: {e}")
            
        except Exception as e:
            print(f"🔋 Termux API: ❌ ({e})")
        
        # Проверка файлов конфигурации
        config_files = ['.env', 'servers.db', 'encryption.key']
        for file in config_files:
            file_path = self.project_dir / file
            exists = file_path.exists()
            print(f"📄 {file}: {'✅' if exists else '❌'}")
            
            if exists:
                size = file_path.stat().st_size
                print(f"   Size: {size} bytes")
    
    def backup_database(self, backup_dir="backups"):
        """Создание резервной копии базы данных"""
        backup_path = Path(backup_dir)
        backup_path.mkdir(exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = backup_path / f"servers_backup_{timestamp}.db"
        
        try:
            if Path(self.db_path).exists():
                import shutil
                shutil.copy2(self.db_path, backup_file)
                print(f"✅ Database backup created: {backup_file}")
                
                # Также создаем JSON экспорт
                json_backup = backup_path / f"servers_export_{timestamp}.json"
                self.export_to_json(json_backup)
                
                return str(backup_file)
            else:
                print(f"❌ Database file not found: {self.db_path}")
                return None
        except Exception as e:
            print(f"❌ Backup failed: {e}")
            return None
    
    def export_to_json(self, output_file):
        """Экспорт данных в JSON (без паролей)"""
        try:
            conn = sqlite3.connect(self.db_path)
            
            export_data = {
                "export_date": datetime.now().isoformat(),
                "servers": [],
                "logs": [],
                "settings": []
            }
            
            # Экспорт серверов (без паролей)
            cursor = conn.cursor()
            cursor.execute("SELECT id, name, ip_address, port, username, key_path, shutdown_command, created_at FROM servers")
            for row in cursor.fetchall():
                server = {
                    "id": row[0],
                    "name": row[1],
                    "ip_address": row[2],
                    "port": row[3],
                    "username": row[4],
                    "key_path": row[5],
                    "shutdown_command": row[6],
                    "created_at": row[7]
                }
                export_data["servers"].append(server)
            
            # Экспорт последних 50 логов
            cursor.execute("SELECT event_type, message, server_name, status, timestamp FROM event_logs ORDER BY timestamp DESC LIMIT 50")
            for row in cursor.fetchall():
                log = {
                    "event_type": row[0],
                    "message": row[1],
                    "server_name": row[2],
                    "status": row[3],
                    "timestamp": row[4]
                }
                export_data["logs"].append(log)
            
            # Экспорт настроек (если есть)
            try:
                cursor.execute("SELECT key, value FROM settings")
                for row in cursor.fetchall():
                    setting = {
                        "key": row[0],
                        "value": row[1]
                    }
                    export_data["settings"].append(setting)
            except sqlite3.OperationalError:
                pass  # Таблица настроек может не существовать
            
            conn.close()
            
            # Сохранение в JSON
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False)
            
            print(f"✅ JSON export created: {output_file}")
            
        except Exception as e:
            print(f"❌ JSON export failed: {e}")
    
    def test_ssh_connections(self):
        """Тестирование всех SSH подключений"""
        print("🔗 Testing SSH connections...")
        print("=" * 40)
        
        if not Path(self.db_path).exists():
            print("❌ Database not found")
            return
        
        try:
            # Загрузка ключа шифрования
            if Path("encryption.key").exists():
                with open("encryption.key", "rb") as key_file:
                    key = key_file.read()
                cipher = Fernet(key)
            else:
                print("⚠️ Encryption key not found - passwords cannot be decrypted")
                cipher = None
            
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM servers")
            servers = cursor.fetchall()
            conn.close()
            
            if not servers:
                print("ℹ️ No servers configured")
                return
            
            for server in servers:
                name = server[1]
                ip = server[2]
                port = server[3]
                username = server[4]
                encrypted_password = server[5]
                key_path = server[6]
                
                print(f"\n🖥️ Testing {name} ({ip}:{port})")
                
                try:
                    client = paramiko.SSHClient()
                    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                    
                    # Подготовка аутентификации
                    auth_kwargs = {
                        'hostname': ip,
                        'port': port,
                        'username': username,
                        'timeout': 10
                    }
                    
                    if encrypted_password and cipher:
                        try:
                            password = cipher.decrypt(encrypted_password.encode()).decode()
                            auth_kwargs['password'] = password
                            print("   🔐 Using password authentication")
                        except Exception:
                            print("   ❌ Password decryption failed")
                            continue
                    elif key_path and Path(key_path).exists():
                        auth_kwargs['key_filename'] = key_path
                        print(f"   🔑 Using key authentication: {key_path}")
                    else:
                        print("   ❌ No valid authentication method")
                        continue
                    
                    # Попытка подключения
                    start_time = datetime.now()
                    client.connect(**auth_kwargs)
                    connection_time = (datetime.now() - start_time).total_seconds()
                    
                    # Тест команды
                    stdin, stdout, stderr = client.exec_command('whoami')
                    result = stdout.read().decode().strip()
                    
                    client.close()
                    
                    print(f"   ✅ Connection successful ({connection_time:.2f}s)")
                    print(f"   👤 Remote user: {result}")
                    
                except Exception as e:
                    print(f"   ❌ Connection failed: {e}")
            
        except Exception as e:
            print(f"❌ Test failed: {e}")
    
    def cleanup_logs(self, days_to_keep=30):
        """Очистка старых логов"""
        print(f"🧹 Cleaning up logs older than {days_to_keep} days...")
        
        if not Path(self.db_path).exists():
            print("❌ Database not found")
            return
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Удаление старых записей
            cutoff_date = datetime.now() - timedelta(days=days_to_keep)
            cursor.execute(
                "DELETE FROM event_logs WHERE timestamp < ?",
                (cutoff_date.isoformat(),)
            )
            
            deleted_count = cursor.rowcount
            conn.commit()
            conn.close()
            
            print(f"✅ Deleted {deleted_count} old log entries")
            
            # Очистка файлов логов
            logs_dir = Path("logs")
            if logs_dir.exists():
                deleted_files = 0
                for log_file in logs_dir.glob("*.log"):
                    file_age = datetime.now() - datetime.fromtimestamp(log_file.stat().st_mtime)
                    if file_age.days > days_to_keep:
                        log_file.unlink()
                        deleted_files += 1
                
                print(f"✅ Deleted {deleted_files} old log files")
        
        except Exception as e:
            print(f"❌ Cleanup failed: {e}")
    
    def show_statistics(self):
        """Показать статистику использования"""
        print("📊 Bot Statistics")
        print("=" * 40)
        
        if not Path(self.db_path).exists():
            print("❌ Database not found")
            return
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Количество серверов
            cursor.execute("SELECT COUNT(*) FROM servers")
            server_count = cursor.fetchone()[0]
            print(f"🖥️ Total servers: {server_count}")
            
            # Статистика событий
            cursor.execute("""
                SELECT event_type, COUNT(*) as count 
                FROM event_logs 
                GROUP BY event_type 
                ORDER BY count DESC
            """)
            
            print("\n📋 Event statistics:")
            for event_type, count in cursor.fetchall():
                icon = self._get_event_icon(event_type)
                print(f"   {icon} {event_type}: {count}")
            
            # Последние события
            cursor.execute("""
                SELECT event_type, message, timestamp 
                FROM event_logs 
                ORDER BY timestamp DESC 
                LIMIT 5
            """)
            
            print("\n🕐 Recent events:")
            for event_type, message, timestamp in cursor.fetchall():
                icon = self._get_event_icon(event_type)
                dt = datetime.fromisoformat(timestamp)
                formatted_time = dt.strftime("%d.%m %H:%M")
                print(f"   {icon} {formatted_time}: {message}")
            
            # Статистика за последние 30 дней
            thirty_days_ago = datetime.now() - timedelta(days=30)
            cursor.execute("""
                SELECT COUNT(*) FROM event_logs 
                WHERE timestamp > ? AND event_type = 'power_loss'
            """, (thirty_days_ago.isoformat(),))
            
            power_losses = cursor.fetchone()[0]
            print(f"\n⚡ Power losses (30 days): {power_losses}")
            
            cursor.execute("""
                SELECT COUNT(*) FROM event_logs 
                WHERE timestamp > ? AND event_type = 'server_shutdown'
            """, (thirty_days_ago.isoformat(),))
            
            shutdowns = cursor.fetchone()[0]
            print(f"🔴 Server shutdowns (30 days): {shutdowns}")
            
            conn.close()
            
        except Exception as e:
            print(f"❌ Statistics failed: {e}")
    
    def _get_event_icon(self, event_type):
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
    
    def interactive_menu(self):
        """Интерактивное меню"""
        while True:
            print("\n🤖 Server Management Bot - Utilities")
            print("=" * 40)
            print("1. 🔍 Check system requirements")
            print("2. 💾 Backup database")
            print("3. 🔗 Test SSH connections")
            print("4. 🧹 Cleanup old logs")
            print("5. 📊 Show statistics")
            print("6. 📤 Export data to JSON")
            print("0. 🚪 Exit")
            print()
            
            try:
                choice = input("Select option: ").strip()
                
                if choice == "1":
                    self.check_system_requirements()
                elif choice == "2":
                    self.backup_database()
                elif choice == "3":
                    self.test_ssh_connections()
                elif choice == "4":
                    days = input("Days to keep (default 30): ").strip()
                    days = int(days) if days.isdigit() else 30
                    self.cleanup_logs(days)
                elif choice == "5":
                    self.show_statistics()
                elif choice == "6":
                    filename = input("Output file (default: export.json): ").strip()
                    filename = filename if filename else "export.json"
                    self.export_to_json(filename)
                elif choice == "0":
                    print("👋 Goodbye!")
                    break
                else:
                    print("❌ Invalid option")
                
                input("\nPress Enter to continue...")
                
            except KeyboardInterrupt:
                print("\n👋 Goodbye!")
                break
            except Exception as e:
                print(f"❌ Error: {e}")
                input("Press Enter to continue...")


def main():
    """Главная функция"""
    if len(sys.argv) > 1:
        # Режим командной строки
        diagnostics = BotDiagnostics()
        command = sys.argv[1].lower()
        
        if command == "check":
            diagnostics.check_system_requirements()
        elif command == "backup":
            diagnostics.backup_database()
        elif command == "test":
            diagnostics.test_ssh_connections()
        elif command == "cleanup":
            days = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 30
            diagnostics.cleanup_logs(days)
        elif command == "stats":
            diagnostics.show_statistics()
        elif command == "export":
            filename = sys.argv[2] if len(sys.argv) > 2 else "export.json"
            diagnostics.export_to_json(filename)
        else:
            print("Usage: python bot_utils.py [check|backup|test|cleanup|stats|export]")
            print("Or run without arguments for interactive menu")
    else:
        # Интерактивный режим
        diagnostics = BotDiagnostics()
        diagnostics.interactive_menu()


if __name__ == "__main__":
    main()
