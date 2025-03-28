from . import jsonrpc
from . import prompts

import asyncio
from typing import TypedDict, Literal, NotRequired

from pydantic_ai import Agent
from pydantic_ai.common_tools.duckduckgo import duckduckgo_search_tool

import logfire

logfire.configure()
logfire.instrument_anthropic()


class Position(TypedDict):
    line: int
    character: int


class Range(TypedDict):
    start: Position
    end: Position


class FunctionCategoryProperties(TypedDict):
    type: Literal["functionCategory"]
    functionName: str


class ReturnTypeProperties(TypedDict):
    type: Literal["returnType"]
    functionName: str


class ArgumentTypeProperties(TypedDict):
    type: Literal["argumentType"]
    functionName: str
    argumentIndex: int
    argumentName: NotRequired[str]


class InputResponse(TypedDict):
    value: int | str
    isStdlib: bool | None
    source: str


_client: jsonrpc.JsonRpcClient
_agent: Agent


async def input_request(
    *,
    type: Literal["integer"] | Literal["string"] | list[str],
    text: str,
    filePath: str | None = None,
    range: Range | None = None,
    properties: FunctionCategoryProperties
    | ReturnTypeProperties
    | ArgumentTypeProperties
    | None = None,
) -> InputResponse:
    global _agent

    file_contents = ""
    context = ""

    if filePath is not None:
        with open(filePath) as file:
            file_lines = file.readlines()
            file_contents = "".join(file_lines)

        if range is not None:
            context = "".join(
                file_lines[range["start"]["line"] - 1 : range["end"]["line"]]
            )
    if properties is None:
        return

    if properties["type"] == "functionCategory":
        response = await _agent.run(
            prompts.function_category(
                file_contents, context, properties["functionName"]
            ),
            result_type=prompts.CategoryAgentResponse,
        )
        return {
            "isStdlib": response.data.isStdlib,
            "source": "AI",
            "value": response.data.response,
        }
    elif properties["type"] == "returnType":
        response = await _agent.run(
            prompts.return_type(file_contents, context, properties["functionName"]),
            result_type=prompts.ReturnTypeAgentResponse,
        )
        return {"source": "AI", "value": response.data.response, "isStdlib": None}
    elif properties["type"] == "argumentType":
        response = await _agent.run(
            prompts.argument_type(
                file_contents,
                context,
                properties["functionName"],
                properties["argumentIndex"],
            ),
            result_type=prompts.ArgumentTypeAgentResponse,
        )
        return {"source": "AI", "value": response.data.response, "isStdlib": None}


async def _run(path: str):
    global _client, _agent

    (reader, writer) = await asyncio.open_unix_connection(path)
    _client = jsonrpc.JsonRpcClient(reader, writer)

    _agent = Agent(
        "anthropic:claude-3-7-sonnet-latest",
        system_prompt="You are an expert computer programmer specializing in static analysis.",
        tools=[duckduckgo_search_tool()],
        result_retries=5,
        retries=5,
        instrument=True,
    )

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
