import asyncio

from pydantic_ai import ModelRetry, RunContext


async def man(ctx: RunContext, page: str) -> str:
    """Reads the man page for a function"""
    man_proc = await asyncio.create_subprocess_shell(
        "xargs --null man -S 2:3:4 -w | xargs mandoc -Tmarkdown",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    (man_out, man_err) = await man_proc.communicate(page.strip().encode())
    if man_proc.returncode != 0 or len(man_err.strip()) != 0:
        raise ModelRetry(man_err.decode())

    return man_out.decode()
