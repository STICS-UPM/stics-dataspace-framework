import { Locator } from "@playwright/test";

function isEnabled(): boolean {
  const raw = process.env.PLAYWRIGHT_INTERACTION_MARKERS;
  if (!raw) {
    return false;
  }
  return ["1", "true", "yes", "on"].includes(raw.trim().toLowerCase());
}

function markerDelayMs(): number {
  const raw = process.env.PLAYWRIGHT_INTERACTION_MARKER_DELAY_MS;
  const value = Number(raw ?? "350");
  return Number.isFinite(value) && value >= 0 ? value : 350;
}

async function highlight(locator: Locator): Promise<void> {
  if (!isEnabled()) {
    return;
  }

  let restoreDomMarker: (() => Promise<void>) | undefined;

  try {
    await locator.scrollIntoViewIfNeeded({ timeout: 2_000 });
  } catch {
    // Some targets, such as hidden file inputs, cannot be scrolled into view.
  }

  try {
    restoreDomMarker = await applyDomMarker(locator);
  } catch {
    restoreDomMarker = undefined;
  }

  try {
    await locator.highlight();
  } catch {
    // Playwright's overlay is best-effort; the DOM marker above remains visible in videos.
  }

  const delayMs = markerDelayMs();
  if (delayMs > 0) {
    await locator.page().waitForTimeout(delayMs);
  }

  if (restoreDomMarker) {
    await restoreDomMarker().catch(() => undefined);
  }
}

async function applyDomMarker(locator: Locator): Promise<() => Promise<void>> {
  const markerId = `pionera-marker-${Date.now()}-${Math.random().toString(16).slice(2)}`;

  await locator.evaluate(
    (element, id) => {
      const target = element as HTMLElement | SVGElement;
      const previous = {
        outline: target.style.outline,
        boxShadow: target.style.boxShadow,
        borderRadius: target.style.borderRadius,
        transition: target.style.transition,
        position: target.style.position,
        zIndex: target.style.zIndex,
      };

      target.setAttribute("data-pionera-playwright-marker", id);
      target.setAttribute("data-pionera-playwright-marker-style", JSON.stringify(previous));
      target.style.outline = "4px solid #ff8a00";
      target.style.boxShadow = "0 0 0 6px rgba(255, 138, 0, 0.32), 0 0 24px rgba(255, 138, 0, 0.85)";
      target.style.borderRadius = target.style.borderRadius || "10px";
      target.style.transition = "outline 120ms ease, box-shadow 120ms ease";

      const computedPosition = window.getComputedStyle(target).position;
      if (computedPosition === "static") {
        target.style.position = "relative";
      }
      target.style.zIndex = "2147483646";
    },
    markerId,
  );

  return async () => {
    await locator.evaluate((element, id) => {
      const target = element as HTMLElement | SVGElement;
      if (target.getAttribute("data-pionera-playwright-marker") !== id) {
        return;
      }

      const rawPrevious = target.getAttribute("data-pionera-playwright-marker-style");
      const previous = rawPrevious ? JSON.parse(rawPrevious) : {};
      target.style.outline = previous.outline ?? "";
      target.style.boxShadow = previous.boxShadow ?? "";
      target.style.borderRadius = previous.borderRadius ?? "";
      target.style.transition = previous.transition ?? "";
      target.style.position = previous.position ?? "";
      target.style.zIndex = previous.zIndex ?? "";
      target.removeAttribute("data-pionera-playwright-marker");
      target.removeAttribute("data-pionera-playwright-marker-style");
    }, markerId);
  };
}

export async function clickMarked(locator: Locator, options?: Parameters<Locator["click"]>[0]): Promise<void> {
  await highlight(locator);
  await locator.click(options);
}

export async function fillMarked(locator: Locator, value: string, options?: Parameters<Locator["fill"]>[1]): Promise<void> {
  await highlight(locator);
  await locator.fill(value, options);
}

export async function pressMarked(locator: Locator, key: string, options?: Parameters<Locator["press"]>[1]): Promise<void> {
  await highlight(locator);
  await locator.press(key, options);
}

export async function selectOptionMarked(
  locator: Locator,
  values: Parameters<Locator["selectOption"]>[0],
  options?: Parameters<Locator["selectOption"]>[1],
): Promise<void> {
  await highlight(locator);
  await locator.selectOption(values, options);
}

export async function setInputFilesMarked(
  locator: Locator,
  files: Parameters<Locator["setInputFiles"]>[0],
  options?: Parameters<Locator["setInputFiles"]>[1],
): Promise<void> {
  await highlight(locator);
  await locator.setInputFiles(files, options);
}

export async function checkMarked(locator: Locator, options?: Parameters<Locator["check"]>[0]): Promise<void> {
  await highlight(locator);
  await locator.check(options);
}
