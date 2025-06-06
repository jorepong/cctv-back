from django.apps import AppConfig


class AnalyticsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'analytics'

    def ready(self):
        # Django 앱 로딩이 완료된 후 스케줄러 설정을 진행합니다.
        # 이 import는 ready() 메소드 내에서 하여 순환 참조 및 앱 로딩 문제를 방지합니다.
        from django_q.tasks import schedule
        from django_q.models import Schedule

        # 스케줄링할 함수의 전체 Python 경로
        func_path = 'analytics.congestion_analysis_tasks.update_all_camera_rois_periodic_task'

        # 스케줄 이름 (중복 등록 방지를 위해 사용)
        schedule_name = 'Hourly ROI Update via Django-Q'

        # 매 시간 정각에 실행하는 CRON 스케줄
        # 테스트를 위해 매 분 실행하려면 '*/1 * * * *' 로 변경
        cron_schedule = '0 */1 * * *'

        # 이미 같은 이름의 스케줄이 등록되어 있는지 확인하여 중복 등록을 방지합니다.
        if not Schedule.objects.filter(name=schedule_name).exists():
            schedule(
                func_path,
                name=schedule_name,
                schedule_type=Schedule.CRON,
                cron=cron_schedule,
                repeats=-1,  # 무한 반복
            )
            print(f"'{schedule_name}' 작업이 django-q 스케줄러에 등록되었습니다.")