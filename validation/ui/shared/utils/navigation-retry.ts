import type { Page, Response } from "@playwright/test";

type RetryingPage = Page & {
  __pioneraNavigationRetry?: {
    goto: Page["goto"];
    reload: Page["reload"];
  };
};

type RetrySettings = {
  attempts: number;
  delayMs: number;
  statuses: Set<number>;
};

function parseBool(value: string | undefined, fallback: boolean): boolean {
  if (value === undefined || value.trim() === "") {
    return fallback;
  }
  return ["1", "true", "yes", "on"].includes(value.trim().toLowerCase());
}

function parsePositiveInt(value: string | undefined, fallback: number): number {
  const parsed = Number.parseInt(String(value || ""), 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function parseStatusSet(value: string | undefined): Set<number> {
  const entries = String(value || "502,503,504")
    .split(",")
    .map((entry) => Number.parseInt(entry.trim(), 10))
    .filter((entry) => Number.isFinite(entry) && entry >= 400 && entry <= 599);
  return new Set(entries.length > 0 ? entries : [502, 503, 504]);
}

function retrySettings(): RetrySettings {
  return {
    attempts: parsePositiveInt(process.env.PLAYWRIGHT_NAVIGATION_RETRY_ATTEMPTS, 4),
    delayMs: parsePositiveInt(process.env.PLAYWRIGHT_NAVIGATION_RETRY_DELAY_MS, 750),
    statuses: parseStatusSet(process.env.PLAYWRIGHT_NAVIGATION_RETRY_STATUSES),
  };
}

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function transientNavigationError(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error || "");
  return /ERR_CONNECTION_RESET|ERR_CONNECTION_REFUSED|ERR_EMPTY_RESPONSE|ERR_SOCKET_NOT_CONNECTED|ERR_TIMED_OUT|Timeout .* exceeded/i.test(
    message,
  );
}

async function retryNavigation(
  label: string,
  operation: () => Promise<Response | null>,
  settings: RetrySettings,
): Promise<Response | null> {
  let lastError: unknown;

  for (let attempt = 1; attempt <= settings.attempts; attempt += 1) {
    try {
      const response = await operation();
      const status = response?.status();
      if (!status || !settings.statuses.has(status) || attempt === settings.attempts) {
        return response;
      }

      console.warn(
        `[navigation-retry] ${label} returned HTTP ${status}; retrying ${attempt}/${settings.attempts - 1}`,
      );
    } catch (error) {
      lastError = error;
      if (!transientNavigationError(error) || attempt === settings.attempts) {
        throw error;
      }
      console.warn(
        `[navigation-retry] ${label} failed with a transient navigation error; retrying ${attempt}/${settings.attempts - 1}`,
      );
    }

    await wait(settings.delayMs * attempt);
  }

  throw lastError instanceof Error ? lastError : new Error(String(lastError || "navigation failed"));
}

export function installTransientNavigationRetry(page: Page): () => void {
  if (!parseBool(process.env.PLAYWRIGHT_NAVIGATION_RETRY_ENABLED, true)) {
    return () => {};
  }

  const retryingPage = page as RetryingPage;
  if (retryingPage.__pioneraNavigationRetry) {
    return () => {};
  }

  const originalGoto = page.goto.bind(page);
  const originalReload = page.reload.bind(page);
  const settings = retrySettings();

  retryingPage.__pioneraNavigationRetry = {
    goto: page.goto,
    reload: page.reload,
  };

  page.goto = (async (url, options) =>
    retryNavigation(`goto ${String(url)}`, () => originalGoto(url, options), settings)) as Page["goto"];

  page.reload = (async (options) =>
    retryNavigation(`reload ${page.url() || "<current page>"}`, () => originalReload(options), settings)) as Page["reload"];

  return () => {
    const installed = retryingPage.__pioneraNavigationRetry;
    if (!installed) {
      return;
    }
    page.goto = installed.goto;
    page.reload = installed.reload;
    delete retryingPage.__pioneraNavigationRetry;
  };
}
