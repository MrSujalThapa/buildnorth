import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { api, type WorkflowSnapshot } from "../../api/client";
import { AgentProgress } from "../agents/AgentProgress";

type Props = {
  goalId: string;
  initialSnapshot?: WorkflowSnapshot | null;
  onSnapshotChange?: (snapshot: WorkflowSnapshot | null) => void;
  embedded?: boolean;
};

export function EvidenceWorkflow({ goalId, initialSnapshot = null, onSnapshotChange, embedded = false }: Props) {
  const location = useLocation();
  const queryClient = useQueryClient();
  const [snapshot, setSnapshot] = useState<WorkflowSnapshot | null>(initialSnapshot);
  const [evidenceText, setEvidenceText] = useState("");
  const [answers, setAnswers] = useState<Record<string, string>>({});

  useEffect(() => {
    if (location.hash === "#evidence") {
      document.getElementById("evidence")?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [location.hash]);

  const addEvidence = useMutation({
    mutationFn: () => api.addEvidence(goalId, evidenceText),
    onSuccess: (data) => {
      setSnapshot(data);
      onSnapshotChange?.(data);
      if (data.status === "completed" || data.status === "limited" || data.status === "withheld") {
        void queryClient.invalidateQueries({ queryKey: ["evidence", goalId] });
        void queryClient.invalidateQueries({ queryKey: ["goal", goalId] });
        void queryClient.invalidateQueries({ queryKey: ["market-history", goalId] });
        void queryClient.invalidateQueries({ queryKey: ["what-if-baseline", goalId] });
        setEvidenceText("");
      }
    },
  });

  const resume = useMutation({
    mutationFn: (body: { answers?: Record<string, string>; confirmed?: boolean; cancelled?: boolean }) => {
      if (!snapshot) throw new Error("missing thread");
      return api.resumeThread(snapshot.thread_id, body);
    },
    onSuccess: (data) => {
      setSnapshot(data);
      onSnapshotChange?.(data);
      setAnswers({});
      if (data.status === "completed" || data.status === "limited" || data.status === "withheld") {
        void queryClient.invalidateQueries({ queryKey: ["evidence", goalId] });
        void queryClient.invalidateQueries({ queryKey: ["goal", goalId] });
        void queryClient.invalidateQueries({ queryKey: ["market-history", goalId] });
        void queryClient.invalidateQueries({ queryKey: ["what-if-baseline", goalId] });
      }
    },
  });

  const interrupt = snapshot?.interrupt;

  const Wrapper = embedded ? "div" : "section";

  return (
    <Wrapper className={embedded ? "composer-form" : "market-shell evidence-workflow"} aria-labelledby={embedded ? undefined : "evidence-workflow-title"}>
      {!embedded ? (
        <h2 id="evidence-workflow-title" className="visually-hidden">
          Evidence workflow
        </h2>
      ) : null}
      <AgentProgress snapshot={snapshot} />
      {interrupt?.type === "confirm_evidence" ? (
        <form
          id="evidence"
          className="composer-form"
          onSubmit={(event) => {
            event.preventDefault();
            resume.mutate({ confirmed: true, answers });
          }}
        >
          <h2>Recognized evidence</h2>
          <ul className="evidence-list">
            {(interrupt.proposal?.events as { summary: string }[] | undefined)?.map((event) => (
              <li key={event.summary}>{event.summary}</li>
            ))}
          </ul>
          {interrupt.questions.map((question) => (
            <label key={question.id} htmlFor={question.id}>
              {question.question}
              <input
                id={question.id}
                value={answers[question.id] ?? ""}
                onChange={(event) => setAnswers((current) => ({ ...current, [question.id]: event.target.value }))}
              />
            </label>
          ))}
          <div className="composer-actions">
            <button type="submit" disabled={resume.isPending}>
              {resume.isPending ? "Committing…" : "Commit evidence"}
            </button>
            <button type="button" className="secondary" onClick={() => resume.mutate({ cancelled: true })}>
              Cancel
            </button>
          </div>
        </form>
      ) : (
        <form
          id="evidence"
          className="composer-form"
          onSubmit={(event) => {
            event.preventDefault();
            if (evidenceText.trim()) addEvidence.mutate();
          }}
        >
          <label htmlFor="evidence-input">Add evidence</label>
          <textarea
            id="evidence-input"
            rows={4}
            value={evidenceText}
            onChange={(event) => setEvidenceText(event.target.value)}
            placeholder="I failed a Meta phone screen today but studied LeetCode for 3 hours."
          />
          <button type="submit" disabled={addEvidence.isPending || !evidenceText.trim()}>
            {addEvidence.isPending ? "Reading evidence…" : "Submit evidence"}
          </button>
        </form>
      )}
    </Wrapper>
  );
}
