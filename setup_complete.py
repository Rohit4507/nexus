"""
NEXUS COMPLETE SETUP - Dashboard + PostgreSQL + Full System
"""

import os
import sys
import subprocess
import time
import requests

def check_component_status():
    """Check status of all components."""
    
    print("🔍 CHECKING SYSTEM COMPONENTS")
    print("=" * 50)
    
    # Check NEXUS API
    try:
        response = requests.get("http://localhost:8000/health", timeout=3)
        if response.status_code == 200:
            print("✅ NEXUS API: Running")
        else:
            print("❌ NEXUS API: Not responding correctly")
    except:
        print("❌ NEXUS API: Not running")
    
    # Check Ollama
    try:
        response = requests.get("http://localhost:11434/api/tags", timeout=3)
        if response.status_code == 200:
            models = response.json().get("models", [])
            print(f"✅ Ollama: Running with {len(models)} models")
        else:
            print("❌ Ollama: Not responding")
    except:
        print("❌ Ollama: Not running")
    
    # Check PostgreSQL
    try:
        result = subprocess.run(['psql', '--version'], capture_output=True, text=True, timeout=5)
        print(f"✅ PostgreSQL: Installed ({result.stdout.strip()})")
    except (subprocess.TimeoutExpired, FileNotFoundError):
        print("❌ PostgreSQL: Not installed")
    
    # Check if PostgreSQL service is running
    try:
        result = subprocess.run(['net', 'start'], capture_output=True, text=True, timeout=5)
        if 'postgresql' in result.stdout.lower() or 'postgres' in result.stdout.lower():
            print("✅ PostgreSQL Service: Running")
        else:
            print("❌ PostgreSQL Service: Not running")
    except:
        print("❌ PostgreSQL Service: Check failed")
    
    print()

def setup_postgresql():
    """Guide for PostgreSQL setup."""
    
    print("🐘 POSTGRESQL SETUP GUIDE")
    print("=" * 50)
    
    print("📥 STEP 1: Download PostgreSQL")
    print("   1. Go to: https://www.postgresql.org/download/windows/")
    print("   2. Download PostgreSQL 16 (latest stable)")
    print("   3. Run installer as Administrator")
    print()
    
    print("⚙️ STEP 2: Install PostgreSQL")
    print("   1. Use default port: 5432")
    print("   2. Set superuser password: 'changeme'")
    print("   3. Install pgAdmin 4 (included)")
    print("   4. Add PostgreSQL to PATH")
    print()
    
    print("🗄️ STEP 3: Create Database")
    print("   1. Open pgAdmin 4")
    print("   2. Connect to server (localhost:5432)")
    print("   3. Create database: 'nexus'")
    print("   4. Create user: 'nexus' with password 'changeme'")
    print()
    
    print("🚀 STEP 4: Start PostgreSQL Service")
    print("   1. Open Services (services.msc)")
    print("   2. Find 'postgresql-x64-16'")
    print("   3. Right-click → Start")
    print()
    
    input("Press Enter after PostgreSQL is installed and running...")

def create_dashboard():
    """Create a simple dashboard for NEXUS."""
    
    dashboard_html = """
<!DOCTYPE html>
<html>
<head>
    <title>NEXUS Dashboard</title>
    <meta charset="utf-8">
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }
        .header { background: #2c3e50; color: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; }
        .card { background: white; padding: 20px; margin: 10px 0; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .status { display: inline-block; padding: 5px 15px; border-radius: 20px; font-weight: bold; }
        .online { background: #27ae60; color: white; }
        .offline { background: #e74c3c; color: white; }
        .endpoint { background: #3498db; color: white; padding: 10px; border-radius: 5px; margin: 5px 0; }
        button { background: #3498db; color: white; border: none; padding: 10px 20px; border-radius: 5px; cursor: pointer; margin: 5px; }
        button:hover { background: #2980b9; }
        .test-area { background: #ecf0f1; padding: 15px; border-radius: 5px; margin: 10px 0; }
        textarea { width: 100%; height: 100px; margin: 10px 0; padding: 10px; border: 1px solid #bdc3c7; border-radius: 5px; }
    </style>
</head>
<body>
    <div class="header">
        <h1>🚀 NEXUS Dashboard</h1>
        <p>Enterprise Multi-Agent System - Real-time Monitoring</p>
    </div>
    
    <div class="card">
        <h2>🔍 System Status</h2>
        <div id="status-container">
            <p>Checking system components...</p>
        </div>
    </div>
    
    <div class="card">
        <h2>📤 Test Meeting Agent</h2>
        <div class="test-area">
            <p>Enter meeting transcript to test AI processing:</p>
            <textarea id="transcript" placeholder="Alice: We need to order monitors. Bob: I'll handle it."></textarea>
            <button onclick="testMeeting()">🧪 Test Meeting Processing</button>
            <div id="meeting-result"></div>
        </div>
    </div>
    
    <div class="card">
        <h2>🔗 API Endpoints</h2>
        <div class="endpoint">Health: <a href="http://localhost:8000/health" target="_blank">http://localhost:8000/health</a></div>
        <div class="endpoint">API Docs: <a href="http://localhost:8000/docs" target="_blank">http://localhost:8000/docs</a></div>
        <div class="endpoint">Meetings: <a href="http://localhost:8000/meetings/upload" target="_blank">http://localhost:8000/meetings/upload</a></div>
        <div class="endpoint">Workflows: <a href="http://localhost:8000/workflows" target="_blank">http://localhost:8000/workflows</a></div>
    </div>
    
    <div class="card">
        <h2>📊 Quick Actions</h2>
        <button onclick="refreshStatus()">🔄 Refresh Status</button>
        <button onclick="window.open('http://localhost:8000/docs', '_blank')">📚 Open API Docs</button>
        <button onclick="window.open('http://localhost:11434', '_blank')">🤖 Open Ollama</button>
    </div>
    
    <script>
        async function checkStatus() {
            const statusContainer = document.getElementById('status-container');
            statusContainer.innerHTML = '<p>Checking...</p>';
            
            try {
                // Check NEXUS API
                const apiResponse = await fetch('http://localhost:8000/health');
                const apiStatus = apiResponse.ok ? 
                    '<span class="status online">✅ NEXUS API: Online</span>' : 
                    '<span class="status offline">❌ NEXUS API: Offline</span>';
                
                // Check Ollama
                const ollamaResponse = await fetch('http://localhost:11434/api/tags');
                const ollamaStatus = ollamaResponse.ok ? 
                    '<span class="status online">✅ Ollama: Online</span>' : 
                    '<span class="status offline">❌ Ollama: Offline</span>';
                
                statusContainer.innerHTML = apiStatus + '<br>' + ollamaStatus;
                
            } catch (error) {
                statusContainer.innerHTML = '<span class="status offline">❌ Connection Failed</span>';
            }
        }
        
        async function testMeeting() {
            const transcript = document.getElementById('transcript').value;
            const resultDiv = document.getElementById('meeting-result');
            
            if (!transcript.trim()) {
                resultDiv.innerHTML = '<p style="color: red;">Please enter a transcript</p>';
                return;
            }
            
            resultDiv.innerHTML = '<p>🔄 Processing meeting...</p>';
            
            try {
                const formData = new FormData();
                formData.append('transcript', transcript);
                formData.append('title', 'Dashboard Test Meeting');
                formData.append('participants', '["User", "Assistant"]');
                formData.append('auto_trigger_workflows', 'false');
                formData.append('created_by', 'dashboard@nexus.local');
                
                const response = await fetch('http://localhost:8000/meetings/upload', {
                    method: 'POST',
                    body: formData
                });
                
                if (response.ok) {
                    const result = await response.json();
                    resultDiv.innerHTML = `
                        <h3>✅ Processing Successful!</h3>
                        <p><strong>Workflow ID:</strong> ${result.workflow_id}</p>
                        <p><strong>Status:</strong> ${result.status}</p>
                        <p><strong>Processing Result:</strong></p>
                        <pre>${JSON.stringify(result.processing_result, null, 2)}</pre>
                    `;
                } else {
                    resultDiv.innerHTML = `<p style="color: red;">❌ Error: ${response.status}</p>`;
                }
                
            } catch (error) {
                resultDiv.innerHTML = `<p style="color: red;">❌ Error: ${error.message}</p>`;
            }
        }
        
        function refreshStatus() {
            checkStatus();
        }
        
        // Auto-refresh status every 30 seconds
        setInterval(checkStatus, 30000);
        
        // Initial status check
        checkStatus();
    </script>
</body>
</html>
    """
    
    with open("nexus_dashboard.html", "w", encoding="utf-8") as f:
        f.write(dashboard_html)
    
    print("📊 Dashboard created: nexus_dashboard.html")
    print("   Open in browser: file:///path/to/nexus_dashboard.html")

def start_all_services():
    """Start all NEXUS services."""
    
    print("🚀 STARTING ALL NEXUS SERVICES")
    print("=" * 50)
    
    print("1. ✅ NEXUS API should be running on http://localhost:8000")
    print("2. ✅ Ollama should be running on http://localhost:11434")
    print("3. ❌ PostgreSQL needs to be started manually")
    print()
    
    print("📊 Dashboard: nexus_dashboard.html")
    print("📚 API Docs: http://localhost:8000/docs")
    print()
    
    input("Press Enter to open dashboard...")

def main():
    """Main setup function."""
    
    print("🎯 NEXUS COMPLETE SETUP")
    print("=" * 50)
    
    # Check current status
    check_component_status()
    
    print("\n" + "=" * 50)
    print("📋 SETUP OPTIONS:")
    print("1. Setup PostgreSQL (for workflow automation)")
    print("2. Create Dashboard (for monitoring)")
    print("3. Start All Services")
    print("4. Check Status Only")
    print()
    
    choice = input("Select option (1-4): ").strip()
    
    if choice == "1":
        setup_postgresql()
    elif choice == "2":
        create_dashboard()
    elif choice == "3":
        start_all_services()
    elif choice == "4":
        check_component_status()
    else:
        print("Invalid choice")

if __name__ == "__main__":
    main()
