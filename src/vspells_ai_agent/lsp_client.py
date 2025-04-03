from .jsonrpc import JsonRpcConnection

from itertools import count
from pydantic_ai import RunContext, Tool, ModelRetry
from typing import TypedDict, NotRequired, Protocol


class ServerCapabilities(TypedDict):
    declarationProvider: NotRequired[dict | bool]
    definitionProvider: NotRequired[dict | bool]
    typeDefinitionProvider: NotRequired[dict | bool]
    implementationProvider: NotRequired[dict | bool]
    referencesProvider: NotRequired[dict | bool]
    callHierarchyProvider: NotRequired[dict | bool]
    typeHierarchyProvider: NotRequired[dict | bool]


class InitializeResult(TypedDict):
    class ServerInfo(TypedDict):
        name: str
        version: NotRequired[str]

    capabilities: ServerCapabilities
    serverInfo: NotRequired[ServerInfo]


class Position(TypedDict):
    """Position in a text document expressed as zero-based line and zero-based character offset. A position is between two characters like an ‘insert’ cursor in an editor. Special values like for example -1 to denote the end of a line are not supported."""

    line: int
    """Line position in a document (zero-based)."""

    character: int
    """Character offset on a line in a document (zero-based)."""


class Range(TypedDict):
    """A range in a text document expressed as (zero-based) start and end positions. A range is comparable to a selection in an editor. Therefore, the end position is exclusive. If you want to specify a range that contains a line including the line ending character(s) then use an end position denoting the start of the next line."""

    start: Position
    """The range's start position."""

    end: Position
    """The range's end position."""


class Location(TypedDict):
    """A location inside a resource, such as a line inside a text file."""

    uri: str
    range: Range


class TextDocumentIdentifier(TypedDict):
    """Text documents are identified using a URI."""

    uri: str
    """The text document's URI. Includes protocol (e.g. file:// )"""


class LSPContext(Protocol):
    lsp: JsonRpcConnection


async def openDocument(client: JsonRpcConnection, uri: str):
    if not uri.startswith("file://"):
        raise ModelRetry("URIs must start with a protocol name (e.g. file://)")
    with open(uri[len("file://") :]) as file:
        text = file.read()
    await client.send_notification(
        "textDocument/didOpen",
        {
            "textDocument": {
                "uri": uri,
                "languageId": "c",
                "version": 0,
                "text": text,
            }
        },
    )


async def gotoDeclaration(
    ctx: RunContext[LSPContext],
    textDocument: TextDocumentIdentifier,
    position: Position,
) -> Location | list[Location] | None:
    """Resolve the declaration location of a symbol at a given text document position. Remember all URIs must start with a protocol (e.g. file:// )"""
    try:
        await openDocument(ctx.deps.lsp, textDocument["uri"])
        return await ctx.deps.lsp.send_request(
            "textDocument/declaration",
            {
                "textDocument": textDocument,
                "position": position,
            },
        )
    except Exception as ex:
        raise ModelRetry(str(ex)) from ex


async def gotoDefinition(
    ctx: RunContext[LSPContext],
    textDocument: TextDocumentIdentifier,
    position: Position,
) -> Location | list[Location] | None:
    """Resolve the definition location of a symbol at a given text document position. Remember all URIs must start with a protocol (e.g. file:// )"""
    try:
        await openDocument(ctx.deps.lsp, textDocument["uri"])
        return await ctx.deps.lsp.send_request(
            "textDocument/definition",
            {
                "textDocument": textDocument,
                "position": position,
            },
        )
    except Exception as ex:
        raise ModelRetry(str(ex)) from ex


async def gotoTypeDefinition(
    ctx: RunContext[LSPContext],
    textDocument: TextDocumentIdentifier,
    position: Position,
) -> Location | list[Location] | None:
    """Resolve the type definition location of a symbol at a given text document position. Remember all URIs must start with a protocol (e.g. file:// )"""
    try:
        await openDocument(ctx.deps.lsp, textDocument["uri"])
        return await ctx.deps.lsp.send_request(
            "textDocument/typeDefinition",
            {
                "textDocument": textDocument,
                "position": position,
            },
        )
    except Exception as ex:
        raise ModelRetry(str(ex)) from ex


async def gotoImplementation(
    ctx: RunContext[LSPContext],
    textDocument: TextDocumentIdentifier,
    position: Position,
) -> Location | list[Location] | None:
    """Resolve the implementation location of a symbol at a given text document position. Remember all URIs must start with a protocol (e.g. file:// )"""
    try:
        await openDocument(ctx.deps.lsp, textDocument["uri"])
        return await ctx.deps.lsp.send_request(
            "textDocument/implementation",
            {
                "textDocument": textDocument,
                "position": position,
            },
        )
    except Exception as ex:
        raise ModelRetry(str(ex)) from ex


async def findReferences(
    ctx: RunContext[LSPContext],
    textDocument: TextDocumentIdentifier,
    position: Position,
) -> Location | list[Location] | None:
    """Resolve project-wide references for the symbol denoted by the given text document position. Remember all URIs must start with a protocol (e.g. file:// )"""
    try:
        await openDocument(ctx.deps.lsp, textDocument["uri"])
        return await ctx.deps.lsp.send_request(
            "textDocument/references",
            {
                "textDocument": textDocument,
                "position": position,
            },
        )
    except Exception as ex:
        raise ModelRetry(str(ex)) from ex


async def readFile(ctx: RunContext[LSPContext], uri: str, range: Range):
    """Reads the contents of a file. Remember all URIs must start with a protocol (e.g. file:// )"""
    if not uri.startswith("file://"):
        raise ModelRetry("URIs must start with a protocol name (e.g. file://)")
    try:
        with open(uri[len("file://") :]) as file:
            lines = file.readlines()
            lines_nos = list(map(lambda x: f"{x[0]}: {x[1]}", zip(count(), lines)))
            return "    ".join(lines_nos[range["start"]["line"] : range["end"]["line"]])
    except Exception as ex:
        raise ModelRetry(str(ex)) from ex


async def initialize(lsp: JsonRpcConnection) -> list[Tool[LSPContext]]:
    result: InitializeResult = await lsp.send_request(
        "initialize", {"clientCapabilities": {}}
    )

    tools: list[Tool[LSPContext]] = [Tool(readFile, name="lsp_read_file")]
    if (
        "declarationProvider" in result["capabilities"]
        and result["capabilities"]["declarationProvider"]
    ):
        tools.append(Tool(gotoDeclaration, name="lsp_goto_declaration"))
    if (
        "definitionProvider" in result["capabilities"]
        and result["capabilities"]["definitionProvider"]
    ):
        tools.append(Tool(gotoDefinition, name="lsp_goto_definition"))
    if (
        "typeDefinitionProvider" in result["capabilities"]
        and result["capabilities"]["typeDefinitionProvider"]
    ):
        tools.append(Tool(gotoTypeDefinition, name="lsp_goto_type_definition"))
    if (
        "implementationProvider" in result["capabilities"]
        and result["capabilities"]["implementationProvider"]
    ):
        tools.append(Tool(gotoImplementation, name="lsp_goto_implementation"))
    if (
        "referencesProvider" in result["capabilities"]
        and result["capabilities"]["referencesProvider"]
    ):
        tools.append(Tool(findReferences, name="lsp_find_references"))

    return tools
