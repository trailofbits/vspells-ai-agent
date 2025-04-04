from . import jsonrpc
from . import prompts
from . import lsp_client
from . import man

import asyncio
from itertools import count
from typing import TypedDict
from dataclasses import dataclass, field
import logging

from pydantic_ai import Agent, RunContext, ModelRetry, Tool
from pydantic_ai.common_tools.duckduckgo import duckduckgo_search_tool
from pydantic_ai.messages import ModelMessage

from pydantic_graph import BaseNode, GraphRunContext, End, Graph

import logfire


class Position(TypedDict):
    line: int
    character: int


class Range(TypedDict):
    start: Position
    end: Position


@dataclass(kw_only=True)
class Context:
    client: jsonrpc.JsonRpcConnection
    lsp: jsonrpc.JsonRpcConnection
    function_name: str
    expected_arg_no: int
    file_contents: str
    file_path: str
    usage_context: str
    message_history: list[ModelMessage] = field(default_factory=list)


_client: jsonrpc.JsonRpcConnection
_clangd: jsonrpc.JsonRpcConnection
analysis_agent: Agent[Context, prompts.AnalysisResponse]
feedback_agent: Agent[Context, prompts.FeedbackResponse]


@dataclass
class AnalyzeFunction(BaseNode[Context]):
    analysis_feedback: str | None = None

    async def run(self, ctx: GraphRunContext[Context]) -> "AnalysisFeedback":
        global analysis_agent

        if self.analysis_feedback:
            prompt = f"Reconsider your analysis by incorporating the following feedback:\n{self.analysis_feedback}"
        else:
            prompt = prompts.analyze_function(
                ctx.state.file_contents,
                ctx.state.usage_context,
                ctx.state.function_name,
                ctx.state.expected_arg_no,
                ctx.state.file_path,
            )
        result = await analysis_agent.run(
            prompt,
            deps=ctx.state,
            message_history=ctx.state.message_history,
        )
        ctx.state.message_history.extend(result.all_messages())
        return AnalysisFeedback(result.data)


@dataclass
class AnalysisFeedback(BaseNode[Context, None, prompts.FunctionModel]):
    analysis: prompts.AnalysisResponse

    async def run(
        self, ctx: GraphRunContext[Context]
    ) -> AnalyzeFunction | End[prompts.FunctionModel]:
        global feedback_agent

        prompt = prompts.provide_feedback(
            ctx.state.file_contents,
            ctx.state.usage_context,
            ctx.state.function_name,
            ctx.state.expected_arg_no,
            ctx.state.file_path,
            self.analysis,
        )
        result = await feedback_agent.run(prompt, deps=ctx.state)
        if result.data.accept_analysis:
            return End(self.analysis)
        else:
            return AnalyzeFunction(result.data.feedback)


async def input_request(
    *,
    functionName: str,
    numberOfArguments: int,
    filePath: str | None = None,
    range: Range | None = None,
) -> prompts.FunctionModel:
    global analysis_agent, feedback_agent, _context, _clangd

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
        client=_client,
        lsp=_clangd,
        function_name=functionName,
        expected_arg_no=numberOfArguments,
        file_contents=file_contents,
        file_path=filePath,
        usage_context=usage_context,
    )

    graph = Graph(nodes=(AnalyzeFunction, AnalysisFeedback))

    with logfire.span("Analyze {function=}", function=functionName):
        result = await graph.run(AnalyzeFunction(), state=ctx)
        return result.output


def validate_result(
    ctx: RunContext[Context], result: prompts.AnalysisResponse
) -> prompts.AnalysisResponse:
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

    if result["category"] == "nonparser":
        for i, arg in zip(count(), result["arguments"]):
            if arg != "nodata":
                raise ModelRetry(
                    f"The function was categorized as being nonparser but argument #{i} is categorised as being {arg}, whereas all nonparser arguments must be nodata"
                )
    elif result["category"] == "sink" and result["return_type"] != "nodata":
        raise ModelRetry(
            f"The function was categorized as being a sink but returns {result['return_type']}, whereas the return type of a sink musk always be nodata"
        )
    return result


async def get_function_model(
    ctx: RunContext[Context], function_name: str
) -> prompts.FunctionModel:
    """Returns the model of a function that has been analyzed beforehand"""

    try:
        return await ctx.deps.client.send_request(
            "get_function_model", functionName=function_name
        )
    except Exception as ex:
        raise ModelRetry(str(ex)) from ex


async def _run(path: str, clang_path: str | None, disable_ddg: bool, disable_man: bool):
    global _client, analysis_agent, feedback_agent, _clangd

    if clang_path is not None:
        clangd_proc = await asyncio.create_subprocess_exec(
            "clangd",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
        )

        _clangd = jsonrpc.JsonRpcConnection(
            jsonrpc.JsonRpcStreamTransport(clangd_proc.stdout, clangd_proc.stdin)
        )

        clangd_task = asyncio.create_task(_clangd.run())
        tools = await lsp_client.initialize(_clangd)
    else:
        tools = []

    (reader, writer) = await asyncio.open_unix_connection(path)
    _client = jsonrpc.JsonRpcConnection(jsonrpc.JsonRpcStreamTransport(reader, writer))

    if not disable_ddg:
        tools.append(duckduckgo_search_tool())

    if not disable_man:
        tools.append(man.man)

    tools.append(Tool(get_function_model))

    analysis_agent = Agent(
        "anthropic:claude-3-7-sonnet-latest",
        system_prompt="You are an expert in computer programming and static analysis, specializing in evaluating function behavior and its implications for dataflow analysis and taint tracking.",
        tools=tools,
        deps_type=Context,
        result_type=prompts.AnalysisResponse,
        result_retries=5,
        retries=5,
        instrument=True,
    )

    feedback_agent = Agent(
        "anthropic:claude-3-7-sonnet-latest",
        system_prompt="You are an expert in computer programming and static analysis, specializing in evaluating function behavior and its implications for dataflow analysis and taint tracking.",
        tools=tools,
        deps_type=Context,
        result_type=prompts.FeedbackResponse,
        result_retries=5,
        retries=5,
        instrument=True,
    )

    analysis_agent.result_validator(validate_result)

    _client.rpc_method("input")(input_request)

    await _client.run()


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "socket_path",
        help="Path to the Unix socket to be used for communicating with vast-detect-parsers",
    )
    parser.add_argument(
        "--disable-ddg", action="store_true", help="Disables the DuckDuckGo integration"
    )
    parser.add_argument(
        "--disable-man",
        action="store_true",
        help="Disables the man pages integration. The man pages integration requires man and mandoc to be available in PATH.",
    )
    parser.add_argument(
        "--enable-logfire",
        action="store_true",
        help="Enables logging LLM calls to Logfire",
    )
    lsp_group = parser.add_mutually_exclusive_group()
    lsp_group.add_argument(
        "--clang-path",
        default="clang",
        help="Path to the clangd executable to be used for the LSP integration. Defaults to `clang`.",
    )
    lsp_group.add_argument(
        "--disable-clang",
        dest="clang_path",
        action="store_const",
        const=None,
        help="Disables the LSP integration",
    )

    args = parser.parse_args()

    if args.enable_logfire:
        logfire.configure(scrubbing=False)
        logfire.instrument_anthropic()
        logging.basicConfig(handlers=[logfire.LogfireLoggingHandler()])

    logging.info("Starting loop", extra={
        "cliArgs": vars(args)
    })
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    loop.run_until_complete(
        _run(args.socket_path, args.clang_path, args.disable_ddg, args.disable_man)
    )
