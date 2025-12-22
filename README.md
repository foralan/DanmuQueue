# DanmuQueue (本地排队姬)

无 GUI，本地启动一个程序后，用浏览器打开管理页 `/admin`，点击“启动”后启用展示页 `/overlay`（OBS 浏览器源可直接抓取）。支持：

- 队列显示：`0` 号为当前服务用户，`1..n` 为等待
- 队列管理：移除 / 置顶到 1 号 / 标记
- 满队列提示：“排队已满”（`max_queue` 限制 **总人数：current+waiting**）
- 样式：内置默认透明样式 + `custom.css` 覆盖
- 弹幕来源：优先 B 站开放平台；否则 SESSDATA(web)；都没有则无法启动监听
- 测试注入：`/test` 页面通过 HTTP 注入弹幕，后端按 keyword 真检测

## 运行

在项目根目录：

```bash
uv sync
source .venv/bin/activate
python -m app.run
```

首次运行会自动生成：

- `./config.yaml`
- `./custom.css`

程序会自动打开：`http://127.0.0.1:10000/admin`

## 页面

- 管理页：`/admin`
  - 配置：标题/关键词/最大队列/CSS 路径/弹幕配置
  - Runtime：启动/停止、启用测试弹幕、显示 overlay URL
  - 队列：移除/置顶/标记
- 展示页：`/overlay`
  - stopped：提示“未启动”
  - running：显示队列 + 满队列提示
- 测试页：`/test`
  - 仅 `running && 启用测试弹幕` 时可用

## 配置文件 `config.yaml`

默认值（自动生成）：

- `server.host`: `127.0.0.1`
- `server.port`: `10000`
- `queue.keyword`: `排队`
- `queue.max_queue`: `10`
- `ui.overlay_title`: `排队队列`
- `style.custom_css_path`: `./custom.css`

弹幕配置（二选一，**优先 open_live**）：

### 1) 开放平台（open_live）

```yaml
bilibili:
  open_live:
    access_key: "xxx"
    access_secret: "yyy"
    app_id: 123456
    identity_code: "主播身份码"
```

### 2) Web 端（SESSDATA）

```yaml
bilibili:
  web:
    sessdata: "你的SESSDATA"
    room_id: 123456
```

## 自定义样式 `custom.css`

展示页会按顺序加载：

1. `/static/default.css`（内置透明背景/透明边框）
2. `/static/custom.css`（读取 `custom_css_path` 指向的文件内容，用于覆盖）

你可以在 `custom.css` 覆盖 CSS 变量，例如：

```css
:root {
  --font-size: 34px;
}
```


