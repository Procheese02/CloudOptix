import argparse
import json
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv
from langchain_core.tools import tool

if TYPE_CHECKING:
    from agent import AgentState

PROJECT_ROOT = Path(__file__).resolve().parent
BILLING_PATH = PROJECT_ROOT / "data" / "mock_billing.json"
INSTANCE_DOWNGRADE_ORDER = [
    "t3.micro",
    "t3.small",
    "t3.medium",
    "t3.large",
    "t3.xlarge",
    "t3.2xlarge",
]

load_dotenv(dotenv_path=PROJECT_ROOT / ".env")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the CloudOptix EC2 cost optimization workflow.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate the AWS action plan without modifying any infrastructure. This is the default mode.",
    )
    mode.add_argument(
        "--execute",
        action="store_true",
        help="Ask for human approval, then execute the EC2 resize through AWS boto3.",
    )
    return parser.parse_args()


def get_aws_region() -> str:
    region = os.environ.get("AWS_DEFAULT_REGION", "").strip()
    if not region:
        raise ValueError("缺少 AWS_DEFAULT_REGION，请在 .env 中配置 AWS 区域，例如 us-east-2。")

    availability_zone_match = re.fullmatch(r"([a-z]{2}-[a-z]+-\d)[a-z]", region)
    if availability_zone_match:
        corrected_region = availability_zone_match.group(1)
        print(f"⚠️ AWS_DEFAULT_REGION 不能写可用区 {region}，已自动改用区域 {corrected_region}。")
        return corrected_region

    return region


def get_target_instance_type(instance_type: str) -> str:
    if instance_type not in INSTANCE_DOWNGRADE_ORDER:
        raise ValueError(f"暂不支持自动推导 {instance_type} 的降级目标。")

    current_index = INSTANCE_DOWNGRADE_ORDER.index(instance_type)
    target_index = max(0, current_index - 2)
    if target_index == current_index:
        raise ValueError(f"{instance_type} 已经是当前规则中的最低规格，无需继续降级。")
    return INSTANCE_DOWNGRADE_ORDER[target_index]


def print_action_plan(instance_id: str, current_type: str, target_type: str, mode: str) -> None:
    print("\n" + "=" * 40)
    print("📋 AWS Action Plan")
    print("=" * 40)
    print(f"Instance ID: {instance_id}")
    print(f"Current type: {current_type}")
    print(f"Target type: {target_type}")
    print(f"Mode: {mode}")
    print("Planned steps: stop instance -> modify instance type -> start instance")
    print("=" * 40 + "\n")


@tool
def execute_aws_downgrade(instance_id: str, target_type: str) -> str:
    """
    当决定要降低服务器成本时调用此工具。
    执行真实的 AWS EC2 实例降级操作。
    """
    print("\n" + "🚨 " * 10 + " 生产环境变更确认 " + "🚨 " * 10)
    print(f"⚠️  AI 智能体请求执行物理变更：将真实实例 [{instance_id}] 变更为 [{target_type}]")

    confirm = input("❓ 是否允许 AI 执行该物理变更？输入 Y 确认，N 取消: ").strip().upper()
    if confirm != "Y":
        print("❌ 已拦截：人类管理员拒绝了此次操作。")
        return f"Action cancelled by human administrator. No changes made to {instance_id}."

    print("\n🚀 授权通过！正在连接 AWS 底层接口...")
    ec2 = boto3.client("ec2", region_name=get_aws_region())
    stopped_by_tool = False

    try:
        print("⏳ 1/3 正在发送关机指令，等待实例完全停止 (可能需要十几秒)...")
        ec2.stop_instances(InstanceIds=[instance_id])
        ec2.get_waiter("instance_stopped").wait(InstanceIds=[instance_id])
        stopped_by_tool = True

        print(f"⚙️ 2/3 实例已停止，正在修改底层硬件规格为 {target_type} ...")
        ec2.modify_instance_attribute(
            InstanceId=instance_id,
            InstanceType={"Value": target_type},
        )

        print("⚡️ 3/3 规格修改成功，正在重新启动实例...")
        ec2.start_instances(InstanceIds=[instance_id])
        ec2.get_waiter("instance_running").wait(InstanceIds=[instance_id])
        stopped_by_tool = False
        print("✅ 物理机已重新上线！")

        return f"Success: 物理机 {instance_id} 已成功降级为 {target_type} 并重新上线。"

    except ClientError as exc:
        if stopped_by_tool:
            try:
                print("⚠️ 修改失败，正在尝试把实例恢复启动...")
                ec2.start_instances(InstanceIds=[instance_id])
            except Exception as restart_exc:
                print(f"❌ 自动恢复启动失败: {restart_exc}")

        error = exc.response.get("Error", {})
        if error.get("Code") == "FreeTierRestrictionError":
            print("⚠️ AWS 免费计划账号不允许修改实例规格，本次演示已到达 Human-in-the-loop 和 API 调用阶段。")
            return (
                "Demo blocked by AWS FreeTierRestrictionError: 免费计划账号不允许执行 "
                "ModifyInstanceAttribute，因此没有完成真实降级。"
            )
        error_msg = f"Error: 执行真实物理变更失败。原因: {exc}"
        print(f"❌ 发生严重错误: {error_msg}")
        return error_msg
    except Exception as exc:
        if stopped_by_tool:
            try:
                print("⚠️ 修改失败，正在尝试把实例恢复启动...")
                ec2.start_instances(InstanceIds=[instance_id])
            except Exception as restart_exc:
                print(f"❌ 自动恢复启动失败: {restart_exc}")

        error_msg = f"Error: 执行真实物理变更失败。原因: {exc}"
        print(f"❌ 发生严重错误: {error_msg}")
        return error_msg


def load_billing_data() -> dict:
    with BILLING_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def _parse_percent(value: object) -> float:
    return float(str(value).strip().strip("%"))


def get_instances(billing_data: dict) -> list[dict]:
    instances = billing_data.get("instances")
    if isinstance(instances, list):
        return instances
    if billing_data.get("instance_id"):
        return [billing_data]
    return []


def is_execution_candidate(instance: dict) -> bool:
    metrics = instance.get("metrics", {})
    avg_cpu = _parse_percent(metrics.get("avg_cpu_utilization", "100%"))
    peak_cpu = _parse_percent(metrics.get("peak_cpu_utilization", "100%"))
    avg_memory = _parse_percent(metrics.get("avg_memory_utilization", "100%"))
    return avg_cpu < 10.0 and peak_cpu <= 30.0 and avg_memory < 20.0 and not instance.get("protected")


def build_action_result(billing_data: dict, execute: bool) -> str:
    instances = get_instances(billing_data)
    if not instances:
        return "账单缺少 EC2 实例信息，无法生成自动降级计划。"

    candidates = [instance for instance in instances if is_execution_candidate(instance)]
    if not candidates:
        return "No action: 没有可自动执行的低利用率 EC2 实例。"

    mode = "execute" if execute else "dry-run"
    action_results = []
    for instance in candidates:
        instance_id = instance.get("instance_id")
        instance_type = instance.get("instance_type")
        if not instance_id or not instance_type:
            action_results.append("Skipped: 账单条目缺少 instance_id 或 instance_type。")
            continue

        try:
            target_type = get_target_instance_type(instance_type)
        except ValueError as exc:
            action_results.append(f"Skipped: {instance_id} 无法自动降级。原因: {exc}")
            continue

        print_action_plan(instance_id, instance_type, target_type, mode)

        if not execute:
            action_results.append(
                f"Dry run: would downgrade {instance_id} from {instance_type} to {target_type}. No AWS changes were made."
            )
        else:
            action_results.append(execute_aws_downgrade.invoke({
                "instance_id": instance_id,
                "target_type": target_type,
            }))

    return "\n".join(action_results)


def main() -> None:
    from agent import app, close_qdrant_clients

    args = parse_args()
    execute = args.execute

    print("\n" + "=" * 50)
    print("🚀 CloudOptix 智能体工作流启动")
    print("=" * 50 + "\n")

    if not execute:
        print("🧪 当前运行模式：dry-run。只生成执行计划，不会修改 AWS 资源。")
    else:
        print("⚠️ 当前运行模式：execute。人工确认后会尝试修改真实 AWS 资源。")

    billing_data = load_billing_data()
    initial_state = {
        "billing_data": billing_data,
        "needs_optimization": False,
        "rag_context": "",
        "final_report": "",
        "action_taken": "",
    }

    final_state = app.invoke(initial_state)

    if "final_report" in final_state:
        print("\n✅ 最终生成的优化方案：\n")
        print(final_state["final_report"])

        try:
            action_taken = build_action_result(billing_data, execute)
        except Exception as exc:
            action_taken = f"Error: 自动降级计划生成失败。原因: {exc}"
        final_state["action_taken"] = action_taken

        print("\n" + "=" * 40)
        print("⚡️ 自动化执行结果记录：")
        print(final_state.get("action_taken", "无执行记录"))
        print("=" * 40 + "\n")
    else:
        print("\n✅ 巡检结束：EC2 fleet 运行良好，无需优化。")


if __name__ == "__main__":
    try:
        main()
    finally:
        close_qdrant_clients()
