# 🚀 NEXUS API - RUNNING GUIDE

## ✅ HOW TO KNOW API IS RUNNING

### Method 1: Health Check (PowerShell)
```powershell
Invoke-RestMethod -Uri http://localhost:8000/health
```

**You should see:**
```
status  version environment
------  ------- -----------
healthy 0.1.0   development
```

### Method 2: Browser Test
Open your browser and go to:
- http://localhost:8000/health (should show JSON)
- http://localhost:8000/docs (should show Swagger UI)

## 🌐 HOW TO USE THE API

### Step 1: Open API Documentation
Go to: **http://localhost:8000/docs**

This shows you all available endpoints with interactive testing!

### Step 2: Test Meeting Agent (Easiest Method)

#### Using Web Interface:
1. Go to http://localhost:8000/docs
2. Find `POST /meetings/upload` 
3. Click "Try it out"
4. Fill in:
   - transcript: `Alice will order new monitors. Bob will handle onboarding.`
   - title: `Test Meeting`
   - participants: `["Alice", "Bob"]`
   - auto_trigger_workflows: `false`
   - created_by: `test@example.com`
5. Click "Execute"

#### Using PowerShell:
```powershell
$body = @{
    transcript = "Alice will order new monitors. Bob will handle onboarding."
    title = "Test Meeting"
    participants = '["Alice", "Bob"]'
    auto_trigger_workflows = "false"
    created_by = "test@example.com"
}

Invoke-RestMethod -Uri http://localhost:8000/meetings/upload -Method POST -Form $body
```

### Step 3: Check Results
The API returns:
- `workflow_id`: Unique ID for your meeting
- `status`: Processing status
- `processing_result`: Summary and action items
- `downstream_workflows`: Any automated workflows triggered

## 📋 ALL AVAILABLE ENDPOINTS

- **Health**: http://localhost:8000/health
- **Workflows**: http://localhost:8000/workflows
- **Meeting Upload**: http://localhost:8000/meetings/upload
- **API Docs**: http://localhost:8000/docs
- **Metrics**: http://localhost:8000/metrics

## 🛠️ STARTING THE API (if needed)

```powershell
cd "C:\Users\rohit\OneDrive\Desktop\mlops\nexus"
python -m uvicorn nexus.api.main:app --host 0.0.0.0 --port 8000 --reload
```

**Look for:**
```
INFO:     Started server process [xxxx]
INFO:     Application startup complete.
```

## 🎯 QUICK TEST

Run this in PowerShell:
```powershell
Invoke-RestMethod -Uri http://localhost:8000/health
```

If you see the health response, the API is RUNNING and ready to use! 🚀

## 📱 What You Can Do

1. **Upload meeting transcripts** for AI analysis
2. **Extract action items** automatically  
3. **Trigger downstream workflows** (procurement, onboarding, contracts)
4. **Monitor processing status** in real-time
5. **View API metrics** and health status

The NEXUS Meeting Agent is now fully operational with all RTX 3050 optimizations!
