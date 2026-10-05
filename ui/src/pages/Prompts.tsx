import { Button, InputField } from "@actioneer/ads";
import { useState } from "react";
import { comparePrompts, type PromptComparison } from "../api";
import { ms } from "../format";

function rate(value: number | null): string {
  return value == null ? "—" : `${Math.round(value * 100)}%`;
}

function money(value: number | null): string {
  return value == null ? "—" : value.toFixed(3);
}

export default function Prompts() {
  const [campaignId, setCampaignId] = useState("");
  const [rows, setRows] = useState<PromptComparison[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setRows(await comparePrompts(campaignId.trim() || undefined));
    } catch (err) {
      setRows(null);
      setError(err instanceof Error ? err.message : "Could not load prompt versions");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="page">
      <div className="list">
        <div className="head">
          <h1>Prompts</h1>
          <div className="sub">
            Each hash is one prompt version: the campaign script without that
            customer's name or the callback clock. Rates are among calls a person answered.
          </div>
        </div>
        <form
          className="row"
          onSubmit={(event) => {
            event.preventDefault();
            void load();
          }}
        >
          <InputField
            label="Campaign"
            value={campaignId}
            onChange={(event) => setCampaignId(event.target.value)}
            placeholder="Campaign id"
          />
          <Button type="submit" disabled={loading}>
            {loading ? "Loading" : "Compare"}
          </Button>
        </form>
        {error && <p className="error">{error}</p>}
        {rows && rows.length === 0 && <p className="sub">No calls for that campaign yet.</p>}
        {rows && rows.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Prompt</th>
                <th>Calls</th>
                <th>Answered</th>
                <th>Objective</th>
                <th>Script</th>
                <th>Guardrails</th>
                <th>Voice to voice</th>
                <th>Avg cost</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.sha256 ?? "unversioned"}>
                  <td>
                    <div>{row.sha256 ? row.sha256.slice(0, 12) : "No version"}</div>
                    <div className="sub">{row.preview || "Prompt text was not registered."}</div>
                  </td>
                  <td>{row.calls}</td>
                  <td>{row.connected}</td>
                  <td>{rate(row.objective_rate)}</td>
                  <td>{rate(row.adherence_rate)}</td>
                  <td>{rate(row.guardrail_rate)}</td>
                  <td>{ms(row.v2v_p50_ms)}</td>
                  <td>{money(row.avg_cost)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
