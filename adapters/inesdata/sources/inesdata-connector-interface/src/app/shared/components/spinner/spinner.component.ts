// spinner.component.ts
import { Component } from '@angular/core';
import { Observable } from 'rxjs';
import { LoadingService } from '../../services/loading.service';

@Component({
  selector: 'app-spinner',
  template: `
    <div class="overlay" *ngIf="isLoading$ | async">
      <div class="spinner"></div>
      <div class="message" *ngIf="message$ | async as message">{{ message }}</div>
    </div>
  `,
  styleUrls: ['./spinner.component.scss']
})
export class SpinnerComponent {
  isLoading$: Observable<boolean>;
  message$: Observable<string>;

  constructor(private loadingService: LoadingService) {
    this.isLoading$ = this.loadingService.isLoading$;
    this.message$ = this.loadingService.message$;
  }
}
