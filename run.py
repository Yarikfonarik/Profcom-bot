# run.py — запуск с автоперезагрузкой при изменении файлов
from watchfiles import run_process


def target():
    import asyncio
    from main import main
    asyncio.run(main())


if __name__ == "__main__":
    run_process(".", target=target)
