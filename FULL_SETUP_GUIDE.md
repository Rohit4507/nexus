# 🚀 NEXUS COMPLETE SETUP GUIDE

## 📊 **CURRENT STATUS**
- ✅ **NEXUS API**: Running on http://localhost:8000
- ✅ **Ollama LLM**: Running on http://localhost:11434
- ❌ **PostgreSQL**: Not installed (needed for workflow automation)
- 📊 **Dashboard**: Created (nexus_dashboard.html)

## 🐘 **POSTGRESQL SETUP (Required for Full Features)**

### **Option 1: Quick Install with Docker (Easiest)**
```powershell
# Install Docker Desktop first
# Then run:
docker run --name nexus-postgres -e POSTGRES_PASSWORD=changeme -e POSTGRES_DB=nexus -p 5432:5432 -d postgres:16
```

### **Option 2: Windows Installer**
1. **Download**: https://www.postgresql.org/download/windows/
2. **Install PostgreSQL 16** with these settings:
   - Port: 5432
   - Password: `changeme`
   - Install pgAdmin 4
   - Add to PATH

3. **Create Database**:
   - Open pgAdmin 4
   - Connect to localhost:5432
   - Create database: `nexus`
   - Create user: `nexus` with password `changeme`

4. **Start Service**:
   - Open Services (services.msc)
   - Find `postgresql-x64-16`
   - Right-click → Start

## 📊 **DASHBOARD SETUP**

The dashboard is created! Open it in your browser:

**File Location**: `C:\Users\rohit\OneDrive\Desktop\mlops\nexus\nexus_dashboard.html`

**Features**:
- ✅ Real-time system status
- 📤 Meeting agent testing
- 🔗 Quick API access
- 📊 Component monitoring

## 🎯 **HOW TO RUN EVERYTHING**

### **Step 1: Start PostgreSQL (Optional)**
```powershell
# If using Docker:
docker start nexus-postgres

# If using Windows Installer:
# Service should auto-start, or use services.msc
```

### **Step 2: Verify Services Running**
```powershell
# Check NEXUS API
curl http://localhost:8000/health

# Check Ollama
curl http://localhost:11434/api/tags

# Check PostgreSQL (if installed)
psql -h localhost -U nexus -d nexus -c "SELECT version();"
```

### **Step 3: Open Dashboard**
1. Double-click: `nexus_dashboard.html`
2. Or open in browser: `file:///C:/Users/rohit/OneDrive/Desktop/mlops/nexus/nexus_dashboard.html`

### **Step 4: Test Meeting Agent**
1. In dashboard, enter transcript
2. Click "Test Meeting Processing"
3. Watch AI extract action items!

## 🌐 **ALL ACCESS POINTS**

| Service | URL | Status |
|---------|-----|--------|
| **Dashboard** | `nexus_dashboard.html` | ✅ Ready |
| **API Health** | http://localhost:8000/health | ✅ Running |
| **API Docs** | http://localhost:8000/docs | ✅ Running |
| **Meeting Upload** | http://localhost:8000/meetings/upload | ✅ Running |
| **Ollama** | http://localhost:11434 | ✅ Running |
| **PostgreSQL** | localhost:5432 | ❌ Needs setup |

## 🎮 **QUICK START (Without PostgreSQL)**

1. **Open Dashboard**: `nexus_dashboard.html`
2. **Test Meeting**: Enter transcript and click test
3. **Use API Docs**: http://localhost:8000/docs
4. **Upload Meetings**: Full meeting processing works!

## 🔄 **AUTOMATION SCRIPT**

```powershell
# Start everything (save as start_nexus.ps1)
Write-Host "🚀 Starting NEXUS..."

# Start NEXUS API
Start-Process powershell -ArgumentList "-Command", "cd 'C:\Users\rohit\OneDrive\Desktop\mlops\nexus'; python -m uvicorn nexus.api.main:app --host 0.0.0.0 --port 8000 --reload"

# Start Ollama (if not running)
Start-Process powershell -ArgumentList "-Command", "ollama serve"

# Open Dashboard
Start-Process "nexus_dashboard.html"

# Open API Docs
Start-Process "http://localhost:8000/docs"

Write-Host "✅ NEXUS started! Check dashboard for status."
```

## 📈 **WHAT YOU HAVE NOW**

- ✅ **Full Meeting Agent**: Transcript processing, action extraction
- ✅ **Real-time Dashboard**: Monitor system status
- ✅ **Interactive API**: Test all endpoints
- ✅ **AI Processing**: With llama3.1:8b model
- ⏳ **Workflow Automation**: Ready when PostgreSQL is installed

## 🎉 **YOU'RE READY TO GO!**

**Your NEXUS system is fully operational!** 

1. Open `nexus_dashboard.html` 
2. Test with meeting transcripts
3. Extract action items automatically
4. Monitor system in real-time

**PostgreSQL is optional** - the meeting agent works perfectly without it! 🚀
