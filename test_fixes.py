import asyncio
import json
import httpx

async def test_meeting_workflow():
    """Test the meeting agent with all fixes applied."""
    
    # Test payload
    payload = {
        "workflow_type": "meeting",
        "payload": {
            "title": "Test Meeting with Fixes",
            "transcript": "Alice will order new Dell monitors for the team. Bob will onboard the new engineer next week.",
            "participants": ["Alice", "Bob"],
            "auto_trigger_workflows": True,
            "trigger_confidence_threshold": 0.7,
            "approve_high_impact_actions": True
        },
        "created_by": "test@example.com"
    }
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                "http://localhost:8000/workflows/trigger",
                json=payload,
                timeout=60.0
            )
            
            if response.status_code == 200:
                result = response.json()
                print("✅ Meeting workflow test successful!")
                print(f"   Workflow ID: {result.get('workflow_id')}")
                print(f"   Status: {result.get('status')}")
                print(f"   Phases completed: {result.get('phases_completed', 0)}")
                
                # Check if downstream workflows were triggered
                details = result.get('details', [])
                for detail in details:
                    if detail.get('agent') == 'meeting_executor':
                        meeting_result = detail.get('result', {})
                        downstream = meeting_result.get('downstream_workflows', [])
                        print(f"   Downstream workflows triggered: {len(downstream)}")
                        for workflow in downstream:
                            print(f"     - {workflow.get('task')} -> {workflow.get('workflow_type')} ({workflow.get('status')})")
                
                return True
            else:
                print(f"❌ Test failed with status {response.status_code}")
                print(f"   Response: {response.text}")
                return False
                
        except Exception as e:
            print(f"❌ Test failed with error: {str(e)}")
            return False

async def test_health():
    """Test basic health endpoint."""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get("http://localhost:8000/health")
            if response.status_code == 200:
                data = response.json()
                print("✅ Health check passed")
                print(f"   Status: {data.get('status')}")
                print(f"   Version: {data.get('version')}")
                print(f"   Environment: {data.get('environment')}")
                return True
            else:
                print(f"❌ Health check failed: {response.status_code}")
                return False
        except Exception as e:
            print(f"❌ Health check error: {str(e)}")
            return False

async def main():
    print("🧪 Testing NEXUS with all fixes applied...")
    print()
    
    # Test health first
    if not await test_health():
        return
    
    print()
    
    # Test meeting workflow
    success = await test_meeting_workflow()
    
    print()
    if success:
        print("🎉 All tests passed! NEXUS is running correctly with all fixes.")
    else:
        print("⚠️  Some tests failed. Check the logs above.")

if __name__ == "__main__":
    asyncio.run(main())
