"""Test: contentedge_smart_chat — disabled tool placeholder."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tests.conftest import setup; setup()
import asyncio


async def main():
    print("=== smart_chat is currently disabled ===")
    print("This tool is kept for future use but not registered.")


if __name__ == "__main__":
    asyncio.run(main())
