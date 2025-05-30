# SmartCCTV/settings.py

import os
import traceback
from pathlib import Path
import environ  # django-environ 임포트
from sshtunnel import SSHTunnelForwarder
import sys
import atexit

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# django-environ 초기화
env = environ.Env(
    # (타입, 기본값)
    DEBUG=(bool, False),  # DEBUG 기본값은 False (프로덕션 환경 고려)
    SSH_PORT=(int, 22),
    MYSQL_PORT_ON_DEBIAN=(int, 3306),
    LOCAL_BIND_PORT=(int, 3309),
    # DATABASE_URL=(str, None) # DATABASE_URL을 사용할 경우
)

# .env 파일 읽기 (BASE_DIR에 .env 파일이 있다고 가정)
# 파일이 존재하지 않아도 오류를 발생시키지 않음
ENV_FILE_PATH = BASE_DIR / '.env'
if ENV_FILE_PATH.exists():
    environ.Env.read_env(str(ENV_FILE_PATH))
else:
    print(f"Warning: .env file not found at {ENV_FILE_PATH}. Using environment variables or defaults.")
print("✅ ENV loaded:", ENV_FILE_PATH.exists())
print("✅ SECRET_KEY:", env('SECRET_KEY', default='❌ Not Found'))

CCTV_STREAMS_CONFIG_PATH = BASE_DIR / 'config' / 'cctv_streams.yaml'

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = env('SECRET_KEY')# .env 또는 환경변수에서 로드 (필수)

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = env('DEBUG')

ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=['127.0.0.1', 'localhost'])

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'cameras.apps.CamerasConfig',
    'analytics.apps.AnalyticsConfig',
    'dashboard_api.apps.DashboardApiConfig',
    'core.apps.CoreConfig',
    'django_celery_beat',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'SmartCCTV.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug', # DEBUG True일 때 유용
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'SmartCCTV.wsgi.application'

# --- SSH 터널 및 데이터베이스 설정 시작 ---

# SSH 터널 정보
SSH_HOST = env('SSH_HOST', default=None)
SSH_PORT = env.int('SSH_PORT')
SSH_USERNAME = env('SSH_USERNAME', default=None)
SSH_PRIVATE_KEY_PATH = env('SSH_PRIVATE_KEY_PATH', default=None)

# MySQL 정보 (Debian 서버 내부 기준)
MYSQL_HOST_ON_DEBIAN = env('MYSQL_HOST_ON_DEBIAN', default='127.0.0.1')
MYSQL_PORT_ON_DEBIAN = env.int('MYSQL_PORT_ON_DEBIAN')
MYSQL_USERNAME_DB = env('MYSQL_USERNAME_DB', default=None) # .env 또는 환경변수 (필수)
MYSQL_PASSWORD_DB = env('MYSQL_PASSWORD_DB', default=None) # .env 또는 환경변수 (필수)
MYSQL_DATABASE_NAME = env('MYSQL_DATABASE_NAME', default=None) # .env 또는 환경변수 (필수)

# 로컬에서 사용할 포트 (터널의 로컬 끝점)
LOCAL_BIND_PORT = env.int('LOCAL_BIND_PORT')

ssh_tunnel_server = None
tunnel_active_and_configured = False # 터널 활성 및 DB 설정 완료 여부

def start_ssh_tunnel():
    global ssh_tunnel_server, tunnel_active_and_configured

    # 필수 환경 변수 확인
    required_ssh_vars = [SSH_HOST, SSH_USERNAME, SSH_PRIVATE_KEY_PATH]
    required_db_vars = [MYSQL_USERNAME_DB, MYSQL_PASSWORD_DB, MYSQL_DATABASE_NAME]

    if not all(required_ssh_vars):
        print("SSH 터널에 필요한 환경 변수(SSH_HOST, SSH_USERNAME, SSH_PRIVATE_KEY_PATH)가 .env 파일 또는 환경변수에 충분히 설정되지 않았습니다.")
        tunnel_active_and_configured = False
        return False

    if not all(required_db_vars):
        print("데이터베이스 접속에 필요한 환경 변수(MYSQL_USERNAME_DB, MYSQL_PASSWORD_DB, MYSQL_DATABASE_NAME)가 .env 파일 또는 환경변수에 충분히 설정되지 않았습니다.")
        tunnel_active_and_configured = False
        return False

    if ssh_tunnel_server and ssh_tunnel_server.is_active:
        print("SSH 터널이 이미 활성 상태입니다. 새로운 연결을 시도하지 않습니다.")
        tunnel_active_and_configured = True # 이미 활성 상태면 설정도 완료된 것으로 간주
        return True

    try:
        if not Path(SSH_PRIVATE_KEY_PATH).exists(): # type: ignore
            raise FileNotFoundError(f"SSH 개인 키 파일을 찾을 수 없습니다: {SSH_PRIVATE_KEY_PATH}")

        ssh_tunnel_server = SSHTunnelForwarder(
            (SSH_HOST, SSH_PORT), # type: ignore
            ssh_username=SSH_USERNAME,
            ssh_pkey=SSH_PRIVATE_KEY_PATH,
            remote_bind_address=(MYSQL_HOST_ON_DEBIAN, MYSQL_PORT_ON_DEBIAN),
            local_bind_address=('127.0.0.1', LOCAL_BIND_PORT)
        )
        ssh_tunnel_server.start()
        print(f"SSH 터널 (키 사용)이 127.0.0.1:{LOCAL_BIND_PORT}에서 {MYSQL_HOST_ON_DEBIAN}:{MYSQL_PORT_ON_DEBIAN} (원격)으로 연결되었습니다.")
        tunnel_active_and_configured = True
        return True
    except Exception as e:
        print(f"SSH 터널 시작 실패: {e}")
        traceback.print_exc()
        ssh_tunnel_server = None
        tunnel_active_and_configured = False
        return False

# start_ssh_tunnel() # 터널 시작 시도

# 데이터베이스 설정
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': MYSQL_DATABASE_NAME,
        'USER': MYSQL_USERNAME_DB,
        'PASSWORD': MYSQL_PASSWORD_DB,
        'HOST': '127.0.0.1',  # SSH 터널의 로컬 바인딩 주소
        'PORT': str(LOCAL_BIND_PORT),  # SSH 터널의 로컬 바인딩 포트
        'OPTIONS': {
            'charset': 'utf8mb4',
            # 'init_command': "SET sql_mode='STRICT_TRANS_TABLES'", # 필요시 MySQL 모드 설정
        },
    }
}


def stop_ssh_tunnel():
    global ssh_tunnel_server
    if ssh_tunnel_server and ssh_tunnel_server.is_active:
        print("애플리케이션 종료 시 SSH 터널을 닫습니다...")
        ssh_tunnel_server.stop()
        print("SSH 터널이 닫혔습니다.")
    else:
        print("애플리케이션 종료: 활성 SSH 터널 없음.")


# ssh_tunnel_server 객체가 존재하고 활성화된 경우에만 atexit 등록
if ssh_tunnel_server and ssh_tunnel_server.is_active:
    atexit.register(stop_ssh_tunnel)

start_ssh_tunnel()

# --- SSH 터널 및 데이터베이스 설정 끝 ---

# Password validation
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization
# https://docs.djangoproject.com/en/5.2/topics/i18n/

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.2/howto/static-files/

STATIC_URL = 'static/'

# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


CAPTURE_ROOT = BASE_DIR / "captured"

# settings.py
TIME_ZONE = 'Asia/Seoul'
USE_TZ = True

