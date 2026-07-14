import { apiRequest } from "@/lib/api";
import type {
  ArcadeGameId,
  ArcadeHighScore,
} from "@/lib/arcade-high-score-state";

type ArcadeHighScoreListResponse = {
  items: ArcadeHighScore[];
};

export type ArcadeHighScoreSubmitResponse = ArcadeHighScore & {
  is_new_high_score: boolean;
};

export async function listArcadeHighScores(options: { signal?: AbortSignal } = {}) {
  const response = await apiRequest<ArcadeHighScoreListResponse>(
    "/arcade/high-scores",
    {
      bypassCache: true,
      method: "GET",
      signal: options.signal,
    },
  );

  return response.items;
}

export function submitArcadeHighScore(
  gameId: ArcadeGameId,
  score: number,
  options: { keepalive?: boolean; signal?: AbortSignal } = {},
) {
  return apiRequest<ArcadeHighScoreSubmitResponse>(
    `/arcade/high-scores/${gameId}`,
    {
      body: { score },
      method: "POST",
      keepalive: options.keepalive,
      retryLimit: 0,
      signal: options.signal,
    },
  );
}
