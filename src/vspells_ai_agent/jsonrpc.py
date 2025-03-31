import asyncio
import inspect
import json
from typing import TypedDict, Literal, NotRequired, Callable


class JsonRpcRequest(TypedDict):
    jsonrpc: Literal["2.0"]
    method: str
    params: dict | list
    id: NotRequired[str | int]


class JsonRpcResult(TypedDict):
    jsonrpc: Literal["2.0"]
    result: str | int | dict | list
    id: str | int


class JsonRpcError(TypedDict):
    code: int
    message: str
    data: NotRequired[str | int | dict | list]


class JsonRpcErrorResponse(TypedDict):
    jsonrpc: Literal["2.0"]
    error: JsonRpcError
    id: str | int


JSONRPC_PARSE_ERROR = -32700
JSONRPC_INVALID_REQUEST = -32600
JSONRPC_METHOD_NOT_FOUND = -32601
JSONRPC_INVALID_PARAMS = -32602
JSONRPC_INTERNAL_ERROR = -32603


class JsonRpcClient:
    _reader: asyncio.StreamReader
    _writer: asyncio.StreamWriter
    _next_id = 0
    _pending_requests: dict[int, asyncio.Future] = {}
    _receive_task: asyncio.Task | None = None
    _message_queue: asyncio.Queue
    _running: bool = False
    _rpc_methods: dict[str, Callable] = {}

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self._message_queue = asyncio.Queue()
        (self._reader, self._writer) = (reader, writer)

    async def start(self):
        """Start the client and message processing tasks"""
        if self._receive_task is None:
            self._running = True
            # Create and store both tasks so we can properly manage them
            self._receive_task = asyncio.create_task(self._receive_messages())
            self._process_task = asyncio.create_task(self._process_messages())

            # Add done callbacks to handle unexpected task termination
            self._receive_task.add_done_callback(self._on_task_done)
            self._process_task.add_done_callback(self._on_task_done)

    def _on_task_done(self, task):
        """Handle task completion, including unexpected errors."""
        try:
            # This will re-raise any exception that caused the task to terminate
            task.result()
        except asyncio.CancelledError:
            # Normal cancellation during shutdown, ignore
            pass
        except Exception:
            # If we're not already shutting down, initiate shutdown
            if self._running:
                print("Critical error in task, initiating shutdown")
                # Create a new task to handle shutdown to avoid deadlocks
                asyncio.create_task(self.stop())
            raise

    async def stop(self):
        """Stop the client and cancel all pending tasks"""
        if not self._running:
            return  # Already stopping or stopped

        self._running = False

        # Cancel both tasks
        if self._receive_task and not self._receive_task.done():
            self._receive_task.cancel()

        if (
            hasattr(self, "_process_task")
            and self._process_task
            and not self._process_task.done()
        ):
            self._process_task.cancel()

        # Wait for tasks to complete cancellation
        pending = []
        if self._receive_task and not self._receive_task.done():
            pending.append(self._receive_task)
        if (
            hasattr(self, "_process_task")
            and self._process_task
            and not self._process_task.done()
        ):
            pending.append(self._process_task)

        if pending:
            # Wait with a timeout
            try:
                await asyncio.wait(pending, timeout=5)
            except Exception:
                print("Error while waiting for tasks to cancel")

        self._receive_task = None
        if hasattr(self, "_process_task"):
            self._process_task = None

        # Cancel all pending requests
        for future in self._pending_requests.values():
            if not future.done():
                future.cancel()
        self._pending_requests.clear()

        # Close writer if it exists
        if hasattr(self, "_writer") and self._writer:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass

    async def _read_headers(self) -> dict[str, str]:
        res: dict[str, str] = {}
        row = await self._reader.readuntil(b"\r\n")
        while row != b"\r\n":
            [name, value] = row.split(b":", 1)
            res[name.strip().lower().decode()] = value.strip().decode()
            row = await self._reader.readuntil(b"\r\n")
        return res

    def _write_headers(self, headers: dict[str, str]):
        for key, value in headers.items():
            self._writer.write(f"{key}: {value}\r\n".encode())
        self._writer.write(b"\r\n")

    async def _read_body(
        self, length: int
    ) -> JsonRpcRequest | JsonRpcResult | JsonRpcErrorResponse:
        content = await self._reader.readexactly(length)
        return json.loads(content)

    async def _write_response(
        self, body: JsonRpcRequest | JsonRpcResult | JsonRpcErrorResponse
    ):
        contents = json.dumps(body).encode()
        self._write_headers(
            {
                "Content-Type": "application/json;charset=utf-8",
                "Content-Length": str(len(contents)),
            }
        )
        self._writer.write(contents)
        await self._writer.drain()

    async def _receive_messages(self):
        """Task that receives messages and puts them in the queue"""
        try:
            while self._running:
                headers = await self._read_headers()
                if "content-length" not in headers:
                    continue

                length = int(headers["content-length"])
                body = await self._read_body(length)
                await self._message_queue.put(body)

        except asyncio.CancelledError:
            return
        except asyncio.IncompleteReadError:
            self._running = False
            return
        except Exception:
            self._running = False
            raise

    async def _process_messages(self):
        """Task that processes messages from the queue"""
        try:
            while self._running:
                body = await self._message_queue.get()

                try:
                    if "method" in body:
                        if "id" in body:
                            # Handle request
                            try:
                                res = await self._handle_request(
                                    body["method"], body["params"]
                                )
                                response = {
                                    "jsonrpc": "2.0",
                                    "result": res,
                                    "id": body["id"],
                                }
                                await self._write_response(response)
                            except Exception as e:
                                error_response = {
                                    "jsonrpc": "2.0",
                                    "error": {
                                        "code": JSONRPC_INTERNAL_ERROR,
                                        "message": str(e),
                                        "data": None,
                                    },
                                    "id": body["id"],
                                }
                                await self._write_response(error_response)
                        else:
                            # Handle notification
                            await self.handle_notification(
                                body["method"], body["params"]
                            )
                    elif "result" in body and "id" in body:
                        # Handle response
                        req_id = body["id"]
                        if isinstance(req_id, int) and req_id in self._pending_requests:
                            future = self._pending_requests.pop(req_id)
                            if not future.done():
                                future.set_result(body["result"])
                    elif "error" in body and "id" in body:
                        # Handle error
                        req_id = body["id"]
                        if isinstance(req_id, int) and req_id in self._pending_requests:
                            future = self._pending_requests.pop(req_id)
                            if not future.done():
                                future.set_exception(
                                    RuntimeError(body["error"]["message"])
                                )
                finally:
                    self._message_queue.task_done()

        except asyncio.CancelledError:
            return
        except Exception:
            self._running = False
            raise

    def rpc_method(self, method_name: str):
        def decorator(func):
            self._rpc_methods[method_name] = func
            return func

        return decorator

    async def _handle_request(
        self, method: str, params: dict | list
    ) -> str | int | dict | list:
        """Handle an incoming JSON-RPC request.
        Dispatches to registered methods or falls back to handle_unknown_request.
        """
        if method in self._rpc_methods:
            handler = self._rpc_methods[method]
            sig = inspect.signature(handler)

            # Convert list params to positional args, dict params to keyword args
            if isinstance(params, list):
                return await handler(*params)
            elif isinstance(params, dict):
                # Filter the params dict to only include parameters the handler accepts
                filtered_params = {
                    k: v for k, v in params.items() if k in sig.parameters
                }
                return await handler(**filtered_params)
            else:
                return await handler()
        else:
            return await self.handle_unknown_request(method, params)

    async def handle_unknown_request(
        self, method: str, params: dict | list
    ) -> str | int | dict | list:
        """Handle requests for which no method handler is registered.

        Override this method to provide custom handling for unregistered methods.
        By default, it raises a method not found error.
        """
        error = {
            "code": JSONRPC_METHOD_NOT_FOUND,
            "message": f"Method {method} not found",
        }
        raise RuntimeError(error["message"])

    async def handle_notification(self, method: str, params: dict | list):
        """Handle an incoming JSON-RPC notification.

        Similar to handle_request but for notifications (which have no response).
        Uses the same registered methods as handle_request.
        """
        if method in self._rpc_methods:
            handler = self._rpc_methods[method]
            sig = inspect.signature(handler)

            # Convert list params to positional args, dict params to keyword args
            if isinstance(params, list):
                await handler(*params)
            elif isinstance(params, dict):
                # Filter the params dict to only include parameters the handler accepts
                filtered_params = {
                    k: v for k, v in params.items() if k in sig.parameters
                }
                await handler(**filtered_params)
            else:
                await handler()
        else:
            await self.handle_unknown_notification(method, params)

    async def handle_unknown_notification(self, method: str, params: dict | list):
        """Handle notifications for which no method handler is registered.

        Override this method to provide custom handling for unregistered notifications.
        By default, it logs a warning and ignores the notification.
        """
        print(
            f"Warning: Notification for unknown method '{method}' received and ignored"
        )

    async def send_request(self, method: str, params: dict | list):
        """Send a request and return a future for the result"""
        if not self._running:
            raise RuntimeError("Client not running. Call start() first.")

        req_id = self._next_id
        self._next_id += 1

        request: JsonRpcRequest = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": req_id,
        }

        loop = asyncio.get_event_loop()
        future = loop.create_future()
        self._pending_requests[req_id] = future

        # Create a task for the write operation to avoid blocking
        await self._write_response(request)

        # Create a timeout for the request
        try:
            return await asyncio.wait_for(future, timeout=30)  # 30 seconds timeout
        except asyncio.TimeoutError:
            # Remove the future from pending requests
            if req_id in self._pending_requests:
                self._pending_requests.pop(req_id)
            raise TimeoutError(f"Request {method} timed out after 30 seconds")

    async def send_notification(self, method: str, params: dict | list):
        """Send a notification"""
        if not self._running:
            raise RuntimeError("Client not running. Call start() first.")

        request: JsonRpcRequest = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }

        # Create a task for the write operation to avoid blocking
        await self._write_response(request)
