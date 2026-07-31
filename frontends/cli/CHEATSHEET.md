# frontends/cli/ 技术盲区速查

用途：owner 在实现 CLI 前端时可能不熟的技术点。

---

## 1. `if __name__ == "__main__":`

- **用途**：模块被导入时不执行 `main()`，只在 `python -m frontends.cli.main` 时执行。
- **出现位置**：`frontends/cli/main.py` 末尾。

---

## 2. `signal.signal(signal.SIGINT, handler)`

- **用途**：捕获 Ctrl-C，优雅退出而不是抛 traceback。
- **最小例子**：
  ```python
  import signal
  import sys

  def on_sigint(signum, frame):
      print("\n[退出]")
      sys.exit(0)

  signal.signal(signal.SIGINT, on_sigint)
  ```
- **出现位置**：`frontends/cli/main.py` 的 `main()` 开头。

---

## 3. `input()` 与 `EOFError`

- **用途**：读用户输入；Ctrl-D / 管道结尾时会抛 `EOFError`。
- **最小例子**：
  ```python
  try:
      line = input(">>> ")
  except EOFError:
      print()
      break
  ```
- **出现位置**：`frontends/cli/main.py` 的 while 循环。

---

## 4. 前端只依赖内核公开 API

- **目前公开 API**：`kernel.loop.run(user_input, ctx, provider)`。
- **原则**：CLI 不直接 import provider 内部，也不绕过 kernel。
- **出现位置**：`frontends/cli/main.py` 顶部 import。
