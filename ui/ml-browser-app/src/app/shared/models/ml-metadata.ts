/**
 * ML Metadata Models
 * Based on JS_Pionera_Ontology for Machine Learning assets
 */

/**
 * Machine Learning metadata structure
 * These fields are specific to IA assets and follow the JS_Pionera_Ontology
 */
export interface MLMetadata {
  // ML Task and Classification
  task?: string[];              // e.g., ['Classification', 'Regression']
  subtask?: string[];           // e.g., ['Binary Classification', 'Multi-class']
  algorithm?: string[];         // e.g., ['Random Forest', 'Neural Network']
  
  // Technical Stack
  library?: string[];           // e.g., ['scikit-learn', 'TensorFlow']
  framework?: string[];         // e.g., ['PyTorch', 'Keras']
  software?: string[];          // e.g., ['Python 3.9', 'CUDA 11.2']
  
  // Data Format
  format?: string;              // e.g., 'pickle', 'h5', 'onnx', 'joblib'
  
  // Additional ML-specific properties
  metrics?: Record<string, number>;  // e.g., { accuracy: 0.95, f1Score: 0.92 }
  hyperparameters?: Record<string, unknown>;  // Model hyperparameters
  trainingData?: string;        // Reference to training dataset
  validationData?: string;      // Reference to validation dataset
}

/**
 * Asset types supported by the connector
 * Only ML model types
 */
export const ASSET_TYPES = {
  machineLearning: 'Machine learning',
  deepLearning: 'Deep learning'
} as const;

/**
 * Default asset type for IA assets
 */
export const DEFAULT_ASSET_TYPE = ASSET_TYPES.machineLearning;

/**
 * Common ML tasks from JS_Pionera_Ontology
 */
export const ML_TASKS = [
  'Classification',
  'Regression',
  'Clustering',
  'Dimensionality Reduction',
  'Natural Language Processing',
  'Computer Vision',
  'Reinforcement Learning',
  'Time Series Analysis'
] as const;

/**
 * Common ML algorithms
 */
export const ML_ALGORITHMS = [
  'Random Forest',
  'Neural Network',
  'Support Vector Machine',
  'Logistic Regression',
  'Decision Tree',
  'K-Means',
  'Gradient Boosting',
  'Convolutional Neural Network',
  'Recurrent Neural Network',
  'Transformer'
] as const;

/**
 * Common ML libraries
 */
export const ML_LIBRARIES = [
  'scikit-learn',
  'TensorFlow',
  'PyTorch',
  'Keras',
  'XGBoost',
  'LightGBM',
  'Pandas',
  'NumPy'
] as const;

/**
 * Common ML frameworks
 */
export const ML_FRAMEWORKS = [
  'TensorFlow',
  'PyTorch',
  'Keras',
  'JAX',
  'MXNet',
  'Caffe',
  'ONNX'
] as const;

/**
 * Common model formats
 */
export const ML_FORMATS = [
  'pickle',
  'joblib',
  'h5',
  'hdf5',
  'onnx',
  'pb',
  'pt',
  'pth',
  'safetensors',
  'json'
] as const;

