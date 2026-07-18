import os
import sys
import tempfile

# до импорта bot.config: тестовое окружение
os.environ.setdefault('BOT_TOKEN', 'test-token')
os.environ['DATA_DIR'] = tempfile.mkdtemp(prefix='bottest_')

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
