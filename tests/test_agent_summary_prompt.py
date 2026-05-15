import json
import unittest
from unittest.mock import patch

import agent
import analyze_billing
import generate_mock


class AgentSummaryPromptTests(unittest.TestCase):
    def test_agent_import_does_not_initialize_llm_or_retriever(self):
        self.assertIsNone(agent.llm)
        self.assertIsNone(agent.retriever)
        self.assertFalse(agent.retriever_configured)

    def test_inspector_adds_enterprise_summary_state(self):
        billing_data = generate_mock.generate_billing_data(fleet_size=40, seed=42, autoscale_count=2)

        state = agent.inspector_node({"billing_data": billing_data})

        self.assertIn("billing_analysis", state)
        self.assertIn("enterprise_summary", state)
        self.assertIn("data_quality", state)
        self.assertIn("top_candidates", state)
        self.assertEqual(
            state["fleet_summary"]["optimizable_resource_count"],
            state["enterprise_summary"]["enterprise_savings_summary"]["eligible_candidate_count"],
        )

    def test_advisor_prompt_uses_summary_not_full_instance_list(self):
        billing_data = generate_mock.generate_billing_data(fleet_size=500, seed=42, autoscale_count=4)
        analysis = analyze_billing.analyze_billing_data(billing_data)
        state = {
            "billing_data": billing_data,
            "billing_analysis": analysis,
            "fleet_summary": analysis["enterprise_summary"]["enterprise_savings_summary"],
        }

        prompt = agent.build_advisor_prompt(state, "pricing policy context")
        full_billing_json = json.dumps(billing_data, indent=2, ensure_ascii=False)
        top_candidates = analysis["enterprise_summary"]["enterprise_savings_summary"]["top_candidates"]
        top_candidate_ids = {candidate["instance_id"] for candidate in top_candidates}
        non_candidate_ids = [
            instance["instance_id"]
            for instance in billing_data["instances"]
            if instance["instance_id"] not in top_candidate_ids
        ]

        self.assertIn("enterprise_savings_summary", prompt)
        self.assertIn("missing_metrics_coverage", prompt)
        self.assertIn("top_candidates", prompt)
        self.assertLess(len(prompt), len(full_billing_json) * 0.5)
        self.assertNotIn('"instances"', prompt)
        self.assertNotIn(non_candidate_ids[-1], prompt)

    def test_advisor_node_invokes_llm_with_summary_prompt(self):
        billing_data = generate_mock.generate_billing_data(fleet_size=60, seed=42, autoscale_count=4)
        analysis = analyze_billing.analyze_billing_data(billing_data)
        captured = {}

        class FakeLLM:
            def invoke(self, messages):
                captured["messages"] = messages

                class Response:
                    content = "summary report"

                return Response()

        with patch("agent.get_llm", return_value=FakeLLM()):
            result = agent.advisor_node({
                "billing_data": billing_data,
                "billing_analysis": analysis,
                "fleet_summary": analysis["enterprise_summary"]["enterprise_savings_summary"],
                "rag_context": "pricing policy context",
            })

        prompt = captured["messages"][1].content
        self.assertEqual(result["final_report"], "summary report")
        self.assertIn("enterprise_savings_summary", prompt)
        self.assertNotIn('"instances"', prompt)


if __name__ == "__main__":
    unittest.main()
