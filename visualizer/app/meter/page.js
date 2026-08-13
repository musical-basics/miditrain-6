import MeterDiagnostic from '../components/MeterDiagnostic';

export const metadata = {
  title: 'Meter Diagnostic — MidiTrain',
  description: 'Which metrical level did each engine lock onto, and why?',
};

export default function MeterPage() {
  return <MeterDiagnostic />;
}
