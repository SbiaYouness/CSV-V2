export interface ZipFileEntry {
  name: string;
  lei: string;
  date: string;
  size: number;
}

export interface ExcelFileEntry {
  name: string;
  size: number;
}

export interface AvailableFiles {
  excel_files: ExcelFileEntry[];
  zip_files: ZipFileEntry[];
  by_date: Record<string, ZipFileEntry[]>;
}

export interface BankResult {
  id?: string;
  bank: string;
  lei: string;
  matched: number;
  total: number;
  score: number;
  has_pdf: boolean;
  zip_name?: string;
  input_metrics?: number;
  pdf_metrics_found?: number;
  expected_metrics?: number;
  detail_rows?: number;
  parent_group?: string;
  relationship?: string;
  reports_with_parent?: boolean;
  reporting_context?: 'parent_group_reporting' | 'identical_to_parent';
  parent_data_available?: boolean;
  relationship_source?: string;
  relationship_source_url?: string;
}

export interface ReconciliationRow {
  Entité: string;
  LEI: string;
  Indicateur: string;
  'Valeur resultats': number | null;
  'Valeur PDF (EBA)': number | null;
  Ecart: number | null;
  'Ecart %': number | null;
  Statut: string;
  'Source PDF': string;
}

export type TransactionStatus = 'matched' | 'ecart' | 'mismatched' | 'pdf_only' | 'csv_only';

export interface Transaction {
  bank_id?: string;
  id?: string;
  date?: string;
  reference?: string;
  description?: string;
  amount?: number;
  status?: TransactionStatus | string;
  pdfAmount?: number;
  csvAmount?: number;
  difference?: number;
  entity?: string;
  lei?: string;
  indicator?: string;
  resultValue?: number;
  pdfValue?: number;
  sourcePdf?: string;
  // Batch reconcile columns
  Entité?: string;
  LEI?: string;
  Indicateur?: string;
  'Valeur resultats'?: number | null;
  'Valeur PDF (EBA)'?: number | null;
  Ecart?: number | null;
  'Ecart %'?: number | null;
  Statut?: string;
  'Source PDF'?: string;
}

export interface FileInfoMeta {
  id: string;
  name: string;
  size: number;
  type: 'pdf' | 'csv';
}

export interface ReconciliationResult {
  id: string;
  date: string;
  report_date?: string;
  output_file?: string;
  pdfFile: FileInfoMeta;
  csvFile: FileInfoMeta;
  complianceScore: number;
  summary: {
    matched: number;
    ecart: number;
    pdfOnly: number;
    csvOnly: number;
    total: number;
  };
  bank_results?: BankResult[];
  skipped_banks?: Array<{ bank: string; lei: string; reason: string }>;
  transactions: Transaction[];
  aiSynthesis: string;
  processingTime?: number;
}

export interface FileInfo {
  id: string;
  name: string;
  size: number;
  type: 'pdf' | 'csv';
  file: File;
}

export type ProcessingStep =
  | 'extraction_zip'
  | 'extraction_pdf'
  | 'lecture_excel'
  | 'correspondance'
  | 'anomalies'
  | 'rapport_ia';

export interface ProcessingState {
  currentStep: ProcessingStep;
  completedSteps: ProcessingStep[];
}

export type AppState =
  | { type: 'upload' }
  | { type: 'processing'; processing: ProcessingState }
  | { type: 'results'; result: ReconciliationResult };
