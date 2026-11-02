# 公开来源连接

FF只发逻辑请求并接收版本化结果，不读取CWP私有数据库或在业务流程中探测其配置布局。

旧配置 `schema_version: "1.0"`、`company_wiki_root` 继续有效。新部署可用 `connection` 代替物理根：

```json
{
  "schema_version": "1.0",
  "connection": {
    "cwd": "C:/source-service-launcher",
    "commands": {
      "catalog": ["python", "catalog-service.py"],
      "query": ["python", "query-service.py"],
      "local_prepare": ["python", "prepare-service.py"],
      "open": ["python", "read-service.py"],
      "transcript_import": ["python", "import-service.py"],
      "financial_statements": ["python", "statement-service.py"]
    }
  }
}
```

命令前缀由部署者提供，接收对应公开CLI的操作参数、JSON输入或原文/receipt管道。前缀可包含生产者自己的配置参数；FF不补猜它的目录。cwd与可选acquisition_config相对所选FF配置文件解析。明确connection中缺少实际需要的operation时报告配置错误，不回退到默认邻仓。所有旧CLI命令/根/src定位只由ff_company_wiki_connection.py兼容适配器处理。

库入口resolve_filing的company_wiki_root参数也可传WikiConnection；不是只能从CLI选连接。传入配置路径与显式连接二选一。原文verified-open由CWP负责当前根、真实字节与来源校验，FF只使用公开候选/SourceRef；实际下载意图和额度来自请求。

ET的非零业务返回由ET协议分类；网络超额、超时、输入未写完仍是传输故障。原始文件额度独立于已经消耗的网络余额，CWP入库不重复扣下载字节。当前默认预算仍保留，显式更大的合法预算不能被隐藏的16MiB/25MiB帽盖回。

普通CI不检出邻仓。真实跨仓节点已经迁入company-wiki/integration，见该目录README和迁移表；大节点在ROOT跑，不给每次commit增加多仓全量。
