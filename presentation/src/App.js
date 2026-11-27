import React, { useEffect, useState } from 'react';
import { ChevronLeft, ChevronRight, ArrowRight } from 'lucide-react';

// WP2 meeting, ~5 min: DEP DLM usage reporter and the WP4 credit management
// milestone (10 December). Speaker notes: SPEAKER_NOTES.md.

const slides = [
  {
    type: 'content',
    title: 'Why a Usage Reporter',
    content: [
      {
        heading: 'Requirement',
        text: 'WP4 credit management needs data-transfer usage per DEP project and scientific use case, in ARGO Accounting'
      },
      {
        heading: 'Gap',
        text: 'Rucio knows every transfer but nothing about projects or credits; ARGO knows projects but not transfers'
      },
      {
        heading: 'Agreed with GRNET',
        text: 'Bytes per calendar day (UTC) per project and use case (group_id) · one metric definition under CERN → CERN-Rucio · each day reported once'
      }
    ]
  },

  {
    type: 'flow',
    title: 'How It Works',
    steps: [
      { label: 'CronJob', detail: '01:00 UTC, yesterday' },
      { label: 'Rucio', detail: 'Finished transfers + account attributes' },
      { label: 'Aggregate', detail: 'Bytes per day, project, group_id' },
      { label: 'ARGO', detail: 'Look up, POST if missing, never PATCH' }
    ],
    facts: [
      'Unmapped accounts are excluded and flagged, never guessed',
      'Re-run or backfill any day; exit codes for alerting',
      'Service-to-service tokens: one ARGO client per accounting project',
      'Status: running in the testbed in dry-run; 10 December: mock data for RI-SCALE_ENES against ARGO devel'
    ]
  },

  {
    type: 'evolution',
    title: 'From Daily Batch to Real-Time Events',
    today: {
      heading: 'Today: daily batch',
      items: ['Matches daily accounting', 'Idempotent, re-runnable per day', 'No message broker to run']
    },
    later: {
      heading: 'If requirements change',
      items: ['Near-real-time balances or credit checks before transfers', 'Rucio Hermes → ActiveMQ transfer-done events', 'A listener reports usage as transfers finish']
    },
    options: [
      { name: 'A: listener only', text: 'Replaces the batch; lost events mean lost usage' },
      { name: 'B: listener + daily job', text: 'Provisional usage in real time, today\'s job as the authoritative reconciliation' }
    ],
    open: 'Open with WP4: group_id and data ownership (per DEP or per use case), and whether anything faster than daily is needed'
  }
];

function List({ items, color }) {
  return (
    <ul className="space-y-3">
      {items.map((item, idx) => (
        <li key={idx} className="text-lg text-gray-700 flex items-start">
          <span className={`${color} mr-3`}>▸</span>
          <span>{item}</span>
        </li>
      ))}
    </ul>
  );
}

function App() {
  const [currentSlide, setCurrentSlide] = useState(0);
  const nextSlide = () => setCurrentSlide((i) => Math.min(i + 1, slides.length - 1));
  const prevSlide = () => setCurrentSlide((i) => Math.max(i - 1, 0));

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'ArrowRight' || e.key === 'PageDown') nextSlide();
      if (e.key === 'ArrowLeft' || e.key === 'PageUp') prevSlide();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const slide = slides[currentSlide];

  return (
    <div className="w-full h-screen bg-white flex flex-col relative">
      {/* Header with logos */}
      <div className="absolute top-0 left-0 right-0 flex justify-between items-start p-6 z-10">
        <img src="/assets/ri-scale-logo-top-left.png" alt="RI-SCALE Logo" className="h-16 w-auto" />
        <img src="/assets/logo-top-right.png" alt="Decorative graphics" className="h-20 w-auto" />
      </div>

      {/* Footer with EU funding logo */}
      <div className="absolute bottom-14 left-0 p-6 z-10">
        <img src="/assets/funded-bottom-left.png" alt="Funded by the European Union" className="h-8 w-auto" />
      </div>

      {/* Slide Content */}
      <div className="flex-1 flex items-center justify-center p-8 pt-24 pb-20 overflow-y-auto">
        <div className="w-full max-w-5xl slide-content">
          <p className="text-sm uppercase tracking-wide text-gray-500 mb-2">
            DEP DLM Usage Reporter · WP4 credit management
          </p>

          {slide.type === 'content' && (
            <div className="space-y-6">
              <h2 className="text-4xl font-bold text-gray-900 mb-8">{slide.title}</h2>
              {slide.content.map((item) => (
                <div key={item.heading} className="bg-gray-50 p-6 rounded-lg border border-gray-200">
                  <h3 className="text-2xl font-semibold text-orange-400 mb-3">{item.heading}</h3>
                  <p className="text-lg text-gray-700">{item.text}</p>
                </div>
              ))}
            </div>
          )}

          {slide.type === 'flow' && (
            <div className="space-y-8">
              <h2 className="text-4xl font-bold text-gray-900 mb-8">{slide.title}</h2>
              <div className="flex items-stretch gap-2">
                {slide.steps.map((step, idx) => (
                  <React.Fragment key={step.label}>
                    <div className="flex-1 bg-gray-50 p-4 rounded-lg border border-gray-200 text-center">
                      <h3 className="text-xl font-semibold text-orange-400 mb-2">{step.label}</h3>
                      <p className="text-base text-gray-700">{step.detail}</p>
                    </div>
                    {idx < slide.steps.length - 1 && (
                      <div className="flex items-center text-orange-400">
                        <ArrowRight size={28} />
                      </div>
                    )}
                  </React.Fragment>
                ))}
              </div>
              <List items={slide.facts} color="text-orange-500" />
            </div>
          )}

          {slide.type === 'evolution' && (
            <div className="space-y-6">
              <h2 className="text-4xl font-bold text-gray-900 mb-6">{slide.title}</h2>
              <div className="grid grid-cols-2 gap-8">
                <div className="bg-green-50 p-6 rounded-lg border border-green-200">
                  <h3 className="text-2xl font-semibold text-green-700 mb-4">{slide.today.heading}</h3>
                  <List items={slide.today.items} color="text-green-500" />
                </div>
                <div className="bg-amber-50 p-6 rounded-lg border border-amber-200">
                  <h3 className="text-2xl font-semibold text-amber-700 mb-4">{slide.later.heading}</h3>
                  <List items={slide.later.items} color="text-amber-500" />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-8">
                {slide.options.map((opt) => (
                  <div key={opt.name} className="bg-gray-50 p-4 rounded-lg border border-gray-200">
                    <h3 className="text-xl font-semibold text-orange-400 mb-1">{opt.name}</h3>
                    <p className="text-lg text-gray-700">{opt.text}</p>
                  </div>
                ))}
              </div>
              <p className="text-lg text-gray-600 italic">{slide.open}</p>
            </div>
          )}
        </div>
      </div>

      {/* Navigation */}
      <div className="bg-gray-100 border-t border-gray-300 p-4 flex items-center justify-between relative z-20">
        <button
          onClick={prevSlide}
          disabled={currentSlide === 0}
          className="flex items-center gap-2 px-4 py-2 bg-orange-400 text-white rounded-lg disabled:opacity-30 disabled:cursor-not-allowed hover:bg-orange-700 transition"
        >
          <ChevronLeft size={20} />
          Previous
        </button>
        <div className="text-gray-600">Slide {currentSlide + 1} of {slides.length}</div>
        <button
          onClick={nextSlide}
          disabled={currentSlide === slides.length - 1}
          className="flex items-center gap-2 px-4 py-2 bg-orange-400 text-white rounded-lg disabled:opacity-30 disabled:cursor-not-allowed hover:bg-orange-700 transition"
        >
          Next
          <ChevronRight size={20} />
        </button>
      </div>
    </div>
  );
}

export default App;