import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { api, type CourseGradeComponent, type CourseGradeResult } from "../../api/client";
import { courseStandingSummary, formatCourseScore } from "../../adapters/courseGrade";
import "./course-standing.css";

const EMPTY_ROW = (): CourseGradeComponent => ({ label: "", score: null, weight: 0, known: false });

export default function CourseStandingPanel() {
  const [rows, setRows] = useState<CourseGradeComponent[]>([EMPTY_ROW(), EMPTY_ROW()]);
  const [target, setTarget] = useState("");
  const [scenarios, setScenarios] = useState(["", ""]);
  const mutation = useMutation({
    mutationFn: () =>
      api.courseGrade({
        components: rows,
        target: target.trim() === "" ? null : Number(target),
        scenarios: scenarios.filter((value) => value.trim() !== "").map(Number),
      }),
  });
  const result: CourseGradeResult | undefined = mutation.data;
  const canCompute = rows.length > 0 && rows.every((row) => row.label.trim() && row.weight > 0);
  const update = (index: number, patch: Partial<CourseGradeComponent>) => {
    setRows((current) => current.map((row, rowIndex) => (rowIndex === index ? { ...row, ...patch } : row)));
  };

  return (
    <section className="course-standing" aria-labelledby="course-standing-title">
      <div className="panel-head tight">
        <div>
          <h2 id="course-standing-title">Course standing</h2>
        </div>
        <span className="meta">Not a forecast. Hypothetical remaining scores are not stored as evidence.</span>
      </div>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          mutation.mutate();
        }}
      >
        <table>
          <thead>
            <tr>
              <th scope="col">Component</th>
              <th scope="col">Weight</th>
              <th scope="col">Score</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={index}>
                <td>
                  <input
                    aria-label={`Component ${index + 1} name`}
                    value={row.label}
                    onChange={(event) => update(index, { label: event.target.value })}
                  />
                </td>
                <td>
                  <input
                    aria-label={`${row.label || `Component ${index + 1}`} weight`}
                    type="number"
                    min={0}
                    max={100}
                    step="any"
                    value={row.weight || ""}
                    onChange={(event) => update(index, { weight: Number(event.target.value) })}
                  />
                </td>
                <td>
                  <input
                    aria-label={`${row.label || `Component ${index + 1}`} score`}
                    type="number"
                    min={0}
                    max={100}
                    step="any"
                    placeholder="unknown"
                    value={row.score ?? ""}
                    onChange={(event) => {
                      const raw = event.target.value;
                      update(index, { score: raw === "" ? null : Number(raw), known: raw !== "" });
                    }}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="course-standing-actions">
          <label>
            Target
            <input
              aria-label="Target course average"
              type="number"
              min={0}
              max={100}
              value={target}
              onChange={(event) => setTarget(event.target.value)}
            />
          </label>
          <button type="button" onClick={() => setRows((current) => [...current, EMPTY_ROW()].slice(0, 8))}>
            Add component
          </button>
          <button type="submit" disabled={mutation.isPending || !canCompute}>
            {mutation.isPending ? "Computing…" : "Compute standing"}
          </button>
        </div>
        <div className="course-standing-scenarios" aria-label="Hypothetical remaining scores">
          {scenarios.map((value, index) => (
            <label key={index}>
              Scenario {index === 0 ? "A" : "B"}
              <input
                aria-label={`Scenario ${index === 0 ? "A" : "B"} remaining score`}
                type="number" min={0} max={100} step="any" placeholder="Optional"
                value={value}
                onChange={(event) => setScenarios((current) => current.map((item, itemIndex) => itemIndex === index ? event.target.value : item))}
              />
            </label>
          ))}
        </div>
      </form>
      {mutation.isError ? (
        <p role="alert">{mutation.error instanceof Error ? mutation.error.message : "Could not compute standing."}</p>
      ) : null}
      {result ? (
        <div className="course-standing-result">
          <p>{courseStandingSummary(result)}</p>
          {result.scenarios.length ? (
            <ul aria-label="Hypothetical remaining scores">
              {result.scenarios.map((scenario) => (
                <li key={scenario.label}>
                  Remaining {formatCourseScore(scenario.remaining_score)} → {formatCourseScore(scenario.average)}
                  {scenario.meets_target == null ? "" : scenario.meets_target ? " (meets target)" : " (below target)"}
                </li>
              ))}
            </ul>
          ) : null}
          <p className="quiet-copy">{result.message}</p>
        </div>
      ) : null}
    </section>
  );
}
