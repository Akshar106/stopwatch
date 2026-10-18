import { QueryClient } from "@tanstack/react-query";
import { ApiError } from "../lib/apiClient";
import { DataError } from "../lib/dataClient";

function isClientError(err: unknown): boolean {
  const status = err instanceof ApiError || err instanceof DataError ? err.status : 0;
  return status >= 400 && status < 500;
}

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 5 * 60_000,
        retry: (failureCount, err) => !isClientError(err) && failureCount < 2,
        refetchOnWindowFocus: false,
      },
      mutations: { retry: false },
    },
  });
}
