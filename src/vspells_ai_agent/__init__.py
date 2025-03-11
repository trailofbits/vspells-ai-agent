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

def _extract(text: str, start: str, end: str) -> str:
    start_index = text.index(start) + len(start)
    end_index = text.index(end, start_index)
    return text[start_index:end_index]

class ClaudeAgent(jsonrpc.JsonRpcClient):
    _anthropic: anthropic.AsyncAnthropic

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self._anthropic = anthropic.AsyncAnthropic(
            max_retries=10
        )
        self._logfile = open("/tmp/vspells-claude.log", "w", buffering=1)
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
            possible_outputs = "\n".join(type)

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

        msg = f"""Your task is to categorize a given function based on its role in parsing, handling, or processing data. You will receive file contents, context, a function name, and possible output categories. Analyze the information provided and categorize the function according to the given criteria.

First, review the following file contents:

<file_contents>
{file_contents}
</file_contents>

Now, consider this additional context that may be relevant to your analysis:

<context>
{context}
</context>

Your goal is to analyze and categorize a function based on the following definitions and categories:

1. Parser: Any function that takes arbitrary user input and produces structured output.
2. Source: Any function that produces arbitrary user input.
3. Sink: Any function that accepts potentially arbitrary user data and doesn't propagate it further.
4. Nonparser: Any other kind of function that doesn't fit into the above categories.

Additionally, consider these value types:
- "data": Values subject to parsing.
- "nodata": Values not subject to parsing.
- "maybedata": Values that could contain either "data" or "nodata".

The possible output values are:

<possible_outputs>
{possible_outputs}
</possible_outputs>

IMPORTANT: Focus on analyzing the function's behavior rather than its name. The name itself should not be the primary factor in your categorization.

Please conduct your analysis using the following steps:

1. List all relevant code snippets from the file_contents that pertain to the function being analyzed.
2. Summarize the function's overall purpose based on the given context and file contents.
3. Examine the function's behavior based on the given context and file contents.
4. Consider how the function interacts with other parts of the system.
5. Consider how well the function fits into each category (Parser, Source, Sink, Nonparser).
6. Evaluate how the function might handle input.
7. Assess how the function might handle output.
8. Determine which value type (data, nodata, maybedata) the function is likely to work with.
9. Consider edge cases and potential ambiguities.
10. Make a final determination on the most appropriate category.
11. State any assumptions made during the analysis.
12. Provide a confidence rating (0-100%) for your final categorization.

For each step of your analysis:

- Quote relevant parts of the file_contents and context that support your analysis.
- For steps 5 and 8, list arguments for and against each category or value type, provide a confidence level (0-100%) for each, and number each piece of evidence.
- Provide detailed reasoning for your conclusions.
- For step 9, explicitly state any edge cases or ambiguities you've identified.

Wrap your analysis in <function_analysis> tags. After completing your analysis, provide your final categorization in <result> tags. The <result> tag should contain ONLY one of the values from the <possible_outputs> list.

Here's an example of how your response should be structured:

<function_analysis>
1. Relevant code snippets:
   [List code snippets here]

2. Function purpose summary:
   The function appears to...

3. Function behavior examination:
   Relevant quote from file_contents: "..."
   Relevant quote from context: "..."
   The function appears to...

[Steps 4-12 following the same structure]

</function_analysis>

<result>
example_category
</result>

This is your task:
{text}
"""
        response = await self._anthropic.messages.create(
            model="claude-3-7-sonnet-20250219",
            max_tokens=8192,
            temperature=1,
            system="You are an expert computer programmer specializing in static analysis.",
            messages=[
                {"role": "user", "content": [{"type": "text", "text": msg}]},
                {"role": "assistant", "content": "<function_analysis>"},
            ],
        )
        response_msg: str = response.content[0].text
        reasoning = response_msg[:response_msg.find("</function_analysis>")].strip()
        value = _extract(response_msg, "<result>", "</result>").strip()
        json.dump({"prompt": text, "reasoning": reasoning, "value": value}, self._logfile)
        self._logfile.write("\n")
        return {"value": value}


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
    except Exception:
        raise
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
