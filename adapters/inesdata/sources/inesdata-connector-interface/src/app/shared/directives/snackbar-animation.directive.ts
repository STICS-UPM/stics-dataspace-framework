import { Directive, ElementRef, Renderer2, AfterViewInit, OnDestroy } from '@angular/core';
import { MatSnackBarRef } from '@angular/material/snack-bar';

@Directive({
  selector: '[appSnackBarAnimation]'
})
export class SnackBarAnimationDirective implements AfterViewInit, OnDestroy {

  constructor(private snackBarRef: MatSnackBarRef<any>, private el: ElementRef, private renderer: Renderer2) {}

  ngAfterViewInit(): void {
    // Añadir la animación de entrada cuando se abre el Snackbar
    this.renderer.addClass(this.el.nativeElement, 'snackbar-animation-in');

    // Configuramos el evento de dismissal para que ejecute la animación de salida
    this.snackBarRef.afterDismissed().subscribe(() => {
      this.renderer.addClass(this.el.nativeElement, 'snackbar-animation-out');
    });
  }

  ngOnDestroy(): void {
    // Limpiamos las clases cuando el Snackbar se destruya
    this.renderer.removeClass(this.el.nativeElement, 'snackbar-animation-in');
    this.renderer.removeClass(this.el.nativeElement, 'snackbar-animation-out');
  }
}
