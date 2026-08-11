from tools.render_static_in_out import (
    agent_input_text,
    knowledge_text,
    observation_text,
    operation_memory_text,
)


def test_opposing_attitudes_are_collapsed_into_uncertainty() -> None:
    observation = {
        "frames": [
            {
                "condition_tag_id": "app:web_browser",
                "object_tag_id": "app:web_browser",
                "attitude_direction": "positive",
                "confidence": 0.92,
            },
            {
                "condition_tag_id": "app:web_browser",
                "object_tag_id": "app:web_browser",
                "attitude_direction": "negative",
                "confidence": 0.95,
            },
        ]
    }

    text = observation_text(observation)

    assert "同时出现支持与反对表达" in text
    assert "positive" not in text
    assert "negative" not in text


def test_browser_log_summary_removes_internal_event_syntax() -> None:
    memory = {
        "summary": (
            'click web_element click(uid="abc") [00:01] Hello '
            '[00:12] Please open Wikipedia. ; not_supplied_by_compact_source；'
            'say message say(speaker="navigator", utterance="Done")'
        ),
        "expected_action": "click say",
    }

    lines = operation_memory_text(memory)
    text = "\n".join(lines)

    assert "Please open Wikipedia." in text
    assert "click(uid" not in text
    assert "not_supplied_by_compact_source" not in text
    assert "say(speaker" not in text


def test_agent_context_is_readable_text_without_gold_labels() -> None:
    row = {
        "query_text": "继续整理月度汇总表，不要画图。",
        "current_context_text": "SalesRep.xlsx 已打开。",
        "query_observation": {"formed": False, "frames": []},
        "retrieved_memories": [
            {
                "memory_kind": "legacy_memory",
                "summary": "在 Sheet2 建立 Month 和 Total 两列。",
                "constraints": "不创建图表",
                "source_event_count": 1,
            }
        ],
        "knowledge_references": [
            {
                "name": "Spreadsheet",
                "tag_id": "app:spreadsheet",
                "groups": ["condition", "object"],
                "matched_alias": "Calc",
                "exact_alias": True,
                "score": 2.0,
            }
        ],
    }

    text = agent_input_text(row)

    assert "【按相关性拼贴的用户记忆】" in text
    assert "【现在需要回答的用户请求】" in text
    assert text.rfind(row["query_text"]) > text.find("【通用知识提示】")
    assert "required_memory_ids" not in text
    assert "tag_id" not in text
    assert "```json" not in text


def test_knowledge_output_deduplicates_the_same_exact_alias() -> None:
    refs = [
        {
            "name": "File Manager",
            "tag_id": "app:file_manager",
            "groups": ["condition", "object"],
            "matched_alias": "文件管理器",
            "exact_alias": True,
            "score": 2.2,
        },
        {
            "name": "Peony",
            "tag_id": "app:desktop:peony",
            "groups": ["condition", "object"],
            "matched_alias": "文件管理器",
            "exact_alias": True,
            "score": 1.9,
        },
    ]

    text = knowledge_text(refs, scored=False)

    assert text.count("文件管理器") == 2  # label and matched alias, only one entry
    assert "Peony" not in text
