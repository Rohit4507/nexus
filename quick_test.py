import asyncio
import sys
sys.path.append('.')

from unittest.mock import AsyncMock, MagicMock
from nexus.agents.meeting import MeetingAgent

async def quick_test():
    print('🧪 Running Meeting Agent integration test...')
    
    # Mock dependencies
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()
    mock_db.flush = AsyncMock()
    
    mock_tools = MagicMock()
    mock_tools.has = MagicMock(return_value=False)
    mock_tools.close_all = AsyncMock()
    
    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(return_value={
        'content': '''{
            "summary": "Quick test meeting",
            "decisions": ["Test decision"],
            "action_items": [
                {"task": "Test task", "assignee": "test@example.com", "priority": "medium"}
            ],
            "open_questions": [],
            "participants": ["Test User"],
            "sentiment": "neutral",
            "follow_up_required": false
        }'''
    })
    mock_llm.close = AsyncMock()
    
    agent = MeetingAgent(
        tool_registry=mock_tools,
        llm_router=mock_llm,
        audit_logger=AsyncMock(),
        db_session=mock_db,
    )
    
    metadata = {
        'workflow_id': 'quick-test-123',
        'title': 'Quick Test Meeting',
        'participants': ['Test User'],
        'auto_trigger_workflows': False,
        'created_by': 'test@example.com',
    }
    
    result = await agent.process(
        audio_path=None,
        transcript_text='This is a quick test transcript for integration testing.',
        meeting_metadata=metadata,
    )
    
    print(f'✅ Meeting Agent test completed: {result["status"]}')
    print(f'   Summary: {result["summary"]}')
    print(f'   Action items: {len(result["action_items"])}')
    print(f'   Decisions: {len(result["decisions"])}')
    
    # Test workflow inference
    test_items = [
        {'task': 'Order new laptops'},
        {'task': 'Set up accounts for new hire'},
        {'task': 'Prepare contract agreement'},
        {'task': 'Schedule team lunch'},
    ]
    
    print('\n🔍 Testing workflow inference:')
    for item in test_items:
        inference = agent._infer_workflow_from_action_item(item)
        print(f'   "{item["task"]}" -> {inference["workflow_type"]} (confidence: {inference["confidence"]:.2f})')
    
    print('\n✅ All tests completed successfully!')

if __name__ == "__main__":
    asyncio.run(quick_test())
