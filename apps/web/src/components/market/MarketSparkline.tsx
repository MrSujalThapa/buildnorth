import type { ChartPoint } from "../../adapters/templateTypes";
import WealthsimpleAreaChart from "./WealthsimpleAreaChart";
import SparsePublicHistory from "../social/SparsePublicHistory";

type Props = {
  history: ChartPoint[];
  withheld?: boolean;
};

export default function MarketSparkline({ history, withheld = false }: Props) {
  if (withheld || history.length === 0) {
    return (
      <div className="market-sparkline is-empty" role="img" aria-label={withheld ? "Forecast withheld" : "No published history"}>
        <span>{withheld ? "Withheld" : "No chart"}</span>
      </div>
    );
  }
  if (history.length <= 2) {
    return (
      <div className="market-sparkline is-sparse">
        <SparsePublicHistory history={history} compact />
      </div>
    );
  }
  return (
    <div className="market-sparkline">
      <WealthsimpleAreaChart data={history} interactive={false} />
    </div>
  );
}
