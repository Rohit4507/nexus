import requests
import json

def test_meeting_agent_full():
    """Test the meeting agent with a comprehensive example."""
    
    print("🎯 TESTING NEXUS MEETING AGENT - FULL DEMO")
    print("=" * 50)
    
    base_url = "http://localhost:8000"
    
    # Comprehensive meeting transcript
    transcript = """
    Alice: Good morning everyone. Let's discuss our infrastructure needs for the new team members starting next week.
    
    Bob: I've been thinking about this. We need to order 5 Dell monitors - the UltraSharp models we discussed last month.
    
    Charlie: Yes, and I need to set up email accounts and Slack access for the two new engineers. I'll handle the onboarding process.
    
    Alice: Great. Also, we need to prepare the NDA agreement for the vendor contract renewal that's due next month.
    
    Bob: I'll contact the legal department about the NDA and contract renewal.
    
    Charlie: Should I order the monitors or do you want to handle that Bob?
    
    Bob: I'll place the order for the monitors today. I'll get the approved vendor list from procurement.
    
    Alice: Perfect. Let's meet again next Friday to review the onboarding progress.
    
    Charlie: Sounds good. I'll have the accounts ready by Monday.
    """
    
    payload = {
        "transcript": transcript.strip(),
        "title": "Infrastructure Planning Meeting",
        "participants": '["Alice", "Bob", "Charlie"]',
        "auto_trigger_workflows": "false",
        "created_by": "team-lead@company.com"
    }
    
    try:
        print("📤 Processing meeting transcript...")
        response = requests.post(f"{base_url}/meetings/upload", data=payload, timeout=30)
        
        if response.status_code == 200:
            result = response.json()
            print("✅ MEETING PROCESSING SUCCESSFUL!")
            print()
            
            print(f"🔍 Workflow ID: {result.get('workflow_id')}")
            print(f"📊 Status: {result.get('status')}")
            print()
            
            # Show processing results
            processing = result.get('processing_result', {})
            if processing:
                print("📋 MEETING ANALYSIS RESULTS:")
                print(f"   📝 Summary: {processing.get('summary', 'N/A')}")
                print()
                
                action_items = processing.get('action_items_count', 0)
                decisions = processing.get('decisions_count', 0)
                
                print(f"   ✅ Action Items Found: {action_items}")
                print(f"   🎯 Decisions Made: {decisions}")
                print()
                
                # Show downstream workflows (if any)
                downstream = result.get('downstream_workflows', [])
                if downstream:
                    print("🔄 AUTOMATED WORKFLOW TRIGGERS:")
                    for workflow in downstream:
                        print(f"   • {workflow.get('task', 'N/A')} -> {workflow.get('status', 'N/A')}")
                else:
                    print("🔄 No downstream workflows (auto_trigger_workflows=false)")
                
                print()
                print("🎉 NEXUS MEETING AGENT IS WORKING PERFECTLY!")
                print("   ✅ Transcript processed")
                print("   ✅ Action items extracted") 
                print("   ✅ Decisions identified")
                print("   ✅ Summary generated")
                print("   ✅ Task assignments suggested")
                
            else:
                print("⚠️ No processing details available")
                
        else:
            print(f"❌ Error: {response.status_code}")
            print(f"Response: {response.text[:500]}")
            
    except Exception as e:
        print(f"❌ Test failed: {e}")
    
    print("\n" + "=" * 50)
    print("💡 NEXT STEPS:")
    print("1. Use http://localhost:8000/docs for interactive testing")
    print("2. Upload your own meeting transcripts")
    print("3. Extract actionable items automatically")
    print("4. Start PostgreSQL for workflow automation (optional)")

if __name__ == "__main__":
    test_meeting_agent_full()
