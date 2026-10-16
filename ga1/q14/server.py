import hashlib

from mcp.server import Server, ServerRequestContext
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import (
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
    Tool,
)

EMAIL = "24f3001989@ds.study.iitm.ac.in"

SOLVE_CHALLENGE = Tool(
    name="solve_challenge",
    description="Solve the current exam challenge.",
      input_schema={
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
)


async def list_tools(
    ctx: ServerRequestContext,
    params: PaginatedRequestParams | None,
) -> ListToolsResult:
    return ListToolsResult(tools=[SOLVE_CHALLENGE])


async def call_tool(
    ctx: ServerRequestContext,
    params: CallToolRequestParams,
) -> CallToolResult:
    if params.name != "solve_challenge":
        raise ValueError(f"Unknown tool: {params.name}")

    headers = ctx.request.headers if ctx.request else {}

    challenge = headers.get("X-Exam-Challenge")

    if not challenge:
        raise ValueError("Missing X-Exam-Challenge header")

    value = f"{challenge}:{EMAIL}"
    digest = hashlib.sha256(value.encode()).hexdigest()

    return CallToolResult(
        content=[
            TextContent(
                type="text",
                text=digest[:16],
            )
        ]
    )


server = Server(
    "TDS Challenge Server",
    on_list_tools=list_tools,
    on_call_tool=call_tool,
)


app = server.streamable_http_app(
    stateless_http=True,
    transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection = False
    )
)


if __name__ == "__main__":
    import os
    import uvicorn

    port  = int(os.environ.get("PORT", '8000'))
    uvicorn.run(app, host="127.0.0.1", port=port)