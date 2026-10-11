import { useEffect, useState } from "react";
import { getConfig, getReplays, getScenarios, getSources } from "../lib/api";
import { readMock } from "../lib/config";
import { MOCK_CONFIG, MOCK_REPLAYS, MOCK_SCENARIOS, MOCK_SOURCES } from "../lib/mock";
import type { ApiConfig, ReplayInfo, ScenarioInfo, ScenariosResponse, SourcesResponse } from "../types/api";

export interface Catalog {
  loading: boolean;
  error: string | null;
  config: ApiConfig | null;
  scenarios: ScenariosResponse | null;
  replays: ReplayInfo[];
  sources: SourcesResponse | null;
  all: ScenarioInfo[];
}

export function useCatalog(): Catalog {
  const [c, setC] = useState<Catalog>({ loading: true, error: null, config: null, scenarios: null, replays: [], sources: null, all: [] });
  useEffect(() => {
    const ac = new AbortController();
    (async () => {
      if (readMock()) {
        setC({ loading: false, error: null, config: MOCK_CONFIG, scenarios: MOCK_SCENARIOS, replays: MOCK_REPLAYS, sources: MOCK_SOURCES, all: MOCK_SCENARIOS.groups.flatMap((g) => g.scenarios) });
        return;
      }
      try {
        const [config, scenarios, replays] = await Promise.all([getConfig(ac.signal), getScenarios(ac.signal), getReplays(ac.signal)]);
        setC((p) => ({ ...p, loading: false, config, scenarios, replays, all: scenarios.groups.flatMap((g) => g.scenarios) }));
        getSources(ac.signal).then((sources) => setC((p) => ({ ...p, sources }))).catch(() => undefined);
      } catch (e) {
        if (ac.signal.aborted) return;
        setC((p) => ({ ...p, loading: false, error: (e as Error).message || "Cannot reach the API" }));
      }
    })();
    return () => ac.abort();
  }, []);
  return c;
}
