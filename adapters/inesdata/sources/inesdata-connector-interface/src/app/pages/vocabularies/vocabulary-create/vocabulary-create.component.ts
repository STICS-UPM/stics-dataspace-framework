import { Component,EventEmitter, Output, QueryList, ViewChildren} from '@angular/core';
import { Vocabulary } from "../../../shared/models/vocabulary";
import { NotificationService } from 'src/app/shared/services/notification.service';
import { CATEGORIES } from 'src/app/shared/utils/app.constants';
import { VocabularyService } from 'src/app/shared/services/vocabulary.service';
import { Router } from '@angular/router';
import { BehaviorSubject } from 'rxjs';
import { NgModel } from '@angular/forms';

@Component({
  selector: 'app-vocabulary-create',
  templateUrl: './vocabulary-create.component.html',
  styleUrls: ['./vocabulary-create.component.scss']
})
export class VocabularyCreateComponent {

  private fetch$ = new BehaviorSubject(null);
  // Default asset properties
  id: string = '';
  name: string = '';
  category: string = '';
  jsonSchema: string = '';
  categories = Object.entries(CATEGORIES);
  @Output() vocabularyChange: EventEmitter<any> = new EventEmitter<any>();

  @ViewChildren(NgModel) formControls: QueryList<NgModel>;

  constructor(private vocabularyService: VocabularyService,
    private notificationService: NotificationService, private router: Router) {
  }

  async onSave() {
    this.formControls.toArray().forEach(control => {
      control.control.markAsTouched();
    });

    // Check whether the asset is valid
    if (!this.checkRequiredFields()) {
      this.notificationService.showError("Review the form fields");
      return;
    }
    if(!this.checkJsonField()){
      this.notificationService.showError("Schema field must be a JSON");
      return;
    }

    // Create Vocabulary
    const vocabulary: Vocabulary = {
      "@id": this.id,
      name: this.name,
      category: this.category,
      jsonSchema: this.jsonSchema
    };

    this.createVocabulary(vocabulary);

  }

  /**
   * Checks the required fields
   *
   * @returns true if required fields have been filled
   */
  private checkRequiredFields(): boolean {
    if (!this.id || !this.name || !this.jsonSchema || !this.category) {
      return false;
    }
    return true;
  }

  private checkJsonField(): boolean {
    try {
      JSON.parse(this.jsonSchema);
    } catch (e) {
      return false;
    }

    return true;
  }

  private createVocabulary(vocabulary: Vocabulary){
    this.vocabularyService.createVocabulary(vocabulary).subscribe({
      next: () => this.fetch$.next(null),
      error: err => this.showError(err, "This vocabulary cannot be created"),
      complete: () => {
        this.notificationService.showInfo("Successfully created");
        this.navigateToVocabularies()
      }
    })
  }


  private showError(error: string, errorMessage: string) {
    this.notificationService.showError(errorMessage);
    console.error(error);
  }

  navigateToVocabularies(){
    this.router.navigate(['/vocabularies'])
  }
}
