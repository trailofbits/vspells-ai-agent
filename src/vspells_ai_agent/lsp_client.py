import logging
from typing import NotRequired, Protocol, TypedDict

from pydantic import BaseModel
from pydantic_ai import ModelRetry, RunContext, Tool

from . import jsonrpc

logger = logging.getLogger(__name__)


class ServerCapabilities(TypedDict):
    declarationProvider: NotRequired[dict | bool]
    definitionProvider: NotRequired[dict | bool]
    typeDefinitionProvider: NotRequired[dict | bool]
    implementationProvider: NotRequired[dict | bool]
    referencesProvider: NotRequired[dict | bool]
    callHierarchyProvider: NotRequired[dict | bool]
    typeHierarchyProvider: NotRequired[dict | bool]


class ServerInfo(TypedDict):
    name: str
    version: NotRequired[str]


class InitializeResult(TypedDict):
    capabilities: ServerCapabilities
    serverInfo: NotRequired[ServerInfo]


class Position(BaseModel):
    """Position in a text document expressed as zero-based line and zero-based character offset. A position is between two characters like an 'insert' cursor in an editor. Special values like for example -1 to denote the end of a line are not supported."""

    line: int
    """Line position in a document (zero-based)."""

    character: int
    """Character offset on a line in a document (zero-based)."""


class Range(BaseModel):
    """A range in a text document expressed as (zero-based) start and end positions. A range is comparable to a selection in an editor. Therefore, the end position is exclusive. If you want to specify a range that contains a line including the line ending character(s) then use an end position denoting the start of the next line."""

    start: Position
    """The range's start position."""

    end: Position
    """The range's end position."""


class Location(BaseModel):
    """A location inside a resource, such as a line inside a text file."""

    uri: str
    range: Range


class TextDocumentIdentifier(BaseModel):
    """Text documents are identified using a URI."""

    uri: str
    """The text document's URI. Includes protocol (e.g. file:// )"""


class TextDocumentOpen(BaseModel):
    uri: str
    languageId: str
    version: int
    text: str


class LSPContext(Protocol):
    lsp: "LSPClient"


class LSPClient:
    @jsonrpc.notification("textDocument/didOpen")
    async def open_document(self, *, textDocument: TextDocumentOpen): ...

    @jsonrpc.method
    async def initialize(self, *, clientCapabilities: dict) -> InitializeResult: ...  # type: ignore[empty-body]

    @jsonrpc.method("textDocument/declaration")
    async def goto_declaration(
        self, *, textDocument: TextDocumentIdentifier, position: Position
    ) -> Location | list[Location] | None: ...

    @jsonrpc.method("textDocument/definition")
    async def goto_definition(
        self, *, textDocument: TextDocumentIdentifier, position: Position
    ) -> Location | list[Location] | None: ...

    @jsonrpc.method("textDocument/typeDefinition")
    async def goto_type_definition(
        self, *, textDocument: TextDocumentIdentifier, position: Position
    ) -> Location | list[Location] | None: ...

    @jsonrpc.method("textDocument/implementation")
    async def goto_implementation(
        self, *, textDocument: TextDocumentIdentifier, position: Position
    ) -> Location | list[Location] | None: ...

    @jsonrpc.method("textDocument/references")
    async def find_references(
        self, *, textDocument: TextDocumentIdentifier, position: Position
    ) -> Location | list[Location] | None: ...


async def open_document(client: LSPClient, uri: str):
    if not uri.startswith("file://"):
        raise ModelRetry("URIs must start with a protocol name (e.g. file://)")
    with open(uri[len("file://") :]) as file:
        text = file.read()
    await client.open_document(
        textDocument=TextDocumentOpen(uri=uri, languageId="c", version=0, text=text),
    )


async def lsp_goto_declaration(
    ctx: RunContext[LSPContext],
    textDocument: TextDocumentIdentifier,
    position: Position,
) -> Location | list[Location] | None:
    """Resolve the declaration location of a symbol at a given text document position. Remember all URIs must start with a protocol (e.g. file:// )"""
    try:
        await open_document(ctx.deps.lsp, textDocument.uri)
        return await ctx.deps.lsp.goto_declaration(
            textDocument=textDocument,
            position=position,
        )
    except Exception as ex:
        raise ModelRetry(str(ex)) from ex


async def lsp_goto_definition(
    ctx: RunContext[LSPContext],
    textDocument: TextDocumentIdentifier,
    position: Position,
) -> Location | list[Location] | None:
    """Resolve the definition location of a symbol at a given text document position. Remember all URIs must start with a protocol (e.g. file:// )"""
    try:
        await open_document(ctx.deps.lsp, textDocument.uri)
        return await ctx.deps.lsp.goto_definition(
            textDocument=textDocument,
            position=position,
        )
    except Exception as ex:
        raise ModelRetry(str(ex)) from ex


async def lsp_goto_type_definition(
    ctx: RunContext[LSPContext],
    textDocument: TextDocumentIdentifier,
    position: Position,
) -> Location | list[Location] | None:
    """Resolve the type definition location of a symbol at a given text document position. Remember all URIs must start with a protocol (e.g. file:// )"""
    try:
        await open_document(ctx.deps.lsp, textDocument.uri)
        return await ctx.deps.lsp.goto_type_definition(
            textDocument=textDocument,
            position=position,
        )
    except Exception as ex:
        raise ModelRetry(str(ex)) from ex


async def lsp_goto_implementation(
    ctx: RunContext[LSPContext],
    textDocument: TextDocumentIdentifier,
    position: Position,
) -> Location | list[Location] | None:
    """Resolve the implementation location of a symbol at a given text document position. Remember all URIs must start with a protocol (e.g. file:// )"""
    try:
        await open_document(ctx.deps.lsp, textDocument.uri)
        return await ctx.deps.lsp.goto_implementation(
            textDocument=textDocument,
            position=position,
        )
    except Exception as ex:
        raise ModelRetry(str(ex)) from ex


async def lsp_find_references(
    ctx: RunContext[LSPContext],
    textDocument: TextDocumentIdentifier,
    position: Position,
) -> Location | list[Location] | None:
    """Resolve project-wide references for the symbol denoted by the given text document position. Remember all URIs must start with a protocol (e.g. file:// )"""
    try:
        await open_document(ctx.deps.lsp, textDocument.uri)
        return await ctx.deps.lsp.find_references(
            textDocument=textDocument,
            position=position,
        )
    except Exception as ex:
        raise ModelRetry(str(ex)) from ex


async def lsp_read_file(ctx: RunContext[LSPContext], uri: str, range: Range) -> str:
    """Reads the contents of a file. Remember all URIs must start with a protocol (e.g. file:// )"""
    if not uri.startswith("file://"):
        raise ModelRetry("URIs must start with a protocol name (e.g. file://)")
    try:
        with open(uri[len("file://") :]) as file:
            lines = file.readlines()
            lines_nos = list(map(lambda x: f"{x[0]}: {x[1]}", enumerate(lines)))
            return "    ".join(lines_nos[range.start.line : range.end.line])
    except Exception as ex:
        raise ModelRetry(str(ex)) from ex


async def initialize(lsp: LSPClient) -> list[Tool[LSPContext]]:
    result = await lsp.initialize(
        clientCapabilities={},
    )
    logger.info(
        "LSP connection initialized with %s",
        result["serverInfo"]["name"],
        extra={
            "serverInfo": result["serverInfo"],
            "serverCapabilities": result["capabilities"],
        },
    )

    tools: list[Tool[LSPContext]] = [Tool(lsp_read_file)]
    if result["capabilities"].get("declarationProvider"):
        tools.append(Tool(lsp_goto_declaration))
    if result["capabilities"].get("definitionProvider"):
        tools.append(Tool(lsp_goto_definition))
    if result["capabilities"].get("typeDefinitionProvider"):
        tools.append(Tool(lsp_goto_type_definition))
    if result["capabilities"].get("implementationProvider"):
        tools.append(Tool(lsp_goto_implementation))
    if result["capabilities"].get("referencesProvider"):
        tools.append(Tool(lsp_find_references))

    return tools
