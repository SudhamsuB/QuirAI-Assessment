"""Task 1 end-to-end MCP v2 stdio protocol check.

Run in the repository root after installing requirements. Uses the official
SDK client and server; SDK stdout framing fails if the server pollutes stdout.
"""
import asyncio
import sys

from mcp import Client, MCPError, StdioServerParameters


async def main() -> None:
    params = StdioServerParameters(command=sys.executable, args=["-m", "mcp_server"])
    async with Client(params, mode="legacy") as client:
        listing = await client.list_tools()
        names = {tool.name for tool in listing.tools}
        assert names == {"get_customer_record", "trigger_refund"}, names

        record = await client.call_tool("get_customer_record", {"customer_id": "CUST-00001"})
        assert not record.is_error
        assert any("Demo Customer" in block.text for block in record.content if block.type == "text")

        refund = await client.call_tool("trigger_refund", {
            "customer_id": "CUST-00001", "amount": 12.5,
            "reason": "Duplicate charge on order",
        })
        assert not refund.is_error
        assert any("simulated" in block.text for block in refund.content if block.type == "text")

        invalid_cases = [
            {"customer_id": "CUST-1234", "amount": -1, "reason": "too short"},
            {"customer_id": "CUST-00001", "amount": "10.50", "reason": "Duplicate charge"},
            {"customer_id": "CUST-00001", "amount": 5.0, "reason": "          "},
        ]
        for arguments in invalid_cases:
            try:
                await client.call_tool("trigger_refund", arguments)
            except MCPError as exc:
                assert exc.code == -32602, (exc.code, exc.message)
            else:
                raise AssertionError(f"Expected JSON-RPC -32602 for invalid arguments: {arguments!r}")

    print("PASS: MCP v2 stdio handshake, tools/list, tool execution, strict -32602 errors")


if __name__ == "__main__":
    asyncio.run(main())
