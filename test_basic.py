import asyncio
import httpx

async def test_simple_health():
    """Test basic health endpoint without database dependencies."""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get("http://localhost:8000/health")
            if response.status_code == 200:
                data = response.json()
                print("✅ Health check passed")
                print(f"   Status: {data.get('status')}")
                print(f"   Version: {data.get('version')}")
                print(f"   Environment: {data.get('environment')}")
                return True
            else:
                print(f"❌ Health check failed: {response.status_code}")
                return False
        except Exception as e:
            print(f"❌ Health check error: {str(e)}")
            return False

async def test_tools_health():
    """Test tools health endpoint."""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get("http://localhost:8000/health/tools")
            if response.status_code == 200:
                data = response.json()
                print("✅ Tools health check passed")
                print(f"   Overall status: {data.get('status')}")
                tools = data.get('tools', {})
                for tool_name, tool_status in tools.items():
                    print(f"   {tool_name}: {'✅' if tool_status.get('healthy') else '❌'}")
                return True
            else:
                print(f"❌ Tools health check failed: {response.status_code}")
                return False
        except Exception as e:
            print(f"❌ Tools health check error: {str(e)}")
            return False

async def main():
    print("🧪 Testing NEXUS with all fixes applied...")
    print()
    
    # Test health first
    if not await test_simple_health():
        return
    
    print()
    
    # Test tools health
    if not await test_tools_health():
        return
    
    print()
    print("🎉 Basic tests passed! NEXUS server is running correctly with all fixes.")
    print("   (Full workflow tests require PostgreSQL database)")

if __name__ == "__main__":
    asyncio.run(main())
