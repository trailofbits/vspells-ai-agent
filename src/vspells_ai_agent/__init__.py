from . import jsonrpc

import asyncio
from typing import TypedDict, Literal
import json

import anthropic


class Position(TypedDict):
    line: int
    character: int


class Range(TypedDict):
    start: Position
    end: Position


class InputResponse(TypedDict):
    value: int | str


class ClaudeAgent(jsonrpc.JsonRpcClient):
    _anthropic: anthropic.Anthropic

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self._anthropic = anthropic.Anthropic()
        self._logfile = open("/tmp/vspells-claude.log", "w")
        super().__init__(reader, writer)

    @jsonrpc.rpc_method("input")
    async def input_request(
        self,
        *,
        type: Literal["integer"] | Literal["string"] | list[str],
        text: str,
        filePath: str | None = None,
        range: Range | None = None,
    ) -> InputResponse:
        if type == "integer":
            possible_outputs = "an integer"
        elif type == "string":
            possible_outputs = "a string"
        else:
            strings = ", ".join(map(lambda s: f'"{s}"', type))
            possible_outputs = f"one of the strings {strings}"

        file_contents = None
        context = None

        if filePath is not None:
            with open(filePath) as file:
                file_lines = list(map(lambda s: f"    {s}", file.readlines()))
                file_contents = "".join(file_lines)

            if range is not None:
                context = "".join(
                    file_lines[range["start"]["line"] - 1 : range["end"]["line"]]
                )

        if file_contents is not None:
            file_contents = (
                f"These are the contents of the relevant file:\n\n{file_contents}\n\n"
            )
        else:
            file_contents = ""

        if context is not None:
            context = f"\n\nIn particular, these lines:\n\n${context}\n\n"
        else:
            context = ""

        prompt = f"""You are a computer programmer, and an expert in static analysis.
Your task is to identify properties of computer programs, in particular those related to parsing:
  - a "parser" is defined as any function that takes arbitrary user input and produces structured output, for example `scanf`
  - a "source" is defined as any function that produces arbitrary user input, for example `fread`
  - a "sink" is defined as any function that accepts potentially arbitrary user data and doesn't propagate it further, for example `printf`
  - a "nonparser" is any other kind of function.

Values can have different types:
  - type "data" is defined as being those values that are subject to parsing, for example the argument to `isspace`
  - values of type "nodata" are defined as not being subject to parsing, for example the return value to `isdigit`
  - values of type "maybedata" are defined as possibly containing either "data" or "nodata".

{file_contents}{context}

Your response should be a valid JSON object of this format:

    {{
        "reasoning": "$YOUR_REASONING"
        "value": $YOUR_RESPONSE
    }}

where $YOUR_REASONING should be the reasoning that led you to choose a particular response, and $YOUR_RESPONSE should be {possible_outputs}
"""
        response = self._anthropic.messages.create(
            model="claude-3-7-sonnet-20250219",
            max_tokens=1000,
            temperature=1,
            system=prompt,
            messages=[
                {"role": "user", "content": [{"type": "text", "text": text}]},
                {"role": "assistant", "content": "{"},
            ],
        )
        obj = json.loads("{" + response.content[0].text, strict=False)
        copy = dict(obj)
        copy["prompt"] = text
        json.dump(copy, self._logfile)
        self._logfile.write("\n")
        return obj


async def _run(path: str):
    (reader, writer) = await asyncio.open_unix_connection(path)
    client = ClaudeAgent(reader, writer)
    await client.start()

    # Keep the client running until interrupted
    try:
        # Use an event to keep the coroutine alive
        stop_event = asyncio.Event()
        await stop_event.wait()
    except asyncio.CancelledError:
        # Handle graceful shutdown
        print("Shutting down gracefully...")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        # Ensure we properly clean up
        await client.stop()


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
    except Exception as e:
        print(f"Error: {e}")


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
