# Ask Great Thinkers

把一个决定同时问给 **2578 个人**，看这些答案铺开成什么形状。

![世界地图、各文化圈三色条、三张名单](docs/preview.png)

丢进去一句话——「人类要成为一个星际文明吗？」——它先把这句话改写成一句能打分的命题，
再把同一个问题分别问给 2578 位历史上的思想家，一人一次，按他那套框架看这件事：
支持，还是不支持。

每个人**正反两个方向各问一遍取中间**，落在 0–1 上的一个位置。2578 个位置按百年切开，
铺成一张世界地图、一根三色条、三张名单，和一句由这些数字现算出来的结论。
拖着时间轴，整页跟着走——「17 世纪谁最支持」不需要第二次请求。

这是 **should-i** 的第二个子产品。那一半（三个探针 + 一个判断）不在这里；
这里只有一件事：**把同一个问题问全人类，看它铺开成什么形状。**

## 快速开始

Python 3.9+ · 只用标准库，没有依赖、没有构建步骤、没有数据库。

```bash
export TYPESAFE_API_KEY="..."   # Jev：那 5610 次判断
export DEEPSEEK_API_KEY="..."   # DeepSeek：只有一件事——把 X 说出来

python3 app/server.py           # 然后打开 http://127.0.0.1:8420
```

不想碰终端的话，环境变量可以不设：起服务后打开页面底部的**「设置 API key」**，
把两个 key 粘进去，点「保存并测试」——它会各发一次真实请求，告诉你到底通不通。
key 只留在这个进程里，浏览器只跟 `/api/*` 说话。

> 如果这台机器有本地代理（Clash 之类），`http_proxy` 会把发往 `127.0.0.1` 的请求也拦下来，
> 看起来就像服务没起来。给自己配一个：`export no_proxy=127.0.0.1,localhost`。
> `scripts/smoke_test.py` 自己关掉代理，所以不受影响。

**可选环境变量**

| 变量 | 默认 | 作用 |
| --- | --- | --- |
| `TYPESAFE_BASE_URL` | `https://api.typesafe.ai` | Jev 端点 |
| `TYPESAFE_DEFAULT_MODEL` | `jev-latest` | Jev 模型 |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | DeepSeek 端点 |
| `DEEPSEEK_MODEL` | `deepseek-chat` | DeepSeek 模型 |
| `SHOULD_I_JEV_CACHE` | `should_i.jevcache.db` | 上游答案缓存，设成 `0` 整个关掉 |
| `SHOULD_I_SETTINGS` | `should_i.settings.json` | key 文件路径 |
| `PORT` | `8420` | 监听端口 |

## 一次提问要花多少

- **上游请求** —— 11 次 Jev ＋ 1 次 DeepSeek，一共 5,610 次判断
- **token** —— 约 38–41 万输入 / 12 万输出
- **用时** —— Jev 那 11 批约 19 秒、4 条并发，和动画并行
- **开头那次改写要串行等** —— 它定的就是 state，11 批必须等它。实测 0.006s（缓存）／
  1.03s（热）／**7.12s（冷）**，倒计时是它的封面；超过 2 秒会开始报秒数
- **第二次问同一句** —— 免费，缓存命中

## 它怎么工作

```
「人类要成为一个星际文明吗？」
  │
  ├─ DeepSeek ×1    把 X 说出来并对齐方向
  │                 「你支持人类成为一个星际文明吗？」＋同一句英文
  ↓
  ├─ Jev ×11 批     每批 255 人 × 正反两个方向 = 510 次判断，一次请求
  ↓
  ├─ 每人分数 = (正向 − 反向 + 1) / 2
  ↓
  └─ 地图 / 三色条 / 文化圈 / 两头 / 三张名单 / 结论      全部在前端现算
```

里面有四个不显然的地方，每个都是量出来才定下的，不是选出来的：
**只给身份、不给观点**，**每人问两遍**，**用 noul、不用 Choice**，**11 批里放同一组锚**。
为什么，以及各自的实测数字，在 [docs/design.md](docs/design.md)。

## 项目结构

```
app/                 运行的产品本身 —— 服务、页面、名录
  server.py            标准库 HTTP 服务：静态页 + /api/*，key 只留在这个进程里
  index.html           单文件前端：样式 + 原生 JS，无依赖
  thinkers.py          名录、分帧、255 恒等式、noul 题目与 state（纯逻辑，无网络）
  thinkers_data.py     名录本体：2578 位、13 个文化圈、年份 + 经纬度
  thinkers_pinyin.py   拼音索引，给锚点选择面板搜名字用
  upstreams.py         Jev 和 DeepSeek 两个客户端；对模型输出的校验与回退都在这里
  jevcache.py          上游答案缓存：键是请求本身；失败不入库、命中报 0 token
  settings.py          设置页写的 key 文件：读写、0600、掩码（纯逻辑，无网络）
scripts/             一次性工具，不参与运行
  gen_pinyin.py        从 app/thinkers_data.py 重建 app/thinkers_pinyin.py
  smoke_test.py        对着一个跑起来的服务做端到端验证
tests/               纯逻辑测试：无网络、无 key、无浏览器
docs/                设计笔记、架构、页面、名录、已知取舍
```

运行时会多出两个文件——答案缓存和 key 文件——都落在 `app/` 里，也都在
`.gitignore` 里。两者都可以用环境变量换个位置。

## 测试

```bash
python3 tests/test_thinkers.py && python3 tests/test_upstreams.py && python3 tests/test_settings.py
```

纯逻辑测试：无网络、无 key、无浏览器。

```bash
python3 -u app/server.py &
python3 scripts/smoke_test.py "人类要成为一个星际文明吗？"          # 名录 + 改写，不花钱
python3 scripts/smoke_test.py "人类要成为一个星际文明吗？" --run    # 加上那 11 批（真花钱）
```

## 文档

| 文档 | 内容 |
| --- | --- |
| [docs/design.md](docs/design.md) | 每个设计决定，和支撑它的实测数字 |
| [docs/architecture.md](docs/architecture.md) | 一次运行的完整流程、缓存的三条规矩、文件清单 |
| [docs/interface.md](docs/interface.md) | 页面：地图、时间轴、面板、视觉语言 |
| [docs/roster.md](docs/roster.md) | 名录：2578 人、13 个文化圈、来源与偏向 |
| [docs/limitations.md](docs/limitations.md) | 已知的取舍，以及这一页最该被质疑的地方 |

## 已知限制

一句话版本：**「全人类」是 2578 位有英文维基条目的人，其中一半来自西欧 + 北美 + 东欧**，
而画面上是两位小数、跨批次误差却有 0.055。这两条是这张图最大的解释性风险，
展开在 [docs/limitations.md](docs/limitations.md)。

## 许可

MIT，见 [LICENSE](LICENSE)。
