import { Injectable } from '@angular/core';
import { BehaviorSubject } from 'rxjs';

@Injectable({
  providedIn: 'root',
})
export class LoadMenuStatusService {
  private loadStatus = new BehaviorSubject<boolean>(false);
  loadStatus$ = this.loadStatus.asObservable();

  setLoaded(loaded: boolean) {
    this.loadStatus.next(loaded);
  }
}
