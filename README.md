# eink-dashboard

墨水屏待办仪表盘:定时抓取天气、室内温湿度与待办,渲染成 **800×480 PNG**,由 SenseCraft 墨水屏设备每 5 分钟拉取刷新。

## 功能

- **时钟与日期** — 时间、星期、日期、农历
- **天气** — 当前天气、体感、逐时预报(未来 3 小时)、今日高低温、AQI、降水概率、日出日落(数据源:QWeather)
- **室内环境** — SenseCraft 设备上的 SHT40 温湿度 + 电量
- **番茄钟** — 时钟锚定的 25/5 循环,工作窗口可配置;午休/晚餐等休息时段是**真正暂停**(从时钟中扣除,结束后循环继续);窗口结束前 5 分钟预渲染,设备拉取即有最新画面
- **待办** — 手机浏览器管理(`/todos`,Basic 认证),支持优先级与完成状态;墨水屏展示未完成的前 6 条,紧要/普通/从容用 **实心黑圆 ● / 实心灰圆 ● / 空心圆 ○** 区分
- **节假日/调休** — 日历文件驱动(通用):节假日显示节日名、调休补班的周末照常渲染、大小周可表达;任何国家的开发者替换日历文件即可接入自己的节假日

所有数据都"烤"进一张图里,设备端只需一个 Image 小部件,无需任何 JSON 绑定。

## 工作流程

```
APScheduler(定时) ──► 抓取 QWeather / SenseCraft / 待办SQLite
        │
        ▼
Jinja2 模板(dashboard.html) ──► Playwright 截图 ──► static/dashboard.png (800×480)
        │
        ▼
SenseCraft 墨水屏每 5 分钟拉取 /dashboard.png
```

渲染降级策略:任一数据源故障(天气 / 温湿度 / 待办)只让对应面板降级显示,不会整屏空白。

## 技术栈

- **后端**:FastAPI + APScheduler + Jinja2
- **渲染**:Playwright(无头 Chromium)截图
- **数据源**:QWeather(天气)、SenseCraft API(SHT40 温湿度)、SQLite(待办)
- **前端**:vanilla JS 单页管理端(Material 3 风格)

## 快速开始(本地开发)

> 依赖 Python 3.10+,Windows 下命令以 PowerShell 为例。

```powershell
# 1. 创建虚拟环境并安装依赖(禁止全局安装)
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m playwright install chromium   # 本地截图需要 Chromium

# 2. 配置环境变量
Copy-Item .env.example .env   # 填真实值,见下方配置表
Copy-Item calendar.example.json calendar.json   # 日历文件(节假日/窗口/休息时段),见下方「日历文件」

# 3. 启动
uvicorn app:app --reload
```

验证:

- `http://localhost:8000/healthz` → `{"ok":true}`
- `http://localhost:8000/dashboard.png` → 渲染好的 800×480 PNG
- `http://localhost:8000/todos` → 待办管理页(输入 `ADMIN_USERNAME` / `ADMIN_PASSWORD`)

## 配置

复制 `.env.example` 为 `.env` 后填写;再复制 `calendar.example.json` 为 `calendar.json`(见下方「日历文件」)。**注意:`.env` 与 `calendar.json` 必须保存为 UTF-8 编码**(日历含中文标签,非 UTF-8 会导致启动时 `UnicodeDecodeError`):

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `SENSECRAFT_DEVICE_ID` | — | SenseCraft 设备 ID(室内温湿度) |
| `SENSECRAFT_API_KEY` | — | SenseCraft API Key |
| `QWEATHER_HOST` | — | QWeather API 主机,如 `https://h.qweatherapi.com` |
| `QWEATHER_API_KEY` | — | QWeather API Key |
| `QWEATHER_LOCATION` | `120.16,30.29` | 天气位置(经纬度,逗号分隔) |
| `CALENDAR_FILE` | — | **必填**。日历 JSON 路径(节假日/窗口/休息时段/刷新间隔的唯一真相),详见下节 |
| `ADMIN_USERNAME` | `admin` | `/todos` 与 `/api/todos` 的 Basic 认证用户名 |
| `ADMIN_PASSWORD` | `changeme` | **部署前必须改成强密码** |
| `TZ` | `Asia/Shanghai` | 时区 |
| `TODO_DB` | `todos.db` | SQLite 待办库路径(Docker 中为 `/app/data/todos.db`) |
| `LOG_LEVEL` | `INFO` | 根日志级别 |

## 日历文件

`CALENDAR_FILE` 指向一个 JSON 日历文件——**所有时间/调度行为的唯一真相**。复制
`calendar.example.json`(含 2026 年中国节假日+调休)后修改即可;任何国家的开发者替换
`overrides` 就能接入自己的节假日,无需改代码。

| 字段 | 默认 | 说明 |
|------|------|------|
| `render_interval_min` | `5` | 全天渲染触发间隔(分钟) |
| `weather_cache_min` | `30` | 天气缓存分钟数 |
| `breaks` | `[]` | 休息暂停时段,`{"start": "HH:MM", "end": "HH:MM", "label": "午休"}`,适用于所有工作日 |
| `weekends` | `[5, 6]` | 休息日星期(0=周一 … 6=周日,默认周六日);中东可改 `[4, 5]` |
| `types.workday` | `{start: 9, end: 21}` | 普通工作日渲染/番茄钟窗口 |
| `types.friday` | 同 workday | 周五窗口(不写则周五等同工作日) |
| `types.rest` | `{simple: true, render_at: "9:00"}` | 休息日:从 `render_at` 起每 `render_interval_min` 渲染**完整主画面**(时钟/天气/待办照常刷新)——只把「状态」卡片换成休息内容(显示节日名) |
| `overrides` | `{}` | 例外日:日期 → `{"type": "rest"/"workday"/..., "name": "国庆节"}`。节假日、调休补班、大小周的周六都写在这里;`type` 需在 `types` 中定义 |

- **判定优先级**:`overrides` > `weekends` > 周五 > 工作日
- **大小周**:把上班的周六逐条写成 `{"type": "workday", "name": "大周"}`(小周窗口可自定义类型,见 `calendar.example.json`)
- 校验失败(格式/时间/重叠/未知类型)启动即报错,便于早发现

## 部署

### 1. 准备代码

把项目放到服务器(`git clone` 或 scp)。

### 2. 配 `.env`

```sh
cp .env.example .env
cp calendar.example.json calendar.json   # 按当年官方安排更新节假日
# 填真实值:SENSECRAFT_DEVICE_ID / SENSECRAFT_API_KEY / QWEATHER_HOST / QWEATHER_API_KEY
# 以及 ADMIN_USERNAME / ADMIN_PASSWORD —— 改成强值!
# 休息暂停时段 / 渲染窗口 / 节假日都在 calendar.json 里配置,见上方「日历文件」
```

> `ADMIN_USERNAME` / `ADMIN_PASSWORD` 必须改成强值。`/todos` 和 `/api/todos` 在公网,靠它俩把锁。

### 3. 构建并启动

```sh
docker compose up -d --build
```

首次构建会拉 Playwright 镜像(约 1.5GB,含 Chromium)并装 CJK 字体,需要几分钟。启动后容器监听 `127.0.0.1:8000`(仅本机,给 nginx 反代)。

验证:

```sh
curl http://127.0.0.1:8000/healthz                       # {"ok":true}
curl -o /tmp/x.png http://127.0.0.1:8000/dashboard.png   # 200, 800x480 PNG
```

### 4. nginx 反代(用宿主已有的 nginx)

在**专属子域名**的 server 块里加(域名 + TLS 证书用已有的):

```nginx
server {
    listen 443 ssl http2;
    server_name eink.你的域名;
    # ssl_certificate     /你的证书/fullchain.pem;
    # ssl_certificate_key /你的证书/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

用专属子域名、把 `/` 整个反代到容器——这样 `/dashboard.png`、`/todos`、`/api/todos` 都在根路径下,待办页里的相对请求(`/api/todos`)能对上。

```sh
nginx -t && nginx -s reload
```

### 5. SenseCraft HMI 配置

- 编辑器里加一个 **Image 小部件**,URL 填 `https://eink.你的域名/dashboard.png`,刷新间隔 **5 分钟**。
- 不要再加原生 JSON 的 data/date 绑定——所有数据都烤在图里了。

### 6. 日常使用

- **墨水屏**:Image 小部件每 5 分钟拉图。
- **手机管待办**:浏览器开 `https://eink.你的域名/todos`,Basic 认证(用户名 = `ADMIN_USERNAME`、密码 = `ADMIN_PASSWORD`)。

### 运维

- **日志**:`docker compose logs -f`
  - HTTP 访问日志(uvicorn)会显示**真实客户端 IP**(nginx 的 `X-Forwarded-For`)——已开 `--proxy-headers`,不再全是 docker 网关 `172.20.0.1`。
  - 应用日志会打印:每次渲染成功(`rendered ...`)/ 失败(`render failed` + 完整 traceback)、天气/温湿度抓取降级、待办读取失败、启动时的配置 banner。
  - 想看 APScheduler 作业事件(添加作业 / misfire),把 `LOG_LEVEL=DEBUG` 放进 `.env` 再重启即可。
- **重启**:`docker compose restart`
- **更新代码**:`git pull && docker compose up -d --build`(改了 Dockerfile/启动参数必须 `--build` 重建镜像,单纯 restart 不会生效)
- **待办持久化**:在宿主 `./data/todos.db`(bind mount)。

## 待办 API

全部需要 Basic 认证(`ADMIN_USERNAME` / `ADMIN_PASSWORD`)。优先级取值:`high`(紧要)/ `normal`(普通)/ `low`(从容)。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/todos?include_done=true` | 待办列表(默认只含未完成,按优先级 + 创建时间排序) |
| POST | `/api/todos` | 创建,body `{"title": "...", "prio": "normal"}` |
| PATCH | `/api/todos/{id}` | 更新,body 任意组合 `{"title"?} {"done"?} {"prio"?}` |
| DELETE | `/api/todos/{id}` | 删除 |

自动化示例:`curl -u admin:密码 -X PATCH http://localhost:8000/api/todos/1 -H "Content-Type: application/json" -d '{"done": true}'`

## 项目结构

```
├── app.py               # FastAPI 入口:调度器、路由、日志配置
├── config.py            # 环境变量/基础配置
├── daytypes.py          # 日历系统:weekends/overrides/types/breaks 判定与校验
├── render.py            # 数据组装、Jinja2 渲染、Playwright 截图、番茄钟状态机
├── fetchers/
│   ├── sht40.py         # SenseCraft SHT40 温湿度抓取
│   └── weather.py       # QWeather 抓取与解析
├── todos/
│   ├── api.py           # /api/todos REST 路由
│   ├── auth.py          # Basic 认证(常数时间比较)
│   └── db.py            # SQLite 存取,按优先级 + 创建时间排序
├── templates/
│   ├── dashboard.html   # 墨水屏页面(800×480)
│   └── todos.html       # 待办管理页(手机端)
├── tests/               # pytest 测试(75 个)
└── static/              # dashboard.png 输出目录
```

## 测试

```powershell
.\.venv\Scripts\python -m pytest -v
```

覆盖:天气解析与抓取、SHT40、番茄钟状态机(含休息暂停的"真暂停"语义)、渲染降级、调度计划、待办 CRUD 与优先级、模板输出、并发渲染串行化。
