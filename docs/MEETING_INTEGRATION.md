# Meeting Agent Integration Documentation

## Overview

The Meeting Agent is now fully integrated into the NEXUS orchestrator and supports both audio file processing and direct transcript input. The agent can automatically trigger downstream workflows based on extracted action items.

## Features Implemented

### ✅ Dual Input Support
- **Audio Files**: WAV, MP3, M4A, FLAC, AAC formats supported
- **Transcripts**: Direct text input to skip transcription latency
- **Priority**: If both provided, transcript takes priority

### ✅ Enhanced S3 Storage
- **Production**: S3 bucket storage with metadata
- **Development**: Local filesystem fallback
- **Features**: 
  - Presigned URLs for immediate access
  - Proper content-type headers
  - Rich metadata for retrieval

### ✅ Downstream Workflow Triggers
- **Gated by Configuration**: `auto_trigger_workflows=true`
- **Confidence Threshold**: Configurable threshold (default: 0.8)
- **High-Impact Actions**: Requires approval if `approve_high_impact_actions=false`
- **Supported Workflows**: Procurement, Onboarding, Contract

### ✅ Full Orchestrator Integration
- **LangGraph Integration**: Wired into `execute_node`
- **API Endpoints**: Dedicated meeting upload endpoint
- **Database Persistence**: Full audit trail and action tracking

## API Usage

### 1. Upload Audio File

```bash
curl -X POST "http://localhost:8000/meetings/upload" \
  -F "audio_file=@meeting.wav" \
  -F "title=Team Standup" \
  -F 'participants=["Alice", "Bob", "Charlie"]' \
  -F "auto_trigger_workflows=true" \
  -F "trigger_confidence_threshold=0.8" \
  -F "created_by=manager@company.com"
```

### 2. Provide Transcript Only

```bash
curl -X POST "http://localhost:8000/meetings/upload" \
  -F "transcript=Alice will order new monitors. Bob will onboard the new engineer." \
  -F "title=Planning Meeting" \
  -F 'participants=["Alice", "Bob"]' \
  -F "auto_trigger_workflows=true"
```

### 3. Generic Workflow Trigger

```bash
curl -X POST "http://localhost:8000/workflows/trigger" \
  -H "Content-Type: application/json" \
  -d '{
    "workflow_type": "meeting",
    "payload": {
      "title": "Team Meeting",
      "transcript": "Alice needs to order equipment for the new team members.",
      "participants": ["Alice", "Bob"],
      "auto_trigger_workflows": true,
      "trigger_confidence_threshold": 0.7,
      "approve_high_impact_actions": true
    },
    "created_by": "team-lead@company.com"
  }'
```

## Configuration

### Environment Variables

```bash
# Meeting Recording Storage
MEETING_RECORDING_STORAGE=s3                    # local | s3
MEETING_RECORDING_LOCAL_DIR=data/meetings
MEETING_RECORDING_S3_BUCKET=company-meetings
MEETING_RECORDING_S3_PREFIX=recordings

# AWS S3 Configuration (if using S3)
AWS_ACCESS_KEY_ID=your-access-key
AWS_SECRET_ACCESS_KEY=your-secret-key
AWS_REGION=us-east-1
AWS_S3_ENDPOINT_URL=                    # Optional: for S3-compatible services

# Auto-Trigger Settings
MEETING_AUTO_TRIGGER_THRESHOLD=0.8     # Confidence threshold
```

## Workflow Inference Logic

The agent uses heuristic pattern matching to infer workflow types from action items:

### Procurement Triggers
- Keywords: `order`, `buy`, `purchase`, `procure`, `vendor`, `invoice`, `equipment`, `laptop`, `monitor`
- Confidence: 0.84
- High Impact: False

### Onboarding Triggers  
- Keywords: `onboard`, `new hire`, `access`, `provision`, `account`, `slack`, `email`, `training`
- Confidence: 0.86
- High Impact: False

### Contract Triggers
- Keywords: `contract`, `agreement`, `nda`, `msa`, `sow`, `docusign`, `legal`, `renewal`
- Confidence: 0.92
- High Impact: True

## Response Format

### Meeting Processing Result

```json
{
  "workflow_id": "uuid-string",
  "status": "completed",
  "meeting_title": "Team Standup",
  "audio_uploaded": true,
  "transcript_provided": false,
  "auto_trigger_workflows": true,
  "processing_result": {
    "summary": "Team discussed equipment needs and onboarding tasks",
    "action_items_count": 2,
    "decisions_count": 1,
    "assignments_count": 2,
    "downstream_workflows": [
      {
        "task": "Order 5 Dell monitors",
        "status": "triggered",
        "workflow_type": "procurement",
        "confidence": 0.84,
        "child_workflow_id": "child-uuid",
        "child_status": "completed"
      }
    ],
    "recording_storage": {
      "stored": true,
      "mode": "s3",
      "bucket": "company-meetings",
      "object_key": "recordings/workflow-uuid.wav",
      "presigned_url": "https://...",
      "file_size": 1048576
    }
  },
  "phases_completed": 4
}
```

## Database Schema

### Meetings Table
- `id`: UUID primary key
- `title`: Meeting title
- `transcript`: Full transcript text
- `summary`: AI-generated summary
- `participants`: JSON array of participants
- `recorded_at`: When meeting was recorded
- `processed_at`: When processing completed

### Meeting Actions Table
- `id`: UUID primary key
- `meeting_id`: Foreign key to meetings
- `action_text`: Description of action item
- `assignee`: Who is assigned (if any)
- `due_date`: When action is due
- `priority`: low|medium|high
- `status`: pending|completed|cancelled
- `workflow_id`: Link to downstream workflow (if triggered)

## Error Handling

### Transcription Failures
- Falls back to mock transcript for development
- Logs transcription errors appropriately
- Continues with action extraction using available text

### S3 Upload Failures
- Gracefully falls back to local storage
- Detailed error reporting in response
- Does not fail the entire workflow

### Downstream Workflow Failures
- Individual workflow failures don't affect meeting processing
- Failed workflows marked as `failed` status
- Success workflows marked as `completed` status

## Testing

### Run Integration Tests

```bash
# Quick integration test
python quick_test.py

# Full test suite (requires pytest)
pytest tests/test_meeting_integration.py -v
```

### Test Coverage

- ✅ Transcript-only processing
- ✅ Audio file processing  
- ✅ S3 storage configuration
- ✅ Downstream workflow triggering
- ✅ Workflow inference heuristics
- ✅ Full orchestrator integration

## Production Considerations

### Audio Processing
- **Whisper Integration**: Configure OpenAI API or self-hosted whisper.cpp
- **File Size Limits**: Consider maximum file size for uploads
- **Processing Time**: Audio transcription can take 30-60 seconds per hour

### S3 Configuration
- **IAM Permissions**: Ensure proper S3 access permissions
- **Bucket Policies**: Configure appropriate bucket policies
- **Cost Optimization**: Consider lifecycle policies for old recordings

### Performance
- **Async Processing**: All operations are fully async
- **Connection Pooling**: Database and HTTP clients use connection pooling
- **Memory Management**: Large transcripts are truncated for LLM processing

## Security

### File Upload Security
- **File Type Validation**: Only allowed audio formats accepted
- **Size Limits**: Configurable maximum file size
- **Temporary Storage**: Files cleaned up after processing

### Data Privacy
- **Transcript Storage**: Stored in PostgreSQL with proper access controls
- **Audio Files**: Optional S3 encryption with customer-managed keys
- **Audit Trail**: Complete audit logging of all actions

## Monitoring

### Metrics Available
- Meeting processing volume
- Transcription success/failure rates
- Downstream workflow trigger rates
- Storage usage (local vs S3)
- Processing latency metrics

### Health Checks
- `/health` - Overall system health
- `/health/tools` - Individual tool health including S3 connectivity
- `/meetings/{workflow_id}` - Individual meeting status

## Future Enhancements

### Planned Features
- **Speaker Diarization**: Identify individual speakers
- **Real-time Processing**: Stream audio for live meetings
- **Multi-language Support**: Transcription in multiple languages
- **Advanced Action Parsing**: More sophisticated NLP for action extraction
- **Calendar Integration**: Auto-schedule follow-up meetings

### Integration Opportunities
- **Zoom/Teams APIs**: Direct integration with meeting platforms
- **Calendar Systems**: Automatic meeting scheduling and recording
- **Notification Systems**: Enhanced Slack/Teams integration
- **CRM Integration**: Update customer records from meeting outcomes
