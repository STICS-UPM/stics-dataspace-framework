import { Injectable } from "@angular/core";
import * as $rdf from "rdflib";

@Injectable({
  providedIn: "root",
})
export class SemanticFileValidatorService {

  private readonly FORMATS = [
    "text/turtle",
    "application/rdf+xml",
    "application/ld+json",
    "text/n3"
  ];

  private readonly BASE_IRI = "urn:semantic-file:";

  constructor() {}

  async isASemanticFile(file: File): Promise<boolean> {
    try {
      const text = await file.text();

      for (const format of this.FORMATS) {
        try {
          const store = $rdf.graph();
          $rdf.parse(text, store, this.BASE_IRI, format);
          return true;
        } catch (e) {
          // Try the next RDF serialization supported by rdflib.
        }
      }

      return false;

    } catch {
      return false;
    }
  }
}
