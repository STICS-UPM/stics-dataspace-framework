import { expect, Page } from "@playwright/test";

import { clickMarked, fillMarked, setInputFilesMarked } from "../../shared/utils/live-marker";
import { materialInput, materialSelect, snackBar } from "../../shared/utils/selectors";

export class AssetCreatePage {
  constructor(private readonly page: Page) {}

  async goto(baseUrl: string): Promise<void> {
    await this.page.goto(`${baseUrl.replace(/\/$/, "")}/assets/create`, {
      waitUntil: "domcontentloaded",
    });
  }

  async expectReady(): Promise<void> {
    await expect(
      this.page.locator("mat-card-title", { hasText: "Create an asset" }),
    ).toBeVisible({ timeout: 30_000 });
  }

  async fillRequiredFields(assetId: string, folderName: string): Promise<void> {
    await fillMarked(materialInput(this.page, "ID"), assetId);
    await fillMarked(materialInput(this.page, "Name"), `QA Asset ${assetId}`);
    await fillMarked(materialInput(this.page, "Version"), "1.0");
    await fillMarked(materialInput(this.page, "Short description"), 
      "Validacion automatica con Playwright para subida de asset",
    );
    await fillMarked(materialInput(this.page, "Keywords"), "qa,playwright,upload");

    await clickMarked(materialSelect(this.page, "Asset type"));
    await clickMarked(this.page.locator("mat-option").filter({ hasText: "Dataset" }).first());

    const editor = this.page.locator(".ck-editor__editable[contenteditable='true']").first();
    await clickMarked(editor);
    await fillMarked(editor, "Descripcion de prueba automatizada para subida de asset");

    await clickMarked(this.page.getByRole("tab", { name: "Storage information" }));
    await expect(
      this.page.getByRole("tabpanel", { name: "Storage information" }),
    ).toBeVisible({ timeout: 15_000 });

    await clickMarked(materialSelect(this.page, "Destination"));
    await clickMarked(this.page.locator("mat-option").filter({ hasText: "InesDataStore" }).first());
    await fillMarked(materialInput(this.page, "Folder"), folderName);
  }

  async uploadFile(filePath: string): Promise<void> {
    await setInputFilesMarked(this.page.locator("input#fileDropRef"), filePath);
  }

  async submit(): Promise<void> {
    const uploadProgress = this.page.getByText(/Uploading file:/i).first();
    if ((await uploadProgress.count()) > 0) {
      await expect(uploadProgress).toBeHidden({ timeout: 120_000 });
    }

    const blockingOverlay = this.page.locator("app-spinner .overlay").first();
    if ((await blockingOverlay.count()) > 0) {
      await expect(blockingOverlay).toBeHidden({ timeout: 15_000 });
    }

    await clickMarked(this.page.getByRole("button", { name: /^Create$/ }));
  }

  async isCreateButtonVisible(): Promise<boolean> {
    return this.page.getByRole("button", { name: /^Create$/ }).isVisible().catch(() => false);
  }

  async waitForSnackBarText(timeoutMs: number): Promise<string | undefined> {
    const container = snackBar(this.page);
    try {
      await container.waitFor({ state: "visible", timeout: timeoutMs });
      const text = (await container.textContent()) ?? "";
      return text.replace(/\s+/g, " ").trim();
    } catch {
      return undefined;
    }
  }
}
