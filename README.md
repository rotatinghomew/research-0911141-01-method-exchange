# 检测方法比较工作台

用于教研人员查看本地记录、选择业务范围、核对原始数据并保存复核材料。页面在样品配对明细之外，提供面向方法替换决策的比较：参考方法同样视为带测量误差的观测（Deming 回归，lambda 由复测方差估计），展示偏差随量程的变化、按业务容许误差（绝对项与相对项可在页面编辑）逐段判定的适用范围、实验室与试剂批次差异，并对低于检出限、单方法批次和证据不足区间显式留空或限制说明；每条结论都可追溯到支持它的样品。所有示例都是本地生成的虚构记录，不含个人信息、真实研究数据或受限材料。

## 运行

需要 Python 3.11，运行不依赖第三方服务或第三方包。推荐使用锁定基础镜像的容器；也可以在项目根目录直接启动。

```bash
python3 -m method_exchange --host 127.0.0.1 --port 8080
```

浏览器打开 `http://127.0.0.1:8080`。状态默认保存在 `.state/research.sqlite3`，可用 `--state` 指定独立目录。页面提供范围选择、容许误差编辑、偏差图与量程判定、实验室/批次差异、原始记录查看、完整数据导入、保存和导出。保存的是数据版本、方法选择与当时的容许误差约定，不会因后续导入变化。

```bash
docker build -t method_exchange:local .
docker run --rm -p 8080:8080 -v method_exchange-state:/app/.state method_exchange:local
```

## 检查

```bash
python3 -m unittest discover -s tests -v
```

回归覆盖数据口径、容许误差校验与判定变化、检出限与单方法处理、HTTP 交互、非法导入回滚、误差约定与不可变版本的冻结复开、重启后的历史读取。测试使用临时状态目录，不改变演示数据。详见 `docs/data-contract.md`、`docs/http.md` 和 `docs/walkthrough.md`。如果扩展运行依赖，请同时在依赖清单和镜像中固定版本。

## 构建与浏览器回归

服务只使用 Python 标准库。下列固定版本工具用于构建和自动浏览器检查，不是运行服务的前置依赖。

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements-build.txt -r requirements-test.txt
python3 -m playwright install --with-deps chromium
python3 -m build --wheel --no-isolation
python3 tests/browser_smoke.py
```

自动浏览器检查在随机本地端口启动真实应用，使用临时数据库验证范围切换、容许误差编辑与判定变化、结论到样品的追溯、原始记录、保存复开（含误差约定还原）、导出和幂等导入；结束后关闭浏览器和服务。它不要求预先启动服务器，也不依赖外部数据。`npm start` 是现有 Python 服务的启动别名，支持附加 `--host`、`--port` 参数；`npm run test:browser` 调用同一浏览器回归。npm 锁文件不引入 Node 运行包。

支持 CPython 3.11 系列，产品镜像仍由不可变 digest 固定至同一 Python 3.11.14 镜像；运行兼容性不依赖补丁版本专有行为。上述构建工具和测试工具均通过固定版本清单预装，正式启动和浏览器操作无须下载。
