from django.test import TestCase
from django.db.models import Count, Avg, Sum, F, Q
from analytics.models import *  # Import all models from analytics app


class AnalyticsORMTestCase(TestCase):
    """Test case to verify Django ORM functionality with analytics models"""
    
    def test_orm_basic_operations(self):
        """Test basic ORM operations"""
        # Print all model classes in the analytics app
        print("\n=== 사용 가능한 모델 클래스 ===")
        for model_class in [Cameras, CameraStatus, CameraSourceType, 
                           ProcessingStatus, CongestionLevel, ROIDefinitionType]:
            print(f"- {model_class.__name__}")
        
        # Test camera operations
        print("\n=== 카메라 데이터 테스트 ===")
        # Count cameras
        total_cameras = Cameras.objects.count()
        print(f"총 카메라 수: {total_cameras}")
        
        # List all cameras (limited to 5)
        cameras = Cameras.objects.all()[:5]
        print("\n카메라 목록 (최대 5개):")
        for camera in cameras:
            print(f"- ID: {camera.camera_id}, 이름: {camera.name}")
        
        # Example of filtering (if cameras exist)
        if total_cameras > 0:
            # Get camera with the lowest ID
            first_camera = Cameras.objects.order_by('camera_id').first()
            print(f"\n첫 번째 카메라: {first_camera.name}")
            
            # Example of field access
            print(f"RTSP URL: {first_camera.rtsp_url or '없음'}")


# This code runs when you execute this file directly
if __name__ == "__main__":
    import os
    import django
    
    # Setup Django environment if running standalone
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'SmartCCTV.settings')
    django.setup()
    
    # # Create an instance of the test case
    # test_case = AnalyticsORMTestCase()
    #
    # # Run the test method directly
    # print("\n===== Django ORM 테스트 시작 =====")
    # test_case.test_orm_basic_operations()
    # print("\n===== Django ORM 테스트 완료 =====")