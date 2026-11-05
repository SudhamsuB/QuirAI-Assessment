"""Task 1: official MCP SDK server on stdio; stdout belongs to the SDK."""
import asyncio
import json
import logging
import sys

from mcp.server import Server, ServerRequestContext
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, CallToolRequestParams, CallToolResult, ListToolsResult, PaginatedRequestParams
from mcp.shared.exceptions import MCPError
from pydantic import BaseModel, ConfigDict, Field, ValidationError, StrictStr, field_validator

logging.basicConfig(stream=sys.stderr, level=logging.INFO)
log = logging.getLogger(__name__)

class CustomerInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    customer_id: StrictStr = Field(pattern=r"^CUST-[0-9]{5}$")

class RefundInput(CustomerInput):
    amount: float = Field(gt=0, allow_inf_nan=False, strict=True)
    reason: StrictStr = Field(min_length=10)

    @field_validator("reason")
    @classmethod
    def reason_is_meaningful(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 10:
            raise ValueError("reason must contain at least 10 non-whitespace characters")
        return cleaned

# Tool schemas include additionalProperties: false and validation constraints.
TOOLS = {
    "get_customer_record": CustomerInput,
    "trigger_refund": RefundInput,
}
RECORDS = {"CUST-00001": {"customer_id": "CUST-00001", "name": "Demo Customer", "status": "active"}}

async def list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
    return ListToolsResult(tools=[Tool(name=name, description=("Retrieve mock customer record" if name == "get_customer_record" else "Trigger a mock refund"),
                 input_schema=model.model_json_schema()) for name, model in TOOLS.items()])

async def call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
    name, arguments = params.name, params.arguments
    if name not in TOOLS:
        raise MCPError(-32602, "Unknown tool")
    try:
        args = TOOLS[name].model_validate(arguments if arguments is not None else {})
    except ValidationError as exc:
        # Sanitize: do not echo possibly sensitive input values or raw traceback.
        fields = sorted({".".join(map(str, e["loc"])) for e in exc.errors()})
        raise MCPError(-32602, "Invalid tool arguments: " + ", ".join(fields)) from None
    if name == "get_customer_record":
        result = RECORDS.get(args.customer_id, {"customer_id": args.customer_id, "status": "not_found"})
    else:
        # MOCK ONLY: do not connect to financial rails; real refunds need idempotency,
        # user confirmation, authorization and audit logging.
        result = {"status": "simulated", "customer_id": args.customer_id,
                  "amount": args.amount, "reason": args.reason}
    log.info("Tool invoked: %s", name)
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(result))])

server = Server("customer-operations", on_list_tools=list_tools, on_call_tool=call_tool)

async def main():
    log.info("MCP stdio server starting")
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
