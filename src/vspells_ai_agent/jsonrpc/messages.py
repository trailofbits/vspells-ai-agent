"""JSON-RPC 2.0 Message Type Definitions

This module defines the core message types used in JSON-RPC 2.0 communication.
All types are defined using Python's TypedDict to ensure proper typing and validation.

The JSON-RPC 2.0 specification defines four types of messages:
1. Request - A call to a method that requires a response
2. Notification - A one-way message that doesn't require a response
3. Success Response - A response containing the result of a method call
4. Error Response - A response indicating an error occurred

References:
    JSON-RPC 2.0 Specification: https://www.jsonrpc.org/specification
"""

from typing import TypedDict, Literal, NotRequired


class JsonRpcNotification(TypedDict):
    """A JSON-RPC notification message.
    
    Notifications are one-way messages that do not require a response.
    They are similar to requests but do not include an id field.
    
    Fields:
        jsonrpc: Must be exactly "2.0"
        method: The name of the method to be invoked
        params: Optional positional or named parameters (default: None)
    """
    jsonrpc: Literal["2.0"]
    method: str
    params: NotRequired[list | dict]


class JsonRpcRequest(TypedDict):
    """A JSON-RPC request message.
    
    Requests are messages that require a response. The response will
    contain the same id as the request.
    
    Fields:
        jsonrpc: Must be exactly "2.0"
        method: The name of the method to be invoked
        params: Optional positional or named parameters (default: None)
        id: Request identifier that will be echoed back in the response
    """
    jsonrpc: Literal["2.0"]
    method: str
    params: NotRequired[list | dict]
    id: str | int


class JsonRpcResult(TypedDict):
    """A JSON-RPC success response message.
    
    Success responses contain the result of a method call and the id
    of the original request.
    
    Fields:
        jsonrpc: Must be exactly "2.0"
        result: The result of the method call
        id: The id from the original request
    """
    jsonrpc: Literal["2.0"]
    result: dict | list | str | int | float | bool | None
    id: str | int


class JsonRpcError(TypedDict):
    """A JSON-RPC error object.
    
    Error objects describe the error that occurred when processing
    a request.
    
    Fields:
        code: The error code (see error code constants below)
        message: A short description of the error
        data: Optional additional error information (default: None)
    """
    code: int
    message: str
    data: NotRequired[dict | list]


class JsonRpcErrorResponse(TypedDict):
    """A JSON-RPC error response message.
    
    Error responses indicate that an error occurred while processing
    the request. They contain an error object and the id of the
    original request.
    
    Fields:
        jsonrpc: Must be exactly "2.0"
        error: The error that occurred
        id: The id from the original request, or null if the id couldn't be determined
    """
    jsonrpc: Literal["2.0"]
    error: JsonRpcError
    id: str | int | None


JsonRpcMessage = JsonRpcRequest | JsonRpcNotification | JsonRpcResult | JsonRpcErrorResponse
"""Union type of all possible JSON-RPC message types."""


# Standard JSON-RPC 2.0 error codes
JSONRPC_PARSE_ERROR = -32700
"""Invalid JSON was received by the server."""

JSONRPC_INVALID_REQUEST = -32600
"""The JSON sent is not a valid Request object."""

JSONRPC_METHOD_NOT_FOUND = -32601
"""The method does not exist / is not available."""

JSONRPC_INVALID_PARAMS = -32602
"""Invalid method parameter(s)."""

JSONRPC_INTERNAL_ERROR = -32603
"""Internal JSON-RPC error."""
