"""Test Meeting Agent integration with orchestrator."""

import pytest
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from nexus.agents.meeting import MeetingAgent
from nexus.agents.orchestrator import run_workflow
from nexus.config import get_settings


@pytest.fixture
def mock_db_session():
    """Mock database session for testing."""
    session = AsyncMock()
    session.execute = AsyncMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    return session


@pytest.fixture
def mock_tools():
    """Mock tool registry."""
    tools = MagicMock()
    tools.has = MagicMock(return_value=False)  # No tools by default
    tools.close_all = AsyncMock()
    return tools


@pytest.fixture
def mock_llm():
    """Mock LLM router."""
    llm = AsyncMock()
    llm.generate = AsyncMock(return_value={
        "content": """{
            "summary": "Test meeting summary",
            "decisions": ["Decision 1"],
            "action_items": [
                {"task": "Test task", "assignee": "test@example.com", "due_date": "2024-01-01", "priority": "high"}
            ],
            "open_questions": ["Question 1"],
            "participants": ["Alice", "Bob"],
            "sentiment": "positive",
            "follow_up_required": true
        }"""
    })
    llm.close = AsyncMock()
    return llm


@pytest.fixture
def meeting_agent(mock_tools, mock_llm, mock_db_session):
    """Create MeetingAgent instance with mocked dependencies."""
    return MeetingAgent(
        tool_registry=mock_tools,
        llm_router=mock_llm,
        audit_logger=AsyncMock(),
        db_session=mock_db_session,
    )


class TestMeetingAgentIntegration:
    """Test Meeting Agent integration scenarios."""

    @pytest.mark.asyncio
    async def test_meeting_agent_with_transcript_only(self, meeting_agent):
        """Test meeting processing with transcript only (no audio)."""
        metadata = {
            "workflow_id": "test-workflow-123",
            "title": "Test Meeting",
            "participants": ["Alice", "Bob"],
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "auto_trigger_workflows": True,
            "trigger_confidence_threshold": 0.8,
            "approve_high_impact_actions": False,
            "created_by": "test@example.com",
        }

        result = await meeting_agent.process(
            audio_path=None,
            transcript_text="This is a test transcript. Alice will order new monitors.",
            meeting_metadata=metadata,
        )

        assert result["status"] == "completed"
        assert result["workflow_id"] == "test-workflow-123"
        assert "summary" in result
        assert "action_items" in result
        assert "decisions" in result
        assert result["recording_storage"]["stored"] is False
        assert result["recording_storage"]["mode"] == "none"

    @pytest.mark.asyncio
    async def test_meeting_agent_with_audio_file(self, meeting_agent, tmp_path):
        """Test meeting processing with audio file."""
        # Create a fake audio file
        audio_file = tmp_path / "test_meeting.wav"
        audio_file.write_text("fake audio content")

        metadata = {
            "workflow_id": "test-workflow-456",
            "title": "Test Meeting with Audio",
            "participants": ["Alice", "Bob"],
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "auto_trigger_workflows": False,
            "created_by": "test@example.com",
        }

        result = await meeting_agent.process(
            audio_path=str(audio_file),
            transcript_text=None,
            meeting_metadata=metadata,
        )

        assert result["status"] == "completed"
        assert result["workflow_id"] == "test-workflow-456"
        assert result["recording_storage"]["stored"] is True
        assert result["recording_storage"]["mode"] == "local"

    @pytest.mark.asyncio
    async def test_downstream_workflow_triggering(self, meeting_agent, mock_db_session):
        """Test downstream workflow triggering from meeting actions."""
        # Mock the run_workflow function to avoid actual execution
        with pytest.mock.patch('nexus.agents.meeting.run_workflow') as mock_run:
            mock_run.return_value = {
                "status": "completed",
                "workflow_id": "child-workflow-123"
            }

            metadata = {
                "workflow_id": "parent-workflow-789",
                "auto_trigger_workflows": True,
                "trigger_confidence_threshold": 0.7,  # Lower threshold
                "approve_high_impact_actions": True,
                "created_by": "test@example.com",
            }

            action_items = [
                {"task": "Order 5 Dell monitors", "assignee": "procurement@company.com", "priority": "high"},
                {"task": "Onboard new engineer", "assignee": "hr@company.com", "priority": "medium"},
            ]

            downstream = await meeting_agent._maybe_trigger_downstream_workflows(
                workflow_id="parent-workflow-789",
                action_items=action_items,
                meeting_metadata=metadata,
            )

            assert len(downstream) == 2
            assert downstream[0]["status"] == "triggered"
            assert downstream[0]["workflow_type"] == "procurement"
            assert downstream[1]["status"] == "triggered"
            assert downstream[1]["workflow_type"] == "onboarding"

    @pytest.mark.asyncio
    async def test_workflow_inference_heuristics(self, meeting_agent):
        """Test workflow type inference from action items."""
        # Test procurement inference
        item = {"task": "Order new laptops for the team"}
        result = meeting_agent._infer_workflow_from_action_item(item)
        assert result["workflow_type"] == "procurement"
        assert result["confidence"] > 0.8
        assert result["high_impact"] is False

        # Test onboarding inference
        item = {"task": "Set up email and Slack for new hire"}
        result = meeting_agent._infer_workflow_from_action_item(item)
        assert result["workflow_type"] == "onboarding"
        assert result["confidence"] > 0.8

        # Test contract inference
        item = {"task": "Prepare NDA for vendor"}
        result = meeting_agent._infer_workflow_from_action_item(item)
        assert result["workflow_type"] == "contract"
        assert result["high_impact"] is True

        # Test no match
        item = {"task": "Schedule team building event"}
        result = meeting_agent._infer_workflow_from_action_item(item)
        assert result["workflow_type"] is None
        assert result["confidence"] == 0.0

    @pytest.mark.asyncio
    async def test_s3_storage_configuration(self, meeting_agent, tmp_path):
        """Test S3 storage with proper configuration."""
        # Mock S3 settings
        meeting_agent.settings.meeting_recording_storage = "s3"
        meeting_agent.settings.meeting_recording_s3_bucket = "test-bucket"
        meeting_agent.settings.aws_access_key_id = "test-key"
        meeting_agent.settings.aws_secret_access_key = "test-secret"
        meeting_agent.settings.aws_region = "us-east-1"

        # Create fake audio file
        audio_file = tmp_path / "test_s3.wav"
        audio_file.write_text("fake audio content")

        metadata = {
            "workflow_id": "s3-test-workflow",
            "title": "S3 Test Meeting",
        }

        # Mock boto3 to avoid actual S3 call
        with pytest.mock.patch('boto3.client') as mock_boto3:
            mock_s3 = AsyncMock()
            mock_boto3.return_value = mock_s3
            mock_s3.generate_presigned_url.return_value = "https://test-bucket.s3.amazonaws.com/test-file"

            result = await meeting_agent.process(
                audio_path=str(audio_file),
                transcript_text=None,
                meeting_metadata=metadata,
            )

            assert result["recording_storage"]["mode"] == "s3"
            assert result["recording_storage"]["bucket"] == "test-bucket"
            assert "presigned_url" in result["recording_storage"]


@pytest.mark.asyncio
async def test_full_orchestrator_integration(mock_db_session):
    """Test full orchestrator integration with meeting workflow."""
    payload = {
        "title": "Integration Test Meeting",
        "participants": ["Alice", "Bob"],
        "transcript": "Alice needs to order new monitors for the team. Bob will handle onboarding.",
        "auto_trigger_workflows": True,
        "trigger_confidence_threshold": 0.7,
        "approve_high_impact_actions": True,
        "created_by": "integration@test.com",
    }

    # Mock all external dependencies
    with pytest.mock.patch('nexus.agents.orchestrator.ToolRegistry.from_settings') as mock_tools:
        with pytest.mock.patch('nexus.agents.orchestrator.LLMRouter') as mock_llm:
            with pytest.mock.patch('nexus.agents.orchestrator.AuditLogger') as mock_audit:
                # Setup mocks
                mock_tools.return_value = MagicMock()
                mock_tools.return_value.has = MagicMock(return_value=False)
                mock_tools.return_value.close_all = AsyncMock()
                
                mock_llm.return_value = AsyncMock()
                mock_llm.return_value.generate = AsyncMock(return_value={
                    "content": """{
                        "summary": "Integration test meeting",
                        "decisions": ["Order monitors"],
                        "action_items": [
                            {"task": "Order monitors", "assignee": "alice@company.com", "priority": "high"}
                        ],
                        "open_questions": [],
                        "participants": ["Alice", "Bob"],
                        "sentiment": "positive",
                        "follow_up_required": false
                    }"""
                })
                mock_llm.return_value.close = AsyncMock()
                
                mock_audit.return_value = AsyncMock()
                mock_audit.return_value.log_action = AsyncMock()

                # Mock downstream workflow execution
                with pytest.mock.patch('nexus.agents.meeting.run_workflow') as mock_run:
                    mock_run.return_value = {
                        "status": "completed",
                        "workflow_id": "child-123"
                    }

                    result = await run_workflow(
                        workflow_type="meeting",
                        payload=payload,
                        created_by="integration@test.com",
                        workflow_id="integration-test-123",
                        db_session=mock_db_session,
                    )

                    assert result["status"] == "completed"
                    assert result["workflow_type"] == "meeting"
                    assert len(result["agent_outputs"]) > 0
                    
                    # Check that meeting agent was called
                    execute_output = None
                    for output in result["agent_outputs"]:
                        if output.get("agent") == "meeting_executor":
                            execute_output = output
                            break
                    
                    assert execute_output is not None
                    assert execute_output["phase"] == "execute"


if __name__ == "__main__":
    # Run a quick integration test
    async def quick_test():
        """Quick integration test without pytest."""
        print("🧪 Running Meeting Agent integration test...")
        
        # Mock dependencies
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock()
        mock_db.flush = AsyncMock()
        
        mock_tools = MagicMock()
        mock_tools.has = MagicMock(return_value=False)
        mock_tools.close_all = AsyncMock()
        
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(return_value={
            "content": """{
                "summary": "Quick test meeting",
                "decisions": ["Test decision"],
                "action_items": [
                    {"task": "Test task", "assignee": "test@example.com", "priority": "medium"}
                ],
                "open_questions": [],
                "participants": ["Test User"],
                "sentiment": "neutral",
                "follow_up_required": false
            }"""
        })
        mock_llm.close = AsyncMock()
        
        agent = MeetingAgent(
            tool_registry=mock_tools,
            llm_router=mock_llm,
            audit_logger=AsyncMock(),
            db_session=mock_db,
        )
        
        metadata = {
            "workflow_id": "quick-test-123",
            "title": "Quick Test Meeting",
            "participants": ["Test User"],
            "auto_trigger_workflows": False,
            "created_by": "test@example.com",
        }
        
        result = await agent.process(
            audio_path=None,
            transcript_text="This is a quick test transcript for integration testing.",
            meeting_metadata=metadata,
        )
        
        print(f"✅ Meeting Agent test completed: {result['status']}")
        print(f"   Summary: {result['summary']}")
        print(f"   Action items: {len(result['action_items'])}")
        print(f"   Decisions: {len(result['decisions'])}")
        
        # Test workflow inference
        test_items = [
            {"task": "Order new laptops"},
            {"task": "Set up accounts for new hire"},
            {"task": "Prepare contract agreement"},
            {"task": "Schedule team lunch"},
        ]
        
        print("\n🔍 Testing workflow inference:")
        for item in test_items:
            inference = agent._infer_workflow_from_action_item(item)
            print(f"   '{item['task']}' -> {inference['workflow_type']} (confidence: {inference['confidence']:.2f})")
        
        print("\n✅ All tests completed successfully!")
    
    asyncio.run(quick_test())
