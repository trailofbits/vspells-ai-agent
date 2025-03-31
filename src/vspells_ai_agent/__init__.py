from . import jsonrpc
from . import prompts
from . import lsp_client

import asyncio
from itertools import count
from typing import TypedDict, Literal
from dataclasses import dataclass

from pydantic_ai import Agent, RunContext, ModelRetry
from pydantic_ai.common_tools.duckduckgo import duckduckgo_search_tool

import logfire

logfire.configure(scrubbing=False)
logfire.instrument_anthropic()


class Position(TypedDict):
    line: int
    character: int


class Range(TypedDict):
    start: Position
    end: Position


class FunctionModel(TypedDict):
    category: Literal["sink", "source", "parser", "nonparser"]
    return_type: Literal["data", "nodata", "maybedata"]
    arguments: list[Literal["data", "nodata", "maybedata"]]
    is_stdlib: bool


class Response(FunctionModel):
    reasoning: str


@dataclass(kw_only=True)
class Context:
    lsp: jsonrpc.JsonRpcClient
    expected_arg_no: int


_client: jsonrpc.JsonRpcClient
_clangd: jsonrpc.JsonRpcClient
_agent: Agent[Context, Response]


async def input_request(
    *,
    functionName: str,
    numberOfArguments: int,
    filePath: str | None = None,
    range: Range | None = None,
) -> FunctionModel:
    global _agent, _context, _clangd

    file_contents = ""
    usage_context = ""

    if filePath is not None:
        with open(filePath) as file:
            file_lines = file.readlines()
            file_lines_nos = map(lambda x: f"{x[0]}: {x[1]}", zip(count(), file_lines))
            file_contents = "    ".join(file_lines_nos)

        if range is not None:
            usage_context = "".join(
                file_lines[range["start"]["line"] - 1 : range["end"]["line"]]
            )

    ctx = Context(
        lsp=_clangd,
        expected_arg_no=numberOfArguments,
    )

    res = await _agent.run(
        prompts.analyze_function(
            file_contents, usage_context, functionName, numberOfArguments, filePath
        ),
        deps=ctx,
    )
    return res.data


async def _run(path: str):
    global _client, _agent, _clangd

    clangd_proc = await asyncio.create_subprocess_exec(
        "clangd",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
    )

    _clangd = jsonrpc.JsonRpcClient(clangd_proc.stdout, clangd_proc.stdin)

    await _clangd.start()

    (reader, writer) = await asyncio.open_unix_connection(path)
    _client = jsonrpc.JsonRpcClient(reader, writer)

    tools = await lsp_client.initialize(_clangd)
    tools.append(duckduckgo_search_tool())

    _agent = Agent(
        "anthropic:claude-3-7-sonnet-latest",
        system_prompt="You are an expert computer programmer specializing in static analysis.",
        tools=tools,
        deps_type=jsonrpc.JsonRpcClient,
        result_type=Response,
        result_retries=5,
        retries=5,
        instrument=True,
    )

    @_agent.result_validator
    def validate_result(ctx: RunContext[Context], result: Response) -> Response:
        actual_args_no = len(result["arguments"])
        expected_args_no = ctx.deps.expected_arg_no
        if actual_args_no > expected_args_no:
            raise ModelRetry(
                f"Too many argument types: expected {expected_args_no} but got {actual_args_no}"
            )
        elif actual_args_no < expected_args_no:
            raise ModelRetry(
                f"Not enough argument types: expected {expected_args_no} but got {actual_args_no}"
            )
        return result

    _client.rpc_method("input")(input_request)

    await _client.start()

    # Keep the client running until interrupted
    try:
        # Use an event to keep the coroutine alive
        stop_event = asyncio.Event()
        await stop_event.wait()
    except asyncio.CancelledError:
        # Handle graceful shutdown
        print("Shutting down gracefully...")
    except Exception:
        raise
    finally:
        # Ensure we properly clean up
        await _client.stop()


def main() -> None:
    import argparse
    import signal

    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    args = parser.parse_args()

    try:
        # Set up proper signal handling for graceful shutdown
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        # Register signal handlers
        signals = (signal.SIGTERM, signal.SIGINT)
        for s in signals:
            loop.add_signal_handler(
                s, lambda s=s: asyncio.create_task(shutdown(loop, s))
            )

        # Run the main task
        try:
            loop.run_until_complete(_run(args.path))
        finally:
            loop.close()
    except KeyboardInterrupt:
        print("Interrupted by user")
    except Exception:
        raise


async def shutdown(loop, signal=None):
    """Cleanup tasks tied to the service's shutdown."""
    if signal:
        print(f"Received exit signal {signal.name}")

    # Cancel all running tasks except the current one
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]

    for task in tasks:
        task.cancel()

    # Wait for all tasks to be cancelled
    await asyncio.gather(*tasks, return_exceptions=True)

    # Stop the event loop
    loop.stop()
