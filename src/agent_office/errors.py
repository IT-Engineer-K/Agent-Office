"""Domain errors and exit codes for Agent Office."""

from __future__ import annotations

from enum import IntEnum


class ExitCode(IntEnum):
    OK = 0
    INVALID_ARGS = 2
    NOT_FOUND = 3
    CONFLICT = 4
    PERMISSION_DENIED = 5
    ADAPTER_ERROR = 6
    STORAGE_ERROR = 7


class AgentOfficeError(Exception):
    """Base domain error with stable error code and CLI exit code."""

    code: str = "ERROR"
    exit_code: int = int(ExitCode.STORAGE_ERROR)

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        exit_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if exit_code is not None:
            self.exit_code = int(exit_code)


class InvalidArgumentsError(AgentOfficeError):
    code = "INVALID_ARGS"
    exit_code = int(ExitCode.INVALID_ARGS)


class NotFoundError(AgentOfficeError):
    code = "NOT_FOUND"
    exit_code = int(ExitCode.NOT_FOUND)


class ConflictError(AgentOfficeError):
    code = "CONFLICT"
    exit_code = int(ExitCode.CONFLICT)


class ChannelNotAllowedError(AgentOfficeError):
    code = "PERMISSION_DENIED"
    exit_code = int(ExitCode.PERMISSION_DENIED)


class AdapterError(AgentOfficeError):
    code = "ADAPTER_ERROR"
    exit_code = int(ExitCode.ADAPTER_ERROR)


class StorageError(AgentOfficeError):
    code = "STORAGE_ERROR"
    exit_code = int(ExitCode.STORAGE_ERROR)
