# cameras/models.py
from django.db import models
from django.utils import timezone # now() 대신 Django의 timezone.now 또는 auto_now/auto_now_add 사용

# Enum-like choices for Cameras model
class CameraStatus(models.TextChoices):
    ACTIVE = 'ACTIVE', '활성 (ACTIVE)'
    INACTIVE = 'INACTIVE', '비활성 (INACTIVE)'
    ERROR = 'ERROR', '오류 (ERROR)'

class CameraSourceType(models.TextChoices):
    TESTBED = 'TESTBED', '테스트베드 (TESTBED)'
    WONWOO_REMOTE = 'WONWOO_REMOTE', '원우 리모트 (WONWOO_REMOTE)'
    YOUTUBE_LIVE = 'YOUTUBE_LIVE', '유튜브 라이브 (YOUTUBE_LIVE)'

class Cameras(models.Model):
    camera_id = models.AutoField(primary_key=True, help_text='카메라 고유 ID')
    name = models.CharField(max_length=255, help_text='카메라 이름 (예: 신공학관 9층 엘리베이터 앞)')
    rtsp_url = models.CharField(max_length=512, null=True, blank=True, help_text='RTSP 스트리밍 URL (외부 CCTV용)')
    source_type = models.CharField(
        max_length=50,
        choices=CameraSourceType.choices,
        default=CameraSourceType.TESTBED,
        help_text='카메라 소스 타입 (TESTBED, WONWOO_REMOTE, YOUTUBE_LIVE)'
    )
    location_description = models.TextField(null=True, blank=True, help_text='설치 위치 상세 설명')
    resolution_width = models.IntegerField(null=True, blank=True, help_text='해상도 너비')
    resolution_height = models.IntegerField(null=True, blank=True, help_text='해상도 높이')
    status = models.CharField(
        max_length=20,
        choices=CameraStatus.choices,
        default=CameraStatus.ACTIVE,
        help_text='카메라 상태 (ACTIVE, INACTIVE, ERROR)'
    )
    is_active_monitoring = models.BooleanField(default=True, help_text='현재 모니터링(분석) 대상 여부')
    created_at = models.DateTimeField(auto_now_add=True, help_text='레코드 생성 시각')
    updated_at = models.DateTimeField(auto_now=True, help_text='레코드 수정 시각')

    class Meta:
        db_table = 'Cameras'
        verbose_name = '카메라 (Camera)'
        verbose_name_plural = '카메라 목록 (Cameras)'

    def __str__(self):
        return f"{self.name} (ID: {self.camera_id})"