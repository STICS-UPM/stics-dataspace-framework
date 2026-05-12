import { Component, OnInit } from '@angular/core';
import { BehaviorSubject } from 'rxjs';
import { MatDialog } from '@angular/material/dialog';
import { ConfirmationDialogComponent, ConfirmDialogModel } from "../../../shared/components/confirmation-dialog/confirmation-dialog.component";
import { NotificationService } from "../../../shared/services/notification.service";
import { VocabularyService } from 'src/app/shared/services/vocabulary.service';
import { Vocabulary } from 'src/app/shared/models/vocabulary';
import { environment } from 'src/environments/environment';
import { JsonDialogData } from '../../json-dialog/json-dialog/json-dialog.data';
import { JsonDialogComponent } from '../../json-dialog/json-dialog/json-dialog.component';
import { Router } from '@angular/router';

@Component({
  selector: 'app-vocabulary-viewer',
  templateUrl: './vocabulary-viewer.component.html',
  styleUrls: ['./vocabulary-viewer.component.scss']
})
export class VocabularyViewerComponent implements OnInit {

  vocabularies: Vocabulary[] = [];

  isTransferring = false;
  private fetch$ = new BehaviorSubject(null);
  PARTICIPANT_ID = `${environment.runtime.participantId}`;

  constructor(private vocabularyService: VocabularyService,
    private notificationService: NotificationService,
    private readonly dialog: MatDialog,
    private router: Router) {
  }

  private showError(error: string, errorMessage: string) {
    this.notificationService.showError(errorMessage);
    console.error(error);
  }

  ngOnInit(): void {
    this.loadVocabularies();
  }

  isBusy() {
    return this.isTransferring;
  }

  onDelete(vocabulary: Vocabulary) {
    const dialogData = ConfirmDialogModel.forDelete("vocabulary", `"${vocabulary['@id']}"`)
    const ref = this.dialog.open(ConfirmationDialogComponent, { maxWidth: "30%", data: dialogData });

    ref.afterClosed().subscribe({
      next: res => {
        if (res) {
          this.vocabularyService.removeVocabulary(vocabulary['@id']).subscribe({
            next: () => this.fetch$.next(null),
            error: err => this.showError(err, "This vocabulary cannot be deleted"),
            complete: () => {
              this.loadVocabularies();
              this.notificationService.showInfo("Successfully deleted");
            }
          });
        }
      }
    });
  }

  onCreate() {
    this.router.navigate(['vocabularies/create'])
  }

  loadVocabularies() {

    this.vocabularyService.requestSharedVocabularies()
      .subscribe(results => {
        this.vocabularies = results;
      });
  }

  viewSchema(title: string, schema: any) {
    try {
      const data: JsonDialogData = {
        title: title,
        subtitle: 'JSON Schema',
        icon: 'book',
        objectForJson: JSON.parse(schema)
      };

      this.dialog.open(JsonDialogComponent, {data});
    } catch (error) {
      this.notificationService.showError("Error parsing JSON schema");
    }
  }
}
