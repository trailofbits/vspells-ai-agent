import asyncio
import inspect
import json
from typing import Callable
from pydantic import TypeAdapter, ValidationError
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
    def __init__(
        self, message: str, code: int, data: str | int | dict | list | None = None
    ):
        super(JsonRpcException, self).__init__(message)
        self.code = code
        self.data = data

    def to_err(self) -> JsonRpcError:
        if self.data is not None:
            return JsonRpcError(code=self.code, message=str(self), data=self.data)
        else:
            return JsonRpcError(code=self.code, message=str(self))

    @staticmethod
    def from_error(err: JsonRpcError):
        if "data" in err:
            return JsonRpcException(err["message"], err["code"], err["data"])
        else:
            return JsonRpcException(err["message"], err["code"])


class JsonRpcConnection:
    def __init__(self, transport: JsonRpcTransport):
        self._transport = transport
        self._next_id = 0
        self._pending_requests: dict[str | int, asyncio.Future] = {}
        self._noti_tasks: list[asyncio.Task] = []
        self._method_handlers: dict[str, Callable] = {}
        self._noti_handlers: dict[str, Callable] = {}
        self._queue = asyncio.Queue()

    def rpc_method(self, method_name: str):
        def decorator(func):
            self._method_handlers[method_name] = func
            return func

        return decorator

    def rpc_notification(self, method_name: str):
        def decorator(func):
            self._noti_handlers[method_name] = func
            return func

        return decorator

    async def _send_obj(
        self,
        obj: JsonRpcMessage,
    ):
        await self._transport.send_message(json.dumps(obj))

    async def _send_err(self, id: int | str | None, err: JsonRpcError):
        await self._send_obj(JsonRpcErrorResponse(jsonrpc="2.0", id=id, error=err))

    async def send_request(self, method: str, params: list | dict | None):
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

    async def send_notification(self, method: str, params: list | dict | None):
        if params is not None:
            req = JsonRpcNotification(jsonrpc="2.0", method=method, params=params)
        else:
            req = JsonRpcNotification(jsonrpc="2.0", method=method)

        await self._send_obj(req)

    def _handle_notification(self, noti: JsonRpcNotification):
        method = noti["method"]

        if method not in self._noti_handlers:
            return

        handler = self._noti_handlers[method]

        if "params" not in noti:
            coro = handler()
        else:
            params = noti["params"]

            # Convert list params to positional args, dict params to keyword args
            if isinstance(params, list):
                coro = handler(*params)
            elif isinstance(params, dict):
                sig = inspect.signature(handler)
                # Filter the params dict to only include parameters the handler accepts
                filtered_params = {
                    k: v for k, v in params.items() if k in sig.parameters
                }
                coro = handler(**filtered_params)
        self._noti_tasks.append(asyncio.create_task(coro))

    async def _send_response(self, id: str | int, coro):
        try:
            res = await coro
            await self._send_obj(JsonRpcResult(jsonrpc="2.0", id=id, result=res))
        except JsonRpcException as e:
            await self._send_err(id, e.to_err())
        except Exception as e:
            await self._send_err(
                id, JsonRpcError(message=str(e), code=JSONRPC_INTERNAL_ERROR)
            )

    async def _handle_request(self, req: JsonRpcRequest):
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

        if "params" not in req:
            coro = handler()
        else:
            params = req["params"]

            # Convert list params to positional args, dict params to keyword args
            if isinstance(params, list):
                coro = handler(*params)
            elif isinstance(params, dict):
                sig = inspect.signature(handler)
                # Filter the params dict to only include parameters the handler accepts
                filtered_params = {
                    k: v for k, v in params.items() if k in sig.parameters
                }
                coro = handler(**filtered_params)
        self._noti_tasks.append(asyncio.create_task(self._send_response(id, coro)))

    async def _handle_result(self, res: JsonRpcResult):
        id = res["id"]
        result = res["result"]

        if id is None:
            logger.warning("Received result %s with no id", result)
            return

        if id not in self._pending_requests:
            logger.warning("Received result %s for invalid id %s", result, id)
            return

        req = self._pending_requests[id]
        req.set_result(result)
        del self._pending_requests[id]

    async def _handle_error(self, res: JsonRpcErrorResponse):
        id = res["id"]
        error = res["error"]

        if id is None:
            logger.warning("Received error %s with no id", error)
            return

        if id not in self._pending_requests:
            logger.warning("Received error %s with invalid id %s", error, id)
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
                await self._queue.put(await self._receive_one_msg())
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
