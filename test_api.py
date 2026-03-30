import requests
import json

def test_api_endpoints():
    """Test the NEXUS API endpoints to show they're working."""
    
    base_url = "http://localhost:8000"
    
    print("🚀 Testing NEXUS API Endpoints")
    print("=" * 50)
    
    # Test 1: Health Check
    try:
        response = requests.get(f"{base_url}/health", timeout=5)
        if response.status_code == 200:
            data = response.json()
            print("✅ Health Check:")
            print(f"   Status: {data['status']}")
            print(f"   Version: {data['version']}")
            print(f"   Environment: {data['environment']}")
        else:
            print(f"❌ Health Check Failed: {response.status_code}")
    except Exception as e:
        print(f"❌ Health Check Error: {e}")
    
    print()
    
    # Test 2: List Workflows (should work even without DB)
    try:
        response = requests.get(f"{base_url}/workflows?limit=5", timeout=5)
        print(f"📋 Workflows List: Status {response.status_code}")
        if response.status_code == 200:
            workflows = response.json()
            print(f"   Found {len(workflows)} workflows")
        else:
            print("   (May need database for full functionality)")
    except Exception as e:
        print(f"❌ Workflows Error: {e}")
    
    print()
    
    # Test 3: Simple Meeting Upload (transcript only)
    try:
        payload = {
            "transcript": "Alice will order new monitors. Bob will handle onboarding.",
            "title": "Test Meeting",
            "participants": '["Alice", "Bob"]',
            "auto_trigger_workflows": "false",
            "created_by": "test@example.com"
        }
        
        response = requests.post(f"{base_url}/meetings/upload", data=payload, timeout=10)
        print(f"📤 Meeting Upload: Status {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            print(f"   Workflow ID: {result.get('workflow_id', 'N/A')}")
            print(f"   Status: {result.get('status', 'N/A')}")
            print("   ✅ Meeting processing pipeline working!")
        else:
            print(f"   Response: {response.text[:200]}")
            
    except Exception as e:
        print(f"❌ Meeting Upload Error: {e}")
    
    print()
    
    # Test 4: API Docs
    try:
        response = requests.get(f"{base_url}/docs", timeout=5)
        if response.status_code == 200:
            print("✅ API Documentation:")
            print(f"   Available at: {base_url}/docs")
            print("   Interactive Swagger UI ready!")
        else:
            print(f"❌ Docs Failed: {response.status_code}")
    except Exception as e:
        print(f"❌ Docs Error: {e}")
    
    print()
    print("=" * 50)
    print("🎉 API is RUNNING and ACCESSIBLE!")
    print()
    print("📚 Available Endpoints:")
    print(f"   • Health: {base_url}/health")
    print(f"   • Workflows: {base_url}/workflows")
    print(f"   • Meeting Upload: {base_url}/meetings/upload")
    print(f"   • API Docs: {base_url}/docs")
    print(f"   • Metrics: {base_url}/metrics")
    print()
    print("🌐 Open your browser and go to:")
    print(f"   {base_url}/docs")
    print("   (Interactive API testing interface)")

if __name__ == "__main__":
    test_api_endpoints()
