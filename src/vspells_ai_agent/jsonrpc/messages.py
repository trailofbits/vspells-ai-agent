from typing import TypedDict, Literal, NotRequired


class JsonRpcNotification(TypedDict):
    jsonrpc: Literal["2.0"]
    method: str
    params: NotRequired[list | dict]


class JsonRpcRequest(TypedDict):
    jsonrpc: Literal["2.0"]
    method: str
    params: NotRequired[list | dict]
    id: str | int


class JsonRpcResult(TypedDict):
    jsonrpc: Literal["2.0"]
    result: dict | list | str | int | float | bool | None
    id: str | int


class JsonRpcError(TypedDict):
    code: int
    message: str
    data: NotRequired[dict | list]


class JsonRpcErrorResponse(TypedDict):
    jsonrpc: Literal["2.0"]
    error: JsonRpcError
    id: str | int | None


type JsonRpcMessage = (
    JsonRpcRequest | JsonRpcNotification | JsonRpcResult | JsonRpcErrorResponse
)


JSONRPC_PARSE_ERROR = -32700
JSONRPC_INVALID_REQUEST = -32600
JSONRPC_METHOD_NOT_FOUND = -32601
JSONRPC_INVALID_PARAMS = -32602
JSONRPC_INTERNAL_ERROR = -32603
