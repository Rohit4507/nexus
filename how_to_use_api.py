"""
NEXUS API - How to Know It's Running and How to Use It
======================================================

STEP 1: CHECK IF API IS RUNNING
------------------------------
Open PowerShell/CMD and run:

curl http://localhost:8000/health

OR in PowerShell:
Invoke-WebRequest -Uri http://localhost:8000/health -UseBasicParsing

You should see:
{"status":"healthy","version":"0.1.0","environment":"development"}

If you see this, the API is RUNNING! ✅

STEP 2: OPEN THE API DOCUMENTATION
----------------------------------
Open your web browser and go to:
http://localhost:8000/docs

This shows you ALL available endpoints with interactive testing!

STEP 3: TEST THE MEETING AGENT
------------------------------
METHOD A: Using the Web Interface (Easiest)
1. Go to http://localhost:8000/docs
2. Find the POST /meetings/upload endpoint
3. Click "Try it out"
4. Fill in the form:
   - transcript: "Alice will order new monitors. Bob will handle onboarding."
   - title: "Test Meeting"
   - participants: '["Alice", "Bob"]'
   - auto_trigger_workflows: false
   - created_by: "test@example.com"
5. Click "Execute"

METHOD B: Using PowerShell
```powershell
$body = @{
    transcript = "Alice will order new monitors. Bob will handle onboarding."
    title = "Test Meeting"
    participants = '["Alice", "Bob"]'
    auto_trigger_workflows = "false"
    created_by = "test@example.com"
}

Invoke-WebRequest -Uri http://localhost:8000/meetings/upload -Method POST -Form $body -UseBasicParsing
```

METHOD C: Using Python
```python
import requests

payload = {
    "transcript": "Alice will order new monitors. Bob will handle onboarding.",
    "title": "Test Meeting", 
    "participants": '["Alice", "Bob"]',
    "auto_trigger_workflows": False,
    "created_by": "test@example.com"
}

response = requests.post("http://localhost:8000/meetings/upload", data=payload)
print(response.json())
```

STEP 4: CHECK THE RESULTS
------------------------
The API will return:
- workflow_id: Unique ID for your meeting
- status: "completed" or "escalated"
- processing_result: Summary, action items, decisions
- downstream_workflows: Any automated workflows triggered

STEP 5: MONITOR THE API
----------------------
Health Check: http://localhost:8000/health
API Docs:    http://localhost:8000/docs
Metrics:     http://localhost:8000/metrics

COMMON TROUBLESHOOTING
-----------------------
❌ "Connection refused" → API not running, start it first
❌ "Timeout" → Processing audio, wait longer or use transcript only
❌ "Database error" → PostgreSQL not running (meetings still work without DB)

STARTING THE API (if not running)
----------------------------------
cd "C:\Users\rohit\OneDrive\Desktop\mlops\nexus"
python -m uvicorn nexus.api.main:app --host 0.0.0.0 --port 8000 --reload

You should see output like:
INFO:     Started server process [12345]
INFO:     Waiting for application startup.
🚀 NEXUS v0.1.0 starting in development mode
INFO:     Application startup complete.

That's it! Your NEXUS API is ready to use! 🚀
"""

def show_running_status():
    """Check and display the current API running status."""
    
    print("🔍 CHECKING NEXUS API STATUS")
    print("=" * 50)
    
    try:
        import requests
        response = requests.get("http://localhost:8000/health", timeout=3)
        
        if response.status_code == 200:
            data = response.json()
            print("✅ API IS RUNNING!")
            print(f"   Status: {data['status']}")
            print(f"   Version: {data['version']}")
            print(f"   Environment: {data['environment']}")
            print()
            print("🌐 HOW TO USE IT:")
            print("   1. Open browser: http://localhost:8000/docs")
            print("   2. Try the meeting upload endpoint")
            print("   3. Use the interactive Swagger UI")
            print()
            print("📋 QUICK TEST:")
            print("   POST http://localhost:8000/meetings/upload")
            print("   with transcript: 'Alice will order monitors'")
            print()
        else:
            print(f"❌ API responded with: {response.status_code}")
            
    except requests.exceptions.ConnectionError:
        print("❌ API IS NOT RUNNING")
        print()
        print("🚀 HOW TO START IT:")
        print("   cd 'C:\\Users\\rohit\\OneDrive\\Desktop\\mlops\\nexus'")
        print("   python -m uvicorn nexus.api.main:app --host 0.0.0.0 --port 8000 --reload")
        print()
        
    except Exception as e:
        print(f"❌ Error checking API: {e}")

if __name__ == "__main__":
    show_running_status()
    print("\n" + "=" * 50)
    print("📚 FULL DOCUMENTATION ABOVE IN THE DOCSTRING")
