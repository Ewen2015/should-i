# Ask Great Thinkers

**把一个问题交给全人类的思想家，看答案铺开成什么形状。**

![世界地图、各文化圈三色条、三张名单](docs/preview.png)

丢进去一句话——「如果有机会，我要去火星移民吗？」——它先把这句话改写成一句能打分的命题，
再把同一个问题问给历史上的思想家，一人一次，按自己那套框架看这件事：支持，还是不支持。

每个人**正反两个方向各问一遍取中间**，落在 0–1 上的一个位置；所有位置按百年切开，
铺成一张世界地图、一根三色条、三张名单，和一句由这些数字现算出来的结论。
拖着时间轴，整页跟着走——「17 世纪谁最支持」不需要第二次请求。

这是 **should-i** 的第二个子产品。那一半（三个探针 + 一个判断）不在这里；
这里只有一件事：**把同一个问题问给全人类的思想家，看它铺开成什么形状。**

## 全量询问

这个产品的目的不是「问了多少人」，而是**建立一种全量询问的框架**。有三件事不做：

- **不抽样。** 名录上的人一个不落，全部被问到，不做子采样，也不挑「有代表性」的那几个。
  这不是一句承诺——分帧必须覆盖名录里的每一个人，这条有测试盯着。
- **不检索。** 检索交给你的永远是「最像的几个」，一个排好序的子集；这里每个点都被单独
  给了一个读数，各自落在 0–1 上，然后才铺成形状。
- **不排名。** 地图、三百年切片、直方图、三张名单都是**同一个空间的投影**；
  「最反对的三个人」是空间的一处切片，不是检索的前三名。

**提问需要框架，回答不需要。** 一个人可以不知道自己该怎么活，但他知道自己支持还是反对一件事。
所以这里不做更聪明的聊天框，而是把提问权从个人手里拿走：问题从读者那一句话来，
每个人只给出自己的位置。

模型也不是聊天对象，是电钻。预训练模型是压缩到一起的矿脉，jev-like 是钻头，这条产品线
要建的是**钻井平台**，`ask great thinkers` 是第一口井。展开在 [docs/philosophy.md](docs/philosophy.md)。

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
「如果有机会，我要去火星移民吗？」
  │
  ├─ DeepSeek ×1    把 X 说出来并对齐方向
  │                 「你支持去火星移民吗？」＋同一句英文
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
docs/                设计笔记、架构、页面、名录、已知取舍、产品哲学、路演幻灯
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
python3 scripts/smoke_test.py "如果有机会，我要去火星移民吗？"          # 名录 + 改写，不花钱
python3 scripts/smoke_test.py "如果有机会，我要去火星移民吗？" --run    # 加上那 11 批（真花钱）
```

## 文档

| 文档 | 内容 |
| --- | --- |
| [docs/philosophy.md](docs/philosophy.md) | 产品哲学：为什么是让所有人回答问题，为什么是做井而不是做聊天框 |
| [docs/design.md](docs/design.md) | 每个设计决定，和支撑它的实测数字 |
| [docs/architecture.md](docs/architecture.md) | 一次运行的完整流程、缓存的三条规矩、文件清单 |
| [docs/interface.md](docs/interface.md) | 页面：地图、时间轴、面板、视觉语言 |
| [docs/roster.md](docs/roster.md) | 名录：2578 人、13 个文化圈、来源与偏向 |
| [docs/limitations.md](docs/limitations.md) | 已知的取舍，以及这一页最该被质疑的地方 |
| [docs/slides.html](docs/slides.html) | 路演用的七页幻灯：一个 HTML，← → 翻页，也能直接打印成 PDF |
| [docs/wechat.md](docs/wechat.md) | 公众号用的产品介绍：一次真实运行，文字配五张截图 |

## 已知限制

**「全量」是这个框架要做到的事，不是当前这份名录已经做到的事。** 现在的「全人类」
是 2578 位有英文维基条目的人，其中一半来自西欧 + 北美 + 东欧；而画面上是两位小数、
跨批次误差却有 0.055。这两条是这张图最大的解释性风险，
展开在 [docs/limitations.md](docs/limitations.md)。

## 许可

MIT，见 [LICENSE](LICENSE)。

幻灯里有**两张照片不在 MIT 授权范围内**，它们有自己的授权，署名必须跟着它们走。

**第 6 页 · 太阳与行星**

- 文件：[Planets and sun size comparison.jpg](https://commons.wikimedia.org/wiki/File:Planets_and_sun_size_comparison.jpg)，来自 Wikimedia Commons
- 作者：**Lsmpascal**（自己的作品）
- 授权：[CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/)，署名必须保留；改动后的版本必须以同一授权发布

这张照片在 [WeatherSTEM 的课程页](https://learn.weatherstem.com/modules/learn/lessons/127/06.html) 上也能找到，而那一页自己把它标注为来自维基百科。

**第 7 页 · 恒星大小对比（参宿四 / 心宿二）**

- **原始出处未确认。** 对照过 Wikimedia Commons 的
  [Star size comparisons](https://commons.wikimedia.org/wiki/Category:Star_size_comparisons)
  分类里最接近的十几张（Star-sizes、Comparison of planets and stars、Well known stars 2、
  Large Stars Comparison、Antares 系列），没有一张是它，也不是它们的裁剪。
- 所以幻灯上写的是「网络流传 · 原始出处待考」，而不是编一个署名。
- **对外路演前请替换成有明确授权的图**——上面那个分类里有可直接用的替代品，
  换掉时记得同时改幻灯上的署名行。
