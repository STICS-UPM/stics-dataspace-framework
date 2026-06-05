/** Resolve RDF format for EDC management API `/validation/rdf_asset`. */
export function resolveRdfFormat(file: File | undefined): string {
  if (!file) {
    return 'turtle';
  }
  const mime = (file.type || '').toLowerCase();
  if (mime.includes('n3')) {
    return 'n3';
  }
  if (mime.includes('turtle')) {
    return 'turtle';
  }
  if (mime.includes('rdf+xml') || mime.includes('xml')) {
    return 'rdfxml';
  }
  if (mime.includes('ld+json') || mime.includes('jsonld')) {
    return 'jsonld';
  }
  if (mime.includes('n-triples') || mime.includes('ntriples')) {
    return 'ntriples';
  }

  const fileName = (file.name || '').toLowerCase();
  if (fileName.endsWith('.n3')) {
    return 'n3';
  }
  if (fileName.endsWith('.ttl')) {
    return 'turtle';
  }
  if (fileName.endsWith('.rdf') || fileName.endsWith('.xml') || fileName.endsWith('.owl')) {
    return 'rdfxml';
  }
  if (fileName.endsWith('.jsonld')) {
    return 'jsonld';
  }
  if (fileName.endsWith('.nt')) {
    return 'ntriples';
  }

  return 'turtle';
}

const SEMANTIC_EXTENSIONS = ['.ttl', '.n3', '.rdf', '.owl', '.xml', '.jsonld', '.nt'];
const SEMANTIC_MIME_HINTS = ['turtle', 'n3', 'rdf', 'jsonld', 'n-triples', 'ntriples'];

/** Lightweight semantic file check without rdflib (extension/MIME heuristics). */
export function isLikelySemanticRdfFile(file: File | undefined): boolean {
  if (!file) {
    return false;
  }
  const name = (file.name || '').toLowerCase();
  if (SEMANTIC_EXTENSIONS.some(ext => name.endsWith(ext))) {
    return true;
  }
  const mime = (file.type || '').toLowerCase();
  return SEMANTIC_MIME_HINTS.some(hint => mime.includes(hint));
}
