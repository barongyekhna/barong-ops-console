import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  ARCADE_GAME_IDS,
  mergeArcadeHighScores,
  optimisticArcadeHighScore,
  reconcileArcadeHighScore,
} from "../../frontend/src/lib/arcade-high-score-state.ts";
import {
  getBackendApiPath,
  isAllowedBackendProxyPath,
} from "../../frontend/src/app/api/backend/[...path]/route.ts";

function highScore(gameId, score, username, updatedAt = null) {
  return {
    game_id: gameId,
    score,
    username,
    updated_at: updatedAt,
  };
}

test("lower and tied optimistic scores do not replace the current record", () => {
  const current = highScore("snake", 100, "alice", "2026-07-14T10:00:00Z");

  assert.strictEqual(
    optimisticArcadeHighScore(current, {
      gameId: "snake",
      score: 90,
      username: "bob",
    }),
    current,
  );
  assert.strictEqual(
    optimisticArcadeHighScore(current, {
      gameId: "snake",
      score: 100,
      username: "bob",
    }),
    current,
  );
});

test("a strictly higher optimistic score updates score and username together", () => {
  const current = highScore("snake", 100, "alice", "2026-07-14T10:00:00Z");

  assert.deepEqual(
    optimisticArcadeHighScore(current, {
      gameId: "snake",
      score: 110,
      username: "bob",
    }),
    highScore("snake", 110, "bob"),
  );
});

test("an authoritative tie can correct the record holder", () => {
  const optimistic = highScore("snake", 110, "local-player");
  const authoritative = highScore(
    "snake",
    110,
    "server-winner",
    "2026-07-14T10:01:00Z",
  );

  assert.strictEqual(
    reconcileArcadeHighScore(optimistic, authoritative),
    authoritative,
  );
});

test("a stale lower authoritative response cannot overwrite a newer optimistic score", () => {
  const newerOptimistic = highScore("snake", 140, "bob");
  const staleAuthoritative = highScore(
    "snake",
    120,
    "alice",
    "2026-07-14T09:59:00Z",
  );

  assert.strictEqual(
    reconcileArcadeHighScore(newerOptimistic, staleAuthoritative),
    newerOptimistic,
  );
});

test("high-score merges keep records isolated by game", () => {
  const snake = highScore("snake", 100, "alice");
  const tetris = highScore("tetris", 800, "carol");
  const nextSnake = highScore(
    "snake",
    120,
    "bob",
    "2026-07-14T10:02:00Z",
  );

  const merged = mergeArcadeHighScores(
    { snake, tetris },
    [nextSnake],
  );

  assert.strictEqual(merged.snake, nextSnake);
  assert.strictEqual(merged.tetris, tetris);
  assert.deepEqual(Object.keys(merged).sort(), ["snake", "tetris"]);
});

test("the arcade console wires authenticated live scores to named history UI", () => {
  const consoleSource = readFileSync(
    "frontend/src/components/console-arcade.tsx",
    "utf8",
  );

  assert.match(consoleSource, /import \{ useAuth \}/);
  assert.match(consoleSource, /const \{ user \} = useAuth\(\)/);
  assert.match(consoleSource, /const username = user\.username/);
  assert.match(consoleSource, /userId: user\.id/);
  assert.match(consoleSource, /历史最高/);
  assert.match(consoleSource, /currentHighScore\.score/);
  assert.match(consoleSource, /currentHighScore\.username/);
  assert.match(consoleSource, /onScoreChange=\{handleActiveScoreChange\}/);
  assert.match(consoleSource, /handleScoreChange\(active, score\)/);
  assert.match(consoleSource, /identityGenerationRef/);
  assert.match(consoleSource, /pending\.identityKey !== currentIdentityKeyRef\.current/);
  assert.match(consoleSource, /inFlightScoresRef\.current = \{\}/);
  assert.match(consoleSource, /isApiAbortError\(error\)/);
  assert.match(consoleSource, /error instanceof ApiTimeoutError/);
  assert.match(consoleSource, /keepalive: true/);
  assert.match(consoleSource, /confirmedHighScoresRef/);
  assert.match(consoleSource, /entry\?\.controller\.abort\(\)/);
});

test("all twelve arcade games report live scores and Mines labels cleared cells", () => {
  const componentPaths = {
    "2048": "frontend/src/components/arcade-2048.tsx",
    asteroids: "frontend/src/components/arcade-asteroids.tsx",
    breakout: "frontend/src/components/arcade-breakout.tsx",
    flappy: "frontend/src/components/arcade-flappy.tsx",
    match3: "frontend/src/components/arcade-match3.tsx",
    mines: "frontend/src/components/arcade-mines.tsx",
    pong: "frontend/src/components/arcade-pong.tsx",
    runner: "frontend/src/components/arcade-runner.tsx",
    shmup: "frontend/src/components/arcade-shmup.tsx",
    snake: "frontend/src/components/arcade-snake.tsx",
    tank: "frontend/src/components/arcade-tank.tsx",
    tetris: "frontend/src/components/arcade-tetris.tsx",
  };

  assert.deepEqual(
    Object.keys(componentPaths).sort(),
    [...ARCADE_GAME_IDS].sort(),
  );

  for (const [gameId, componentPath] of Object.entries(componentPaths)) {
    const source = readFileSync(componentPath, "utf8");
    assert.match(source, /onScoreChange/, `${gameId} must accept onScoreChange`);
    assert.match(
      source,
      /onScoreChange\?\.\(/,
      `${gameId} must publish its live score`,
    );
  }

  assert.match(
    readFileSync(componentPaths.mines, "utf8"),
    /已排除/,
  );
});

test("the backend proxy allows only exact arcade high-score routes", () => {
  const listPath = ["arcade", "high-scores"];

  assert.equal(
    getBackendApiPath("GET", listPath),
    "/api/app/arcade/high-scores",
  );
  assert.equal(isAllowedBackendProxyPath("GET", listPath), true);

  for (const gameId of ARCADE_GAME_IDS) {
    const submitPath = ["arcade", "high-scores", gameId];
    assert.equal(
      getBackendApiPath("POST", submitPath),
      `/api/app/arcade/high-scores/${gameId}`,
    );
    assert.equal(isAllowedBackendProxyPath("POST", submitPath), true);
  }

  const rejected = [
    ["POST", ["arcade", "high-scores", "not-a-game"]],
    ["POST", ["arcade", "high-scores"]],
    ["PUT", ["arcade", "high-scores", "snake"]],
    ["GET", ["arcade", "high-scores", "snake"]],
    ["POST", ["arcade", "high-scores", "snake", "extra"]],
    ["GET", ["arcade", "high-scores", "extra"]],
  ];

  for (const [method, path] of rejected) {
    assert.equal(getBackendApiPath(method, path), null);
    assert.equal(isAllowedBackendProxyPath(method, path), false);
  }
});
