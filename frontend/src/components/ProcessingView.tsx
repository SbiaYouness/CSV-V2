import { ProcessingStep, ProcessingState } from '../types';

interface ProcessingViewProps {
  state: ProcessingState;
}

const STEPS: { id: ProcessingStep; label: string }[] = [
  { id: 'extraction_zip', label: 'Décompression des archives ZIP' },
  { id: 'extraction_pdf', label: 'Extraction PDF / OCR des rapports' },
  { id: 'lecture_excel', label: 'Lecture du classeur de résultats' },
  { id: 'correspondance', label: 'Correspondance banques ↔ LEI' },
  { id: 'anomalies', label: 'Détection des écarts et anomalies' },
  { id: 'rapport_ia', label: 'Génération du rapport IA' },
];

export function ProcessingView({ state }: ProcessingViewProps) {
  const stepOrder = STEPS.map((s) => s.id);
  const currentIndex = stepOrder.indexOf(state.currentStep);

  return (
    <div className="h-screen flex flex-col items-center justify-center p-8">
      <div className="w-full max-w-lg">
        <div className="text-center mb-12">
          <h2 className="text-xl font-medium text-gray-200 mb-2">
            Analyse en cours
          </h2>
          <p className="text-sm text-gray-500">
            Veuillez patienter pendant le traitement
          </p>
        </div>

        <div className="space-y-1">
          {STEPS.map((step) => {
            const isCompleted = state.completedSteps.includes(step.id);
            const isInProgress = step.id === state.currentStep;
            const isAiStep = step.id === 'rapport_ia';

            return (
              <div
                key={step.id}
                className={`
                  flex items-center gap-4 p-4 rounded-lg
                  transition-all duration-300
                  ${isCompleted || isInProgress
                    ? 'bg-background-lighter'
                    : 'bg-transparent'}
                `}
              >
                <div className="flex-shrink-0 w-6 h-6">
                  {isCompleted ? (
                    <div className="w-6 h-6 rounded-full bg-emerald-900/50 flex items-center justify-center animate-check-pop">
                      <svg className="w-3.5 h-3.5 text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                      </svg>
                    </div>
                  ) : isInProgress ? (
                    <div className="relative w-6 h-6">
                      {isAiStep && (
                        <div className="absolute inset-0 rounded-full bg-gold/20 animate-pulse-subtle" />
                      )}
                      <div className={`
                        absolute inset-0 rounded-full border-2
                        ${isAiStep ? 'border-gold' : 'border-slate-600'}
                        ${isAiStep ? 'opacity-100' : 'opacity-50'}
                      `}>
                        <div
                          className="absolute inset-0 rounded-full border-2 border-t-gold"
                          style={{
                            animation: 'spin 1s linear infinite',
                          }}
                        />
                      </div>
                      <style>{`
                        @keyframes spin {
                          from { transform: rotate(0deg); }
                          to { transform: rotate(360deg); }
                        }
                      `}</style>
                    </div>
                  ) : (
                    <div className="w-6 h-6 rounded-full border-2 border-slate-800 opacity-50" />
                  )}
                </div>

                <span
                  className={`
                    text-sm transition-colors duration-200
                    ${isCompleted ? 'text-gray-400' : ''}
                    ${isInProgress ? (isAiStep ? 'text-gold' : 'text-gray-200') : ''}
                    ${!isCompleted && !isInProgress ? 'text-gray-600' : ''}
                  `}
                >
                  {step.label}
                </span>
              </div>
            );
          })}
        </div>

        <div className="mt-12 h-1 bg-background-lighter rounded-full overflow-hidden">
          <div
            className="h-full bg-gold transition-all duration-500 ease-out"
            style={{
              width: `${((currentIndex + (state.completedSteps.length === STEPS.length ? 1 : 0.5)) / STEPS.length) * 100}%`,
            }}
          />
        </div>
      </div>
    </div>
  );
}
