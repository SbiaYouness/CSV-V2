import { ReconciliationResult, Transaction } from './types';

const generateTransactions = (): Transaction[] => {
  const transactions: Transaction[] = [
    {
      id: '1',
      date: '2024-01-15',
      reference: 'VIR-2024-0115',
      description: 'Virement client SARL Martin',
      amount: 2450.0,
      status: 'matched',
      pdfAmount: 2450.0,
      csvAmount: 2450.0,
    },
    {
      id: '2',
      date: '2024-01-16',
      reference: 'CHQ-5521',
      description: 'Cheque fournisseur Dubois',
      amount: -892.5,
      status: 'matched',
      pdfAmount: -892.5,
      csvAmount: -892.5,
    },
    {
      id: '3',
      date: '2024-01-17',
      reference: 'VIR-2024-0117',
      description: 'Paiement loyer janvier',
      amount: -1800.0,
      status: 'ecart',
      pdfAmount: -1800.0,
      csvAmount: -1750.0,
      difference: -50.0,
    },
    {
      id: '4',
      date: '2024-01-18',
      reference: 'PRE-EDF-0118',
      description: 'Prelevement EDF',
      amount: -234.67,
      status: 'matched',
      pdfAmount: -234.67,
      csvAmount: -234.67,
    },
    {
      id: '5',
      date: '2024-01-19',
      reference: 'VIR-SAL-0119',
      description: 'Salaire employe Dupont',
      amount: -3200.0,
      status: 'matched',
      pdfAmount: -3200.0,
      csvAmount: -3200.0,
    },
    {
      id: '6',
      date: '2024-01-20',
      reference: 'CB-0120-8562',
      description: 'Carte bureau tabac',
      amount: -45.8,
      status: 'pdf_only',
      pdfAmount: -45.8,
    },
    {
      id: '7',
      date: '2024-01-21',
      reference: 'FAC-2024-0089',
      description: 'Facture client LEGRAND',
      amount: 5670.0,
      status: 'csv_only',
      csvAmount: 5670.0,
    },
    {
      id: '8',
      date: '2024-01-22',
      reference: 'VIR-2024-0122',
      description: 'Remboursement assurance',
      amount: 1250.0,
      status: 'matched',
      pdfAmount: 1250.0,
      csvAmount: 1250.0,
    },
    {
      id: '9',
      date: '2024-01-23',
      reference: 'PRE-ORANGE-0123',
      description: 'Abonnement telecom',
      amount: -89.9,
      status: 'ecart',
      pdfAmount: -89.9,
      csvAmount: -84.9,
      difference: -5.0,
    },
    {
      id: '10',
      date: '2024-01-24',
      reference: 'VIR-2024-0124',
      description: 'Paiement client PETIT',
      amount: 1890.0,
      status: 'matched',
      pdfAmount: 1890.0,
      csvAmount: 1890.0,
    },
    {
      id: '11',
      date: '2024-01-25',
      reference: 'CHQ-5522',
      description: 'Fourniture bureau',
      amount: -156.4,
      status: 'pdf_only',
      pdfAmount: -156.4,
    },
    {
      id: '12',
      date: '2024-01-26',
      reference: 'VIR-2024-0126',
      description: 'Subvention regionale',
      amount: 5000.0,
      status: 'matched',
      pdfAmount: 5000.0,
      csvAmount: 5000.0,
    },
    {
      id: '13',
      date: '2024-01-27',
      reference: 'PRE-LOCI-0127',
      description: 'Prelevement loyer commercial',
      amount: -2500.0,
      status: 'matched',
      pdfAmount: -2500.0,
      csvAmount: -2500.0,
    },
    {
      id: '14',
      date: '2024-01-28',
      reference: 'FAC-2024-0095',
      description: 'Prestation conseil MARC',
      amount: 3400.0,
      status: 'csv_only',
      csvAmount: 3400.0,
    },
    {
      id: '15',
      date: '2024-01-29',
      reference: 'VIR-2024-0129',
      description: 'Virement client MOREAU',
      amount: 2100.0,
      status: 'matched',
      pdfAmount: 2100.0,
      csvAmount: 2100.0,
    },
  ];

  return transactions;
};

export const generateMockResult = (
  pdfName: string,
  csvName: string
): ReconciliationResult => {
  const transactions = generateTransactions();

  const matched = transactions.filter((t) => t.status === 'matched').length;
  const ecart = transactions.filter((t) => t.status === 'ecart').length;
  const pdfOnly = transactions.filter((t) => t.status === 'pdf_only').length;
  const csvOnly = transactions.filter((t) => t.status === 'csv_only').length;

  const complianceScore = Math.round(
    ((matched / transactions.length) * 100 * 0.7) +
      (((transactions.length - ecart) / transactions.length) * 100 * 0.3)
  );

  return {
    id: `result-${Date.now()}`,
    date: new Date().toISOString(),
    pdfFile: {
      id: `file-${Date.now()}-pdf`,
      name: pdfName,
      size: 245780,
      type: 'pdf',
    },
    csvFile: {
      id: `file-${Date.now()}-csv`,
      name: csvName,
      size: 45678,
      type: 'csv',
    },
    complianceScore,
    summary: {
      matched,
      ecart,
      pdfOnly,
      csvOnly,
      total: transactions.length,
    },
    transactions,
    aiSynthesis: `Le rapprochement bancaire pour la periode analysee presente un score de conformite de ${complianceScore}%, ce qui indique une coherence globale satisfaisante entre le releve bancaire et le registre comptable.

Sur les ${transactions.length} transactions analysees:
- ${matched} transactions correspondent parfaitement entre les deux documents
- ${ecart} ecart(s) de montant ont ete identifies, representant des divergences mineures a verifier
- ${pdfOnly} transaction(s) presente(s) uniquement sur le releve bancaire
- ${csvOnly} transaction(s) presente(s) uniquement sur le registre comptable

Les ecarts detectes semblent correspondre a des differences de montant mineures, potentiellement liees a des frais annexes ou des ajustements comptables.

Recommandations:
1. Verifier les 2 transactions presentant des ecarts de montant
2. Controler les ${pdfOnly + csvOnly} transactions unilaterales pour identifier les omissions potentielles
3. Documenter les ajustements necessaires dans le registre comptable

L'audit de conformite recommande une verification manuelle des elements identifies avant cloture comptable.`,
  };
};

export const generateHistory = (): ReconciliationResult[] => {
  return [
    {
      id: 'hist-1',
      date: '2024-01-20T10:30:00Z',
      pdfFile: { id: 'hf1', name: 'releve_janvier_2024.pdf', size: 234567, type: 'pdf' },
      csvFile: { id: 'hf2', name: 'registre_Q1_2024.csv', size: 45678, type: 'csv' },
      complianceScore: 94,
      summary: { matched: 12, ecart: 1, pdfOnly: 2, csvOnly: 1, total: 16 },
      transactions: [],
      aiSynthesis: '...',
    },
    {
      id: 'hist-2',
      date: '2024-01-15T14:22:00Z',
      pdfFile: { id: 'hf3', name: 'releve_decembre_2023.pdf', size: 198234, type: 'pdf' },
      csvFile: { id: 'hf4', name: 'grand_livre_2023.csv', size: 56789, type: 'csv' },
      complianceScore: 87,
      summary: { matched: 18, ecart: 3, pdfOnly: 4, csvOnly: 2, total: 27 },
      transactions: [],
      aiSynthesis: '...',
    },
    {
      id: 'hist-3',
      date: '2024-01-10T09:15:00Z',
      pdfFile: { id: 'hf5', name: 'excerpt_bnp_janv.pdf', size: 145678, type: 'pdf' },
      csvFile: { id: 'hf6', name: 'comptabilite_janv.csv', size: 34567, type: 'csv' },
      complianceScore: 98,
      summary: { matched: 24, ecart: 0, pdfOnly: 1, csvOnly: 0, total: 25 },
      transactions: [],
      aiSynthesis: '...',
    },
  ];
};
