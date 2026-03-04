import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, of } from 'rxjs';
import { map, catchError, shareReplay } from 'rxjs/operators';

/**
 * Vocabulary options loaded from JSON-LD
 */
export interface VocabularyOptions {
  task: string[];
  subtask: string[];
  algorithm: string[];
  library: string[];
  framework: string[];
  software: string[];
  format: string[];
}

/**
 * VocabularyService
 * 
 * Loads ML metadata vocabulary options from JS_Pionera_Ontology JSON-LD
 */
@Injectable({
  providedIn: 'root'
})
export class VocabularyService {
  private http = inject(HttpClient);
  
  private vocabularyCache$?: Observable<VocabularyOptions>;

  /**
   * Get vocabulary options from JS_Pionera_Ontology
   */
  getVocabularyOptions(): Observable<VocabularyOptions> {
    if (!this.vocabularyCache$) {
      this.vocabularyCache$ = this.http.get<any>('/assets/vocabularies/js-pionera-ontology.json').pipe(
        map((data) => ({
          task: data.task || [],
          subtask: data.subtask || [],
          algorithm: data.algorithm || [],
          library: data.library || [],
          framework: data.framework || [],
          software: data.software || [],
          format: data.format || []
        })),
        catchError((error) => {
          console.error('Error loading vocabulary:', error);
          // Return default empty values if loading fails
          return of({
            task: [],
            subtask: [],
            algorithm: [],
            library: [],
            framework: [],
            software: [],
            format: []
          });
        }),
        shareReplay(1)
      );
    }
    
    return this.vocabularyCache$;
  }

  /**
   * Get specific field options
   */
  getFieldOptions(fieldName: keyof VocabularyOptions): Observable<string[]> {
    return this.getVocabularyOptions().pipe(
      map((options) => options[fieldName] || [])
    );
  }
}
