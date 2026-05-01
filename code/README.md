# 中亚新闻地图

抓取中亚五国新闻，AI 翻译为中文，按地点呈现在地图上。

## 项目结构

```
code/
├── backend/              FastAPI 后端
│   ├── app.py            主程序：抓取 + 翻译 + API
│   ├── requirements.txt  Python 依赖
│   └── start.sh          启动脚本
├── frontend/             静态前端
│   ├── index.html        页面 + 高德地图
│   └── build.sh          Render 构建脚本（替换环境变量）
├── render.yaml           Render Blueprint（一键部署配置）
├── local-dev.sh          本地开发：mock 数据 + 浏览器打开
├── local-stop.sh         停止本地服务
└── .gitignore
```

## 本地测试（不需要任何 API key）

```bash
bash local-dev.sh
# 浏览器打开 http://127.0.0.1:8764
```

如果你有高德 key，可以让地图也加载：
```bash
bash local-dev.sh 你的高德key
```

## 部署到 Render

详见 `../部署清单.md`。

简短版：
1. 把这个 `code/` 文件夹推到 GitHub
2. 在 Render 创建 Blueprint，选这个仓库
3. 部署后台填 3 个环境变量：
   - 后端 service：`ANTHROPIC_API_KEY`
   - 前端 service：`AMAP_KEY` `API_BASE`
4. 完成
