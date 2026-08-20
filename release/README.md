# ActionFlow Windows 安装包

下载同目录的 `ActionFlow_Setup_v1.0.0.exe`，双击安装后通过开始菜单或桌面快捷方式启动。

- 支持 Windows 10 / 11 x64。
- 应用会自动打开本地白紫工作台，优先使用 `http://127.0.0.1:8767`；若该端口被其他应用占用，会自动选择下一个可用端口。
- 会议数据保存在当前用户的 `%LOCALAPPDATA%\ActionFlow`，卸载程序不会主动删除它。
- 安装包不包含 API Key。需要 AI 分析时，在 `%LOCALAPPDATA%\ActionFlow\settings.env` 填写 `DEEPSEEK_API_KEY=你的密钥` 后重新启动应用。
