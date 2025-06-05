# analytics/tests/test_services.py
from django.test import TestCase
from django.utils import timezone
from analytics.models import (
    Cameras, Snapshots, DetectedObjects, ROIDefinitions, CongestionEvents,
    CongestionLevelLabel, ProcessingStatus, ROIDefinitionType
)
from analytics.services import (  # 테스트할 서비스 함수들을 임포트
    calculate_and_save_congestion_event,
    get_active_roi_for_camera,
    calculate_total_footprint_area,
    determine_congestion_level,
    CONGESTION_CALCULATION_R_RATIO  # 필요하다면 상수도 임포트
)


class CongestionServiceTests(TestCase):

    def setUp(self):
        """
        각 테스트 메소드 실행 전에 공통적으로 필요한 객체들을 생성합니다.
        테스트용 DB에 임시 데이터를 만듭니다.
        """
        self.camera1 = Cameras.objects.create(name="Test Camera 1", is_active_monitoring=True)
        self.camera2 = Cameras.objects.create(name="Test Camera 2", is_active_monitoring=True)

        # Test Camera 1에 대한 활성 ROI 정의
        self.roi_def_cam1 = ROIDefinitions.objects.create(
            camera=self.camera1,
            definition_type=ROIDefinitionType.DYNAMIC_CONVEX_HULL,
            definition_data={
                "coordinates": [{"x": 0, "y": 0}, {"x": 100, "y": 0}, {"x": 100, "y": 100}, {"x": 0, "y": 100}],
                "area": 10000.0},  # 예시 면적
            is_active=True
        )
        # Test Camera 2에는 활성 ROI 없음

        # 테스트용 스냅샷 생성
        self.snapshot_cam1_pending_ai = Snapshots.objects.create(
            camera=self.camera1,
            captured_at=timezone.now(),
            image_path="/fake/path1.jpg",
            processing_status_ai=ProcessingStatus.PENDING,
            processing_status_congestion=ProcessingStatus.PENDING
        )
        self.snapshot_cam1_ai_completed = Snapshots.objects.create(
            camera=self.camera1,
            captured_at=timezone.now() - timezone.timedelta(minutes=1),
            image_path="/fake/path2.jpg",
            processing_status_ai=ProcessingStatus.COMPLETED,
            processing_status_congestion=ProcessingStatus.PENDING
        )
        self.snapshot_cam2_ai_completed_no_roi = Snapshots.objects.create(
            camera=self.camera2,  # 이 카메라는 활성 ROI가 없음
            captured_at=timezone.now() - timezone.timedelta(minutes=2),
            image_path="/fake/path3.jpg",
            processing_status_ai=ProcessingStatus.COMPLETED,
            processing_status_congestion=ProcessingStatus.PENDING
        )

    # --- 헬퍼 함수 테스트 ---
    def test_get_active_roi_for_camera(self):
        # 카메라1은 활성 ROI가 있음
        roi_data_cam1 = get_active_roi_for_camera(self.camera1)
        self.assertIsNotNone(roi_data_cam1)
        self.assertEqual(roi_data_cam1['area'], 10000.0)

        # 카메라2는 활성 ROI가 없음
        roi_data_cam2 = get_active_roi_for_camera(self.camera2)
        self.assertIsNone(roi_data_cam2)

    def test_calculate_total_footprint_area(self):
        # 탐지된 객체가 없는 경우
        self.assertEqual(calculate_total_footprint_area([], CONGESTION_CALCULATION_R_RATIO), 0.0)

        # 탐지된 객체가 있는 경우
        detected_objects = [
            DetectedObjects(class_label='person', bbox_x=10, bbox_y=10, bbox_width=20, bbox_height=50),
            # area_foot = 20 * (50*0.05) = 20 * 2.5 = 50
            DetectedObjects(class_label='person', bbox_x=30, bbox_y=30, bbox_width=30, bbox_height=60),
            # area_foot = 30 * (60*0.05) = 30 * 3.0 = 90
            DetectedObjects(class_label='other', bbox_x=0, bbox_y=0, bbox_width=10, bbox_height=10),  # 사람은 아니므로 계산 제외
        ]
        # 예상값: (20 * max(1, 50*0.05)) + (30 * max(1, 60*0.05))
        #        = (20 * 2.5) + (30 * 3.0) = 50 + 90 = 140
        expected_area = (20 * max(1.0, 50 * CONGESTION_CALCULATION_R_RATIO)) + \
                        (30 * max(1.0, 60 * CONGESTION_CALCULATION_R_RATIO))
        self.assertAlmostEqual(calculate_total_footprint_area(detected_objects, CONGESTION_CALCULATION_R_RATIO),
                               expected_area, places=5)

    def test_determine_congestion_level(self):
        self.assertEqual(determine_congestion_level(0.05), CongestionLevelLabel.LOW)
        self.assertEqual(determine_congestion_level(0.15), CongestionLevelLabel.MEDIUM)  # 0.1 <= x < 0.3
        self.assertEqual(determine_congestion_level(0.35), CongestionLevelLabel.HIGH)  # 0.3 <= x < 0.6
        self.assertEqual(determine_congestion_level(0.65), CongestionLevelLabel.VERY_HIGH)  # x >= 0.6

    # --- calculate_and_save_congestion_event 함수 전체 테스트 ---
    def test_calculate_and_save_congestion_event_success_low_congestion(self):
        # 시나리오: AI 분석 완료, 활성 ROI 존재, 낮은 밀집도
        # 이 스냅샷에 대해 탐지된 객체 1명 생성
        DetectedObjects.objects.create(
            snapshot=self.snapshot_cam1_ai_completed, class_label='person',
            bbox_x=10, bbox_y=10, bbox_width=10, bbox_height=20  # area_foot = 10 * (20*0.05) = 10 * 1 = 10
        )

        result_event = calculate_and_save_congestion_event(self.snapshot_cam1_ai_completed.snapshot_id)
        self.assertIsNotNone(result_event)
        self.assertEqual(result_event.person_count, 1)
        self.assertEqual(result_event.estimated_roi_pixel_area, 10000.0)
        # congestion_value_raw = (10 * max(1, 20*0.05)) / 10000 = 10 / 10000 = 0.001
        expected_raw_value = (10 * max(1.0, 20 * CONGESTION_CALCULATION_R_RATIO)) / 10000.0
        self.assertAlmostEqual(result_event.congestion_value_raw, expected_raw_value, places=5)
        self.assertEqual(result_event.congestion_level, CongestionLevelLabel.LOW)
        self.assertFalse(result_event.alert_triggered)

        # 스냅샷 상태 변경 확인
        self.snapshot_cam1_ai_completed.refresh_from_db()
        self.assertEqual(self.snapshot_cam1_ai_completed.processing_status_congestion, ProcessingStatus.COMPLETED)

    def test_calculate_and_save_congestion_event_success_high_congestion(self):
        # 시나리오: AI 분석 완료, 활성 ROI 존재, 높은 밀집도
        # 많은 사람 객체 생성 (예: 50명, 각 객체가 일정 면적 차지)
        person_footprint_area = 50.0  # 각 사람의 발자국 면적이 50이라고 가정 (단순화)
        num_persons = 100  # 100명
        for i in range(num_persons):
            # DetectedObjects를 실제로 생성하는 대신, calculate_total_footprint_area가 특정 값을 반환하도록 모킹할 수도 있음
            # 여기서는 DetectedObjects를 간단히 만듭니다. (bbox 값은 중요하지 않음, person_count와 footprint_area 합계가 중요)
            DetectedObjects.objects.create(
                snapshot=self.snapshot_cam1_ai_completed, class_label='person',
                bbox_x=i, bbox_y=i, bbox_width=25, bbox_height=80  # footprint = 25 * (80*0.05) = 25*4 = 100
            )
        # 총 footprint_area_sum = 100명 * 100 = 10000
        # congestion_value_raw = 10000 / 10000.0 (ROI area) = 1.0

        result_event = calculate_and_save_congestion_event(self.snapshot_cam1_ai_completed.snapshot_id)
        self.assertIsNotNone(result_event)
        self.assertEqual(result_event.person_count, num_persons)
        self.assertEqual(result_event.congestion_level, CongestionLevelLabel.VERY_HIGH)  # 1.0은 VERY_HIGH
        self.assertTrue(result_event.alert_triggered)

    def test_calculate_and_save_congestion_event_snapshot_not_found(self):
        result = calculate_and_save_congestion_event(99999)  # 존재하지 않는 ID
        self.assertIsNone(result)

    def test_calculate_and_save_congestion_event_ai_not_completed(self):
        result = calculate_and_save_congestion_event(self.snapshot_cam1_pending_ai.snapshot_id)
        self.assertIsNone(result)
        self.snapshot_cam1_pending_ai.refresh_from_db()
        self.assertEqual(self.snapshot_cam1_pending_ai.processing_status_congestion, ProcessingStatus.FAILED)

    def test_calculate_and_save_congestion_event_no_active_roi(self):
        # self.snapshot_cam2_ai_completed_no_roi 는 camera2에 연결되어 있고, camera2는 활성 ROI가 없음
        result = calculate_and_save_congestion_event(self.snapshot_cam2_ai_completed_no_roi.snapshot_id)
        self.assertIsNone(result)
        self.snapshot_cam2_ai_completed_no_roi.refresh_from_db()
        self.assertEqual(self.snapshot_cam2_ai_completed_no_roi.processing_status_congestion, ProcessingStatus.FAILED)

    def test_calculate_and_save_congestion_event_already_processed(self):
        # 첫 번째 처리
        DetectedObjects.objects.create(
            snapshot=self.snapshot_cam1_ai_completed, class_label='person',
            bbox_x=10, bbox_y=10, bbox_width=10, bbox_height=20
        )
        calculate_and_save_congestion_event(self.snapshot_cam1_ai_completed.snapshot_id)

        # 두 번째 처리 시도 (이미 COMPLETED 상태)  
        # 이전에 생성된 CongestionEvent가 몇 개인지 세어서, 추가 생성이 안되었는지 확인하거나,
        # calculate_and_save_congestion_event가 None을 반환함을 확인 (현재 구현은 None 반환)
        initial_event_count = CongestionEvents.objects.count()
        result_second_call = calculate_and_save_congestion_event(self.snapshot_cam1_ai_completed.snapshot_id)
        self.assertIsNone(result_second_call)  # 이미 처리된 경우 None 반환하도록 수정 or 기존 이벤트 객체 반환하도록 수정
        self.assertEqual(CongestionEvents.objects.count(), initial_event_count)  # 이벤트가 더 생성되지 않음