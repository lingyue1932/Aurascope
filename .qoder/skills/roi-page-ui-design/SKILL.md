---
name: roi-page-ui-design
description: Aurascope ROI（缺陷面积）页面的 UI 设计规范与实现契约。修改或扩展 area_tab.py / area_canvas.py 的界面、修复该页视觉问题、或按同一设计语言开发新的 PyQt6 页面时使用。覆盖设计 token、侧栏布局、组件选型、画布配色、交互反馈和 QSS 陷阱。
---

# ROI 页面 UI 设计规范（Aurascope）

## 概述

ROI Tab 在 main_window.py 注册为 `'    ROI    '`，实现分布在四个文件：

| 文件 | 职责 |
|---|---|
| area_tab.py | `DefectAreaTab`：侧栏布局、控件、状态文案与业务交互 |
| area_canvas.py | `AreaCanvas`：自绘画布、坐标变换、模式交互与图元渲染 |
| styles.py | 全局 QSS 与 token 字典 `_C`；文件头注释即设计契约 |
| ui_components.py | 按钮/标签工厂、`CollapsibleSection`、下拉弹层样式化 |

核心心智模型：左侧约 280px 可滚动参数栏 + 右侧自绘画布。控件一律用工厂函数 + objectName 选择器；颜色、字号、圆角、间距只从 token 取；画布元素按固定语义色板绘制。

## 设计 token（styles.py `_C`）

### 色彩

| token | 值 | 用途 |
|---|---|---|
| bg | #F4F6FA | 页面/对话框底 |
| surface | #FFFFFF | 卡片、表格、输入框 |
| surface2 | #F8FAFC | 表头、次级面 |
| border | #DCE3EC | 常规描边 |
| border2 | #C8D2E0 | 强描边/悬停 |
| text / text2 / text3 | #1B2333 / #4E5A70 / #7D879B | 主/次/弱文字 |
| accent | #2563EB（hover #1D4ED8，pressed #1E40AF） | 主色 |
| accent_tint / tint2 | rgba(37,99,235,.10) / .18 | 次级按钮底、选中行 |
| success / danger / warning | #16A34A / #DC2626 / #B45309 | 语义色 |
| 禁用底 | #F1F3F8（禁用主按钮 #C7D2E4） | 禁用态 |

新增颜色先加进 `_C` 再复用；页面代码里禁止散写新 hex。画布色板是唯一例外，集中在本文「画布视觉语言」一节维护。

### 字体与字阶

- UI 正文：`-apple-system, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei'`，14px。
- 表格/数值：`'Cascadia Mono', Consolas` 13px，等宽。
- 展示字体 token `_C['font']`（Bahnschrift 起头）留给大标题类场景，正文别混用。
- 字阶只有 6 级：11 caption-2 · 12 caption/InfoLabel · 14 body/按钮 · 15 StepTitle · 18 CardTitle · 24 页面标题。不要引入 13/16/17 等中间字号，表格 13px 是既定例外。

### 间距与圆角

- 8pt 网格：4 / 8 / 12 / 16 / 24。
- 页面外边距 16；侧栏内容 margins 16、区块间距 14；同行按钮间距 8；折叠内容 10/2/10/10、行距 6。
- 圆角：6 小标签 · 8 输入/小件 · 10 按钮/内嵌卡片 · 12 大卡片 · 999 胶囊。

## 页面布局

- 顶层 `QVBoxLayout` margins 16 → `QSplitter` 水平，`childrenCollapsible=False`，stretch 0:1，默认 `setSizes([330, 638])`。
- 左栏 `QFrame#SidebarCard`（白底、border、12 圆角），`minimumWidth 280`；内部 `QScrollArea`：widgetResizable、NoFrame、关闭横向滚动条。
- 右栏 `AreaCanvas`：最小 200×180；图片按 0.9 系数 fit 居中。
- 侧栏顺序固定：导入图片（主按钮）→「比例尺标定」展开 →「距离测量」收起 →「检测区域」展开 →「阈值检测」展开 →「手动修正」收起 →「测量结果」收起 → 状态标签 → addStretch。
- 「检测区域」按钮用 2×2：第一行 矩形框选 / 多边形框选，第二行 删除当前 ROI / 清空全部 ROI；每行 `QHBoxLayout` spacing 8、stretch 1:1。其余区块按钮单列堆叠，不要恢复成四连排单列。
- 状态标签 `create_info_label` + `TextFormat.PlainText`，常驻侧栏底部；`error=True` 时 `sidebar_scroll.ensureWidgetVisible` 滚到可见。
- 1000×600 窗口下侧栏必须可滚动、splitter 可拖动（test_area_tab.py 有覆盖），不要写死高度或塞死布局。

## 组件规范

### 按钮层级

- `PrimaryBtn`：每个流程至多一个主行动（导入图片、检测全部 ROI）。
- `SecondaryBtn`：工具与次级动作；工具按钮 `checkable=True`，checked 态即主色填充。
- `SuccessBtn` / `DangerBtn`：保留语义，ROI 页当前未使用，不要为“好看”引入第三、第四种按钮样式。
- 工具按钮用 `QButtonGroup` 互斥管理；点击已激活工具回到 `none` 模式；模式变化统一走 `set_mode()`，用 blockSignals 防回环。

### 折叠区块

- 用 `CollapsibleSection`：整行标题可点击，`▼  标题` 表示展开、`▲  标题` 表示收起——箭头方向是项目既定约定，不要“修正”成常规方向。
- 默认只展开当前流程需要的区块；新功能区块默认收起。

### 信息标签

- 说明文字用 `create_info_label`（12px、text2、自动换行）。
- 阈值数值标签居中、固定高 20；测量统计用 `测量数量: N` 这类“标签: 值”短句。
- 汇总行用 `·` 分隔，如 `ROI 数量: 3 · 当前框缺陷: 12`。

### 表格

- 一律 `QTableWidget`：隐藏 verticalHeader；单元格只读（去掉 ItemIsEditable）；表头 `ResizeToContents`；明细表加 `StretchLastSection`。
- ROI 总表 7 列（ROI/状态/阈值/亮暗/最小面积/缺陷数/总面积），单选整行，最低高 130；缺陷明细 4 列（编号/像素面积/实际面积/来源），最低高 160；测距表最低高 120。
- 表行选中与画布选中双向联动：ROI 表行 ↔ 画布 ROI 标签；明细表行 ↔ 画布缺陷高亮。
- 面积显示走 `fmt_area`/`_area_label`：未标定为 `Npx²`，已标定自动换挡到 nm²–m²、两位小数；未标定列显示 `未标定` 而不是 0。

### 滑块 / 数字框 / 复选框

- 阈值：0–255、默认 127，上方居中数值标签，`自动阈值 (Otsu)` 只算当前 ROI。
- 最小面积：1–100000、默认 1 px²，滑块 + `QSpinBox`（后缀 ` px²`、`keyboardTracking=False`）双向同步。
- 复选框用 `create_checkbox`，勾选态是主色实心指示块（不做图片对勾），保持现有观感。
- 所有交互控件必须写全 default / hover / pressed / checked / disabled / focus 状态。

## 画布视觉语言

所有线宽写成 `x / self.scale`，保证缩放时屏幕粗细恒定。配色表：

| 元素 | 样式 |
|---|---|
| 画布底 / 空状态 | #f0f4f8 底；居中 #94a3b8 “请先导入图片” |
| ROI 未选中 | 虚线 #3b82f6，2px |
| ROI 选中 | 实线 #ffd166，2.5px |
| ROI 标签 | 12px 黑描边白字，锚在左上角偏移 (4,-4)，内容 `ROI {id}` + 待检测/失败/面积 |
| 缺陷填充 | rgba(0,200,120,100)，逐像素，不插值、不填孔洞 |
| 缺陷轮廓 | 实线 (0,220,130)，1.5px |
| 缺陷选中 | #ffd166 2.5px |
| 缺陷悬停（删除模式） | #ff6b6b |
| 添加预览 | 同款填充 + 虚线轮廓 |
| 测距线 | #f59e0b 2.5px，端点白描边实心圆 r=4，标签在 midpoint+(6,-10) |
| 测距悬停 | #ff6b6b |
| 7° 吸附徽标 | #ef4444 短横/短竖 |
| 标定线 | #3b82f6 实线 2px，端点圆 r=3 |
| 拖拽草图 | 虚线 #3b82f6 2px；多边形随鼠标画实时折线 |
| 汇总胶囊 | 画布右上角，黑 190 alpha 底、白字，内容为全部 ROI 重叠去重总面积 |

- 文字统一 `_text()`：12px、3px 黑描边 + 白填充，保证任意底色可读。
- 渲染层级固定：图 → 缺陷填充/轮廓 → 添加预览 → ROI → 测距 → 进行中草图 → 文字层。新增图元先定层级，别插错层造成遮挡。

## 交互与反馈

- 模式集合：`none`（点选 ROI）/ `rect` / `poly` / `calibrate` / `measure` / `distance_delete` / `add` / `delete`。ESC 撤销草图和预览、退出工具模式。
- 画布导航：右键拖动平移（ClosedHand 光标），滚轮以鼠标为锚缩放 ×1.1/×0.9。平移打断左键拖拽时不得提交意外 ROI（`_drag_interrupted`）。
- 测距：标定后才能进入；点击两点自动记录，`SNAP_DEG = 7` 吸附近水平/垂直并显示徽标。未标定时按钮禁用并给状态提示。
- 防卡顿契约：阈值/最小面积改动 150ms 防抖；拖动阈值过程中只更新状态文案，松手才重跑；切换 ROI 时取消未执行的防抖，把旧结果标记为待检测，但不自动重跑。
- 自动行为：新建 ROI 自动检测该框；导入图片绝不自动检测；检测进行中主按钮变“停止并清空”。
- 状态文案：每个动作写“做了什么 + 保留了什么”，如“已清空全部 ROI；图片和标定保留”；错误文案要指明下一步（“请先框选 ROI，再开始检测”）。
- 文案风格：中文短句、动宾结构；按钮 2–6 字；单位用全角或半角保持同页一致，不混排。

## QSS / Qt 陷阱

1. QSS 不支持变量：颜色只能引用 `styles.py` 的 `_C`，或经 f-string 注入。
2. Qt 不支持 CSS 三角：`QComboBox` 的下拉箭头由 `ui_components.ChevronComboBox` 自绘（`paintEvent` 里画 chevron，颜色 text2/禁用 text3），业务里一律用 `create_combo()` 工厂创建，不要直接 `QComboBox()`，也不要再写 `::down-arrow { image: none }`（会把箭头变空白）；`QSpinBox` 上下按钮宽 0 隐藏，靠输入/滚轮修改。
3. 下拉弹层是独立窗口，全局 QSS 可能命中不了：必须调用 `style_combo_popups(widget)`（应用 POPUP_QSS、去焦点框委托、按项数设弹层高度）。
4. 输入框 focus 用 2px accent 边框并回收 padding，避免跳动。
5. `QSplitter` 手柄默认透明，只 hover 显示 border、pressed 显示 accent。
6. 表格/数值用等宽字体，正文用 UI 字体；不要出现第三种字体。
7. 不要新增灰阶或字号档位；禁用/占位底色已定义，不要另造。

## 修改流程与验收

1. 动手前先读 styles.py 的 token 注释与 area_tab.py `_build_ui`。
2. 复用既有 helper（在 `_build_ui` 内）：

   ```python
   sec = group('新功能', expanded=False)       # 注册到 self.sections 并加入侧栏
   btn = tool(sec, '开始新功能', 'new_mode')   # 互斥工具按钮，checked 跟随 set_mode
   sec.addWidget(create_info_label('一句话说明操作方式'))
   ```

3. 新增画布图元：在 `AreaCanvas` 里加 `_draw_*` 方法，线宽除以 `self.scale`，颜色从上表取，并明确绘制层级。
4. 缺控件就在 ui_components.py 加工厂 + objectName 样式，不在页面里手写 setStyleSheet（`CollapsibleSection` 的局部样式是既有先例，不要扩散）。
5. 验证：
   - `python test_area_tab.py` 跑行为与布局测试（含 1000×600 侧栏滚动与 splitter 拖动）。
   - `python test_ui_audit.py` 生成各 Tab 截图到 `.workbuddy/validation/audit`，逐项对照本规范检查颜色、箭头方向、字号、圆角。
   - 在 1000×600 与 1440×900 下确认按钮不截断、侧栏可滚动、状态标签始终可见。
6. 验收清单：
   - [ ] 无新增散写颜色/字号，token 复用
   - [ ] 按钮层级正确，每区块主按钮 ≤ 1
   - [ ] 折叠箭头 ▼ 展开 / ▲ 收起
   - [ ] 画布配色与线宽符合上表，且除以 scale
   - [ ] 表行与画布选中联动无回归
   - [ ] 阈值拖动不卡顿、松手才重跑
   - [ ] 状态文案说明“变更 + 保留”

## 资源

- 参考实现：`area_tab.py`（布局与交互）、`area_canvas.py`（渲染）、`styles.py`（token 契约）、`ui_components.py`（工厂与折叠区）。
- 回归测试：`test_area_tab.py`（行为/布局）、`test_ui_audit.py`（截图走查）。
