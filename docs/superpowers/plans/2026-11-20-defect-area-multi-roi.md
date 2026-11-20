# 缺陷面积多 ROI 改进实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 在现有缺陷面积 Tab 中实现多 ROI 独立参数与检测、ROI 面积标签、重叠像素去重总面积，并彻底删除逐缺陷画布文字。

**Architecture:** `AreaCanvas` 只管理多 ROI 的渲染和点选；`DefectAreaTab` 以稳定 id 的 ROI 数据项为事实源，逐框调用现有 `detect_defects()`。每框独立保存 objects，全部面积通过最终局部 mask 写入全图并集计算。批量检测用事件循环队列逐框执行，不引入线程。

**Tech Stack:** Python 3.13、PyQt6/QtTest、OpenCV、NumPy、标准库 unittest。

**Spec:** `docs/superpowers/specs/2026-11-19-defect-area-design.md` v2.0

## Global Constraints

- 当前目录 `D:/toolbox/0428` 原地实施；保留所有用户已有未提交改动，不提交、不切换分支、不恢复无关文件。
- 不修改 `image.py` 算法及其他 6 个 Tab；主要改动仅限 `area_canvas.py`、`area_tab.py`、`test_area_tab.py` 和已确认文档。
- 导入、绘制、选择、未激活调参/Otsu 不检测；无 ROI 不默认全图。
- 每框独立 threshold/bright/min_area；新框复制当前框的值，但不共享可变 params。
- 每框独立面积；全部面积为最终有效对象 mask 的像素并集，不能用面积相加减猜重叠。
- 画布不得出现逐缺陷编号或面积文字，也不保留“显示全部面积标签”开关。
- 所有新行为先写测试并观察预期失败；完成前运行完整 `test_area_tab.py`，真实图验证不伪称 ImageJ 已对照。

---

### Task 1: Canvas 多 ROI 渲染、点选与无对象文字

**Files:**
- Modify: `area_canvas.py`
- Test: `test_area_tab.py`

**Interfaces:**
- Produces: `AreaCanvas.roi_pick = pyqtSignal(float, float)`。
- Produces: `set_rois(entries, selected_id)`；entry 为 `{'id': int, 'roi': ('rect'|'poly', data), 'label': str}`。
- Produces: `set_objects(objects, summary='')`，不再接收 labels。
- Produces: `roi_entries`、`selected_roi_id` 供渲染和测试读取。

- [x] **Step 1: 写画布失败测试**

在 UI 测试类加入直接操作 Canvas 的测试，验证两个 ROI 标签、对象无文字、选择信号：

```python
def test_canvas_draws_only_roi_labels_and_emits_roi_pick(self):
    self.load()
    canvas = self.tab.canvas
    objects = image.detect_defects(self.gray, 127)
    canvas.set_rois([
        {'id': 1, 'roi': ('rect', (90, 50, 40, 40)), 'label': 'ROI 1 200px²'},
        {'id': 2, 'roi': ('rect', (10, 10, 30, 30)), 'label': 'ROI 2 待检测'},
    ], 1)
    canvas.set_objects(objects, '全部 ROI 总面积（重叠去重）: 200px²')
    with patch.object(canvas, '_text', wraps=canvas._text) as text:
        canvas.grab()
    self.assertEqual(text.call_count, 2)
    self.assertFalse(hasattr(canvas, 'labels'))
    picked = []
    canvas.roi_pick.connect(lambda x, y: picked.append((x, y)))
    canvas.set_mode('none')
    self.click(100, 60)
    self.assertEqual(len(picked), 1)
```

- [x] **Step 2: 运行并确认失败**

Run: `PYTHONIOENCODING=utf-8 QT_QPA_PLATFORM=offscreen venv/Scripts/python.exe -B -m unittest test_area_tab.AreaUITests.test_canvas_draws_only_roi_labels_and_emits_roi_pick`

Expected: FAIL，当前没有 `set_rois` / `roi_pick`，且旧接口仍保存对象 labels。

- [x] **Step 3: 实现最小 Canvas 改造**

- 用 `roi_entries=[]`、`selected_roi_id=-1` 替换单一 `self.roi`；实现 `set_rois` 并保留几何 draft。
- `set_objects(objects, summary='')` 只保存对象、生成 mask QImage 和 summary，删除 `self.labels`。
- `paintEvent` 对每个 entry 调 `_draw_roi`，当前框使用黄色/加粗，其余蓝色虚线；标签锚点取 rect 左上或 poly 第一个顶点，在屏幕空间绘制 entry.label。
- 删除对象 labels 的 `zip` 和 `_text` 循环；标定和 ROI 标签继续使用 `_text`。
- 在 `mode == 'none'` 的左键点击中发出 `roi_pick(x,y)`；其他工具模式不触发选择。
- `set_image` 调用 `set_rois([], -1)`，清除旧框。

- [x] **Step 4: 验证 Task 1**

重跑 Step 2 测试，Expected: PASS。再运行现有 Canvas 相关测试，记录因 Tab 尚未接入新接口而预期需要迁移的失败，不用旧接口回退新设计。

- [x] **Step 5: 检查范围**

Run: `git diff --check -- area_canvas.py test_area_tab.py`

Expected: 不引入 trailing whitespace；不修改其他文件。

---

### Task 2: Tab 多 ROI 数据模型、独立参数和检测编排

**Files:**
- Modify: `area_tab.py`
- Modify: `area_canvas.py`（仅 Task 1 接口联调所需）
- Test: `test_area_tab.py`

**Interfaces:**
- Produces: `self.rois`、`selected_roi_id`、`current_roi()`、`select_roi(roi_id)`。
- Produces: `roi_area_px(roi_id)`；全局像素并集留到 Task 3 用失败测试驱动。
- Produces: `_run_roi(roi)`、`detect_now()`（当前框）、`toggle_detection()`（整批/停止）。
- Keeps: `self.objects` 为按 ROI id 展开的缓存列表，刷新时切片更新以保留列表身份；它不再是独立事实源。

- [x] **Step 1: 写多 ROI 与独立参数失败测试**

使用两个 20×10 亮块，灰度分别 150 和 180，验证复制参数、独立修改、一次全检和只重跑当前：

```python
def test_multiple_rois_detect_all_with_independent_thresholds(self):
    gray = np.zeros((80, 180), np.uint8)
    gray[10:20, 10:30] = 150
    gray[10:20, 80:100] = 180
    self.load(gray)
    self.assertTrue(self.tab.set_roi_rect((5, 5, 40, 40)))
    self.tab.slider_thresh.setValue(100)
    self.assertTrue(self.tab.set_roi_rect((75, 5, 40, 40)))
    self.assertEqual(self.tab.slider_thresh.value(), 100)
    self.tab.slider_thresh.setValue(160)
    QTest.mouseClick(self.tab.btn_detect, Qt.MouseButton.LeftButton)
    self.drain_batch()
    self.assertEqual([self.tab.roi_area_px(1), self.tab.roi_area_px(2)], [200, 200])
    first_objects = self.tab.rois[0]['objects']
    with patch('area_tab.detect_defects', wraps=image.detect_defects) as detector:
        self.tab.select_roi(2)
        self.tab.slider_thresh.setValue(140)
        QTest.qWait(190)
    self.assertEqual(detector.call_count, 1)
    self.assertIs(self.tab.rois[0]['objects'], first_objects)
    self.assertEqual(self.tab.roi_area_px(2), 200)
```

增加有界等待辅助，禁止无限循环：

```python
def drain_batch(self):
    for _ in range(200):
        if not self.tab._batch_queue:
            self.app.processEvents()
            return
        QTest.qWait(10)
    self.fail('批量 ROI 检测未在 2 秒内完成')
```

- [x] **Step 2: 运行并确认失败**

Run: `PYTHONIOENCODING=utf-8 QT_QPA_PLATFORM=offscreen venv/Scripts/python.exe -B -m unittest test_area_tab.AreaUITests.test_multiple_rois_detect_all_with_independent_thresholds`

Expected: FAIL，旧 `set_roi_rect` 会替换 ROI，且没有 `roi_area_px` / `_batch_queue`。

- [x] **Step 3: 实现 ROI 状态与 UI**

- 新图清空 `rois`、队列和选中项；保留侧栏参数作为新图首个 ROI 默认值。
- `_append_roi(mask, roi)` 复制当前 params，追加稳定 id 并选中新框，不检测、不清其他框。
- `select_roi` 更新 id，并用 `blockSignals` 同步 threshold/bright/min_area；参数控件 `schedule_detection` 先把值写回当前 ROI。
- 区域按钮改为“删除当前 ROI”“清空全部 ROI”；增加 `roi_table` 和保留当前 `table` 作为当前框缺陷明细。
- `_refresh_results` 更新 ROI 表、当前明细、展开 objects、Canvas `set_rois` 和每框面积标签。

- [x] **Step 4: 实现显式批量与单框重跑**

- `_run_roi(roi)` 调现有算法、写入 `roi_id/source`、替换当前框 objects、设置 active/error。
- `toggle_detection` 首次启动：停止旧 timer，整批清结果，首框立即运行，其余 id 放入 `_batch_queue` 并由 0ms QTimer 逐框执行；停止/新图使队列失效。
- `detect_now` 只重跑当前 active ROI；未激活只保存参数。150ms 防抖 timer 只服务当前选择，选择变化时停止旧 timer，避免把旧参数跑到新框。
- “检测全部”始终显式整批重跑并清全部手动修正；新增 pending ROI 不自动运行。

- [x] **Step 5: 验证 Task 2**

Run: `PYTHONIOENCODING=utf-8 QT_QPA_PLATFORM=offscreen venv/Scripts/python.exe -B -m unittest test_area_tab.AreaUITests.test_multiple_rois_detect_all_with_independent_thresholds test_area_tab.AreaUITests.test_canvas_draws_only_roi_labels_and_emits_roi_pick`

Expected: 2 tests PASS。

---

### Task 3: 去重总面积、手动修正、双表和 CSV 完整迁移

**Files:**
- Modify: `area_tab.py`
- Test: `test_area_tab.py`

**Interfaces:**
- Produces: `union_area_px()` 返回最终对象 mask 的全图像素并集计数。
- Produces: CSV 列 `ROI编号,缺陷编号,像素面积,实际面积,面积单位,质心x_px,质心y_px,来源`。
- Keeps: 标定函数 `fmt_area` / `compute_real_area` 和 `image.detect_defects` 不变。

- [x] **Step 1: 写手算重叠测试**

```python
def test_overlapping_rois_keep_independent_areas_and_union_total(self):
    gray = np.zeros((40, 60), np.uint8)
    gray[10:30, 10:30] = 255
    self.load(gray)
    self.tab.set_roi_rect((10, 10, 20, 20))
    self.tab.set_roi_rect((20, 10, 20, 20))
    QTest.mouseClick(self.tab.btn_detect, Qt.MouseButton.LeftButton)
    self.drain_batch()
    self.assertEqual(self.tab.roi_area_px(1), 200)
    self.assertEqual(self.tab.roi_area_px(2), 200)
    self.assertEqual(self.tab.union_area_px(), 350)
    self.assertIn('350px²', self.tab.lbl_total.text())
```

再增加孔洞 fixture：20×20 块中挖 10×10 孔，两个相同 ROI 各自面积 300，union 必须为 300 而非 400 或 600。

- [x] **Step 2: 运行并确认失败**

Run: `PYTHONIOENCODING=utf-8 QT_QPA_PLATFORM=offscreen venv/Scripts/python.exe -B -m unittest test_area_tab.AreaUITests.test_overlapping_rois_keep_independent_areas_and_union_total`

Expected: FAIL，旧单 ROI 替换逻辑无法得到两个 200 和并集 350。

- [x] **Step 3: 实现最终 mask 并集**

`union_area_px` 创建 `np.zeros_like(self.gray)`，遍历每框 objects，将每个局部 mask OR 到 `union[y:y+h,x:x+w]`，返回 `cv2.countNonZero`。在检测、手动增删、删除 ROI 和标定刷新中统一使用，不另存容易过期的总面积。

- [x] **Step 4: 将手动修正绑定当前 ROI**

- `preview_add` 要求当前 active ROI 且点击处 `roi['mask'][y,x] != 0`。
- 候选只与当前 ROI objects 查重，确认/删除只修改当前框。
- `_manual_changed` 从单项读取；重跑当前只清当前，全检才清全部。
- 明细表选择映射到展开 objects 中当前 ROI 的偏移，仅高亮，不生成文字。

- [x] **Step 5: 迁移 CSV 与旧测试**

CSV 按 ROI id 和对象 id 顺序写所有框，新增 ROI编号；保持 BOM、临时文件和 `os.replace`。旧单 ROI 测试改为读取 `rois[0]` / `current_roi()['mask']`，删除 `chk_show_labels` 和逐缺陷文字期待；`detect()` 辅助在有多个 ROI 时调用 `drain_batch()`。

新增断言：两个 ROI 各一个缺陷导出两行，ROI编号分别为 1、2；修改标定后所有面积更新且检测调用不增加。

- [x] **Step 6: 运行完整测试并修复真实回归**

Run: `PYTHONIOENCODING=utf-8 QT_QPA_PLATFORM=offscreen venv/Scripts/python.exe -B test_area_tab.py`

Expected: 全部通过；若旧测试失败，先判断是新契约迁移还是生产回归，不修改手算面积期望来掩盖错误。

---

### Task 4: 队列边界、独立审查和真实图验收

**Files:**
- Modify: `area_tab.py`（仅测试揭示的问题）
- Modify: `area_canvas.py`（仅测试揭示的问题）
- Test: `test_area_tab.py`
- Output: `.workbuddy/validation/defect-area/`

**Interfaces:**
- Consumes: 前三个 Task 的全部接口。
- Produces: 最终测试日志和原生 Windows 多 ROI 截图。

- [x] **Step 1: 写队列失效和单框异常测试**

使用 `patch('area_tab.detect_defects', wraps=...)` 统计：批量进行中调用停止或加载新图后，等待超过所有 timer，旧 ROI 不得重新出现结果。让第二框抛出 `cv2.error`，第三框仍必须得到手算面积，第二框 status 为 error。

- [x] **Step 2: 先观察失败，再做最小修复**

Run 对应 unittest，确认是否出现过期提交或批量中断。若失败，只修改队列 token/timer 和单框异常边界，并重复红—绿验证。

- [x] **Step 3: 完整验证并保存日志**

Run: `PYTHONIOENCODING=utf-8 QT_QPA_PLATFORM=offscreen venv/Scripts/python.exe -B test_area_tab.py 2>&1 | tee .workbuddy/validation/defect-area/test_area_tab.log`

Expected: 输出 `OK`、0 failures；从输出记录实际测试总数，不预先写死。

Run: `git -c core.whitespace=cr-at-eol diff --check -- area_tab.py area_canvas.py test_area_tab.py docs/superpowers/specs/2026-11-19-defect-area-design.md`

Expected: 无输出、退出码 0。

- [x] **Step 4: 独立代码审查**

派发只读 general-purpose reviewer，聚焦：ROI 选择/编号、timer 和批量过期提交、独立参数、并集正确性、手动修正归属、CSV 行归属、是否仍存在对象文字路径。Critical/Important 问题先复现、补失败测试再修；Minor 记录，不扩大范围。

- [x] **Step 5: 原生 Windows 双 ROI 验证**

使用用户原图：

`C:/Users/lingfeng.zhang/.qoder/tmp/D--toolbox-0428/images/00f8f060-0e4e-4e90-a23b-01f74a9acdd7/8c3c4618-b896-429d-a1de-012db16562d6.jpg`

- 实际尺寸 3840×2160；上方 ROI `(1958,480,1238,163)`，右侧 ROI `(3264,768,192,922)`。
- 导入后断言 0 objects；分别设置独立 Otsu 参数且仍不检测；点击全检并等待队列完成。
- 保存 `multi-roi-import-clean.png`、`multi-roi-before-detection.png`、`multi-roi-results.png`。
- 截图确认只有两个 ROI 标签、绿色掩膜、去重总面积，无任何 `#缺陷号 面积` 文本。
- 记录各框 Otsu、对象数、像素面积、union、导入/检测渲染耗时；不把未标定像素面积写成 µm²。

- [x] **Step 6: 汇报已验证与未验证项**

报告实际测试数、真实图数值、截图链接和审查结果。明确 ImageJ ≤1%、Excel 人工打开及缺失示教配方回归仍未完成；不自动提交或打包。
