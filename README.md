# NJU Crawler Service

异步爬取南京大学教务网公告、持久化到本地 SQLite，并将正文同步到可替换的向量服务（默认 mock）。下面涵盖部署、运行与排错要点。

## 功能亮点

- **配置化抓取**：`config.py` 中定义目标站点、分页数量、请求头等参数。
- **异步网络与 OCR**：基于 `curl_cffi` 的 TLS 伪装 + `asyncio` 并发，配合 Tesseract OCR 抽取图片文字。
- **去重+持久化**：正文内容计算 SHA256，利用 SQLite (`data/crawler.db`) 做重复过滤，并以 JSON 存储附件元数据。
- **向量服务接口**：`vector_client.py` 统一调用远端存储；开发阶段可用 `mock_vector_service.py` 在本地验证。
- **可扩展的附件处理**：目前支持 PDF、DOCX、内嵌 PDF、以及 OCR 得到的图片文本，便于下游检索。

## 环境准备

1. **Python 3.10+**（示例使用 `.venv310` 虚拟环境）
2. **Tesseract OCR**：确保 `TESSERACT_CMD`、`TESSDATA_DIR` 在 `config.py` 中指向实际路径，并设置 `TESSDATA_PREFIX` 环境变量。
3. **依赖安装**：
   ```powershell
   .\.venv310\Scripts\activate
   pip install -r requirements.txt
   ```

## 运行步骤

1. **确保向量服务 8000 已就绪**（TeamB 的“后端 2”模块）。如果需要本地联调且暂时没有真实服务，可运行 `mock_vector_service.py`，但默认直接对接团队的向量数据库接口。

   ```powershell
   # 仅在无后端 2 时需要临时 mock
   .\.venv310\Scripts\activate
   uvicorn mock_vector_service:app --host 0.0.0.0 --port 8000 --reload
   ```

2. **启动 FastAPI 主服务（端口 8001，符合 TeamB 规范）**
   ```powershell
   .\.venv310\Scripts\activate
   uvicorn main:app --host 0.0.0.0 --port 8001 --reload
   ```

3. **触发一次抓取**
    ```powershell
       Invoke-RestMethod -Uri http://localhost:8001/api/crawl -Method Post `
          -Headers @{ "Content-Type" = "application/json" } `
          -Body '{"source":"bksy_ggtz"}'
    ```

## 配置与定时任务

- **端口与定时**：`config.py` 默认将 `CRAWLER_PORT=8001`、`CRAWL_INTERVAL=3600` 秒、`AUTO_CRAWL_ENABLED=True`，都可通过环境变量覆盖，例如：
  ```powershell
  set CRAWLER_PORT=8001
  set CRAWL_INTERVAL=1800
  set AUTO_CRAWL_ENABLED=true
  ```
- **向量服务端口**：默认 `VECTOR_SERVICE_BASE_URL=http://localhost:8000`，若接入其它端口/服务，只需：
   ```powershell
   set VECTOR_SERVICE_BASE_URL=http://vector-host:8000
   ```
- **自动定时爬取**：服务启动后会在后台按 `CRAWL_INTERVAL` 依次抓取 `TARGET_SOURCES`。若只想手动触发，可把 `AUTO_CRAWL_ENABLED` 设成 `false`。

## 结果验证

- **API 返回**：`data` 列表中的每条 `CrawlItem` 都包含 `content`、`attachments` 等字段。若本次全部为重复记录，`data` 可能为空，属正常现象。
- **SQLite**：检查 `data/crawler.db`，确认记录数及最新插入时间：
   ```powershell
   sqlite3 data/crawler.db "SELECT COUNT(*), MAX(created_at) FROM crawled_records;"
   ```
- **向量服务**：默认对接团队的后端 2，可直接通过其 `/vectors/documents` 接口查看文档；若临时启用 mock，命令如下：
   ```powershell
   Invoke-RestMethod -Uri http://localhost:8000/vectors/documents | ConvertTo-Json -Depth 5
   Invoke-RestMethod -Uri http://localhost:8000/vectors/documents/<document_id>
   ```
- **清空状态（可选）**：
   ```powershell
   Invoke-RestMethod -Uri http://localhost:8000/vectors/documents -Method Delete
   sqlite3 data/crawler.db "DELETE FROM crawled_records;"
   ```

## 常见问题

- **Tesseract 语言包缺失**：确认 `D:\Apps\tesseract\tessdata` 中存在 `chi_sim.traineddata` 与 `eng.traineddata`，并在启动服务前设置 `TESSDATA_PREFIX`。
- **TLS/403 拦截**：所有请求通过 `curl_cffi` 的 Chrome 指纹发送，如依旧被 CAS 拒绝，可在 `TARGET_SOURCES` 中暂时排除需登录的页面。
- **编码乱码**：PowerShell 默认使用 GBK，可执行 `chcp 65001` 或将输出写入 UTF-8 文件后再查看。

## 项目结构

```
├── main.py                # FastAPI 入口
├── router.py              # /api/crawl 路由
├── services.py            # 抓取、解析、异步流程核心
├── storage/database.py    # SQLite 工具
├── vector_client.py       # 向量服务客户端
├── mock_vector_service.py # 本地 mock 服务
├── config.py              # 爬虫与服务配置
├── data/crawler.db        # 默认数据库文件（运行后生成）
└── web_list.txt           # 测试 URL 列表（可选）
```

## 开发提示

- 新增站点时在 `config.TARGET_SOURCES` 填写 `id`、`list_url`、`selectors`、`max_pages` 等信息。
- 调整并发量可修改 `services.MAX_CONCURRENT_DETAIL_REQUESTS`。
- 若将 mock 替换为真实向量服务，仅需更新 `config.VECTOR_SERVICE.base_url` 及 `api_key`。
