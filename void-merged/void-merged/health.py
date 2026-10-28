import logging

from aiohttp import web


async def start_health_server(host: str, port: int) -> web.AppRunner:
    """Поднимает /, /health -> 'OK'. Возвращает runner, его нужно cleanup() при остановке."""

    async def ok(_request):
        return web.Response(text="OK")

    app = web.Application()
    app.router.add_get("/", ok)
    app.router.add_get("/health", ok)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, host=host, port=port).start()
    logging.getLogger("health").info("Health-сервер: %s:%s", host, port)
    return runner
