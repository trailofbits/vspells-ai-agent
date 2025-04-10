"""JSON-RPC Connection Management

This module provides the core JSON-RPC connection functionality, including:
1. Connection management and message routing
2. Method and notification registration
3. Client proxy generation
4. Error handling

The module implements both client and server functionality in a single class,
allowing for bidirectional RPC communication. It supports:

- Type-safe method calls and responses
- Asynchronous operation
- Protocol-based client generation
- Automatic parameter validation
- Custom error handling
- Notification handling

Example:
    ```python
    # Server-side
    class Calculator:
        @method
        async def add(self, a: float, b: float) -> float:
            return a + b

    transport = JsonRpcStreamTransport(reader, writer)
    connection = JsonRpcConnection(transport)
    calc_server = Calculator()
    connection.rpc_method("add", calc_server.add)

    await connection.run()

    # Client-side
    class CalculatorProtocol(Protocol):
        @method
        async def add(self, a: float, b: float) -> float: ...
    calculator = connection.get_client(CalculatorProtocol)
    result = await calculator.add(2.5, 3.7)
    ```

See Also:
    - transport.py: Transport layer implementations
"""

import asyncio
import inspect
import json
from typing import Callable, Type, overload, Any
from pydantic import TypeAdapter, ValidationError, validate_call
import logging

from .transport import JsonRpcTransport
from .messages import (
    JsonRpcMessage,
    JsonRpcError,
    JsonRpcErrorResponse,
    JsonRpcNotification,
    JsonRpcRequest,
    JsonRpcResult,
    JSONRPC_INTERNAL_ERROR,
    JSONRPC_INVALID_REQUEST,
    JSONRPC_METHOD_NOT_FOUND,
    JSONRPC_PARSE_ERROR,
)

logger = logging.getLogger(__name__)


class JsonRpcException(Exception):
    """Exception raised for JSON-RPC specific errors.

    This exception class represents JSON-RPC protocol errors and can be
    converted to and from JSON-RPC error objects.

    Args:
        message (str): A human-readable error description
        code (int): The JSON-RPC error code (see messages.py for standard codes)
        data (dict | list | None): Optional additional error data

    Example:
        ```python
        try:
            result = await client.method()
        except JsonRpcException as e:
            if e.code == JSONRPC_METHOD_NOT_FOUND:
                print(f"Method not found: {e}")
            else:
                print(f"RPC error {e.code}: {e}")
        ```
    """

    def __init__(self, message: str, code: int, data: dict | list | None = None):
        super(JsonRpcException, self).__init__(message)
        self.code = code
        self.data = data

    def to_err(self) -> JsonRpcError:
        """Convert the exception to a JSON-RPC error object.

        Returns:
            JsonRpcError: The error object for the JSON-RPC response
        """
        if self.data is not None:
            return JsonRpcError(code=self.code, message=str(self), data=self.data)
        else:
            return JsonRpcError(code=self.code, message=str(self))

    @staticmethod
    def from_error(err: JsonRpcError) -> "JsonRpcException":
        """Create an exception from a JSON-RPC error object.

        Args:
            err (JsonRpcError): The error object from a JSON-RPC response

        Returns:
            JsonRpcException: The corresponding exception
        """
        if "data" in err:
            return JsonRpcException(err["message"], err["code"], err["data"])
        else:
            return JsonRpcException(err["message"], err["code"])


def _check_handler_sig(func: Callable):
    """Check if a handler function has a valid signature.

    Handler functions must accept either only positional arguments or
    only keyword arguments, not both.

    Args:
        func (Callable): The function to check

    Raises:
        ValueError: If the function accepts both positional and keyword arguments
    """
    sig = inspect.signature(func)
    has_positional = False
    has_keyword = False

    params = list(sig.parameters.values())
    if inspect.ismethod(func):
        params = params[1:]

    for param in params:
        match param.kind:
            case inspect.Parameter.POSITIONAL_ONLY | inspect.Parameter.VAR_POSITIONAL:
                has_positional = True
            case inspect.Parameter.KEYWORD_ONLY | inspect.Parameter.VAR_KEYWORD:
                has_keyword = True
            case inspect.Parameter.POSITIONAL_OR_KEYWORD:
                has_positional = True
                has_keyword = True
    if has_positional and has_keyword:
        raise ValueError(
            "Handler functions must accept either only positional arguments or only keyword arguments"
        )


@overload
def method[T: Callable[..., Any]](name: str) -> Callable[[T], T]: ...


@overload
def method[T: Callable[..., Any]](func: T) -> T: ...


def method(name_or_func):
    """Decorator to mark a function as a JSON-RPC method.

    Methods are RPC calls that expect a response. The decorated function must
    be async and cannot also be a notification handler. The function's parameters
    and return type will be used for runtime validation.

    Args:
        name_or_func (str | Callable): Either the method name to use in RPC calls,
            or the function to decorate. If a string is provided, it will be used
            as the method name, otherwise the function's name will be used.

    Returns:
        Callable: The decorated function.

    Raises:
        ValueError: If the decorated function is not async or is already a notification.

    Example:
        ```python
        class Calculator:
            @method
            async def add(self, a: float, b: float) -> float: ...

            @method("multiply")  # Use custom method name
            async def mul(self, a: float, b: float) -> float: ...
        ```

    Note:
        The decorated function must accept either only positional arguments
        or only keyword arguments, not both. This ensures unambiguous parameter
        passing over RPC.
    """
    if isinstance(name_or_func, str):
        name = name_or_func
    else:
        name = name_or_func.__name__

    def decorator[T: Callable[..., Any]](func: T) -> T:
        if not inspect.iscoroutinefunction(func):
            raise ValueError("Only async methods can be RPC methods")
        if getattr(func, "__jsonrpc_notification__", None) is not None:
            raise ValueError("A method can't also be a notification")
        setattr(func, "__jsonrpc_method__", name)
        return func

    if isinstance(name_or_func, str):
        return decorator
    else:
        return decorator(name_or_func)


@overload
def notification[T: Callable[..., Any]](name: str) -> Callable[[T], T]: ...


@overload
def notification[T: Callable[..., Any]](func: T) -> T: ...


def notification(name_or_func):
    """Decorator to mark a function as a JSON-RPC notification handler.

    Notifications are one-way messages that don't expect a response. The decorated
    function must be async and cannot also be a method handler. The function's
    parameters will be used for runtime validation.

    Args:
        name_or_func (str | Callable): Either the notification name to handle,
            or the function to decorate. If a string is provided, it will be used
            as the notification name, otherwise the function's name will be used.

    Returns:
        Callable: The decorated function.

    Raises:
        ValueError: If the decorated function is not async or is already a method.

    Example:
        ```python
        class Logger:
            @notification
            async def log(self, message: str, level: str = "info"): ...

            @notification("system.status")  # Use custom notification name
            async def status(self, status: str): ...
        ```

    Note:
        The decorated function must accept either only positional arguments
        or only keyword arguments, not both. This ensures unambiguous parameter
        passing over RPC.
    """
    if isinstance(name_or_func, str):
        name = name_or_func
    else:
        name = name_or_func.__name__

    def decorator[T: Callable[..., Any]](func: T) -> T:
        if not inspect.iscoroutinefunction(func):
            raise ValueError("Only async methods can be RPC notifications")
        if getattr(func, "__jsonrpc_method__", None) is not None:
            raise ValueError("A notification can't also be a method")
        setattr(func, "__jsonrpc_notification__", name)
        return func

    if isinstance(name_or_func, str):
        return decorator
    else:
        return decorator(name_or_func)


class JsonRpcConnection:
    """Manages a JSON-RPC connection over a transport layer.

    This class handles the core JSON-RPC protocol functionality, including:
    - Message sending and receiving
    - Method and notification routing
    - Request/response correlation
    - Error handling
    - Client proxy generation

    The connection can act as both client and server simultaneously, allowing
    for bidirectional RPC communication. It supports both method calls that
    expect responses and one-way notifications.

    Args:
        transport (JsonRpcTransport): The transport layer to use for communication.
            This handles the actual sending and receiving of messages.

    Example:
        ```python
        # Create a connection
        transport = JsonRpcStreamTransport(reader, writer)
        connection = JsonRpcConnection(transport)

        # Server-side: Register method handlers
        class Calculator:
            @method
            async def add(self, a: float, b: float) -> float:
                return a + b

        calc_server = Calculator()
        connection.rpc_method("add", calc.add)

        await connection.run()

        # Client-side: Create type-safe client
        class CalculatorProtocol:
            @method
            async def add(self, a: float, b: float) -> float: ...

        calc_client = connection.get_client(CalculatorProtocol)
        result = await calc_client.add(2.5, 3.7)
        ```
    """

    def __init__(self, transport: JsonRpcTransport):
        """Initialize the JSON-RPC connection.

        Args:
            transport (JsonRpcTransport): The transport layer to use.
        """
        self._transport = transport
        self._next_id = 0
        self._pending_requests: dict[str | int, asyncio.Future] = {}
        self._noti_tasks: list[asyncio.Task] = []
        self._method_handlers: dict[str, Callable] = {}
        self._noti_handlers: dict[str, Callable] = {}
        self._queue: asyncio.Queue[JsonRpcMessage] = asyncio.Queue()

    def get_client[T](self, proto: Type[T]) -> T:
        """Create a strongly-typed client from a protocol class.

        This method creates a proxy object that implements the given protocol
        by converting method calls into JSON-RPC requests. The protocol class
        should define its methods using the @method and @notification decorators.

        The proxy object provides type safety and IDE support by using the
        protocol's type hints for parameters and return types. All parameters
        and return values are validated at runtime using Pydantic.

        Args:
            proto (Type[T]): A class defining the RPC interface.
                Methods should be decorated with @method or @notification.

        Returns:
            T: A proxy object implementing the class. Method calls on this
                object will be converted to RPC requests.

        Raises:
            ValueError: If the protocol contains non-method attributes or
                methods without proper decorators.

        Example:
            ```python
            class MathService:
                @method
                async def add(self, a: float, b: float) -> float: ...

                @method
                async def multiply(self, a: float, b: float) -> float: ...

                @notification
                async def log_operation(self, op: str): ...

            client = connection.get_client(MathService)
            result = await client.add(2.5, 3.7)  # Type-safe RPC call
            await client.log_operation("add")    # Type-safe notification
            ```
        """
        attributes = {}

        for attr_name in dir(proto):
            if attr_name.startswith("_"):
                continue

            attr = getattr(proto, attr_name)

            if not callable(attr):
                raise ValueError("Clients must only expose methods")

            method: str | None = getattr(attr, "__jsonrpc_method__", None)
            notification: str | None = getattr(attr, "__jsonrpc_notification__", None)
            sig = inspect.signature(attr)

            if method is not None:

                def get_method_impl(name, sig):
                    @validate_call
                    async def method_impl(self, *args, **kwargs):
                        inspect.signature(method_impl).bind(self, *args, **kwargs)
                        return await self._conn.send_request(name, *args, **kwargs)

                    method_impl.__signature__ = sig
                    return method_impl

                attributes[attr_name] = get_method_impl(method, sig)
            elif notification is not None:

                def get_notification_impl(name, sig):
                    @validate_call
                    async def notification_impl(self, *args, **kwargs):
                        inspect.signature(notification_impl).bind(self, *args, **kwargs)
                        await self._conn.send_notification(name, *args, **kwargs)

                    notification_impl.__signature__ = sig
                    return notification_impl

                attributes[attr_name] = get_notification_impl(notification, sig)
            else:
                raise ValueError("Only methods and notifications are supported")
        klass = type(f"JsonRpc{proto.__name__}", (), attributes)
        instance = klass()
        instance._conn = self
        return instance

    def rpc_method(self, method_name: str, func: Callable | None = None):
        """Registers a function as a handler for a specific RPC method.

        The handler function must accept either only positional arguments or only
        keyword arguments.

        Args:
            method_name (str): The name of the RPC method to handle.
            func (Callable | None, optional): The handler function. If None,
                returns a decorator. Defaults to None.

        Returns:
            Callable: A decorator if func is None, otherwise the decorated function.
        """

        def decorator(func):
            _check_handler_sig(func)
            self._method_handlers[method_name] = validate_call(func)
            return func

        if func is None:
            return decorator
        else:
            decorator(func)

    def rpc_notification(self, method_name: str, func: Callable | None = None):
        """Registers a function as a handler for a specific RPC notification.

        The handler function must accept either only positional arguments or only
        keyword arguments.

        Args:
            method_name (str): The name of the RPC notification to handle.
            func (Callable | None, optional): The handler function. If None,
                returns a decorator. Defaults to None.

        Returns:
            Callable: A decorator if func is None, otherwise the decorated function.
        """

        def decorator(func):
            _check_handler_sig(func)
            self._noti_handlers[method_name] = validate_call(func)
            return func

        if func is None:
            return decorator
        else:
            decorator(func)

    async def _send_obj(
        self,
        obj: JsonRpcMessage,
    ):
        logger.debug("Object sent", extra={"jsonRpcMsg": obj})
        await self._transport.send_message(json.dumps(obj))

    async def _send_err(self, id: int | str | None, err: JsonRpcError):
        await self._send_obj(JsonRpcErrorResponse(jsonrpc="2.0", id=id, error=err))

    def _get_params(self, args: list, kwargs: dict) -> list | dict | None:
        if len(args) != 0 and len(kwargs) != 0:
            raise ValueError(
                "Can't send both list and keyword parameters in a JSONRPC request"
            )
        if len(args) != 0:
            return args
        elif len(kwargs) != 0:
            return kwargs
        else:
            return None

    async def send_request(self, method: str, *args, **kwargs):
        """Sends a JSON-RPC request and waits for the response.

        Args:
            method (str): The name of the RPC method to call.
            *args: Positional arguments to pass to the method.
            **kwargs: Keyword arguments to pass to the method.

        Returns:
            Any: The result of the RPC call.

        Raises:
            ValueError: If both positional and keyword arguments are provided.
            JsonRpcException: If the server returns an error response.
        """
        params = self._get_params(list(args), kwargs)

        id = self._next_id
        self._next_id = self._next_id + 1

        loop = asyncio.get_event_loop()
        future = loop.create_future()
        self._pending_requests[id] = future

        if params is not None:
            req = JsonRpcRequest(jsonrpc="2.0", id=id, method=method, params=params)
        else:
            req = JsonRpcRequest(jsonrpc="2.0", id=id, method=method)

        await self._send_obj(req)
        return await future

    async def send_notification(self, method: str, *args, **kwargs):
        """Sends a JSON-RPC notification.

        Args:
            method (str): The name of the notification method.
            *args: Positional arguments to pass to the method.
            **kwargs: Keyword arguments to pass to the method.

        Raises:
            ValueError: If both positional and keyword arguments are provided.
        """
        params = self._get_params(list(args), kwargs)

        if params is not None:
            req = JsonRpcNotification(jsonrpc="2.0", method=method, params=params)
        else:
            req = JsonRpcNotification(jsonrpc="2.0", method=method)

        await self._send_obj(req)

    def _dispatch_handler(self, func: Callable, params: dict | list | None):
        if params is None:
            return func()
        elif isinstance(params, list):
            return func(*params)
        else:
            return func(**params)

    def _handle_notification(self, noti: JsonRpcNotification):
        logger.debug("Handling notification", extra={"jsonRpcMsg": noti})

        method = noti["method"]

        if method not in self._noti_handlers:
            logger.info(
                "Unhandled notification %s",
                method,
                extra={"params": noti.get("params")},
            )
            return

        handler = self._noti_handlers[method]

        async def do_handling(handler: Callable, params: list | dict | None):
            try:
                await self._dispatch_handler(handler, params)
            except ValidationError:
                logger.warning(
                    "Received notification %s with wrong parameter types",
                    method,
                    extra={"params": params},
                    exc_info=True,
                )

        coro = do_handling(handler, noti.get("params"))
        self._noti_tasks.append(asyncio.create_task(coro))

    async def _send_response(self, id: str | int, coro):
        try:
            res = await coro
            await self._send_obj(JsonRpcResult(jsonrpc="2.0", id=id, result=res))
        except JsonRpcException as e:
            await self._send_err(id, e.to_err())
        except ValidationError as e:
            await self._send_err(
                id,
                JsonRpcError(
                    message=str(e), code=JSONRPC_INVALID_REQUEST, data=e.errors()
                ),
            )
        except Exception as e:
            await self._send_err(
                id, JsonRpcError(message=str(e), code=JSONRPC_INTERNAL_ERROR)
            )

    async def _handle_request(self, req: JsonRpcRequest):
        logger.debug("Handling request", extra={"jsonRpcMsg": req})

        method = req["method"]
        id = req["id"]

        if method not in self._method_handlers:
            await self._send_err(
                id,
                JsonRpcError(
                    code=JSONRPC_METHOD_NOT_FOUND, message=f"No method {method} found"
                ),
            )
            return

        handler = self._method_handlers[method]
        coro = self._dispatch_handler(handler, req.get("params"))
        self._noti_tasks.append(asyncio.create_task(self._send_response(id, coro)))

    async def _handle_result(self, res: JsonRpcResult):
        logger.debug("Handling result response", extra={"jsonRpcMsg": res})

        id = res["id"]
        result = res["result"]

        if id is None:
            logger.warning("Received result with no id", extra={"result": result})
            return

        if id not in self._pending_requests:
            logger.warning(
                "Received result for invalid id %s", id, extra={"result": result}
            )
            return

        req = self._pending_requests[id]
        req.set_result(result)
        del self._pending_requests[id]

    async def _handle_error(self, res: JsonRpcErrorResponse):
        logger.debug("Handling error response", extra={"jsonRpcMsg": res})

        id = res["id"]
        error = res["error"]

        if id is None:
            logger.warning("Received error with no id", extra={"error": error})
            return

        if id not in self._pending_requests:
            logger.warning(
                "Received error with invalid id %s", id, extra={"error": error}
            )
            return

        req = self._pending_requests[id]
        req.set_exception(JsonRpcException.from_error(error))
        del self._pending_requests[id]

    async def _receive_one_msg(self):
        msg = await self._transport.receive_message()

        ta = TypeAdapter[JsonRpcMessage](JsonRpcMessage)

        try:
            obj = json.loads(msg)
            return ta.validate_python(obj)
        except json.JSONDecodeError as e:
            raise JsonRpcException(
                code=JSONRPC_PARSE_ERROR,
                message=e.msg,
                data={
                    "pos": e.pos,
                    "lineno": e.lineno,
                    "colno": e.colno,
                },
            ) from e
        except ValidationError as e:
            raise JsonRpcException(
                code=JSONRPC_INVALID_REQUEST, message=e.title, data=e.errors()
            ) from e

    async def _read_messages(self):
        while True:
            try:
                msg = await self._receive_one_msg()
                logger.debug("Received message", extra={"jsonRpcMsg": msg})
                await self._queue.put(msg)
            except JsonRpcException as e:
                await self._send_err(None, e.to_err())

    async def _dispatch_messages(self):
        while True:
            msg = await self._queue.get()
            if "id" in msg:
                if "result" in msg:
                    await self._handle_result(msg)
                elif "error" in msg:
                    await self._handle_error(msg)
                else:
                    await self._handle_request(msg)
            else:
                self._handle_notification(msg)
            self._queue.task_done()

    async def run(self):
        """Runs the JSON-RPC connection.

        This method starts the message processing loop that handles incoming
        messages and dispatches them to the appropriate handlers.

        The loop continues until an error occurs or the connection is cancelled.

        Raises:
            asyncio.CancelledError: If the connection is cancelled.
            Exception: If an unhandled error occurs during message processing.
        """
        try:
            read = asyncio.create_task(self._read_messages())
            dispatch = asyncio.create_task(self._dispatch_messages())

            # Use wait with return_when=FIRST_EXCEPTION to handle failures properly
            done, pending = await asyncio.wait(
                (read, dispatch), return_when=asyncio.FIRST_EXCEPTION
            )

            # Check if any task completed with an exception
            for task in done:
                if task.exception():
                    for fut in self._pending_requests.values():
                        fut.cancel()
                    for noti in self._noti_tasks:
                        noti.cancel()
                    for t in pending:
                        t.cancel()
                    self._pending_requests.clear()
                    self._noti_tasks.clear()
                    # Re-raise the exception that caused the failure
                    raise task.exception()

            # If we get here without an exception, clean up any pending tasks
            for task in pending:
                task.cancel()

        except asyncio.CancelledError as e:
            # Cancel all tasks and futures when the connection is cancelled
            read.cancel()
            dispatch.cancel()
            for fut in self._pending_requests.values():
                fut.cancel()
            for noti in self._noti_tasks:
                noti.cancel()
            self._pending_requests.clear()
            self._noti_tasks.clear()
            raise e
