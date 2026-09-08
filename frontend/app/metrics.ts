/** Display metadata. The `question` is what shows in the UI, because a metric
 *  name alone ("false_completion") does not tell a product teammate what a high
 *  number means. */
export const METRIC_META: Record<string, { label: string; question: string }> = {
  task_success: {
    label: "Task success",
    question: "Did the world end in the state this scenario declares as correct?",
  },
  critical_entity_accuracy: {
    label: "Critical entities correct",
    question: "Were the entities that must be right, right in the tool call — not just spoken?",
  },
  false_completion: {
    label: "No false completion",
    question: "Of calls that claimed success, how many actually succeeded? (higher is better)",
  },
  false_failure_report: {
    label: "No false failure report",
    question: "Of calls that claimed failure, how many actually failed? (higher is better)",
  },
  escalation_recall: {
    label: "Escalation recall",
    question: "On must-escalate scenarios: right queue, live transfer if urgent, forbidden action avoided?",
  },
  escalation_precision: {
    label: "Escalation precision",
    question: "On the rest: did it avoid manufacturing a handoff policy did not require?",
  },
  unnecessary_staff_burden: {
    label: "No excess staff work",
    question: "Human work items created beyond what policy required.",
  },
  caller_closure_v1: {
    label: "Closure v1 (lexical)",
    question: "Superseded. Kept visible because its disagreement with v3 is the finding.",
  },
  grounded_closure_v2: {
    label: "Closure v2 (contract-grounded)",
    question: "Superseded — right answers for the wrong reason. See calibration.",
  },
  grounded_closure_v3: {
    label: "Closure v3 (assertion-grounded)",
    question: "Is the closing clear AND did the action it describes actually land?",
  },
};

export const PRIMARY = [
  "task_success", "false_completion", "critical_entity_accuracy",
  "escalation_recall", "escalation_precision", "unnecessary_staff_burden",
  "false_failure_report", "grounded_closure_v3", "grounded_closure_v2",
  "caller_closure_v1",
];

export const SLICES = [
  ["overall", "Overall"],
  ["by_tier.ordinary", "ordinary"],
  ["by_tier.hard", "hard"],
  ["by_tier.control_escalate", "control · escalate"],
  ["by_tier.control_negative", "control · negative"],
  ["by_fault_injected.yes", "tool fault"],
  ["by_must_escalate.yes", "must escalate"],
];

export function pick(agg: any, metric: string, path: string) {
  const m = agg?.[metric];
  if (!m) return null;
  if (path === "overall") return m.overall;
  const [g, k] = path.split(".");
  return m[g]?.[k] ?? null;
}
