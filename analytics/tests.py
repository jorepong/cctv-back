from django.test import TestCase
from django.utils import timezone
# from decimal import Decimal # 필요시 사용

from analytics.models import Cameras, ROIDefinitions, ROIDefinitionType
from analytics.tasks import update_roi_for_camera_service

try:
    from shapely.geometry import Polygon, Point

    SHAPELY_AVAILABLE = True
except ImportError:
    Polygon = None
    Point = None
    SHAPELY_AVAILABLE = False


class ROIEstimationServiceTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        print("\n" + "=" * 70)
        print("ROIEstimationServiceTests: Setting up test data...")
        print("=" * 70)
        if not SHAPELY_AVAILABLE:
            print("WARNING: Shapely library not found. Some ROI tests may not run correctly or be skipped.")

        cls.camera1 = Cameras.objects.create(name="TestCamera1_WithInitialROI", is_active_monitoring=True)
        cls.camera2 = Cameras.objects.create(name="TestCamera2_NoInitialROI", is_active_monitoring=True)
        cls.camera3 = Cameras.objects.create(name="TestCamera3_ForCollinear", is_active_monitoring=True)

        cls.initial_roi_coords_cam1 = [
            {"x": 10.0, "y": 10.0}, {"x": 60.0, "y": 10.0},
            {"x": 60.0, "y": 60.0}, {"x": 10.0, "y": 60.0},
        ]
        cls.initial_roi_area_cam1 = 0.0
        if Polygon:
            try:
                cls.initial_roi_area_cam1 = Polygon([(p['x'], p['y']) for p in cls.initial_roi_coords_cam1]).area
            except Exception:
                cls.initial_roi_area_cam1 = 2500.0

        ROIDefinitions.objects.create(
            camera=cls.camera1,
            definition_type=ROIDefinitionType.DYNAMIC_CONVEX_HULL,
            definition_data={
                "type": ROIDefinitionType.DYNAMIC_CONVEX_HULL.label,
                "coordinates": cls.initial_roi_coords_cam1,
                "area": cls.initial_roi_area_cam1
            },
            is_active=True,
            version=1
        )
        print("setUpTestData: Initial data setup complete.\n")

    def _assert_coordinates_match(self, coords1, coords2, tolerance=1e-5):
        self.assertEqual(len(coords1), len(coords2), "Coordinate list lengths differ.")
        sorted_coords1 = sorted(coords1, key=lambda p: (p.get('x', 0), p.get('y', 0)))
        sorted_coords2 = sorted(coords2, key=lambda p: (p.get('x', 0), p.get('y', 0)))
        for p1, p2 in zip(sorted_coords1, sorted_coords2):
            self.assertAlmostEqual(p1.get('x', 0), p2.get('x', 0), delta=tolerance, msg="X coordinates differ.")
            self.assertAlmostEqual(p1.get('y', 0), p2.get('y', 0), delta=tolerance, msg="Y coordinates differ.")

    def test_service_camera_not_found(self):
        print("\n--- Test: test_service_camera_not_found ---")
        print("Purpose: 존재하지 않는 카메라 ID로 ROI 업데이트 시도 시 False 반환 확인")
        if not SHAPELY_AVAILABLE: self.skipTest("Shapely not available for this test.")

        non_existent_camera_id = 9999
        footprints = [(1, 1), (2, 2), (3, 1)]
        print(f"Action: Calling update_roi_for_camera_service with camera_id={non_existent_camera_id}")
        result = update_roi_for_camera_service(non_existent_camera_id, footprints)

        self.assertFalse(result, "Should return False for non-existent camera.")
        print(f"Result: Service returned {result} (Expected: False). Test Passed.")

    def test_service_create_new_roi_for_camera_without_one(self):
        print("\n--- Test: test_service_create_new_roi_for_camera_without_one ---")
        print(f"Purpose: 기존 ROI가 없는 카메라(ID: {self.camera2.camera_id})에 새 ROI 생성 테스트")
        if not SHAPELY_AVAILABLE: self.skipTest("Shapely not available for this test.")

        footprints = [(10.0, 10.0), (110.0, 10.0), (110.0, 110.0), (10.0, 110.0)]
        expected_area = 10000.0
        print(
            f"Action: Calling update_roi_for_camera_service for camera_id={self.camera2.camera_id} with {len(footprints)} footprints.")
        ROIDefinitions.objects.filter(camera=self.camera2).delete()  # Ensure clean state
        result = update_roi_for_camera_service(self.camera2.camera_id, footprints)

        self.assertTrue(result, "ROI creation should succeed.")
        print(f"Result: Service returned {result} (Expected: True).")

        new_roi_def = ROIDefinitions.objects.get(camera=self.camera2, is_active=True)
        self.assertIsNotNone(new_roi_def)
        self.assertEqual(new_roi_def.definition_type, ROIDefinitionType.DYNAMIC_CONVEX_HULL)
        self.assertAlmostEqual(new_roi_def.definition_data.get('area', 0), expected_area, places=1)
        print(
            f"DB Check: New ROI created with area {new_roi_def.definition_data.get('area', 0):.1f} (Expected: {expected_area:.1f}).")

        expected_poly_coords = Polygon(footprints).convex_hull.exterior.coords
        expected_coords_dict = [{"x": p[0], "y": p[1]} for p in expected_poly_coords[:-1]]
        self._assert_coordinates_match(new_roi_def.definition_data.get('coordinates', []), expected_coords_dict)
        print("DB Check: Coordinates match expected convex hull. Test Passed.")

    def test_service_create_roi_insufficient_footprints(self):
        print("\n--- Test: test_service_create_roi_insufficient_footprints ---")
        print(f"Purpose: 충분하지 않은 발자취 포인트(<3개)로 카메라(ID: {self.camera2.camera_id}) ROI 생성 시도")
        if not SHAPELY_AVAILABLE: self.skipTest("Shapely not available for this test.")

        footprints = [(10.0, 10.0), (20.0, 20.0)]
        print(
            f"Action: Calling update_roi_for_camera_service for camera_id={self.camera2.camera_id} with {len(footprints)} footprints.")
        ROIDefinitions.objects.filter(camera=self.camera2).delete()  # Ensure clean state
        result = update_roi_for_camera_service(self.camera2.camera_id, footprints)

        self.assertFalse(result, "ROI creation should fail with <3 points.")
        print(f"Result: Service returned {result} (Expected: False).")

        roi_exists = ROIDefinitions.objects.filter(camera=self.camera2, is_active=True).exists()
        self.assertFalse(roi_exists)
        print(f"DB Check: ROI was not created (Exists: {roi_exists}, Expected: False). Test Passed.")

    def test_service_update_roi_no_new_outside_points(self):
        print("\n--- Test: test_service_update_roi_no_new_outside_points ---")
        print(f"Purpose: 새 발자취가 모두 기존 ROI 내부에 있을 때 카메라(ID: {self.camera1.camera_id}) ROI 변경 없음 확인")
        if not SHAPELY_AVAILABLE: self.skipTest("Shapely not available for this test.")

        footprints_inside = [(20.0, 20.0), (30.0, 30.0), (25.0, 40.0)]
        print(
            f"Action: Calling update_roi_for_camera_service for camera_id={self.camera1.camera_id} with {len(footprints_inside)} (inside) footprints.")
        initial_updated_at = ROIDefinitions.objects.get(camera=self.camera1, is_active=True).updated_at
        result = update_roi_for_camera_service(self.camera1.camera_id, footprints_inside)

        self.assertFalse(result, "ROI should not update if new points are all inside.")
        print(f"Result: Service returned {result} (Expected: False).")

        current_roi_def = ROIDefinitions.objects.get(camera=self.camera1, is_active=True)
        self._assert_coordinates_match(current_roi_def.definition_data.get('coordinates', []),
                                       self.initial_roi_coords_cam1)
        self.assertAlmostEqual(current_roi_def.definition_data.get('area', 0), self.initial_roi_area_cam1, places=1)
        # self.assertEqual(current_roi_def.updated_at, initial_updated_at, "updated_at should not change if no update occurs.")
        print(
            f"DB Check: ROI unchanged. Area {current_roi_def.definition_data.get('area', 0):.1f} (Expected: {self.initial_roi_area_cam1:.1f}). Test Passed.")

    def test_service_update_roi_expansion_with_outside_points(self):
        print("\n--- Test: test_service_update_roi_expansion_with_outside_points ---")
        print(f"Purpose: 새 발자취가 기존 ROI 외부에 있어 카메라(ID: {self.camera1.camera_id}) ROI가 확장되는 경우 확인")
        if not SHAPELY_AVAILABLE: self.skipTest("Shapely not available for this test.")

        footprints_outside = [(80.0, 80.0)]
        print(
            f"Action: Calling update_roi_for_camera_service for camera_id={self.camera1.camera_id} with {len(footprints_outside)} (outside) footprint.")
        result = update_roi_for_camera_service(self.camera1.camera_id, footprints_outside)

        self.assertTrue(result, "ROI update (expansion) should succeed.")
        print(f"Result: Service returned {result} (Expected: True).")

        updated_roi_def = ROIDefinitions.objects.get(camera=self.camera1, is_active=True)

        all_points_for_hull = self.initial_roi_coords_cam1 + [{"x": fp[0], "y": fp[1]} for fp in footprints_outside]
        all_points_tuples = [(p['x'], p['y']) for p in all_points_for_hull]
        expected_new_poly = Polygon(all_points_tuples).convex_hull
        expected_new_area = expected_new_poly.area
        expected_new_coords_dict = [{"x": p[0], "y": p[1]} for p in expected_new_poly.exterior.coords[:-1]]

        self._assert_coordinates_match(updated_roi_def.definition_data.get('coordinates', []), expected_new_coords_dict)
        self.assertAlmostEqual(updated_roi_def.definition_data.get('area', 0), expected_new_area, places=1)
        self.assertTrue(updated_roi_def.definition_data.get('area', 0) > self.initial_roi_area_cam1)
        print(
            f"DB Check: ROI expanded. New Area {updated_roi_def.definition_data.get('area', 0):.1f} (Expected: {expected_new_area:.1f}, Initial: {self.initial_roi_area_cam1:.1f}). Test Passed.")

    def test_service_update_roi_no_new_footprints(self):
        print("\n--- Test: test_service_update_roi_no_new_footprints ---")
        print(f"Purpose: 새 발자취가 없을 때 카메라(ID: {self.camera1.camera_id}) ROI 변경 없음 확인")
        if not SHAPELY_AVAILABLE: self.skipTest("Shapely not available for this test.")

        footprints_empty = []
        print(
            f"Action: Calling update_roi_for_camera_service for camera_id={self.camera1.camera_id} with empty footprints.")
        result = update_roi_for_camera_service(self.camera1.camera_id, footprints_empty)

        self.assertFalse(result, "ROI should not update if no new footprints are provided.")
        print(f"Result: Service returned {result} (Expected: False).")

        current_roi_def = ROIDefinitions.objects.get(camera=self.camera1, is_active=True)
        self._assert_coordinates_match(current_roi_def.definition_data.get('coordinates', []),
                                       self.initial_roi_coords_cam1)
        self.assertAlmostEqual(current_roi_def.definition_data.get('area', 0), self.initial_roi_area_cam1, places=1)
        print(
            f"DB Check: ROI unchanged. Area {current_roi_def.definition_data.get('area', 0):.1f} (Expected: {self.initial_roi_area_cam1:.1f}). Test Passed.")

    def test_service_create_roi_collinear_points(self):
        print("\n--- Test: test_service_create_roi_collinear_points ---")
        print(f"Purpose: 일직선 상의 점들로 카메라(ID: {self.camera3.camera_id}) ROI 생성 시도 (유효 폴리곤 생성 불가)")
        if not SHAPELY_AVAILABLE: self.skipTest("Shapely not available for this test.")

        footprints_collinear = [(10.0, 10.0), (20.0, 10.0), (30.0, 10.0)]
        print(
            f"Action: Calling update_roi_for_camera_service for camera_id={self.camera3.camera_id} with collinear footprints.")
        ROIDefinitions.objects.filter(camera=self.camera3).delete()  # Ensure clean state
        result = update_roi_for_camera_service(self.camera3.camera_id, footprints_collinear)

        self.assertFalse(result, "ROI creation should fail for collinear points not forming a polygon.")
        print(f"Result: Service returned {result} (Expected: False).")

        roi_exists = ROIDefinitions.objects.filter(camera=self.camera3, is_active=True).exists()
        self.assertFalse(roi_exists)
        print(f"DB Check: ROI was not created (Exists: {roi_exists}, Expected: False). Test Passed.")

    def test_service_update_roi_complex_shape_expansion(self):
        print("\n--- Test: test_service_update_roi_complex_shape_expansion ---")
        print(f"Purpose: 복잡한 형태의 다각형으로 ROI(카메라 ID: {self.camera1.camera_id})가 확장되는 경우 확인")
        if not SHAPELY_AVAILABLE: self.skipTest("Shapely not available for this test.")

        # 초기 ROI: self.camera1의 정사각형 (10,10) - (60,60) / 넓이: 2500.0
        # self.initial_roi_coords_cam1 = [
        #     {"x": 10.0, "y": 10.0}, {"x": 60.0, "y": 10.0},
        #     {"x": 60.0, "y": 60.0}, {"x": 10.0, "y": 60.0},
        # ]
        # self.initial_roi_area_cam1 (2500.0)

        # 새롭게 추가될 외부 발자취 포인트들 (기존 ROI를 여러 방향으로 확장시킬 수 있도록)
        footprints_complex_expansion = [
            (5.0, 65.0),  # 기존 ROI의 좌하단 바깥
            (35.0, 80.0),  # 기존 ROI의 하단 중앙 바깥 (더 아래로)
            (70.0, 65.0),  # 기존 ROI의 우하단 바깥
            (80.0, 30.0),  # 기존 ROI의 우상단 바깥 (더 오른쪽으로)
            (65.0, 5.0),  # 기존 ROI의 우상단 바깥 (더 위로)
            (5.0, 5.0)  # 기존 ROI의 좌상단 바깥
        ]
        print(
            f"Action: Calling update_roi_for_camera_service for camera_id={self.camera1.camera_id} with {len(footprints_complex_expansion)} (complex expansion) footprints.")

        # 테스트 실행 전, camera1의 ROI를 초기 상태로 확실히 돌리기 위해 (다른 테스트의 영향 배제)
        # setUpTestData에서 생성된 cls.roi_def_cam1을 직접 사용하거나, 아래처럼 다시 설정 가능
        ROIDefinitions.objects.update_or_create(
            camera=self.camera1, is_active=True,
            defaults={
                'definition_type': ROIDefinitionType.DYNAMIC_CONVEX_HULL,
                'definition_data': {
                    "type": ROIDefinitionType.DYNAMIC_CONVEX_HULL.label,
                    "coordinates": self.initial_roi_coords_cam1,
                    "area": self.initial_roi_area_cam1
                },
                'version': 1  # 필요시 버전 관리
            }
        )
        initial_roi_def_check = ROIDefinitions.objects.get(camera=self.camera1, is_active=True)
        print(
            f"Initial ROI for test: Area {initial_roi_def_check.definition_data.get('area', 0):.1f}, Coords Count: {len(initial_roi_def_check.definition_data.get('coordinates', []))}")

        result = update_roi_for_camera_service(self.camera1.camera_id, footprints_complex_expansion)

        self.assertTrue(result, "ROI update (complex expansion) should succeed.")
        print(f"Result: Service returned {result} (Expected: True).")

        updated_roi_def = ROIDefinitions.objects.get(camera=self.camera1, is_active=True)

        # 예상되는 새 ROI 좌표 (기존 ROI 점들 + 새 외부 점의 Convex Hull)
        # 모든 점들을 튜플 리스트로 변환
        all_points_for_hull_dicts = self.initial_roi_coords_cam1 + [{"x": fp[0], "y": fp[1]} for fp in
                                                                    footprints_complex_expansion]
        all_points_tuples = [(p['x'], p['y']) for p in all_points_for_hull_dicts]

        # Shapely를 사용하여 예상되는 Convex Hull 계산
        expected_new_poly = Polygon(all_points_tuples).convex_hull
        expected_new_area = expected_new_poly.area
        # Shapely 결과 좌표는 (x,y) 튜플 리스트이며, 마지막 점이 첫 점과 동일. dict 리스트로 변환 시 마지막 점 제외.
        expected_new_coords_dict = [{"x": p[0], "y": p[1]} for p in list(expected_new_poly.exterior.coords)[:-1]]

        print(
            f"DB Check: ROI expanded. New Area {updated_roi_def.definition_data.get('area', 0):.1f} (Expected: {expected_new_area:.1f})")
        print(
            f"DB Check: New Coords Count {len(updated_roi_def.definition_data.get('coordinates', []))} (Expected: {len(expected_new_coords_dict)})")
        # print(f"DB Coords: {updated_roi_def.definition_data.get('coordinates', [])}") # 디버깅 시 실제 좌표 출력
        # print(f"Expected Coords: {expected_new_coords_dict}") # 디버깅 시 예상 좌표 출력

        self._assert_coordinates_match(updated_roi_def.definition_data.get('coordinates', []), expected_new_coords_dict)
        self.assertAlmostEqual(updated_roi_def.definition_data.get('area', 0), expected_new_area, places=1)
        self.assertTrue(updated_roi_def.definition_data.get('area', 0) > self.initial_roi_area_cam1,
                        "Area should have significantly expanded.")
        self.assertTrue(len(updated_roi_def.definition_data.get('coordinates', [])) > 4,
                        "Number of vertices in complex ROI should be > 4.")
        print(f"DB Check: Area and Coordinates match expected complex convex hull. Test Passed.")