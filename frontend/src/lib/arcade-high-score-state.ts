export const ARCADE_GAME_IDS = [
  "shmup",
  "snake",
  "tetris",
  "tank",
  "asteroids",
  "breakout",
  "2048",
  "runner",
  "match3",
  "mines",
  "flappy",
  "pong",
] as const;

export type ArcadeGameId = (typeof ARCADE_GAME_IDS)[number];

export type ArcadeHighScore = {
  game_id: ArcadeGameId;
  score: number;
  username: string;
  updated_at: string | null;
};

export type ArcadeHighScoreMap = Partial<
  Record<ArcadeGameId, ArcadeHighScore>
>;

type HighScoreCandidate = {
  gameId: ArcadeGameId;
  score: number;
  username: string;
};

export function optimisticArcadeHighScore(
  current: ArcadeHighScore | undefined,
  candidate: HighScoreCandidate,
): ArcadeHighScore | undefined {
  const score = Math.floor(candidate.score);
  const username = candidate.username.trim();

  if (
    !Number.isSafeInteger(score) ||
    score <= 0 ||
    !username ||
    (current !== undefined && score <= current.score)
  ) {
    return current;
  }

  return {
    game_id: candidate.gameId,
    score,
    username,
    updated_at: null,
  };
}

export function reconcileArcadeHighScore(
  current: ArcadeHighScore | undefined,
  authoritative: ArcadeHighScore,
): ArcadeHighScore {
  if (current === undefined || authoritative.score >= current.score) {
    return authoritative;
  }

  return current;
}

export function mergeArcadeHighScores(
  current: ArcadeHighScoreMap,
  incoming: readonly ArcadeHighScore[],
): ArcadeHighScoreMap {
  const next = { ...current };

  for (const highScore of incoming) {
    next[highScore.game_id] = reconcileArcadeHighScore(
      next[highScore.game_id],
      highScore,
    );
  }

  return next;
}
