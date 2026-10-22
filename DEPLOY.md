# 免费部署

源码保存在 GitHub，Python 应用运行在 Streamlit Community Cloud。GitHub Pages 无法直接运行此 Python 服务。

1. 登录 https://share.streamlit.io ，连接 GitHub。
2. Create app → Deploy a public app from GitHub。
3. Repository：`xu20080725xu-jpg/deepseek-quant-lab`；Branch：`main`；Main file path：`cloud_app.py`。
4. Advanced settings 选择 Python 3.14（与本地验证版本一致；云端实际支持版本以平台为准）。依赖使用 `requirements.txt`。
5. 不填 Secrets 也能部署并使用访客历史行情、离线示例、回测和实验导出。

## 启用站主 AI

在自己的电脑运行：

```bash
.venv/bin/python scripts/create_access_hash.py
```

输入独立的至少16字符口令（终端不回显），复制程序输出的哈希配置。在应用 Settings → Secrets 中填写：

```toml
QUANTLAB_PASSWORD_HASH = "程序输出的完整哈希"
DEEPSEEK_API_KEY = "你的真实Key"
DEEPSEEK_MODEL = "deepseek-flash"
```

不要把真实配置提交到 GitHub，不要在聊天中发送口令或 Key。网页左侧「站主登录」输入原口令，再在「系统设置」测试官方 API 连接。DeepSeek 调用费用由 API 账户承担，网站托管免费不代表模型调用免费。

## 数据和访问边界

- 访客只看到自己的临时 SQLite 与行情缓存；刷新建立新会话后可能丢失。
- 站主登录后使用单独的云端研究数据库；本机数据库、行情缓存、API Key 不上传。
- 云端磁盘不作为可靠备份。应用重启、休眠或重新部署后数据可能丢失；重要实验及时导出 JSON。
- 首次启动和休眠唤醒可能较慢。大陆不同网络可达性不保证；不能将一次成功访问当作全国直连验证。
- 行情来自公开研究接口，可能被限流或拒绝云服务器访问；失败会明确报错，可使用明确标注的合成示例。没有保证实时的数据。
- 所有真实下单、自动模拟交易仍关闭。公网站点不会向访问者提供投资建议。
- 本地使用 `start.command`，它明确绑定 `127.0.0.1`。云端使用 `cloud_app.py`；勿用 `app.py` 作为公网上线入口。

官方说明：[部署](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app)、[Secrets](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management)。
