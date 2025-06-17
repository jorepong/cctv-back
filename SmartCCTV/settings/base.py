# SmartCCTV/settings.py

from pathlib import Path
import environ  # django-environ 임포트

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent.parent
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media' # 또는 os.path.join(BASE_DIR, 'media')

# django-environ 초기화
env = environ.Env(
    DEBUG=(bool, False),
    SSH_PORT=(int, 22),
    MYSQL_PORT_ON_DEBIAN=(int, 3306),
    LOCAL_BIND_PORT=(int, 3307),
)

env = environ.Env()

CCTV_STREAMS_CONFIG_PATH = BASE_DIR / 'config' / 'cctv_streams.yaml'

# SECURITY WARNING: keep the secret key used in production secret!
# SECRET_KEY = env('SECRET_KEY')  # .env 또는 환경변수에서 로드 (필수)

# SECURITY WARNING: don't run with debug turned on in production!
# DEBUG = env('DEBUG')

# ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=['127.0.0.1', 'localhost'])

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'django_q',
    'cameras.apps.CamerasConfig',
    'analytics.apps.AnalyticsConfig',
    'dashboard_api.apps.DashboardApiConfig',
    'core.apps.CoreConfig',
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

# 데이터베이스 설정
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
    }
}

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

# settings.py
TIME_ZONE = 'Asia/Seoul'
USE_TZ = True

Q_CLUSTER = {
    'name': 'SmartCCTV_Scheduler',
    'workers': 1,  # 주기적인 ROI 업데이트 작업 하나만이라면 1개로도 충분할 수 있습니다. 필요시 조정.
    'timeout': 90,  # 작업 타임아웃 (초). ROI 작업이 오래 걸린다면 늘려주세요.
    'retry': 120,   # 실패한 작업 재시도 대기 시간 (초)
    'queue_limit': 50, # 큐에 쌓일 수 있는 최대 작업 수
    'bulk': 10,
    'orm': 'default',  # Django의 'default' 데이터베이스를 브로커로 사용
    'scheduler': True  # 내장 스케줄러 사용 설정 (주기적 작업에 필수)
}