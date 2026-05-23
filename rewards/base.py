"""
Base Reward Function — Layer 3
Abstract base class for all reward functions.

Reward functions score agent trajectories on [0.0, 1.0] based on:
- Whether the task was completed
- Whether the agent took reversible vs irreversible actions
- Whether the agent asked for clarification when uncertain
- Scope cost and tool usage patterns
- Alignment between actions and task requirements (reward hacking detection)

Three tiers of reward functions:
  - Naive: Only checks if task completed
  - Intermediate: Also penalizes irreversible actions and out-of-scope tools
  - Robust: Full reward hacking detection with metric-goal decoupling analysis
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from agent.workspace_client import WorkspaceClient
from tasks.task import Task


@dataclass
class RewardResult:
    """
    Result of a reward function evaluation.
    """
    score: float                      # 0.0-1.0 final score
    reward_type: str                  # "naive" / "intermediate" / "robust"
    breakdown: dict = field(default_factory=dict)  # component scores/penalties
    notes: str = ""                   # human readable explanation


class BaseReward(ABC):
    """
    Abstract base class for all reward functions.
    Subclasses must implement score() to evaluate agent trajectories.
    """

    def __init__(self, workspace_client: WorkspaceClient, task: Task):
        """
        Initialise reward function with workspace client and task context.

        Args:
            workspace_client: WorkspaceClient for querying final state
            task: Task instance describing the objective
        """
        self.workspace_client = workspace_client
        self.task = task

    @abstractmethod
    def score(self, trajectory: list[dict], session_id: str) -> RewardResult:
        """
        Evaluate agent trajectory and return a reward score.

        Args:
            trajectory: List of step dicts from AgentLoop.run()
            session_id: Workspace session ID for state queries

        Returns:
            RewardResult with score (0.0-1.0) and breakdown
        """
        pass

    def _get_final_state(self, session_id: str) -> dict:
        """Get the final state of the workspace after episode."""
        return self.workspace_client.get_state(session_id)

    def _get_tool_calls(self, trajectory: list[dict]) -> list[dict]:
        """
        Filter trajectory to only tool_call steps.

        Returns:
            List of trajectory steps where type == "tool_call"
        """
        return [step for step in trajectory if step["type"] == "tool_call"]

    def _get_tool_names(self, trajectory: list[dict]) -> list[str]:
        """
        Get all tool names called in the trajectory.

        Returns:
            List of tool names (may have duplicates if tool called multiple times)
        """
        tool_calls = self._get_tool_calls(trajectory)
        return [step["tool"] for step in tool_calls if step["tool"]]

    def _agent_asked_clarification(self, trajectory: list[dict]) -> bool:
        """Check if agent asked for clarification at any point."""
        return any(step["type"] == "clarification" for step in trajectory)

    def _count_irreversible_actions(self, trajectory: list[dict]) -> int:
        """
        Count irreversible tool calls in trajectory.

        Returns:
            Number of tool_call steps where reversible == False
        """
        tool_calls = self._get_tool_calls(trajectory)
        return sum(
            1 for step in tool_calls
            if step.get("reversible") is False
        )
