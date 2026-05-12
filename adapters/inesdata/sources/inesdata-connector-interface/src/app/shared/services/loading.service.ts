// loading.service.ts
import { Injectable } from '@angular/core';
import { BehaviorSubject } from 'rxjs';

@Injectable({
  providedIn: 'root'
})
export class LoadingService {
  private loadingSubject = new BehaviorSubject<boolean>(false);
  private messageSubject = new BehaviorSubject<string>(''); // Nueva propiedad para manejar el mensaje
  isLoading$ = this.loadingSubject.asObservable();
  message$ = this.messageSubject.asObservable(); // Observable del mensaje

  showLoading(message: string = ''): void {
    this.loadingSubject.next(true);
    this.messageSubject.next(message); // Actualizar el mensaje
  }

  hideLoading(): void {
    this.loadingSubject.next(false);
    this.messageSubject.next(''); // Limpiar el mensaje al ocultar el spinner
  }

  updateMessage(message: string): void {
    this.messageSubject.next(message); // Método para actualizar el mensaje
  }
}
