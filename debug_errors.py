import requests
import json

def debug_api_errors():
    """Debug the internal errors in meetings and workflows."""
    
    print("🔍 DEBUGGING API ERRORS")
    print("=" * 40)
    
    base_url = "http://localhost:8000"
    
    # Test 1: Health Check (should work)
    try:
        response = requests.get(f"{base_url}/health", timeout=5)
        print(f"✅ Health: {response.status_code}")
        if response.status_code == 200:
            print(f"   {response.json()}")
    except Exception as e:
        print(f"❌ Health Error: {e}")
    
    # Test 2: Workflows List (likely database error)
    try:
        response = requests.get(f"{base_url}/workflows?limit=5", timeout=5)
        print(f"📋 Workflows: {response.status_code}")
        if response.status_code != 200:
            print(f"   Error: {response.text[:200]}")
    except Exception as e:
        print(f"❌ Workflows Error: {e}")
    
    # Test 3: Meeting Upload (likely database error)
    try:
        payload = {
            "transcript": "Alice will order monitors. Bob will handle onboarding.",
            "title": "Test Meeting",
            "participants": '["Alice", "Bob"]',
            "auto_trigger_workflows": "false",
            "created_by": "test@example.com"
        }
        
        response = requests.post(f"{base_url}/meetings/upload", data=payload, timeout=10)
        print(f"📤 Meeting Upload: {response.status_code}")
        if response.status_code != 200:
            print(f"   Error: {response.text[:300]}")
    except Exception as e:
        print(f"❌ Meeting Error: {e}")
    
    # Test 4: Generic Workflow Trigger (likely database error)
    try:
        payload = {
            "workflow_type": "meeting",
            "payload": {
                "title": "Test Meeting",
                "transcript": "Alice will order monitors.",
                "participants": ["Alice", "Bob"]
            },
            "created_by": "test@example.com"
        }
        
        response = requests.post(f"{base_url}/workflows/trigger", json=payload, timeout=10)
        print(f"⚡ Workflow Trigger: {response.status_code}")
        if response.status_code != 200:
            print(f"   Error: {response.text[:300]}")
    except Exception as e:
        print(f"❌ Workflow Trigger Error: {e}")

if __name__ == "__main__":
    debug_api_errors()
