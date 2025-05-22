
from .base import *

from pathlib import Path
import environ

environ.Env.read_env(str(BASE_DIR / '.env'))

DEBUG = True
ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=['127.0.0.1', 'localhost'])

# --- SSH 터널 및 데이터베이스 설정 시작 ---

# MySQL 정보 (Debian 서버 내부 기준)
MYSQL_HOST_ON_DEBIAN = env('MYSQL_HOST_ON_DEBIAN', default='127.0.0.1')
MYSQL_PORT_ON_DEBIAN = env.int('MYSQL_PORT_ON_DEBIAN')
MYSQL_USERNAME_DB = env('MYSQL_USERNAME_DB', default=None) # .env 또는 환경변수 (필수)
MYSQL_PASSWORD_DB = env('MYSQL_PASSWORD_DB', default=None) # .env 또는 환경변수 (필수)
MYSQL_DATABASE_NAME = env('MYSQL_DATABASE_NAME', default=None) # .env 또는 환경변수 (필수)

# 데이터베이스 설정
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': MYSQL_DATABASE_NAME,
        'USER': MYSQL_USERNAME_DB,
        'PASSWORD': MYSQL_PASSWORD_DB,
        'HOST': MYSQL_HOST_ON_DEBIAN,
        'PORT': str(MYSQL_PORT_ON_DEBIAN),
        'OPTIONS': {
            'charset': 'utf8mb4',
            # 'init_command': "SET sql_mode='STRICT_TRANS_TABLES'", # 필요시 MySQL 모드 설정
        },
    }
}

# --- SSH 터널 및 데이터베이스 설정 끝 ---