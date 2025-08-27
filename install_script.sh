#!/data/data/com.termux/files/usr/bin/bash

# Скрипт установки Server Management Bot в Termux
# Автор: Assistant
# Описание: Автоматическая установка всех необходимых компонентов

set -e

echo "🤖 Server Management Bot - Installation Script"
echo "==============================================="

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Проверка, что скрипт запущен в Termux
if [[ ! -d "/data/data/com.termux" ]]; then
    print_error "This script must be run in Termux on Android!"
    exit 1
fi

print_status "Checking Termux environment..."
print_success "Running in Termux environment"

# Обновление пакетов
print_status "Updating package repositories..."
pkg update -y

# Установка основных пакетов
print_status "Installing required packages..."
pkg install -y python git openssh termux-api

# Проверка Python
python_version=$(python --version 2>&1)
if [[ $? -eq 0 ]]; then
    print_success "Python installed: $python_version"
else
    print_error "Python installation failed!"
    exit 1
fi

# Установка pip пакетов
print_status "Installing Python packages..."
pip install --upgrade pip

packages=(
    "python-telegram-bot"
    "paramiko"
    "cryptography"
    "schedule"
)

for package in "${packages[@]}"; do
    print_status "Installing $package..."
    if pip install "$package"; then
        print_success "$package installed successfully"
    else
        print_error "Failed to install $package"
        exit 1
    fi
done

# Создание директории проекта
PROJECT_DIR="$HOME/server_bot"
print_status "Creating project directory: $PROJECT_DIR"

if [[ -d "$PROJECT_DIR" ]]; then
    print_warning "Project directory already exists"
    read -p "Do you want to backup and recreate it? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        mv "$PROJECT_DIR" "${PROJECT_DIR}_backup_$(date +%Y%m%d_%H%M%S)"
        print_status "Created backup of existing directory"
        mkdir -p "$PROJECT_DIR"
    fi
else
    mkdir -p "$PROJECT_DIR"
fi

cd "$PROJECT_DIR"

# Создание файла конфигурации
print_status "Creating configuration file..."
cat > config_template.env << 'EOF'
# Telegram Bot Configuration
# Copy this file to .env and fill in your values

# Your Telegram Bot Token (get from @BotFather)
BOT_TOKEN=your_bot_token_here

# Your Telegram username (without @)
ALLOWED_USER=mgmwm

# Optional: Custom database path
# DB_PATH=servers.db

# Optional: Log level (DEBUG, INFO, WARNING, ERROR)
# LOG_LEVEL=INFO
EOF

# Создание файла .env если его нет
if [[ ! -f ".env" ]]; then
    cp config_template.env .env
    print_status "Created .env configuration file"
else
    print_warning ".env file already exists - not overwriting"
fi

# Создание директорий
mkdir -p logs
mkdir -p backups

# Создание скрипта запуска
print_status "Creating startup script..."
cat > start_bot.sh << 'EOF'
#!/data/data/com.termux/files/usr/bin/bash

# Server Management Bot Startup Script
cd "$(dirname "$0")"

# Load environment variables
if [[ -f ".env" ]]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

# Check if bot token is set
if [[ -z "$BOT_TOKEN" ]]; then
    echo "❌ BOT_TOKEN not set in .env file!"
    echo "Please edit .env file and set your bot token"
    exit 1
fi

echo "🤖 Starting Server Management Bot..."
echo "👤 Authorized user: @${ALLOWED_USER:-mgmwm}"
echo "📅 Started at: $(date)"

# Start the bot with logging
python server_bot.py 2>&1 | tee -a logs/bot_$(date +%Y%m%d).log
EOF

chmod +x start_bot.sh

# Создание скрипта остановки
cat > stop_bot.sh << 'EOF'
#!/data/data/com.termux/files/usr/bin/bash

echo "🛑 Stopping Server Management Bot..."

# Find and kill bot processes
pgrep -f "python.*server_bot.py" | while read pid; do
    echo "Killing process $pid"
    kill "$pid"
done

echo "✅ Bot stopped"
EOF

chmod +x stop_bot.sh

# Создание скрипта статуса
cat > status_bot.sh << 'EOF'
#!/data/data/com.termux/files/usr/bin/bash

echo "📊 Server Management Bot Status"
echo "==============================="

if pgrep -f "python.*server_bot.py" > /dev/null; then
    echo "✅ Bot is running"
    echo "🔍 Process ID(s): $(pgrep -f "python.*server_bot.py" | tr '\n' ' ')"
else
    echo "❌ Bot is not running"
fi

echo ""
echo "📂 Project directory: $(pwd)"
echo "📋 Configuration file: $([[ -f .env ]] && echo "✅ Found" || echo "❌ Missing")"
echo "🗄️  Database file: $([[ -f servers.db ]] && echo "✅ Found" || echo "❌ Not created yet")"

# Show recent log
if [[ -f "logs/bot_$(date +%Y%m%d).log" ]]; then
    echo ""
    echo "📝 Recent log entries:"
    tail -5 "logs/bot_$(date +%Y%m%d).log"
fi
EOF

chmod +x status_bot.sh

# Создание скрипта автозапуска
cat > install_autostart.sh << 'EOF'
#!/data/data/com.termux/files/usr/bin/bash

# Install autostart for Server Management Bot
echo "🔧 Installing autostart configuration..."

# Create .termux directory if it doesn't exist
mkdir -p ~/.termux

# Create boot script
cat > ~/.termux/boot/start_server_bot << 'BOOT_EOF'
#!/data/data/com.termux/files/usr/bin/bash
cd ~/server_bot
./start_bot.sh &
BOOT_EOF

chmod +x ~/.termux/boot/start_server_bot

echo "✅ Autostart installed"
echo "📱 The bot will start automatically when Termux starts"
echo "⚠️  Make sure to allow autostart for Termux in Android settings"
EOF

chmod +x install_autostart.sh

# Создание README
print_status "Creating documentation..."
cat > README.md << 'EOF'
# Server Management Bot

Telegram-бот для управления серверами с мониторингом питания, разработанный для работы в Termux на Android.

## Возможности

- 🔍 Мониторинг состояния питания устройства
- 🖥️ Управление серверами через SSH
- 🚨 Автоматическое отключение серверов при потере питания  
- 📱 Уведомления в Telegram
- 🔐 Шифрование паролей и ключей
- 📋 Журналирование всех событий

## Быстрый старт

1. **Настройка бота:**
   ```bash
   # Отредактируйте файл .env
   nano .env
   
   # Установите ваш BOT_TOKEN и имя пользователя
   BOT_TOKEN=your_bot_token_from_botfather
   ALLOWED_USER=your_username
   ```

2. **Запуск:**
   ```bash
   ./start_bot.sh
   ```

3. **Отправьте `/start` боту в Telegram**

## Скрипты управления

- `./start_bot.sh` - Запуск бота
- `./stop_bot.sh` - Остановка бота  
- `./status_bot.sh` - Статус бота
- `./install_autostart.sh` - Установка автозапуска

## Команды бота

- `/start` - Начало работы
- `📊 Status` - Статус системы
- `🖥️ Servers` - Управление серверами
- `📋 Logs` - Просмотр логов
- `🧪 Test Shutdown` - Тестовое отключение
- `⚙️ Settings` - Настройки

## Требования

- Android с установленным Termux
- Termux:API из Google Play
- Telegram Bot Token (от @BotFather)

## Безопасность

- Бот отвечает только авторизованному пользователю
- Пароли шифруются с помощью Fernet
- Логирование всех действий
- Резервное копирование настроек

## Устранение неполадок

### Ошибка "termux-battery-status not found"
```bash
pkg install termux-api
# Также установите Termux:API из Google Play Store
```

### Бот не отвечает
1. Проверьте BOT_TOKEN в .env
2. Убедитесь что бот запущен: `./status_bot.sh`
3. Проверьте логи: `tail -f logs/bot_$(date +%Y%m%d).log`

### Проблемы с SSH
- Проверьте доступность сервера в локальной сети
- Убедитесь в правильности учетных данных
- Проверьте права SSH-ключа: `chmod 600 ~/.ssh/id_rsa`

## Файловая структура

```
server_bot/
├── server_bot.py          # Основной файл бота
├── .env                   # Конфигурация
├── start_bot.sh          # Скрипт запуска
├── stop_bot.sh           # Скрипт остановки
├── status_bot.sh         # Статус бота
├── servers.db            # База данных серверов
├── encryption.key        # Ключ шифрования
├── logs/                 # Логи
└── backups/              # Резервные копии
```

## Поддержка

Для вопросов и проблем создавайте issues в репозитории проекта.
EOF

print_success "Installation completed!"
print_status "Next steps:"
echo ""
echo "1. 📝 Edit configuration file:"
echo "   nano .env"
echo ""
echo "2. 🔧 Set your bot token and username in .env file"
echo ""
echo "3. 🚀 Start the bot:"
echo "   ./start_bot.sh"
echo ""
echo "4. 📱 Send /start to your bot in Telegram"
echo ""
echo "5. 🔄 (Optional) Install autostart:"
echo "   ./install_autostart.sh"
echo ""

print_warning "Important notes:"
echo "- Install Termux:API from Google Play Store"
echo "- Allow autostart for Termux in Android settings"  
echo "- Keep your device plugged in for power monitoring"
echo "- Make sure your bot token is correct"
echo ""

print_success "Installation directory: $PROJECT_DIR"
print_status "Read README.md for detailed instructions"

# Проверка Termux API
if command -v termux-battery-status &> /dev/null; then
    print_success "Termux:API is available"
    
    # Тест команды
    if termux-battery-status &> /dev/null; then
        print_success "Battery monitoring is working"
    else
        print_warning "Battery monitoring requires Termux:API app from Google Play"
    fi
else
    print_warning "termux-battery-status not found"
    print_status "Install it with: pkg install termux-api"
fi

echo ""
print_status "Installation completed successfully! 🎉"