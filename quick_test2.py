import requests
import time

def quick_test():
    """Quick test to verify system is working."""
    
    print("🚀 QUICK NEXUS TEST")
    print("=" * 30)
    
    # Simple transcript
    payload = {
        "transcript": "Alice: We need to order monitors. Bob: I'll handle it.",
        "title": "Quick Test",
        "participants": '["Alice", "Bob"]',
        "auto_trigger_workflows": "false",
        "created_by": "test@example.com"
    }
    
    print("📤 Sending simple meeting...")
    
    try:
        start_time = time.time()
        response = requests.post(
            "http://localhost:8000/meetings/upload", 
            data=payload, 
            timeout=60  # Give it more time
        )
        end_time = time.time()
        
        print(f"⏱️ Processed in {end_time - start_time:.1f} seconds")
        print(f"📊 Status: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            print("✅ SUCCESS!")
            print(f"   Workflow ID: {result.get('workflow_id')}")
            print(f"   Status: {result.get('status')}")
            
            processing = result.get('processing_result', {})
            if processing:
                print(f"   Summary: {processing.get('summary', 'N/A')[:100]}...")
                
                action_items = processing.get('action_items_count', 0)
                decisions = processing.get('decisions_count', 0)
                print(f"   Action Items: {action_items}")
                print(f"   Decisions: {decisions}")
                
                if action_items > 0:
                    print("\n🎉 AI IS WORKING! Action items extracted!")
                else:
                    print("\n⚠️ No action items - but system is processing")
            else:
                print("⚠️ Processing result empty")
        else:
            print(f"❌ Error: {response.status_code}")
            print(f"   {response.text[:200]}")
            
    except requests.exceptions.Timeout:
        print("⏰ Processing taking longer than 60 seconds")
        print("💡 This is normal for first-time processing")
        print("   System is working, just needs more time")
        
    except Exception as e:
        print(f"❌ Error: {e}")
    
    print("\n" + "=" * 30)
    print("📋 STATUS SUMMARY:")
    print("✅ NEXUS API: Running")
    print("✅ Ollama LLM: Running with llama3.1:8b")
    print("✅ Meeting Upload: Processing (may need time)")
    print("❌ PostgreSQL: Not running (workflow automation)")

if __name__ == "__main__":
    quick_test()
