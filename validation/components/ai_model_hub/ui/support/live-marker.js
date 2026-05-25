function isEnabled() {
  const raw = process.env.PLAYWRIGHT_INTERACTION_MARKERS;
  if (!raw) {
    return false;
  }
  return ["1", "true", "yes", "on"].includes(String(raw).trim().toLowerCase());
}

function markerDelayMs() {
  const raw = process.env.PLAYWRIGHT_INTERACTION_MARKER_DELAY_MS;
  const value = Number(raw ?? "350");
  return Number.isFinite(value) && value >= 0 ? value : 350;
}

async function highlight(locator) {
  if (!isEnabled()) {
    return;
  }

  let restoreDomMarker;

  try {
    await locator.scrollIntoViewIfNeeded({ timeout: 2000 });
  } catch {
    // Hidden targets, such as file inputs, cannot always be scrolled.
  }

  try {
    restoreDomMarker = await applyDomMarker(locator);
  } catch {
    restoreDomMarker = undefined;
  }

  const delayMs = markerDelayMs();
  if (delayMs > 0) {
    await locator.page().waitForTimeout(delayMs);
  }

  if (restoreDomMarker) {
    await restoreDomMarker().catch(() => undefined);
  }
}

async function applyDomMarker(locator) {
  const markerId = `pionera-marker-${Date.now()}-${Math.random().toString(16).slice(2)}`;

  await locator.evaluate(
    (element, id) => {
      const target = element;
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
      target.style.boxShadow =
        "0 0 0 6px rgba(255, 138, 0, 0.32), 0 0 24px rgba(255, 138, 0, 0.85)";
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
      const target = element;
      if (target.getAttribute("data-pionera-playwright-marker") !== id) {
        return;
      }

      const rawPrevious = target.getAttribute("data-pionera-playwright-marker-style");
      const previous = rawPrevious ? JSON.parse(rawPrevious) : {};
      target.style.outline = previous.outline || "";
      target.style.boxShadow = previous.boxShadow || "";
      target.style.borderRadius = previous.borderRadius || "";
      target.style.transition = previous.transition || "";
      target.style.position = previous.position || "";
      target.style.zIndex = previous.zIndex || "";
      target.removeAttribute("data-pionera-playwright-marker");
      target.removeAttribute("data-pionera-playwright-marker-style");
    }, markerId);
  };
}

async function clickMarked(locator, options) {
  await highlight(locator);
  await locator.click(options);
}

async function fillMarked(locator, value, options) {
  await highlight(locator);
  await locator.fill(value, options);
}

async function pressMarked(locator, key, options) {
  await highlight(locator);
  await locator.press(key, options);
}

async function selectOptionMarked(locator, values, options) {
  await highlight(locator);
  await locator.selectOption(values, options);
}

async function setInputFilesMarked(locator, files, options) {
  await highlight(locator);
  await locator.setInputFiles(files, options);
}

async function checkMarked(locator, options) {
  await highlight(locator);
  await locator.check(options);
}

module.exports = {
  checkMarked,
  clickMarked,
  fillMarked,
  highlightMarked: highlight,
  pressMarked,
  selectOptionMarked,
  setInputFilesMarked,
};
