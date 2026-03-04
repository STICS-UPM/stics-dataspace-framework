import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ModelExecutionService, ExecutableAsset } from '../../shared/services/model-execution.service';

@Component({
  selector: 'app-model-execution',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './model-execution.component.html',
  styleUrl: './model-execution.component.scss'
})
export class ModelExecutionComponent implements OnInit {
  private readonly executionService = inject(ModelExecutionService);

  loading = false;
  executing = false;
  errorMessage = '';

  executableAssets: ExecutableAsset[] = [];
  selectedAsset: ExecutableAsset | null = null;

  inputJson = JSON.stringify({ inputs: 'Hello from Pionera' }, null, 2);
  outputJson = '';

  ngOnInit(): void {
    this.loadExecutableAssets();
  }

  loadExecutableAssets(): void {
    this.loading = true;
    this.executionService.getExecutableAssets().subscribe({
      next: (assets) => {
        this.executableAssets = assets;
        this.loading = false;
      },
      error: (err) => {
        console.error('[Inference UI] Failed to load executable assets:', err);
        this.errorMessage = 'Failed to load executable assets';
        this.loading = false;
      }
    });
  }

  onSelectAsset(assetId: string): void {
    this.selectedAsset = this.executableAssets.find(a => a.id === assetId) || null;
    this.outputJson = '';
  }

  execute(): void {
    this.errorMessage = '';
    this.outputJson = '';

    if (!this.selectedAsset) {
      this.errorMessage = 'Select an executable asset first';
      return;
    }

    let payload: any;
    try {
      payload = JSON.parse(this.inputJson);
    } catch {
      this.errorMessage = 'Invalid JSON input';
      return;
    }

    this.executing = true;
    this.executionService.executeModel({
      assetId: this.selectedAsset.id,
      payload,
      path: this.selectedAsset.execution_path
    }).subscribe({
      next: (resp) => {
        this.outputJson = JSON.stringify(resp.output ?? resp, null, 2);
        this.executing = false;
      },
      error: (err) => {
        console.error('[Inference UI] Execution error:', err);
        this.errorMessage = err?.error?.message || 'Execution failed';
        this.executing = false;
      }
    });
  }
}
