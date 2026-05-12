import type { ConsoleMessage, Page, Request } from "@playwright/test";

type ConsoleDiagnostic = {
  kind: "console";
  type: string;
  text: string;
  location: {
    url: string;
    lineNumber: number;
    columnNumber: number;
  };
  timestamp: string;
};

type PageErrorDiagnostic = {
  kind: "pageerror";
  name: string;
  message: string;
  stack?: string;
  timestamp: string;
};

type RequestFailedDiagnostic = {
  kind: "requestfailed";
  method: string;
  url: string;
  failureText?: string;
  timestamp: string;
};

export type BrowserDiagnosticEvent =
  | ConsoleDiagnostic
  | PageErrorDiagnostic
  | RequestFailedDiagnostic;

export type BrowserDiagnostics = {
  dispose: () => void;
  snapshot: () => {
    eventCount: number;
    droppedEventCount: number;
    events: BrowserDiagnosticEvent[];
  };
};

type BrowserDiagnosticsOptions = {
  consoleTypes?: string[];
  maxEvents?: number;
};

export function collectBrowserDiagnostics(
  page: Page,
  options: BrowserDiagnosticsOptions = {},
): BrowserDiagnostics {
  const consoleTypes = new Set(options.consoleTypes ?? ["error", "warning"]);
  const maxEvents = options.maxEvents ?? 200;
  const events: BrowserDiagnosticEvent[] = [];
  let droppedEventCount = 0;

  const addEvent = (event: BrowserDiagnosticEvent): void => {
    if (events.length >= maxEvents) {
      droppedEventCount += 1;
      return;
    }

    events.push(event);
  };

  const onConsole = (message: ConsoleMessage): void => {
    if (!consoleTypes.has(message.type())) {
      return;
    }

    const location = message.location();
    addEvent({
      kind: "console",
      type: message.type(),
      text: message.text(),
      location: {
        url: location.url,
        lineNumber: location.lineNumber,
        columnNumber: location.columnNumber,
      },
      timestamp: new Date().toISOString(),
    });
  };

  const onPageError = (error: Error): void => {
    addEvent({
      kind: "pageerror",
      name: error.name,
      message: error.message,
      stack: error.stack,
      timestamp: new Date().toISOString(),
    });
  };

  const onRequestFailed = (request: Request): void => {
    addEvent({
      kind: "requestfailed",
      method: request.method(),
      url: request.url(),
      failureText: request.failure()?.errorText,
      timestamp: new Date().toISOString(),
    });
  };

  page.on("console", onConsole);
  page.on("pageerror", onPageError);
  page.on("requestfailed", onRequestFailed);

  return {
    dispose: () => {
      page.off("console", onConsole);
      page.off("pageerror", onPageError);
      page.off("requestfailed", onRequestFailed);
    },
    snapshot: () => ({
      eventCount: events.length,
      droppedEventCount,
      events: [...events],
    }),
  };
}
