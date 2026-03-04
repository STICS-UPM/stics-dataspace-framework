import { Injectable, inject } from '@angular/core';
import { MatSnackBar, MatSnackBarConfig, MatSnackBarDismiss } from "@angular/material/snack-bar";
import { Observable } from "rxjs";

@Injectable({
  providedIn: 'root'
})
export class NotificationService {
  private readonly snackBar = inject(MatSnackBar);

  /**
   * Shows a snackbar message with a particular text
   * @param message The text to display
   * @param action A string specifying the text on an action button. If left out, no action button is shown.
   * If left out, and onAction is specified, "Done" is used as default.
   * @param onAction A callback that is invoked when the action button is clicked.
   */
  public showWarning(message: string, action?: string, onAction?: () => unknown): Observable<MatSnackBarDismiss> {
    if (!action && onAction) {
      action = "Done";
    }
    const config: MatSnackBarConfig = {
      duration: onAction ? 5000 : 3000, // no auto-cancel if an action was specified
      verticalPosition: "top",
      politeness: "polite",
      horizontalPosition: "end",
      panelClass: ["snackbar-warning-style"] //see styles.scss
    }
    const ref = this.snackBar.open(message, action, config);

    if (onAction) {
      ref.onAction().subscribe(() => onAction());
    }

    return ref.afterDismissed()
  }

  /**
   * Shows a snackbar message with a particular text
   * @param message The text to display
   * @param action A string specifying the text on an action button. If left out, no action button is shown.
   * If left out, and onAction is specified, "Done" is used as default.
   * @param onAction A callback that is invoked when the action button is clicked.
   */
  public showInfo(message: string, action?: string, onAction?: () => unknown): Observable<MatSnackBarDismiss> {
    if (!action && onAction) {
      action = "Done";
    }
    const config: MatSnackBarConfig = {
      duration: onAction ? 5000 : 3000, // no auto-cancel if an action was specified
      verticalPosition: "top",
      politeness: "polite",
      horizontalPosition: "end",
      panelClass: ["snackbar-info-style"] //see styles.scss
    }
    const ref = this.snackBar.open(message, action, config);

    if (onAction) {
      ref.onAction().subscribe(() => onAction());
    }

    return ref.afterDismissed()
  }

  public showError(message: string): Observable<MatSnackBarDismiss> {
    const config: MatSnackBarConfig = {
      duration: 5000, // no auto-cancel if an action was specified
      verticalPosition: "top",
      politeness: "assertive",
      horizontalPosition: "end",
      panelClass: ["snackbar-error-style"] //see styles.scss
    }

    const ref = this.snackBar.open(message, undefined, config);
    return ref.afterDismissed();
  }

  /**
   * Shows a success snackbar message
   * @param message The text to display
   * @param action Optional action button text
   * @param onAction Optional callback when action button is clicked
   */
  public showSuccess(message: string, action?: string, onAction?: () => unknown): Observable<MatSnackBarDismiss> {
    if (!action && onAction) {
      action = "Done";
    }
    const config: MatSnackBarConfig = {
      duration: onAction ? 5000 : 3000,
      verticalPosition: "top",
      politeness: "polite",
      horizontalPosition: "end",
      panelClass: ["snackbar-success-style"] //see styles.scss
    }
    const ref = this.snackBar.open(message, action, config);

    if (onAction) {
      ref.onAction().subscribe(() => onAction());
    }

    return ref.afterDismissed();
  }
}
