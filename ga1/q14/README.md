# GA1 Q14 — MCP Challenge Server

A publicly reachable Model Context Protocol (MCP) server that exposes exactly one tool: `solve_challenge`.

## Tool

### `solve_challenge`

The tool accepts no required input properties.

For every tool call, the server reads the challenge from the HTTP header:

```text
X-Exam-Challenge