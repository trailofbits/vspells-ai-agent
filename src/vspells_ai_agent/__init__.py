import asyncio
import logging
from dataclasses import dataclass, field
from typing import Sequence
import urllib.parse

import logfire
from pydantic_ai import Agent, ModelRetry, RunContext, Tool
from pydantic_ai.common_tools.duckduckgo import duckduckgo_search_tool
from pydantic_ai.messages import ModelMessage
from pydantic_graph import BaseNode, End, Graph, GraphRunContext

from . import jsonrpc, lsp_client, man, prompts


class VastClient:
    @jsonrpc.method
    async def get_function_model(
        self, *, functionName: str
    ) -> prompts.FunctionModel: ...  # type: ignore


@dataclass(kw_only=True)
class Context(lsp_client.LSPContext):
    client: VastClient
    lsp: lsp_client.LSPClient
    analysis_agent: Agent["Context", prompts.AnalysisResponse]
    feedback_agent: Agent["Context", prompts.FeedbackResponse]
    function_name: str
    expected_arg_no: int
    file_contents: str
    file_path: str
    usage_context: str


@dataclass
class State:
    message_history: list[ModelMessage] = field(default_factory=list)


@dataclass
class AnalyzeFunction(BaseNode[State, Context]):
    analysis_feedback: str | None = None

    async def run(self, ctx: GraphRunContext[State, Context]) -> "AnalysisFeedback":
        if self.analysis_feedback:
            prompt = f"Reconsider your analysis by incorporating the following feedback:\n{self.analysis_feedback}"
        else:
            prompt = prompts.analyze_function(
                ctx.deps.file_contents,
                ctx.deps.usage_context,
                ctx.deps.function_name,
                ctx.deps.expected_arg_no,
                ctx.deps.file_path,
            )
        result = await ctx.deps.analysis_agent.run(
            prompt,
            deps=ctx.deps,
            message_history=ctx.state.message_history,
        )
        ctx.state.message_history.extend(result.all_messages())
        return AnalysisFeedback(result.data)


@dataclass
class AnalysisFeedback(BaseNode[State, Context, prompts.FunctionModel]):
    analysis: prompts.AnalysisResponse

    async def run(
        self, ctx: GraphRunContext[State, Context]
    ) -> AnalyzeFunction | End[prompts.FunctionModel]:
        prompt = prompts.provide_feedback(
            ctx.deps.file_contents,
            ctx.deps.usage_context,
            ctx.deps.function_name,
            ctx.deps.expected_arg_no,
            ctx.deps.file_path,
            self.analysis,
        )
        result = await ctx.deps.feedback_agent.run(prompt, deps=ctx.deps)
        if result.data.accept_analysis:
            return End(self.analysis)
        else:
            return AnalyzeFunction(result.data.feedback)


class AnalysisService:
    def __init__(
        self,
        client: VastClient,
        lsp: lsp_client.LSPClient,
        analysis_agent: Agent[Context, prompts.AnalysisResponse],
        feedback_agent: Agent[Context, prompts.FeedbackResponse],
    ):
        self._client = client
        self._lsp = lsp
        self._analysis_agent = analysis_agent
        self._feedback_agent = feedback_agent

    async def input_request(
        self,
        *,
        functionName: str,
        numberOfArguments: int,
        filePath: str | None = None,
        range: lsp_client.Range | None = None,
    ) -> prompts.FunctionModel:
        file_contents = ""
        usage_context = ""

        if filePath is not None:
            with open(filePath) as file:
                file_lines = file.readlines()
                file_lines_nos = map(lambda x: f"{x[0]}: {x[1]}", enumerate(file_lines))
                file_contents = "    ".join(file_lines_nos)

            if range is not None:
                usage_context = "".join(
                    file_lines[range.start.line - 1 : range.end.line]
                )

        ctx = Context(
            client=self._client,
            lsp=self._lsp,
            analysis_agent=self._analysis_agent,
            feedback_agent=self._feedback_agent,
            function_name=functionName,
            expected_arg_no=numberOfArguments,
            file_contents=file_contents,
            file_path=filePath or "",
            usage_context=usage_context,
        )

        graph = Graph(nodes=(AnalyzeFunction, AnalysisFeedback))

        with logfire.span("Analyze {function=}", function=functionName):
            result = await graph.run(AnalyzeFunction(), state=State(), deps=ctx)
            return result.output


def validate_result(
    ctx: RunContext[Context], result: prompts.AnalysisResponse
) -> prompts.AnalysisResponse:
    actual_args_no = len(result.arguments)
    expected_args_no = ctx.deps.expected_arg_no
    if actual_args_no > expected_args_no:
        raise ModelRetry(
            f"Too many argument types: expected {expected_args_no} but got {actual_args_no}"
        )
    elif actual_args_no < expected_args_no:
        raise ModelRetry(
            f"Not enough argument types: expected {expected_args_no} but got {actual_args_no}"
        )

    if result.category == "nonparser":
        for i, arg in enumerate(result.arguments):
            if arg != "nodata":
                raise ModelRetry(
                    f"The function was categorized as being nonparser but argument #{i} is categorised as being {arg}, whereas all nonparser arguments must be nodata"
                )
    elif result.category == "sink" and result.return_type != "nodata":
        raise ModelRetry(
            f"The function was categorized as being a sink but returns {result.return_type}, whereas the return type of a sink musk always be nodata"
        )
    return result


async def get_function_model(
    ctx: RunContext[Context], function_name: str
) -> prompts.FunctionModel:
    """Returns the model of a function that has been analyzed beforehand"""

    try:
        return await ctx.deps.client.get_function_model(functionName=function_name)
    except Exception as ex:
        raise ModelRetry(str(ex)) from ex


async def _run(
    path: urllib.parse.ParseResult,
    clang_path: str | None,
    disable_ddg: bool,
    disable_man: bool,
):
    tools: Sequence[Tool[Context]] = []
    if clang_path is not None:
        clangd_proc = await asyncio.create_subprocess_exec(
            clang_path,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
        )

        assert clangd_proc.stdout is not None
        assert clangd_proc.stdin is not None

        clangd = jsonrpc.JsonRpcConnection(
            jsonrpc.JsonRpcStreamTransport(clangd_proc.stdout, clangd_proc.stdin)
        )

        clangd_task = asyncio.create_task(clangd.run())
        clangd_client = clangd.get_client(lsp_client.LSPClient)
        tools = await lsp_client.initialize(clangd_client)

    match path.scheme:
        case "unix":
            (reader, writer) = await asyncio.open_unix_connection(path.hostname)
        case "tcp":
            (reader, writer) = await asyncio.open_connection(path.hostname, path.port)
        case _:
            raise ValueError(f"Unsupported scheme {path.scheme}")
    client = jsonrpc.JsonRpcConnection(jsonrpc.JsonRpcStreamTransport(reader, writer))

    if not disable_ddg:
        tmp = list(tools)
        tmp.append(duckduckgo_search_tool())
        tools = tmp

    if not disable_man:
        tmp = list(tools)
        tmp.append(Tool(man.man))
        tools = tmp

    tmp = list(tools)
    tmp.append(Tool(get_function_model))
    tools = tmp

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

    service = AnalysisService(
        client.get_client(VastClient),
        clangd_client,
        analysis_agent,
        feedback_agent,
    )
    client.rpc_method("input", service.input_request)

    await client.run()


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "socket_path",
        help="URI to the socket to be used for communicating with vast-detect-parsers. Examples: tcp://localhost:1234 unix:///tmp/vast.sock",
        type=urllib.parse.urlparse,
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
        "--clangd-path",
        default="clangd",
        help="Path to the clangd executable to be used for the LSP integration. Defaults to `clangd`.",
    )
    lsp_group.add_argument(
        "--disable-clangd",
        dest="clangd_path",
        action="store_const",
        const=None,
        help="Disables the LSP integration",
    )

    args = parser.parse_args()

    if args.enable_logfire:
        logfire.configure(scrubbing=False)
        logfire.instrument_anthropic()
        logging.basicConfig(handlers=[logfire.LogfireLoggingHandler()])

    logging.info("Starting loop", extra={"cliArgs": vars(args)})
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    loop.run_until_complete(
        _run(args.socket_path, args.clangd_path, args.disable_ddg, args.disable_man)
    )
