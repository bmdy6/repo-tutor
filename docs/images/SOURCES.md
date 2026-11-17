# 图片来源

| 图片 | 类型 | 生成命令 | 数据来源 | SHA-256 |
| --- | --- | --- | --- | --- |
| `docs/images/pipeline.png` | illustration | `node render.mjs html pipeline.html docs/images/pipeline.png 900` | examples/flask/README.md 与 full-course-verification.md 中的数字；无模型调用 | `0d56d8c649c7f23fcd5d33ebcea8b25ee386ea5528db7b29337d3f8fff20d899` |
| `docs/images/flask-lesson.png` | command-run | `node render.mjs md excerpt10.md docs/images/flask-lesson.png 900 560` | examples/flask/lessons/10.md 原文，由 DeepSeek 在演示运行中生成；渲染本身不调用模型 | `a0e9b536a843d8282a57315cc73b877b2693d6c16ae1d43d927084f2d894a217` |

类型含义：illustration 是示意图，command-run 是真实输出的截图。渲染脚本用 Playwright 把 HTML/Markdown 截成 PNG，未随仓库分发。
