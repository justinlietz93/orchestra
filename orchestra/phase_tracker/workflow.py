from __future__ import annotations

from dataclasses import replace

from .domain import Agent, ProjectStatus, Transition, WorkflowState


RESULTS: dict[Agent, tuple[str, ...]] = {
    Agent.OPERATOR: ("Package produced", "Not produced", "Project complete"),
    Agent.GUARDIAN: ("Pass", "Fail", "Project complete"),
    Agent.AUDITOR: ("Pass", "Fail", "Project complete"),
}

WORKFLOW_POSITIONS = (
    "Operator",
    "Auditor",
    "Auditor revising after Guardian failure",
    "Guardian reviewing Operator",
    "Guardian reviewing Auditor",
    "Project complete",
)


def available_results(state: WorkflowState) -> tuple[str, ...]:
    return RESULTS[state.active_agent]


def describe_position(state: WorkflowState) -> str:
    if state.status == ProjectStatus.COMPLETE:
        return "Project complete"
    if state.active_agent == Agent.AUDITOR and state.auditor_revision:
        return "Auditor revising after Guardian failure"
    if state.active_agent == Agent.GUARDIAN and state.guardian_subject:
        return f"Guardian reviewing {state.guardian_subject.value}"
    return state.active_agent.value


def align_position(state: WorkflowState, position: str) -> WorkflowState:
    if position not in WORKFLOW_POSITIONS:
        raise ValueError(f"Unknown workflow position: {position}")
    if position == "Project complete":
        return replace(
            state,
            status=ProjectStatus.COMPLETE,
            guardian_subject=None,
            auditor_revision=False,
        )
    if position == "Auditor revising after Guardian failure":
        agent = Agent.AUDITOR
        subject = None
        revision = True
    elif position == "Guardian reviewing Operator":
        agent = Agent.GUARDIAN
        subject = Agent.OPERATOR
        revision = False
    elif position == "Guardian reviewing Auditor":
        agent = Agent.GUARDIAN
        subject = Agent.AUDITOR
        revision = False
    else:
        agent = Agent(position)
        subject = None
        revision = False
    return replace(
        state,
        active_agent=agent,
        guardian_subject=subject,
        auditor_revision=revision,
        status=ProjectStatus.IN_PROGRESS,
    )


def advance(state: WorkflowState, result: str) -> Transition:
    if state.status == ProjectStatus.COMPLETE:
        raise ValueError("The project is marked complete")
    if result not in available_results(state):
        raise ValueError(f"{result!r} is not valid for {state.active_agent.value}")

    previous = state.active_agent
    if result == "Project complete":
        next_state = replace(
            state,
            status=ProjectStatus.COMPLETE,
            guardian_subject=None,
            auditor_revision=False,
        )
        return Transition(previous, result, next_state, "Project complete")

    if previous == Agent.OPERATOR:
        if result == "Package produced":
            next_state = replace(
                state,
                active_agent=Agent.GUARDIAN,
                guardian_subject=Agent.OPERATOR,
                auditor_revision=False,
            )
            handoff = "Send the Operator package and response to Guardian"
        else:
            next_state = replace(
                state, guardian_subject=None, auditor_revision=False
            )
            handoff = "Return to Operator and request the missing package"
        return Transition(previous, result, next_state, handoff)

    if previous == Agent.AUDITOR:
        next_state = replace(
            state,
            active_agent=Agent.GUARDIAN,
            guardian_subject=Agent.AUDITOR,
        )
        return Transition(
            previous,
            result,
            next_state,
            "Send the Auditor package and response to Guardian",
        )

    subject = state.guardian_subject
    if subject not in (Agent.OPERATOR, Agent.AUDITOR):
        raise ValueError("Guardian has no Operator or Auditor submission to review")

    if result == "Pass" and subject == Agent.OPERATOR:
        next_agent = Agent.AUDITOR
        handoff = (
            "Send the Guardian ratification, Operator package, and Operator "
            "response to Auditor"
        )
    elif result == "Pass" and subject == Agent.AUDITOR:
        next_agent = Agent.OPERATOR
        handoff = (
            "Send the Guardian ratification, Auditor package, and Auditor "
            "response to Operator"
        )
    elif subject == Agent.OPERATOR:
        next_agent = Agent.OPERATOR
        handoff = "Send the Guardian response to Operator to revise and resubmit"
    else:
        next_agent = Agent.AUDITOR
        handoff = "Send the Guardian response to Auditor to revise and resubmit"

    next_state = replace(
        state,
        active_agent=next_agent,
        guardian_subject=None,
        auditor_revision=(result == "Fail" and subject == Agent.AUDITOR),
    )
    return Transition(previous, result, next_state, handoff)
