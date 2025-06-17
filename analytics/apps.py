# analytics/apps.py

from django.apps import AppConfig


class AnalyticsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'analytics'

    def ready(self):
        # Django 앱 로딩이 완료된 후 스케줄러 설정을 진행합니다.
        # 이 import는 ready() 메소드 내에서 하여 순환 참조 및 앱 로딩 문제를 방지합니다.
        from django_q.tasks import schedule
        from django_q.models import Schedule

        # 기존 ROI 업데이트 스케줄링
        func_path = 'analytics.congestion_analysis_tasks.update_all_camera_rois_periodic_task'
        schedule_name = 'Hourly ROI Update via Django-Q'
        cron_schedule = '0 */1 * * *'

        if not Schedule.objects.filter(name=schedule_name).exists():
            schedule(
                func_path,
                name=schedule_name,
                schedule_type=Schedule.CRON,
                cron=cron_schedule,
                repeats=-1, # 무한 반복
            )
            print(f"'{schedule_name}' 작업이 django-q 스케줄러에 등록되었습니다.")

        # 새로운 카메라 캡처 스케줄링 (30초마다 모든 활성 카메라 캡처)
        capture_func_path = 'analytics.capture.capture_all_active_cameras_task'
        capture_schedule_name = 'Camera Capture Every 30 Seconds'
        capture_cron_schedule = '*/1 * * * *'  # 매 분마다 실행 (30초 간격을 위해 함수 내에서 처리)

        if not Schedule.objects.filter(name=capture_schedule_name).exists():
            schedule(
                capture_func_path,
                name=capture_schedule_name,
                schedule_type=Schedule.CRON,
                cron=capture_cron_schedule,
                repeats=-1, # 무한 반복
            )
            print(f"'{capture_schedule_name}' 작업이 django-q 스케줄러에 등록되었습니다.")