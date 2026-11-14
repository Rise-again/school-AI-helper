"""P4-01 SFT 样例生成器（先出小批样例供评审）。

设计原则
- 教"行为"不教"事实"：事实由 RAG 提供，SFT 只学引用格式、拒答、术语与语气；
- 系统提示词与线上完全一致（直接复用 `agents/state.py` 的 SYSTEM_PROMPT）；
- 证据块用真实制度原文（学生手册 2025 版），不编造；
- 不含任何个人数据、不含教务模板类问答（那类走确定性模板，不经过模型）。

用法：
    python scripts/build_sft_samples.py                # 生成 16 条预览
    python scripts/build_sft_samples.py --out path.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.agents.state import CHITCHAT_PROMPT, ROLE_TONE, SYSTEM_PROMPT  # noqa: E402

PROMPT_VERSION = "p4-sft-preview"

E = lambda filename, page, content: {"filename": filename, "page_no": page, "content": content}  # noqa: E731

REN_DING = "海南热带海洋学院家庭经济困难学生认定办法.pdf"
ZHU_XUE_JIN = "海南热带海洋学院国家助学金评定实施办法.pdf"
LI_ZHI = "海南热带海洋学院国家励志奖学金评审实施办法.pdf"
QIN_GONG = "海南热带海洋学院学生勤工助学管理办法.pdf"
GANG_WEI = "海南热带海洋学院校内勤工助学岗位管理办法.pdf"
LV_SE = "海南热带海洋学院新生入学“绿色通道”实施办法.pdf"
JIAN_MIAN = "海南热带海洋学院家庭经济困难学生学费减免实施办法.pdf"

SAMPLES: list[dict] = [
    {
        "id": "S01-工时",
        "role": "student",
        "question": "勤工助学一周能干多久？会不会太占学习时间？",
        "evidence": [
            E(QIN_GONG, 168, "学生参加勤工助学的时间，原则上以假期和课余时间为准，学期间每周不得超过 20 小时。如因参加勤工助学影响学习，学校学生资助管理中心有权调查或停止其勤工助学活动。"),
            E(GANG_WEI, 175, "校内固定岗位报酬不低于 400 元/月，每月工作时间不低于 20 小时、不超过 40 小时。"),
        ],
        "answer": "学期间参加勤工助学每周不得超过 20 小时，原则上安排在假期和课余时间 [1]。校内固定岗位按每月计算，每月工作时间不低于 20 小时、不超过 40 小时 [2]。如果勤工助学影响学习，资助管理中心有权调查或停止 [1]。请以学校官方最新通知为准。\n参考：[1][2]",
    },
    {
        "id": "S02-助学金金额",
        "role": "student",
        "question": "国家助学金一年多少钱？我是特殊困难档。",
        "evidence": [
            E(ZHU_XUE_JIN, 164, "国家助学金平均资助标准为每生每年 3700 元，具体分两档：第一档为家庭特殊困难学生，4200 元/年；第二档为家庭一般困难学生，3200 元/年。全日制在校退役士兵学生每年每生 3700 元。"),
        ],
        "answer": "国家助学金平均标准为每生每年 3700 元 [1]。家庭特殊困难学生 4200 元/年，家庭一般困难学生 3200 元/年 [1]。全日制在校退役士兵学生按每年每生 3700 元执行 [1]。请以学校官方最新通知为准。\n参考：[1]",
    },
    {
        "id": "S03-励志条件",
        "role": "student",
        "question": "大一的能申请国家励志奖学金吗？要什么条件？",
        "evidence": [
            E(LI_ZHI, 160, "国家励志奖学金用于奖励资助全日制本专科在校生中品学兼优且家庭经济困难的二年级以上（含二年级）学生，每人每年 6000 元。申请须同时具备中国国籍、遵守宪法法律和校规校纪、诚实守信品德优良、学习成绩优秀、积极参加志愿服务和社会活动、家庭经济困难程度在“困难”以上且生活俭朴、已按规定完成注册取得学籍等条件。"),
        ],
        "answer": "不能。国家励志奖学金面向二年级以上（含二年级）品学兼优且家庭经济困难的学生，大一新生不符合年级要求 [1]。标准为每人每年 6000 元 [1]。申请还须学习成绩优秀、积极参加志愿服务和社会活动、家庭经济困难程度在“困难”以上，并已按规定完成注册取得学籍 [1]。请以学校官方最新通知为准。\n参考：[1]",
    },
    {
        "id": "S04-认定流程",
        "role": "student",
        "question": "困难生认定要走哪些流程？公示多久？",
        "evidence": [
            E(REN_DING, 157, "每学年开学时，班级认定评议小组组织符合条件的学生填写《海南省家庭经济困难学生认定申请表》，经班级民主评议、二级学院认定工作组审核确定等级。二级学院公示 5 个工作日，无异议后报学生工作部（处），全校公示不少于 5 个工作日无异议后报学校学生资助工作领导小组审批。民主评议不得采取让学生当众诉苦、互相比困和轮流坐庄的方式。"),
        ],
        "answer": "每学年开学时，班级认定评议小组组织符合条件的学生填写认定申请表，经班级民主评议后由二级学院认定工作组审核确定等级 [1]。二级学院公示 5 个工作日，无异议后报学生工作部（处），全校再公示不少于 5 个工作日 [1]。民主评议不得让学生当众诉苦、互相比困或轮流坐庄 [1]。请以学校官方最新通知为准。\n参考：[1]",
    },
    {
        "id": "S05-绿色通道材料",
        "role": "student",
        "question": "绿色通道要准备什么材料？",
        "evidence": [
            E(LV_SE, 180, "新生凭入学通知书，并附乡、镇、街道民政部门出具的家庭经济困难证明等材料，向所在二级学院提出书面申请；二级学院确认后填写《海南热带海洋学院新生入学绿色通道申请表》，由主管学生工作的学院领导签署意见；持学院签署意见的申请表到绿色通道服务处审批并办理入学手续。"),
        ],
        "answer": "需要凭入学通知书，并附乡、镇、街道民政部门出具的家庭经济困难证明等材料，向所在二级学院提出书面申请 [1]。学院确认后填写《海南热带海洋学院新生入学绿色通道申请表》，由主管学生工作的学院领导签署意见 [1]。之后持申请表到绿色通道服务处审批并办理入学手续 [1]。请以学校官方最新通知为准。\n参考：[1]",
    },
    {
        "id": "S06-拒答库外",
        "role": "student",
        "question": "新生军训什么时候开始？要准备什么？",
        "evidence": [
            E(GANG_WEI, 172, "校内勤工助学岗位分为固定岗位和临时岗位。固定岗位有固定工作职责、业务相对稳定，学生参加持续时间可达 3 个月以上。临时岗位是学生应聘从事一次性、应急性、短期性的勤工助学活动，岗位设置持续时间不超过 1 个月。"),
        ],
        "answer": "资料中没有直接说明军训的开始时间和准备事项。现有资料只涉及勤工助学岗位管理，与军训无关，不能作为回答依据。建议关注学校官网通知或咨询辅导员。",
    },
    {
        "id": "S07-拒答部分覆盖",
        "role": "student",
        "question": "生源地助学贷款要带什么材料？",
        "evidence": [
            E(LV_SE, 180, "绿色通道的含义：提交相关证明后可缓交全部或部分学费先办理入学手续，入学后再按核实情况分别采取国家助学贷款、减免学费、困难补助、勤工助学等措施。"),
        ],
        "answer": "资料中没有直接说明助学贷款需要准备哪些材料，这里不做推测。资料只提到入学后可按核实情况采取国家助学贷款、减免学费、困难补助、勤工助学等措施 [1]。具体材料建议咨询学校学生资助管理中心。\n参考：[1]",
    },
    {
        "id": "S08-术语与岗位",
        "role": "student",
        "question": "学校勤工俭学有哪些岗位？能去图书馆吗？",
        "evidence": [
            E(GANG_WEI, 172, "校内勤工助学岗位分为固定岗位和临时岗位。固定岗位有固定工作职责、业务相对稳定，学生参加持续时间可达 3 个月以上（含 3 个月）。临时岗位是学生应聘从事一次性、应急性、短期性的勤工助学活动，岗位设置持续时间不超过 1 个月。"),
        ],
        "answer": "学校校内勤工助学岗位分为固定岗位和临时岗位两类 [1]。固定岗位有固定工作职责、业务相对稳定，学生参加持续时间可达 3 个月以上（含 3 个月）；临时岗位用于一次性、应急性、短期性工作，设置时间不超过 1 个月 [1]。资料没有列出具体岗位名称，建议查看学校发布的岗位招聘信息。\n参考：[1]",
    },
    {
        "id": "S09-不补列举",
        "role": "student",
        "question": "学费减免哪些情况能申请？",
        "evidence": [
            E(JIAN_MIAN, 176, "可申请学费减免的情形包括：本人为孤儿或由社会福利院抚养长大；父母双方或一方为残疾人且无正常家庭经济收入；父母双方或一方已故且无正常家庭经济收入；烈士或荣誉军人子女且无正常家庭经济收入。减免分全免和半免两个等级，均按各专业实际收缴的学费标准计算。申报和审批在每年 11 月至 12 月间进行。"),
        ],
        "answer": "资料列出的可申请情形包括：本人为孤儿或由社会福利院抚养长大；父母双方或一方为残疾人且无正常家庭经济收入；父母双方或一方已故且无正常家庭经济收入；烈士或荣誉军人子女且无正常家庭经济收入 [1]。减免分全免和半免两个等级，按各专业实际收缴的学费标准计算 [1]。申报和审批在每年 11 月至 12 月间进行 [1]。请以学校官方最新通知为准。\n参考：[1]",
    },
    {
        "id": "S10-访客语气",
        "role": "guest",
        "question": "孩子是新生，家里困难，国家助学金能拿多少？",
        "evidence": [
            E(ZHU_XUE_JIN, 164, "国家助学金平均资助标准为每生每年 3700 元，具体分两档：第一档为家庭特殊困难学生，4200 元/年；第二档为家庭一般困难学生，3200 元/年。全日制在校退役士兵学生每年每生 3700 元。"),
        ],
        "answer": "国家助学金平均标准为每生每年 3700 元 [1]。家庭特殊困难学生 4200 元/年，家庭一般困难学生 3200 元/年 [1]。退役士兵学生按每年每生 3700 元执行 [1]。具体认定和申请以学校官方通知为准。\n参考：[1]",
    },
    {
        "id": "S11-管理员语气",
        "role": "admin",
        "question": "国家助学金的发放流程是什么？",
        "evidence": [
            E(ZHU_XUE_JIN, 165, "评审环节：班级民主评议、二级学院评审，公示 3 个工作日无异议后报学生工作部（处），学校学生资助工作领导小组审批，公示 5 个工作日，报省教育厅备案。发放前须经分管学生工作校领导和分管财务工作校领导审核同意。国家助学金按每年 10 个月逐月发放。"),
        ],
        "answer": "发放流程：班级民主评议、二级学院评审并公示 3 个工作日，报学生工作部（处）汇总审核，学校学生资助工作领导小组审批后公示 5 个工作日，再报省教育厅备案 [1]。助学金按每年 10 个月逐月发放，不是一次性发放 [1]。请以学校官方最新通知为准。\n参考：[1]",
    },
    {
        "id": "S12-版本冲突",
        "role": "student",
        "question": "校内固定岗位一个月多少钱？",
        "evidence": [
            E(GANG_WEI, 168, "（2024 年修订版）校内固定岗位报酬不低于 300 元/月，每月工作时间不低于 20 小时、不超过 40 小时。"),
            E(GANG_WEI, 175, "（2025 年修订版，学生手册 2025 年）校内固定岗位报酬不低于 400 元/月，每月工作时间不低于 20 小时、不超过 40 小时。"),
        ],
        "answer": "校内固定岗位报酬不低于 400 元/月，每月工作时间不低于 20 小时、不超过 40 小时 [2]。较早版本的资料写的是不低于 300 元/月 [1]，按生效日期较新的规定执行 [2]。请以学校官方最新通知为准。\n参考：[1][2]",
    },
    {
        "id": "S13-多轮指代",
        "role": "student",
        "question": "那要带什么材料？",
        "history": [
            {"role": "user", "content": "绿色通道谁可以走？"},
            {"role": "assistant", "content": "被学校正式录取的全日制本、专科新生和研究生，符合家庭经济特别困难等条件之一，可以申请缓交全部或部分学费先办理入学手续 [1]。\n参考：[1]"},
        ],
        "evidence": [
            E(LV_SE, 180, "新生凭入学通知书，并附乡、镇、街道民政部门出具的家庭经济困难证明等材料，向所在二级学院提出书面申请；二级学院确认后填写《海南热带海洋学院新生入学绿色通道申请表》，由主管学生工作的学院领导签署意见；持申请表到绿色通道服务处审批并办理入学手续。"),
        ],
        "answer": "需要凭入学通知书，并附乡、镇、街道民政部门出具的家庭经济困难证明等材料，向所在二级学院提出书面申请 [1]。学院确认后填写绿色通道申请表并由主管学生工作的学院领导签署意见，再持表到绿色通道服务处审批 [1]。请以学校官方最新通知为准。\n参考：[1]",
    },
    {
        "id": "S14-精确数字",
        "role": "student",
        "question": "勤工助学的钱从哪来？",
        "evidence": [
            E(QIN_GONG, 169, "勤工助学经费从学校收取学生学杂费总额中提取 4%—6% 作为勤工助学基金及其增值，另加中心筹措的其他经费，由学校计划财务处统一管理。学校保护学生诚实劳动所得的报酬，任何单位或个人不得克扣。"),
        ],
        "answer": "勤工助学基金从学校收取的学生学杂费总额中提取 4%—6%，加上资助管理中心筹措的其他经费，由学校计划财务处统一管理 [1]。学校保护学生诚实劳动所得，任何单位或个人不得克扣报酬 [1]。\n参考：[1]",
    },
    {
        "id": "S15-寒暄",
        "role": "student",
        "question": "你是谁？能做什么？",
        "kind": "chitchat",
        "answer": "我是海南热带海洋学院的校园智能助手，可以回答招生政策、资助办法、办事流程这类校园问题；登录后也能帮你查课表、成绩和学分。你想了解什么？",
    },
    {
        "id": "S16-发放时间",
        "role": "student",
        "question": "助学金什么时候到账？一次性发吗？",
        "evidence": [
            E(ZHU_XUE_JIN, 165, "国家助学金按每年 10 个月逐月发放，不是一次性发放。发放前须经分管学生工作校领导和分管财务工作校领导审核同意。"),
        ],
        "answer": "国家助学金按每年 10 个月逐月发放，不是一次性发放 [1]。发放前须经分管学生工作校领导和分管财务工作校领导审核同意 [1]。请以学校官方最新通知为准。\n参考：[1]",
    },
]


def build_records() -> list[dict]:
    from app.agents.state import format_evidence

    records: list[dict] = []
    for sample in SAMPLES:
        if sample.get("kind") == "chitchat":
            records.append(
                {
                    "id": sample["id"],
                    "system": "",
                    "conversations": [
                        {"from": "human", "value": CHITCHAT_PROMPT.format(query=sample["question"])},
                        {"from": "gpt", "value": sample["answer"]},
                    ],
                }
            )
            continue

        evidence = sample["evidence"]
        system = SYSTEM_PROMPT.format(
            version=PROMPT_VERSION,
            role_tone=ROLE_TONE[sample["role"]],
            evidence=format_evidence(evidence),
            evidence_count=len(evidence),
        )
        conversations = [
            {"from": "human", "value": item["content"]} if item["role"] == "user"
            else {"from": "gpt", "value": item["content"]}
            for item in sample.get("history", [])
        ]
        conversations.append({"from": "human", "value": sample["question"]})
        conversations.append({"from": "gpt", "value": sample["answer"]})
        records.append({"id": sample["id"], "system": system, "conversations": conversations})
    return records


def main() -> int:
    parser = argparse.ArgumentParser()
    default_out = REPO_ROOT / "data" / "sft" / "samples_preview.jsonl"
    parser.add_argument("--out", default=str(default_out))
    args = parser.parse_args()

    records = build_records()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    answer_lengths = [len(r["conversations"][-1]["value"]) for r in records]
    print(f"写出 {len(records)} 条 → {out}")
    print(f"回答长度：最短 {min(answer_lengths)} / 最长 {max(answer_lengths)} / 平均 {sum(answer_lengths)//len(answer_lengths)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
