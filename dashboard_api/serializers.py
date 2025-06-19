# dashboard_api/serializers.py

from datetime import timezone

from rest_framework import serializers

from SmartCCTV.settings import base as settings
from analytics.models import CongestionEvents, Snapshots # models.py 파일에서 CongestionEvents 모델 가져오기
from cameras.models import Cameras # cameras 앱의 Cameras 모델 임포트

class LatestCongestionSerializer(serializers.ModelSerializer):
    # CongestionEvents.camera (ForeignKey to Cameras) 필드에서 관련 정보 가져오기
    camera_id = serializers.IntegerField(source='camera.camera_id', read_only=True)
    name = serializers.CharField(source='camera.name', read_only=True) # 카메라 이름

    # CongestionEvents.snapshot (ForeignKey to Snapshots) 필드에서 스냅샷 ID 가져오기
    # API 명세에 snapshot_id_for_event 로 명시됨
    snapshot_id_for_event = serializers.PrimaryKeyRelatedField(
        source='snapshot',
        read_only=True,
        allow_null=True # snapshot 필드가 null=True, blank=True 이므로 허용
    )

    # ROI 추정 결과인 estimated_roi_pixel_area 를 명시적으로 포함 (API 명세에 따라 선택 가능)
    # 이 필드는 CongestionEvents 모델에 이미 있으므로, 직렬화 대상에 포함시키면 됩니다.
    # estimated_roi_pixel_area = serializers.IntegerField(read_only=True) # 이미 모델 필드라 자동 포함 가능

    class Meta:
        model = CongestionEvents
        fields = [
            'camera_id',                 # 카메라 ID (Cameras 모델 참조)
            'name',                      # 카메라 이름 (Cameras 모델 참조)
            'event_timestamp',           # 혼잡도 측정 시각
            'person_count',              # 탐지된 총 사람 수
            'congestion_level',          # 최종 판정된 혼잡도 수준
            'congestion_value_raw',      # 계산된 원시 밀집도 값
            'snapshot_id_for_event',     # 이 혼잡도 계산에 사용된 대표 스냅샷 ID
            'estimated_roi_pixel_area',  # 추정된 ROI 픽셀 면적 (ROI 추정 결과)
        ]
        read_only_fields = fields # 모든 필드를 읽기 전용으로 설정 (GET 요청이므로)

class CongestionHistoryDataSerializer(serializers.ModelSerializer):
    """
    GET /congestion/history/ API의 data 배열 내 각 항목을 위한 Serializer.
    API 명세 응답 예시에 맞춰 필드 선정.
    """
    class Meta:
        model = CongestionEvents
        fields = [
            'event_timestamp',
            'person_count',
            'congestion_level',
            'congestion_value_raw',
            # 'estimated_roi_pixel_area' # 명세 예시에는 없지만 필요시 추가 가능
        ]

# GET /snapshots/{snapshot_id}/processed_image/ API 응답용 Serializer (옵션 2: JSON URL 반환 시)
class ProcessedSnapshotImageSerializer(serializers.ModelSerializer):
    original_image_url = serializers.SerializerMethodField()
    processed_image_url = serializers.SerializerMethodField()

    class Meta:
        model = Snapshots
        fields = [
            'snapshot_id',
            'original_image_url',
            'processed_image_url',
        ]

    def get_processed_image_url(self, obj):
        """
        처리된 이미지(processed_image_path)의 완전한 URL을 생성합니다.
        URL 경로의 시작을 '/analytics/'로 고정합니다.
        """
        if not obj.processed_image_path:
            return None

        # 윈도우 경로 구분자(\)를 웹 표준(/)으로 변경
        relative_path = obj.processed_image_path.replace('\\', '/')

        # URL 경로를 '/analytics/'로 시작하도록 직접 구성
        url_path = f"/analytics/{relative_path}"

        request = self.context.get('request')
        if request:
            return request.build_absolute_uri(url_path)

        # request 객체가 없을 경우 (테스트 환경 등)
        return url_path

    def get_original_image_url(self, obj):
        """
        원본 이미지(image_path)의 완전한 URL을 생성합니다.
        DB에 'C:\\Users\\...\\SmartCCTV\\analytics\\...' 와 같은 절대 경로가 저장된 문제를 해결합니다.
        """
        if not obj.image_path:
            return None

        absolute_path = obj.image_path
        project_root_name = 'SmartCCTV'

        try:
            path_parts = absolute_path.split(project_root_name)
            if len(path_parts) > 1:
                relative_path = path_parts[1]
            else:
                relative_path = absolute_path

            relative_path = relative_path.replace('\\', '/').lstrip('/')

            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(f'/{relative_path}')

            return f'/{relative_path}'

        except Exception:
            return None

# GET /alerts/ API 응답용 Serializer
class AlertSerializer(serializers.ModelSerializer):
    # CongestionEvents 모델을 기반으로 알림 정보를 구성 (API 명세 참조)
    # API 명세의 alert_id는 CongestionEvents.event_id와 연관될 수 있다고 되어 있음
    alert_id = serializers.IntegerField(source='event_id', read_only=True)
    camera_id = serializers.IntegerField(source='camera.camera_id', read_only=True)
    camera_name = serializers.CharField(source='camera.name', read_only=True)
    # alert_type은 CongestionEvents에 직접적 필드가 없으므로, 필요시 로직으로 생성하거나 모델 확장 필요
    # 여기서는 임시로 congestion_level을 기반으로 단순화하거나, 고정값을 사용할 수 있음.
    # 또는, 별도의 Alert 모델이 있다면 해당 모델을 사용.
    # 현재는 CongestionEvents를 기반으로 하므로, alert_type은 직접 매핑이 어려움.
    # message 또한 동적으로 생성 필요.
    # 우선 명세에 있는 필드들을 최대한 CongestionEvents에서 가져오도록 구성.
    message = serializers.SerializerMethodField() # 동적으로 메시지 생성

    class Meta:
        model = CongestionEvents # CongestionEvents를 알림의 기반으로 사용
        fields = [
            'alert_id',             # CongestionEvents.event_id
            'camera_id',
            'camera_name',
            'event_timestamp',      # 알림 발생 시각 (혼잡 이벤트 발생 시각)
            # 'alert_type',         # 현재 모델로는 직접 매핑 불가, get_alert_type 등으로 구현 필요
            'message',              # 동적 생성
            'congestion_level',     # 혼잡도 수준 (알림의 근거)
            'person_count',         # 당시 인원 수
            'is_acknowledged',      # 관리자 확인 여부 (CongestionEvents 필드)
            'created_at',           # 알림 생성 시각 (혼잡 이벤트 레코드 생성 시각)
        ]
        read_only_fields = fields

    def get_message(self, obj):
        # API 명세 예시: "높은 혼잡도(25명) 감지: 신공학관 9층 엘리베이터 앞"
        return f"{obj.get_congestion_level_display()} ({obj.person_count}명) 감지: {obj.camera.name}"

    # def get_alert_type(self, obj):
    #     # 예시: 혼잡도 수준에 따라 alert_type 결정
    #     if obj.congestion_level in [CongestionLevelLabel.HIGH, CongestionLevelLabel.VERY_HIGH]:
    #         return "HIGH_CONGESTION"
    #     # 다른 알림 유형 로직 추가 가능
    #     return "GENERAL_INFO" # 기본값

# POST /alerts/{alert_id}/acknowledge/ API 응답용 Serializer
class AlertAcknowledgeSerializer(serializers.ModelSerializer):
    alert_id = serializers.IntegerField(source='event_id', read_only=True)

    class Meta:
        model = CongestionEvents
        fields = [
            'alert_id',
            'is_acknowledged',
            'acknowledged_at',
        ]
        read_only_fields = ['alert_id', 'acknowledged_at'] # is_acknowledged는 요청으로 받을 수 있음

    def update(self, instance, validated_data):
        instance.is_acknowledged = validated_data.get('is_acknowledged', instance.is_acknowledged)
        if instance.is_acknowledged and not instance.acknowledged_at: # 확인 처리 시 시간 기록
            instance.acknowledged_at = timezone.now()
        elif not instance.is_acknowledged: # 확인 취소 시 시간도 초기화 (정책에 따라 다름)
            instance.acknowledged_at = None
        instance.save()
        return instance

class CameraSerializer(serializers.ModelSerializer):
    class Meta:
        model = Cameras
        fields = [
            'camera_id',
            'name',
            'location_description',
            'status',
            'is_active_monitoring',
            'resolution_width',
            'resolution_height',
            'created_at',
            'updated_at',
            # 'rtsp_url', # API 명세의 응답에는 없으므로 필요시 추가
            # 'source_type', # API 명세의 응답에는 없으므로 필요시 추가
        ]
        read_only_fields = fields # 모든 필드를 읽기 전용으로

class CameraStreamURLSerializer(serializers.Serializer):
    # 이 Serializer는 특정 카메라 스트리밍 URL 조회 API의 응답 형식을 정의합니다.
    camera_id = serializers.IntegerField()
    name = serializers.CharField()
    stream_url = serializers.URLField()
    stream_type = serializers.CharField()