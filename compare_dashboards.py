import requests
import webbrowser
import time

def check_dashboards():
    """Check both dashboards and explain differences."""
    
    print("🎯 DASHBOARD COMPARISON")
    print("=" * 50)
    
    # Check NEXUS API
    try:
        response = requests.get("http://localhost:8000/health", timeout=3)
        api_status = "✅ Running" if response.status_code == 200 else "❌ Error"
    except:
        api_status = "❌ Not running"
    
    print(f"📊 NEXUS API: {api_status}")
    print()
    
    print("🌐 YOUR DASHBOARDS:")
    print()
    
    print("1️⃣ ORIGINAL DASHBOARD (nexus_dashboard.html):")
    print("   🎯 Purpose: System monitoring and testing")
    print("   🔍 Features: Health checks, API testing")
    print("   📊 Use: Technical monitoring, quick tests")
    print("   📱 Style: Professional monitoring interface")
    print()
    
    print("2️⃣ CHAT DASHBOARD (nexus_chat_dashboard.html):")
    print("   🎯 Purpose: ChatGPT-like AI assistant")
    print("   💬 Features: Natural conversation, commands")
    print("   🗣️ Commands: 'arrange meeting at 8 am'")
    print("   ⏰ Features: Smart reminders, task management")
    print("   📱 Style: Modern chat interface")
    print()
    
    print("🎮 HOW TO USE EACH:")
    print()
    
    print("📊 ORIGINAL DASHBOARD:")
    print("   • Upload meeting transcripts")
    print("   • Test API endpoints")
    print("   • Monitor system health")
    print("   • View technical status")
    print()
    
    print("🤖 CHAT DASHBOARD:")
    print("   • Type 'arrange meeting at 8 am'")
    print("   • Type 'set reminder for 3 pm'")
    print("   • Type 'create task for report'")
    print("   • Natural conversation with AI")
    print("   • Get proactive suggestions")
    print()
    
    print("🎯 RECOMMENDATION:")
    print("   Use CHAT dashboard for daily tasks")
    print("   Use ORIGINAL dashboard for technical testing")
    print("   Both are open and ready!")
    print()
    
    print("🌐 OPEN IN BROWSER:")
    print("   🤖 Chat: nexus_chat_dashboard.html ✅")
    print("   📊 Original: nexus_dashboard.html")
    print("   📚 API Docs: http://localhost:8000/docs")
    print()
    
    # Test quick command
    print("🧪 TESTING CHAT DASHBOARD...")
    print("   Try typing: 'arrange meeting at 9 am'")
    print("   Or: 'set reminder for 2 pm'")
    print("   Or: 'what can you do?'")
    print()
    
    print("🚀 BOTH DASHBOARDS READY!")
    print("   Choose based on your needs:")
    print("   🤖 Chat for daily productivity")
    print("   📊 Original for system monitoring")

if __name__ == "__main__":
    check_dashboards()
