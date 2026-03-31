import requests
import json

def test_current_setup():
    """Test current NEXUS + Ollama setup."""
    
    print("🔍 TESTING CURRENT SETUP")
    print("=" * 40)
    
    # Test 1: Check NEXUS API
    try:
        response = requests.get("http://localhost:8000/health", timeout=5)
        if response.status_code == 200:
            print("✅ NEXUS API: Running")
        else:
            print(f"❌ NEXUS API: {response.status_code}")
    except:
        print("❌ NEXUS API: Not running")
        return
    
    # Test 2: Check Ollama
    try:
        response = requests.get("http://localhost:11434/api/tags", timeout=3)
        if response.status_code == 200:
            models = response.json().get("models", [])
            print(f"✅ Ollama: Running with {len(models)} models")
            for model in models[:3]:  # Show first 3
                print(f"   - {model.get('name', 'Unknown')}")
        else:
            print(f"❌ Ollama: {response.status_code}")
    except Exception as e:
        print(f"❌ Ollama: {str(e)}")
    
    # Test 3: Test meeting processing
    print("\n📤 Testing meeting processing...")
    
    payload = {
        "transcript": "Alice will order 5 Dell monitors. Bob will handle onboarding new engineer.",
        "title": "Team Meeting",
        "participants": '["Alice", "Bob"]',
        "auto_trigger_workflows": "false",
        "created_by": "test@example.com"
    }
    
    try:
        response = requests.post("http://localhost:8000/meetings/upload", data=payload, timeout=20)
        print(f"📤 Meeting Upload: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            status = result.get('status', 'unknown')
            print(f"   Status: {status}")
            
            processing = result.get('processing_result', {})
            if processing:
                summary = processing.get('summary', 'No summary')
                print(f"   Summary: {summary[:100]}...")
                
                action_count = processing.get('action_items_count', 0)
                decision_count = processing.get('decisions_count', 0)
                print(f"   Action Items: {action_count}")
                print(f"   Decisions: {decision_count}")
                
                if action_count > 0 or decision_count > 0:
                    print("\n🎉 AI PROCESSING WORKING!")
                    print("   ✅ Action items extracted")
                    print("   ✅ Decisions identified")
                else:
                    print("\n⚠️ AI processing may need attention")
                    print("   - Check if Ollama has the right model")
                    print("   - Check LLM router configuration")
            else:
                print("⚠️ No processing results received")
        else:
            print(f"   Error: {response.text[:200]}")
            
    except Exception as e:
        print(f"❌ Meeting test failed: {e}")
    
    print("\n" + "=" * 40)
    print("💡 NEXT STEPS:")
    print("1. If Ollama is running but no action items:")
    print("   - Check if llama3.1:8b model is available")
    print("   - Or use current model (qwen2.5-coder:7b)")
    print("2. If meeting upload works: System is functional!")
    print("3. For workflow automation: Start PostgreSQL")

if __name__ == "__main__":
    test_current_setup()
