import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useClient } from "@/api/client";

/** The evaluation behind the serving model (small; cached for a minute). */
export function useEvaluation() {
  const client = useClient();
  return useQuery({ queryKey: ["evaluation"], queryFn: ({ signal }) => client.evaluation(signal), staleTime: 60_000 });
}

/** Every saved experiment with its evaluation regime; the serving one is flagged. */
export function useEvaluations() {
  const client = useClient();
  return useQuery({ queryKey: ["evaluations"], queryFn: ({ signal }) => client.evaluations(signal), staleTime: 60_000 });
}

export function useEvaluationById(id: string | null) {
  const client = useClient();
  return useQuery({ queryKey: ["evaluation", id], queryFn: ({ signal }) => client.evaluationById(id!, signal),
    enabled: !!id, staleTime: 60_000, placeholderData: keepPreviousData });
}

export function useResearch(id: string | null) {
  const client = useClient();
  return useQuery({ queryKey: ["research", id], queryFn: ({ signal }) => client.research(id!, signal), enabled: !!id,
    staleTime: 60_000 });
}

/** The models replay sessions actually use, independent of whichever report is being read. */
export function useServing() {
  const client = useClient();
  return useQuery({ queryKey: ["serving"], queryFn: ({ signal }) => client.serving(signal), staleTime: 60_000 });
}

export function useDatasets() {
  const client = useClient();
  return useQuery({ queryKey: ["datasets"], queryFn: ({ signal }) => client.datasets(signal), staleTime: 60_000 });
}
