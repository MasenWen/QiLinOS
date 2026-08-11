from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence


AMBIGUOUS_OBJECT_ID = "object:ambiguous_prior_workflow"
TEMPORAL_LABELS = (
    "temporal_short",
    "temporal_medium",
    "temporal_long",
)


@dataclass(frozen=True)
class ActionAnnotation:
    name: str
    aliases: tuple[str, ...]


# These compact semantic cores were reviewed against the 47 source tasks and
# the five human-style query variants. They are deliberately narrower than the
# source sentences so an exact hit is still a useful object span.
ACTION_ANNOTATIONS: dict[str, ActionAnnotation] = {
    "fill_blank_from_above": ActionAnnotation(
        "Fill blanks from above",
        (
            "blank cells",
            "空白单元格",
            "记录断了",
            "漏项",
            "断档",
            "那套补法",
            "老办法补齐",
            "fill all the blank cells",
        ),
    ),
    "build_total_and_growth_charts": ActionAnnotation(
        "Build total and growth charts",
        (
            "Total+Growth",
            "总额看柱状",
            "环比看折线",
            "一张柱状图一张折线图",
            "销售表继续做双图",
            "年度双图",
            "total sales",
            "month-on-month growth",
        ),
    ),
    "calculate_gross_profit_and_year_profit_key": ActionAnnotation(
        "Calculate gross profit and Year_Profit key",
        (
            "Gross profit",
            "Year_Profit",
            "算出毛利",
            "毛利列",
            "年份_整数毛利",
            "真正剩下的毛利",
        ),
    ),
    "calculate_asset_year_over_year_changes": ActionAnnotation(
        "Calculate asset year-over-year changes",
        (
            "年度百分比变化",
            "三类资产相对上一年的变化",
            "年度变化分析",
            "相对前一年的增减比例",
            "Year 加三类 changes",
            "percentage annual changes",
        ),
    ),
    "build_monthly_total_line_chart": ActionAnnotation(
        "Build monthly total line chart",
        (
            "月度合计趋势",
            "Total 行加折线图",
            "按月份走的折线图",
            "每月合计和它的趋势线",
            "总量随月份怎么走",
            "monthly total sales",
            "line chart",
        ),
    ),
    "pad_customer_ids_to_seven_digits": ActionAnnotation(
        "Pad customer IDs to seven digits",
        (
            "补成七位",
            "补零凑够7位",
            "编号标准化",
            "短编号补齐",
            "左侧补零",
            "seven digits",
            "pad them with zeros",
        ),
    ),
    "rename_copy_and_reorder_sheets": ActionAnnotation(
        "Rename, copy, and reorder sheets",
        (
            "工作表结构",
            "主表、备份表和离线表",
            "表页整理",
            "主用、备份和离线三个版本",
            "LARS Resources",
            "make a copy",
            "rename",
        ),
    ),
    "create_sales_cogs_clustered_column_chart": ActionAnnotation(
        "Create Sales and COGS clustered column chart",
        (
            "簇状柱形图",
            "Sales 和 COGS 的对比图",
            "并排柱子",
            "成本对比图",
            "两组柱子并排",
            "clustered column chart",
            "Sales & COGS",
        ),
    ),
    "copy_revenue_column_to_sheet2": ActionAnnotation(
        "Copy Revenue column to Sheet2",
        (
            "Revenue 这一列",
            "Revenue 列连同表头",
            "Revenue 整列",
            "收入列原样搬到 Sheet2",
            "那一列连标题",
            "Copy the Revenue column",
        ),
    ),
    "zoom_out_spreadsheet_view": ActionAnnotation(
        "Zoom out spreadsheet view",
        (
            "缩小工作表视图",
            "视图缩小",
            "画面再拉远",
            "显示比例往下调",
            "缩小视图",
            "zoom out",
        ),
    ),
    "create_invoice_count_pivot": ActionAnnotation(
        "Create invoice count pivot",
        (
            "发票号重复情况",
            "计数透视表",
            "编号频次汇总",
            "按编号聚合后把次数列出来",
            "Invoice No.",
            "count how many times",
        ),
    ),
    "build_investment_summary_header_layout": ActionAnnotation(
        "Build investment summary header layout",
        (
            "投资摘要页",
            "Investment Summary",
            "利率对比页",
            "第二张表的表头",
            "投资汇总页的骨架",
            "High Interest Rate",
        ),
    ),
    "create_promotion_revenue_pivot": ActionAnnotation(
        "Create promotion revenue pivot",
        (
            "促销收入",
            "促销类型汇总",
            "promotion type",
            "促销类别把收入加总",
            "promotion 的名称",
            "promotion type 的总 revenue",
        ),
    ),
    "calculate_weekly_profit": ActionAnnotation(
        "Calculate weekly profit",
        (
            "利润列",
            "逐周看赚了多少",
            "利润计算",
            "每周毛利",
            "收入和成本的差",
            "Profit column",
            "subtracting COGS from Sales",
        ),
    ),
    "calculate_period_rate_and_highlight_max": ActionAnnotation(
        "Calculate period rate and highlight maximum",
        (
            "期间利率",
            "Period Rate (%)",
            "最大的 period rate",
            "期间收益比例",
            "最高值高亮",
            "highlight the highest result",
        ),
    ),
    "format_values_in_millions_and_billions": ActionAnnotation(
        "Format values in millions and billions",
        (
            "M/B 展示格式",
            "百万和十亿单位",
            "单位缩写显示",
            "百万版和十亿版",
            "Millions (M)",
            "Billions (B)",
        ),
    ),
    "create_month_total_table": ActionAnnotation(
        "Create month total table",
        (
            "Month/Total 两列表",
            "月度汇总表",
            "第一列月份、第二列合计",
            "两列结构",
            "月份加总额清单",
            "Month and Total",
        ),
    ),
    "create_order_sparklines": ActionAnnotation(
        "Create order sparklines",
        (
            "迷你图",
            "sparkline",
            "小趋势图",
            "迷你趋势",
            "订单趋势",
            "Jan-Mar",
        ),
    ),
    "build_demographic_profile_pivots": ActionAnnotation(
        "Build demographic profile pivots",
        (
            "人口画像页",
            "Demographic Profile",
            "性别、婚姻状态和最高学历",
            "三部分展示结构比例",
            "三张 Pivot",
            "percentage of Sex",
        ),
    ),
    "create_yearly_monthly_cost_charts": ActionAnnotation(
        "Create yearly monthly cost charts",
        (
            "年度双图",
            "两年的月度总成本",
            "两张年度成本图",
            "每年十二个月的合计",
            "月度总成本柱形图",
            "2019 and 2020",
        ),
    ),
    "calculate_earnings_from_time_and_rate": ActionAnnotation(
        "Calculate earnings from time and rate",
        (
            "工时乘费率",
            "换成小时再算应得金额",
            "时间乘单价",
            "工资总额",
            "hourly rate",
            "total earnings",
        ),
    ),
    "split_employee_identity_fields": ActionAnnotation(
        "Split employee identity fields",
        (
            "人员信息拆分",
            "姓名和 Rank",
            "人员字段拆分",
            "三个独立字段",
            "First Name、Last Name 和 Rank",
            "split",
        ),
    ),
    "sort_and_chart_boomerang_quantity": ActionAnnotation(
        "Sort and chart Boomerang quantity",
        (
            "销量趋势",
            "时间顺序",
            "时序图",
            "quantity 随 Date Time",
            "销量随时间的走势",
            "A列升序后再画线",
        ),
    ),
    "export_current_sheet_to_csv": ActionAnnotation(
        "Export current sheet to CSV",
        (
            "导出成同名 CSV",
            "另存为 CSV",
            "只导出正在看的 sheet",
            "逗号分隔版本",
            "当前 sheet 导出 CSV",
            "export",
        ),
    ),
    "calculate_loan_maturity_dates": ActionAnnotation(
        "Calculate loan maturity dates",
        (
            "贷款到期日",
            "Maturity Date",
            "什么时候到期",
            "到期日列",
            "最终日期",
            "maturity dates",
        ),
    ),
    "freeze_header_range_a1_b1": ActionAnnotation(
        "Freeze header range A1:B1",
        (
            "A1:B1 固定",
            "冻结一下",
            "视图固定",
            "始终留在屏幕上",
            "冻结 A1:B1",
            "freeze",
        ),
    ),
    "summarize_revenue_and_expenses": ActionAnnotation(
        "Summarize revenue and expenses",
        (
            "收入和费用总额",
            "总收入和总支出",
            "Revenue 和 Total Expenses 分别加总",
            "两项合计",
            "Total Revenue",
            "Total Expenses",
        ),
    ),
    "fill_acceleration_and_build_combined_data": ActionAnnotation(
        "Fill acceleration and build combined data",
        (
            "加速度",
            "Combined Data",
            "公式下填和 Combined Data 拼接",
            "完整的加速度列",
            "B、D按第2行填充",
            "Header: cell value",
        ),
    ),
    "calculate_employee_ages": ActionAnnotation(
        "Calculate employee ages",
        (
            "年龄列",
            "员工年龄",
            "根据每个人的 birthday",
            "补年龄",
            "出生日期",
            "calculate the age",
        ),
    ),
    "format_embedded_number_to_two_decimals": ActionAnnotation(
        "Format embedded number to two decimals",
        (
            "拼进文字的数字",
            "文本里的数也固定两位",
            "公式拼接的显示问题",
            "说明文字中的金额",
            "文本公式里的数字",
            "embedded text",
        ),
    ),
    "calculate_revenue_and_create_product_pivot": ActionAnnotation(
        "Calculate revenue and create product pivot",
        (
            "产品收入透视表",
            "每种产品实际带来多少收入",
            "收入列和产品 Pivot",
            "按商品聚合",
            "按产品做透视汇总",
            "Retail Price",
        ),
    ),
    "sort_amounts_ascending": ActionAnnotation(
        "Sort amounts ascending",
        (
            "最小金额排到最大金额",
            "amount 升序",
            "金额排序",
            "数额由低到高",
            "金额升序排序",
            "ascending",
        ),
    ),
    "create_product_and_channel_revenue_pivots": ActionAnnotation(
        "Create product and channel revenue pivots",
        (
            "双透视表",
            "产品视角和渠道视角",
            "两组 revenue Pivot",
            "两张透视表",
            "product total revenue",
            "sales channel total revenue",
        ),
    ),
    "hide_na_display_without_deleting": ActionAnnotation(
        "Hide N/A display without deleting",
        (
            "隐藏表格里的 N/A",
            "N/A 先按之前的方法藏起来",
            "暂时不想在表里看到 N/A",
            "显示隐藏",
            "缺失占位符先别露出来",
            "N/A 只隐藏显示",
        ),
    ),
    "format_spent_two_decimals": ActionAnnotation(
        "Format spent to two decimals",
        (
            "spent 列",
            "全部显示两位",
            "支出列统一成小数点后两位",
            "固定两位小数",
            "two decimal",
        ),
    ),
    "reorder_order_columns": ActionAnnotation(
        "Reorder order columns",
        (
            "字段重排",
            "列顺序",
            "日期放最前",
            "Date、First Name、Last Name、Order ID、Sales",
            "move column",
        ),
    ),
    "fill_branch_officers_from_lookup": ActionAnnotation(
        "Fill branch officers from lookup",
        (
            "负责人列",
            "officer 对照表",
            "branch name 查 officer",
            "各机构对应的人名",
            "officer name",
            "headoffice",
        ),
    ),
    "fill_order_sequence_labels": ActionAnnotation(
        "Fill order sequence labels",
        (
            "Seq No.",
            "顺序号",
            "No. 1、No. 2",
            "连续编号",
            "No. #",
            "sequence",
        ),
    ),
    "highlight_calendar_weekends_red": ActionAnnotation(
        "Highlight calendar weekends red",
        (
            "周末高亮",
            "Saturday 和 Sunday",
            "两天休息日",
            "周六周日",
            "#ff0000",
            "weekends",
        ),
    ),
    "set_decimal_separator_comma": ActionAnnotation(
        "Set decimal separator to comma",
        (
            "小数点显示成逗号",
            "逗号小数",
            "小数分隔符",
            "地区显示习惯",
            "decimal separator",
            "分隔符显示为逗号",
        ),
    ),
    "clean_movie_titles": ActionAnnotation(
        "Clean movie titles",
        (
            "电影名",
            "片名空格和大小写",
            "清理标题",
            "规范名称",
            "Garbage Movie Titles",
            "Clean Movie Titles",
            "Title Case",
        ),
    ),
    "fit_sheet_to_one_page_and_export_pdf": ActionAnnotation(
        "Fit sheet to one page and export PDF",
        (
            "单页版式",
            "调整到一页内",
            "页面适配和导出",
            "版面压到单页",
            "fit to one page",
            "同名 PDF",
        ),
    ),
    "extract_unique_names_preserving_order": ActionAnnotation(
        "Extract unique names preserving order",
        (
            "名单去重",
            "不重复名单",
            "姓名去重",
            "唯一人员清单",
            "Names with duplicates",
            "Unique Names",
        ),
    ),
    "assign_student_grades_from_scale": ActionAnnotation(
        "Assign student grades from scale",
        (
            "等级按上方量表",
            "评分表填等级",
            "scale table",
            "等级映射",
            "数值成绩转换成对应等级",
            "grade",
        ),
    ),
    "transpose_table_to_b8": ActionAnnotation(
        "Transpose table to B8",
        (
            "转置到 B8",
            "交换行列",
            "矩阵转置",
            "行列互换",
            "转置 B2:F5",
            "transpose",
        ),
    ),
    "add_pass_fail_held_validation": ActionAnnotation(
        "Add Pass/Fail/Held validation",
        (
            "三个固定选项",
            "Pass/Fail/Held",
            "数据验证",
            "受控下拉列表",
            "Pass、Fail、Held",
            "data validation",
        ),
    ),
    "fill_missing_row_and_column_totals": ActionAnnotation(
        "Fill missing row and column totals",
        (
            "行列合计",
            "Total 没算",
            "补总计",
            "两边缺少的合计",
            "行 Total、列 Total",
            "row and column totals",
        ),
    ),
}


FILE_ALIASES: dict[str, tuple[str, ...]] = {
    "Student_Level_Fill_Blank.xlsx": (
        "学生等级表",
        "等级数据",
    ),
    "SalesRep.xlsx": (
        "SalesRep",
        "销售代表表",
        "月度销售表",
    ),
    "IncomeStatement2.xlsx": ("利润表", "损益表"),
    "SmallBalanceSheet.xlsx": ("小型资产负债表",),
    "Customers_New_7digit_Id.xlsx": ("客户表", "客户编号"),
    "copy_sheet_insert.xlsx": ("资源清单", "资源表"),
    "WeeklySales.xlsx": ("WeeklySales", "周销售表", "周报表"),
    "NetIncome.xlsx": ("NetIncome", "净收益表"),
    "Zoom_Out_Oversized_Cells.xlsx": ("当前表格",),
    "Invoices.xlsx": ("发票表",),
    "FutureValue.xlsx": ("未来价值表",),
    "EntireSummerSales.xlsx": ("暑期销售表",),
    "PeriodRate.xlsx": ("PeriodRate", "期间利率表"),
    "Represent_in_millions_billions.xlsx": ("参数表",),
    "OrderId_Month_Chart.xlsx": ("订单表",),
    "DemographicProfile.xlsx": ("人口数据", "人员资料"),
    "Create_column_charts_using_statistics.xlsx": (
        "月度成本表",
        "统计表",
    ),
    "Multiply_Time_Number.xlsx": ("工资表", "工时表"),
    "Employee_Roles_and_Ranks.xlsx": ("员工表", "人员表"),
    "BoomerangSales.xlsx": (
        "BoomerangSales",
        "Boomerang 表",
        "回旋镖销售表",
    ),
    "Export_Calc_to_CSV.xlsx": ("Calc 文件",),
    "MaturityDate.xlsx": ("贷款表",),
    "Freeze_row_column.xlsx": ("当前工作表",),
    "RampUpAndDown.xlsx": ("升降数据",),
    "Employee_Age_By_Birthday.xlsx": ("员工表", "人事名单"),
    "Padding_Decimals_In_Formular.xlsx": ("文本公式",),
    "Arrang_Value_min_to_max.xlsx": ("金额表",),
    "SummerSales.xlsx": ("暑期销售表",),
    "Date_Budget_Variance_HideNA.xlsx": ("预算差异表",),
    "Keep_Two_decimal_points.xlsx": ("支出表",),
    "Name_Order_Id_move_column.xlsx": ("订单表",),
    "VLOOKUP_Fill_the_form.xlsx": ("分支机构表",),
    "Order_Sales_Serial#.xlsx": ("订单表",),
    "Calendar_Highlight_Weekend_Days.xlsx": ("日历", "排期表"),
    "Set_Decimal_Separator_Dot.xlsx": ("数值表",),
    "Movie_title_garbage_clean.xlsx": ("片名表",),
    "Resize_Cells_Fit_Page.xlsx": ("项目表",),
    "Names_Duplicate_Unique.xlsx": ("姓名表",),
    "Student_Grades_and_Remarks.xlsx": ("成绩表", "学生表"),
    "Students_Class_Subject_Marks.xlsx": ("学生成绩表",),
    "Order_Id_Mark_Pass_Fail.xlsx": ("订单表",),
    "Quarterly_Product_Sales_by_Zone.xlsx": (
        "季度销售交叉表",
        "分区销售表",
    ),
}


AMBIGUOUS_OBJECT_ALIASES = (
    "之前那种方式",
    "上次的版本",
    "照旧整理",
    "之前的结果",
    "以前的做法",
    "上次要求",
    "以前那版",
    "之前的口径",
    "上次那个结果",
    "之前做法",
    "上次的处理方式",
    "照旧收尾",
    "以前的版本",
    "之前做过的那个结果",
    "之前的分析方法",
    "上次那版",
    "照旧分析",
    "以前的方式",
    "之前交付的版本",
    "之前那张透视表",
    "上次的口径",
    "照旧汇总",
    "以前的透视方式",
    "之前做过的那张汇总透视表",
    "之前的方式",
    "上次的图表版式",
    "图表照旧",
    "以前那种图",
    "之前交付过的图表方式",
    "之前的格式",
    "以前的规则",
    "旧版",
    "旧规则",
    "旧办法",
    "旧版的输出方法",
    "之前的操作",
    "上次那套",
)


TEMPORAL_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "temporal_short",
        (
            "当前",
            "这次",
            "这回",
            "本轮",
            "今天",
            "现在",
            "this time",
            "today",
        ),
    ),
    (
        "temporal_medium",
        (
            "接下来",
            "后续",
            "近期",
            "这周",
            "下个月",
            "next month",
            "later",
        ),
    ),
    (
        "temporal_long",
        (
            "之前",
            "上次",
            "以前",
            "照旧",
            "老办法",
            "原来的规则",
            "沿用",
            "一直",
            "每次",
            "今后",
            "以后",
            "previous",
            "as before",
            "always",
        ),
    ),
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _split(value: str) -> tuple[str, ...]:
    return tuple(part for part in value.split("|") if part)


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return normalized or hashlib.sha1(
        value.encode("utf-8")
    ).hexdigest()[:12]


def condition_tag_id(filename: str) -> str:
    return f"condition:file:{_slug(filename)}"


def object_tag_id(action: str) -> str:
    return f"object:action:{action}"


def file_aliases(filename: str) -> tuple[str, ...]:
    stem = Path(filename).stem
    return tuple(
        dict.fromkeys(
            (
                filename,
                stem,
                *FILE_ALIASES.get(filename, ()),
            )
        )
    )


def _find_alias(text: str, aliases: Iterable[str]) -> str | None:
    matches = [
        alias
        for alias in aliases
        if alias and alias.casefold() in text.casefold()
    ]
    return max(matches, key=lambda value: (len(value), value)) if matches else None


def temporal_gold(text: str) -> tuple[tuple[str, ...], dict[str, str]]:
    found: dict[str, str] = {}
    for label, markers in TEMPORAL_MARKERS:
        marker = _find_alias(text, markers)
        if marker is not None:
            found[label] = marker
    return tuple(found), found


def _distractors(
    values: Sequence[str],
    expected: Sequence[str],
    *,
    key: str,
    count: int = 3,
) -> tuple[str, ...]:
    blocked = set(expected)
    candidates = [value for value in values if value not in blocked]
    ranked = sorted(
        candidates,
        key=lambda value: hashlib.sha256(
            f"{key}:{value}".encode("utf-8")
        ).digest(),
    )
    return tuple(ranked[:count])


def _task_catalog(dataset_root: Path) -> tuple[
    dict[str, dict[str, str]],
    dict[str, dict[str, str]],
]:
    tasks = _read_csv(dataset_root / "processed_data" / "task_index.csv")
    memories = _read_csv(
        dataset_root / "processed_data" / "memory_records.csv"
    )
    by_task = {row["task_id"]: row for row in tasks}
    by_memory = {row["memory_id"]: row for row in memories}
    for memory_id, memory in by_memory.items():
        task = by_task[memory["source_task_id"]]
        action = memory["expected_action"]
        if action not in ACTION_ANNOTATIONS:
            raise ValueError(f"unreviewed_action:{action}:{memory_id}")
        if task["input_file"] not in FILE_ALIASES:
            FILE_ALIASES.setdefault(task["input_file"], ())
    return by_task, by_memory


def _tag_catalog(
    by_task: dict[str, dict[str, str]],
    by_memory: dict[str, dict[str, str]],
) -> dict[str, list[dict[str, Any]]]:
    conditions = {}
    for task in by_task.values():
        filename = task["input_file"]
        conditions[condition_tag_id(filename)] = {
            "tag_id": condition_tag_id(filename),
            "name": filename,
            "groups": ["condition"],
            "aliases": list(file_aliases(filename)),
            "prototypes": [
                f"在 {filename} 工作簿中执行任务",
                f"处理电子表格文件 {filename}",
            ],
        }
    objects = {}
    for memory in by_memory.values():
        action = memory["expected_action"]
        reviewed = ACTION_ANNOTATIONS[action]
        tag_id = object_tag_id(action)
        value = objects.setdefault(
            tag_id,
            {
                "tag_id": tag_id,
                "name": reviewed.name,
                "groups": ["object"],
                "aliases": list(reviewed.aliases),
                "prototypes": [],
            },
        )
        value["prototypes"].append(memory["memory_summary"])
    objects[AMBIGUOUS_OBJECT_ID] = {
        "tag_id": AMBIGUOUS_OBJECT_ID,
        "name": "Unspecified prior workflow",
        "groups": ["object"],
        "aliases": list(AMBIGUOUS_OBJECT_ALIASES),
        "prototypes": [
            "沿用先前做法但没有说明具体是哪一种操作",
            "请求继续历史方案但当前文本无法唯一确定工作流",
        ],
    }
    return {
        "conditions": sorted(
            conditions.values(),
            key=lambda value: value["tag_id"],
        ),
        "objects": sorted(
            objects.values(),
            key=lambda value: value["tag_id"],
        ),
    }


def _support(text: str, aliases: Sequence[str]) -> tuple[str, str | None]:
    mention = _find_alias(text, aliases)
    return ("explicit", mention) if mention else ("implicit", None)


def _observation(
    *,
    text: str,
    filename: str | None,
    action: str,
    temporal_labels: Sequence[str],
    temporal_evidence: dict[str, str],
) -> dict[str, Any]:
    if filename is None:
        condition_id = None
        condition_support = "null"
        condition_evidence = None
    else:
        condition_id = condition_tag_id(filename)
        condition_support, condition_evidence = _support(
            text,
            file_aliases(filename),
        )
    if action == AMBIGUOUS_OBJECT_ID:
        object_id = action
        _, object_evidence = _support(
            text,
            AMBIGUOUS_OBJECT_ALIASES,
        )
    else:
        object_id = object_tag_id(action)
        _, object_evidence = _support(
            text,
            ACTION_ANNOTATIONS[action].aliases,
        )
    if object_evidence is None:
        object_evidence = (
            "semantic_review:"
            + (
                "unspecified_prior_workflow"
                if action == AMBIGUOUS_OBJECT_ID
                else action
            )
        )
    return {
        "condition_tag_id": condition_id,
        "object_tag_id": object_id,
        "attitude_direction": "positive",
        "temporal_labels": list(temporal_labels),
        "support": {
            "condition": condition_support,
            "object": "explicit",
            "attitude": "explicit",
            "temporal": "explicit" if temporal_labels else "null",
        },
        "evidence": {
            "condition": condition_evidence,
            "object": object_evidence,
            "attitude": "request_or_imperative_speech_act",
            "temporal": temporal_evidence,
        },
    }


def _event_cases(
    dataset_root: Path,
    by_task: dict[str, dict[str, str]],
    by_memory: dict[str, dict[str, str]],
    condition_ids: Sequence[str],
    object_ids: Sequence[str],
) -> list[dict[str, Any]]:
    cases = []
    for task_id, task in sorted(by_task.items()):
        raw = json.loads(
            (
                dataset_root
                / "raw_json"
                / task["raw_json_file"]
            ).read_text(encoding="utf-8")
        )
        memory = by_memory[task["memory_id"]]
        filename = task["input_file"]
        action = memory["expected_action"]
        text = f"{filename}: {raw['instruction']}"
        temporal_labels, temporal_evidence = temporal_gold(
            raw["instruction"]
        )
        observation = _observation(
            text=text,
            filename=filename,
            action=action,
            temporal_labels=temporal_labels,
            temporal_evidence=temporal_evidence,
        )
        expected_conditions = [observation["condition_tag_id"]]
        expected_objects = [observation["object_tag_id"]]
        cases.append(
            {
                "id": f"event:{task_id}",
                "source_kind": "event",
                "evaluation_track": "source_event",
                "query_type": "raw_instruction",
                "text": text,
                "raw_text": raw["instruction"],
                "gold_observations": [observation],
                "options": {
                    "condition_tag_ids": [
                        *expected_conditions,
                        *_distractors(
                            condition_ids,
                            expected_conditions,
                            key=f"event:{task_id}:condition",
                        ),
                    ],
                    "object_tag_ids": [
                        *expected_objects,
                        *_distractors(
                            object_ids,
                            expected_objects,
                            key=f"event:{task_id}:object",
                        ),
                    ],
                    "temporal_labels": list(TEMPORAL_LABELS),
                },
                "annotation_notes": [
                    "The document prefix is part of normalized OS event context.",
                    "Dataset lifecycle labels are not used as temporal gold.",
                ],
            }
        )
    return cases


def _query_cases(
    dataset_root: Path,
    by_task: dict[str, dict[str, str]],
    by_memory: dict[str, dict[str, str]],
    condition_ids: Sequence[str],
    object_ids: Sequence[str],
) -> list[dict[str, Any]]:
    queries = _read_csv(
        dataset_root / "processed_data" / "query_set.csv"
    )
    cases = []
    for row in queries:
        text = row["query_text"]
        temporal_labels, temporal_evidence = temporal_gold(text)
        observations = []
        notes = [
            "Gold action/file hints were reviewed against the query text.",
            "Synthetic lifecycle labels are not temporal gold.",
        ]
        if row["evaluation_track"] == "clarification_required":
            target_files = tuple(dict.fromkeys(_split(row["target_objects"])))
            filename = target_files[0] if len(target_files) == 1 else None
            observations.append(
                _observation(
                    text=text,
                    filename=filename,
                    action=AMBIGUOUS_OBJECT_ID,
                    temporal_labels=temporal_labels,
                    temporal_evidence=temporal_evidence,
                )
            )
            notes.append(
                "Ambiguous queries use a generic prior-workflow object; "
                "candidate actions are not treated as committed gold."
            )
        else:
            required = _split(row["required_memory_ids"])
            for memory_id in required:
                memory = by_memory[memory_id]
                task = by_task[memory["source_task_id"]]
                observations.append(
                    _observation(
                        text=text,
                        filename=task["input_file"],
                        action=memory["expected_action"],
                        temporal_labels=temporal_labels,
                        temporal_evidence=temporal_evidence,
                    )
                )
        expected_conditions = tuple(
            dict.fromkeys(
                value["condition_tag_id"]
                for value in observations
                if value["condition_tag_id"]
            )
        )
        expected_objects = tuple(
            dict.fromkeys(
                value["object_tag_id"] for value in observations
            )
        )
        cases.append(
            {
                "id": f"query:{row['query_id']}",
                "source_kind": "query",
                "evaluation_track": row["evaluation_track"],
                "query_type": row["query_type"],
                "text": text,
                "raw_text": text,
                "gold_observations": observations,
                "options": {
                    "condition_tag_ids": [
                        *expected_conditions,
                        *_distractors(
                            condition_ids,
                            expected_conditions,
                            key=f"{row['query_id']}:condition",
                        ),
                    ],
                    "object_tag_ids": [
                        *expected_objects,
                        *_distractors(
                            object_ids,
                            expected_objects,
                            key=f"{row['query_id']}:object",
                        ),
                    ],
                    "temporal_labels": list(TEMPORAL_LABELS),
                },
                "annotation_notes": notes,
            }
        )
    return cases


def build_annotation_dataset(dataset_root: Path) -> dict[str, Any]:
    by_task, by_memory = _task_catalog(dataset_root)
    catalog = _tag_catalog(by_task, by_memory)
    condition_ids = [
        value["tag_id"] for value in catalog["conditions"]
    ]
    object_ids = [value["tag_id"] for value in catalog["objects"]]
    cases = [
        *_event_cases(
            dataset_root,
            by_task,
            by_memory,
            condition_ids,
            object_ids,
        ),
        *_query_cases(
            dataset_root,
            by_task,
            by_memory,
            condition_ids,
            object_ids,
        ),
    ]
    support_counts: dict[str, dict[str, int]] = {}
    for role in ("condition", "object", "attitude", "temporal"):
        counts: dict[str, int] = {}
        for case in cases:
            for observation in case["gold_observations"]:
                status = observation["support"][role]
                counts[status] = counts.get(status, 0) + 1
        support_counts[role] = counts
    return {
        "schema_version": "os_agent.observation_gold.v1",
        "source_dataset": "os_agent_memory_query_benchmark_v3.1",
        "annotation_policy": {
            "annotator": "Codex semantic review plus deterministic export",
            "condition": (
                "The workbook or active file is the work environment."
            ),
            "object": (
                "The requested operation is the attitude subject."
            ),
            "attitude": (
                "A request or imperative is positive toward its main "
                "operation; negative constraints are not allowed to flip it."
            ),
            "temporal": (
                "Only explicit wording is labeled. Dataset STM/MTM/LTM "
                "metadata is rejected as text-level temporal gold."
            ),
            "implicit": (
                "A dataset hint is retained for end-to-end auditing but "
                "excluded from the fair extractable-role score."
            ),
        },
        "audit": {
            "task_count": len(by_task),
            "query_count": len(cases) - len(by_task),
            "case_count": len(cases),
            "condition_tag_count": len(catalog["conditions"]),
            "object_tag_count": len(catalog["objects"]),
            "support_counts": support_counts,
            "rejected_as_direct_gold": [
                "target_memory_type for temporal labels",
                "all candidate files as committed clarification conditions",
                "candidate actions as committed clarification objects",
            ],
        },
        "tag_catalog": catalog,
        "cases": cases,
    }
