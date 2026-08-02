# tests/ 技术盲区速查

用途：owner 写测试时可能不熟的技术点（pytest）。

---

## 1. 怎么跑测试

- **用途**：一条命令跑全部测试。
- **最小例子**：
  ```
  python -m pytest      # 跑全部
  python -m pytest -v   # 显示每个用例名
  ```
- **注意**：`pytest.ini` 已配置 `pythonpath = .`（让测试能 `import kernel`）和 `testpaths = tests`（只扫 tests/）。
- **出现位置**：项目根目录 `pytest.ini`。

---

## 2. 断言用原生 `assert`

- **用途**：pytest 不需要 `assertEquals`/`assertTrue` 那套，直接用 Python 的 `assert`，失败时 pytest 自动给出详细对比。
- **最小例子**：
  ```python
  assert result == "hi"
  assert [m.role for m in ctx.history] == ["system", "user", "assistant"]
  ```
- **出现位置**：`tests/test_loop.py` 各用例。

---

## 3. 测试函数就是普通函数

- **用途**：文件名 `test_*.py`、函数名 `test_*`，pytest 自动收集。
- **最小例子**：
  ```python
  def test_first_run_injects_system_prompt():
      ...
  ```
- **出现位置**：`tests/test_loop.py`。

---

## 4. `pytest.raises` —— 断言"应该抛异常"

- **用途**：测错误路径：希望某段代码抛异常，且异常类型正确。若没抛，用例直接失败。
- **最小例子**：
  ```python
  with pytest.raises(APIError):
      run("hello", ctx, FakeProvider(error=APIError("boom")))
  ```
- **出现位置**：`tests/test_loop.py::test_api_error_rolls_back_history`。

---

## 5. FakeProvider：测试替身，不联网

- **用途**：测试 kernel 时不想真调 LLM（慢、要 key、不可控）。用"假 provider"替身，返回写死的回复或抛写死的错。
- **最小例子**：
  ```python
  class FakeProvider(Provider):
      def chat(self, messages, **kwargs):
          return Response(content="ok")
  ```
- **出现位置**：`tests/test_loop.py` 顶部。

---

## 6. 假绿陷阱：没有断言的测试直接 PASS

- **用途**：提醒——函数体里没有 `assert` 的测试，pytest 直接判 PASS（空转通过），什么都不证明。看到绿先确认里面有没有真 assert。
- **最小例子**：
  ```python
  def test_foo():
      pass   # 这是假绿，别信
  ```
- **出现位置**：任何新写的测试都检查一遍。
