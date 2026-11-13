# Flask 固定版本演示

来源：<https://github.com/pallets/flask>，tag `3.1.2`，commit `2c1b30d0503cfb064f1cb252e6614a06915a362a`。
扫描默认生产范围，tests、docs、examples 均排除；原始 checkout 不在本工具仓库内。

本目录保存完整大纲与扫描快照，以及第 01、12、14 课。完整生成结果有 14 课，原始完整课文保存在演示运行目录。
`verification.*` 对应这里的 3 课：59/323，缺少 264 节点，退出码为 1；
`full-course-verification.*` 是完整 14 课运行时的校验快照：323/323，无效引用 0/323。
仅拉取这 3 课不能复现完整课程的覆盖结果。覆盖完整 ≠ 讲对了，内容正确性需要人看。

`scan.json` 保留文件 SHA256 与源码清单；`topology.json` 包含 4 组循环依赖和 5 个入口的静态可达流程。
`plan.json` 保存拓扑顺序与节点归属；`usage.json` 为真实调用账本，总计 17 次，无密钥和请求正文。
前 2 次用于初版大纲和未采用的课文；修正节点身份、稳定排序和文本格式约束后，最终大纲 1 次、最终课文 14 次。
API 请求成功不等于输出已通过渲染校验，账本按请求次数计。

## 无模型复核样例

从本工具仓库根目录运行：

```bash
git clone --depth 1 --branch 3.1.2 https://github.com/pallets/flask.git ../flask-3.1.2
repo-tutor verify ../flask-3.1.2 --out examples/flask
```

预期输出 `Covered 59/323; invalid citations 0; human review required`，预期退出码 `1`。
报告会被本地重新生成。可用脚本读取 `scan.json`，逐项比较文件 SHA256。

课文的 `src/flask/app.py:534` 以 Flask checkout 为根；对应的在线位置是：
<https://github.com/pallets/flask/blob/2c1b30d0503cfb064f1cb252e6614a06915a362a/src/flask/app.py#L534>。

## 重新生成完整课程

配置 DeepSeek key 后，从工具仓库根目录执行：

```bash
repo-tutor all ../flask-3.1.2 --out ../flask-course-new
```

使用默认设置会产生一次大纲请求和逐课请求；本目录的实测次数含前期调试，不是每次固定成本。
模型输出不保证逐字相同；校验与覆盖检查可重复运行，不再调用模型。
