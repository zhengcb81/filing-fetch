# W19 开工唯一入口

完整目标：[施工卡](inputs/construction_card.md)。一个harness负责两个独立工区，先读各自AGENTS及本计划三文件。

- 主工作目录：`C:/Users/郑曾波/Projects/company-wiki-w19-sina-statements`。
- 配套FF目录：`C:/Users/郑曾波/Projects/filing-fetch-w19-sina-statements`。
- 固定`PLAN_ID=w19-sina-statements-2026-10-25`、`PWF_PLAN_ROOT=docs/plans`。
- 当前仅ROOT文档seed，未实施。用户派发后A中性RED→B共享owner→C真实E2E/独审全部修复再交接，不等小步骤签收。主交接在CWP `delivery/w19/handoff.md/json`，引用FF实现commit；正常提交推支线，不merge master/同步安装。
- 不改W16/W17/W18或ROOT narrative/document_understanding路径。前三卡COMMON零下载只适用前三卡，本卡按完整卡做有界公开真实测试；0LLM、0收费、原件/生产配置库不动。

## 解释器与执行来源

新工区不复制.venv，可复用已有解释器读取依赖。测试子进程用局部env/PYTHONPATH或隔离部署，确认`company_wiki.__file__`和FF脚本来自本卡工区，而非可编辑安装指向主仓；记录实际执行源码SHA。FF测试配置指独占测试湖，不指生产catalog。不改永久环境或安装副本。
