/**
 * Vocabulary interface for JSON-LD schemas
 * Used to load dynamic options for ML metadata fields
 */
export interface Vocabulary {
  '@id': string;
  name: string;
  category: string;
  jsonSchema: string;
  connectorId?: string;
}

/**
 * Vocabulary category types
 */
export type VocabularyCategory = 'default' | 'Machine learning' | 'Deep learning';
