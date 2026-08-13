import ScoreCompare from '../components/ScoreCompare';

export const metadata = {
  title: 'Score Comparison — MidiTrain',
  description: 'Generated MusicXML vs. reference MusicXML, notes only',
};

export default function ComparePage() {
  return <ScoreCompare />;
}
