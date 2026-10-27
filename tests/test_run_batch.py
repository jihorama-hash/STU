import hashlib
import tempfile
import unittest
from pathlib import Path

from roundabout.run_batch import (
    StagePlan,
    decide_actions,
    stage_is_complete,
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class BatchResumeTest(unittest.TestCase):
    def make_plan(self, root: Path, name: str, signature: str) -> StagePlan:
        output = root / f"{name}.txt"
        output.write_text(name, encoding="utf-8")
        return StagePlan(
            video_id="DJI_TEST",
            name=name,
            command=("python", "-m", f"roundabout.{name}"),
            outputs=(output,),
            signature=signature,
            validator=lambda: output.read_text(encoding="utf-8") == name,
        )

    def complete_state(self, plan: StagePlan) -> dict[str, object]:
        output = plan.outputs[0]
        return {
            "video_id": plan.video_id,
            "stages": {
                plan.name: {
                    "status": "complete",
                    "signature": plan.signature,
                    "artifacts": {str(output): digest(output)},
                }
            },
        }

    def test_completed_stage_with_matching_artifact_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = self.make_plan(Path(directory), "detect", "signature-1")
            state = self.complete_state(plan)
            self.assertTrue(stage_is_complete(plan, state))
            action = decide_actions((plan,), state, force=False)[0]
            self.assertFalse(action.run)

    def test_changed_artifact_invalidates_completed_stage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = self.make_plan(Path(directory), "detect", "signature-1")
            state = self.complete_state(plan)
            plan.outputs[0].write_text("changed", encoding="utf-8")
            self.assertFalse(stage_is_complete(plan, state))

    def test_rerun_propagates_to_downstream_stages(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            detect = self.make_plan(root, "detect", "signature-1")
            filter_plan = self.make_plan(root, "filter", "signature-2")
            state = self.complete_state(filter_plan)
            detect.outputs[0].write_text("damaged", encoding="utf-8")
            actions = decide_actions((detect, filter_plan), state, force=False)
            self.assertEqual([action.run for action in actions], [True, True])
            self.assertEqual(actions[1].reason, "upstream will run")

    def test_legacy_risk_output_is_not_trusted_without_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = self.make_plan(Path(directory), "risk", "signature-1")
            self.assertFalse(
                stage_is_complete(plan, {"video_id": "DJI_TEST", "stages": {}})
            )

    def test_valid_output_recovers_failed_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = self.make_plan(Path(directory), "detect", "signature-1")
            state = self.complete_state(plan)
            state["stages"]["detect"]["status"] = "failed"
            state["stages"]["detect"].pop("artifacts")
            self.assertTrue(stage_is_complete(plan, state))


if __name__ == "__main__":
    unittest.main()
