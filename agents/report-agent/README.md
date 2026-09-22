# Report Agent

规划报告结构，然后直接产出：

- `report.html`
- `report.css`
- `assets/charts/`、`assets/diagrams/`（有图像素材时还有 `assets/images/`）
- 可选 `report.pdf`

内部阶段：研究/分析、正文、图表、引用、版式规划、HTML、PDF。模型只提供正文和数值图表规格，不提供可执行代码。HTML 会转义并去掉 `script` 等标签；PDF 在临时目录里用子进程渲染（Paged.js 或 Playwright），命令行不接受模型输入。

```bash
cd agents/report-agent
pip install -r requirements.txt
uvicorn agent:app --host 0.0.0.0 --port 8003
```

PDF 引擎由 `REPORT_PDF_ENGINE` 选择：`auto`（默认）、`paged`、`browser`、`none`。

- Paged.js：本机已有 `pagedjs-cli`，或设置 `REPORT_PAGEDJS_BIN`
- Browser：已安装 Playwright Chromium 时走 `pipeline/browser_pdf.py`
