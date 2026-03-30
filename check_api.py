import requests

def check_api_status():
    """Check and display the current API status in a clear way."""
    
    print("🔍 NEXUS API STATUS CHECK")
    print("=" * 40)
    
    try:
        # Test health endpoint
        response = requests.get("http://localhost:8000/health", timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            print("✅ API IS RUNNING!")
            print(f"   Status: {data['status']}")
            print(f"   Version: {data['version']}")
            print(f"   Environment: {data['environment']}")
            print()
            print("🌐 HOW TO USE IT:")
            print("   1. Open your web browser")
            print("   2. Go to: http://localhost:8000/docs")
            print("   3. You'll see the interactive API documentation")
            print("   4. Click on any endpoint to test it")
            print()
            print("📤 QUICK TEST - MEETING UPLOAD:")
            print("   • In the docs, find POST /meetings/upload")
            print("   • Click 'Try it out'")
            print("   • Enter a transcript like: 'Alice will order monitors'")
            print("   • Click Execute")
            print("   • See the AI extract action items!")
            print()
            print("🎯 YOUR API IS READY! 🚀")
            
        else:
            print(f"❌ API Error: {response.status_code}")
            
    except requests.exceptions.ConnectionError:
        print("❌ API is not running")
        print()
        print("🚀 TO START IT:")
        print("   1. Open PowerShell/CMD")
        print("   2. Run: cd 'C:\\Users\\rohit\\OneDrive\\Desktop\\mlops\\nexus'")
        print("   3. Run: python -m uvicorn nexus.api.main:app --host 0.0.0.0 --port 8000 --reload")
        print("   4. Wait for 'Application startup complete'")
        
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    check_api_status()
